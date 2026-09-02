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

**2026-09-02 current evidence update:** [S0.3.4 small and medium compute acceptance](../reviews/s0-3-4-compute-acceptance-2026-09-02.md) passed on exact Backend Staging revision `c5817070b85e6778db3dbdf558cd8fd756ffb904`, paired with isolated Provider deployment `edcdfc6bdfd691facf152ac577e41e520fdec4c9`. OCR duration, raw shard bytes and GPU sampling proxy are `observed`; S0.3.3 transport/download metrics remain `observed`. Medium covers two sequential shards and all seven Provider-selected pages plus four local-result pages. Section 6 now reflects both current collector snapshots, including seven remaining `not_instrumented` required metrics. The next engineering item is S0.3.5. S0 remains In Progress; S1/S2 are not started.

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

**Next engineering item; not yet implemented or accepted by this update.** First inventory the exact bounded first-open and reopen paths across Backend and Reader, then define their measurement boundaries before adding instrumentation. Preserve current loading behavior; do not introduce full-document fetches to obtain a metric.

Measure the Reader path without changing Reader behavior:

- Reader-open latency for the accepted bounded open path;
- bounded backend/database query count for that open;
- any binary fetch/proxy component kept separate from semantic-content latency.

The measurement must remain valid for both first open and reopen semantics or explicitly declare which case it represents.

Keep server request duration, client-visible usable-content latency and actual database query count distinct. Correlate a bounded open operation using privacy-safe identity; do not label an arbitrary endpoint duration or query count as the complete Reader open. Validate with an already processed small document after exact-head CI and Staging deployment; a new PDF upload is not intrinsically required for Reader acceptance.

### S0.3.6 Failure and retry attempt counters

Normalize explicit counters rather than inferring retries from diagnostic signals.

Required semantics:

- failed attempt count;
- retry attempt count;
- retryable classification remains a separate diagnostic attribute;
- one logical retry must not be double-counted across Provider and backend events.

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
| Reader-open latency | `not_instrumented` | S0.3.5 — next engineering item |
| Reader bounded query count | `not_instrumented` | S0.3.5 — next engineering item |
| upload-to-Reader-ready latency | `not_instrumented` | compose only after upload and Reader-ready boundaries are explicit |
| failure/retry counts | `not_instrumented` | S0.3.6 |
| TXT representative baseline | open | acceptance sequence after timing contract exists |
| large PDF representative baseline | deferred | run only after instrumentation makes it useful |

The seven `not_instrumented` rows are measured collector gaps, not accepted waivers. Current PDF evidence also does not close TXT timing, Reader binary access coverage, or the final S0 review.

## 7. Exit gate for this closure plan

This closure plan is complete when:

1. every required S0 metric is either `observed` for the representative path or explicitly documented as unavailable with an accepted reason that does not block later comparison;
2. small/medium PDF reruns prove the new measurement contracts on exact Staging revisions;
3. TXT timing evidence is meaningful rather than based on zero/ambiguous lifecycle timestamps;
4. the team can compare backend upload memory, network transport, CPU/GPU work, Provider/OCR timing, failure/retry behavior, and Reader latency across later S phases;
5. the remaining need for the 528-page fixture is decided from incremental-evidence value, not from a desire to fill a registry row;
6. a final S0 completion review explicitly changes the horizontal scalability status from In Progress.

Until then, **S0 remains In Progress and S1/S2 are not started by this plan**.
