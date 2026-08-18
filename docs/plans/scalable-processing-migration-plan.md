# Scalable Processing Migration Plan

| Field | Value |
|---|---|
| Document Type | Cross-Repository Implementation Plan |
| Approval Status | Accepted implementation direction |
| Lifecycle Status | Active planning / implementation sequencing |
| Date | 2026-08-15 |
| Applies To | `pdf-ocr-service`, `paddle-vl-api`, `speed-reading-trainer` |
| Related Architecture | [Scalable Storage and Processing Architecture](../architecture/scalable-storage-and-processing-architecture.md) |
| Related Storage Design | [Content-Addressed Artifacts and Document Reuse](../storage/content-addressed-artifacts-and-document-reuse.md) |
| Related Contract | [Processing Attempt and Artifact Manifest v1](../contracts/processing-attempt-and-artifact-manifest-v1.md) |
| Related M5 Reconciliation | [M5 Progress Reconciliation — 2026-08-15](../reviews/m5-progress-reconciliation-2026-08-15.md) |

## 1. Objective

Move Atlas from a working single-service-oriented processing path to a multi-user architecture in which:

- the backend is a thin durable control plane;
- Neon is the business-state plane;
- object storage is the binary/artifact data plane;
- Modal is a retryable elastic CPU/GPU compute plane;
- duplicate documents reuse verified immutable source and processing artifacts;
- long-running processing survives ordinary backend/container restarts;
- large PDFs do not require repeated backend memory buffering or network proxying;
- each migration step can be validated and rolled back independently.

This is a horizontal platform track. It supports M5 Reader reliability and the later M6/M7 product milestones; it is not itself a Smart Reading Intelligence feature and must not be incorrectly moved into M6 scope.

## 2. Implementation rules for every phase

Every implementation PR must state:

1. phase and work item ID from this plan;
2. exact repository and base/head revision;
3. current behavior and target behavior;
4. changed ownership or transport boundary;
5. input/output contract version;
6. idempotency and retry behavior;
7. artifact retention class;
8. memory/network/CPU/GPU expectations;
9. isolated test/staging evidence;
10. rollback/fallback path;
11. whether Production data/config/runtime changes;
12. milestone criteria or external-pilot gate items advanced.

No destructive migration or Production storage/database change is implied by approval of this plan.

## 3. Phase overview

| Phase | Goal | Primary repositories | Production risk |
|---|---|---|---|
| S0 | Baseline and observability | backend + Modal | Low |
| S1 | Object/artifact identity contracts | backend | Low/medium |
| S2 | Durable attempt + fingerprint + single-flight | backend | Medium |
| S3 | Direct object-store transport to Modal | backend + Modal | Medium |
| S4 | Move complete pre-OCR execution boundary to Modal | backend + Modal | Medium/high |
| S5 | Durable shards, resume, resource-aware scheduling, GPU scale | Modal + backend | High but isolated by contract |
| S6 | Modal PDF -> SPR compute boundary | backend + Modal | High |
| S7 | Modal visual artifact generation | backend + Modal | Medium/high |
| S8 | Direct Reader binary delivery and upload optimization | backend + frontend | Medium |
| S9 | Higher-level page/publication reuse and shared content optimization | backend + optional frontend | Evidence-driven |

## 4. S0 — Baseline and observability

### Goal

Create a quantitative current-state baseline before moving compute.

### Required measurements

For representative small/medium/large PDF and TXT fixtures, capture:

- source byte size and page count;
- backend upload peak memory and upload duration;
- backend source/object-store bytes read/written;
- preprocessing wall time and CPU time where available;
- source transport bytes Backend -> Modal;
- Modal download time;
- OCR page/batch duration;
- GPU busy/idle time or bounded proxy metric;
- raw result/shard size;
- canonicalization duration;
- visual asset generation duration;
- object-store reads/writes by stage;
- Reader-open latency and bounded query count;
- end-to-end upload-to-Reader-ready latency;
- failure/retry counts.

### Deliverables

- versioned benchmark fixture list;
- repeatable measurement script/process;
- baseline report committed under `docs/reviews` or `docs/testing`;
- no secret/document-content leakage in metrics.

### Exit criteria

S0 is complete when later phases can compare network, backend memory, CPU, GPU throughput, and time-to-Reader against a stable baseline.

## 5. S1 — Object storage and artifact identity foundation

### Goal

Make artifact identity independent of local filesystem layout and prepare exact source dedupe.

### Work items

**S1.1 ObjectStore capability contract**

Extend/clarify storage abstraction around operations such as `put/create`, `get/stream`, `head`, `exists`, checksum validation, delete, and optional signed/direct-access capability. Do not expose provider-specific path semantics to business code.

**S1.2 Content-addressed source identity**

Use server-verified complete source SHA-256 as physical source identity for new source objects or an equivalent indirection that produces the same dedupe property.

**S1.3 Artifact descriptor**

Implement the v1 descriptor fields and tests before changing Modal execution.

**S1.4 Retention classes**

Represent canonical/recovery/diagnostic/scratch intent explicitly enough for cleanup policies to become reference-aware.

**S1.5 Exact-source dedupe**

After bytes are verified, allow multiple SourceFile/business records to reference the same immutable physical source without cross-user disclosure.

### Tests

- same bytes/different filename -> same physical content identity;
- different bytes/same filename -> different identity;
- collision with different checksum fails closed;
- no client SHA-only ownership bypass;
- delete one logical document does not delete a still-referenced shared source.

### Rollout

Additive first. Existing random `src_...` references may coexist until migrated/rebuilt; do not require an immediate historical-object rewrite.

## 6. S2 — Durable ProcessingRun, fingerprint, reuse, and single-flight

### Goal

Remove process-local orchestration as the only durable owner of long-running work.

### Work items

**S2.1 Early ProcessingRun creation**

Create the durable run before compute submission. Reuse existing ProcessingRun schema where feasible; do not redesign the recent PostgreSQL migration without demonstrated need.

**S2.2 Processing fingerprint v1**

Implement deterministic canonical serialization and output-affecting version inputs.

**S2.3 Completed-result reuse**

Look up compatible successful artifact sets and finalize a new user-owned logical run without recomputing OCR.

**S2.4 Single-flight active claim**

Use durable transactional/database semantics to ensure concurrent compatible requests launch at most one expensive compute flight.

**S2.5 Reconciliation loop**

Provide a bounded operator/background reconciliation path for nonterminal runs after restart.

### Tests

- same compatible request submitted concurrently -> one compute flight;
- second user receives independent Document/run ownership without seeing first user identity;
- restart after submit -> run is recoverable;
- duplicate finalization -> no duplicate selection/candidate corruption;
- new pipeline version -> no stale reuse.

### Exit criteria

Backend process death is no longer sufficient to orphan the only knowledge of an active attempt.

## 7. S3 — Direct Object Storage <-> Modal transport

### Goal

Eliminate the avoidable durable-storage -> Backend RAM -> HTTP source transport -> Modal hop.

### Work items

**S3.1 Direct-read proof in isolated environment**

Use a test/staging bucket/object and Modal secret/capability to read a checksum-pinned source directly.

**S3.2 Compute submission by descriptor**

Submit `artifact_ref + sha256 + size + media_type`, not source bytes or Backend transport URL.

**S3.3 Direct result/artifact write proof**

Where supported safely, let Modal write immutable attempt artifacts directly to object storage and return descriptors.

**S3.4 Keep fallback during rollout**

Preserve the existing `/internal/source-transport` path behind an explicit fallback until direct transport has real acceptance evidence.

**S3.5 Retire in-memory grant dependence**

Only after parity/recovery evidence, remove active processing dependence on process-local transport grants.

### Required evidence

- byte-for-byte source checksum parity;
- authorization capability cannot read arbitrary unrelated objects;
- source read survives Backend restart;
- measured network bytes confirm Backend is no longer proxying source PDFs.

## 8. S4 — Move the complete pre-OCR execution boundary to Modal

### Goal

Move work by coherent execution boundary rather than function-by-function relocation.

### Target compute stage

```text
source PDF
 -> inspection
 -> native text recovery
 -> presentation-page routing
 -> geometry/render planning
 -> OpenCV / preprocessing
 -> provider/OCR subset construction
 -> PaddleOCR-VL for OCR-required pages
 -> original-page remap
```

### Required invariants

- preserve selective OCR;
- presentation/native-text skipped pages remain auditable;
- deterministic original-page mapping;
- no regression to blanket GPU OCR;
- source is read directly from object storage or Modal scratch cache;
- Backend no longer renders/opens the PDF for these heavy stages on the normal path.

### Rollout strategy

1. isolated fixture parity;
2. test deployment;
3. shadow/dual-output comparison on representative PDFs without double-publishing business state;
4. staging acceptance;
5. opt-in Production path;
6. fallback retained until success/error metrics are acceptable.

## 9. S5 — Durable shards, resume, resource-aware batching, fairness, and GPU scale

### Goal

Turn a large document into deterministic independently recoverable work units and make compute actually scale across users.

### Work items

**S5.1 Durable OCR/result shards**

Persist successful range/page outputs as recovery artifacts with checksums.

**S5.2 Resume missing shards**

On retry, validate existing shards and compute only missing/invalid units.

**S5.3 Resource-aware planner**

Replace fixed-page-only policy with bounded page count + rendered pixels + estimated memory + byte size + route/model constraints.

**S5.4 Per-attempt fairness**

Bound in-flight GPU batches per attempt so one huge document cannot monopolize capacity.

**S5.5 GPU autoscaling**

Remove the effective one-container throughput ceiling only after deterministic shard semantics and cost/latency metrics exist.

**S5.6 Backpressure**

Use Modal/runtime capacity controls first. Introduce Queue or additional scheduler infrastructure only when measurements demonstrate a need; Queue is never Atlas durable job truth.

### Exit criteria

A worker/container loss should cause bounded shard retry, not whole-book recomputation.

## 10. S6 — Move PDF -> SPR into Modal

### Goal

Establish SPR as the clean compute/business boundary.

### Target Modal scope

- provider result normalization;
- observation recovery;
- structure recovery;
- bounded LLM structure refinement;
- deterministic validation;
- SPR serialization/storage;
- manifest publication.

### Backend scope after S6

- validate manifest/SPR;
- enforce source/document/business policy;
- deterministic SPR -> SCv2;
- persist candidate and selection;
- finalize ProcessingRun.

### Required tests

- SPR parity against accepted fixtures;
- deterministic replay;
- LLM/provider bounded failure behavior;
- Backend refuses invalid/mismatched manifest;
- Modal has no business DB write path.

## 11. S7 — Move visual asset generation into compute plane

### Goal

Avoid Backend reopening/rerendering the same PDF after Modal already owns source/page geometry.

### Target work

- figure/table crop generation;
- presentation source rendering;
- approved OpenCV normalization/diagnostics;
- rendition checksum/storage;
- artifact descriptor production.

Backend keeps asset/business metadata validation and SCv2 persistence.

### Storage rule

Do not retain every processing raster permanently. Persist Reader-needed visuals, required evidence, bounded diagnostics, and selected recovery artifacts according to retention class. Use scratch/cache for temporary full-page renders.

## 12. S8 — Direct Reader binary delivery and upload-path optimization

### Goal

Remove remaining large binary proxy load from the Backend.

### S8.1 Reader assets

Backend authorizes and returns a short-lived delivery capability/URL; Browser retrieves the binary from object storage/CDN. Durable artifact refs remain hidden/internal where required.

### S8.2 Streaming/direct uploads

Prefer browser -> object storage upload where authorization capabilities support it safely. Otherwise use streaming upload + streaming hash instead of whole-file web-process buffering.

### S8.3 Cross-user upload optimization

Do not skip uploads based only on a client hash. Only introduce proof-of-possession after exact server-verified dedupe is stable and bandwidth metrics justify the complexity.

## 13. S9 — Higher-level reuse and shared canonical content

This phase is evidence-driven and must not delay S1-S8.

Possible work:

- normalized PDF fingerprints;
- page fingerprints and page-level processing cache;
- page-sequence alignment for inserted/removed cover pages;
- publication/edition identity;
- shared immutable ContentPackage to avoid duplicate SCv2 graph rows across many user Documents;
- content/package-level embeddings/intelligence reuse in later milestones.

S9 requires dedicated security, provenance, versioning, deletion, and false-positive analysis before implementation.

## 14. Production safety sequence

For any phase that changes active processing:

```text
contract/tests
 -> disposable/local integration
 -> isolated HF/Modal/Neon staging as applicable
 -> exact-head CI
 -> code review
 -> representative real-document acceptance
 -> opt-in/fallback Production rollout
 -> post-deploy provenance verification
 -> only then retire old path
```

Do not combine database migration, object-store migration, compute-boundary migration, and old-path deletion in one Production change unless a later review proves that coupling is necessary.

## 15. Milestone relationship

This platform plan is horizontal:

- **M5 Reader MVP:** bounded delivery, reliable processing status, reopen/retry behavior, large-document behavior, and multi-user readiness depend on parts of this plan.
- **M6 Smart Reading Intelligence:** consumes stable content/artifacts and benefits from dedupe/reuse but does not own this infrastructure.
- **M7 Smart Archive:** benefits from shared durable content/artifacts and lifecycle/retention foundations.
- **External pilot/commercial gate:** durable status, retry/idempotency, secure ownership, quotas/cost controls, observability, backup/restore, retention/deletion, and incident recovery are directly advanced by this plan.

Product milestone status and scalability-phase status must be reported separately.

## 16. Recommended next implementation slice

After this documentation reconciliation, the next engineering work should begin with **S0 + the smallest non-invasive parts of S1**:

1. baseline current network/memory/latency;
2. formalize `ArtifactDescriptor`/ObjectStore capabilities in tests;
3. prove content-addressed exact-source identity on isolated/test data;
4. do not yet move OpenCV/OCR stages;
5. then implement S2 durable attempt/fingerprint semantics before changing the main compute boundary.

This order prevents compute migration from hardening another temporary storage/orchestration contract.
