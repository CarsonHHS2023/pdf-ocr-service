# S0.3.7 collector admission review — 2026-09-19

Status: **Two reproduced admission defects remain open; PR #48's narrow fix passes local current-Staging composition tests.**

## Scope and pinned sources

- Backend Staging: `090f1f075b7ef356f3066e29848415c7db559a93`.
- PR #48 head: `5ee14ed5d106a8aff86ecc190475de017a701a3e`, still Draft, unmerged.
- Scope: bounded SQL event loading, upload/Reader payload admission and the exact
  Reader join. TXT's separate strict envelope adapter is a source-level comparison,
  not a new full TXT audit.
- Existing [upload/Reader review](s0-3-7-upload-reader-contract-review-2026-09-11.md)
  and [small TXT acceptance](s0-txt-worker-small-acceptance-2026-09-19.md)
  retain their original provenance.

The local source snapshot used Git blob-verified raw files and the Staging
integration workflow's overlay sequence, including the TXT overlay. Tests used
synthetic in-memory SQLite, not the live database, HF, Provider or a new upload.
The PR #48 variant substitutes exactly its two changed files into that composed
current-Staging source. This is a local compatibility check, not a new GitHub
merge-artifact CI run or deployment.

## P2 — Validate Reader scope before filtering the exact join

Source:
[`measure_upload_reader`](https://github.com/CarsonHHS2023/pdf-ocr-service/blob/090f1f075b7ef356f3066e29848415c7db559a93/app/s0_upload_reader_metrics.py#L122-L124).

The selection comprehension drops known Reader-family events whose payload has
no matching `open_scope_id` before validating those events. Given otherwise valid
six-event evidence, append another `S0_READER_OPEN_TERMINAL` with payload `{}`
or `{"open_scope_id": null}`. The composed collector still marks
`upload_to_reader_ready_seconds` **observed**, while its Reader latency and query
metrics correctly become **not_available**. Such an unassignable terminal cannot
be proven to belong to a different open; silently excluding it hides possible
conflicting evidence. This is valid JSON, so JSON-decode failure detection does
not catch it.

A same-scope `S0_READER_OPEN_UNRECOGNIZED` event is also silently ignored by
both validators. The sibling upload family already rejects an unknown name.

Fix direction: admit the complete Reader family and validate names and minimally
valid scope identities before selecting the exact open. Missing/invalid scope
identity must fail closed. Define unknown-family rejection explicitly in both
Reader and upload validators. Keep unrelated event families and separately
identified valid opens out of the upload's interval; do not simply require every
Reader open in the run to be complete.

## P2 — Preserve and validate the upload event envelope in collection

Sources:
[`_load_bounded_event_rows`](https://github.com/CarsonHHS2023/pdf-ocr-service/blob/090f1f075b7ef356f3066e29848415c7db559a93/app/processing/s0_baseline.py#L643-L692),
[writer-side checks](https://github.com/CarsonHHS2023/pdf-ocr-service/blob/090f1f075b7ef356f3066e29848415c7db559a93/app/s0_upload_reader_persistence.py#L51-L69).

The bounded SQL projection omits schema, page and event ID; the decoded event
also drops severity. Start with real synthetic acceptance/terminal writes through
the production persistence functions, then independently change only the upload
terminal's schema to `unsupported.v99`, page to `1`, severity to `error`, or ID
to a noncanonical slot. Every variant is still **observed** at 120.25 seconds.
These envelopes violate checks already enforced by the upload writer.

Fix direction: retain bounded envelope metadata through collection and validate
schema, page, severity and deterministic upload slot identity before admission,
alongside the existing exact run/document SQL predicates. Do not materialize
unbounded payload TEXT or infer envelope validity from payload validity.
The TXT adapter already provides a separate strict-envelope design; it does not
retroactively protect upload/Reader rows.

These are collector robustness defects under malformed or conflicting durable
evidence. No public injection route or corruption of accepted live evidence was
demonstrated. The earlier live upload/Reader envelope audit remains valid.

## Controls and PR #48 disposition

| Synthetic case | Current Staging upload status | With PR #48 | Interpretation |
|---|---|---|---|
| Complete valid evidence, 120.25 s / 1.5 s | observed | observed | Positive control preserved |
| Upload 1 s, Reader 1.5 s | observed | not_available | PR #48 fixes its stated defect |
| Equal upload/Reader duration, 1.5 s | observed | observed | Clock precision boundary preserved |
| Missing/null Reader scope on an extra known terminal | observed | observed | First finding remains |
| Same-scope unknown Reader-family name | observed | observed | First finding's family admission gap |
| Invalid upload schema/page/severity/slot, separately | observed | observed | Second finding remains |
| Unknown upload-family event | not_available | not_available | Family rejection control |
| Duplicate upload terminal | not_available | not_available | Ambiguity rejection control |
| Malformed JSON / payload 8,193 bytes | not_available | not_available | Decode/byte-bound controls |
| Six events with max_events=5 | not_available | not_available | Truncation control |
| Unrelated-family event | observed | observed | Unrelated evidence is not confused with this family |

The 16-case probe was run against both variants. Existing focused upload/Reader
suites: **49 passed, 1 skipped** on current Staging; **53 passed, 1 skipped** with
PR #48. The skip is the isolated PostgreSQL gate; no local PostgreSQL concurrency
claim is made. The additional four passing cases are PR #48's duration boundaries;
its composed regression also passes.

PR #48 remains a valid narrow correction with no new blocker found in that diff.
The two findings above predate it; they are not regressions introduced by #48.
Do not describe its successful tests as full S0.3.7 completion or deploy it
implicitly. Plan the admission-hardening fix next, with composed regression
coverage for both findings, while retaining the valid-other-open control.

PR #47 documentation head `f680efe17cf88c2cca83f46d8fb98175f55e31b7` passed all
four workflows:
[Transport](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35460890300),
[Provider 20 MiB](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35460890303),
[Durable Events](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35460890298),
[Integration](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35460890328).
Integration and artifact verification passed; deploy was skipped. This does not
claim CI for the later documentation commit containing this review.

## Remaining scope

Full transport/compute/failure-retry/worker-CPU/visual-generation contract review,
cross-family snapshot consistency, revision trust, relational candidate admission
and privacy review beyond the inspected path remain open. The upload writer also
uses a SQL LIKE prefix and ORM row loading; its full boundedness review is outside
these two reproduced collector findings. No S0 closure, full upload memory or
complete preprocessing CPU claim follows. Accepted S0 remains **17/19**.

## Reproduction

Save the following as `audit_probe.py` in the source snapshot after applying its
Staging workflow overlays, install the repository's test dependencies, then run
`PYTHONPATH=. python audit_probe.py`. To reproduce the PR #48 variant, substitute
only its metric module and existing upload/Reader test file. All rows are
synthetic and each case uses a fresh in-memory SQLite database.

```python
"""Local review probe: synthetic SQLite only; no runtime/provider/network work."""
import json
from types import SimpleNamespace as NS
from app import s0_upload_reader_metrics as c
from app import s0_upload_reader_persistence as p
from app.processing.processing_event_model import ProcessingEvent
from app.processing.s0_baseline import collect_s0_run_snapshot
from sqlalchemy.orm import sessionmaker
from tests.test_s0_baseline import _session, _metric
from tests.test_s0_upload_reader_observability import seed, rows, request, ROOT, FRONT, SHA

KEYS = ('upload_to_reader_ready_seconds', 'reader_open_latency_seconds', 'reader_bounded_query_count')

def run(case):
    db = _session()
    try:
        run_id = seed(db)
        factory = sessionmaker(bind=db.get_bind())
        assert p.accept('dispatch-test', ROOT, FRONT, SHA, session_factory=factory)
        assert p.terminal('doc-s0', request(), SHA, session_factory=factory) == 204
        for n, row in enumerate(rows()[2:]):
            db.add(ProcessingEvent(id=f'reader-audit-{n}', processing_run_id=run_id,
                document_id='doc-s0', schema_version='atlas.processing.event.v1',
                event_name=row.event_name, severity='info', payload_json=json.dumps(row.payload)))
        db.commit()
        terminal = db.query(ProcessingEvent).filter_by(event_name=c.TERMINAL).one()
        if case.startswith('envelope_'):
            key, val = {'envelope_schema': ('schema_version', 'unsupported.v99'),
                'envelope_page': ('page_number', 1), 'envelope_severity': ('severity', 'error'),
                'envelope_slot': ('id', 'noncanonical-upload-slot')}[case]
            setattr(terminal, key, val)
        elif case in ('missing_reader_scope', 'invalid_reader_scope'):
            payload = {} if case == 'missing_reader_scope' else {'open_scope_id': None}
            db.add(ProcessingEvent(id='ambiguous-reader', processing_run_id=run_id, document_id='doc-s0',
                schema_version='atlas.processing.event.v1', event_name='S0_READER_OPEN_TERMINAL',
                severity='info', payload_json=json.dumps(payload)))
        elif case in ('unknown_reader', 'unknown_upload', 'unrelated_event'):
            name = {'unknown_reader': 'S0_READER_OPEN_UNRECOGNIZED',
                'unknown_upload': 'S0_UPLOAD_READER_UNRECOGNIZED',
                'unrelated_event': 'UNRELATED_AUDIT_CONTROL'}[case]
            db.add(ProcessingEvent(id='extra-audit', processing_run_id=run_id, document_id='doc-s0',
                schema_version='atlas.processing.event.v1', event_name=name, severity='info',
                payload_json=json.dumps({'open_scope_id': request()['open_scope_id']})))
        elif case == 'shorter_duration':
            payload = json.loads(terminal.payload_json); payload['duration_seconds'] = 1.0
            terminal.payload_json = json.dumps(payload)
        elif case == 'equal_duration':
            payload = json.loads(terminal.payload_json); payload['duration_seconds'] = 1.5
            terminal.payload_json = json.dumps(payload)
        elif case == 'duplicate_terminal':
            db.add(ProcessingEvent(id='duplicate-audit', processing_run_id=run_id, document_id='doc-s0',
                schema_version='atlas.processing.event.v1', event_name=c.TERMINAL, severity='info',
                payload_json=terminal.payload_json))
        elif case == 'malformed_json': terminal.payload_json = '{'
        elif case == 'oversized': terminal.payload_json = 'x' * 8193
        db.commit()
        snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id,
            **({'max_events': 5} if case == 'truncated' else {}))
        return {key: {'status': _metric(snapshot, key).status, 'value': _metric(snapshot, key).value} for key in KEYS}
    finally:
        db.close()

if __name__ == '__main__':
    cases = ('valid', 'shorter_duration', 'equal_duration', 'envelope_schema', 'envelope_page',
        'envelope_severity', 'envelope_slot', 'unknown_reader', 'unknown_upload',
        'unrelated_event', 'missing_reader_scope', 'invalid_reader_scope',
        'duplicate_terminal', 'malformed_json', 'oversized', 'truncated')
    print(json.dumps({case: run(case) for case in cases}, indent=2))
```
