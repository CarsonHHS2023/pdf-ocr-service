# S0 preprocessing worker-CPU small acceptance — 2026-09-04

| Field | Value |
|---|---|
| Result | **Worker-thread auxiliary PASS; S0 and M5 remain In Progress** |
| Backend Staging revision | `ee2f48d83972bfd978060b40b3729b4b6b8405d4` |
| Processing run | `pdf-ingest-a9982db262c0426bb0e5eac5d5077a73` |
| Document | `ed9008c4-fab7-4878-9253-1b8a962ad55f` |
| Source file | `dfa8c630-cccc-49da-828e-2b4d1b61a5b9` |
| Run result | `succeeded`; one PDF page |
| Started / completed | `2026-09-04T13:33:27.498Z` / `2026-09-04T13:35:30.756Z` |

## Evidence and collector result

The exact tested artifact was deployed by [Staging Backend Integration CI run
33793672727](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/33793672727).
Its integration, artifact-verification and deploy jobs succeeded, including the
pre/post Staging-head guards and exact Hugging Face runtime revision check.

Read-only Neon queries locked the fresh terminal run above and exported its full
durable event set. Replaying those exact rows through the deployed strict S0
collector produced:

| Metric | Status | Value |
|---|---|---:|
| `preprocessing_worker_thread_cpu_seconds` | `observed` | `21.996906251 s` |
| `preprocessing_worker_thread_cpu_breakdown` | `observed` | one completed worker scope |
| `preprocessing_cpu_seconds` | `not_instrumented` | no value |

The four worker-CPU events form one root with ordinals `0,1,2,3`. The terminal
scope records `cpu_delta_ns=21996906251`, `clock_status=measured`,
`operation_outcome=completed`, and `clock_resolution_ns=1`. The root terminal is
complete with one scope and `issue=none`. All events bind to the exact Staging
revision and the run's hashed source identity.

The bounded-event loader reported no truncation, malformed JSON, oversized
payload or decode incompleteness. The largest relevant payload was 563 bytes;
there were no duplicate scope/ordinal pairs and no filename, path, URL, token,
credential or raw storage-reference fields.

## Related transport control and limits

The same run independently retained `784772` original source bytes, sent
`982161` preprocessed bytes through one completed Backend fallback ASGI body, and
recorded `982161` Provider-download bytes in `0.947113` seconds. Equality of the
last two counters is a single-download control result; the three byte meanings
remain independent.

This acceptance covers the current synchronous worker thread only. It does not
cover native helper threads, child processes or full stage-owned CPU and cannot
promote the required `preprocessing_cpu_seconds` row. It does not authorize S1,
S2, Production rollout, another fixture run, or a 100-page/528-page benchmark.
