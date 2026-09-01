"""Compose Staging-only S0.3.3 Provider source-transport observability."""
from __future__ import annotations

from pathlib import Path

INTEGRATION_PATH = Path("app/processing/integration.py")
SOURCE_TRANSPORT_PATH = Path("app/routers/source_transport.py")
BASELINE_PATH = Path("app/processing/s0_baseline.py")

_INTEGRATION_ANCHOR = '''        try:\n            transport_url = None\n            if self.source_transport_url_factory is not None:\n                transport_url = self.source_transport_url_factory(self.source_access_ttl)\n                if transport_url is not None and not isinstance(transport_url, TemporarySourceTransportUrl):\n                    raise IntegrationError(\n                        IntegrationErrorCategory.URL_CONSTRUCTION_FAILURE,\n                        "source transport URL factory returned an invalid value",\n                    )\n            if transport_url is None:\n                if origin is None:\n                    origin = TrustedPublicSourceOrigin(self._origin_value)\n                transport_url = build_temporary_source_transport_url(origin, created.token)\n'''
_INTEGRATION_BLOCK = '''        try:\n            transport_url = None\n            source_transport_route = "atlas_source_transport_fallback"\n            if self.source_transport_url_factory is not None:\n                transport_url = self.source_transport_url_factory(self.source_access_ttl)\n                if transport_url is not None and not isinstance(transport_url, TemporarySourceTransportUrl):\n                    raise IntegrationError(\n                        IntegrationErrorCategory.URL_CONSTRUCTION_FAILURE,\n                        "source transport URL factory returned an invalid value",\n                    )\n                if transport_url is not None:\n                    source_transport_route = "presigned_object_get"\n            if transport_url is None:\n                if origin is None:\n                    origin = TrustedPublicSourceOrigin(self._origin_value)\n                transport_url = build_temporary_source_transport_url(origin, created.token)\n            try:\n                from app.s0_transport_download_observability import (\n                    record_provider_source_route_selected,\n                )\n                record_provider_source_route_selected(grant, source_transport_route)\n            except Exception:\n                # S0 telemetry must never affect Provider URL selection or execution.\n                pass\n'''
_RESPONSE_ANCHOR = '''    response = Response(\n        content=payload,\n'''
_RESPONSE_BLOCK = '''    from app.s0_transport_download_observability import (\n        bind_source_transport_response,\n        build_source_transport_response,\n    )\n    response = build_source_transport_response(\n        Response,\n        content=payload,\n'''
_RESPONSE_RETURN_ANCHOR = '''    except Exception:\n        # S0 telemetry must never affect the provider source response.\n        pass\n\n    return response\n'''
_RESPONSE_RETURN_BLOCK = '''    except Exception:\n        # S0 telemetry must never affect the provider source response.\n        pass\n\n    try:\n        bind_source_transport_response(response, grant, retrieval_ordinal)\n    except Exception:\n        # Missing send-boundary telemetry fails closed in the collector only.\n        pass\n\n    return response\n'''
_IMPORT_ANCHOR = '''from app.s0_transport_scope_terminal_observability import (\n    TRANSPORT_SCOPE_TERMINAL_EVENT as _S0_TRANSPORT_SCOPE_TERMINAL_EVENT,\n)\n'''
_IMPORT_BLOCK = '''from app.s0_transport_download_observability import (\n    BACKEND_BODY_EVENT as _S0_BACKEND_BODY_EVENT,\n    SOURCE_ROUTE_EVENT as _S0_SOURCE_ROUTE_EVENT,\n    measure_backend_source_transport as _measure_backend_source_transport,\n)\n''' + _IMPORT_ANCHOR
_SAFE_EVENT_ANCHOR = '''        _S0_TRANSPORT_SCOPE_TERMINAL_EVENT,\n    }\n) | _PHASE2_MEASUREMENT_EVENT_NAMES\n'''
_SAFE_EVENT_BLOCK = '''        _S0_TRANSPORT_SCOPE_TERMINAL_EVENT,\n        _S0_SOURCE_ROUTE_EVENT,\n        _S0_BACKEND_BODY_EVENT,\n    }\n) | _PHASE2_MEASUREMENT_EVENT_NAMES\n'''
_SAFE_NUMERIC_ANCHOR = '''        "terminal_retrieval_count",\n    }\n)\n_NONNEGATIVE_EVENT_FIELDS'''
_SAFE_NUMERIC_BLOCK = '''        "terminal_retrieval_count",\n        "source_object_size_bytes",\n        "body_bytes",\n        "body_messages",\n    }\n)\n_NONNEGATIVE_EVENT_FIELDS'''
_NONNEGATIVE_ANCHOR = '''        "terminal_retrieval_count",\n    }\n)\n\n\n@dataclass'''
_NONNEGATIVE_BLOCK = '''        "terminal_retrieval_count",\n        "source_object_size_bytes",\n        "body_bytes",\n        "body_messages",\n    }\n)\n\n\n@dataclass'''
_MEASUREMENT_ANCHOR = '''    preprocessing_wall_measurement = _event_measurement(\n'''
_MEASUREMENT_BLOCK = '''    (\n        backend_source_transport_bytes,\n        source_transport_breakdown,\n        _provider_selected_payload_from_transport,\n        source_transport_status,\n        source_transport_note,\n    ) = _measure_backend_source_transport(\n        decoded_events_tuple,\n        evidence_incomplete=payload_evidence_incomplete,\n        uninspectable_event_names=uninspectable_event_names_frozen,\n    )\n\n    preprocessing_wall_measurement = _event_measurement(\n'''
_REQUIRED_ANCHOR = '''        "preprocessing_wall_seconds": _metric(\n'''
_REQUIRED_BLOCK = '''        "backend_to_modal_transport_bytes": _metric(\n            "backend_to_modal_transport_bytes",\n            value=backend_source_transport_bytes,\n            status=source_transport_status,\n            source=(\n                "processing_events.S0_PROVIDER_SOURCE_ROUTE_SELECTED + "\n                "S0_BACKEND_SOURCE_BODY_TRANSMITTED + "\n                "S0_OBJECT_STORE_TRANSPORT_SCOPE_TERMINAL"\n            ),\n            note=_combine_notes(\n                "Legacy metric key retained for compatibility. Value is exact Provider source-body bytes whose ASGI body-send completed at the Atlas fallback boundary; presigned scopes contribute zero. It excludes HTTP/TLS framing and does not prove consumer-side download bytes.",\n                source_transport_note,\n            ),\n        ),\n        "modal_download_seconds": _metric(\n            "modal_download_seconds",\n            value=None,\n            status="not_available",\n            source="external Provider/compute source-download telemetry contract",\n            note=(\n                "The current Provider API exposes source URL input and OCR lifecycle state but no authoritative source-download elapsed time; compute-side download code is outside this repository, so Provider integration wall time is not substituted."\n            ),\n        ),\n        "preprocessing_wall_seconds": _metric(\n'''
_MISSING_BACKEND = '''        "backend_to_modal_transport_bytes": (\n            "transport instrumentation",\n            "Provider input bytes are not equivalent to backend-to-Modal network bytes, which are not durably separated from other provider/source routes.",\n        ),\n'''
_MISSING_DOWNLOAD = '''        "modal_download_seconds": (\n            "Modal instrumentation",\n            "Modal download timing is not available in backend durable state.",\n        ),\n'''
_PROVIDER_SELECTED_ANCHOR = '''    raw_result_size = _event_measurement(\n'''
_PROVIDER_SELECTED_BLOCK = '''    provider_selected_payload_size = _event_measurement(\n        decoded_events_tuple,\n        event_name="PDF_PROVIDER_TRANSPORT_SHARDING_DECISION",\n        field="provider_input_size_bytes",\n        evidence_incomplete=payload_evidence_incomplete,\n        uninspectable_event_names=uninspectable_event_names_frozen,\n    )\n    raw_result_size = _event_measurement(\n'''
_AUX_ANCHOR = '''        MetricReading(\n            key="raw_result_size_bytes",\n'''
_AUX_BLOCK = '''        MetricReading(\n            key="provider_selected_payload_bytes",\n            label="Provider-selected source payload size",\n            unit="bytes",\n            status=provider_selected_payload_size.status,\n            value=provider_selected_payload_size.value,\n            source="processing_events.PDF_PROVIDER_TRANSPORT_SHARDING_DECISION.payload.provider_input_size_bytes",\n            note=_combine_notes(\n                "Bytes selected for Provider source delivery after local page exclusion; this is distinct from the full preprocessed artifact, per-scope source object sizes, Backend ASGI body bytes, and consumer download bytes.",\n                provider_selected_payload_size.note,\n            ),\n        ),\n        MetricReading(\n            key="provider_source_transport_breakdown",\n            label="Provider source transport route breakdown",\n            unit=None,\n            status=source_transport_status,\n            value=source_transport_breakdown,\n            source="processing_events.S0_PROVIDER_SOURCE_ROUTE_SELECTED + S0_BACKEND_SOURCE_BODY_TRANSMITTED + terminal proof",\n            note=_combine_notes(\n                "Per-scope allowlisted route, source object size, final Backend fallback retrieval count, and exact Backend ASGI source-body bytes. Presigned object size is not consumer download bytes.",\n                source_transport_note,\n            ),\n        ),\n        MetricReading(\n            key="provider_source_download_bytes",\n            label="Provider/compute source download bytes",\n            unit="bytes",\n            status="not_available",\n            value=None,\n            source="external Provider/compute source-download telemetry contract",\n            note="No authoritative consumer-side source-download byte counter is exposed by the current Provider API or this Backend repository; object size and Backend ASGI send bytes are not substituted.",\n        ),\n        MetricReading(\n            key="provider_source_download_seconds",\n            label="Provider/compute source download elapsed time",\n            unit="seconds",\n            status="not_available",\n            value=None,\n            source="external Provider/compute source-download telemetry contract",\n            note="No authoritative consumer-side source-download timer is exposed by the current Provider API or this Backend repository; Provider integration wall time is not substituted.",\n        ),\n        MetricReading(\n            key="raw_result_size_bytes",\n'''
_BASELINE_FINAL_MARKERS = (
    "_S0_SOURCE_ROUTE_EVENT,",
    "_S0_BACKEND_BODY_EVENT,",
    '"backend_to_modal_transport_bytes": _metric(',
    'key="provider_source_transport_breakdown"',
    'key="provider_source_download_bytes"',
)


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique S0.3.3 anchor: {label}")
    return source.replace(old, new, 1)


def patch_integration(path: Path = INTEGRATION_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    if "record_provider_source_route_selected(grant, source_transport_route)" in source:
        return
    source = _replace_once(source, _INTEGRATION_ANCHOR, _INTEGRATION_BLOCK, "Provider route selection")
    path.write_text(source, encoding="utf-8")


def patch_source_transport(path: Path = SOURCE_TRANSPORT_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    if "bind_source_transport_response(response, grant, retrieval_ordinal)" in source:
        return
    if "record_retrieval_with_ordinal(token)" not in source:
        raise RuntimeError("S0.3.3 source transport must be composed after S0.3.2 atomic retrieval instrumentation")
    source = _replace_once(source, _RESPONSE_ANCHOR, _RESPONSE_BLOCK, "observed Response construction")
    source = _replace_once(source, _RESPONSE_RETURN_ANCHOR, _RESPONSE_RETURN_BLOCK, "observed Response binding")
    path.write_text(source, encoding="utf-8")


def patch_baseline(path: Path = BASELINE_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    if all(marker in source for marker in _BASELINE_FINAL_MARKERS):
        return
    if any(marker in source for marker in _BASELINE_FINAL_MARKERS):
        raise RuntimeError("S0.3.3 baseline mapping is only partially installed")
    if "def _s0_storage_io_measurement(" not in source:
        raise RuntimeError("S0.3.3 collector must be composed after S0.3.2 storage I/O mapping")
    source = _replace_once(source, _IMPORT_ANCHOR, _IMPORT_BLOCK, "collector imports")
    source = _replace_once(source, _SAFE_EVENT_ANCHOR, _SAFE_EVENT_BLOCK, "safe event names")
    source = _replace_once(source, _SAFE_NUMERIC_ANCHOR, _SAFE_NUMERIC_BLOCK, "safe numeric fields")
    source = _replace_once(source, _NONNEGATIVE_ANCHOR, _NONNEGATIVE_BLOCK, "nonnegative fields")
    source = _replace_once(source, _MEASUREMENT_ANCHOR, _MEASUREMENT_BLOCK, "transport extraction")
    source = _replace_once(source, _REQUIRED_ANCHOR, _REQUIRED_BLOCK, "required transport mapping")
    source = _replace_once(source, _MISSING_BACKEND, "", "obsolete Backend transport missing metric")
    source = _replace_once(source, _MISSING_DOWNLOAD, "", "explicit compute download unavailable metric")
    source = _replace_once(source, _PROVIDER_SELECTED_ANCHOR, _PROVIDER_SELECTED_BLOCK, "Provider-selected payload auxiliary")
    source = _replace_once(source, _AUX_ANCHOR, _AUX_BLOCK, "transport auxiliary breakdown")
    if not all(marker in source for marker in _BASELINE_FINAL_MARKERS):
        raise RuntimeError("S0.3.3 baseline mapping did not reach final contract")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    patch_integration()
    patch_source_transport()
    patch_baseline()


if __name__ == "__main__":
    main()
