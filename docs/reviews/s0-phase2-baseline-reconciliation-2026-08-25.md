# S0 Phase 2 Baseline Reconciliation — 2026-08-25

| Field | Value |
|---|---|
| Document Type | Baseline / Instrumentation Reconciliation |
| Scalability Phase | S0 — Baseline and observability |
| Product Relationship | M5 Reader MVP reliability / horizontal scalability |
| Review Date | 2026-08-25 |
| Status | **Accepted PDF small + medium baseline; S0 remains In Progress** |
| Base Environment | Backend Staging / Neon Staging |
| Backend / Runtime Revision | `6fe56d35bfb39cf1e1016beb2694464fb1fc2e4f` |
| Fixture Registry | [S0 Benchmark Fixture Registry v1](../testing/s0-benchmark-fixtures-v1.md) |
| Measurement Contract | `atlas.s0.baseline.v1` |
| Prior Review | [S0 Baseline Report — 2026-08-23](s0-baseline-2026-08-23.md) |

## 1. Decision

The S0 PDF small and medium Phase 2 measurement path is accepted on Staging.

The accepted reruns prove that the merged S0 durable measurements and collector mapping work on both a one-page control and a multi-page route that crosses the transport-sharding threshold. They do **not** close S0 because several required network, upload, Modal/GPU, Reader, and failure/retry metrics still lack explicit durable contracts.

This reconciliation does not authorize S1/S2 implementation, Production changes, or a large-PDF rerun. The next implementation slice remains S0 observability only.

## 2. Deployment and provenance

The accepted runs used the exact Staging revision:

`6fe56d35bfb39cf1e1016beb2694464fb1fc2e4f`

The Staging integration/deploy workflow run `32795555006` completed successfully on attempt 3 after the Neon data-transfer quota issue was cleared. The deployed HF runtime reported `RUNNING`, and `/api/v1/health` verified the same exact revision.

For both accepted fixtures, the operator confirmed private source SHA-256 identity against retained benchmark evidence before accepting the run. Checksums, filenames, document IDs, source-file IDs, storage references, and signed URLs remain outside this committed report.

## 3. Accepted PDF baseline

| Metric | `pdf-small-v1` | `pdf-medium-v1` | Contract treatment |
|---|---:|---:|---|
| Source pages | 1 | 11 | required / observed |
| Source bytes | 784,772 | 4,558,903 | required / observed |
| ProcessingRun wall seconds | 155.495 | 526.902 | auxiliary lifecycle evidence |
| Classification wall seconds | 19.912596 | 278.457030 | auxiliary Phase 2 evidence |
| Preprocessing wall seconds | 45.311772 | 317.714785 | required / observed |
| Preprocessing process CPU delta seconds | 27.252357 | 270.275642 | auxiliary only; process-wide |
| Preprocessing endpoint RSS MiB | 516.9 | 739.2 | auxiliary only; process-wide |
| Process-lifetime peak RSS MiB | 656.4 | 1,126.9 | auxiliary only; process-wide |
| Provider integration wall seconds | 112.651302 | 211.625335 | auxiliary logical integration evidence |
| Canonicalization wall seconds | 10.303615 | 85.526802 | required / observed |
| Preprocessed Provider input artifact bytes | 982,161 | 35,498,078 | auxiliary; not network bytes |
| Aggregate raw Provider result bytes | 52,305 | 12,008 | auxiliary; not per-shard bytes |
| Durable event count | 23 | 28 | auxiliary completeness evidence |
| Error-severity events | 0 | 0 | auxiliary diagnostic evidence |
| `retryable=true` signals | 0 | 0 | auxiliary diagnostic evidence |

Important timing semantics:

- preprocessing wall time wraps work that includes classification, so classification and preprocessing durations must not be added;
- canonicalization is nested inside logical Provider integration, so canonicalization and Provider integration durations must not be added;
- process-wide CPU/RSS values are not promoted to stage-owned CPU, upload memory, or GPU memory claims.

## 4. Collector integrity acceptance

For both accepted runs:

- `PDF_S0_CLASSIFICATION_MEASURED` appeared exactly once and had `succeeded=true`;
- `PDF_S0_PREPROCESSING_MEASURED` appeared exactly once and had `succeeded=true`;
- `PDF_S0_PROVIDER_INTEGRATION_MEASURED` appeared exactly once and had `succeeded=true`;
- `PDF_S0_CANONICALIZATION_MEASURED` appeared exactly once and had `succeeded=true`;
- the bounded durable-event window was not truncated;
- no measured-event payload exceeded the service-owned 8,192-byte payload bound;
- no error-severity event was retained;
- no `retryable=true` signal was retained.

The merged collector therefore accepted the dedicated preprocessing and canonicalization measurements as `observed` while continuing to leave unrelated required metrics `not_instrumented` rather than promoting auxiliary process-wide or Provider values.

## 5. Medium-path transport evidence

The medium fixture exercised the behavior that the one-page control cannot cover:

- 11/11 pages classified successfully;
- 7 pages were routed to OCR/Provider;
- 4 pages were excluded from Provider work: 1 native-text page and 3 presentation pages;
- no classifier fallback or fail-open path was used;
- the Provider-selected payload was 28,425,561 bytes, above the 20 MiB sharding threshold;
- transport executed as 2 sequential shards;
- shard source reads were obtained through `presigned_object_get`;
- the two observed shard object sizes were 20,066,861 and 8,361,977 bytes;
- transport-sharding terminal evidence reported `shard_count=2`, `poll_count=17`, `succeeded=true`, and `retryable=false`;
- logical Provider integration completed successfully.

The small fixture used the existing source-transport fallback route while the medium fixture used presigned object reads. This route difference is useful S0 evidence: Atlas still does not have one explicit durable `backend_to_compute_transport_bytes` metric that remains valid across all source-access paths.

The difference between the 35,498,078-byte preprocessed Provider input artifact, the 28,425,561-byte Provider-selected payload, and the observed shard object sizes further confirms that these byte counts are different concepts and must not be collapsed into one required network metric.

## 6. Scaling findings from small -> medium

The accepted pair is already sufficient to identify several current-state pressure points without running the 528-page fixture:

1. **Classification is a material wall-time contributor.** The measured classification interval increased from about 19.9 seconds to 278.5 seconds.
2. **Backend/process memory grows materially before large-book scale.** Process-lifetime peak RSS increased from about 656 MiB to 1,127 MiB. This remains auxiliary because it is process-wide, but it is strong evidence that heavy PDF work should not remain coupled to a thin web/control process long term.
3. **Preprocessed artifacts can expand far beyond source size.** The 4.56 MB medium source produced a 35.50 MB preprocessed Provider input artifact before Provider page selection.
4. **Transport changes behavior at the configured threshold.** The medium route crossed 20 MiB and became sequentially sharded.
5. **Provider/transport remains a scaling boundary.** Logical Provider integration took about 211.6 seconds even for the 7-page Provider subset.
6. **Canonicalization is no longer negligible at medium scale.** The measured interval increased from about 10.3 seconds to 85.5 seconds.

These findings are sufficient to guide the next observability work. A large rerun before the missing metrics exist would mostly produce another expensive lifecycle sample rather than close the S0 evidence gaps.

## 7. Remaining required S0 gaps

### 7.1 Upload / backend control-plane gaps

Still missing as explicit durable metrics:

- backend upload peak memory;
- upload duration;
- backend source/object-store bytes read/written by stage;
- upload-to-Reader-ready latency.

### 7.2 Preprocessing / transport ownership gaps

Still missing:

- stage-owned preprocessing CPU time distinct from process-wide CPU delta;
- explicit Backend -> compute/provider transport bytes across direct and fallback routes;
- a durable way to separate source artifact size, Provider-selected payload size, shard object size, and actual network transfer.

### 7.3 Modal / Provider / GPU gaps

Still missing:

- Modal source download duration;
- OCR page/batch duration;
- GPU busy/idle time or a bounded proxy;
- per-shard raw-result bytes;
- explicit retry-attempt/failure counters rather than diagnostic signals only.

### 7.4 Reader / visual / object-store gaps

Still missing:

- visual asset generation duration;
- object-store reads/writes by processing stage;
- Reader-open latency;
- bounded Reader query count.

### 7.5 Coverage still open

- TXT small/medium need meaningful current timing boundaries;
- the large PDF remains an approved registry fixture but should not be rerun merely to fill a table;
- the large rerun should occur only after the next instrumentation slice can capture metrics that materially improve S0 closure evidence.

## 8. Next S0 implementation slice

The next engineering slice should be **instrumentation-only** and should not change processing ownership or move compute boundaries.

Priority order:

1. add upload wall-time and upload-specific memory instrumentation;
2. add explicit object-store/source I/O byte counters at the backend stages that currently touch source artifacts;
3. add transport-route-specific byte and timing measurements, including Modal/direct-download timing where available;
4. add Provider/OCR per-batch or per-shard timing and raw-result-byte measurements plus a bounded GPU utilization proxy;
5. add Reader-open latency and bounded query-count measurement;
6. normalize explicit retry-attempt/failure counters;
7. rerun the cheap small/medium controls to validate the new contracts;
8. then decide whether TXT and the 528-page PDF add enough incremental evidence to justify their execution cost.

No S1/S2 implementation is part of this slice.

## 9. S0 exit interpretation

Current state:

- versioned fixture registry: **implemented**;
- repeatable collector/process: **implemented**;
- exact-revision Staging acceptance: **implemented**;
- formal PDF small baseline: **accepted**;
- formal PDF medium baseline: **accepted**;
- multi-page sharded Provider path: **accepted**;
- privacy-safe committed reconciliation: **implemented by this review**;
- network/backend upload memory/CPU/GPU/Reader comparison coverage: **not complete**;
- representative TXT/large acceptance: **not complete**.

Therefore **S0 remains In Progress**.

The next phase transition should be considered only after the remaining metric contracts let later phases compare backend memory, network transfer, CPU/GPU throughput, and time-to-Reader against a stable baseline. This review does not authorize S1, S2, Production migration, or large-fixture execution.
