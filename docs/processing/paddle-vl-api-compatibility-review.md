# Atlas ↔ paddle-vl-api Protocol Compatibility Review

| Field | Value |
|---|---|
| Document Type | Compatibility Review |
| Review Date | 2026-07-14 |
| Evidence Role | Point-in-time provider-protocol compatibility review |
| Reviewed Revisions | Atlas `aed1884`; provider reference `3a790e3e4c0ececef316bd2ca5aa03d84f6c6159`; provider implementation inventory revision `20b9ec9` |
| Authority Domain | Compatibility findings between inspected Atlas adapter assumptions and inspected paddle-vl-api provider protocol |
| Applies To | Atlas M2 processing contract assumptions; paddle-vl-api async job submission, polling, result, artifact, status, error, transport, lifecycle, page mapping, and adapter responsibilities inspected for this review |

## Status

Reviewed; implementation not authorized.

- Atlas commit inspected: `aed1884` (`Merge pull request #57 from CarsonHHS2023/codex/create-documentation-only-branch-for-atlas-contract`).
- Provider reference commit inspected: `3a790e3e4c0ececef316bd2ca5aa03d84f6c6159`.
- Provider implementation revision recorded by the inventory: `20b9ec9` (`Merge pull request #36 from CarsonHHS2023/codex/fix-merge-regression-in-modal_app.py`).
- Review date: 2026-07-14.
- Access limitations: Atlas was inspected from the mounted repository and the provider review used only the provider reference repository's current protocol inventory; no live provider calls, no secrets, and no unapproved provider source inspection were used.
- `paddle-vl-api` reference repository was read-only for this review and remained clean before editing Atlas documentation.

## Objective

This review compares the provider-independent Atlas M2 Document Processing Contract with the verified current `paddle-vl-api` protocol inventory before implementation. It identifies directly compatible behavior, Atlas adapter responsibilities, provider changes, deferred issues, implementation blockers, and the smallest safe implementation sequence. It does not authorize production code, API, database, CI, dependency, deployment, client, adapter, provider-interface, coordinator, worker, or ingestion implementation.

## Evidence sources

### Atlas canonical contract

- `docs/architecture/document-processing-contract.md`.
- `docs/architecture/persistence-processing-foundation.md`.
- `docs/milestones/M2.md`.
- `docs/milestones/M3.md`.
- `docs/storage/storage-adapter-design.md`.
- `docs/storage/storage-ownership-model.md`.
- `docs/storage/current-storage-review.md`.
- `docs/roadmap/roadmap.md`.

### Provider implementation inventory

- The provider reference repository's current protocol inventory at provider reference commit `3a790e3e4c0ececef316bd2ca5aa03d84f6c6159`.
- The inventory states it was grounded in provider implementation commit `20b9ec9` and not in a live Modal call.

### Current transitional Atlas implementation

- `README.md`.
- `app/routers/ocr.py`.
- `app/services/page_ocr_service.py`.
- `app/services/mineru_popo_service.py`.
- `app/models.py`.
- `app/storage/`.
- `app/book_service.py`.
- Current processing and Reader compatibility tests under `tests/` as discovered by repository search.

### Target M2 architecture

Atlas target M2 starts from retained `Document`/`SourceFile` source identity, retrieves bytes through Storage, invokes a provider, captures provider-specific Raw Processing Results, normalizes them through MinerU-Popo or equivalent logic, and emits provider-independent Structured Processing Output for M3. The current local OCR/Reader path is explicitly transitional and must remain compatible until a controlled cutover.

## Executive compatibility summary

- **Directly compatible areas:** `paddle-vl-api` has implemented async job submission, polling, result retrieval, artifact delivery, provider job/request identities, status/progress counters, PDF whole-document processing by provider-created ranges, partial failure reporting, structured async errors, bearer auth on async endpoints, and build tags.
- **Adapter-required areas:** Atlas must translate opaque Storage references to a provider transport, map Atlas processing attempts to provider `job_id`/`request_id`, normalize provider lifecycle/progress/error/status values, ingest temporary provider results into Atlas-controlled durable storage, remap provider page identities, and transform provider `standard`/`full` output into MinerU-Popo-compatible input and then provider-independent output.
- **Provider gaps:** The provider lacks Atlas StorageReference support, raw-byte async upload, client-selected page ranges, cancellation, automatic retries, a general idempotency key, stable top-level model/version metadata, durable result ownership, hostname/IP SSRF blocking, authentication on sync/warmup/config/spike endpoints, explicit page-count limit, first-class warnings, and first-class table/figure/formula arrays.
- **Atlas gaps:** Atlas has not yet implemented the M2 provider client, processing attempt model, raw-result ingestion, durable raw-result ownership, provider capability metadata capture, status/error/progress mapping, page-remapping adapter, or new-pipeline comparison/cutover mechanics.
- **Non-blocking deferred areas:** M3 canonical Structured Content identity, final evidence IDs, broad non-PDF media support, capability negotiation, public API error schemas, and final partial-output product policy remain deferred.
- **Integration blockers:** Human decisions are required for initial transport, primary async/sync integration choice, job granularity, attempt/job ID mapping, raw-result ownership, result profile, artifact TTL policy, partial failure policy, retry/idempotency strategy, page identity contract, and security ownership. No provider behavior prevents beginning a mocked Atlas client after those decisions.

## Compatibility status vocabulary

Use only these statuses in this review:

- **Compatible:** Provider behavior satisfies an Atlas M2 requirement without a provider change and without more than ordinary request wiring.
- **Compatible with Atlas adapter:** Provider behavior is usable if Atlas translates identity, transport, status, shape, provenance, or persistence at the adapter boundary.
- **Partially compatible:** Provider behavior satisfies part of the requirement but leaves a meaningful gap or policy decision.
- **Missing in provider:** The verified inventory shows the provider does not implement the required behavior.
- **Missing in Atlas:** Atlas target requires a behavior that is not implemented in the current Atlas codebase.
- **Provider-specific:** The behavior exists but must remain behind the provider boundary and must not become an Atlas contract.
- **Deferred:** The item is intentionally outside this implementation review or belongs to later milestones.
- **Unclear:** The verified inventory is insufficient to make a safe claim.

## End-to-end compatibility matrix

| Atlas M2 contract requirement | paddle-vl-api current behavior | Compatibility status | Gap or mismatch | Recommended owner | Required action | Blocking level | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Retrieve retained Source bytes through Storage using opaque references. | Async jobs accept HTTPS `pdf_source_url`; no StorageReference or raw-byte public async endpoint. | Compatible with Atlas adapter | Atlas must resolve Storage and expose/transport bytes without making transport artifacts durable Sources. | Atlas adapter/client | Decide signed/accessible URL vs future upload endpoint. | M2 implementation blocker | Atlas source retrieval contract; provider input/transport inventory. |
| Keep provider transport artifacts non-durable. | Provider downloads source PDFs and creates temporary range PDFs in Modal execution cache. | Compatible with Atlas adapter | Provider temp files are execution artifacts, not Atlas Sources. | Atlas persistence/ingestion | Record only source identity and processing artifact provenance. | Required before cutover | Provider temporary-state inventory. |
| Verify source integrity. | Optional `pdf_source_sha256` is checked against downloaded bytes; ETag retained internally but not validated. | Partially compatible | Atlas must compute/own source checksum and decide where mismatch is terminal. | Atlas adapter/client | Send SHA-256 when available and verify raw-result source metadata on ingest. | Required before cutover | Provider request model and errors. |
| Support provider-independent source types. | Implementation expects PDFs; sync/spike multipart lacks strong MIME checks. | Partially compatible | Atlas is broader than provider; M2 can be PDF-only. | Atlas processing orchestration | Gate initial provider route to PDF. | Non-blocking | Provider supported MIME notes; Atlas future contract. |
| Async processing foundation. | `/ocr/jobs`, status, result, artifact are implemented with bearer auth. | Compatible | None for M2 development. | Atlas adapter/client | Use async endpoints as stable integration dependencies. | Non-blocking | Provider endpoint inventory. |
| Synchronous OCR as primary production path. | `/ocr/sync` exists, unauthenticated, multipart, one PDF, blocking response. | Partially compatible | Not suitable as primary durable M2 integration. | deployment/configuration | Restrict to smoke/small manual use unless secured. | Required before production | Provider endpoint and security inventory. |
| Stable lifecycle mapping. | Provider statuses: `queued`, `running`, `completed`, `partial_failed`, `failed`, `expired`; no cancellation. | Compatible with Atlas adapter | Atlas states differ and include cancellation/retry concepts. | Atlas processing orchestration | Normalize provider states and keep ingestion/normalization states separate. | M2 implementation blocker | Provider lifecycle inventory; Atlas processing stages. |
| Progress/counters. | Status exposes document/task/page counters and `percent_complete` based on pages completed over pages total. | Compatible with Atlas adapter | Provider completion is not full Atlas attempt completion after ingestion/normalization. | Atlas processing orchestration | Calculate Atlas progress phases. | Required before cutover | Provider status/progress inventory. |
| Stable page evidence mapping. | Provider remaps range-local pages to original zero-based `page_index`, one-based `page_number`, `local_page_index`, and `source_page_range`. | Compatible with Atlas adapter | Atlas must preserve/remap for M2 evidence; partial/duplicate/missing ambiguity remains. | Atlas adapter/client | Define page-remapping adapter contract. | M2 implementation blocker | Provider processing execution and result inventory. |
| Raw Processing Result capture. | Provider serves `summary`, `standard`, `full`; large full raw result via gzip artifact with checksum and TTL. | Compatible with Atlas adapter | Provider storage is temporary and not Atlas durable ownership. | Atlas persistence/ingestion | Ingest inline/artifact result promptly into Atlas Storage. | M2 implementation blocker | Provider result delivery and TTL inventory. |
| MinerU-Popo normalization input. | Async `standard` has markdown, blocks, pages; `full` adds sanitized raw result. | Unclear | Current MinerU-Popo expects per-page PaddleOCR-VL JSON in `PdfPage.ocr_raw_json`; exact shape compatibility is not proven by the inventory. | MinerU-Popo | Capture fixtures and build adapter from provider output to MinerU-Popo input. | Required before cutover | Atlas MinerU-Popo implementation; provider result inventory. |
| Structured Processing Output semantic minimum. | Provider normalized blocks include type/text/bbox/confidence/order/metadata; tables/images/formulas appear via blocks/pass-through/raw/statistics. | Partially compatible | Hierarchy and first-class references may need MinerU-Popo/M3. | M3 Structured Content | Keep provider JSON out of public M2 output contract. | Deferred | Atlas contract; provider block inventory. |
| Multi-document handling. | Async jobs support multiple documents per job with document-level counters and partial failures. | Compatible with Atlas adapter | Atlas attempt isolation is simpler one document per provider job. | Atlas processing orchestration | Decide job granularity. | M2 implementation blocker | Provider request/job inventory. |
| Partial failures. | `partial_failed` terminal status can expose successful documents/pages when `fail_fast=false`. | Compatible with Atlas adapter | Product policy for partial Reader/M3 output is undecided. | Atlas processing orchestration | Decide ingest/retry behavior and preserve provenance. | Required before cutover | Provider lifecycle/errors. |
| Error categorization. | Async endpoints mostly structured errors with retryable flags; sync errors less structured. | Compatible with Atlas adapter | Atlas needs provider-independent categories and redaction policy. | Atlas adapter/client | Implement conceptual mapping in future code. | M2 implementation blocker | Provider error inventory. |
| Authentication/security. | Bearer auth for async job/status/result/artifact only; sync/warmup/config/spike unauthenticated; HTTPS-only downloads; limited SSRF controls. | Partially compatible | Production hardening needed, especially SSRF/private-network protection and endpoint exposure. | paddle-vl-api | Use bearer async endpoints; harden provider before production. | Required before production | Provider security inventory. |
| Provider provenance. | `build_tag`, request/job IDs, timestamps, warmup versions; no API code revision or stable top-level model version in async result. | Partially compatible | Atlas needs model/pipeline/build provenance minimum. | paddle-vl-api | Add stable top-level model/version/revision metadata or capture from warmup/config policy. | Required before production | Provider provenance inventory. |
| Cancellation. | No cancellation endpoint or state. | Missing in provider | Atlas cancellation state cannot propagate to provider. | paddle-vl-api | Decide defer vs provider enhancement. | Non-blocking unless required by product | Provider known gaps. |
| Retries/idempotency. | Duplicate unexpired `job_id` rejected; no auto retry or general idempotency key. | Partially compatible | Atlas needs safe retry rules after uncertain submission and expired jobs. | Atlas processing orchestration | Generate stable job IDs per attempt or define retry-new-attempt policy. | M2 implementation blocker | Provider request identity and known gaps. |
| Legacy Reader compatibility. | Provider returns provider output, not Reader-specific stream text/images/MinerUResult. | Compatible with Atlas adapter | Compatibility must remain in Atlas integration/serialization. | Atlas persistence/ingestion | Keep old pipeline until comparison/cutover passes. | Required before cutover | Atlas current implementation and tests. |

## Section A — Source identity and retrieval

Atlas expects `Document` and `SourceFile` to identify the business Source, while Storage owns byte retrieval through opaque references. `paddle-vl-api` async jobs accept only HTTPS PDF URLs (`pdf_source_url`) with optional `pdf_source_etag` and optional `pdf_source_sha256`. It downloads each whole source PDF into execution cache, validates HTTPS redirects, checks optional SHA-256, validates PDF magic bytes, counts pages, creates internal page-range PDFs, and processes those ranges. It has no direct Atlas StorageReference support.

Atlas should resolve `SourceFile.storage_reference` through Storage, then use a transport chosen by humans. A private/local Storage object is not reachable by the provider merely because Atlas can resolve it; Atlas must either expose bytes through an Atlas-controlled HTTPS URL, use a future provider upload/bytes endpoint, or create another explicitly approved transport artifact. The safest current recommendation is an Atlas-controlled temporary HTTPS URL whose lifetime is shorter than or equal to provider job/result needs, with `pdf_source_sha256` supplied when Atlas has it. A future provider raw-byte/upload endpoint would avoid URL exposure and SSRF risk, but it is not implemented. An internal transport artifact may be required, but it must be recorded as an execution artifact, not as a durable Source. SHA-256 should be verified by Atlas before submission when reading from Storage and by the provider during download when the hash is supplied; Atlas should also capture the checksum in raw-result provenance. Provider download/cache behavior is acceptable for development if URLs are Atlas-controlled, but production use requires SSRF and host-policy decisions.

**Codex recommendation — human confirmation required:** begin with Atlas-controlled HTTPS transport only if the URL host and lifetime are controlled by Atlas; otherwise request a provider upload endpoint before production.

## Section B — Supported source types

| Source type | Atlas future intent | paddle-vl-api current support | Compatibility status | M2 implication |
| --- | --- | --- | --- | --- |
| PDF | Required initial document-processing source. | Implemented as expected input for sync and async. | Compatible | Initial M2 can be PDF-only. |
| TXT | Atlas currently supports TXT upload/Reader compatibility and future broader sources. | Not supported by provider inventory. | Missing in provider | Keep TXT on legacy/other path. |
| Image | Future Atlas source class. | Not claimed by provider inventory as public API. | Missing in provider | Deferred. |
| DOCX | Future Atlas source class. | Not claimed. | Missing in provider | Deferred. |
| EPUB | Future Atlas source class. | Not claimed. | Missing in provider | Deferred. |
| Audio | Future Atlas multimodal source. | Not claimed. | Missing in provider | Deferred. |
| Video | Future Atlas multimodal source. | Not claimed. | Missing in provider | Deferred. |
| Webpage | Future/possible source. | Not claimed. | Missing in provider | Deferred. |

M2 initial scope may remain PDF-only even though Atlas is provider-independent and broader by design.

## Section C — Request identity and idempotency

Atlas needs processing attempt identity, request/correlation identity, and safe retry semantics. Provider async requests accept optional `job_id` and `request_id`; if `job_id` is omitted the provider generates one. Duplicate unexpired `job_id` values are rejected with `409 JOB_ALREADY_EXISTS`. There is no general idempotency key and no automatic retry scheduler.

**Recommended mapping — human confirmation required:** Atlas should generate provider `job_id` from the Atlas processing attempt ID, with a provider-safe prefix/suffix if needed, and pass Atlas request/correlation ID as provider `request_id`. A retry after an uncertain submission should first poll the provider by the generated `job_id`. If the provider returns an existing active/completed job, Atlas should reconcile rather than submit a duplicate. If the provider job expired or cannot be found, Atlas should create a new Atlas processing attempt or an explicitly linked retry attempt rather than silently reusing the old attempt. A successful prior attempt must not be overwritten.

Risks: duplicate job IDs reject active retries; expired jobs lose result access; replay can reprocess the same source; successful prior attempts can be obscured if Atlas does not persist raw-result provenance; uncertain submission may leave a provider job running while Atlas believes submission failed.

## Section D — Sync vs async

Atlas M2 should use async jobs as the primary integration because `/ocr/jobs`, `/ocr/jobs/{job_id}`, `/ocr/jobs/{job_id}/result`, and `/ocr/jobs/{job_id}/artifact` are implemented with bearer auth, polling, result readiness, TTL, progress counters, and artifact delivery. `/ocr/sync` should be limited to manual smoke tests or very small development checks because it is unauthenticated, blocks one HTTP request, accepts multipart upload, and does not use the async result/profile/artifact contract. `/warmup` belongs in deployment operations or operator checks, not normal application flow. `/health/config` may be a deployment diagnostic, not an application dependency. `/spike/*` endpoints are experimental and must not be used in the stable integration plan.

Stable integration dependencies: `POST /ocr/jobs`, `GET /ocr/jobs/{job_id}`, `GET /ocr/jobs/{job_id}/result`, and conditionally `GET /ocr/jobs/{job_id}/artifact`. Endpoints not to use for production workflow: `/spike/*`; `/ocr/sync` except limited smoke use; `/warmup` inside user request flow.

## Section E — Job lifecycle mapping

| Provider job state | Conceptual Atlas processing-attempt state | Normalization state | Output-ingestion state | Document business status | M3 publication state | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `queued` | `queued` | Not started | Not started | Existing/current processing status remains separate | Not started | Provider accepted but not running. |
| `running` | `running` | Not started | Not started | Processing | Not started | Provider may be downloading/planning/running tasks. |
| `completed` | Provider stage succeeded; Atlas attempt still `running` until ingestion and normalization finish | Pending/running after raw result captured | Pending/running | Processing until Atlas output completes | Not started | Do not mark full M2 attempt complete solely on provider completion. |
| `partial_failed` | Provider stage partially succeeded or failed by policy | Conditional | Conditional | Policy-dependent | Deferred/policy-dependent | Successful pages/documents may be ingestible. |
| `failed` | `failed` or retryable failure | Not started | Not started or failed | Failed unless retry pending | Not started | Error mapping determines retry. |
| `expired` | `failed` due to result loss or retry-needed state | Not possible from expired provider result | Failed if not already ingested | Failed/retry pending | Not started | Expired results require new attempt if Atlas did not ingest. |
| No provider cancellation | Atlas `cancelled` cannot be confirmed by provider | N/A | N/A | Cancelled only locally/policy | N/A | Missing provider cancellation. |

Atlas must explicitly separate provider job state from Atlas processing-attempt state, normalization state, output-ingestion state, Document business status, and M3 publication state. Provider retry behavior is missing; Atlas retry must be an orchestration decision.

## Section F — Progress and counters

Provider status may expose `documents_total`, `documents_completed`, `documents_planned`, `documents_failed`, `tasks_total`, `tasks_completed`, `pages_total`, `pages_completed`, `percent_complete`, `failed_tasks`, document projections, and task projections. Task projections include `task_id`, `task_index`, `page_start`, `page_end`, `pages_total`, status, attempts, timestamps, and errors. Provider `percent_complete` is page-based (`pages_completed / pages_total`) and only increases.

Atlas can pass through provider document/task/page counters as provider-stage diagnostics, but it must normalize them into Atlas progress phases: source retrieval/transport, provider submission, provider execution, result retrieval, raw-result ingestion, MinerU-Popo normalization, Structured Processing Output creation, and compatibility serialization. Provider progress is task/page/document-level within a provider job. In multi-document jobs, counters combine multiple documents; one Atlas attempt per provider job avoids cross-document progress ambiguity. Result ingestion and MinerU-Popo normalization occur after the provider reports `completed` or `partial_failed`, so Atlas progress must not reach 100% at provider completion unless Atlas deliberately reports provider-stage progress separately.

**Recommendation:** Atlas user-facing M2 attempt progress should not reach 100% until raw-result ingestion, normalization, and output handoff finish. Provider `percent_complete=100` may be displayed only as provider-stage completion.

## Section G — Page ranges and page numbering

Provider async public requests do not accept client-selected page ranges. Instead, the coordinator downloads the whole PDF, counts pages, and creates one-based inclusive source page ranges based on `batch_size`. Each temporary range PDF is processed locally by the provider. Provider range output must have exactly the expected local page count, and local page indexes must be sequential. The provider then sets:

- zero-based original `page_index`;
- one-based `page_number`;
- zero-based `local_page_index`;
- `source_page_range`;
- `page_start`/`page_end` task metadata using one-based inclusive source ranges.

Provider merge behavior flattens completed range pages, sorts by `page_number`, and reports `pages_merged`, `page_order_verified`, `duplicate_pages`, and `missing_pages` in `merge_summary`.

Future Atlas adapter responsibility: convert provider page identity into stable M2 page/evidence mapping while preserving original source page index, provider page number, local range identity, source range, task ID, job ID, and merge anomalies. The adapter must not define final M3 evidence IDs in this task.

Ambiguities to preserve in provenance: repeated pages may appear as duplicate pages, missing pages may occur in partial jobs or bad range outputs, document page count comes from provider PDF counting rather than Atlas Storage metadata unless Atlas separately computes it, and multi-document jobs require document-scoped page numbering to avoid collisions.

## Section H — Provider capabilities

| Capability | Provider classification | Notes | Atlas metadata recommendation |
| --- | --- | --- | --- |
| Supported MIME types | Implemented with caveat | Implementation expects PDF; no declared MIME allowlist. | Record `application/pdf` as effective supported type with caveat. |
| Whole-document processing | Implemented | Sync processes whole uploaded PDF; async downloads whole PDF. | Record supported. |
| Page ranges | Implemented with caveat | Internal provider-created ranges only; no client-selected ranges. | Record internal batching/range support and no public range selection. |
| Batching | Implemented | Async multi-document jobs and page-range tasks. | Record batch size caps/defaults. |
| Async processing | Implemented | `/ocr/jobs` control plane. | Record supported. |
| Sync processing | Implemented with caveat | Unauthenticated, blocking, one multipart PDF. | Record dev/smoke only for Atlas. |
| OCR/text | Implemented | Markdown/text/blocks returned. | Record supported. |
| Layout | Implemented with caveat | Blocks/bboxes/pass-through layout fields where present. | Record supported with provider-native variance. |
| Tables | Implemented with caveat | Blocks/pass-through/statistics/raw; not first-class top-level normalized arrays. | Record partial support. |
| Figures/images | Implemented with caveat | Blocks/pass-through/statistics/raw; image payloads slimmed/null in artifacts. | Record partial support. |
| Formulas | Implemented with caveat | Pass-through/statistics/raw where emitted. | Record partial support. |
| Hierarchy | Unknown | No stable top-level hierarchy contract. | Record unknown/deferred to MinerU-Popo/M3. |
| Reading order | Implemented with caveat | Block `order` where available and sorted page order. | Record partial support. |
| Handwriting | Unknown | Inventory does not claim it. | Record unknown. |
| Language support | Unknown | Inventory does not enumerate languages. | Record unknown. |
| Max file bytes | Implemented with caveat | Async default cap 100 MiB; sync multipart no explicit code limit. | Record async cap/default and sync caveat. |
| Max page count | Absent | No explicit max page count. | Record absent. |
| Batch-size limits | Implemented | Async default 50, cap default 250. | Record. |
| Concurrency limits | Implemented with caveat | Coordinator semaphore default 5/cap 10; OCRWorker serialized by max_containers/max_inputs. | Record effective limits. |
| Cancellation | Absent | No endpoint/state. | Record absent. |
| Retries | Absent | No automatic retry loop; attempts increments once. | Record absent. |
| Partial failure | Implemented | `partial_failed` and fail-fast behavior. | Record supported. |
| Artifact result delivery | Implemented | Full raw result gzip artifact with metadata/checksum/TTL. | Record supported temporary transfer. |

Do not implement capability negotiation in this PR.

## Section I — Error mapping

| Scenario | Provider evidence | Atlas category | Terminal vs retryable | Retry creates new processing attempt? | Partial output may be ingested? | User-facing detail redaction |
| --- | --- | --- | --- | --- | --- | --- |
| Validation failure | `422 INVALID_REQUEST` or `VALIDATION_ERROR`. | Invalid processing request | Terminal until request fixed | No | No | Show safe validation summary only. |
| Unsupported source | PDF-only expectation, non-HTTPS or non-PDF failures. | Unsupported source | Terminal | No unless source/transport changes | No | Redact URL details. |
| Download failure | `PDF_DOWNLOAD_FAILED`, retryable true. | Source transport failure | Retryable | Same attempt retry may be safe before provider success; otherwise new linked attempt | Other docs may be ingested in multi-doc partial | Redact signed URLs. |
| Too-large input | `PDF_TOO_LARGE`, retryable false. | Source exceeds provider limit | Terminal | No unless options/provider change | Other docs may be ingested | Safe size category only. |
| Checksum mismatch | `PDF_HASH_MISMATCH`. | Source integrity mismatch | Terminal | No until source/hash resolved | Other docs may be ingested | Redact URL. |
| Invalid PDF | `INVALID_PDF`. | Invalid source format | Terminal | No | Other docs may be ingested | Safe message. |
| Encrypted PDF | `PDF_ENCRYPTED`. | Unsupported protected source | Terminal | No unless decrypted source supplied | Other docs may be ingested | Avoid exposing password/security internals. |
| Page-count failure | `PDF_PAGE_COUNT_FAILED`. | Provider source planning failure | Terminal unless provider bug suspected | Usually new attempt only after source/provider fix | Other docs may be ingested | Safe message. |
| Provider submission failure | `COORDINATOR_START_FAILED` or submission 500. | Provider submission failure | Retryable | Poll by job ID first; new attempt if no accepted job | No | Redact internal call IDs if sensitive. |
| Timeout | `OCR_TIMEOUT`. | Provider execution timeout | Retryable | Prefer new linked attempt/range policy | Successful pages may be ingested if partial policy allows | Safe timeout category. |
| OCR task failure | `OCR_TASK_FAILED`. | Provider execution failure | Retryable per provider evidence | New attempt/range retry policy | Yes if partial result exists and policy allows | Redact raw exception detail. |
| Partial failure | `partial_failed`, failed tasks/documents. | Partial provider output | Policy-dependent terminal | Retry failed scope via new attempt unless provider range retry exists | Yes, with provenance | Clearly mark incomplete. |
| Malformed result | Bad range output, result parse failure in Atlas. | Malformed provider result | Retryable or terminal by version | Usually retry normalization first; new attempt if raw invalid | Only valid pages if safe | Redact raw payload. |
| Result not ready | `202 RESULT_NOT_READY`. | Provider result pending | Retryable/poll | No | No | Safe. |
| Missing job | `404 JOB_NOT_FOUND`. | Provider job missing | Terminal or uncertain submission | New attempt if no reconcile path | No | Safe job-not-found. |
| Expired job/result | `410 JOB_EXPIRED` or expired status. | Provider result expired | Retryable by new attempt | Yes, new linked attempt if not ingested | No unless Atlas already ingested | Safe. |
| Missing artifact | `404 ARTIFACT_NOT_FOUND`. | Provider artifact missing | Usually terminal for full raw artifact; standard may remain | New attempt if full raw required | Standard result maybe if accepted | Safe. |
| Authentication failure | `401 UNAUTHORIZED` or `503 AUTH_NOT_CONFIGURED`. | Provider auth/config failure | Retryable after config fix | No | No | Never expose token. |
| Internal provider failure | `INTERNAL_ERROR`, coordinator failure, unhandled 500. | Provider internal failure | Retryable depending recurrence | New linked attempt after reconcile | Maybe if partial state exists | Redact stack/internal paths. |

This is conceptual only and does not define public API error schemas.

## Section J — Authentication and security

Atlas may call only bearer-authenticated async job, status, result, and artifact endpoints for the M2 workflow. The bearer token must be owned by deployment/configuration, injected as a secret, never logged, never persisted in raw results, and never exposed to application responses. Logs should redact Authorization headers, signed URL query strings, internal cache keys, and local provider paths.

Provider reality: bearer auth applies to async endpoints only. `/ocr/sync`, `/warmup`, `/health/config`, and `/spike/*` are unauthenticated. Async inputs must be HTTPS and redirects must remain HTTPS. The provider applies byte/time/hash validation but has no hostname/IP allowlist or private-network SSRF block. Secrets are loaded through deployment configuration.

- **M2 development blocker:** none if using a private/dev provider and bearer-authenticated async endpoints with Atlas-controlled URLs.
- **Production hardening:** SSRF/private-network controls, endpoint exposure policy for unauthenticated routes, host allowlist or Atlas-controlled URL policy, and clearer model/provenance endpoint controls are required before production.
- **Deployment policy:** decide whether unauthenticated sync/warmup/config endpoints are inaccessible from public networks or must gain auth. Provider should preferably accept only Atlas-controlled URLs for production unless a safe upload endpoint is added.

## Section K — Result retrieval and TTL

Provider results are available after terminal `completed` or `partial_failed` status. `/result` supports `summary`, `standard`, and `full` profiles. `standard` includes document markdown, flattened blocks, task summaries, pages, and merge summaries. `full` adds slimmed raw results inline when below `RESULT_INLINE_LIMIT_BYTES`; otherwise it returns gzip artifact metadata. Artifacts have metadata including format, compression, size, SHA-256, creation/expiration time, artifact ID, and download endpoint. Job and artifact TTLs are logical; provider storage is temporary Modal Dict/Volume state and is not an Atlas durable persistence guarantee.

Atlas responsibilities: poll until terminal, retrieve the selected result immediately, download artifacts when `full` is offloaded, verify artifact checksum, retry artifact retrieval when retryable and before TTL, copy raw result bytes into Atlas-controlled Storage if raw results are retained, monitor provider TTL relative to ingestion, and handle broken/expired results as failed or retry-needed attempts.

Applications must never depend on provider-temporary result or artifact URLs.

## Section L — Raw Processing Result envelope

Conceptually, Atlas must capture at least:

- Atlas processing attempt identity;
- SourceFile and Document identity;
- provider name (`paddle-vl-api`);
- provider build tag;
- provider job ID, request ID, and artifact/result identifiers where present;
- provider model/pipeline version where available;
- request options (`schema_version`, batch/concurrency/fail-fast/TTL/download/max-byte options);
- result profile ingested (`standard` or `full`);
- source checksum and ETag where available;
- provider and Atlas timestamps;
- raw result bytes or Atlas Storage object reference;
- raw result checksum;
- page/remapping metadata;
- provider warnings/errors/merge anomalies;
- capability snapshot at submission/ingestion time.

Currently unavailable or incomplete provider provenance includes API code revision in responses, stable top-level async model/pipeline version, complete language/handwriting capability declarations, first-class warnings, and live config caps from a stable authenticated endpoint.

## Section M — Raw-result durable ownership

| Option | Assessment against Blueprint | Compatibility result |
| --- | --- | --- |
| Option A: `paddle-vl-api` permanently owns raw results. | Conflicts with Atlas ownership of Raw Processing Result ingestion/lifecycle and provider-independent downstream normalization; provider TTL/storage is temporary. | Not recommended. |
| Option B: Atlas receives inline results and treats provider storage as irrelevant. | Works only for small inline results and ignores artifact TTL/checksum/retry and durable provenance. | Insufficient. |
| Option C: provider temporarily owns execution results; Atlas promptly ingests and retains any durable Raw Processing Result in Atlas-controlled Storage. | Aligns with Storage/Processing boundaries: provider owns execution semantics; Atlas owns Raw Processing Result lifecycle after ingestion. | Recommended direction. |

**Codex Recommendation — Human Confirmation Required:** choose Option C. This PR does not authorize a persistence model, tables, schemas, migrations, or implementation.

## Section N — MinerU-Popo handoff

Current Atlas MinerU-Popo takes per-page PaddleOCR-VL results stored in `PdfPage.ocr_raw_json`, converts them into blocks/model-list input, optionally delegates to `magic-pdf`, and persists MinerU intermediate JSON in `MineruResult.result_json`. Provider async `standard` output supplies page-level markdown and normalized blocks; provider `full` adds sanitized raw per-page result or artifact. Exact shape compatibility is **Unclear** from the inventory alone: shared words such as Markdown and blocks do not prove that provider `standard` can feed the current MinerU-Popo parser directly. `standard` may be sufficient only after fixture-based adapter analysis, while `full` is safer for preserving provider-native fields needed by MinerU-Popo and future debugging.

Atlas needs an adapter transformation from provider pages/blocks/raw_result to the current MinerU-Popo per-page assumptions or a revised MinerU-Popo boundary. Raw page results should be preserved at least through ingestion/normalization. Markdown, blocks, page mapping, source ranges, merge anomalies, tables/images/formulas pass-through lists, and raw provider fields should be retained where available. MinerU-Popo remains responsible for reading order/hierarchy/table/figure/formula cleanup within M2; final canonicalization belongs to M3.

M2 implementation blocker: capture provider result fixtures, choose the result profile with human confirmation, and define/test the provider-output-to-MinerU-Popo input adapter before cutover.

## Section O — Structured Processing Output compatibility

| M2 semantic expectation | Provider output compatibility | Classification | Notes |
| --- | --- | --- | --- |
| Processing block/node identity | No stable Atlas ID; blocks have order/metadata only. | Derivable in Atlas adapter | Generate attempt-scoped identities later; do not make provider index canonical. |
| Type | Block `type` exists. | Directly supplied | Normalize vocabulary in adapter/MinerU-Popo. |
| Order | Block `order` where available; page order sorted. | Directly supplied/derivable | Adapter must preserve and repair gaps. |
| Text/content | Markdown and block text/content. | Directly supplied | Preserve raw and normalized text. |
| Hierarchy | Not stable top-level. | Added by MinerU-Popo / deferred to M3 | Current MinerU-Popo recovers headings. |
| Table references | Blocks/pass-through/raw/statistics, not first-class Atlas references. | Added by MinerU-Popo / deferred to M3 | M3 owns final references. |
| Figure/image references | Blocks/pass-through/raw; image payloads may be slimmed. | Added by MinerU-Popo / deferred to M3 | Atlas may need cropped artifacts separately. |
| Formula references | Pass-through/raw/statistics where emitted. | Added by MinerU-Popo / deferred to M3 | Provider support is caveated. |
| Source/page evidence | Page indexes/numbers/ranges/merge summaries. | Derivable in Atlas adapter | Critical adapter responsibility. |
| Provenance | build tag, job/request IDs, timestamps, options; missing stable model/revision. | Partially supplied | Atlas envelope must add/capture more. |

Provider-specific raw JSON must not become the M2 output contract.

## Section P — Multi-document jobs

Provider supports multiple documents in one async job. Options:

| Option | Evaluation | Recommendation |
| --- | --- | --- |
| A: one SourceFile/document per provider job | Simplifies lifecycle mapping, retries, failure isolation, page counters, result ingestion, provenance, and Reader comparison. Less efficient operationally. | Recommended initial M2 direction, human confirmation required. |
| B: batch multiple Atlas Documents into one provider job | More efficient but complicates partial failures, retries, cancellation, progress, provenance, and ingestion. | Defer until single-doc integration is stable. |
| C: support both immediately | Maximizes flexibility but increases implementation and test complexity. | Not recommended initially. |

**Recommendation requiring human confirmation:** use Option A for initial M2, then revisit batching after status/error/progress/raw-result ingestion is proven.

## Section Q — Partial failures

With `fail_fast=false`, provider can return `partial_failed` and expose successful documents/pages while failed tasks/documents are recorded. With `fail_fast=true`, observed failure stops scheduling, marks queued tasks failed, and produces failed behavior when failures occur.

Atlas may ingest successful documents/pages only if raw-result provenance marks the attempt incomplete and records failed scopes. One failed page should not automatically invalidate all raw evidence, but product policy must decide whether the Atlas processing attempt is failed, partially succeeded, or succeeded-with-warnings. Retries should initially target a new linked processing attempt for the whole document unless a future range retry contract is explicitly designed. Reader compatibility may use partial results only if the UI/API clearly marks incomplete content; M3 should later model incomplete Structured Content explicitly. This review does not define final product policy.

## Section R — Legacy Reader compatibility

Current transitional Atlas behavior to preserve during M2 cutover includes:

- `/api/v1/upload` accepts PDF/TXT, returns `book_id`, title/status/page metadata, and starts PDF background processing while TXT completes synchronously.
- `Document`/book status transitions to processing/completed/failed and stores error messages.
- PDF upload renders pages, records page count, one-based `PdfPage.page_num`, page dimensions, and page image bytes.
- Background OCR writes per-page raw JSON to `PdfPage.ocr_raw_json`, then MinerU-Popo stores `MineruResult.result_json`.
- Reader/content routes assemble content from processed TXT, MinerUResult, PdfPage, and image records.
- Image IDs/markers used by current Reader must continue to resolve while compatibility remains.
- TXT behavior remains synchronous and provider-independent from `paddle-vl-api`.
- Deletion removes book metadata and retained source bytes through Storage while preserving current API semantics.
- Existing error messages and status fields should not be replaced by provider-native errors during cutover.

Provider protocol must not expose Reader-specific formats. Stream Text remains presentation. Compatibility belongs in Atlas integration/serialization. The old local pipeline must remain available until the new pipeline passes comparison and cutover criteria.

## Section S — Compatibility findings by owner

### Compatible without change

- Async job submission, status polling, result retrieval, and artifact retrieval exist with bearer auth. Blocking level: Non-blocking. Evidence: provider endpoint inventory.
- Provider exposes page/document/task counters and result profiles. Blocking level: Non-blocking. Evidence: provider status/result inventory.
- Provider exposes build tag, job ID, request ID, timestamps, and artifact checksum metadata. Blocking level: Non-blocking. Evidence: provider provenance/result inventory.

### Atlas adapter responsibilities

- Resolve Storage references and transport source bytes as Atlas-controlled HTTPS URLs or future uploads. Blocking level: M2 implementation blocker. Evidence: Atlas Storage contract; provider input model.
- Map Atlas attempt/correlation identity to provider `job_id`/`request_id`. Blocking level: M2 implementation blocker. Evidence: provider request model and duplicate job behavior.
- Normalize provider page identity and merge anomalies into stable M2 evidence mapping. Blocking level: M2 implementation blocker. Evidence: provider page remapping inventory.
- Map provider errors into provider-independent categories. Blocking level: M2 implementation blocker. Evidence: provider error inventory.

### Atlas orchestration responsibilities

- Use async endpoints as primary integration and keep sync/spike out of production workflow. Blocking level: Required before cutover. Evidence: provider endpoint/security inventory.
- Keep provider state separate from Atlas attempt, ingestion, normalization, Document, and M3 states. Blocking level: M2 implementation blocker. Evidence: Atlas processing contract; provider lifecycle.
- Define retry/idempotency behavior around duplicate, uncertain, missing, and expired jobs. Blocking level: M2 implementation blocker. Evidence: provider known gaps.
- Decide partial failure and multi-document policy. Blocking level: M2 implementation blocker. Evidence: provider partial and multi-document behavior.

### Atlas persistence/ingestion responsibilities

- Retrieve `standard`/`full` result and artifact before TTL expiry. Blocking level: M2 implementation blocker. Evidence: provider result delivery inventory.
- Verify artifact checksum and copy durable raw result into Atlas-controlled Storage if retained. Blocking level: Required before cutover. Evidence: provider artifact metadata and Atlas Raw Result contract.
- Ensure applications never depend on provider temporary URLs. Blocking level: Required before production. Evidence: provider temporary storage inventory.

### MinerU-Popo responsibilities

- Accept or adapt provider `standard`/`full` output to current per-page PaddleOCR-VL/MinerU-Popo assumptions; exact compatibility remains unclear until fixtures are analyzed. Blocking level: Required before cutover. Evidence: Atlas MinerU-Popo docstring and provider result inventory.
- Preserve page mapping, blocks, markdown, raw result, and visual/table/formula fields needed for normalization. Blocking level: Required before cutover. Evidence: both inventories.

### paddle-vl-api changes recommended before production

- Add/require SSRF private-network blocking or host allowlist for source URLs. Blocking level: Required before production. Evidence: provider security known gaps.
- Add stable top-level model/pipeline/API revision provenance to async results. Blocking level: Required before production. Evidence: provider provenance known gaps.
- Consider auth on sync/warmup/config/spike or restrict public exposure. Blocking level: Required before production. Evidence: provider security inventory.
- Consider cancellation, explicit retry/idempotency, raw-byte upload, page-count limit, first-class warnings, and authenticated capability/config endpoint. Blocking level: Non-blocking to Required before production depending product policy. Evidence: provider known gaps.

### M3 responsibilities

- Final Structured Content identity, evidence IDs, canonical hierarchy, table/figure/formula references, and publication state. Blocking level: Deferred. Evidence: Atlas M2/M3 boundary.

### Deferred issues

- Non-PDF sources for this provider, capability negotiation, final public error schemas, broad batch optimization, and final partial-output product policy. Blocking level: Deferred. Evidence: Atlas roadmap/milestone boundaries and provider current PDF-only reality.

## Section T — Blocking issues

### Blocker for M2 client development

- Human decision on initial source transport.
- Human decision on async as primary integration and whether sync is smoke-only.
- Human decision on Atlas attempt ID to provider `job_id`/`request_id` mapping.
- Human decision on retry/idempotency behavior for duplicate/uncertain/missing/expired jobs.
- Human decision on page identity/remapping contract.

### Blocker for end-to-end integration

- Raw-result retrieval/ingestion ownership and result profile choice.
- Provider result fixtures and MinerU-Popo adapter input shape.
- Provider-to-Atlas status/error/progress mapping.
- Partial failure policy.
- One-document-per-job vs multi-document job granularity.

### Blocker for production cutover

- Durable Atlas-owned raw-result storage policy and TTL monitoring.
- SSRF/private-network hardening or strict Atlas-controlled URL deployment policy.
- Bearer-token/secret ownership and endpoint exposure policy.
- Provider/build/model provenance minimum.
- Legacy/new-pipeline comparison and cutover acceptance criteria.

### Non-blocking hardening

- Provider cancellation, automatic retries, capability negotiation, first-class warnings, authenticated config/capability endpoint, physical cleanup of provider temporary state, and broader source-type support.

## Section U — Human decisions required

1. Initial provider transport: Atlas-controlled HTTPS URL, uploaded bytes/future endpoint, or another transport.
2. Primary integration: async jobs, sync for limited use, or both.
3. Provider job granularity: one Atlas document per provider job or multi-document jobs.
4. Atlas attempt ID ↔ provider job ID mapping.
5. Durable Raw Processing Result ownership.
6. Which result profile Atlas ingests (`standard` vs `full`).
7. Artifact download and TTL policy.
8. Partial failure behavior.
9. Cancellation required now or deferred.
10. Idempotency/retry strategy.
11. Page identity/remapping contract.
12. Authentication and secret ownership.
13. SSRF/private-network hardening timing.
14. Provider/build/model provenance minimum.
15. Legacy pipeline cutover criteria.

## Section V — Recommended implementation sequence

1. Approve compatibility decisions listed in Section U.
2. Capture provider request/response fixtures from the verified protocol and later from controlled live smoke tests.
3. Implement provider-specific Atlas client.
4. Add mocked contract tests for request serialization, auth, status, errors, result profiles, and artifacts.
5. Add provider status/error/progress mapping.
6. Add result retrieval and raw-result ingestion into Atlas-controlled Storage.
7. Add page-remapping adapter.
8. Add MinerU-Popo input adapter.
9. Produce Structured Processing Output behind the M2 boundary.
10. Run live-provider smoke tests outside Required Backend CI.
11. Run legacy/new-pipeline comparison.
12. Add controlled cutover flag.
13. Remove or isolate the legacy path only after acceptance.

No implementation is authorized by this sequence in this PR.

## Section W — Test strategy

Future tests should cover request serialization, auth header creation/redaction, duplicate job handling, status mapping, progress/counters, expired result handling, `full`/`standard` profile parsing, artifact download/checksum verification, page remapping, malformed provider result, partial failure, timeout, retry/idempotency, multi-document behavior, provider provenance capture, MinerU-Popo adapter behavior, legacy/new comparison, mocked Required Backend CI, and manual live-provider smoke. Required Backend CI should use mocked provider fixtures only and must not call the live provider.

## Section X — Decision summary

| Decision | Current evidence | Recommendation | Owner | Blocking level | Human confirmation required? |
| --- | --- | --- | --- | --- | --- |
| Initial provider transport | Provider async accepts HTTPS PDF URLs only; no StorageReference/upload endpoint. | Atlas-controlled temporary HTTPS URL, or request upload endpoint before production. | Atlas adapter/client | M2 implementation blocker | Yes |
| Primary integration | Async endpoints have auth/status/result/artifact; sync is unauthenticated/blocking. | Async primary; sync smoke-only. | Atlas processing orchestration | M2 implementation blocker | Yes |
| Job granularity | Provider supports multi-document jobs. | One Atlas document per provider job initially. | Atlas processing orchestration | M2 implementation blocker | Yes |
| Attempt/job ID mapping | Provider accepts/generates `job_id` and echoes `request_id`; duplicate unexpired IDs rejected. | Atlas-generated provider job ID from processing attempt ID; request ID for correlation. | Atlas adapter/client | M2 implementation blocker | Yes |
| Durable raw-result ownership | Provider state/artifacts are temporary; Atlas contract owns Raw Processing Result lifecycle. | Option C: provider temporary, Atlas durable after ingest. | Atlas persistence/ingestion | M2 implementation blocker | Yes |
| Result profile | `standard` has normalized pages/blocks; `full` adds raw result/artifact; exact MinerU-Popo compatibility is unclear without fixtures. | Prefer `full` for normalization/provenance until fixture analysis proves `standard` is sufficient, unless size/policy chooses `standard` plus artifact fallback. | Atlas persistence/ingestion | Required before cutover | Yes |
| Artifact/TTL policy | Artifacts have checksum and TTL; no durable guarantee. | Download immediately, verify checksum, store durable copy. | Atlas persistence/ingestion | Required before cutover | Yes |
| Partial failure | Provider supports `partial_failed` with successful pages/docs. | Preserve partial raw evidence; mark incomplete; retry via linked attempt until product policy finalizes. | Atlas processing orchestration | Required before cutover | Yes |
| Cancellation | Provider lacks cancellation. | Defer unless product requires cancellation before cutover. | deferred | Non-blocking | Yes |
| Idempotency/retry | Duplicate `job_id` rejection only; no general idempotency key. | Poll existing job before retry; new linked attempt after expiration/missing unreconciled job. | Atlas processing orchestration | M2 implementation blocker | Yes |
| Page remapping | Provider supplies page indexes/numbers/local indexes/source ranges/merge summary. | Preserve all fields and define stable M2 mapping. | Atlas adapter/client | M2 implementation blocker | Yes |
| Auth/secrets | Bearer async only; token from provider deployment config. | Secret owned by deployment; never logged; call only bearer async workflow. | deployment/configuration | Required before production | Yes |
| SSRF timing | Provider HTTPS-only, no private-network block/allowlist. | Development allowed with Atlas-controlled URLs; production requires hardening/policy. | paddle-vl-api | Required before production | Yes |
| Provider provenance minimum | Build tag exposed; no top-level model/API revision in async result. | Require build tag plus model/pipeline/revision where available before production. | paddle-vl-api | Required before production | Yes |
| Legacy cutover | Current Reader depends on MinerUResult/PdfPage/TXT/processed outputs. | Keep old pipeline until comparison passes and flag controls cutover. | Atlas persistence/ingestion | Required before cutover | Yes |
