"""Staging-only S0 backend StorageProvider I/O observability.

Counts logical bytes crossing Atlas' StorageProvider ``put``/``get`` boundary.
These counters describe backend-controlled storage I/O volume; they deliberately
DO NOT claim physical object-store network bytes, backend->compute transport,
or unique object size.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import hashlib
import logging
from pathlib import Path
import re
from threading import Lock
from typing import Any, Callable


STORAGE_IO_EVENT = "S0_OBJECT_STORE_STAGE_IO_MEASURED"
STORAGE_IO_SCOPE = "backend_storage_provider_logical_io_v1"
STAGE_UPLOAD_SOURCE_RETENTION = "upload_source_retention"
STAGE_PROCESSING_SOURCE = "processing_source"
STAGE_GENERATED_ARTIFACT = "generated_artifact"
STAGE_PROVIDER_SOURCE_TRANSPORT = "provider_source_transport"
STORAGE_IO_STAGES = frozenset({
    STAGE_UPLOAD_SOURCE_RETENTION,
    STAGE_PROCESSING_SOURCE,
    STAGE_GENERATED_ARTIFACT,
    STAGE_PROVIDER_SOURCE_TRANSPORT,
})

_RUNTIME_ROOT = Path(__file__).resolve().parents[1]
_STAGING_REVISION_FILE = _RUNTIME_ROOT / "staging-revision.txt"
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
logger = logging.getLogger("uvicorn.error")


@dataclass(slots=True)
class _StageCounter:
    read_bytes: int = 0
    write_bytes: int = 0
    read_operations: int = 0
    write_operations: int = 0


@dataclass(slots=True)
class _RunTracker:
    processing_run_id: str
    document_id: str
    source_storage_reference: str
    stages: dict[str, _StageCounter] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)

    def record_read(self, reference: object, byte_size: int) -> None:
        stage = (
            STAGE_PROCESSING_SOURCE
            if str(reference) == self.source_storage_reference
            else STAGE_GENERATED_ARTIFACT
        )
        self._record(stage, read_bytes=byte_size, read_operations=1)

    def record_write(self, byte_size: int) -> None:
        self._record(STAGE_GENERATED_ARTIFACT, write_bytes=byte_size, write_operations=1)

    def _record(
        self,
        stage: str,
        *,
        read_bytes: int = 0,
        write_bytes: int = 0,
        read_operations: int = 0,
        write_operations: int = 0,
    ) -> None:
        if min(read_bytes, write_bytes, read_operations, write_operations) < 0:
            return
        with self.lock:
            counter = self.stages.setdefault(stage, _StageCounter())
            counter.read_bytes += int(read_bytes)
            counter.write_bytes += int(write_bytes)
            counter.read_operations += int(read_operations)
            counter.write_operations += int(write_operations)


_CURRENT_TRACKER: ContextVar[_RunTracker | None] = ContextVar(
    "atlas_s0_object_store_io_tracker", default=None
)
_UPLOAD_INSTALLED = False
_PDF_INSTALLED = False


def staging_storage_io_observability_enabled() -> bool:
    try:
        revision = _STAGING_REVISION_FILE.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return False
    return _REVISION_RE.fullmatch(revision) is not None


def _safe_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _record_stage_event(
    *,
    processing_run_id: str,
    document_id: str,
    stage: str,
    read_bytes: int,
    write_bytes: int,
    read_operations: int,
    write_operations: int,
    scope_id: str,
    scope_ordinal: int = 1,
) -> bool:
    if stage not in STORAGE_IO_STAGES:
        return False
    numeric = (read_bytes, write_bytes, read_operations, write_operations, scope_ordinal)
    if any(_safe_nonnegative_int(value) is None for value in numeric):
        return False
    if scope_ordinal < 1 or not re.fullmatch(r"[a-z0-9_]{1,48}", scope_id):
        return False
    try:
        from app.processing.processing_events import record_processing_event

        return bool(record_processing_event(
            processing_run_id=processing_run_id,
            document_id=document_id,
            event_name=STORAGE_IO_EVENT,
            severity="info",
            payload={
                "succeeded": True,
                "measurement_scope": STORAGE_IO_SCOPE,
                "stage": stage,
                "scope_id": scope_id,
                "scope_ordinal": scope_ordinal,
                "read_bytes": read_bytes,
                "write_bytes": write_bytes,
                "read_operations": read_operations,
                "write_operations": write_operations,
            },
        ))
    except Exception:
        return False


class _ObservedStorageProvider:
    def __init__(self, delegate: object, tracker: _RunTracker) -> None:
        self._delegate = delegate
        self._tracker = tracker

    def put(self, data: bytes, reference=None, *, expected_size=None, expected_sha256=None):
        result = self._delegate.put(
            data,
            reference,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )
        size = _safe_nonnegative_int(getattr(result, "byte_size", None))
        if size is not None:
            self._tracker.record_write(size)
        return result

    def get(self, reference):
        payload = self._delegate.get(reference)
        if isinstance(payload, bytes):
            self._tracker.record_read(reference, len(payload))
        return payload

    def delete(self, reference):
        return self._delegate.delete(reference)

    def exists(self, reference):
        return self._delegate.exists(reference)

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)


def _storage_for_tracker(storage: object, tracker: _RunTracker | None) -> object:
    """Return one tracker-aware wrapper without stacking duplicate observers."""
    if tracker is None:
        return storage
    if isinstance(storage, _ObservedStorageProvider):
        if storage._tracker is tracker:
            return storage
        storage = storage._delegate
    return _ObservedStorageProvider(storage, tracker)


def _wrap_storage_dependency(delegate: Callable[[], object]) -> Callable[[], object]:
    """Make dynamic storage dependency lookups honor the active PDF run context."""
    if getattr(delegate, "__atlas_s0_storage_dependency__", False):
        return delegate

    @wraps(delegate)
    def wrapped() -> object:
        return _storage_for_tracker(delegate(), _CURRENT_TRACKER.get())

    setattr(wrapped, "__atlas_s0_storage_dependency__", True)
    setattr(wrapped, "__atlas_s0_storage_delegate__", delegate)
    return wrapped


def _load_source_reference(source_file_id: str) -> str | None:
    db = None
    try:
        from app.database import SessionLocal
        from app.models import SourceFile

        db = SessionLocal()
        row = db.get(SourceFile, source_file_id)
        value = getattr(row, "storage_reference", None) if row is not None else None
        return str(value).strip() if isinstance(value, str) and value.strip() else None
    except Exception:
        return None
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def _emit_tracker(tracker: _RunTracker) -> None:
    with tracker.lock:
        snapshot = {
            stage: _StageCounter(
                read_bytes=counter.read_bytes,
                write_bytes=counter.write_bytes,
                read_operations=counter.read_operations,
                write_operations=counter.write_operations,
            )
            for stage, counter in tracker.stages.items()
        }
    for stage in sorted(snapshot):
        counter = snapshot[stage]
        _record_stage_event(
            processing_run_id=tracker.processing_run_id,
            document_id=tracker.document_id,
            stage=stage,
            read_bytes=counter.read_bytes,
            write_bytes=counter.write_bytes,
            read_operations=counter.read_operations,
            write_operations=counter.write_operations,
            scope_id="processing_run",
        )


def install_s0_object_store_upload_observability(*, force: bool = False) -> bool:
    """Emit the source-retention write from the already-proven upload contract."""
    global _UPLOAD_INSTALLED
    if _UPLOAD_INSTALLED:
        return True
    if not force and not staging_storage_io_observability_enabled():
        return False

    from app import s0_upload_boundary_observability as upload

    delegate = upload._record_success
    if getattr(delegate, "__atlas_s0_storage_upload__", False):
        _UPLOAD_INSTALLED = True
        return True

    @wraps(delegate)
    def wrapped(*, processing_run_id: str, document_id: str, fields: dict[str, object]) -> bool:
        recorded = bool(delegate(
            processing_run_id=processing_run_id,
            document_id=document_id,
            fields=fields,
        ))
        if recorded:
            size = _safe_nonnegative_int(fields.get("accepted_source_size_bytes"))
            if size is not None:
                _record_stage_event(
                    processing_run_id=processing_run_id,
                    document_id=document_id,
                    stage=STAGE_UPLOAD_SOURCE_RETENTION,
                    read_bytes=0,
                    write_bytes=size,
                    read_operations=0,
                    write_operations=1,
                    scope_id="upload_acceptance",
                )
        return recorded

    setattr(wrapped, "__atlas_s0_storage_upload__", True)
    upload._record_success = wrapped
    _UPLOAD_INSTALLED = True
    return True


def install_s0_object_store_pdf_observability(*, force: bool = False) -> bool:
    """Wrap one PDF ProcessingRun's StorageProvider and emit stage aggregates."""
    global _PDF_INSTALLED
    if _PDF_INSTALLED:
        return True
    if not force and not staging_storage_io_observability_enabled():
        return False

    from app.processing import pdf_ingestion
    from app.storage import dependencies as storage_dependencies

    original_get_storage = pdf_ingestion.get_storage_provider
    original_dependency_get_storage = storage_dependencies.get_storage_provider
    original_process = pdf_ingestion.process_pdf_document_background
    if getattr(original_process, "__atlas_s0_storage_pdf__", False):
        _PDF_INSTALLED = True
        return True

    @wraps(original_get_storage)
    def observed_get_storage_provider():
        return _storage_for_tracker(original_get_storage(), _CURRENT_TRACKER.get())

    @wraps(original_process)
    async def observed_process(document_id: str, source_file_id: str, ids: object) -> None:
        processing_run_id = str(getattr(ids, "processing_attempt_id", "") or "").strip()
        source_reference = _load_source_reference(source_file_id)
        if not processing_run_id or not source_reference:
            return await original_process(document_id, source_file_id, ids)
        tracker = _RunTracker(
            processing_run_id=processing_run_id,
            document_id=document_id,
            source_storage_reference=source_reference,
        )
        token = _CURRENT_TRACKER.set(tracker)
        try:
            return await original_process(document_id, source_file_id, ids)
        finally:
            _CURRENT_TRACKER.reset(token)
            _emit_tracker(tracker)

    setattr(observed_process, "__atlas_s0_storage_pdf__", True)
    # ``pdf_ingestion`` imported the dependency eagerly, while presentation
    # lifecycle code resolves it dynamically during grant creation. Install both
    # context-aware entry points so one ProcessingRun sees the complete logical
    # StorageProvider read/write path without changing unrelated requests.
    pdf_ingestion.get_storage_provider = observed_get_storage_provider
    storage_dependencies.get_storage_provider = _wrap_storage_dependency(
        original_dependency_get_storage
    )
    pdf_ingestion.process_pdf_document_background = observed_process
    _PDF_INSTALLED = True
    return True


def record_provider_source_transport_read(grant: object, byte_size: int, retrieval_ordinal: int) -> bool:
    """Record one completed backend source-transport StorageProvider read."""
    if not staging_storage_io_observability_enabled():
        return False
    processing_run_id = str(getattr(grant, "atlas_attempt_id", "") or "").strip()
    document_id = str(getattr(grant, "document_id", "") or "").strip()
    grant_id = str(getattr(grant, "grant_id", "") or "").strip()
    if not processing_run_id or not document_id or not grant_id:
        return False
    size = _safe_nonnegative_int(byte_size)
    ordinal = _safe_nonnegative_int(retrieval_ordinal)
    if size is None or ordinal is None or ordinal < 1:
        return False
    scope_id = "transport_" + hashlib.sha256(grant_id.encode("utf-8")).hexdigest()[:16]
    return _record_stage_event(
        processing_run_id=processing_run_id,
        document_id=document_id,
        stage=STAGE_PROVIDER_SOURCE_TRANSPORT,
        read_bytes=size,
        write_bytes=0,
        read_operations=1,
        write_operations=0,
        scope_id=scope_id,
        scope_ordinal=ordinal,
    )


__all__ = [
    "STORAGE_IO_EVENT",
    "STORAGE_IO_SCOPE",
    "STORAGE_IO_STAGES",
    "STAGE_GENERATED_ARTIFACT",
    "STAGE_PROCESSING_SOURCE",
    "STAGE_PROVIDER_SOURCE_TRANSPORT",
    "STAGE_UPLOAD_SOURCE_RETENTION",
    "install_s0_object_store_pdf_observability",
    "install_s0_object_store_upload_observability",
    "record_provider_source_transport_read",
    "staging_storage_io_observability_enabled",
]
