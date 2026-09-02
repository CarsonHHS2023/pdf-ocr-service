# S0 Observability Closure Plan — 2026-08-25

| Field | Value |
|---|---|
| Document Type | Current Execution Plan |
| Scalability Phase | S0 — Baseline and observability |
| Lifecycle Status | Active |
| Date | 2026-08-25 |
| Applies To | `pdf-ocr-service`, `paddle-vl-api`, `speed-reading-trainer` |
| Parent Plan | [Scalable Processing Migration Plan](scalable-processing-migration-plan.md) |
| Evidence Baseline | [S0 Phase 2 Baseline Reconciliation — 2026-08-25](../reviews/s0-phase2-baseline-reconciliation-2026-08-25.md) |
| Fixture Registry | [S0 Benchmark Fixture Registry v1](../testing/s0-benchmark-fixtures-v1.md) |

## 1. Purpose

Close the remaining S0 observability gaps without changing processing ownership, compute placement, storage semantics, or Production behavior.

The accepted 2026-08-25 PDF small/medium runs prove that the durable measurement path and `atlas.s0.baseline.v1` collector work on both a simple control and a multi-page sharded Provider route. S0 remains open because later phases still cannot compare all required backend memory, network, CPU/GPU, failure/retry, and Reader metrics against an explicit stable baseline.

This plan is an execution overlay for S0. It does not redefine the S0-S9 architecture and does not authorize S1 or S2 work.

## 2. Current accepted evidence

Accepted on exact Staging backend/runtime revision `6fe56d35bfb39cf1e1016beb2694464fb1fc2e4f`:

- `pdf-small-v1`: formal one-page exact-identity baseline accepted;
- `pdf-medium-v1`: formal 11-page exact-identity baseline accepted;
- medium route exercised selective page routing plus sequential two-shard Provider transport;
- all four Phase 2 measured-event contracts were unique, bounded, decodable, and successful;
- no error-severity event or `retryable=true` signal occurred in either accepted run.

Key current scaling signals are already visible:

- medium classification wall time is about 278.5 seconds;
- medium preprocessing wall time is about 317.7 seconds and includes classification;
- medium process-lifetime peak RSS reached about 1,126.9 MiB;
- the 4.56 MB source produced a 35.50 MB preprocessed Provider input artifact;
- Provider-selected payload crossed the 20 MiB threshold and used two sequential shards;
- logical Provider integration took about 211.6 seconds;
- canonicalization took about 85.5 seconds.

These signals justify targeted observability work before any expensive large-fixture rerun.

**2026-09-01 S0.3.3 evidence update:** [Small and medium transport/download acceptance](../reviews/s0-3-3-transport-download-acceptance-2026-09-01.md) passed on exact Staging revision `37a3c41fc6f968ef442a723aaccdec2f90af3ce3`. Both required transport/download metrics are `observed`: small exercises one Backend fallback download; medium exercises two presigned shards, including a validated Backend source-body byte count of zero. At that checkpoint, S0.3.4 was the next planned work item.

**2026-09-02 compute checkpoint:** [S0.3.4 small and medium compute acceptance](../reviews/s0-3-4-compute-acceptance-2026-09-02.md) passed on exact Backend Staging revision `c5817070b85e6778db3dbdf558cd8fd756ffb904`, paired with isolated Provider deployment `edcdfc6bdfd691facf152ac577e41e520fdec4c9`. OCR duration, raw shard bytes and GPU sampling proxy are `observed`; S0.3.3 transport/download metrics remain `observed`. Medium covers two sequential shards and all seven Provider-selected pages plus four local-result pages. Those historical snapshots had seven `not_instrumented` required metrics; S0.3.5 was next at that checkpoint.

**2026-09-02 Reader checkpoint:** [Scoped S0.3.5 Reader acceptance](https://github.com/CarsonHHS2023/speed-reading-trainer/blob/a9d470c3609a94be45c525b47038d570c1855b01/docs/s0-reader-open-observability.md) records `reader_open_latency_seconds` and `reader_bounded_query_count` as `observed` using Backend `96801ce840b5dc5d1855e101dbd55df7a592afd8` and frontend `af087d078bd03182bc53610e045778a9d733eda5`. The PDF medium adds first-open/reopen evidence and an existing TXT adds nonzero-window reopen evidence. At that checkpoint the medium collector left **five** required metrics `not_instrumented`, and S0.3.6 was next. Section 6 retains the separate ingestion/Reader provenance.

**2026-09-02 failure/retry follow-up:** [S0.3.6 small success-path acceptance](../reviews/s0-3-6-failure-retry-small-acceptance-2026-09-02.md) passed on exact Backend/runtime `7435aa3fa7ba0766d8cc2584bcacfd735c5ce74c`. The fresh one-page run has `failure_retry_counts = observed`: 14 successful Provider method-call entries (1 submit, 12 normal status polls, 1 result), zero failures/retries/cancellations, and complete start/single-scope/terminal closure. The fresh collector leaves **four** required metrics `not_instrumented`. Multi-scope runtime aggregation and real nonzero retries are not claimed; Section 6.1 sets the next decision. S0 and M5 remain In Progress; S1/S2 are not started.

## 3. Scope rule

Every PR under this closure plan must be instrumentation-only unless this plan is explicitly revised.

Allowed:

- bounded timers/counters/gauges;
- durable privacy-safe measurement events;
- collector mapping for semantically exact metrics;
- tests that prove event uniqueness, bounded payloads, failure semantics, and no content leakage;
- Staging-only acceptance reruns.

Not allowed in this slice:

- moving OpenCV/PDF preprocessing to Modal;
- changing the source/artifact ownership model;
- implementing S1 content-addressed storage behavior;
- implementing S2 single-flight/fingerprint/reconciliation behavior;
- changing Provider/OCR output semantics;
- changing Reader behavior merely to create benchmark data;
- Production rollout;
- 528-page execution solely to populate a baseline table.

## 4. Work items

### S0.3.1 Upload boundary measurements

Add explicit upload-specific metrics that do not reuse generic process RSS or ProcessingRun lifecycle timestamps:

- upload wall duration;
- upload-specific peak memory or a bounded upload-operation memory measure with clear scope;
- accepted source byte count at the upload boundary.

Acceptance requirements:

- one authoritative successful measurement per upload operation;
- no filename/title/content in event payload;
- failed uploads emit bounded failure evidence without fabricating a completed duration;
- generic processing RSS remains auxiliary and is not substituted.

### S0.3.2 Backend object-store/source I/O counters

Persist privacy-safe per-stage counters for backend-controlled source/object-store reads and writes.

At minimum distinguish:

- upload/source-retention write;
- processing source read where the backend actually reads bytes;
- generated artifact write/read where applicable;
- Reader binary proxy read if the current path performs one.

Do not infer network transfer from object size alone.

### S0.3.3 Transport and compute-source download measurements

**Staging acceptance: PASS (2026-09-01)** for `pdf-small-v1` and `pdf-medium-v1`; see the [scope, provenance, and limits](../reviews/s0-3-3-transport-download-acceptance-2026-09-01.md). The required distinctions below remain the contract.

Create explicit transport-route evidence that remains semantically valid across fallback and direct/presigned paths.

Required distinctions:

- preprocessed artifact size;
- Provider-selected payload size;
- shard object size;
- backend-transmitted bytes, if the backend transmits bytes;
- compute/provider source-download bytes;
- compute/provider source-download duration;
- route identifier constrained to an allowlist.

The collector must not collapse these values into one metric unless the contract proves they represent the same boundary.

### S0.3.4 OCR / shard / GPU measurements

**Staging acceptance: PASS (recorded 2026-09-02)** for newly completed `pdf-small-v1` and `pdf-medium-v1`; see [acceptance, provenance and limits](../reviews/s0-3-4-compute-acceptance-2026-09-02.md). The [compute observability contract](../reviews/s0-3-4-compute-observability-contract-2026-09-01.md) defines the Staging-only producer, durable batch/scope events and collector mapping. All three required compute metrics are observed. S0 remains In Progress.

Add the smallest durable measurements that allow later compute phases to compare actual OCR/GPU behavior:

- OCR page/batch or shard duration;
- per-shard raw-result bytes;
- bounded GPU busy/idle proxy or another explicitly defined utilization signal;
- Provider poll/retry counts only where they map to an explicit contract.

Do not promote logical Provider integration wall time to OCR batch duration.

### S0.3.5 Reader-open and bounded query measurements

**Scoped Staging acceptance: PASS (2026-09-02).** See the [exact revisions, measured values and limits](https://github.com/CarsonHHS2023/speed-reading-trainer/blob/a9d470c3609a94be45c525b47038d570c1855b01/docs/s0-reader-open-observability.md). This replaces the earlier "not yet implemented" execution status, not the measurement requirements below. No Reader behavior was changed to create benchmark data.

The existing 11-page PDF medium provided three first opens (mean 5.610667 seconds) and one reopen (5.2728 seconds); its 89 stored nodes fit in the first 150-node window. An existing TXT with 1,013 stored v2 nodes provided one reopen at start 300 / limit 150 (7.1425 seconds). Every measured open had three data requests and 57 measured SQL statement attempts; both required Reader metrics are `observed` in each collection. Sixteen PDF Reader events and four TXT Reader events passed scope/ordinal, terminal, revision, boundedness and privacy checks.

These observations do not establish one-page small-fixture acceptance, adjacent two-window loading, TXT ingestion timing, browser-paint readiness, binary-asset completion or pixel-exact restoration. The current containing-window resume policy predates this instrumentation; its behavior is not silently redefined by the acceptance. The baseline collector was run locally against read-only durable exports using the exact Backend checkout plus CI overlays, not inside HF or from a downloaded byte-verified artifact. Earlier processing metrics retain their earlier ingestion provenance.

The frontend documentation-only descendant `a9d470c3609a94be45c525b47038d570c1855b01` passed 496 local tests, syntax checks, exact-head Client CI and Preview verification. It is not the observed frontend runtime revision. Do not reopen accepted runs merely to refresh a documentation SHA: mixed Reader revisions invalidate complete collector admission. Frontend #86 remains unmerged; this update authorizes no merge or Production deployment.

Measure the Reader path without changing Reader behavior:

- Reader-open latency for the accepted bounded open path;
- bounded backend/database query count for that open;
- any binary fetch/proxy component kept separate from semantic-content latency.

The measurement must remain valid for both first open and reopen semantics or explicitly declare which case it represents.

Keep server request duration, client-reported core semantic-open latency and actual database query count distinct. Correlate a bounded open operation using privacy-safe identity; do not label an arbitrary endpoint duration or query count as the complete Reader open. The original small-fixture validation target remains a coverage limit, not an implicit waiver or instruction to upload again. The completed PDF-medium and TXT-reopen observations must not be relabeled as small acceptance.

### S0.3.6 Failure and retry attempt counters

**Implemented; scoped small success-path Staging acceptance PASS (2026-09-02).** [PR #41](https://github.com/CarsonHHS2023/pdf-ocr-service/pull/41) added the Staging-only producer, durable persistence and strict collector mapping without changing retry policy. The [contract](../testing/s0-failure-retry-observability-v1.md) and [acceptance record](../reviews/s0-3-6-failure-retry-small-acceptance-2026-09-02.md) pin the measured method-call, orchestration, Provider-terminal and logical-invocation layers. Runtime multi-scope coverage remains open, and no real fault-injection acceptance is claimed.

Normalize explicit counters rather than inferring retries from diagnostic signals.

Required semantics:

- failed attempt count;
- retry attempt count;
- retryable classification remains a separate diagnostic attribute;
- one logical retry must not be double-counted across Provider and backend events.

The current orchestration path requires particular care:

- Successful status polls and `RESULT_NOT_READY` waits are normal availability checks, not failed processing attempts or evidence that a retry executed.
- `PDF_PROVIDER_POLL_RETRY` is a stderr diagnostic emitted before the retry sleep. A deadline or cancellation may prevent the next request; a retry-attempt counter must increment at the actual retry dispatch, not when the retry is planned.
- Source-route fallback is distinct from replaying a processing attempt. Backend request retries, Provider execution failures, shard attempts and a whole logical run must retain separate scopes; do not sum them as interchangeable failures.
- A zero count needs explicit complete terminal coverage. Absence of errors, a successful run status, or `retryable=false` alone does not prove observed zero attempts.
- Local fake-provider/fault-injection contract tests cover success, retryable failure then actual retry, cancellation/deadline before dispatch, non-retryable failure, duplicate/missing terminal evidence and per-shard attribution. The fresh small run adds real success-path evidence only. No additional Provider job, failure injection into Staging, upload or benchmark is authorized by this documentation update.

### S0.3.7 Collector mapping and privacy hardening

Only map new fields into required `atlas.s0.baseline.v1` metrics when the event contract exactly matches the required meaning.

Continue the existing fail-closed rules:

- duplicate successful measurements are ambiguous;
- malformed same-name events cannot be ignored when they could create ambiguity;
- oversized payloads are never materialized as trusted evidence;
- document/run association is exact;
- event names and output fields are allowlisted;
- no document content, filename, title, storage reference, signed URL, token, or raw Provider body is emitted.

## 5. Acceptance sequence

Use the cheapest fixture that exercises the new metric first.

1. unit/contract tests;
2. exact-head CI;
3. deploy exact tested revision to Staging;
4. `pdf-small-v1` acceptance;
5. `pdf-medium-v1` acceptance when the metric depends on multi-page/sharded behavior;
6. TXT small/medium acceptance once meaningful TXT timing boundaries are available;
7. only then decide whether `pdf-large-v1` will produce incremental evidence worth its execution cost.

The 528-page fixture requires explicit approval at execution time and must not be automatically included in CI or routine acceptance.

## 6. S0 closure matrix

| S0 requirement | Current status after 2026-09-02 reconciliation | Closure action |
|---|---|---|
| source byte size / page count | observed for accepted PDF small/medium | retain current contract |
| backend upload peak memory | `not_instrumented`; upload-read component bytes remain auxiliary | S0.3.1 exact memory scope remains open |
| upload duration | observed in current small/medium snapshots | retain S0.3.1 upload-operation boundary |
| backend source/object-store bytes | observed for measured Backend logical I/O in current snapshots | retain S0.3.2 logical-I/O scope; not total network traffic |
| preprocessing wall time | observed for accepted PDF small/medium | retain current contract |
| preprocessing CPU time | `not_instrumented` as stage-owned metric; process-wide delta is auxiliary | dedicated stage-attribution instrumentation before S0.3.7 mapping |
| Backend -> compute transport bytes | observed for small fallback and medium presigned shards (2026-09-01) | S0.3.3 representative acceptance PASS; keep ASGI body semantics |
| compute/Modal download time | observed for small and both medium shards (2026-09-01) | S0.3.3 representative acceptance PASS; sum download operations only |
| OCR page/batch duration | observed for small and both medium shards | S0.3.4 representative acceptance PASS; predict-operation sum |
| GPU busy/idle proxy | observed for all three accepted batches across small/medium | S0.3.4 representative acceptance PASS; sample-weighted device proxy |
| raw result/shard size | observed per Provider scope and as validated sum | S0.3.4 representative acceptance PASS; aggregate response size remains auxiliary |
| canonicalization duration | observed for accepted PDF small/medium | retain current contract |
| visual asset generation duration | `not_instrumented` | instrument only when current path can measure it without semantic change |
| object-store reads/writes by stage | observed for measured processing stages in current snapshots | retain S0.3.2 scope; Reader binary proxy is separate and not covered here |
| Reader-open latency | `observed` for PDF-medium first-open/reopen and TXT nonzero reopen | S0.3.5 scoped acceptance PASS; retain exact Reader revision and coverage limits |
| Reader bounded query count | `observed`; 57 SQL statement attempts per measured open | S0.3.5 scoped acceptance PASS; not HTTP request count or a row/byte bound |
| upload-to-Reader-ready latency | `not_instrumented` | compose only after upload and Reader-ready boundaries are explicit |
| failure/retry counts | `observed` for fresh small single-scope success path; explicit zero failures/retries | S0.3.6 small PASS; decide separately authorized medium multi-scope acceptance |
| TXT representative baseline | open | acceptance sequence after timing contract exists |
| large PDF representative baseline | deferred | run only after instrumentation makes it useful |

The **four** remaining `not_instrumented` rows in the fresh S0.3.6 small collector are `backend_upload_peak_memory_mb`, `preprocessing_cpu_seconds`, `visual_asset_generation_seconds`, and `upload_to_reader_ready_seconds`. These are actual collector gaps, not accepted waivers. Historical S0.3.4 seven-gap and S0.3.5 five-gap checkpoints remain valid for their original snapshots. The matrix combines explicitly scoped acceptance across revisions; it does not claim every representative case was freshly measured on one revision. Although Reader metrics are also observed in the latest small snapshot, this failure/retry acceptance did not perform the separate first-open/reopen Reader acceptance audit. One-page Reader acceptance, S0.3.6 multi-scope runtime coverage, TXT ingestion timing, Reader binary access coverage and final S0 review remain open.

### 6.1 Next decisions and remaining instrumentation

1. **S0.3.6 coverage decision:** if separately authorized, use the existing 11-page medium fixture once on the pinned Staging revision to prove new failure/retry counters across multiple Provider scopes. Require more than one actual scope, contiguous ordinals, one complete manifest and no cross-layer failure summation. Earlier medium sharding runs do not validate these new counters. Do not inject real failures or use a large benchmark to manufacture retries.
2. **Next instrumentation design:** finish the S0.3.1 upload-owned memory boundary. Define whether an attributable upload peak can be measured safely under concurrency; largest read-buffer bytes or process-lifetime RSS cannot fill `backend_upload_peak_memory_mb`. An unmeasurable boundary needs an explicit reviewed limitation, not automatic promotion to observed.
3. **Preprocessing CPU attribution:** define a stage-owned CPU measurement that does not count overlapping process-wide work or require moving compute. Current process CPU deltas remain auxiliary.
4. **Visual asset generation timing:** identify the actual generation operation(s), preserve processing behavior, and add bounded durable terminal coverage before collector mapping. Canonicalization duration is not a substitute.
5. **Upload-to-Reader-ready boundary:** define the readiness endpoint and same-run correlation before composing latency. ProcessingRun completion, core semantic-open time and binary/paint readiness are independent; do not sum unrelated or overlapping durations.

S0.3.7 mapping/privacy hardening applies to each new contract; it cannot close missing producer measurements by renaming auxiliary metrics. These are sequencing decisions, not authorization to start implementation, upload fixtures, merge PRs or deploy. No S1/S2 work or 100-page/528-page benchmark is included.

## 7. Exit gate for this closure plan

This closure plan is complete when:

1. every required S0 metric is either `observed` for the representative path or explicitly documented as unavailable with an accepted reason that does not block later comparison;
2. small/medium PDF reruns prove the new measurement contracts on exact Staging revisions;
3. TXT timing evidence is meaningful rather than based on zero/ambiguous lifecycle timestamps;
4. the team can compare backend upload memory, network transport, CPU/GPU work, Provider/OCR timing, failure/retry behavior, and Reader latency across later S phases;
5. the remaining need for the 528-page fixture is decided from incremental-evidence value, not from a desire to fill a registry row;
6. a final S0 completion review explicitly changes the horizontal scalability status from In Progress.

Until then, **S0 remains In Progress and S1/S2 are not started by this plan**.
