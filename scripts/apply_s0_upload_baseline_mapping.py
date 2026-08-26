"""Install the Staging S0 canonical-upload baseline mapping.

The checked-in S0 collector is intentionally read-only. Staging builds already
compose observability overlays before the exact tested artifact is packaged; this
patch follows that established contract so the artifact's collector can consume
the durable canonical-upload measurement without changing upload behavior.
"""
from __future__ import annotations

from pathlib import Path


BASELINE_PATH = Path("app/processing/s0_baseline.py")

_IMPORT_ANCHOR = (
    "from app.processing.processing_events import MAX_EVENT_PAYLOAD_BYTES\n"
)
_IMPORT_BLOCK = (
    "from app.processing.processing_events import MAX_EVENT_PAYLOAD_BYTES\n"
    "from app.s0_upload_boundary_observability import (\n"
    "    CANONICAL_UPLOAD_ROUTE as _S0_CANONICAL_UPLOAD_ROUTE,\n"
    "    UPLOAD_MEASUREMENT_EVENT as _S0_UPLOAD_MEASUREMENT_EVENT,\n"
    "    UPLOAD_MEASUREMENT_SCOPE as _S0_UPLOAD_MEASUREMENT_SCOPE,\n"
    "    UPLOAD_MEMORY_COMPONENT_SCOPE as _S0_UPLOAD_MEMORY_COMPONENT_SCOPE,\n"
    ")\n"
)
_SAFE_EVENT_ANCHOR = '        "PDF_S0_RESOURCE_HEARTBEAT",\n'
_SAFE_EVENT_BLOCK = (
    '        "PDF_S0_RESOURCE_HEARTBEAT",\n'
    "        _S0_UPLOAD_MEASUREMENT_EVENT,\n"
)
_SAFE_NUMERIC_ANCHOR = '        "size_bytes",\n'
_SAFE_NUMERIC_BLOCK = (
    '        "size_bytes",\n'
    '        "accepted_source_size_bytes",\n'
    '        "http_body_bytes_received",\n'
    '        "max_asgi_receive_chunk_bytes",\n'
    '        "max_uploadfile_read_bytes",\n'
    '        "upload_duration_seconds",\n'
    '        "uploadfile_read_total_bytes",\n'
)
_NONNEGATIVE_ANCHOR = (
    '        "provider_input_size_bytes",\n'
    '        "raw_result_size_bytes",\n'
    "    }\n"
    ")\n"
)
_NONNEGATIVE_BLOCK = (
    '        "provider_input_size_bytes",\n'
    '        "raw_result_size_bytes",\n'
    '        "accepted_source_size_bytes",\n'
    '        "http_body_bytes_received",\n'
    '        "max_asgi_receive_chunk_bytes",\n'
    '        "max_uploadfile_read_bytes",\n'
    '        "upload_duration_seconds",\n'
    '        "uploadfile_read_total_bytes",\n'
    "    }\n"
    ")\n"
)
_HELPER_ANCHOR = "def _phase2_process_lifetime_peak(\n"
_HELPER_BLOCK = '''def _s0_upload_event_measurement(
    decoded_events: Iterable[_DecodedEvent],
    *,
    field: str,
    expected_source_size: object,
    evidence_incomplete: bool,
    uninspectable_event_names: frozenset[str],
) -> _EventMeasurement:
    """Extract one strict canonical-upload measurement by exact durable contract."""
    if _S0_UPLOAD_MEASUREMENT_EVENT in uninspectable_event_names:
        return _EventMeasurement(
            value=None,
            status="not_available",
            note=(
                f"At least one retained {_S0_UPLOAD_MEASUREMENT_EVENT} payload could not "
                "be inspected; the collector cannot rule out ambiguous upload evidence."
            ),
        )

    matching = [
        event
        for event in decoded_events
        if event.event_name == _S0_UPLOAD_MEASUREMENT_EVENT
    ]
    if not matching:
        return _EventMeasurement(
            value=None,
            status="not_available",
            note=f"No bounded {_S0_UPLOAD_MEASUREMENT_EVENT} event is retained for this run.",
        )
    if len(matching) != 1:
        return _EventMeasurement(
            value=None,
            status="not_available",
            note=(
                f"Expected exactly one bounded {_S0_UPLOAD_MEASUREMENT_EVENT} event; "
                "the collector does not select among duplicate upload measurements."
            ),
        )

    payload = matching[0].payload
    if payload.get("succeeded") is not True:
        return _EventMeasurement(
            value=None,
            status="not_available",
            note="The retained canonical-upload measurement is not a successful measurement.",
        )
    if payload.get("upload_route") != _S0_CANONICAL_UPLOAD_ROUTE:
        return _EventMeasurement(
            value=None,
            status="not_available",
            note="The retained upload measurement does not identify the canonical multipart route.",
        )
    if payload.get("measurement_scope") != _S0_UPLOAD_MEASUREMENT_SCOPE:
        return _EventMeasurement(
            value=None,
            status="not_available",
            note="The retained upload measurement has an unsupported timing scope.",
        )

    if (
        not isinstance(expected_source_size, int)
        or isinstance(expected_source_size, bool)
        or expected_source_size <= 0
    ):
        return _EventMeasurement(
            value=None,
            status="not_available",
            note="The canonical upload measurement cannot be checked against a positive retained source size.",
        )
    accepted_size = payload.get("accepted_source_size_bytes")
    if (
        not isinstance(accepted_size, int)
        or isinstance(accepted_size, bool)
        or accepted_size != expected_source_size
    ):
        return _EventMeasurement(
            value=None,
            status="not_available",
            note="The canonical upload measurement source size does not match the ProcessingRun source.",
        )

    if field in {"max_uploadfile_read_bytes", "uploadfile_read_total_bytes"}:
        if payload.get("memory_component_scope") != _S0_UPLOAD_MEMORY_COMPONENT_SCOPE:
            return _EventMeasurement(
                value=None,
                status="not_available",
                note="The retained UploadFile.read component has an unsupported memory-component scope.",
            )

    value = _usable_numeric_event_value(field, payload.get(field))
    if value is None:
        return _EventMeasurement(
            value=None,
            status="not_available",
            note=(
                f"No usable successful bounded {_S0_UPLOAD_MEASUREMENT_EVENT}.{field} "
                "measurement is retained."
            ),
        )
    return _EventMeasurement(
        value=value,
        status="partial" if evidence_incomplete else "observed",
        note=(
            "The bounded event/payload evidence for this snapshot is incomplete."
            if evidence_incomplete
            else None
        ),
    )


'''
_MEASUREMENT_ANCHOR = '''    preprocessing_wall_measurement = _event_measurement(
'''
_MEASUREMENT_BLOCK = '''    upload_duration_measurement = _s0_upload_event_measurement(
        decoded_events_tuple,
        field="upload_duration_seconds",
        expected_source_size=source_size,
        evidence_incomplete=payload_evidence_incomplete,
        uninspectable_event_names=uninspectable_event_names_frozen,
    )
    upload_http_body_bytes = _s0_upload_event_measurement(
        decoded_events_tuple,
        field="http_body_bytes_received",
        expected_source_size=source_size,
        evidence_incomplete=payload_evidence_incomplete,
        uninspectable_event_names=uninspectable_event_names_frozen,
    )
    upload_max_read_bytes = _s0_upload_event_measurement(
        decoded_events_tuple,
        field="max_uploadfile_read_bytes",
        expected_source_size=source_size,
        evidence_incomplete=payload_evidence_incomplete,
        uninspectable_event_names=uninspectable_event_names_frozen,
    )

    preprocessing_wall_measurement = _event_measurement(
'''
_REQUIRED_ANCHOR = '''        "preprocessing_wall_seconds": _metric(
'''
_REQUIRED_BLOCK = '''        "upload_duration_seconds": _metric(
            "upload_duration_seconds",
            value=upload_duration_measurement.value,
            status=upload_duration_measurement.status,
            source=(
                "processing_events.S0_UPLOAD_ACCEPTANCE_MEASURED."
                "payload.upload_duration_seconds"
            ),
            note=_combine_notes(
                "Canonical multipart request ingress through durable source/Document acceptance; direct and resumable upload routes have separate boundaries and are not collapsed into this metric.",
                upload_duration_measurement.note,
            ),
        ),
        "preprocessing_wall_seconds": _metric(
'''
_MISSING_UPLOAD_BLOCK = '''        "upload_duration_seconds": (
            "upload instrumentation",
            "Upload start/end timing is not durably persisted.",
        ),
'''
_AUXILIARY_ANCHOR = '''        MetricReading(
            key="preprocessing_process_cpu_delta_seconds",
'''
_AUXILIARY_BLOCK = '''        MetricReading(
            key="canonical_upload_http_body_bytes_received",
            label="Canonical upload HTTP body bytes received",
            unit="bytes",
            status=upload_http_body_bytes.status,
            value=upload_http_body_bytes.value,
            source=(
                "processing_events.S0_UPLOAD_ACCEPTANCE_MEASURED."
                "payload.http_body_bytes_received"
            ),
            note=_combine_notes(
                "ASGI request-body bytes for the canonical multipart request, including multipart framing; this is not retained source size or backend-to-Modal transport.",
                upload_http_body_bytes.note,
            ),
        ),
        MetricReading(
            key="canonical_upload_max_uploadfile_read_bytes",
            label="Largest canonical UploadFile.read result",
            unit="bytes",
            status=upload_max_read_bytes.status,
            value=upload_max_read_bytes.value,
            source=(
                "processing_events.S0_UPLOAD_ACCEPTANCE_MEASURED."
                "payload.max_uploadfile_read_bytes"
            ),
            note=_combine_notes(
                "Exact bytes-object component returned by UploadFile.read during the canonical request; it is not process RSS and is not promoted to backend upload peak memory.",
                upload_max_read_bytes.note,
            ),
        ),
        MetricReading(
            key="preprocessing_process_cpu_delta_seconds",
'''
_FINAL_MARKERS = (
    "def _s0_upload_event_measurement(",
    'field="upload_duration_seconds"',
    '"upload_duration_seconds": _metric(',
    'key="canonical_upload_max_uploadfile_read_bytes"',
    "_S0_UPLOAD_MEASUREMENT_EVENT,",
)


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique S0 upload baseline anchor: {label}")
    return source.replace(old, new, 1)


def patch_s0_upload_baseline_mapping(path: Path = BASELINE_PATH) -> None:
    """Patch the collector exactly once and reject partial/ambiguous composition."""
    source = path.read_text(encoding="utf-8")
    if all(marker in source for marker in _FINAL_MARKERS):
        return
    if any(marker in source for marker in _FINAL_MARKERS):
        raise RuntimeError("S0 upload baseline mapping is only partially installed")

    source = _replace_once(
        source,
        _IMPORT_ANCHOR,
        _IMPORT_BLOCK,
        label="upload contract import",
    )
    source = _replace_once(
        source,
        _SAFE_EVENT_ANCHOR,
        _SAFE_EVENT_BLOCK,
        label="safe event allowlist",
    )
    source = _replace_once(
        source,
        _SAFE_NUMERIC_ANCHOR,
        _SAFE_NUMERIC_BLOCK,
        label="safe numeric field allowlist",
    )
    source = _replace_once(
        source,
        _NONNEGATIVE_ANCHOR,
        _NONNEGATIVE_BLOCK,
        label="nonnegative numeric fields",
    )
    source = _replace_once(
        source,
        _HELPER_ANCHOR,
        _HELPER_BLOCK + _HELPER_ANCHOR,
        label="strict upload measurement helper",
    )
    source = _replace_once(
        source,
        _MEASUREMENT_ANCHOR,
        _MEASUREMENT_BLOCK,
        label="upload measurement extraction",
    )
    source = _replace_once(
        source,
        _REQUIRED_ANCHOR,
        _REQUIRED_BLOCK,
        label="required upload duration mapping",
    )
    source = _replace_once(
        source,
        _MISSING_UPLOAD_BLOCK,
        "",
        label="obsolete upload not-instrumented fallback",
    )
    source = _replace_once(
        source,
        _AUXILIARY_ANCHOR,
        _AUXILIARY_BLOCK,
        label="upload auxiliary evidence",
    )

    if not all(marker in source for marker in _FINAL_MARKERS):
        raise RuntimeError("S0 upload baseline mapping did not reach the final contract")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    patch_s0_upload_baseline_mapping()


if __name__ == "__main__":
    main()
