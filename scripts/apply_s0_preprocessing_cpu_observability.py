"""Compose the worker CPU auxiliary only into Staging; exact idempotent anchors."""
from pathlib import Path


def _patch(path, replacements):
    source = path.read_text(encoding="utf-8")
    installed = [new in source for _, new in replacements]
    if all(installed):
        return
    if any(installed):
        raise RuntimeError(f"Worker CPU overlay partially installed: {path}")
    for old, new in replacements:
        if source.count(old) != 1:
            raise RuntimeError(f"Worker CPU overlay anchor drift: {path}")
        source = source.replace(old, new, 1)
    path.write_text(source, encoding="utf-8")


def main():
    future = "    concurrent_future.add_done_callback(job_state.on_worker_done)\n"
    submit = "            partial(\n                _prepare_geometry_provider_input_from_storage,\n"
    failed = "    except BaseException:\n        job_state.mark_consumed_or_failed()\n        raise\n\n"
    terminal = "        from app.s0_failure_retry_observability import note_pdf_terminal\n"
    install = "install_pdf_observability()\n"
    _patch(Path("app/processing/pdf_ingestion.py"), [
        ("from __future__ import annotations\n", "from __future__ import annotations\n\n"
         "from app.s0_preprocessing_cpu_observability import (\n"
         "    current_preprocessing_scope, run_preprocessing_worker, note_preprocessing_future,\n"
         "    note_preprocessing_submit_failed, note_cpu_terminal,\n)\n"),
        (submit, "            partial(\n                run_preprocessing_worker,\n"
         "                _prepare_geometry_provider_input_from_storage,\n"
         "                cpu_scope=current_preprocessing_scope(),\n"),
        (failed, "    except BaseException:\n        note_preprocessing_submit_failed()\n"
         "        job_state.mark_consumed_or_failed()\n        raise\n\n"),
        (future, "    note_preprocessing_future(concurrent_future)\n" + future),
        (terminal, "        note_cpu_terminal(document_id, locals().get(\"processing_attempt_id\"), status)\n" + terminal),
        (install, install + "\nfrom app.s0_preprocessing_cpu_observability import install_preprocessing_cpu_observability\n"
         "install_preprocessing_cpu_observability()\n"),
    ])
    path = Path("app/processing/s0_phase2_stage_observability.py")
    source = path.read_text(encoding="utf-8")
    begin, end = source.index("def _wrap_preprocessing("), source.index("def _wrap_canonicalization(")
    block = source[begin:end]
    measured = ("            from app.s0_preprocessing_cpu_observability import measure_preprocessing_delegate\n"
                "            result = measure_preprocessing_delegate(delegate, *args, **kwargs)\n")
    if measured not in block:
        if "measure_preprocessing_delegate(delegate, *args, **kwargs)" in block:
            raise RuntimeError("Worker CPU Phase 2 partially installed")
        old = "            result = delegate(*args, **kwargs)\n"
        if block.count(old) != 1:
            raise RuntimeError("Worker CPU Phase 2 boundary drift")
        block = block.replace(old, measured, 1)
        path.write_text(source[:begin] + block + source[end:], encoding="utf-8")
    anchor = "    auxiliary: list[MetricReading] = [\n"
    _patch(Path("app/processing/s0_baseline.py"), [
        ("from __future__ import annotations\n", "from __future__ import annotations\n\n"
         "from app.s0_preprocessing_cpu_metrics import (\n"
         "    EVENT_NAMES as _WORKER_CPU_EVENTS, measure_preprocessing_worker_cpu, source_scope_id as _worker_cpu_source_scope,\n)\n"),
        ('        payload, decode_valid = _decode_event_payload(row.payload_json)\n',
         '        if row.event_name.startswith("S0_PREPROCESS_CPU_"):\n'
         '            from app.s0_preprocessing_cpu_metrics import decode_worker_cpu_payload\n'
         '            payload, decode_valid = decode_worker_cpu_payload(row.payload_json)\n'
         '        else:\n            payload, decode_valid = _decode_event_payload(row.payload_json)\n'),
        ('        "PDF_DOCUMENT_TERMINAL_STATE",\n',
         '        *_WORKER_CPU_EVENTS,\n        "PDF_DOCUMENT_TERMINAL_STATE",\n'),
        (anchor, "    worker_cpu = measure_preprocessing_worker_cpu(\n"
         "        decoded_events_tuple, expected_source_scope=_worker_cpu_source_scope(source.id if source is not None else None),\n"
         "        run_status=run.status, evidence_incomplete=payload_evidence_incomplete,\n"
         "        uninspectable_event_names=uninspectable_event_names_frozen,\n    )\n\n" + anchor +
         "        MetricReading(\n            key=\"preprocessing_worker_thread_cpu_seconds\",\n"
         "            label=\"Preprocessing worker-thread CPU (excludes helpers)\", unit=\"seconds\",\n"
         "            status=worker_cpu[\"status\"], value=worker_cpu[\"value\"],\n"
         "            source=\"processing_events.S0_PREPROCESS_CPU_*\", note=worker_cpu[\"note\"],\n        ),\n"
         "        MetricReading(\n            key=\"preprocessing_worker_thread_cpu_breakdown\",\n"
         "            label=\"Worker-thread CPU scope evidence\", unit=None,\n"
         "            status=worker_cpu[\"status\"], value=worker_cpu[\"breakdown\"],\n"
         "            source=\"processing_events.S0_PREPROCESS_CPU_*\", note=worker_cpu[\"note\"],\n        ),\n"),
    ])


if __name__ == "__main__":
    main()
