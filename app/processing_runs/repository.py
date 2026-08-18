from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models import Document, ProcessingRun, SourceFile, decode_json_text, encode_json_text
from .errors import *
from .types import ProcessingRunCreate, ProcessingRunState, ProcessingRunStatus, ProcessingRunSummary

_CREATE_FIELDS = (
    "processing_run_ref", "document_ref", "source_file_ref", "status", "provider_ref",
    "provider_model_ref", "processing_policy_ref", "idempotency_key", "raw_result_ref",
    "structured_processing_result_ref", "started_at", "completed_at", "failed_at",
    "safe_error_code", "safe_error_summary", "metrics", "extensions",
)
_ALLOWED = {s.value for s in ProcessingRunStatus}
_TRANSITIONS = {
    "created": {"running", "cancelled"},
    "running": {"succeeded", "failed", "cancelled"},
}

def _status(value: ProcessingRunStatus | str) -> str:
    raw = value.value if isinstance(value, ProcessingRunStatus) else str(value)
    if raw not in _ALLOWED:
        raise ProcessingRunInvalid(f"invalid processing run status: {raw}")
    return raw

def _json_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProcessingRunInvalid(f"{field} must be a JSON object")
    try:
        # Encode/decode normalizes tuples and rejects non-finite floats.
        return decode_json_text(encode_json_text(value)) or {}
    except Exception as exc:
        raise ProcessingRunInvalid(f"{field} must be deterministic JSON") from exc

def _safe_ref(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        raise ProcessingRunInvalid(f"{name} must be a nonempty string when supplied")
    return value

class ProcessingRunRepository:
    """Narrow ProcessingRun repository; caller owns transaction, methods flush only."""

    def create_run(self, session, run: ProcessingRunCreate) -> ProcessingRunState:
        normalized = replace(run, status=_status(run.status), metrics=_json_dict(run.metrics, "metrics"), extensions=_json_dict(run.extensions, "extensions"))
        for name in ("processing_run_ref", "document_ref", "source_file_ref", "provider_ref", "provider_model_ref", "processing_policy_ref", "idempotency_key", "raw_result_ref", "structured_processing_result_ref", "safe_error_code"):
            _safe_ref(getattr(normalized, name), name)
        if session.get(Document, normalized.document_ref) is None:
            raise ProcessingRunDocumentNotFound(f"document not found: {normalized.document_ref}")
        if normalized.source_file_ref is not None:
            source = session.get(SourceFile, normalized.source_file_ref)
            if source is None or source.document_id != normalized.document_ref:
                raise ProcessingRunSourceFileMismatch("source file does not belong to document")
        existing = self._row(session, normalized.processing_run_ref)
        if existing is not None:
            return self._idempotent_or_conflict(existing, normalized)
        if normalized.idempotency_key:
            idem = session.execute(select(ProcessingRun).where(ProcessingRun.document_id == normalized.document_ref, ProcessingRun.idempotency_key == normalized.idempotency_key)).scalar_one_or_none()
            if idem is not None:
                return self._idempotent_or_conflict(idem, normalized)
        try:
            with session.begin_nested():
                row = ProcessingRun(
                    processing_run_id=normalized.processing_run_ref,
                    document_id=normalized.document_ref,
                    source_file_id=normalized.source_file_ref,
                    status=normalized.status,
                    provider_ref=normalized.provider_ref,
                    provider_model_ref=normalized.provider_model_ref,
                    processing_policy_ref=normalized.processing_policy_ref,
                    idempotency_key=normalized.idempotency_key,
                    raw_result_ref=normalized.raw_result_ref,
                    structured_processing_result_ref=normalized.structured_processing_result_ref,
                    started_at=normalized.started_at,
                    completed_at=normalized.completed_at,
                    failed_at=normalized.failed_at,
                    safe_error_code=normalized.safe_error_code,
                    safe_error_summary=normalized.safe_error_summary,
                    metrics_json=encode_json_text(normalized.metrics),
                    extensions_json=encode_json_text(normalized.extensions),
                )
                session.add(row); session.flush()
        except IntegrityError as exc:
            session.rollback()
            existing = self._row(session, normalized.processing_run_ref)
            if existing is not None:
                return self._idempotent_or_conflict(existing, normalized)
            raise ProcessingRunPersistenceError("failed to persist processing run") from exc
        except SQLAlchemyError as exc:
            raise ProcessingRunPersistenceError("failed to persist processing run") from exc
        return self.get_run(session, normalized.processing_run_ref)

    def get_run(self, session, processing_run_ref: str) -> ProcessingRunState:
        row = self._row(session, processing_run_ref)
        if row is None:
            raise ProcessingRunNotFound(f"processing run not found: {processing_run_ref}")
        return self._state(row)

    def run_exists(self, session, processing_run_ref: str) -> bool:
        return self._row(session, processing_run_ref) is not None

    def list_runs_for_document(self, session, document_ref: str) -> tuple[ProcessingRunSummary, ...]:
        rows = session.execute(select(ProcessingRun).where(ProcessingRun.document_id == document_ref).order_by(ProcessingRun.created_at, ProcessingRun.processing_run_id)).scalars().all()
        return tuple(ProcessingRunSummary(r.processing_run_id, r.document_id, r.source_file_id, self._valid_status(r.status), r.provider_ref, r.provider_model_ref, r.processing_policy_ref, r.raw_result_ref, r.structured_processing_result_ref, r.started_at, r.completed_at, r.failed_at, r.created_at) for r in rows)

    def mark_running(self, session, processing_run_ref: str, *, started_at: datetime | None = None) -> ProcessingRunState:
        return self._transition(session, processing_run_ref, "running", started_at=started_at or datetime.utcnow())

    def mark_succeeded(self, session, processing_run_ref: str, *, completed_at: datetime | None = None, raw_result_ref: str | None = None, structured_processing_result_ref: str | None = None, metrics: dict[str, Any] | None = None) -> ProcessingRunState:
        return self._transition(session, processing_run_ref, "succeeded", completed_at=completed_at or datetime.utcnow(), raw_result_ref=raw_result_ref, structured_processing_result_ref=structured_processing_result_ref, metrics=metrics)

    def mark_failed(self, session, processing_run_ref: str, *, failed_at: datetime | None = None, safe_error_code: str | None = None, safe_error_summary: str | None = None) -> ProcessingRunState:
        return self._transition(session, processing_run_ref, "failed", failed_at=failed_at or datetime.utcnow(), safe_error_code=safe_error_code, safe_error_summary=safe_error_summary)

    def mark_cancelled(self, session, processing_run_ref: str) -> ProcessingRunState:
        return self._transition(session, processing_run_ref, "cancelled")

    def _transition(self, session, ref: str, to_status: str, **updates) -> ProcessingRunState:
        row = self._row(session, ref)
        if row is None: raise ProcessingRunNotFound(f"processing run not found: {ref}")
        current = self._valid_status(row.status)
        if to_status not in _TRANSITIONS.get(current, set()):
            raise ProcessingRunInvalidTransition(f"invalid transition: {current} -> {to_status}")
        row.status = to_status
        if updates.get("started_at") is not None: row.started_at = updates["started_at"]
        if updates.get("completed_at") is not None: row.completed_at = updates["completed_at"]
        if updates.get("failed_at") is not None: row.failed_at = updates["failed_at"]
        if updates.get("safe_error_code") is not None: row.safe_error_code = _safe_ref(updates["safe_error_code"], "safe_error_code")
        if updates.get("safe_error_summary") is not None: row.safe_error_summary = updates["safe_error_summary"]
        if updates.get("raw_result_ref") is not None: row.raw_result_ref = _safe_ref(updates["raw_result_ref"], "raw_result_ref")
        if updates.get("structured_processing_result_ref") is not None: row.structured_processing_result_ref = _safe_ref(updates["structured_processing_result_ref"], "structured_processing_result_ref")
        if updates.get("metrics") is not None: row.metrics_json = encode_json_text(_json_dict(updates["metrics"], "metrics"))
        try:
            session.flush()
        except SQLAlchemyError as exc:
            raise ProcessingRunPersistenceError("failed to transition processing run") from exc
        return self._state(row)

    def _idempotent_or_conflict(self, row: ProcessingRun, run: ProcessingRunCreate) -> ProcessingRunState:
        try:
            same = (
                row.processing_run_id == run.processing_run_ref and row.document_id == run.document_ref and row.source_file_id == run.source_file_ref and
                row.status == run.status and row.provider_ref == run.provider_ref and row.provider_model_ref == run.provider_model_ref and row.processing_policy_ref == run.processing_policy_ref and
                row.idempotency_key == run.idempotency_key and row.raw_result_ref == run.raw_result_ref and row.structured_processing_result_ref == run.structured_processing_result_ref and
                row.started_at == run.started_at and row.completed_at == run.completed_at and row.failed_at == run.failed_at and row.safe_error_code == run.safe_error_code and row.safe_error_summary == run.safe_error_summary and
                self._decode(row.metrics_json, "metrics_json") == run.metrics and self._decode(row.extensions_json, "extensions_json") == run.extensions
            )
        except PersistedProcessingRunCorrupt:
            raise
        if same: return self._state(row)
        raise ProcessingRunConflict(f"processing run conflicts with existing row: {run.processing_run_ref}")

    def _row(self, session, ref: str):
        return session.execute(select(ProcessingRun).where(ProcessingRun.processing_run_id == ref)).scalar_one_or_none()

    def _decode(self, value: str | None, field: str) -> dict[str, Any]:
        try:
            out = decode_json_text(value) or {}
        except Exception as exc:
            raise PersistedProcessingRunCorrupt(f"invalid {field}") from exc
        if not isinstance(out, dict):
            raise PersistedProcessingRunCorrupt(f"invalid {field}")
        return out

    def _valid_status(self, value: str) -> str:
        if value not in _ALLOWED: raise PersistedProcessingRunCorrupt(f"unknown status: {value}")
        return value

    def _state(self, row: ProcessingRun) -> ProcessingRunState:
        return ProcessingRunState(row.processing_run_id, row.document_id, row.source_file_id, self._valid_status(row.status), row.provider_ref, row.provider_model_ref, row.processing_policy_ref, row.idempotency_key, row.raw_result_ref, row.structured_processing_result_ref, row.started_at, row.completed_at, row.failed_at, row.safe_error_code, row.safe_error_summary, self._decode(row.metrics_json, "metrics_json"), self._decode(row.extensions_json, "extensions_json"), row.created_at)

_repository = ProcessingRunRepository()
create_run = _repository.create_run
get_run = _repository.get_run
run_exists = _repository.run_exists
list_runs_for_document = _repository.list_runs_for_document
mark_running = _repository.mark_running
mark_succeeded = _repository.mark_succeeded
mark_failed = _repository.mark_failed
mark_cancelled = _repository.mark_cancelled
