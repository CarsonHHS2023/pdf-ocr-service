"""Staging-only S0 upload compatibility for durable ingestion dispatch.

The production-equivalent Staging composition rewrites the canonical multipart
upload route so its background task is ``run_ingestion_dispatch(dispatch_id)``.
The base upload observer intentionally understands the direct PDF/TXT processors;
this module extends only the finalization hook so the durable dispatch row can
supply the already-committed document/source/processing identities.

Timing remains fail-closed and observational: the upload elapsed boundary is
captured before any telemetry-only dispatch/source lookup, and every lookup or
event-persistence failure leaves business processing unchanged.
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from app import s0_upload_boundary_observability as upload


_DURABLE_DISPATCH_TASK = (
    "app.processing.ingestion_dispatch",
    "run_ingestion_dispatch",
)
_INSTALLED = False


def _durable_dispatch_id(
    func: object,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> str | None:
    module = getattr(func, "__module__", "")
    name = getattr(func, "__name__", "")
    if (module, name) != _DURABLE_DISPATCH_TASK:
        return None
    value = args[0] if args else kwargs.get("dispatch_id")
    return upload._safe_identity(value)


def _load_dispatch_identity(
    dispatch_id: str,
    *,
    session_factory: Callable[[], Any] | None = None,
) -> tuple[str, str, str] | None:
    """Resolve one already-committed dispatch without mutating its state."""
    if session_factory is None:
        from app.database import SessionLocal

        session_factory = SessionLocal
    from app.processing.ingestion_dispatch_model import IngestionDispatch

    db = None
    try:
        db = session_factory()
        row = db.get(IngestionDispatch, dispatch_id)
        if row is None:
            return None

        document_id = upload._safe_identity(getattr(row, "document_id", None))
        source_file_id = upload._safe_identity(getattr(row, "source_file_id", None))
        kind = upload._safe_identity(getattr(row, "kind", None))
        if kind == "pdf":
            processing_run_id = upload._safe_identity(
                getattr(row, "processing_attempt_id", None)
            )
        elif kind == "txt":
            processing_run_id = upload._safe_identity(
                getattr(row, "txt_processing_run_ref", None)
            )
        else:
            return None

        if (
            processing_run_id is None
            or document_id is None
            or source_file_id is None
        ):
            return None
        return processing_run_id, document_id, source_file_id
    except Exception:
        return None
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def _wrap_upload_finalize(
    delegate: Callable[[object, tuple[object, ...], dict[str, object]], None],
) -> Callable[[object, tuple[object, ...], dict[str, object]], None]:
    if getattr(delegate, "__atlas_s0_durable_dispatch_finalize__", False):
        return delegate

    @wraps(delegate)
    def wrapped(
        func: object,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> None:
        dispatch_id = _durable_dispatch_id(func, args, kwargs)
        if dispatch_id is None:
            return delegate(func, args, kwargs)

        observation = upload._CURRENT_UPLOAD.get()
        if observation is None or observation.finalized:
            return

        # This is the actual durable-acceptance boundary: the canonical handler
        # has committed Document/SourceFile/IngestionDispatch and successfully
        # registered the dispatch task. Capture elapsed before any observability
        # DB read so telemetry cannot inflate upload_duration_seconds.
        elapsed = upload._finite_nonnegative(
            upload.perf_counter() - observation.wall_started
        )
        observation.finalized = True
        if elapsed is None:
            upload._diagnostic(
                "S0_UPLOAD_MEASUREMENT_UNAVAILABLE",
                upload_route=upload.CANONICAL_UPLOAD_ROUTE,
                reason="invalid_elapsed_time",
            )
            return

        identity = _load_dispatch_identity(dispatch_id)
        if identity is None:
            upload._diagnostic(
                "S0_UPLOAD_MEASUREMENT_UNAVAILABLE",
                upload_route=upload.CANONICAL_UPLOAD_ROUTE,
                reason="durable_dispatch_identity_unavailable",
                http_body_bytes_received=observation.http_body_bytes_received,
            )
            return
        processing_run_id, document_id, source_file_id = identity

        accepted_source_size = upload._load_accepted_source_size(source_file_id)
        if accepted_source_size is None:
            upload._diagnostic(
                "S0_UPLOAD_MEASUREMENT_UNAVAILABLE",
                upload_route=upload.CANONICAL_UPLOAD_ROUTE,
                reason="accepted_source_size_unavailable",
                http_body_bytes_received=observation.http_body_bytes_received,
            )
            return

        fields: dict[str, object] = {
            "succeeded": True,
            "upload_route": upload.CANONICAL_UPLOAD_ROUTE,
            "measurement_scope": upload.UPLOAD_MEASUREMENT_SCOPE,
            "upload_duration_seconds": round(elapsed, 6),
            "accepted_source_size_bytes": accepted_source_size,
            "http_body_bytes_received": observation.http_body_bytes_received,
            "max_asgi_receive_chunk_bytes": observation.max_asgi_receive_chunk_bytes,
            "uploadfile_read_total_bytes": observation.uploadfile_read_total_bytes,
            "max_uploadfile_read_bytes": observation.max_uploadfile_read_bytes,
            "memory_component_scope": upload.UPLOAD_MEMORY_COMPONENT_SCOPE,
        }
        if not upload._record_success(
            processing_run_id=processing_run_id,
            document_id=document_id,
            fields=fields,
        ):
            upload._diagnostic(
                "S0_UPLOAD_MEASUREMENT_UNAVAILABLE",
                upload_route=upload.CANONICAL_UPLOAD_ROUTE,
                reason="durable_event_not_recorded",
                accepted_source_size_bytes=accepted_source_size,
            )

    setattr(wrapped, "__atlas_s0_durable_dispatch_finalize__", True)
    setattr(wrapped, "__atlas_s0_durable_dispatch_delegate__", delegate)
    return wrapped


def install_s0_upload_durable_dispatch_compat(*, force: bool = False) -> bool:
    """Extend the already-installed upload observer for durable dispatch tasks."""
    global _INSTALLED
    if _INSTALLED:
        return True
    if not force and not upload.staging_upload_observability_enabled():
        return False

    upload._finalize_from_background_task = _wrap_upload_finalize(
        upload._finalize_from_background_task
    )
    _INSTALLED = True
    return True


__all__ = [
    "install_s0_upload_durable_dispatch_compat",
]
