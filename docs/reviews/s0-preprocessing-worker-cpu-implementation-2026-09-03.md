# S0 worker-thread CPU implementation candidate — 2026-09-03

Status: **implemented in Draft PR #43, not deployed or accepted**. This extends
the [attribution boundary](../testing/s0-preprocessing-cpu-attribution-v1.md) and
[bounded event protocol](../testing/s0-preprocessing-worker-cpu-events-v1.md).
The historical [feasibility report](s0-preprocessing-cpu-feasibility-2026-09-03.md)
remains source/probe evidence, not the runtime implementation result.

## Scope and actual wiring

- `app/s0_preprocessing_cpu_observability.py`: verified-Staging-revision gate,
  explicit metadata reference across raw executor submission, same-thread clock
  capture, bounded root/scope state, non-entry outcomes and late worker closure.
- `app/s0_preprocessing_cpu_metrics.py`: exact field/type/value checks, strict
  JSON decoding, unique root/ordinal/scope admission and worker-only aggregation.
- `scripts/apply_s0_preprocessing_cpu_observability.py`: idempotent Staging-only
  composition into ingestion, Phase 2 and the existing bounded collector. It is
  run after S0.3.6 in both final-composition paths. Raw application files are not
  modified in git; the generated tested artifact receives the hooks.
- S0 Baseline and Staging Backend Integration CI now execute the actual runtime
  contract tests. The integration workflow also tests the real executor bridge
  with a synthetic delegate and has a disposable PostgreSQL-only transaction
  test. Artifact verification checks the new modules and installed hooks.

Only `preprocessing_worker_thread_cpu_seconds` and its bounded breakdown are
added as auxiliaries. The required `preprocessing_cpu_seconds` remains
`not_instrumented`, as do the other three existing required gaps. No native helper
CPU, process-wide CPU or nested classification timing is silently added to it.

Normal per-root bound: eight requests / eighteen events. A single exceptional
`RUN_INVALIDATED` slot makes the absolute bound nineteen and causes rejection
of a previously closed root if it is unexpectedly reused. Processing itself is
not rejected or retried for telemetry overflow/failure. Source-read, admission,
submission and pre-entry cancellation do not fabricate a zero CPU interval.

The writer uses one fresh Session per publication and one transaction for all
scope terminals plus root terminal. Stable per-slot primary keys reject duplicate
insertion without a schema change. Run/document/source associations and exact
artifact revision are checked again at publication. New publication occurs after
existing Phase 2 wall/process measurement, not inside its timed delegate.

The real ProcessingRun success status is `succeeded`; the separate logical and
operation outcomes use `completed`. Collector admission explicitly preserves
that distinction. Missing evidence, malformed/oversized payloads, duplicate JSON
keys, truncated windows and mixed/invalid identities do not yield an observed sum.

## Local verification

Validation used CPython 3.11.15 with the repository's CI/test requirement files,
fresh disposable git checkouts and no live database credentials. Full runtime
composition followed the 15 Staging overlay scripts. Focused composition followed
the actual S0 Baseline workflow's application steps, including applying the new
overlay twice. No user fixture or external Provider was used.

| Check | Result | Limit |
|---|---|---|
| Raw-source CPU contract tests | 56 passed, 4 skipped | Four checks require the composed Phase 2/collector |
| Full-composition CPU + Phase 2 + S0.3.6 + deployment-contract tests | 142 passed, 1 skipped | Disposable PostgreSQL test awaits CI environment |
| Actual S0 Baseline focused test command | 343 passed | Local SQLite/synthetic evidence, not HF acceptance |
| Staging production-equivalent contract test command | 433 passed, 1 skipped | Existing suite's conditional coverage remains conditional |
| Staging Provider/sharding/S0 contract test command | 275 passed, 2 skipped | Includes PostgreSQL-gated test pending CI |

These suites overlap and must not be summed as independent test counts. Existing
SQLAlchemy relationship/deprecation warnings were emitted; this slice does not
modify unrelated ORM mappings.

The new tests cover measured/zero/unavailable clocks, large lifetime counters,
same-thread boundaries, reused workers, source failure before entry, cancellation
while running/queued/publishing, worker completion after event-loop shutdown,
one-time racing closure, overflow, post-closure invalidation, identity mismatch,
observer setup/publication failure, preservation of delegate exceptions, actual
composed alias/executor wiring, old Phase 2-before-new-publication ordering,
SQLite atomic rollback and duplicate insertion, source deletion, strict payload
decoding, SQL-side oversized-payload exclusion and bounded-window rejection.

The PostgreSQL regression refuses non-local hosts, uses the CI service only, and
creates/drops its own random schema. It exercises successful publication, forced
rollback after flush and duplicate-key rejection against real PostgreSQL. Its
executed result belongs to exact-head integration CI, not the local skipped run.
No Neon branch, production database or existing schema was altered locally.

## Review and release gates

Local self-review resolved incorrect raw success-status assumptions, duplicate
JSON-key admission, incomplete installer detection, large thread-lifetime clock
handling and cancellation masking a delegate exception. The initial composed
terminal-hook test also used an incorrect argument and was corrected to the
actual function signature before the passing suites above.

At work start, PR #43 was Draft/open/unmerged at
`1ed3ade6b8479bf447ee6b353ae72293b0afbf14`; Staging was
`300b1d4e83a44aa6723a6143a9d82176e800d50b` and main was
`8fd75117a3b4311c159e38f029a0cf78d9d4081f`. The implementation has a new head;
do not reuse that design-only head's CI. Final implementation head, five CI
results, artifact verification and PR deploy-skipped evidence are recorded on
[PR #43](https://github.com/CarsonHHS2023/pdf-ocr-service/pull/43).

Next gate is exact-head code review before any merge or rollout. No PR merge,
deployment, new PDF upload, benchmark, native thread-setting change, compute
movement, retry-policy change or Production modification is included. Staging
acceptance has not happened. S0/M5 remain In Progress; S1/S2 are not started.
