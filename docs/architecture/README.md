# Atlas Architecture Documentation

| Field | Value |
|---|---|
| Document Type | Reference / Index |
| Approval Status | Accepted |
| Lifecycle Status | Active |
| Date | 2026-08-15 |
| Authority Domain | Navigation and discovery only |
| Applies To | `docs/architecture` conceptual architecture documentation |
| Related Governance | [Atlas Documentation Governance](../project/document-governance.md) |

## Purpose

Architecture documents define or propose conceptual boundaries, semantic ownership, responsibilities, layers, and platform models.

This index provides navigation and discovery only. It does not change the status, authority, lifecycle, or meaning of any indexed document.

## Current implementation-facing architecture

For new storage/processing/concurrency work, start with:

1. [Atlas Scalable Storage and Processing Architecture](scalable-storage-and-processing-architecture.md) — accepted target direction for Neon business state, durable object/artifact plane, Modal elastic compute, thin Backend control plane, CPU/GPU placement, direct binary paths, failure recovery, and cross-repository ownership.
2. [Content-Addressed Artifacts and Duplicate Document Reuse](../storage/content-addressed-artifacts-and-document-reuse.md) — physical source/artifact sharing, exact-source dedupe, processing reuse, single-flight, retention, and cross-user security boundary.
3. [Processing Attempt and Artifact Manifest Contract v1](../contracts/processing-attempt-and-artifact-manifest-v1.md) — attempt/fingerprint/manifest/retry/reconciliation semantics.
4. [Scalable Processing Migration Plan](../plans/scalable-processing-migration-plan.md) — S0–S9 implementation sequence and rollout gates.

These documents refine execution/storage placement without changing the canonical M4 Structured Content ownership boundary or authorizing a big-bang Production migration.

## Core Architecture Documents

| Document | Declared Status | Primary Topic | Notes |
|---|---|---|---|
| [scalable-storage-and-processing-architecture](scalable-storage-and-processing-architecture.md) | Accepted target direction | Multi-user storage, compute, network, retry, and cross-repository execution architecture | Current implementation-facing target for the horizontal scalability track. |
| [atlas-philosophy](atlas-philosophy.md) | Records accepted Atlas architecture principles | Mission and design principles for Atlas as a Document Intelligence Platform | Indexed for discovery without precedence. |
| [atlas-processing-architecture-overview](atlas-processing-architecture-overview.md) | `Draft v1.0` | Provider-independent processing layers, recovery principles, and SPR-oriented processing boundaries | Informative architecture guide. |
| [canonical-data-flow](canonical-data-flow.md) | Accepted conceptual data flow | Conceptual flow from Document and SourceFile through ProcessingRun, Observation, Canonical Knowledge, and Applications | Architecture only. |
| [document-core-information-model](document-core-information-model.md) | `Proposed` | Semantic responsibilities across processing interpretation, evidence, provenance, accepted content, versions, projections, and presentation | Proposed architecture-only model. |
| [document-core-structured-content-architecture](document-core-structured-content-architecture.md) | Proposed M3 architecture | Structured Processing Result and Structured Content layers | Historical/foundation architecture. |
| [document-intelligence-platform](document-intelligence-platform.md) | Proposed target architecture | Shared Document Core, applications, compute services, object storage, and metadata persistence | Broad platform model. |
| [persistence-processing-foundation](persistence-processing-foundation.md) | Documentation-only architecture contract for M1-005 | Lifecycle from retained source through processing, content, and presentation | Conceptual foundation. |
| [recovery-presentation-architecture](recovery-presentation-architecture.md) | M4 architecture | Recovery Presentation responsibilities | Indexed for discovery without precedence. |

## Architecture-adjacent documents

### ADRs

The central ADR discovery index is [Atlas Architecture Decision Records](../adr/README.md). Domain-local ADRs currently remain in [`adr/`](adr/).

### Reviews and current-state assessments

| Document | Role | Date/As-of Signal | Notes |
|---|---|---|---|
| [Current-State Cross-Repository Review](current-state-review.md) | Review/evidence record | 2026-07-11 | Point-in-time assessment, not current target merely because indexed. |
| [M5 Progress Reconciliation](../reviews/m5-progress-reconciliation-2026-08-15.md) | Milestone progress review | 2026-08-15 | Current M5 progress/evidence overlay and horizontal scalability-track relationship. |

### Contract-like and conformance documents

See the [Contracts index](../contracts/README.md). Architecture-local contract-like documents include [Atlas Document Processing Contract](document-processing-contract.md), [Atlas Block Recovery Contract v1.0](atlas-block-recovery-contract-v1.md), and [Atlas Provider Conformance Profile v1](atlas-provider-conformance-profile-v1.md).

## Relationship notes

Inclusion does not establish precedence. Newer commit date does not automatically supersede an Accepted Contract/ADR/released baseline. The scalable target architecture governs its stated storage/compute/execution domain; canonical Structured Content and product milestone authorities remain in their own documents.
