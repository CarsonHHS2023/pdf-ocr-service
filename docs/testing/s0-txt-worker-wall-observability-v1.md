# S0 TXT worker wall-duration evidence contract v1

Status: **Contract and pure validator implemented; producer, persistence adapter,
baseline integration and TXT runtime acceptance not implemented**.

Product milestone: M5 support. Scalability phase: S0, In Progress.

## 1. Provenance and implemented slice

The inspected execution source is Backend Staging
`f3b7af8122d5e5fe946614c6e1ddd0047877d504`. The
[TXT lifecycle inspection](https://github.com/CarsonHHS2023/pdf-ocr-service/blob/a26c6ffd4186e8d644efe2a928f01be13cb267d7/docs/plans/s0-txt-lifecycle-timing-plan-2026-09-11.md)
explains why ProcessingRun lifecycle timestamps cannot measure TXT work:
new runs receive the same late timestamp as both start and completion.

This slice adds [a dependency-free validator](../../app/s0_txt_worker_metrics.py),
[synthetic evidence tests](../../tests/test_s0_txt_worker_metrics.py) and an
explicit test step in S0 Baseline and Staging Integration CI. Existing production
code does not import the module. It performs no I/O and installs no hooks,
clock, endpoint, retry, database write or collector mapping.

The remaining sections specify the producer/adapter obligations for the next
slice. Passing pure validation tests does not prove those obligations are met.

## 2. Metric and clock boundary

| Property | Fixed value |
|---|---|
| Auxiliary metric key | `txt_ingestion_worker_wall_seconds` |
| Contract version | `atlas.s0.txt-worker-wall.v1` |
| Measurement scope | `txt_worker_configuration_to_canonical_commit_v1` |
| Method | `same_worker_perf_counter_ns_v1` |
| Durable elapsed unit | Integer nanoseconds |
| Output unit | Seconds, calculated once as `duration_ns / 1_000_000_000` |
| Normal event count | One STARTED and one TERMINAL |
| Absolute family cap | Three events per logical TXT run, including invalidation |
| Encoded payload bound | 2,048 UTF-8 bytes per event |

The start sample belongs to the synchronous TXT worker, immediately before
`build_production_txt_structure_analyzer()`. Observer admission and STARTED
persistence occur before that sample and are excluded. The stop sample is taken
on the same worker immediately after `TxtCanonicalizationService.canonicalize`
returns its committed outcome. It precedes `_set_document_terminal_state` and
terminal evidence publication. Existing entry diagnostics are outside the clock.

Included: analyzer configuration, source database lookup/read/validation,
normalization, window and outline analysis with existing provider waits/retries,
SPR recovery/serialization/storage, candidate transformation, canonical database
work and the successful commit. This is wall time, including waits; it is not CPU.

Excluded: source upload, queue/claim/executor wait, observer admission and writes,
final book-state transaction, dispatch finalization, browser polling, Reader
opens, binary assets and paint. It is not end-to-end ingestion latency.

Sample `perf_counter_ns()` twice; require integer samples and integer difference
in `[0, 2**53 - 1]`. Reject booleans, a reversed clock, floats, missing clocks or
overflow. Zero is valid only when two actual valid samples produce zero. Do not
substitute UTC, dispatch timestamps, process RSS, process CPU or missing values.
The upper bound is an evidence bound, not a new execution timeout.

## 3. Identity and exact event envelopes

Before observation, the dispatcher must explicitly pass its existing claim
metadata to the worker. Do not infer a claim by selecting the latest row for a
document. Raw claim tokens stay in memory and never enter payloads or reports.

Each actual worker invocation receives a fresh server-generated
`txtw_<32 lowercase hex>` identity. A second invocation under the same run is
ambiguous, even if it would produce an identical candidate. Pre-start dispatch
reclaims can increase `attempt_count` without starting another worker; therefore
the contract binds the observed attempt number and does not require it to be 1.

The future database adapter must provide exactly these eight envelope fields:
`id`, `processing_run_id`, `document_id`, `schema_version`, `event_name`,
`severity`, `page_number`, `payload_json`.

- `processing_run_id`: exact `txt-ingest-<32 lowercase hex>` reference.
- `document_id`: exact document from the trusted relational snapshot.
- `schema_version`: `atlas.processing.event.v1`; `page_number`: null.
- `id`: UUIDv5 using `uuid.NAMESPACE_OID` and the UTF-8 name
  `atlas.s0.txt-worker-wall.v1:<run_id>:<ordinal>`.
- Severity: STARTED is `info`; failed TERMINAL is `error`; completed or invalid
  TERMINAL is `info`; INVALIDATED is `warning`.
- Unknown, extra or missing envelope fields are rejected by the pure validator.
  Project optional audit timestamps separately, outside this exact input shape.

`source_scope_id`, `dispatch_scope_id` and `candidate_scope_id` are respectively
`source_`, `dispatch_` and `candidate_` followed by the full lowercase SHA-256
hex digest of the UTF-8 identifier. Input identifiers must match
`[A-Za-z0-9_-]{1,255}`. This is an opaque identifier digest, not a source-content
checksum. It does not anonymize a publicly enumerable identifier.

## 4. Exact payload fields

Every payload has the eight common fields below, plus `ordinal` and only the
event-specific fields in the next table. JSON duplicate keys, nonfinite values,
unexpected fields and invalid UTF-8 are rejected. Limits count encoded bytes.

| Common field | Type / value |
|---|---|
| `contract_version` | Exact version from section 2 |
| `method` | Exact method from section 2 |
| `measurement_scope` | Exact scope from section 2 |
| `worker_scope_id` | `txtw_` plus 32 lowercase hexadecimal characters |
| `source_scope_id` | `source_` plus 64 lowercase hexadecimal characters |
| `dispatch_scope_id` | `dispatch_` plus 64 lowercase hexadecimal characters |
| `dispatch_attempt` | Integer 1 through `2**31 - 1`; booleans rejected |
| `backend_revision` | Exact measured backend revision, 40 lowercase hexadecimal characters |

| Event | Ordinal | Additional fields |
|---|---:|---|
| `S0_TXT_WORKER_STARTED` | 0 | None |
| `S0_TXT_WORKER_TERMINAL` | 1 | `outcome`, `duration_ns`, `candidate_scope_id`, `reason` |
| `S0_TXT_WORKER_INVALIDATED` | 2 | `reason` |

The complete common identity must agree between STARTED and TERMINAL.
Invalidation is bounded, append-only evidence against the original scope.

| Terminal outcome | Duration / candidate | Allowed reason |
|---|---|---|
| `completed` | Measured integer nanoseconds; full candidate digest | `none` |
| `failed` | Both null | `configuration_error`, `canonicalization_error`, `unexpected_error`, `worker_interrupted` |
| `invalid` | Both null | `clock_unavailable`, `invalid_clock`, `candidate_mismatch` |

Invalidation reasons are `duplicate_worker`, `conflicting_terminal` and
`revision_changed`. These values are fixed enums, never exception messages.
Version 1 records coarse failure reasons; detailed TXT stage messages remain
outside this metric. Failures deliberately publish no successful duration,
including no zero placeholder.

## 5. Required producer and persistence behavior

1. Enable only with the verified Staging revision gate. Disabled observation must
   delegate unchanged without database access, extra threads or new retries.
2. In one short observer transaction, verify the live TXT claim, document/source
   association and attempt number, serialize with a consistent document/dispatch
   lock order, and admit the STARTED slot. The existing application transaction
   and queue state must not be mutated or held open across analyzer work.
3. Freeze the clock boundary after admission. If admission or the first clock
   fails, processing still runs but this invocation cannot become an observed
   success. Never start counting from a later convenient point.
4. After a valid committed canonical outcome, freeze elapsed time before any
   status/evidence write. Verify returned run/document/source/candidate identity;
   publish a TERMINAL using the retained measurement, not a fresh end sample.
5. A writer may recognize an identical publication replay for the same retained
   scope without appending another row. Starting a new worker is not such a
   replay. Conflicting scope/terminal data must append the one invalidation slot
   when possible; never overwrite or choose the latest successful event.
6. Recheck revision and identity at each write. Unknown family rows, malformed
   existing slots, more than three rows, duplicates or conflicts prevent success
   acknowledgement. Enforce payload validity and the byte limit before flush.
7. Keep each observer transaction atomic. Failure rolls back observer writes and
   preserves the processing result/exception. No recursive or unbounded write
   retries, pool reconfiguration or schema migration is included in this design.
   The implementation must supply and test bounded acquisition/statement costs
   before enabling a producer; this pure module claims no database deadline.
8. Publish no filenames, titles, source text, contents, URLs, storage references,
   credentials, raw claim tokens or provider bodies. The generic payload
   sanitizer must leave an already validated payload identical; truncation or
   dropped fields cannot produce valid evidence.

## 6. Cancellation, failure and observation loss

`asyncio.to_thread` waiter cancellation does not stop the running synchronous
worker. Only that worker owns the two clock samples. Cancelling the waiter must
not manufacture a worker terminal, close its clock early or rerun the operation.
An actual worker interruption gets a failed terminal when publication is possible
and preserves the original `BaseException`.

Success admission additionally requires durable dispatch `succeeded`, run
`succeeded` and Document `completed` in the read snapshot. Thus a cancelled
waiter leaving the dispatch `running`, a stale-claim failure or a failed final
book-state update cannot produce observed success merely because a candidate was
committed. A late terminal with a failed dispatch stays unavailable.

Cancellation after both worker completion and successful durable finalization
does not erase completed worker work. The metric still does not assert delivery
to the original waiter or Reader. Tests must cover cancellation while finalization
is running, since its own thread may still commit after the await is cancelled.

A process/database failure can lose STARTED, TERMINAL or invalidation writes.
An earlier snapshot can predate a later conflict; if invalidation is lost, this
protocol cannot prove the absence of an unrecorded competing invocation. Do not
claim linearizable cancellation or perfect execution coverage during observation
loss. The unchanged dispatcher prohibition on rerunning entered work is a
necessary business invariant, not evidence manufactured by this observer.

## 7. Relational adapter and collector admission

The pure `AdmissionContext` is **not** a database join or an authorization token.
Only an operator-side, read-only adapter may construct it, from one consistent
snapshot. It must prove all of these before calling `evaluate`:

- One exact TXT ProcessingRun belongs to the requested document and source;
  SourceFile belongs to that document, is retained, has type `txt`, and has a
  positive integer byte size within the contract bound.
- Exactly one relevant TXT dispatch matches that run reference, document and
  source. More than one matching dispatch is ambiguous. Its attempt number
  matches the event and its status is `succeeded`.
- Exactly one eligible committed candidate belongs to the run and document,
  with matching canonical provenance. Multiple candidates are ambiguous unless
  a separately reviewed contract can disambiguate them. Current Reader selection
  is not a substitute for the measured canonical outcome.
- Run and Document have the success states above. The expected backend revision
  comes from pinned runtime/evidence provenance, not from copying the payload.

Load only this event family, using an escaped prefix predicate so underscores do
not become SQL wildcards. Apply SQL-side UTF-8 byte bounds before materializing
TEXT. Fetch cap-plus-one to detect truncation; never silently take two rows from
an incomplete family. Future snapshot collection must use an explicit consistent
transaction/export strategy; separate READ COMMITTED statements alone do not
establish one snapshot.

`evaluate` accepts only a bounded list/tuple of projected family envelopes and a
valid context. `evidence_incomplete` must be exactly false. It rejects invalid
envelopes, payloads, unknown family names, duplicate slots, missing events,
invalidation, mixed identities/revisions, non-success outcomes and mismatched
candidates. It admits only exactly one STARTED plus one completed TERMINAL.

Returned `Reading` contains only `status`, `value` and a fixed reason string.
It emits no raw identity. `observed` refers to this one proposed auxiliary metric;
it is not S0 completion. No averaging, summation, latest-row choice or zero-fill
is allowed for ambiguous evidence.

Failure before ProcessingRun creation remains outside the success-only run
snapshot. Events can use the stable run reference without a run row because the
existing event table has no run foreign key. A later bounded dispatch-oriented
failure report may inspect them; do not create a synthetic ProcessingRun to make
the current collector accept failure evidence.

## 8. Validation and next implementation gate

This slice runs 22 standard-library unit tests with synthetic envelopes and
subcases. They cover byte bounds, duplicate JSON keys, ordinal/type validation,
full identity and envelope checks, missing/duplicate/conflicting scopes,
invalidation, failure/clock loss, source-size and durable-status gates, order
independence and purity. They require no network, database, model or provider.
Both named CI workflows explicitly run this file after their existing overlays.

The next implementation must add worker hooks, bounded atomic persistence and
the consistent relational adapter together, then test their real composition:
observer off/on, slow analyzer/storage/commit with synthetic clocks, source
changes, missing run/candidate, repeated dispatch/worker ownership, transaction
rollback and concurrent writers, cancellation and finalization races, revision
changes, privacy and publication loss. PostgreSQL tests must use the existing
disposable CI service and an isolated schema. Only after these pass should an
exact tested Staging rollout and the smallest useful TXT fixture be considered.

No TXT fixture, benchmark, merge or deployment is included here. Existing PDF
metric mappings, OpenCV V4 settings, asynchronous OCR and the PDF-only frontend
upload observer stay unchanged. Historical TXT timestamps are not corrected or
backfilled by this slice. Full upload peak memory and full preprocessing CPU
remain unimplemented, and accepted S0 evidence remains 17/19, In Progress.
