"""Compose S0.3.4 into the exact tested Staging artifact after S0.3.3."""
from pathlib import Path


def _patch(path, replacements):
    source = path.read_text(encoding="utf-8")
    present = [new in source for _, new in replacements]
    if all(present):
        return
    if any(present):
        raise RuntimeError("S0.3.4 Backend overlay is partially installed")
    for old, new in replacements:
        if source.count(old) != 1:
            raise RuntimeError("S0.3.4 Backend anchor is not unique")
        source = source.replace(old, new, 1)
    path.write_text(source, encoding="utf-8")


def main():
    orchestration_path = Path("app/processing/orchestration.py")
    if "record_provider_compute_from_result(request, result)" in orchestration_path.read_text(encoding="utf-8"):
        raise RuntimeError("Legacy synchronous S0.3.4 hook found; recompose from a pristine checkout")
    anchor = '            try:\n                from app.s0_provider_source_download_observability import ('
    _patch(orchestration_path, [(anchor,
        '            try:\n                from app.s0_provider_compute_observability import record_provider_compute_from_result_async\n'
        '                await record_provider_compute_from_result_async(request, result)\n'
        '            except Exception:\n                # Observability must never change result retrieval.\n                pass\n' + anchor)])
    import_anchor = 'from app.s0_provider_source_download_observability import ('
    event_anchor = '        _S0_PROVIDER_DOWNLOAD_EVENT,\n'
    measure_anchor = '    preprocessing_wall_measurement = _event_measurement(\n'
    required_anchor = '    required_by_key: dict[str, MetricReading] = {\n'
    required = '''        "ocr_batch_duration_seconds": _metric(
            "ocr_batch_duration_seconds", value=provider_compute["ocr_seconds"], status=provider_compute["status"],
            source="processing_events.S0_PROVIDER_OCR_BATCH_MEASURED.predict_seconds",
            note=_combine_notes("Sum of worker pipeline.predict operation durations including generator consumption; excludes download, queue, initialization, restructuring and polling. Overlapping batches do not imply critical-path time.", provider_compute["note"]),
        ),
        "raw_result_shard_bytes": _metric(
            "raw_result_shard_bytes", value=provider_compute["raw_bytes"], status=provider_compute["status"],
            source="processing_events.S0_PROVIDER_OCR_SCOPE_TERMINAL.raw_result_json_bytes",
            note=_combine_notes("Sum of per-Provider-shard sanitized raw page-list UTF-8 JSON sizes before profile slimming; excludes HTTP envelopes, compression and artifact wrappers. See per-shard breakdown.", provider_compute["note"]),
        ),
        "gpu_busy_idle_proxy": _metric(
            "gpu_busy_idle_proxy", value=provider_compute["gpu"], status=provider_compute["gpu_status"],
            source="processing_events.S0_PROVIDER_OCR_BATCH_MEASURED.gpu",
            note=_combine_notes("Device NVML sample-window utilization during predict, sampled every second. Weighted sample mean and nonzero sample fraction; not GPU active seconds, spatial occupancy, process attribution or between-job idle time. Every batch requires at least two valid samples; missing probes remain unavailable.", provider_compute["note"]),
        ),
'''
    aux_anchor = '    return S0RunSnapshot(\n'
    numeric_fields = ''.join(f'        "{key}",\n' for key in ("predict_seconds", "raw_result_json_bytes", "ordinal", "batch_count"))
    numeric_anchor = '        "download_duration_seconds",\n    }\n)\n_NONNEGATIVE_EVENT_FIELDS'
    nonnegative_anchor = '        "download_duration_seconds",\n    }\n)\n\n\n@dataclass'
    _patch(Path("app/processing/s0_baseline.py"), [
        (numeric_anchor, numeric_fields + numeric_anchor),
        (nonnegative_anchor, numeric_fields + nonnegative_anchor),
        (import_anchor, 'from app.s0_provider_compute_observability import (\n    BATCH_EVENT as _S0_OCR_BATCH_EVENT, TERMINAL_EVENT as _S0_OCR_TERMINAL_EVENT,\n    measure_provider_compute as _measure_provider_compute,\n)\n' + import_anchor),
        (event_anchor, '        _S0_OCR_BATCH_EVENT,\n        _S0_OCR_TERMINAL_EVENT,\n' + event_anchor),
        (measure_anchor, '    provider_compute = _measure_provider_compute(\n        decoded_events_tuple, download_breakdown=provider_source_download_breakdown,\n        evidence_incomplete=payload_evidence_incomplete,\n        uninspectable_event_names=uninspectable_event_names_frozen,\n    )\n\n' + measure_anchor),
        (required_anchor, required_anchor + required),
        (aux_anchor, '    auxiliary.append(MetricReading(\n        key="provider_compute_breakdown", label="Provider OCR batches and raw shards", unit=None,\n        status=provider_compute["status"], value=provider_compute["breakdown"],\n        source="processing_events.S0_PROVIDER_OCR_BATCH_MEASURED + S0_PROVIDER_OCR_SCOPE_TERMINAL",\n        note=provider_compute["note"],\n    ))\n\n' + aux_anchor),
    ])


if __name__ == "__main__":
    main()
