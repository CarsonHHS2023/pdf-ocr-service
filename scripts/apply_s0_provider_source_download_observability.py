"""Compose the Provider/compute half of S0.3.3 into Atlas Staging runtime."""
from __future__ import annotations

from pathlib import Path

ORCHESTRATION_PATH = Path("app/processing/orchestration.py")
BASELINE_PATH = Path("app/processing/s0_baseline.py")

_ORCHESTRATION_ANCHOR = '''            if not result.raw_provider_payload and not result.documents and not result.result_artifact and result.status != ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED:\n                raise OrchestrationError(OrchestrationErrorCategory.RESULT_MALFORMED, "provider result contained no inline payload or artifact metadata", OrchestrationPhase.RETRIEVING_RESULT, request.provider_job_id, result.status.value)\n            return result, polls, terminal\n'''
_ORCHESTRATION_BLOCK = '''            if not result.raw_provider_payload and not result.documents and not result.result_artifact and result.status != ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED:\n                raise OrchestrationError(OrchestrationErrorCategory.RESULT_MALFORMED, "provider result contained no inline payload or artifact metadata", OrchestrationPhase.RETRIEVING_RESULT, request.provider_job_id, result.status.value)\n            try:\n                from app.s0_provider_source_download_observability import (\n                    record_provider_source_download_from_result,\n                )\n                record_provider_source_download_from_result(request, result)\n            except Exception:\n                # S0 telemetry must never alter Provider result retrieval semantics.\n                pass\n            return result, polls, terminal\n'''

_IMPORT_ANCHOR = '''from app.s0_transport_scope_terminal_observability import (\n'''
_IMPORT_BLOCK = '''from app.s0_provider_source_download_observability import (\n    PROVIDER_DOWNLOAD_EVENT as _S0_PROVIDER_DOWNLOAD_EVENT,\n    measure_provider_source_download as _measure_provider_source_download,\n)\n''' + _IMPORT_ANCHOR

_SAFE_EVENT_ANCHOR = '''        _S0_SOURCE_ROUTE_EVENT,\n        _S0_BACKEND_BODY_EVENT,\n    }\n) | _PHASE2_MEASUREMENT_EVENT_NAMES\n'''
_SAFE_EVENT_BLOCK = '''        _S0_SOURCE_ROUTE_EVENT,\n        _S0_BACKEND_BODY_EVENT,\n        _S0_PROVIDER_DOWNLOAD_EVENT,\n    }\n) | _PHASE2_MEASUREMENT_EVENT_NAMES\n'''

_SAFE_NUMERIC_ANCHOR = '''        "body_bytes",\n        "body_messages",\n    }\n)\n_NONNEGATIVE_EVENT_FIELDS'''
_SAFE_NUMERIC_BLOCK = '''        "body_bytes",\n        "body_messages",\n        "download_bytes",\n        "download_duration_seconds",\n    }\n)\n_NONNEGATIVE_EVENT_FIELDS'''

_NONNEGATIVE_ANCHOR = '''        "body_bytes",\n        "body_messages",\n    }\n)\n\n\n@dataclass'''
_NONNEGATIVE_BLOCK = '''        "body_bytes",\n        "body_messages",\n        "download_bytes",\n        "download_duration_seconds",\n    }\n)\n\n\n@dataclass'''

_MEASUREMENT_ANCHOR = '''    preprocessing_wall_measurement = _event_measurement(\n'''
_MEASUREMENT_BLOCK = '''    (\n        provider_source_download_bytes,\n        provider_source_download_seconds,\n        provider_source_download_breakdown,\n        provider_source_download_status,\n        provider_source_download_note,\n    ) = _measure_provider_source_download(\n        decoded_events_tuple,\n        transport_breakdown=source_transport_breakdown,\n        evidence_incomplete=payload_evidence_incomplete,\n        uninspectable_event_names=uninspectable_event_names_frozen,\n    )\n\n    preprocessing_wall_measurement = _event_measurement(\n'''

_MODAL_PLACEHOLDER = '''        "modal_download_seconds": _metric(\n            "modal_download_seconds",\n            value=None,\n            status="not_available",\n            source="external Provider/compute source-download telemetry contract",\n            note=(\n                "The current Provider API exposes source URL input and OCR lifecycle state but no authoritative source-download elapsed time; compute-side download code is outside this repository, so Provider integration wall time is not substituted."\n            ),\n        ),\n'''
_MODAL_MEASURED = '''        "modal_download_seconds": _metric(\n            "modal_download_seconds",\n            value=provider_source_download_seconds,\n            status=provider_source_download_status,\n            source="processing_events.S0_PROVIDER_SOURCE_DOWNLOAD_MEASURED.payload.download_duration_seconds",\n            note=_combine_notes(\n                "Legacy metric key retained for compatibility. Value is the sum of Provider/compute source-download operation durations across the validated Provider transport scopes; it is not Provider integration wall time and not an end-to-end critical-path duration when downloads overlap.",\n                provider_source_download_note,\n            ),\n        ),\n'''

_AUX_BYTES_PLACEHOLDER = '''        MetricReading(\n            key="provider_source_download_bytes",\n            label="Provider/compute source download bytes",\n            unit="bytes",\n            status="not_available",\n            value=None,\n            source="external Provider/compute source-download telemetry contract",\n            note="No authoritative consumer-side source-download byte counter is exposed by the current Provider API or this Backend repository; object size and Backend ASGI send bytes are not substituted.",\n        ),\n'''
_AUX_BYTES_MEASURED = '''        MetricReading(\n            key="provider_source_download_bytes",\n            label="Provider/compute source download bytes",\n            unit="bytes",\n            status=provider_source_download_status,\n            value=provider_source_download_bytes,\n            source="processing_events.S0_PROVIDER_SOURCE_DOWNLOAD_MEASURED.payload.download_bytes",\n            note=_combine_notes(\n                "Exact bytes read by Provider compute from each source URL, validated as a multiset against Atlas per-scope source object sizes. This is distinct from Provider-selected payload bytes and Backend fallback ASGI body bytes.",\n                provider_source_download_note,\n            ),\n        ),\n'''

_AUX_SECONDS_PLACEHOLDER = '''        MetricReading(\n            key="provider_source_download_seconds",\n            label="Provider/compute source download elapsed time",\n            unit="seconds",\n            status="not_available",\n            value=None,\n            source="external Provider/compute source-download telemetry contract",\n            note="No authoritative consumer-side source-download timer is exposed by the current Provider API or this Backend repository; Provider integration wall time is not substituted.",\n        ),\n'''
_AUX_SECONDS_MEASURED = '''        MetricReading(\n            key="provider_source_download_seconds",\n            label="Provider/compute source download elapsed time",\n            unit="seconds",\n            status=provider_source_download_status,\n            value=provider_source_download_seconds,\n            source="processing_events.S0_PROVIDER_SOURCE_DOWNLOAD_MEASURED.payload.download_duration_seconds",\n            note=_combine_notes(\n                "Sum of the validated Provider source-download operation durations. This aggregate is an operation-duration sum, not Provider integration wall time.",\n                provider_source_download_note,\n            ),\n        ),\n        MetricReading(\n            key="provider_source_download_breakdown",\n            label="Provider/compute source download breakdown",\n            unit=None,\n            status=provider_source_download_status,\n            value=provider_source_download_breakdown,\n            source="processing_events.S0_PROVIDER_SOURCE_DOWNLOAD_MEASURED",\n            note=_combine_notes(\n                "Privacy-safe per-Provider-scope download bytes and duration after exact transport-scope byte-multiset validation.",\n                provider_source_download_note,\n            ),\n        ),\n'''

_FINAL_BASELINE_MARKERS = (
    "_S0_PROVIDER_DOWNLOAD_EVENT,",
    '"download_duration_seconds",',
    "_measure_provider_source_download(",
    'value=provider_source_download_seconds,',
    'key="provider_source_download_breakdown"',
)


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique S0.3.3 Provider-download anchor: {label}")
    return source.replace(old, new, 1)


def patch_orchestration(path: Path = ORCHESTRATION_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    if "record_provider_source_download_from_result(request, result)" in source:
        return
    source = _replace_once(source, _ORCHESTRATION_ANCHOR, _ORCHESTRATION_BLOCK, "Provider result retrieval")
    path.write_text(source, encoding="utf-8")


def patch_baseline(path: Path = BASELINE_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    if all(marker in source for marker in _FINAL_BASELINE_MARKERS):
        return
    if any(marker in source for marker in _FINAL_BASELINE_MARKERS):
        raise RuntimeError("S0.3.3 Provider-download collector mapping is only partially installed")
    if "measure_backend_source_transport as _measure_backend_source_transport" not in source:
        raise RuntimeError("Provider-download mapping must be composed after Atlas source-transport mapping")

    source = _replace_once(source, _IMPORT_ANCHOR, _IMPORT_BLOCK, "collector import")
    source = _replace_once(source, _SAFE_EVENT_ANCHOR, _SAFE_EVENT_BLOCK, "safe event name")
    source = _replace_once(source, _SAFE_NUMERIC_ANCHOR, _SAFE_NUMERIC_BLOCK, "safe numeric fields")
    source = _replace_once(source, _NONNEGATIVE_ANCHOR, _NONNEGATIVE_BLOCK, "nonnegative fields")
    source = _replace_once(source, _MEASUREMENT_ANCHOR, _MEASUREMENT_BLOCK, "Provider download extraction")
    source = _replace_once(source, _MODAL_PLACEHOLDER, _MODAL_MEASURED, "required Modal download metric")
    source = _replace_once(source, _AUX_BYTES_PLACEHOLDER, _AUX_BYTES_MEASURED, "auxiliary Provider download bytes")
    source = _replace_once(source, _AUX_SECONDS_PLACEHOLDER, _AUX_SECONDS_MEASURED, "auxiliary Provider download duration")

    if not all(marker in source for marker in _FINAL_BASELINE_MARKERS):
        raise RuntimeError("S0.3.3 Provider-download collector mapping did not reach final contract")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    patch_orchestration()
    patch_baseline()


if __name__ == "__main__":
    main()
