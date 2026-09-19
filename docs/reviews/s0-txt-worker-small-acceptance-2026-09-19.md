# S0 TXT worker timing — small live acceptance

| Field | Value |
|---|---|
| Record date / execution date | 2026-09-19 / 2026-09-16 UTC |
| Result | Scoped worker-timing acceptance PASS; Reader display confirmed by user |
| Backend runtime | `090f1f075b7ef356f3066e29848415c7db559a93` |
| Frontend Preview supplied for this check | `086cda854c24680ea4ce1c414844f10af2c14dcf` |
| Retained TXT bytes | 64,476 |
| Run | `txt-ingest-3beff206052e4e5db58ac5ebcea67975` |
| Document | `0febda9a-2f17-4280-a85c-44b4aaa589ef` |
| Source | `b057d15d-cf5e-4048-8e1d-782e87d4b69d` |
| Dispatch / attempt | `f432fc2b-f004-4fd9-981e-fead03f9b048` / 1 |
| Candidate | `scv2_txt_9bc0c3804537ae5df0ef0325` |
| Worker duration | 23,639,366,950 ns = **23.63936695 s** |

## Runtime and verification provenance

[Backend PR #49](https://github.com/CarsonHHS2023/pdf-ocr-service/pull/49)
implemented the worker observer, bounded durable persistence and read-only
auxiliary adapter. Its final source head was
`a4924db3a9a9382487b60b0cad6d5988e72bd7d2`.
[Deployment run 35093211333](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35093211333)
passed integration, artifact verification and deployment for the runtime revision
above. Deploy job `104784699662` verified that exact HF revision at
2026-09-16T12:01:14.9336927Z. Matching event revisions corroborate this provenance;
this record does not claim a new direct health check.

The evidence audit used bounded SQL projections in one PostgreSQL
REPEATABLE READ, READ ONLY transaction in the Staging database. It checked exact
run/document/source association, dispatch and candidate uniqueness, source-unit
provenance and the complete TXT event family. SQL-side payload byte checks and
cap-plus-one reads guarded materialization. No source text was downloaded and
no database writes were performed.

Independent in-memory contract checks covered field allowlists, strict types,
identity/status joins, scope digests and deterministic UUIDv5 event slots.
This live audit did **not** invoke the native Python collector or produce an
`atlas.s0.baseline.v1` report. Its result is durable worker-event acceptance,
not an exact-source collector replay. Composed native collector behavior was
tested separately in PR #49 CI.

The user confirmed that Reader body and table of contents display normally.
That is user-reported UI evidence; no independent browser observation, exact
browser-loaded revision check or TXT automatic-first-open timing is claimed.

## Durable evidence

Exactly two family events were present, with no invalidation or extra family row:

| Event | Ordinal | Event ID | Persisted UTC | Payload bytes |
|---|---:|---|---|---:|
| STARTED | 0 | `5674a036-4ae3-562c-a4ef-c62b30bd08f5` | 2026-09-16T12:19:25.373272 | 503 |
| TERMINAL | 1 | `222c7787-0404-5bb4-8880-3075af8ad338` | 2026-09-16T12:19:50.491605 | 665 |

Both use contract `atlas.s0.txt-worker-wall.v1`, method
`same_worker_perf_counter_ns_v1`, scope
`txt_worker_configuration_to_canonical_commit_v1`, worker
`txtw_60e8670973b44dd0bb4e8d8d3808bd3a`, the exact backend revision and matching
source/dispatch digests. The terminal outcome is `completed`, reason `none`,
with the duration above and the exact candidate digest. Envelopes use
`atlas.processing.event.v1`, severity `info`, null page and exact run/document.

Run and dispatch were `succeeded`; Document was `completed`.
The single retained TXT source had positive byte size. Exactly one candidate
matched run/document/SPR provenance; source units existed and none referred to
a different source or a kind other than `text_flow`. Current selection was
consistent with the candidate but was not substituted for provenance validation.

The run's lifecycle start and completion are still the same late timestamp,
`2026-09-16T12:19:43.901788`. Neither those timestamps, event insertion times nor
dispatch times were used to calculate the worker duration.

## Accepted scope and remaining gates

The [deployed contract](https://github.com/CarsonHHS2023/pdf-ocr-service/blob/090f1f075b7ef356f3066e29848415c7db559a93/docs/testing/s0-txt-worker-wall-observability-v1.md)
defines the same-worker interval from analyzer configuration through committed
canonicalization, including existing analysis/storage waits. It excludes upload,
queue/claim wait, observer writes, final book-state publication and Reader work.
Its pre-rollout status text is superseded by this dated acceptance record.

This is one small live TXT control, **not formal `txt-small-v1` fixture acceptance**.
The [registry](../testing/s0-benchmark-fixtures-v1.md) lists 89,396 bytes for that
fixture; this source is 64,476 bytes and private fixture checksum identity was
not established. Do not overwrite the registered fixture or claim medium,
multi-window/outline, concurrent or failure-path runtime coverage from this run.
Private filename, content, checksum and storage reference are excluded here.

The auxiliary `txt_ingestion_worker_wall_seconds` does not add a required PDF
metric. The accepted PDF snapshot remains **17/19**: complete upload peak memory
and complete preprocessing CPU remain `not_instrumented`. TXT upload-to-Reader
timing and a formal representative TXT baseline remain open. S0/M5 stay
**In Progress**; see the [current handoff](../plans/s0-remaining-attribution-decisions-2026-09-11.md).
