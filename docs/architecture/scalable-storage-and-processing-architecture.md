# Atlas Scalable Storage and Processing Architecture

| Field | Value |
|---|---|
| Document Type | Target Architecture |
| Decision Status | Accepted target direction |
| Implementation Status | Phased migration required |
| Date | 2026-08-15 |
| Authority Domain | Storage, processing execution, compute placement, artifact flow, and cross-repository responsibility boundaries |
| Applies To | `pdf-ocr-service`, `paddle-vl-api`, `speed-reading-trainer` |
| Related Storage Design | [Content-Addressed Artifacts and Document Reuse](../storage/content-addressed-artifacts-and-document-reuse.md) |
| Related Processing Contract | [Processing Attempt and Artifact Manifest v1](../contracts/processing-attempt-and-artifact-manifest-v1.md) |
| Related Migration Plan | [Scalable Processing Migration Plan](../plans/scalable-processing-migration-plan.md) |
| Related Milestone | [M5 — Reader MVP](../milestones/M5.md) |

## 1. Purpose

This document defines the target architecture for Atlas under multi-user concurrency and large-document load. The goal is not to move individual OpenCV functions between hosts. The goal is to establish durable ownership boundaries that let storage, CPU work, GPU work, memory use, and network transfer scale independently.

The target architecture must:

- keep durable business state authoritative in PostgreSQL;
- keep large binaries and immutable processing artifacts outside PostgreSQL;
- prevent the web/control backend from becoming the data-transfer or heavy-PDF-processing bottleneck;
- let CPU-heavy and GPU-heavy work scale independently;
- minimize repeated transfer and repeated rendering of large PDFs;
- make processing resumable and idempotent across container/backend restarts;
- permit cross-user reuse of identical immutable source and processing artifacts without sharing user-owned business state;
- preserve provenance for every processing attempt;
- preserve the existing provider-independent SPR and Structured Content boundaries;
- allow incremental migration without a big-bang rewrite.

## 2. Target platform model

Atlas is divided into four planes.

```text
Browser / Client
      |
      | small API commands, metadata, status
      v
+----------------------------+
| Atlas Control Plane        |
| pdf-ocr-service initially  |
|                            |
| auth / ownership           |
| document lifecycle         |
| ProcessingRun lifecycle    |
| validation / finalization  |
| SCv2 persistence/selection |
| Reader semantic API        |
+-------------+--------------+
              |
              | short transactions
              v
+----------------------------+
| Neon PostgreSQL            |
| Business State Plane       |
|                            |
| Documents / SourceFiles    |
| ProcessingRuns             |
| Structured Content v2      |
| selections                 |
| user/tenant state later    |
+----------------------------+

Large binary path:

Browser ----> Durable Object Storage <----> Modal Elastic Compute Plane
                    |                            |
                    | source/artifacts           | CPU planner/preprocess
                    | manifests/SPR              | GPU OCR
                    | Reader visual assets       | structure/refinement
                    |                            | visual asset generation
                    +----------------------------+
```

### 2.1 Neon PostgreSQL — Business State Plane

Neon owns canonical relational/business state. It stores identity, relationships, lifecycle state, selection state, Structured Content v2, and references to binary artifacts. It must not become a large binary/object store.

Modal workers do not directly mutate Atlas business tables. Compute concurrency therefore must not translate into one database connection or transaction stream per OCR worker.

### 2.2 Durable Object Storage — Data and Artifact Plane

Object storage is the durable binary data plane and the primary exchange medium between the control plane and compute plane. It stores, according to retention policy:

- retained source PDF/TXT and future source formats;
- raw provider/OCR results or shards where retained;
- SPR;
- immutable processing manifests and completion descriptors;
- Reader visual assets;
- bounded recovery artifacts and diagnostics;
- other large immutable/rebuildable processing objects.

Large data should travel `Object Storage <-> Modal` directly. The control backend should exchange compact references, checksums, sizes, versions, and status descriptors rather than proxying PDF/PNG/large-JSON bytes.

The current storage provider may remain Hugging Face Storage Buckets during early migration if direct authenticated object access satisfies the required contract. Provider choice must remain behind an object-store abstraction so a later S3/R2/GCS migration does not redefine business semantics.

### 2.3 Modal — Elastic Compute Plane

Modal owns retryable processing work, not Atlas business truth. It should evolve from a single OCR provider into separately scalable resource pools:

- document planner / inspection pool;
- CPU preprocessing pool;
- GPU OCR pool;
- structure/refinement pool;
- visual artifact pool;
- final SPR assembly/validation compute.

The long-term compute/business boundary is SPR plus an immutable artifact manifest. Modal may produce SPR and Reader-ready binary artifacts, while `pdf-ocr-service` validates the returned manifest and owns SCv2 persistence and selection.

### 2.4 Backend — Thin Control Plane

The backend owns commands and policy, not heavy binary movement. Its target responsibilities are:

- authentication and authorization;
- user/tenant/document ownership;
- source registration/finalization;
- durable ProcessingRun creation before compute submission;
- idempotency/single-flight decisions;
- submission and reconciliation of compute attempts;
- validation of artifact descriptors/manifests/checksums;
- deterministic SPR -> Structured Content v2 persistence;
- candidate selection and business lifecycle rules;
- Reader semantic APIs and access decisions.

Production web processes should not need to hold whole PDFs or large raster buffers merely to relay them between storage and compute.

## 3. Canonical ownership matrix

| Concern | Canonical owner | Notes |
|---|---|---|
| Document/user/tenant identity | Backend + Neon | Business semantics |
| Source-file business registration | Backend + Neon | References immutable source object |
| Source bytes | Object storage | Content-verified durable object |
| Processing attempt lifecycle | Backend + Neon | Durable `ProcessingRun` truth |
| Live provider progress | Modal/ephemeral cache | Advisory; reconstructable |
| PDF inspection/routing | Modal compute | Retryable compute |
| Native-text recovery | Modal CPU target | Keep selective OCR behavior |
| PDF rendering/OpenCV | Modal CPU target | Avoid web-process CPU/RAM pressure |
| PaddleOCR-VL | Modal GPU | Independently autoscaled |
| OCR shards | Object storage | Recovery/reuse units where retained |
| Structure refinement | Modal CPU/network-I/O target | Not tied to web request lifecycle |
| SPR | Object storage | Provider-neutral compute result |
| Figure/table/presentation binaries | Object storage | Compute may be Modal; Reader references durable objects |
| SCv2 candidate graph | Neon | Business/application content boundary |
| Selection/current content | Neon | Never decided by Modal |
| Reader semantic projection | Backend | Derived from selected canonical content |
| Reader binary delivery | Object store/CDN target | Backend authorizes, should not proxy bytes long term |
| Modal Volume | Modal scratch/cache | Never canonical truth |
| Modal Dict | Modal transient progress/cache | Never canonical Atlas state |
| Modal Queue | Optional execution primitive | Not required as durable truth |

## 4. Target processing flow

```text
1. Source upload / registration
   Browser -> Object Storage
   Backend -> verify/register SourceFile

2. Durable attempt
   Backend -> create ProcessingRun(processing_attempt_id)
   Backend -> calculate processing_fingerprint

3. Reuse/single-flight decision
   succeeded compatible artifact set -> reuse
   compatible active attempt -> join/single-flight
   otherwise -> submit new Modal attempt

4. Compute
   Modal -> read source directly from Object Storage
   Modal planner -> inspect/routes/batches
   CPU pool -> native text, routing, rendering, OpenCV
   GPU pool -> OCR only where required
   Modal -> durable OCR/result shards as needed
   Modal -> structure recovery/refinement
   Modal -> SPR + visual artifacts
   Modal -> immutable artifact manifest + completion descriptor

5. Finalization
   Backend -> read compact descriptor/manifest
   Backend -> validate identity/version/hash/required artifacts
   Backend -> deterministic SPR -> SCv2
   Backend -> persist candidate/selection/ProcessingRun result transactionally

6. Reader
   Browser -> Backend for semantic content/authorization
   Browser -> signed object/CDN path for binary assets when enabled
```

## 5. Preserve selective OCR

The current PDF path already avoids unnecessary OCR for reliable native-text pages and can skip OCR for confirmed presentation pages. This behavior is an architectural asset and must survive compute migration.

The target planner should classify page work into explicit routes such as:

```text
native_text
presentation_source
ocr_required
fallback_ocr
```

Moving work to Modal must not regress into “render every page and OCR every page on GPU.”

## 6. CPU, GPU, memory, and batching

### 6.1 Separate CPU and GPU pools

CPU work includes PDF parsing, native-text extraction, rendering, geometry, OpenCV, crop generation, deterministic recovery, and much SPR construction. GPU workers should focus on work that benefits from GPU acceleration, primarily PaddleOCR-VL inference.

This lets Atlas scale CPU concurrency without reserving GPUs, and scale GPU capacity without duplicating unrelated preprocessing work.

### 6.2 Resource-aware batching

A fixed page count is not a sufficient resource model. A page can vary dramatically in dimensions, DPI, raster memory, and model cost. Batching should eventually consider:

- maximum pages;
- source/provider bytes;
- rendered pixel count;
- estimated peak memory;
- page route/type;
- model/runtime limits.

The planner should emit deterministic batch descriptors and keep every batch independently retryable.

### 6.3 Fairness under multi-user load

One very large document must not monopolize the GPU pool. Each attempt should have a bounded number of in-flight GPU batches, while the platform controls total worker capacity. Later commercial policy may add tenant/plan quotas, but the initial scheduler only needs bounded per-attempt fanout and global capacity limits.

### 6.4 Actual GPU scale-out

Logical coordinator concurrency is not equivalent to GPU scale-out. The current Modal worker configuration must eventually allow more than one GPU container when load requires it. Scaling changes require measured cost/latency evidence and must preserve deterministic batch/result behavior.

## 7. Network-transfer rules

The following are target invariants:

1. A source PDF should not be routed `Object Storage -> Backend -> Modal` when Modal can read the authorized object directly.
2. Large compute results should not be routed `Modal -> Backend memory -> Object Storage` when Modal can write immutable artifacts directly.
3. Backend/Modal messages should normally contain descriptors, not full binary payloads.
4. Repeated workers should reuse an attempt-local/shared scratch copy when appropriate rather than each downloading the full source independently.
5. Reader image delivery should eventually avoid `Object Storage -> Backend -> Browser` proxying when access-controlled direct delivery is available.

## 8. Modal scratch/cache model

Modal Volume may be used as a shared scratch/cache within an attempt:

```text
Object Storage
    -> one verified download
Modal scratch/cache
    -> CPU/GPU workers
```

A cache miss or lost Volume must be recoverable by downloading the durable artifact again. The Volume therefore cannot be the only copy of a canonical source, SPR, manifest, or Reader asset.

Per-worker temporary files remain ephemeral and should be deleted automatically or at attempt cleanup.

## 9. Failure and recovery properties

The architecture must make the following failures routine rather than catastrophic:

- Modal container termination;
- GPU worker loss;
- partial batch failure;
- Backend restart during long processing;
- duplicate user submission;
- duplicate callback;
- callback loss;
- artifact already exists;
- transient object-store failure;
- retry after provider timeout.

Recovery is based on durable ProcessingRun state plus immutable artifacts/manifests. Callback is a latency optimization, not the only durability mechanism. A reconciliation path must be able to inspect active runs and durable completion descriptors after Backend restart.

## 10. Commit ordering and consistency

Prefer artifact-first, database-second finalization:

```text
compute artifact exists and checksum verified
        -> manifest exists
        -> Backend validates
        -> DB transaction marks canonical result/success
```

An unreferenced artifact can be garbage-collected later. A database row claiming success while a required artifact does not exist is not acceptable.

Object writes should be create-only/content-addressed where possible. Same key + same checksum is reuse; same key + different checksum is a hard integrity failure.

## 11. Cross-repository responsibilities

### `pdf-ocr-service`

Owns control-plane contracts, ProcessingRun business state, object metadata/reference validation, SCv2 persistence/selection, Reader semantic API, access control, reconciliation, and rollout gates.

### `paddle-vl-api`

Evolves into the Modal execution implementation: direct object reads/writes, planner, CPU/GPU execution pools, shard/result production, resumability, compute-side manifest production, and measured autoscaling behavior.

It must not own Atlas user/document business semantics or mutate Neon business state directly.

### `speed-reading-trainer`

Consumes bounded Reader semantics and status. Upload and Reader binary paths may later change to direct object-store flows, but the client must not infer cross-user dedupe state or treat object-storage identity as user ownership.

## 12. Non-goals and constraints

This architecture does not require immediately:

- replacing Neon;
- one database per user;
- moving all existing objects to a new provider;
- Kafka or Redis;
- Modal Queue as durable job truth;
- storing every rendered page permanently;
- rewriting stable Structured Content v2 semantics;
- allowing Modal to mutate selection/business state;
- a one-shot migration of every PDF processing stage.

## 13. Implementation authority

Implementation follows [Scalable Processing Migration Plan](../plans/scalable-processing-migration-plan.md). Each PR must identify:

- architecture phase;
- affected repository/resource plane;
- input/output contract version;
- idempotency/retry behavior;
- artifact retention class;
- rollback path;
- test/staging evidence;
- whether Production behavior/configuration changes.

No phase should depend on undocumented process memory as its only recovery mechanism.
