# S0.3.4 OCR / Shard / GPU Acceptance — 2026-09-02

| Field | Value |
|---|---|
| Document Type | Review / Staging Acceptance Evidence |
| Approval Status | Proposed |
| Lifecycle Status | Historical |
| Record Date | 2026-09-02 |
| Fixture Execution Date | 2026-09-01 UTC |
| Scope | S0.3.4 representative PDF small and medium compute measurements |
| Result | **Small PASS; medium PASS; S0 remains In Progress** |
| Environment | Backend Staging / Neon Staging / isolated Provider Staging |
| Backend / Runtime Acceptance Revision | `c5817070b85e6778db3dbdf558cd8fd756ffb904` |
| Provider Staging Deployment Revision | `edcdfc6bdfd691facf152ac577e41e520fdec4c9` |
| Fixture Registry | [S0 Benchmark Fixture Registry v1](../testing/s0-benchmark-fixtures-v1.md) |
| Measurement Contract | [S0.3.4 compute observability contract](s0-3-4-compute-observability-contract-2026-09-01.md) |
| Current Plan | [S0 Observability Closure Plan](../plans/s0-observability-closure-plan-2026-08-25.md) |
| Related Milestone | [M5 — Reader MVP](../milestones/M5.md) |

## 1. Finding and scope

Both newly completed fixture runs pass the producer → durable persistence → collector gates for `ocr_batch_duration_seconds`, `raw_result_shard_bytes`, and `gpu_busy_idle_proxy`. Small covers one page, one batch and one fallback source download. Medium covers 11 document pages: four local-result pages and seven Provider pages split into two sequential shards of three and four pages, with one OCR batch per shard.

This is representative Staging acceptance. It does not close S0 or M5, authorize Production rollout, or start S1/S2. It does not claim multiple batches within a single shard, concurrent-shard timing, or every failure/retry permutation was exercised by these runtime fixtures.

## 2. Revision provenance and collection method

Backend [PR #38](https://github.com/CarsonHHS2023/pdf-ocr-service/pull/38) merged into Staging at the acceptance revision above. [Integration CI 33564752284](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/33564752284), including deploy job `100045802234`, passed integration tests, artifact verification and deployment. The job verified the exact HF runtime revision at `2026-09-01T22:11:26.7832098Z`, followed by the final staging-head guard. Both fixture runs began after deployment; GitHub staging HEAD was re-read during acceptance and still matched.

Provider [preview CI 33564151017](https://github.com/CarsonHHS2023/paddle-vl-api/actions/runs/33564151017), job `100043351262`, checked out the exact Provider revision and deployed isolated app `paddle-vl-api-s0-staging` at `2026-09-01T22:01:49.9905800Z`. Provider [PR #43](https://github.com/CarsonHHS2023/paddle-vl-api/pull/43) remains Draft and unmerged. This is deployment provenance, not a claim that individual durable events embed a Git revision.

Read-only Neon queries selected each new terminal run and exported its exact run/document/source association, source checksum, PostgreSQL text timestamps and all durable event payloads. The medium checksum matched the retained registered medium fixture. The rows were replayed into a local SQLite projection and processed with unmodified `scripts/report_s0_baseline.py`. PostgreSQL event count, JSON validity, payload limits, associations and payload digest independently matched the export; metric values were not synthesized.

**Collector provenance limitation:** GitHub listed tested artifact `9822699884`, but its materialization URL returned HTTP 403. The collector was instead reconstructed from a fresh exact Backend commit using all 15 overlay commands in that commit's Staging Integration CI. Collector file hashes were retained and rechecked for medium. This is exact-source/CI-composition replay, not execution from a downloaded byte-verified deployment archive, and not execution inside HF. It differs from the artifact-download method used for the earlier [S0.3.3 acceptance](s0-3-3-transport-download-acceptance-2026-09-01.md).

Private evidence retains run/document/source IDs, checksums, event/scope IDs, timestamps, all payloads and complete collector output. Those identifiers and private filenames are not copied into this repository report.

## 3. Required metrics and byte boundaries

All six observed metrics below retain separate measurement boundaries. Sizes are bytes.

| Measurement | `pdf-small-v1` | `pdf-medium-v1` |
|---|---:|---:|
| Document pages | 1 | 11 |
| Provider-selected pages | 1 | 7 |
| Provider shards / OCR batches | 1 / 1 | 2 / 2 |
| **`ocr_batch_duration_seconds`** | **49.728492 — observed** | **79.618594 — observed** |
| **`raw_result_shard_bytes`** | **18,404 — observed** | **32,003 — observed** |
| **`gpu_busy_idle_proxy`** | **observed** | **observed** |
| GPU sample count | 50 | 79 |
| GPU nonzero samples / total | 48 / 50 | 76 / 79 |
| GPU sample-weighted mean utilization (%) | 15.92 | 21.911392 |
| GPU nonzero sample fraction | 0.96 | 0.962025 |
| Retained original source bytes | 784,772 | 4,558,903 |
| Full preprocessed PDF bytes | 982,161 | 35,498,078 |
| Provider-selected PDF bytes | 982,161 | 28,425,561 |
| Transport source/shard object bytes, sum | 982,161 | 28,428,838 |
| **`backend_to_modal_transport_bytes`** | **982,161 — observed** | **0 — observed** |
| **`provider_source_download_bytes`** (auxiliary) | **982,161 — observed** | **28,428,838 — observed** |
| **`modal_download_seconds`** | **1.219735 — observed** | **1.301559 — observed** |
| Historical aggregate `raw_result_size_bytes` (auxiliary) | 52,904 | 11,992 |
| Source route | `atlas_source_transport_fallback` | `presigned_object_get` |

OCR seconds sum worker `pipeline.predict` durations, including generator consumption. They exclude source download, queueing, initialization, polling and canonicalization; they are not GPU-only seconds or an end-to-end critical path. Raw shard bytes measure sanitized raw page-list UTF-8 JSON before result-profile slimming, excluding envelopes/compression/artifact wrappers. The aggregate returned-result size is not a substitute.

GPU samples use the requested one-second interval. Medium utilization readings sum to 1,731 percentage points over 79 samples; its weighted mean is not the unweighted mean of the two shard means. The nonzero fraction is a device sample-window proxy, not exact GPU active seconds, spatial occupancy, process attribution or between-job idle time.

Small Backend ASGI body bytes and independent Provider download bytes happen to agree after preprocessing; they remain distinct from retained source bytes. Medium's two presigned routes and two closed zero-retrieval terminals establish observed zero Backend ASGI source-body bytes. Provider still downloaded 28,428,838 bytes, and other Backend object-store operations remain separate. Shard object totals exceed the selected PDF by 3,277 bytes; the object-byte multiset is the download comparator.

The medium route selected seven Provider pages, with one native-text and three presentation pages contributing four local results. Earlier S0.3.3 medium evidence selected eight Provider pages. These are separate runs; no earlier routing counts or timings were substituted.

## 4. Medium per-shard reconciliation

Rows follow observed sequential execution order. Page ranges and batch ordinals are local to each Provider scope.

| Shard | Pages / local range | Batch ordinal | Predict seconds | Raw page-list bytes | Provider download bytes | Download seconds | GPU samples / nonzero |
|---|---|---:|---:|---:|---:|---:|---|
| 1 | 3 / 1–3 | 1 | 55.104763 | 15,383 | 20,066,861 | 0.772654 | 54 / 52 |
| 2 | 4 / 1–4 | 1 | 24.513831 | 16,620 | 8,361,977 | 0.528905 | 25 / 24 |
| Total | 7 | 2 batches | 79.618594 | 32,003 | 28,428,838 | 1.301559 | 79 / 76 |

Each validated Provider download scope has exactly one compute terminal and complete batch evidence. Compute terminal page counts sum to all seven Provider-selected pages. Both batch sequences are `[1]`; the shared ordinal value across different scopes is not a duplicate. Both transport scopes are presigned, their Backend retrieval sequences are empty, and their terminal retrieval counts are zero. Provider download bytes match transport object bytes as a multiset.

## 5. Completeness and privacy

| Check | Small | Medium |
|---|---:|---:|
| Durable events | 34 | 42 |
| Maximum payload bytes / limit | 566 / 8,192 | 591 / 8,192 |
| Malformed / oversized events | 0 / 0 | 0 / 0 |
| Run/document association mismatches | 0 | 0 |
| Duplicate scope ordinals / terminals | 0 / 0 | 0 / 0 |
| Error-severity events | 0 | 0 |
| Event window truncated | false | false |
| Payload decode / oversized incomplete | false / false | false / false |

Every durable payload was inspected for sensitive filenames, paths, URLs, credentials/tokens, raw storage references, document titles/content and unexpected fields. None were found. Both exports matched independent PostgreSQL payload digests. Small's source-access `ProviderUnavailable` diagnostic selected the successful fallback route; it is not promoted to a failed processing attempt or retry count. Medium had no warning events. Collector execution exited zero; existing SQLAlchemy relationship-overlap warnings remain unrelated to this acceptance.

## 6. Remaining S0 work

Small and medium representative S0.3.4 acceptance is satisfied. No additional 100-page or 528-page run is needed for this slice. Both current snapshots still report seven required metrics as `not_instrumented`:

- `backend_upload_peak_memory_mb`;
- `preprocessing_cpu_seconds`;
- `visual_asset_generation_seconds`;
- `reader_open_latency_seconds`;
- `reader_bounded_query_count`;
- `upload_to_reader_ready_seconds`;
- `failure_retry_counts`.

The next planned engineering item is S0.3.5 Reader-open and bounded query observability. It must measure first-open/reopen scope explicitly, preserve existing bounded loading behavior, and keep binary fetch time separate. Upload-read component bytes, process-wide CPU deltas, Provider poll counts and ProcessingRun terminal time must not be relabeled to fill the remaining gaps. TXT timing and final S0 closure review also remain open.
