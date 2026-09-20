"""Install TXT timing only in the composed Staging artifact, idempotently."""
from pathlib import Path


def _patch(path, pairs):
    original = Path(path).read_text()
    installed = [new in original for old, new in pairs]
    if all(installed):
        return
    if any(installed):
        raise RuntimeError(f"TXT observer partially installed: {path}")
    source = original
    for old, new in pairs:
        if source.count(old) != 1:
            raise RuntimeError(f"TXT observer anchor drift: {path}")
        source = source.replace(old, new, 1)
    Path(path).write_text(source)


def main():
    _patch("app/processing/ingestion_dispatch.py", [(
        "            await asyncio.to_thread(\n                txt_processor,\n                claim.document_id,\n                claim.source_file_id,\n                ids,\n            )",
        "            from app.s0_txt_worker_observability import invoke as _invoke_txt_worker\n"
        "            await asyncio.to_thread(\n                _invoke_txt_worker,\n                txt_processor,\n"
        "                claim.document_id,\n                claim.source_file_id,\n                ids,\n"
        "                claim=claim,\n                session_factory=session_factory,\n            )",
    )])
    _patch("app/processing/txt/ingestion.py", [(
        "    try:\n        analyzer = build_production_txt_structure_analyzer()",
        "    from app.s0_txt_worker_observability import admit, begin, finish\n"
        "    observation = admit(document_id, source_file_id, ingestion_ids)\n"
        "    try:\n        begin(observation)\n        analyzer = build_production_txt_structure_analyzer()",
    ), (
        "    except (TxtIngestionConfigurationError, TxtStructureAnalyzerClientError, TxtCanonicalizationError) as exc:\n",
        "        finish(observation, outcome)\n"
        "    except (TxtIngestionConfigurationError, TxtStructureAnalyzerClientError, TxtCanonicalizationError) as exc:\n"
        "        finish(observation, reason=(\"configuration_error\" if isinstance(exc, TxtIngestionConfigurationError)\n"
        "                                    else \"canonicalization_error\"))\n",
    ), (
        "    except Exception as exc:  # pragma: no cover - final production safety boundary\n",
        "    except Exception as exc:  # pragma: no cover - final production safety boundary\n"
        "        finish(observation, reason=\"unexpected_error\")\n",
    ), (
        '    _set_document_terminal_state(document_id, status="completed", error_message=None)',
        '    except BaseException:\n        finish(observation, reason="worker_interrupted")\n        raise\n\n'
        '    _set_document_terminal_state(document_id, status="completed", error_message=None)',
    )])
    # Append a wrapper instead of splitting another overlay's installed block.
    # Earlier overlays verify whole replacement strings when re-run.
    path = Path("app/processing/s0_baseline.py")
    block = '''
# S0 TXT worker auxiliary collector wrapper v1
_s0_collect_without_txt_worker = collect_s0_run_snapshot


def collect_s0_run_snapshot(session, *, processing_run_id: str, max_events: int = DEFAULT_MAX_EVENTS):
    snapshot = _s0_collect_without_txt_worker(session, processing_run_id=processing_run_id, max_events=max_events)
    if snapshot.file_type != "txt":
        return snapshot
    from dataclasses import replace
    from app.s0_txt_worker_persistence import collect as _collect_txt_worker
    txt_worker = _collect_txt_worker(session.get_bind(), snapshot.processing_run_id)
    metric = MetricReading(
        key="txt_ingestion_worker_wall_seconds", label="TXT canonical worker wall time",
        unit="seconds", status=txt_worker.status, value=txt_worker.value,
        source="processing_events.S0_TXT_WORKER_*",
        note="Configuration through canonical commit; excludes upload, queue, document/dispatch finalization and Reader delivery. "
             "Independent read-only consistent TXT projection: " + txt_worker.reason,
    )
    return replace(snapshot, auxiliary_metrics=(*snapshot.auxiliary_metrics, metric))
'''
    source = path.read_text()
    if block in source:
        return
    if "# S0 TXT worker auxiliary collector wrapper v1" in source:
        raise RuntimeError("TXT collector wrapper partially installed")
    path.write_text(source.rstrip() + "\n" + block)



if __name__ == "__main__":
    main()
