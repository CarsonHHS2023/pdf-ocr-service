"""Staging-only S0 Phase 2 durable stage measurements.

This compatibility layer is observational only. It wraps already-composed
classification, preprocessing, canonicalization, and Provider integration
callables, records bounded timing/resource evidence, and returns or raises the
exact delegate result. It does not change routing, sharding, concurrency,
timeouts, retries, storage placement, OCR options, or canonical selection.
"""
from __future__ import annotations

import inspect
import math
from functools import wraps
from time import perf_counter, process_time
from typing import Any, Callable

from app.processing.processing_events import record_processing_event
from app.processing.s0_pdf_resource_heartbeat import resource_snapshot


_INSTALLED = False


def _finite_nonnegative(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _resource_fields() -> dict[str, float]:
    """Return only finite non-negative process memory evidence."""
    try:
        snapshot = resource_snapshot()
    except Exception:
        return {}
    output: dict[str, float] = {}
    for key in ("rss_mb", "peak_rss_mb"):
        value = _finite_nonnegative(snapshot.get(key))
        if value is not None:
            output[key] = value
    return output


def _measurement_fields(
    *,
    wall_started: float,
    cpu_started: float,
) -> dict[str, object]:
    return {
        "elapsed_seconds": round(max(0.0, perf_counter() - wall_started), 6),
        "cpu_seconds": round(max(0.0, process_time() - cpu_started), 6),
        **_resource_fields(),
    }


def _safe_identity(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized else None


def _record(
    *,
    processing_run_id: object,
    document_id: object | None,
    event_name: str,
    severity: str,
    fields: dict[str, object],
) -> None:
    """Persist one bounded measurement without allowing telemetry to affect work."""
    try:
        record_processing_event(
            processing_run_id=processing_run_id,
            document_id=document_id,
            event_name=event_name,
            severity=severity,
            payload=fields,
        )
    except Exception:
        # record_processing_event is already fail-open, but preserve that invariant
        # even if a test double or future implementation raises unexpectedly.
        return


def _bound_argument(
    delegate: Callable[..., Any],
    args: tuple[object, ...],
    kwargs: dict[str, object],
    name: str,
) -> object | None:
    if name in kwargs:
        return kwargs[name]
    try:
        return inspect.signature(delegate).bind_partial(*args, **kwargs).arguments.get(name)
    except (TypeError, ValueError):
        return None


def _classification_processing_run_id() -> str | None:
    try:
        from app.processing import pdf_page_classification_observability_compat as obs

        return _safe_identity(obs._PROCESSING_ATTEMPT_ID.get())
    except Exception:
        return None


def _wrap_classification(
    delegate: Callable[..., Any],
    *,
    run_id_getter: Callable[[], str | None] = _classification_processing_run_id,
) -> Callable[..., Any]:
    if getattr(delegate, "__atlas_s0_phase2_classification__", False):
        return delegate

    @wraps(delegate)
    def wrapped(*args: object, **kwargs: object):
        run_id = run_id_getter()
        wall_started = perf_counter()
        cpu_started = process_time()
        try:
            result = delegate(*args, **kwargs)
        except BaseException as exc:
            fields = {
                "succeeded": False,
                "error_type": type(exc).__name__,
                **_measurement_fields(
                    wall_started=wall_started,
                    cpu_started=cpu_started,
                ),
            }
            _record(
                processing_run_id=run_id,
                document_id=None,
                event_name="PDF_S0_CLASSIFICATION_MEASURED",
                severity="error",
                fields=fields,
            )
            raise

        fields: dict[str, object] = {
            "succeeded": True,
            **_measurement_fields(
                wall_started=wall_started,
                cpu_started=cpu_started,
            ),
        }
        if isinstance(result, (list, tuple)):
            fields["page_count"] = len(result)
        _record(
            processing_run_id=run_id,
            document_id=None,
            event_name="PDF_S0_CLASSIFICATION_MEASURED",
            severity="info",
            fields=fields,
        )
        return result

    setattr(wrapped, "__atlas_s0_phase2_classification__", True)
    setattr(wrapped, "__atlas_s0_phase2_delegate__", delegate)
    return wrapped


def _wrap_preprocessing(delegate: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(delegate, "__atlas_s0_phase2_preprocessing__", False):
        return delegate

    @wraps(delegate)
    def wrapped(*args: object, **kwargs: object):
        run_id = _safe_identity(
            _bound_argument(delegate, args, kwargs, "processing_attempt_id")
        )
        wall_started = perf_counter()
        cpu_started = process_time()
        try:
            result = delegate(*args, **kwargs)
        except BaseException as exc:
            _record(
                processing_run_id=run_id,
                document_id=None,
                event_name="PDF_S0_PREPROCESSING_MEASURED",
                severity="error",
                fields={
                    "succeeded": False,
                    "error_type": type(exc).__name__,
                    **_measurement_fields(
                        wall_started=wall_started,
                        cpu_started=cpu_started,
                    ),
                },
            )
            raise

        fields: dict[str, object] = {
            "succeeded": True,
            **_measurement_fields(
                wall_started=wall_started,
                cpu_started=cpu_started,
            ),
        }
        preprocessing = getattr(result, "preprocessing", None)
        page_count = getattr(preprocessing, "page_count", None)
        if isinstance(page_count, int) and not isinstance(page_count, bool) and page_count > 0:
            fields["page_count"] = page_count
        provider_size = getattr(result, "byte_size", None)
        if isinstance(provider_size, int) and not isinstance(provider_size, bool) and provider_size >= 0:
            fields["provider_input_size_bytes"] = provider_size
        _record(
            processing_run_id=run_id,
            document_id=None,
            event_name="PDF_S0_PREPROCESSING_MEASURED",
            severity="info",
            fields=fields,
        )
        return result

    setattr(wrapped, "__atlas_s0_phase2_preprocessing__", True)
    setattr(wrapped, "__atlas_s0_phase2_delegate__", delegate)
    return wrapped


def _wrap_canonicalization(delegate: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(delegate, "__atlas_s0_phase2_canonicalization__", False):
        return delegate

    @wraps(delegate)
    def wrapped(*args: object, **kwargs: object):
        envelope = (
            args[1]
            if len(args) > 1
            else kwargs.get("envelope")
        )
        identity = getattr(envelope, "identity", None)
        run_id = _safe_identity(getattr(identity, "atlas_attempt_id", None))
        document_id = _safe_identity(getattr(identity, "document_id", None))
        ingestion = getattr(envelope, "ingestion", None)
        payload_size = getattr(ingestion, "payload_size_bytes", None)

        wall_started = perf_counter()
        cpu_started = process_time()
        try:
            result = delegate(*args, **kwargs)
        except BaseException as exc:
            fields: dict[str, object] = {
                "succeeded": False,
                "error_type": type(exc).__name__,
                **_measurement_fields(
                    wall_started=wall_started,
                    cpu_started=cpu_started,
                ),
            }
            if isinstance(payload_size, int) and not isinstance(payload_size, bool) and payload_size >= 0:
                fields["raw_result_size_bytes"] = payload_size
            _record(
                processing_run_id=run_id,
                document_id=document_id,
                event_name="PDF_S0_CANONICALIZATION_MEASURED",
                severity="error",
                fields=fields,
            )
            raise

        fields = {
            "succeeded": True,
            **_measurement_fields(
                wall_started=wall_started,
                cpu_started=cpu_started,
            ),
        }
        if isinstance(payload_size, int) and not isinstance(payload_size, bool) and payload_size >= 0:
            fields["raw_result_size_bytes"] = payload_size
        _record(
            processing_run_id=run_id,
            document_id=document_id,
            event_name="PDF_S0_CANONICALIZATION_MEASURED",
            severity="info",
            fields=fields,
        )
        return result

    setattr(wrapped, "__atlas_s0_phase2_canonicalization__", True)
    setattr(wrapped, "__atlas_s0_phase2_delegate__", delegate)
    return wrapped


def _wrap_provider_process(delegate: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(delegate, "__atlas_s0_phase2_provider__", False):
        return delegate

    @wraps(delegate)
    async def wrapped(*args: object, **kwargs: object):
        service = args[0] if args else None
        request = args[1] if len(args) > 1 else kwargs.get("request")
        retained = getattr(request, "retained_source", None)
        run_id = _safe_identity(getattr(request, "processing_attempt_id", None))
        document_id = _safe_identity(getattr(retained, "document_id", None))
        provider_job_id = _safe_identity(getattr(request, "provider_job_id", None))
        canonicalizer_configured = getattr(service, "canonicalizer", None) is not None

        wall_started = perf_counter()
        cpu_started = process_time()
        try:
            outcome = await delegate(*args, **kwargs)
        except BaseException as exc:
            fields: dict[str, object] = {
                "succeeded": False,
                "canonicalizer_configured": canonicalizer_configured,
                "error_type": type(exc).__name__,
                **_measurement_fields(
                    wall_started=wall_started,
                    cpu_started=cpu_started,
                ),
            }
            if provider_job_id is not None:
                fields["provider_job_id"] = provider_job_id
            _record(
                processing_run_id=run_id,
                document_id=document_id,
                event_name="PDF_S0_PROVIDER_INTEGRATION_MEASURED",
                severity="error",
                fields=fields,
            )
            raise

        fields = {
            "succeeded": getattr(outcome, "error", None) is None,
            "canonicalizer_configured": canonicalizer_configured,
            **_measurement_fields(
                wall_started=wall_started,
                cpu_started=cpu_started,
            ),
        }
        if provider_job_id is not None:
            fields["provider_job_id"] = provider_job_id
        poll_count = getattr(outcome, "poll_count", None)
        if isinstance(poll_count, int) and not isinstance(poll_count, bool) and poll_count >= 0:
            fields["poll_count"] = poll_count
        raw_size = getattr(outcome, "raw_result_size_bytes", None)
        if isinstance(raw_size, int) and not isinstance(raw_size, bool) and raw_size >= 0:
            fields["raw_result_size_bytes"] = raw_size
        status = getattr(outcome, "provider_terminal_status", None)
        status_value = getattr(status, "value", status)
        if isinstance(status_value, str) and status_value:
            fields["provider_status"] = status_value[:64]
        _record(
            processing_run_id=run_id,
            document_id=document_id,
            event_name="PDF_S0_PROVIDER_INTEGRATION_MEASURED",
            severity=("info" if fields["succeeded"] else "error"),
            fields=fields,
        )
        return outcome

    setattr(wrapped, "__atlas_s0_phase2_provider__", True)
    setattr(wrapped, "__atlas_s0_phase2_delegate__", delegate)
    return wrapped


def install_s0_phase2_stage_observability() -> None:
    """Install low-frequency durable measurements around existing delegates."""
    global _INSTALLED
    if _INSTALLED:
        return

    from app.processing import pdf_canonicalization as canonicalization
    from app.processing import pdf_geometry_integration as geometry
    from app.processing import pdf_page_presentation_preprocess_compat as classification
    from app.processing import integration

    classification._classify_source_pages = _wrap_classification(
        classification._classify_source_pages
    )
    geometry.prepare_geometry_provider_input = _wrap_preprocessing(
        geometry.prepare_geometry_provider_input
    )
    canonicalization.PdfCanonicalizationService.canonicalize = _wrap_canonicalization(
        canonicalization.PdfCanonicalizationService.canonicalize
    )
    integration.EndToEndProcessingIntegrationService.process = _wrap_provider_process(
        integration.EndToEndProcessingIntegrationService.process
    )
    _INSTALLED = True


__all__ = [
    "install_s0_phase2_stage_observability",
]
