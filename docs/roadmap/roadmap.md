# Atlas Roadmap

| Field | Value |
|---|---|
| Document Type | Roadmap |
| Authority Domain | Current Atlas Roadmap v3 milestone ordering, high-level scope boundaries, current status, and horizontal platform-track relationship |
| Applies To | M1 through M7 plus cross-cutting scalability/reliability work |
| Related Roadmap v3 Decision | [roadmap-v3-decision.md](roadmap-v3-decision.md) |
| Related Roadmap v3 Review | [roadmap-v3-review.md](roadmap-v3-review.md) |
| Related Milestone Index | [../milestones/README.md](../milestones/README.md) |
| Latest M5 Reconciliation | [../reviews/m5-progress-reconciliation-2026-08-15.md](../reviews/m5-progress-reconciliation-2026-08-15.md) |
| Scalability Plan | [../plans/scalable-processing-migration-plan.md](../plans/scalable-processing-migration-plan.md) |
| Related Governance | [../project/document-governance.md](../project/document-governance.md) |

`roadmap.md` is the current Roadmap v3 view. The accepted sequencing decision remains [Roadmap v3 Decision](roadmap-v3-decision.md); detailed milestone files govern detailed milestone scope and exit criteria.

> **Current notice — 2026-08-15:** M4 is Complete. M5 Reader MVP remains **In Progress**, but the old documentation that treated Slice 1 as Not Started is stale. Substantial Reader/backend/frontend implementation exists; M5 completion evidence is not yet complete. M6 and M7 remain Planned. Atlas also has a horizontal S0–S9 scalability/reliability track that supports multiple product milestones without becoming M6 product scope.

## 1. Project identity

- Product name: **Atlas**.
- Technical category: **Document Intelligence Platform**.
- Product structure:

```text
Atlas
├── Shared Structured Content / Structured Document foundations
├── Reader MVP
├── Smart Reading Intelligence
└── Smart Archive
```

Reader, Smart Reading Intelligence, and Smart Archive are peer applications/capability layers over shared content, provenance, evidence, storage, and processing foundations. None owns provider payloads as canonical truth.

## 2. Current milestone status

| Milestone | Name | Status | Current meaning |
|---|---|---|---|
| M1 | Foundation | Complete | Historical foundation milestone. |
| M2 | Document Processing Foundation | Complete | Complete for revised Raw Processing Result boundary. |
| M3 | Document Core & Structured Content Foundation | Complete for revised scope | SPR, normalization, recovery, diagnostics, fixtures, evidence, and deterministic-validation foundation. |
| M4 | Structured Content / Structured Document Foundation | Complete | Selected canonical content lifecycle, deterministic transformation/persistence, Structured Document/projection foundation. |
| M5 | Reader MVP | **In Progress** | Substantial implementation exists across Reader v2/general reading/Speed Reading/asset and bounded-delivery work. Final 22-criterion completion review remains open. |
| M6 | Smart Reading Intelligence | Planned | Selected evidence-backed intelligence after stable M4/M5 foundations. |
| M7 | Smart Archive | Planned | Peer application over shared content/provenance/evidence/lifecycle foundations. |

For M5 status details, consult [M5 Progress Reconciliation — 2026-08-15](../reviews/m5-progress-reconciliation-2026-08-15.md), not the historical July assumption that Slice 1 is still next.

## 3. Delivery flow

Completed shared foundation:

```text
Source Evidence
  -> retained source
  -> Processing / Raw Processing Result
  -> Structured Processing Result
  -> Structured Content / Structured Document
  -> selected canonical content / projection boundary
```

Current product frontier:

```text
M5 Reader MVP
  -> bounded Reader application/API
  -> general reading
  -> navigation/recovery/assets
  -> Basic Speed Reading
  -> lexical find/lifecycle/completion evidence
```

Downstream product milestones:

```text
M6
  stable content + Reader + evidence
  -> selected Smart Reading Intelligence

M7
  shared content/provenance/evidence/lifecycle
  -> Smart Archive
```

## 4. Horizontal scalability and multi-user platform track

The product milestone sequence is no longer sufficient by itself to describe the platform work needed for multi-user concurrency, large PDFs, durable processing, storage efficiency, and external-pilot readiness.

Atlas therefore maintains a separate horizontal implementation track:

- [Scalable Storage and Processing Architecture](../architecture/scalable-storage-and-processing-architecture.md)
- [Content-Addressed Artifacts and Duplicate Document Reuse](../storage/content-addressed-artifacts-and-document-reuse.md)
- [Processing Attempt and Artifact Manifest v1](../contracts/processing-attempt-and-artifact-manifest-v1.md)
- [Scalable Processing Migration Plan](../plans/scalable-processing-migration-plan.md)

### 4.1 Why it is horizontal

This work includes object-storage/data-plane design, durable ProcessingRun orchestration, idempotency/single-flight, cross-user exact-source/processing reuse, Backend/Modal transport, CPU/GPU scaling, shard recovery, and binary-delivery optimization.

It is not a Reader feature, Smart Reading Intelligence feature, or Smart Archive feature by itself. It supports all of them.

### 4.2 S0–S9 phases

| Phase | Platform goal |
|---|---|
| S0 | Current network/memory/CPU/GPU/latency baseline and observability |
| S1 | Object/artifact identity, exact content addressing, retention classes |
| S2 | Durable attempt, processing fingerprint, completed reuse, single-flight, reconciliation |
| S3 | Direct Object Storage <-> Modal transport; remove Backend binary proxy from processing path |
| S4 | Move coherent pre-OCR PDF execution boundary to Modal while preserving selective OCR |
| S5 | Durable shards, partial retry, resource-aware batching, fairness, real GPU scale-out |
| S6 | Make PDF -> SPR the Modal compute boundary |
| S7 | Move visual asset generation into the compute plane |
| S8 | Direct Reader binary delivery and safe upload-path optimization |
| S9 | Evidence-driven page/publication reuse and optional shared canonical ContentPackage |

Product milestone and scalability phase are reported separately. Example:

```text
Product milestone: M5
Scalability phase: S2
```

or:

```text
Product milestone: horizontal-only
Scalability phase: S3
```

This prevents infrastructure work from silently distorting M6/M7 product scope.

## 5. M1 — Foundation

- **Status:** Complete.
- Foundation, migrations, Document/SourceFile, storage adapter, source retention, and M1->M2 handoff are preserved as completed historical foundation.

## 6. M2 — Document Processing Foundation

- **Status:** Complete.
- Completed the revised provider integration and retained Raw Processing Result boundary. Provider interpretation/canonical content remained downstream at that stage.

## 7. M3 — Document Core & Structured Content Foundation

- **Status:** Complete for revised scope.
- Completed provider-independent SPR foundation, normalization, recovery semantics, diagnostics, evidence linkage, fixtures, and deterministic validation.

## 8. M4 — Structured Content / Structured Document Foundation

- **Status:** Complete.
- Established the selected/canonical content lifecycle, deterministic SPR-to-candidate transformation, durable persistence/selection/ProcessingRun provenance foundation, Structured Document assembly, and derived Reader projection boundary.

M4 completion does not imply public/commercial readiness and does not make provider/raw/SPR output canonical application content.

## 9. M5 — Reader MVP

- **Status:** **In Progress**.
- **Goal:** stable repeated-use Reader over selected M4 content, with general reading, Basic Speed Reading, navigation, asset/recovery behavior, lexical find, reopen/lifecycle semantics, and bounded large-document delivery.

### 9.1 Current progress

The 2026-08-15 reconciliation supersedes only the stale progress assumption, not the accepted M5 scope:

- original backend Slices 1–4 are implemented/evolved;
- Reader client integration and Basic Speed Reading are substantially implemented;
- lexical find requires explicit completion verification;
- lifecycle/delete and legacy cutover posture remain partial/open;
- integrated scale/accessibility/completion evidence remains incomplete;
- the 22-criterion completion mapping has not yet been accepted.

Therefore M5 stays In Progress.

### 9.2 M5 current work priorities

1. resolve current Reader correctness issues through separately scoped PRs;
2. explicitly verify lexical find;
3. reconcile reopen/delete/shared-artifact lifecycle semantics;
4. inventory legacy/parity/cutover dependencies;
5. declare PDF/TXT support and limitations;
6. assemble integrated scale/accessibility/failure evidence;
7. complete the 22-criterion completion review and M5->M6 handoff.

Horizontal S0–S9 work may proceed when it improves M5 reliability or prepares future load, but does not replace this product-completion evidence.

## 10. M6 — Smart Reading Intelligence

- **Status:** Planned.
- **Goal:** add a selected subset of evidence-backed intelligence after stable M4/M5 foundations.

Candidate priority remains:

1. evidence-backed chapter summaries;
2. citation-backed document Q&A;
3. Flashcards;
4. Mind Map;
5. broader AI Tutor.

Semantic search belongs in M6. Evidence, citations, provenance, cost, privacy, security, and safe failure behavior are required for selected features.

**M6 does not own the S0–S9 storage/compute scalability program.** It consumes that platform as needed.

## 11. M7 — Smart Archive

- **Status:** Planned.
- **Goal:** build Smart Archive as a peer application over shared Structured Content, provenance, evidence, metadata, lifecycle, and retrieval foundations.

Smart Archive does not own canonical content and must not duplicate Reader content models or consume provider JSON/Reader serialization as archive truth.

## 12. Scope-transfer ledger

| Previous scope location | Accepted destination | Scope |
|---|---|---|
| Former overloaded M4 | M4 | Structured Content/Structured Document foundation, selection, evidence/assets, projection boundary, ProcessingRun foundation |
| Former overloaded M4 | M5 | Reader API/client, navigation, Recovery Presentation, image/table display, lexical find, Basic Speed Reading |
| Former overloaded M4 | M6 | Summaries, Q&A, Flashcards, Mind Map, AI Tutor/RAG, semantic search |
| Former M5 | M7 | Smart Archive and archive workflows |
| Cross-cutting production/platform concerns | Horizontal requirements + S0–S9 + external gate | durability, idempotency, storage/compute scaling, ownership, observability, retention, security, cost/recovery |

## 13. Production and readiness policy

### Horizontal requirements

Each applicable milestone/phase must address:

- migrations;
- deterministic tests;
- failure behavior;
- cleanup/retention;
- logging/observability;
- provenance;
- access-boundary awareness;
- secret safety;
- compatibility/rollback;
- documented limitations.

### External pilot/commercial gate

Before an external/public/commercial claim, Atlas requires, at minimum:

- authentication;
- authorization;
- user/tenant ownership;
- durable/reliable processing status;
- retry/idempotency;
- secure storage/deployment;
- provider quotas and cost controls;
- observability;
- backup/restore;
- retention/deletion policy;
- security/privacy review;
- incident/failure recovery.

M5 completion alone does not satisfy this gate. S0–S9 directly advances several gate requirements but does not automatically authorize release.

## 14. Current deferred/evidence-driven decisions

Still requiring explicit later decisions/evidence include:

- M5 final lexical-find verification;
- Reader delete/shared-artifact lifecycle semantics;
- Reader legacy cutover/deprecation and destructive cleanup authorization;
- exact production SLOs, maximum supported document size, throughput/cost targets;
- final user/tenant/auth model;
- final storage provider choice if current object storage ceases to satisfy the contract;
- final external release plan;
- complete M6 feature set;
- M7 implementation decomposition;
- exact retention windows and final privacy/security policy;
- whether S9 shared ContentPackage is justified by real duplication scale.

## 15. Detailed records

- [Milestone index](../milestones/README.md)
- [M1](../milestones/M1.md)
- [M2](../milestones/M2.md)
- [M3](../milestones/M3.md)
- [M4](../milestones/M4.md)
- [M5](../milestones/M5.md)
- [M6](../milestones/M6.md)
- [M7](../milestones/M7.md)
- [M5 Progress Reconciliation — 2026-08-15](../reviews/m5-progress-reconciliation-2026-08-15.md)
- [Scalable Processing Migration Plan](../plans/scalable-processing-migration-plan.md)

Roadmap status is sequencing/status guidance; detailed milestone files and accepted contracts/ADRs retain authority within their domains.
