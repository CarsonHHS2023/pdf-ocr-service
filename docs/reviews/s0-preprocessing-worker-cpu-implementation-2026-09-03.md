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
of a previously closed root if it is unexpectedly reused or a final publication
acknowledgement is lost to cancellation. Processing itself is
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

### Exact-head review follow-up: final publication cancellation

Review at `f920a59ed86196a277a9a50783d05c6427cc5317` reproduced a P2 using the
actual writer and collector: cancellation while a final write was in progress
set only the in-memory `persistence_loss`, while the frozen complete snapshot
could still commit and be admitted as observed.

The follow-up reuses the single invalidation slot with `issue=persistence_loss`.
The synchronous publisher drains pending invalidation before returning, and the
cancellation handler submits a synchronous owner to the existing executor for
the already-returned-writer race. The metadata lock gives them one shared claim;
there is no second final-batch attempt, overwrite, schema change, new thread pool
or processing retry. Running publication does not need a live event loop to
finish. The original delegate error remains authoritative.

`tests/test_s0_preprocessing_cpu_publication.py` uses real Sessions, transactions
and the collector against a temporary SQLite file with independent connections.
It tests before-write, in-transaction, post-commit and post-writer-return
cancellation, successful controls, repeated cancellation, loop shutdown with
follow-up submission refused, original exception preservation, racing invalidation
claims and bounded invalidation-write failure. Both focused S0 and full Staging
CI execute this file. These are synthetic/local checks, not new PDF acceptance.

The append-only invalidation is eventual: before it commits, a concurrent read
can still see the old complete snapshot. If invalidation itself is lost, the
already-committed snapshot cannot be guaranteed to become unavailable. The test
and event contract state this limitation explicitly; no retry/availability claim
is fabricated.

Follow-up local validation (CPython 3.11.15; these suites overlap):

| Check | Result |
|---|---|
| Raw CPU and new publication contracts | 69 passed, 4 composed-only skips |
| Full-composition CPU/publication + Phase 2 + S0.3.6 + deployment contracts | 155 passed, 1 PostgreSQL-gated skip |
| Actual focused S0 Baseline command | 356 passed |
| Staging production-equivalent command | 433 passed, 1 skipped |
| Staging Provider/sharding/S0 command | 288 passed, 2 skipped |
| Original P2 reproduction plus non-cancelled control | 2 passed |
| New 13-case publication suite, five consecutive repetitions | 13 passed in each repetition |

Local skips are not PostgreSQL execution evidence. Exact-head CI, including the
disposable PostgreSQL service, artifact verification and deploy-skipped result,
is checked separately and recorded on PR #43.

Next gate is exact-head code review before any merge or rollout. No PR merge,
deployment, new PDF upload, benchmark, native thread-setting change, compute
movement, retry-policy change or Production modification is included. Staging
acceptance has not happened. S0/M5 remain In Progress; S1/S2 are not started.
