# S0.3.3 Transport and Download Acceptance — 2026-09-01

| Field | Value |
|---|---|
| Document Type | Review / Staging Acceptance Evidence |
| Approval Status | Proposed |
| Lifecycle Status | Historical |
| Date / Evidence Date | 2026-09-01 |
| Scope | S0.3.3 representative PDF small and medium transport/download measurements |
| Result | **Small PASS; medium PASS; S0 remains In Progress** |
| Environment | Backend Staging / Neon Staging / isolated Provider Staging route |
| Backend / Runtime Acceptance Revision | `37a3c41fc6f968ef442a723aaccdec2f90af3ce3` |
| Measurement Contract | `atlas.s0.baseline.v1` |
| Fixture Registry | [S0 Benchmark Fixture Registry v1](../testing/s0-benchmark-fixtures-v1.md) |
| Current Plan | [S0 Observability Closure Plan](../plans/s0-observability-closure-plan-2026-08-25.md) |
| Related Milestone | [M5 — Reader MVP](../milestones/M5.md) |
| Prior Evidence | [Phase 2 Baseline Reconciliation](s0-phase2-baseline-reconciliation-2026-08-25.md) |

## 1. Finding and scope

Both newly completed runs pass the S0.3.3 transport/download acceptance gates. The small run exercises one Atlas fallback download; the medium run exercises two sequential presigned object downloads. Producer telemetry, durable persistence, and collector mapping are present for both required metrics.

This records observed acceptance results for the representative paths, not approval to merge, change Production, close S0, or start S1/S2. Earlier Phase 2 findings remain historical evidence. The next planned S0 work item is S0.3.4 OCR/shard/GPU observability; it was not started during this acceptance.

## 2. Provenance and collection method

The acceptance backend revision is `37a3c41fc6f968ef442a723aaccdec2f90af3ce3`. GitHub staging HEAD was re-read for each acceptance and still matched this revision.

[Staging Backend Integration CI run 33533604600](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/33533604600), including deploy job `99942843922`, succeeded. Its deployment log verified the exact HF runtime revision before the fixture runs. The deploy used the verified tested artifact and staging-head guards.

Artifact `9810739764` was downloaded and its archive SHA-256 was checked against GitHub's published digest. The unmodified collector from that exact tested artifact was used, including the composed S0 overlays. A bare source checkout without those overlays is not the accepted runtime collector.

Read-only Neon SQL queries identified the newest matching terminal runs and exported all bounded durable events plus the exact run/document/source metadata used by the collector. The exported rows were replayed into a local SQLite projection and processed with `scripts/report_s0_baseline.py`. The collector was not executed remotely inside HF. PostgreSQL count, JSON validity, byte limits, associations, terminal state, and event-payload digest checks independently verified the exported evidence; metric values were not synthesized.

Private evidence retains the source checksums, run/document/source IDs, event IDs, scope IDs, timestamps, full collector outputs, and bounded payloads. None of those private identifiers, filenames, storage references, or source contents are copied into this report. The new medium source checksum matched retained medium fixture identity.

## 3. Required metrics and distinct byte boundaries

All sizes below are bytes, not MB. These rows describe different boundaries and must remain separate even when their values coincide.

| Measurement | `pdf-small-v1` | `pdf-medium-v1` |
|---|---:|---:|
| Source pages | 1 | 11 |
| Pages selected for Provider | 1 | 8 |
| Retained source bytes | 784,772 | 4,558,903 |
| Full preprocessed artifact bytes | 982,161 | 35,498,078 |
| Provider-selected payload bytes | 982,161 | 31,197,454 |
| Transport source/shard object bytes, sum | 982,161 | 31,200,726 |
| **`backend_to_modal_transport_bytes`** | **982,161 — observed** | **0 — observed** |
| **`provider_source_download_bytes`** (auxiliary) | **982,161 — observed** | **31,200,726 — observed** |
| **`modal_download_seconds`** | **0.708102 — observed** | **4.529134 — observed** |
| Route | `atlas_source_transport_fallback` | `presigned_object_get` |
| Provider downloads | 1 | 2 |

The small source was preprocessed before transmission. The Backend ASGI source-body counter and independent Provider download counter happen to agree for its one download; neither is the retained-source-size metric.

The medium full preprocessed artifact includes all 11 pages. Provider routing selected 8 pages, with 1 native-text page and 2 presentation pages handled outside that OCR input. The two independently serialized shard objects total 3,272 bytes more than the selected payload. Their object sizes, rather than the selected payload size, are the byte-multiset comparator for Provider downloads.

For the presigned medium path, `backend_to_modal_transport_bytes = 0` is a validated observed result: each selected route is presigned and each terminal scope proves zero Backend fallback retrievals. It does not mean zero object-store writes, zero Provider traffic, or zero overall network use. The metric counts successful Atlas fallback ASGI source-body sends and excludes HTTP/TLS framing.

Download seconds are the sum of Provider source-download operation durations. They are not logical Provider integration time, OCR time, GPU utilization, or a general end-to-end critical-path measure.

## 4. Medium per-shard reconciliation

| Shard | Source object bytes | Backend source-body bytes | Provider download bytes | Download seconds | Terminal Backend retrieval count |
|---|---:|---:|---:|---:|---:|
| 1 | 12,916,672 | 0 | 12,916,672 | 2.224881 | 0 |
| 2 | 18,284,054 | 0 | 18,284,054 | 2.304253 | 0 |
| Total | 31,200,726 | 0 | 31,200,726 | 4.529134 | 0 |

Both routes are `presigned_object_get`. The two transport scope IDs, two Provider scope IDs, and two terminal scope IDs are unique within their respective namespaces. Each route has one matching terminal. Provider download sizes match transport object sizes as a multiset. The private evidence also checks the Provider scope hashes against the two shard job IDs.

The successful `PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL` declares `shard_count = 2`. There are no fallback ASGI body events or Backend provider-source read events for either presigned scope. Their Backend retrieval ordinal sets are therefore empty and consistent with terminal count zero; no ordinal 1 is expected on this path.

## 5. Completeness and privacy

| Check | Small | Medium |
|---|---:|---:|
| Durable events | 32 | 38 |
| Maximum payload bytes / limit | 566 / 8,192 | 591 / 8,192 |
| Malformed / oversized events | 0 / 0 | 0 / 0 |
| Run/document association mismatches | 0 | 0 |
| Duplicate route / terminal / Provider scopes | 0 / 0 / 0 | 0 / 0 / 0 |
| Duplicate scope ordinals | 0 | 0 |
| Error-severity events | 0 | 0 |
| Event window truncated | false | false |
| Payload decode incomplete | false | false |
| Payload oversized incomplete | false | false |

Ordinal continuity is checked within each event/measurement/stage/scope namespace. Small fallback storage-read and ASGI-send evidence each contain ordinal `[1]`, and terminal retrieval count is 1. Medium presigned scopes have empty Backend retrieval sequences and terminal count 0. Other measured storage I/O scopes contain ordinal `[1]`.

All bounded payloads were inspected for filenames, paths, full/signed URLs, credentials/tokens, raw storage references, document contents, and titles; none were found. Medium's public host-only source-access diagnostic is not an object reference or signed URL.

## 6. Limits and next work

- S0.3.3 representative small/medium transport and download acceptance is satisfied. This does not claim every mixed-route or retry permutation has been runtime-tested.
- Medium retained two classifier fallback-page diagnostics and two already-deleted shard cleanup diagnostics. They did not prevent successful downloads or terminal completion. They are not promoted to failure/retry counts or interpreted as a new defect by this review.
- Local collector execution completed with exit code 0 and emitted existing SQLAlchemy relationship-overlap warnings; no model changes were made.
- OCR/shard/GPU metrics remain S0.3.4 work. Reader, failure/retry, other missing S0 metrics, and the final S0 closure review remain open.
- No new upload or benchmark was performed by the collector. No 100-page or 528-page run, Production change, or merge occurred.
