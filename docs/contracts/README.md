# Atlas Contracts

| Field | Value |
|---|---|
| Document Type | Reference / Index |
| Approval Status | Accepted |
| Lifecycle Status | Active |
| Date | 2026-08-15 |
| Authority Domain | Navigation and discovery only |
| Applies To | `docs/contracts` and contract-like document discovery |
| Related Governance | [Atlas Documentation Governance](../project/document-governance.md) |

## Purpose

Contracts define verifiable behavior, schemas, protocols, compatibility, and conformance when accepted and versioned. This index is a discovery point; it does not itself assert runtime conformance.

## Contracts in this directory

| Document | Declared Status | Version | Primary Scope | Notes |
|---|---|---|---|---|
| [Processing Attempt and Artifact Manifest Contract](processing-attempt-and-artifact-manifest-v1.md) | Accepted for phased implementation; runtime conformance not yet claimed | v1 | Durable processing identity, fingerprint/idempotency, artifact descriptors/manifests, Backend/Modal handoff, single-flight, retry/reconciliation | Current implementation-facing contract for scalability phases S1–S6. |
| [Reader Content Stream Protocol v2](reader-content-stream-v2.md) | Not explicitly declared | v2 | Reader content stream markers and compatibility behavior | In-directory protocol contract. |
| [Atlas Structured Processing Result Contract v1](structured-processing-result-v1.md) | Proposed provider-independent M3 contract | v1 | Structured Processing Result representation and validation expectations | Foundational processing-result contract. |

## Contract-like documents outside this directory

| Document | Current Location | Existing Self-description | Discovery Note |
|---|---|---|---|
| [Atlas Document Processing Contract](../architecture/document-processing-contract.md) | `docs/architecture` | Document-processing contract | Architecture-local contract-like document. |
| [Atlas Block Recovery Contract v1.0](../architecture/atlas-block-recovery-contract-v1.md) | `docs/architecture` | Block recovery contract | Architecture-local contract-like document. |
| [Atlas Provider Conformance Profile v1](../architecture/atlas-provider-conformance-profile-v1.md) | `docs/architecture` | Provider conformance profile | Conformance-oriented architecture-local document. |

## Current processing-contract guidance

For work that changes storage/Modal/backend execution boundaries, reviewers should verify the PR against:

- [Processing Attempt and Artifact Manifest v1](processing-attempt-and-artifact-manifest-v1.md);
- [Scalable Storage and Processing Architecture](../architecture/scalable-storage-and-processing-architecture.md);
- [Content-Addressed Artifacts and Duplicate Document Reuse](../storage/content-addressed-artifacts-and-document-reuse.md);
- [Scalable Processing Migration Plan](../plans/scalable-processing-migration-plan.md).

A runtime must not claim v1 conformance until the contract's required tests for deterministic fingerprinting, idempotent replay, single-flight, checksum validation, restart reconciliation, partial retry, duplicate finalization, and ownership-safe reuse exist and pass.

## Contract discovery boundary

This index does not:

- accept an unrelated contract;
- claim deployed runtime conformance;
- resolve conflicts outside explicit authority domains;
- change compatibility behavior by itself;
- authorize Production rollout or data migration.
