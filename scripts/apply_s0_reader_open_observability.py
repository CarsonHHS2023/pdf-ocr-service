"""Compose S0.3.5 after S0.3.4; raw Production routes remain unchanged."""
from pathlib import Path
try:
    from scripts.apply_s0_provider_compute_observability import _patch
except ModuleNotFoundError:
    from apply_s0_provider_compute_observability import _patch


def main():
    # Capture only already-built view identity; no extra query in the measured path.
    _patch(Path('app/routers/reader_v2.py'), [
        ('        return build_selected_reader_v2_document(session=db, document_ref=document_ref)',
         '        from app.s0_reader_open_observability import observe_reader_view\n'
         '        return observe_reader_view(build_selected_reader_v2_document(session=db, document_ref=document_ref))'),
    ])
    anchor = 'app.include_router(reader_v2.router)\n'
    _patch(Path('app/main.py'), [(anchor, anchor +
        'from app.s0_reader_open_observability import install as install_s0_reader_open\n'
        'install_s0_reader_open(app)\n')])
    import_anchor = 'from app.s0_provider_compute_observability import ('
    event_anchor = '        _S0_OCR_BATCH_EVENT,\n'
    measure_anchor = '    missing_required_specs: dict[str, tuple[str, str]] = {\n'
    additions = '''        "reader_open_latency_seconds": _metric(
            "reader_open_latency_seconds", value=reader_open["latency"], status=reader_open["status"],
            source="processing_events.S0_READER_OPEN_TERMINAL.duration_seconds",
            note=reader_open["note"],
        ),
        "reader_bounded_query_count": _metric(
            "reader_bounded_query_count", value=reader_open["queries"], status=reader_open["status"],
            source="processing_events.S0_READER_OPEN_REQUEST_MEASURED.query_count",
            note=reader_open["note"],
        ),
'''
    snapshot_anchor = '    auxiliary.append(MetricReading(\n        key="provider_compute_breakdown",'
    _patch(Path('app/processing/s0_baseline.py'), [
        (import_anchor, 'from app.s0_reader_open_observability import (\n'
         '    REQUEST_EVENT as _S0_READER_REQUEST_EVENT, TERMINAL_EVENT as _S0_READER_TERMINAL_EVENT,\n'
         '    measure_reader_open as _measure_reader_open,\n)\n' + import_anchor),
        (event_anchor, '        _S0_READER_REQUEST_EVENT,\n        _S0_READER_TERMINAL_EVENT,\n' + event_anchor),
        (measure_anchor, '    reader_open = _measure_reader_open(\n'
         '        decoded_events_tuple, evidence_incomplete=payload_evidence_incomplete,\n'
         '        uninspectable_event_names=uninspectable_event_names_frozen,\n    )\n    required_by_key.update({\n' + additions + '    })\n\n' + measure_anchor),
        (snapshot_anchor, '    auxiliary.append(MetricReading(\n'
         '        key="reader_open_breakdown", label="Reader core open operations", unit=None,\n'
         '        status=reader_open["status"], value=reader_open["breakdown"],\n'
         '        source="processing_events.S0_READER_OPEN_*", note=reader_open["note"],\n    ))\n\n' + snapshot_anchor),
    ])

    _patch(Path('tests/test_s0_baseline.py'), [(
        'assert _metric(snapshot, "reader_open_latency_seconds").status == "not_instrumented"',
        'assert _metric(snapshot, "reader_open_latency_seconds").status == "not_available"',
    )])


if __name__ == '__main__':
    main()
