"""Compose upload/Reader observation after the existing visual-generation overlay."""
from pathlib import Path
try:
    from scripts.apply_s0_visual_asset_generation_observability import _patch
except ModuleNotFoundError:
    from apply_s0_visual_asset_generation_observability import _patch


def main():
    anchor = "install_s0_reader_open(app)\n"
    _patch(Path("app/main.py"), [(anchor, anchor +
        "from app.s0_upload_reader_observability import install as install_s0_upload_reader\n"
        "install_s0_upload_reader(app)\n")])
    # Insert outside every predecessor's complete installed block. Their
    # idempotence checks intentionally fail if a later overlay splits a block.
    import_anchor = "from dataclasses import asdict, dataclass\n"
    decode_anchor = ('        if row.event_name.startswith("S0_VISUAL_ASSET_GENERATION_"):\n'
        '            payload, decode_valid = decode_visual_asset_generation_payload(row.payload_json)\n')
    mapping_anchor = "    visual_asset_generation = _measure_visual_asset_generation(\n"
    aux_anchor = '    auxiliary.append(MetricReading(\n        key="failure_retry_breakdown",'
    _patch(Path("app/processing/s0_baseline.py"), [
        (import_anchor, "from app.s0_upload_reader_metrics import (\n"
            "    EVENT_NAMES as _UPLOAD_READER_EVENTS, decode_payload as _decode_upload_reader,\n"
            "    measure_upload_reader as _measure_upload_reader, source_scope_id as _upload_reader_source_scope,\n"
            ")\n" + import_anchor),
        ("        *_VISUAL_ASSET_GENERATION_EVENTS,\n", "        *_UPLOAD_READER_EVENTS,\n        *_VISUAL_ASSET_GENERATION_EVENTS,\n"),
        (decode_anchor, decode_anchor + '        if row.event_name.startswith(("S0_UPLOAD_READER_", "S0_READER_OPEN_")):\n'
            '            payload, decode_valid = _decode_upload_reader(row.payload_json)\n'),
        (mapping_anchor, "    upload_reader = _measure_upload_reader(\n"
            "        decoded_events_tuple, expected_source_scope=_upload_reader_source_scope(run.source_file_id),\n"
            "        run_status=run.status, evidence_incomplete=payload_evidence_incomplete,\n"
            "        uninspectable_event_names=uninspectable_event_names_frozen,\n"
            "    )\n"
            '    required_by_key["upload_to_reader_ready_seconds"] = _metric(\n'
            '        "upload_to_reader_ready_seconds", value=upload_reader["value"], status=upload_reader["status"],\n'
            '        source="processing_events.S0_UPLOAD_READER_TERMINAL.duration_seconds", note=upload_reader["note"],\n'
            "    )\n\n" + mapping_anchor),
        (aux_anchor, '    auxiliary.append(MetricReading(\n'
            '        key="upload_reader_breakdown", label="Upload to initial semantic render", unit=None,\n'
            '        status=upload_reader["status"], value=upload_reader["breakdown"],\n'
            '        source="processing_events.S0_UPLOAD_READER_*", note=upload_reader["note"],\n'
            '    ))\n\n' + aux_anchor),
    ])
    _patch(Path("tests/test_s0_baseline.py"), [(
        'assert _metric(snapshot, "upload_to_reader_ready_seconds").status == "not_instrumented"',
        'assert _metric(snapshot, "upload_to_reader_ready_seconds").status == "not_available"')])


if __name__ == "__main__":
    main()
