"""Staging-only S0 upload-boundary observability.

This module measures the canonical ``POST /api/v1/upload`` request from the ASGI
request boundary through durable upload acceptance. It is observational only: it
does not change upload routing, source retention, database semantics,
background-task ownership, or response payloads.

Only the canonical multipart route receives this upload-duration contract.
Resumable and direct-object upload routes have different timing boundaries and
must not be collapsed into it.

Memory evidence is intentionally limited to an exact upload-operation component:
the largest bytes object returned by ``UploadFile.read`` during the canonical
request. It is not process RSS and is not a backend-upload peak-memory metric.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
import logging
import math
from pathlib import Path
import re
import sys
from time import perf_counter
from typing import Any, Callable


CANONICAL_UPLOAD_PATH = "/api/v1/upload"
CANONICAL_UPLOAD_ROUTE = "canonical_multipart"
UPLOAD_MEASUREMENT_SCOPE = "canonical_request_ingress_to_durable_acceptance"
UPLOAD_MEASUREMENT_EVENT = "S0_UPLOAD_ACCEPTANCE_MEASURED"
UPLOAD_MEMORY_COMPONENT_SCOPE = "largest_uploadfile_read_result"

_RUNTIME_ROOT = Path(__file__).resolve().parents[1]
_STAGING_REVISION_FILE = _RUNTIME_ROOT / "staging-revision.txt"
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")

logger = logging.getLogger("uvicorn.error")


@dataclass(slots=True)
class _UploadObservation:
    wall_started: float
    http_body_bytes_received: int = 0
    max_asgi_receive_chunk_bytes: int = 0
    uploadfile_read_total_bytes: int = 0
    max_uploadfile_read_bytes: int = 0
    finalized: bool = False
    failure_reported: bool = False


_CURRENT_UPLOAD: ContextVar[_UploadObservation | None] = ContextVar(
    "atlas_s0_current_upload_observation",
    default=None,
)
_INSTALLED = False


def staging_upload_observability_enabled() -> bool:
    """Return whether this code is running from an exact tested Staging artifact."""
    try:
        revision = _STAGING_REVISION_FILE.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return False
    return _REVISION_RE.fullmatch(revision) is not None


def _diagnostic(event: str, **fields: object) -> None:
    payload = " ".join(f"{name}={value}" for name, value in fields.items())
    message = f"{event} {payload}".rstrip()
    logger.info(message)
    print(message, file=sys.stderr, flush=True)


def _safe_identity(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized else None


def _finite_nonnegative(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _bytes_length(value: object) -> int:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return len(value)
    return 0


def _record_success(
    *,
    processing_run_id: str,
    document_id: str,
    fields: dict[str, object],
) -> bool:
    """Persist the bounded event lazily so startup does not import processing."""
    try:
        from app.processing.processing_events import record_processing_event

        return bool(
            record_processing_event(
                processing_run_id=processing_run_id,
                document_id=document_id,
                event_name=UPLOAD_MEASUREMENT_EVENT,
                severity="info",
                payload=fields,
            )
        )
    except Exception:
        return False


def _load_accepted_source_size(source_file_id: str) -> int | None:
    """Read the already-committed SourceFile byte size without changing state."""
    from app.database import SessionLocal
    from app.models import SourceFile

    db = None
    try:
        db = SessionLocal()
        source = db.get(SourceFile, source_file_id)
        value = getattr(source, "byte_size", None) if source is not None else None
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None
    except Exception:
        return None
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def _background_identity(
    func: object,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> tuple[str, str, str] | None:
    """Resolve only the two canonical upload background-task contracts."""
    module = getattr(func, "__module__", "")
    name = getattr(func, "__name__", "")
    if (module, name) not in {
        ("app.processing.pdf_ingestion", "process_pdf_document_background"),
        ("app.processing.txt.ingestion", "process_txt_document_background"),
    }:
        return None

    document_id = _safe_identity(
        args[0] if len(args) > 0 else kwargs.get("document_id")
    )
    source_file_id = _safe_identity(
        args[1] if len(args) > 1 else kwargs.get("source_file_id")
    )
    ingestion_ids = args[2] if len(args) > 2 else kwargs.get("ingestion_ids")
    processing_run_id = _safe_identity(
        getattr(ingestion_ids, "processing_attempt_id", None)
    ) or _safe_identity(getattr(ingestion_ids, "processing_run_ref", None))

    if document_id is None or source_file_id is None or processing_run_id is None:
        return None
    return processing_run_id, document_id, source_file_id


def _finalize_from_background_task(
    func: object,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> None:
    observation = _CURRENT_UPLOAD.get()
    if observation is None or observation.finalized:
        return

    identity = _background_identity(func, args, kwargs)
    if identity is None:
        return
    processing_run_id, document_id, source_file_id = identity

    # The task is queued only after source retention and the Document/SourceFile
    # commit. Use the committed SourceFile row as the accepted source-byte truth.
    accepted_source_size = _load_accepted_source_size(source_file_id)
    observation.finalized = True
    if accepted_source_size is None:
        _diagnostic(
            "S0_UPLOAD_MEASUREMENT_UNAVAILABLE",
            upload_route=CANONICAL_UPLOAD_ROUTE,
            reason="accepted_source_size_unavailable",
            http_body_bytes_received=observation.http_body_bytes_received,
        )
        return

    elapsed = _finite_nonnegative(perf_counter() - observation.wall_started)
    if elapsed is None:
        _diagnostic(
            "S0_UPLOAD_MEASUREMENT_UNAVAILABLE",
            upload_route=CANONICAL_UPLOAD_ROUTE,
            reason="invalid_elapsed_time",
            accepted_source_size_bytes=accepted_source_size,
        )
        return

    fields: dict[str, object] = {
        "succeeded": True,
        "upload_route": CANONICAL_UPLOAD_ROUTE,
        "measurement_scope": UPLOAD_MEASUREMENT_SCOPE,
        "upload_duration_seconds": round(elapsed, 6),
        "accepted_source_size_bytes": accepted_source_size,
        "http_body_bytes_received": observation.http_body_bytes_received,
        "max_asgi_receive_chunk_bytes": observation.max_asgi_receive_chunk_bytes,
        "uploadfile_read_total_bytes": observation.uploadfile_read_total_bytes,
        "max_uploadfile_read_bytes": observation.max_uploadfile_read_bytes,
        "memory_component_scope": UPLOAD_MEMORY_COMPONENT_SCOPE,
    }
    if not _record_success(
        processing_run_id=processing_run_id,
        document_id=document_id,
        fields=fields,
    ):
        _diagnostic(
            "S0_UPLOAD_MEASUREMENT_UNAVAILABLE",
            upload_route=CANONICAL_UPLOAD_ROUTE,
            reason="durable_event_not_recorded",
            accepted_source_size_bytes=accepted_source_size,
        )


def _wrap_fastapi_call(delegate: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(delegate, "__atlas_s0_upload_boundary__", False):
        return delegate

    @wraps(delegate)
    async def wrapped(
        app_self: object,
        scope: dict[str, object],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ):
        if (
            scope.get("type") != "http"
            or scope.get("path") != CANONICAL_UPLOAD_PATH
            or _CURRENT_UPLOAD.get() is not None
        ):
            return await delegate(app_self, scope, receive, send)

        observation = _UploadObservation(wall_started=perf_counter())
        token = _CURRENT_UPLOAD.set(observation)
        response_status: int | None = None

        async def observed_receive():
            message = await receive()
            if isinstance(message, dict) and message.get("type") == "http.request":
                body_size = _bytes_length(message.get("body", b""))
                observation.http_body_bytes_received += body_size
                observation.max_asgi_receive_chunk_bytes = max(
                    observation.max_asgi_receive_chunk_bytes,
                    body_size,
                )
            return message

        async def observed_send(message):
            nonlocal response_status
            if isinstance(message, dict) and message.get("type") == "http.response.start":
                status = message.get("status")
                if isinstance(status, int) and not isinstance(status, bool):
                    response_status = status
            return await send(message)

        try:
            return await delegate(app_self, scope, observed_receive, observed_send)
        except BaseException as exc:
            observation.failure_reported = True
            _diagnostic(
                "S0_UPLOAD_REQUEST_FAILED",
                upload_route=CANONICAL_UPLOAD_ROUTE,
                error_type=type(exc).__name__,
                http_body_bytes_received=observation.http_body_bytes_received,
                max_asgi_receive_chunk_bytes=observation.max_asgi_receive_chunk_bytes,
                max_uploadfile_read_bytes=observation.max_uploadfile_read_bytes,
            )
            raise
        finally:
            if not observation.finalized and not observation.failure_reported:
                _diagnostic(
                    "S0_UPLOAD_REQUEST_NOT_ACCEPTED",
                    upload_route=CANONICAL_UPLOAD_ROUTE,
                    http_status_code=response_status,
                    http_body_bytes_received=observation.http_body_bytes_received,
                    max_asgi_receive_chunk_bytes=observation.max_asgi_receive_chunk_bytes,
                    max_uploadfile_read_bytes=observation.max_uploadfile_read_bytes,
                )
            _CURRENT_UPLOAD.reset(token)

    setattr(wrapped, "__atlas_s0_upload_boundary__", True)
    setattr(wrapped, "__atlas_s0_upload_delegate__", delegate)
    return wrapped


def _wrap_uploadfile_read(delegate: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(delegate, "__atlas_s0_upload_read__", False):
        return delegate

    @wraps(delegate)
    async def wrapped(file_self: object, *args: object, **kwargs: object):
        data = await delegate(file_self, *args, **kwargs)
        observation = _CURRENT_UPLOAD.get()
        if observation is not None and not observation.finalized:
            size = _bytes_length(data)
            observation.uploadfile_read_total_bytes += size
            observation.max_uploadfile_read_bytes = max(
                observation.max_uploadfile_read_bytes,
                size,
            )
        return data

    setattr(wrapped, "__atlas_s0_upload_read__", True)
    setattr(wrapped, "__atlas_s0_upload_delegate__", delegate)
    return wrapped


def _wrap_background_add_task(delegate: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(delegate, "__atlas_s0_upload_background__", False):
        return delegate

    @wraps(delegate)
    def wrapped(
        background_self: object,
        func: Callable[..., Any],
        *args: object,
        **kwargs: object,
    ):
        result = delegate(background_self, func, *args, **kwargs)
        _finalize_from_background_task(func, tuple(args), dict(kwargs))
        return result

    setattr(wrapped, "__atlas_s0_upload_background__", True)
    setattr(wrapped, "__atlas_s0_upload_delegate__", delegate)
    return wrapped


def install_s0_upload_boundary_observability(*, force: bool = False) -> bool:
    """Install the Staging-only canonical upload probes exactly once."""
    global _INSTALLED
    if _INSTALLED:
        return True
    if not force and not staging_upload_observability_enabled():
        return False

    # Import framework classes only after the Staging runtime gate. Focused S0
    # collector tests intentionally do not need FastAPI/Starlette installed.
    from fastapi import BackgroundTasks, FastAPI
    from starlette.datastructures import UploadFile

    FastAPI.__call__ = _wrap_fastapi_call(FastAPI.__call__)
    UploadFile.read = _wrap_uploadfile_read(UploadFile.read)
    BackgroundTasks.add_task = _wrap_background_add_task(BackgroundTasks.add_task)
    _INSTALLED = True
    return True


__all__ = [
    "CANONICAL_UPLOAD_PATH",
    "CANONICAL_UPLOAD_ROUTE",
    "UPLOAD_MEASUREMENT_EVENT",
    "UPLOAD_MEASUREMENT_SCOPE",
    "UPLOAD_MEMORY_COMPONENT_SCOPE",
    "install_s0_upload_boundary_observability",
    "staging_upload_observability_enabled",
]
