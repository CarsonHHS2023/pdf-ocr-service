"""Production TXT ingestion through retained source -> LLM structure -> Reader v2 canonical content."""
from __future__ import annotations

import logging
import sqlite3
import sys
import uuid
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.database import SessionLocal
from app.models import Document
from app.processing.txt.analyzer_client import (
    OpenAICompatibleTxtAnalyzerConfig,
    OpenAICompatibleTxtStructureAnalyzer,
    TxtStructureAnalyzerClientError,
)
from app.processing.txt.canonicalization import (
    RetainedTxtCanonicalizationRequest,
    TxtCanonicalizationError,
    TxtCanonicalizationService,
)
from app.storage.dependencies import get_storage_provider

logger = logging.getLogger("uvicorn.error")


class TxtIngestionConfigurationError(RuntimeError):
    """Raised when production TXT structure analysis is not configured."""


@dataclass(frozen=True, slots=True)
class TxtIngestionIds:
    processing_run_ref: str


def _diagnostic(event: str, **fields: object) -> None:
    payload = " ".join(f"{name}={value}" for name, value in fields.items())
    message = f"{event} {payload}".rstrip()
    logger.info(message)
    print(message, file=sys.stderr, flush=True)


def new_txt_ingestion_ids() -> TxtIngestionIds:
    return TxtIngestionIds(processing_run_ref=f"txt-ingest-{uuid.uuid4().hex}")


def _resolved_txt_structure_api_key() -> str:
    """Resolve a TXT-specific key first, then the existing shared OpenAI credential."""
    txt_key = (settings.txt_structure_api_key or "").strip()
    if txt_key:
        return txt_key
    return (settings.pdf_structure_refinement_openai_api_key or "").strip()


def build_production_txt_structure_analyzer() -> OpenAICompatibleTxtStructureAnalyzer:
    base_url = (settings.txt_structure_api_base_url or "").strip()
    api_key = _resolved_txt_structure_api_key()
    model = (settings.txt_structure_model or "").strip()
    missing = [
        name
        for value, name in (
            (base_url, "ATLAS_TXT_STRUCTURE_API_BASE_URL"),
            (api_key, "ATLAS_TXT_STRUCTURE_API_KEY or PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY"),
            (model, "ATLAS_TXT_STRUCTURE_MODEL"),
        )
        if not value
    ]
    if missing:
        raise TxtIngestionConfigurationError(
            "TXT structure analysis is not configured: " + ", ".join(missing)
        )
    return OpenAICompatibleTxtStructureAnalyzer(
        OpenAICompatibleTxtAnalyzerConfig(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=settings.txt_structure_timeout_seconds,
            temperature=settings.txt_structure_temperature,
            max_attempts=settings.txt_structure_max_attempts,
            retry_backoff_seconds=settings.txt_structure_retry_backoff_seconds,
        )
    )


def _set_document_terminal_state(
    document_id: str,
    *,
    status: str,
    error_message: str | None,
) -> None:
    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if document is None:
            return
        document.status = status
        document.error_message = error_message
        document.original_file_path = None
        document.processed_file_path = None
        db.commit()
        _diagnostic(
            "TXT_DOCUMENT_STATE_UPDATED",
            document_id=document_id,
            status=status,
            has_error=bool(error_message),
        )
    except Exception:
        db.rollback()
        logger.exception("Could not update TXT ingestion terminal state document_id=%s", document_id)
    finally:
        db.close()


def _exception_chain(exc: BaseException):
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        cause = current.__cause__
        current = cause if cause is not None else current.__context__


def _provider_failure_message(exc: TxtStructureAnalyzerClientError) -> str:
    status = exc.status_code
    if status in {401, 403}:
        return "TXT structure analysis provider authentication failed"
    if status == 404:
        return "TXT structure analysis model or endpoint was not found"
    if status == 429:
        return "TXT structure analysis provider rate limit exceeded"
    if status is not None and status >= 500:
        return "TXT structure analysis provider is temporarily unavailable"
    if exc.stage in {
        "provider_json",
        "provider_output",
        "provider_output_json",
        "provider_output_contract",
        "local_structure_contract",
        "outline_contract",
    }:
        return "TXT structure analysis provider returned invalid structured output"
    if status is not None:
        return f"TXT structure analysis provider rejected the request (HTTP {status})"
    return "TXT structure analysis provider failed"


_CANONICAL_STAGE_MESSAGES = {
    "request_validation": "TXT ingestion request validation failed",
    "session_open": "TXT canonical database session could not be opened",
    "source_lookup": "TXT retained source lookup failed",
    "source_validation": "TXT retained source validation failed",
    "source_read": "TXT retained source could not be read",
    "normalization": "TXT source normalization failed",
    "local_analysis": "TXT local structure analysis failed",
    "local_reconciliation": "TXT local structure reconciliation failed",
    "outline_planning": "TXT document outline planning failed",
    "outline_analysis": "TXT document outline analysis failed",
    "outline_validation": "TXT document outline validation failed",
    "spr_recovery": "TXT structured result recovery failed",
    "spr_serialization": "TXT structured result serialization failed",
    "spr_storage": "TXT structured result storage failed",
    "candidate_transform": "TXT canonical content transformation failed",
    "write_session_open": "TXT canonical write session could not be opened",
    "write_identity_validation": "TXT retained source changed before canonical persistence",
    "processing_run_persistence": "TXT processing-run persistence failed",
    "candidate_persistence": "TXT canonical candidate persistence failed",
    "selection": "TXT Reader v2 candidate selection failed",
    "commit": "TXT canonical database commit failed",
}


def _canonical_failure_message(exc: TxtCanonicalizationError) -> str:
    stage = exc.stage
    base = _CANONICAL_STAGE_MESSAGES.get(stage, "TXT canonicalization failed")
    return f"{base} [{stage}]"


def _safe_failure_message(exc: BaseException) -> str:
    chain = tuple(_exception_chain(exc))
    if any(isinstance(item, TxtIngestionConfigurationError) for item in chain):
        return "TXT structure analysis is not configured"
    provider_error = next(
        (item for item in chain if isinstance(item, TxtStructureAnalyzerClientError)),
        None,
    )
    if provider_error is not None:
        return _provider_failure_message(provider_error)
    canonical_error = next(
        (item for item in chain if isinstance(item, TxtCanonicalizationError)),
        None,
    )
    if canonical_error is not None:
        return _canonical_failure_message(canonical_error)
    return "TXT processing failed before Reader v2 content became ready"


def _database_failure_fields(chain: tuple[BaseException, ...]) -> dict[str, object]:
    sqlalchemy_error = next(
        (item for item in chain if isinstance(item, SQLAlchemyError)),
        None,
    )
    sqlite_error = next(
        (item for item in chain if isinstance(item, sqlite3.Error)),
        None,
    )
    if sqlite_error is None and sqlalchemy_error is not None:
        original = getattr(sqlalchemy_error, "orig", None)
        if isinstance(original, sqlite3.Error):
            sqlite_error = original
    return {
        "sqlalchemy_error_type": type(sqlalchemy_error).__name__ if sqlalchemy_error else None,
        "dbapi_error_type": type(sqlite_error).__name__ if sqlite_error else None,
        "sqlite_error_code": getattr(sqlite_error, "sqlite_errorcode", None) if sqlite_error else None,
        "sqlite_error_name": getattr(sqlite_error, "sqlite_errorname", None) if sqlite_error else None,
    }


def _safe_failure_fields(exc: BaseException) -> dict[str, object]:
    chain = tuple(_exception_chain(exc))
    provider_error = next(
        (item for item in chain if isinstance(item, TxtStructureAnalyzerClientError)),
        None,
    )
    canonical_error = next(
        (item for item in chain if isinstance(item, TxtCanonicalizationError)),
        None,
    )
    return {
        "outer_error_type": type(exc).__name__,
        "canonical_error_type": type(canonical_error).__name__ if canonical_error else None,
        "canonical_stage": canonical_error.stage if canonical_error else None,
        "provider_error_type": type(provider_error).__name__ if provider_error else None,
        "provider_stage": provider_error.stage if provider_error else None,
        "provider_contract_reason": provider_error.contract_reason if provider_error else None,
        "provider_status_code": provider_error.status_code if provider_error else None,
        "provider_retryable": provider_error.retryable if provider_error else None,
        "root_error_type": type(chain[-1]).__name__ if chain else type(exc).__name__,
        **_database_failure_fields(chain),
    }


def process_txt_document_background(
    document_id: str,
    source_file_id: str,
    ingestion_ids: TxtIngestionIds,
) -> None:
    """Canonicalize one retained TXT source without OCR, fake pages, or rewritten text."""
    _diagnostic(
        "TXT_CANONICAL_INGESTION_STARTED",
        document_id=document_id,
        source_file_id=source_file_id,
        processing_run_ref=ingestion_ids.processing_run_ref,
    )
    try:
        analyzer = build_production_txt_structure_analyzer()
        service = TxtCanonicalizationService(
            storage=get_storage_provider(),
            session_factory=SessionLocal,
            analyzer=analyzer,
        )
        outcome = service.canonicalize(
            RetainedTxtCanonicalizationRequest(
                document_ref=document_id,
                source_file_ref=source_file_id,
                processing_run_ref=ingestion_ids.processing_run_ref,
            )
        )
    except (TxtIngestionConfigurationError, TxtStructureAnalyzerClientError, TxtCanonicalizationError) as exc:
        logger.exception(
            "TXT canonical ingestion failed document_id=%s processing_run_ref=%s error_type=%s",
            document_id,
            ingestion_ids.processing_run_ref,
            type(exc).__name__,
        )
        _diagnostic(
            "TXT_CANONICAL_INGESTION_FAILED",
            document_id=document_id,
            processing_run_ref=ingestion_ids.processing_run_ref,
            **_safe_failure_fields(exc),
        )
        _set_document_terminal_state(
            document_id,
            status="failed",
            error_message=_safe_failure_message(exc),
        )
        return
    except Exception as exc:  # pragma: no cover - final production safety boundary
        logger.exception(
            "Unexpected TXT canonical ingestion failure document_id=%s processing_run_ref=%s",
            document_id,
            ingestion_ids.processing_run_ref,
        )
        _diagnostic(
            "TXT_CANONICAL_INGESTION_FAILED",
            document_id=document_id,
            processing_run_ref=ingestion_ids.processing_run_ref,
            **_safe_failure_fields(exc),
        )
        _set_document_terminal_state(
            document_id,
            status="failed",
            error_message=_safe_failure_message(exc),
        )
        return

    _set_document_terminal_state(document_id, status="completed", error_message=None)
    _diagnostic(
        "TXT_CANONICAL_INGESTION_COMPLETED",
        document_id=document_id,
        source_file_id=source_file_id,
        processing_run_ref=ingestion_ids.processing_run_ref,
        candidate_id=outcome.candidate_id,
        selected_candidate_id=outcome.selected_candidate_id,
        selection_version=outcome.selection_version,
    )


__all__ = [
    "TxtIngestionConfigurationError",
    "TxtIngestionIds",
    "build_production_txt_structure_analyzer",
    "new_txt_ingestion_ids",
    "process_txt_document_background",
]
