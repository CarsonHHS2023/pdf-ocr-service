"""Durable book-source acceptance shared by upload transports.

The acceptance transaction is the business boundary: Document, SourceFile, and
IngestionDispatch become durable together. HTTP BackgroundTasks only kick the
durable dispatch after commit and are never the source of queue truth.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Document, DocumentType, SourceFile
from app.processing.ingestion_dispatch import (
    DispatchPayload,
    create_ingestion_dispatch,
    get_dispatch_by_acceptance_key,
    new_dispatch_payload,
    stable_storage_reference,
)
from app.processing.ingestion_dispatch_model import IngestionDispatch
from app.schemas import UploadBookResponse
from app.storage.base import StorageProvider
from app.storage.models import StorageReference

_ACCEPTANCE_NAMESPACE = uuid.UUID("aa72d292-b4f6-42aa-89b9-1b40f215dc95")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class IngestionAcceptanceError(RuntimeError):
    """Raised when an existing durable acceptance contradicts supplied identity."""


@dataclass(frozen=True, slots=True)
class AcceptedIngestion:
    acceptance_key: str
    document_id: str
    source_file_id: str
    dispatch_id: str
    file_type: str
    filename: str
    created: bool
    response: UploadBookResponse


def legacy_acceptance_key() -> str:
    return f"legacy:{uuid.uuid4().hex}"


def resumable_acceptance_key(upload_id: str) -> str:
    value = str(upload_id).strip()
    if not value:
        raise ValueError("upload_id is required")
    return f"resumable:{value}"


def direct_acceptance_key(upload_id: str) -> str:
    value = str(upload_id).strip()
    if not value:
        raise ValueError("upload_id is required")
    return f"direct:{value}"


def stable_entity_id(acceptance_key: str, role: str) -> str:
    normalized_key = str(acceptance_key).strip()
    normalized_role = str(role).strip()
    if not normalized_key or not normalized_role:
        raise ValueError("acceptance_key and role are required")
    return str(uuid.uuid5(_ACCEPTANCE_NAMESPACE, f"{normalized_role}:{normalized_key}"))


def _response(document: Document, source: SourceFile, *, already_accepted: bool) -> UploadBookResponse:
    if already_accepted:
        message = f"File '{source.original_filename}' was already accepted."
    elif document.file_type == "pdf":
        message = (
            f"File '{source.original_filename}' uploaded; PDF processing and "
            "Reader v2 canonicalization queued."
        )
    else:
        message = (
            f"File '{source.original_filename}' uploaded; TXT structure analysis and "
            "Reader v2 canonicalization queued."
        )
    return UploadBookResponse(
        book_id=document.id,
        book_title=document.title,
        file_type=document.file_type,
        status=document.status,
        processed_file_path=document.processed_file_path,
        original_file_path=document.original_file_path,
        error_message=document.error_message,
        message=message,
    )


def _accepted_from_row(
    db: Session,
    row: IngestionDispatch,
    *,
    already_accepted: bool,
    expected_document_id: str | None = None,
    expected_source_file_id: str | None = None,
    expected_storage_reference: str | None = None,
    expected_byte_size: int | None = None,
    expected_checksum_sha256: str | None = None,
) -> AcceptedIngestion:
    document = db.get(Document, row.document_id)
    source = db.get(SourceFile, row.source_file_id)
    if document is None or source is None or source.document_id != document.id:
        raise IngestionAcceptanceError("Durable ingestion acceptance metadata is incomplete")
    expected_pairs = (
        (expected_document_id, document.id, "document_id"),
        (expected_source_file_id, source.id, "source_file_id"),
        (expected_storage_reference, source.storage_reference, "storage_reference"),
        (expected_byte_size, source.byte_size, "byte_size"),
        (
            expected_checksum_sha256.lower() if expected_checksum_sha256 else None,
            source.checksum_sha256.lower() if source.checksum_sha256 else None,
            "checksum_sha256",
        ),
    )
    for expected, actual, field in expected_pairs:
        if expected is not None and expected != actual:
            raise IngestionAcceptanceError(
                f"Durable ingestion acceptance conflicts with expected {field}"
            )
    return AcceptedIngestion(
        acceptance_key=row.acceptance_key,
        document_id=document.id,
        source_file_id=source.id,
        dispatch_id=row.id,
        file_type=document.file_type,
        filename=source.original_filename,
        created=not already_accepted,
        response=_response(document, source, already_accepted=already_accepted),
    )


def find_accepted_ingestion(
    db: Session,
    acceptance_key: str,
    **expected_identity,
) -> AcceptedIngestion | None:
    row = get_dispatch_by_acceptance_key(db, acceptance_key)
    if row is None:
        return None
    return _accepted_from_row(
        db,
        row,
        already_accepted=True,
        **expected_identity,
    )


def commit_retained_ingestion(
    db: Session,
    *,
    acceptance_key: str,
    filename: str,
    file_type: str,
    mime_type: str,
    byte_size: int,
    checksum_sha256: str,
    storage_reference: str,
    page_count: int | None = None,
    document_id: str | None = None,
    source_file_id: str | None = None,
    dispatch_payload: DispatchPayload | None = None,
) -> AcceptedIngestion:
    """Commit Document + SourceFile + dispatch atomically, collapsing races."""
    normalized_key = str(acceptance_key).strip()
    if not normalized_key:
        raise ValueError("acceptance_key is required")
    normalized_type = str(file_type).lower().strip()
    if normalized_type not in {"pdf", "txt"}:
        raise ValueError("file_type must be pdf or txt")
    if int(byte_size) <= 0:
        raise ValueError("byte_size must be positive")
    checksum = str(checksum_sha256).lower().strip()
    if not _SHA256_RE.fullmatch(checksum):
        raise ValueError("checksum_sha256 must contain 64 hexadecimal characters")
    reference = str(StorageReference.parse(storage_reference))

    expected_document_id = document_id or stable_entity_id(normalized_key, "document")
    expected_source_file_id = source_file_id or stable_entity_id(normalized_key, "source")
    existing = find_accepted_ingestion(
        db,
        normalized_key,
        expected_document_id=expected_document_id,
        expected_source_file_id=expected_source_file_id,
        expected_storage_reference=reference,
        expected_byte_size=int(byte_size),
        expected_checksum_sha256=checksum,
    )
    if existing is not None:
        return existing

    payload = dispatch_payload or new_dispatch_payload(normalized_type)
    document = Document(
        id=expected_document_id,
        document_type=DocumentType.BOOK,
        title=Path(filename).stem,
        file_type=normalized_type,
        pages_count=(page_count if normalized_type == "pdf" else None),
        status="processing",
    )
    source = SourceFile(
        id=expected_source_file_id,
        document=document,
        original_filename=filename,
        file_type=normalized_type,
        mime_type=mime_type,
        byte_size=int(byte_size),
        checksum_sha256=checksum,
        storage_reference=reference,
        retained=1,
        is_primary=1,
    )
    db.add(document)
    db.add(source)
    dispatch = None
    try:
        # IngestionDispatch intentionally has only scalar FK identity, not ORM
        # relationships to the staged parent objects. Without an explicit parent
        # flush SQLAlchemy may emit the dispatch INSERT first; PostgreSQL then
        # enforces its FKs before Document/SourceFile exist. Flush parents inside
        # the same transaction before staging the dispatch, preserving one atomic
        # commit while making insert ordering explicit across real FK-enforcing DBs.
        db.flush([document, source])
        dispatch = create_ingestion_dispatch(
            db,
            acceptance_key=normalized_key,
            document_id=document.id,
            source_file_id=source.id,
            payload=payload,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = find_accepted_ingestion(
            db,
            normalized_key,
            expected_document_id=expected_document_id,
            expected_source_file_id=expected_source_file_id,
            expected_storage_reference=reference,
            expected_byte_size=int(byte_size),
            expected_checksum_sha256=checksum,
        )
        if winner is not None:
            return winner
        raise
    except Exception:
        db.rollback()
        raise

    if dispatch is None:  # pragma: no cover - defensive invariant
        raise RuntimeError("Durable ingestion dispatch was not staged")
    db.refresh(document)
    db.refresh(source)
    db.refresh(dispatch)
    return AcceptedIngestion(
        acceptance_key=normalized_key,
        document_id=document.id,
        source_file_id=source.id,
        dispatch_id=dispatch.id,
        file_type=normalized_type,
        filename=filename,
        created=True,
        response=_response(document, source, already_accepted=False),
    )


def retain_and_commit_ingestion(
    db: Session,
    storage: StorageProvider,
    *,
    acceptance_key: str,
    filename: str,
    file_type: str,
    mime_type: str,
    content: bytes,
    page_count: int | None = None,
    cleanup_on_db_failure: bool = False,
) -> AcceptedIngestion:
    """Retain bytes under a stable acceptance ref, then atomically accept metadata."""
    reference = stable_storage_reference(acceptance_key)
    checksum = hashlib.sha256(content).hexdigest()
    result = storage.put(
        content,
        reference,
        expected_size=len(content),
        expected_sha256=checksum,
    )
    try:
        return commit_retained_ingestion(
            db,
            acceptance_key=acceptance_key,
            filename=filename,
            file_type=file_type,
            mime_type=mime_type,
            byte_size=result.byte_size,
            checksum_sha256=result.checksum_sha256,
            storage_reference=str(result.reference),
            page_count=page_count,
        )
    except Exception:
        if cleanup_on_db_failure:
            try:
                if find_accepted_ingestion(db, acceptance_key) is None:
                    storage.delete(reference)
            except Exception:
                # Cleanup is compensation only; never hide the acceptance error.
                pass
        raise


__all__ = [
    "AcceptedIngestion",
    "IngestionAcceptanceError",
    "commit_retained_ingestion",
    "direct_acceptance_key",
    "find_accepted_ingestion",
    "legacy_acceptance_key",
    "resumable_acceptance_key",
    "retain_and_commit_ingestion",
    "stable_entity_id",
]
