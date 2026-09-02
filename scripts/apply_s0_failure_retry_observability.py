"""Compose S0.3.6 only into the tested Staging artifact; fail on anchor drift."""
from pathlib import Path


def _patch(path, replacements):
    source = path.read_text(encoding="utf-8")
    installed = [new in source for _, new in replacements]
    if all(installed):
        return
    if any(installed):
        raise RuntimeError(f"S0.3.6 partially installed: {path}")
    for old, new in replacements:
        if source.count(old) != 1:
            raise RuntimeError(f"S0.3.6 anchor missing/nonunique: {path}")
        source = source.replace(old, new, 1)
    path.write_text(source, encoding="utf-8")


def main():
    anchor = "    async def run_once(self, request: OrchestrationRequest, policy: PollingPolicy | None = None) -> OrchestrationOutcome:\n"
    _patch(Path("app/processing/orchestration.py"), [
        ("from __future__ import annotations\n", "from __future__ import annotations\n\n"
         "from app.s0_failure_retry_observability import observe_orchestration, observe_provider_call\n"),
        (anchor, anchor + "        return await observe_orchestration(self._run_once_without_s036, request, policy)\n\n"
         "    async def _run_once_without_s036(self, request, policy):\n"),
        *[(f"await self.provider.{method}(", f'await observe_provider_call("{op}", self.provider.{method}, ')
          for op, method in (("submit", "submit_job"), ("status", "get_job_status"),
                             ("result", "get_job_result"), ("artifact", "get_job_artifact"))],
    ])
    # Hook after a committed document terminal; no extra state query or mutation.
    anchor = '        _diagnostic(\n            "PDF_DOCUMENT_STATE_UPDATED",\n'
    end_anchor = 'install_s0_object_store_pdf_observability()\n'
    _patch(Path("app/processing/pdf_ingestion.py"), [
        (anchor, '        from app.s0_failure_retry_observability import note_pdf_terminal\n'
         '        note_pdf_terminal(document_id, status)\n' + anchor),
        (end_anchor, end_anchor + '\nfrom app.s0_failure_retry_observability import install_pdf_observability\n'
         'install_pdf_observability()\n'),
    ])
    # Prepend to (not inside) S0.3.5's installed block, preserving its idempotence.
    anchor = '    reader_open = _measure_reader_open(\n'
    aux_anchor = '    auxiliary.append(MetricReading(\n        key="reader_open_breakdown",'
    _patch(Path("app/processing/s0_baseline.py"), [
        ('from app.s0_reader_open_metrics import (',
         'from app.s0_failure_retry_metrics import EVENT_NAMES as _S036_EVENTS, measure_failure_retry\n'
         'from app.s0_failure_retry_observability import source_scope_id as _s036_source_scope\n'
         'from app.s0_reader_open_metrics import ('),
        ('        _S0_READER_REQUEST_EVENT,\n', '        *_S036_EVENTS,\n        _S0_READER_REQUEST_EVENT,\n'),
        (anchor, '    failure_retry = measure_failure_retry(\n'
         '        decoded_events_tuple, source_scope_id=_s036_source_scope(run.source_file_id),\n'
         '        evidence_incomplete=payload_evidence_incomplete,\n'
         '        uninspectable_event_names=uninspectable_event_names_frozen,\n    )\n'
         '    required_by_key["failure_retry_counts"] = _metric(\n'
         '        "failure_retry_counts", value=failure_retry["value"], status=failure_retry["status"],\n'
         '        source="processing_events.S0_FAILURE_RETRY_*", note=failure_retry["note"],\n    )\n\n' + anchor),
        (aux_anchor, '    auxiliary.append(MetricReading(\n'
         '        key="failure_retry_breakdown", label="Backend-owned failure/retry scopes", unit=None,\n'
         '        status=failure_retry["status"], value=failure_retry["breakdown"],\n'
         '        source="processing_events.S0_FAILURE_RETRY_*", note=failure_retry["note"],\n    ))\n\n' + aux_anchor),
    ])


if __name__ == "__main__":
    main()
