# Atlas Storage Documentation

| Field | Value |
|---|---|
| Document Type | Reference / Index |
| Approval Status | Accepted |
| Lifecycle Status | Active |
| Date | 2026-08-15 |
| Authority Domain | Navigation and discovery only |
| Applies To | `docs/storage` design and review discovery |
| Related Governance | [Atlas Documentation Governance](../project/document-governance.md) |

## Purpose

Storage documents cover digital-object vocabulary, source-retention strategy, storage-adapter design, ownership distinctions, duplicate-document reuse, artifact lifecycle, and point-in-time storage evidence.

This README is a navigational index. Child-document metadata and body evidence control each document's role, status, version, implementation boundary, and authority domain.

## Current implementation-facing storage guidance

For the horizontal S0–S9 scalability track, use these documents together:

1. [Content-Addressed Artifacts and Duplicate Document Reuse](content-addressed-artifacts-and-document-reuse.md) — current target direction for exact SHA-256 source dedupe, physical-content versus user ownership, processing reuse/single-flight, L0–L3 reuse levels, retention classes, and reference-aware GC.
2. [Scalable Storage and Processing Architecture](../architecture/scalable-storage-and-processing-architecture.md) — platform ownership and data-flow boundary.
3. [Processing Attempt and Artifact Manifest v1](../contracts/processing-attempt-and-artifact-manifest-v1.md) — artifact/fingerprint/manifest semantics.
4. [Scalable Processing Migration Plan](../plans/scalable-processing-migration-plan.md) — implementation sequencing and rollout gates.

The new design does not require an immediate migration of every historical storage reference and does not authorize deleting shared/legacy objects.

## Taxonomies and conceptual models

| Document | Type | Status / Version | Role and Boundary |
|---|---|---|---|
| [Atlas Digital Object Taxonomy](digital-object-taxonomy.md) | Architecture Taxonomy | — | Conceptual classification and storage-role distinctions. |

## Storage strategies and designs

| Document | Type | Status / Version | Role and Boundary |
|---|---|---|---|
| [Content-Addressed Artifacts and Duplicate Document Reuse](content-addressed-artifacts-and-document-reuse.md) | Storage / Reuse Design | Accepted target direction, 2026-08-15 | Physical content addressing, cross-user exact-source/processing reuse, single-flight, higher-level reuse roadmap, retention classes, and reference-aware deletion. |
| [Source Retention Strategy](source-retention-strategy.md) | Storage Strategy | Approval Status: Proposed | Proposed source-retention strategy and decision framework. |
| [Storage Adapter Design](storage-adapter-design.md) | Storage Design | Version: v1 | Existing storage-adapter design direction and implementation notes. |

## Ownership and responsibility models

| Document | Type | Status / Version | Role and Boundary |
|---|---|---|---|
| [Storage Ownership Model](storage-ownership-model.md) | Ownership Model | — | Distinguishes storage, persistence, business, processing, and application responsibilities. |
| [Scalable Storage and Processing Architecture](../architecture/scalable-storage-and-processing-architecture.md) | Target Architecture | Accepted target direction | Defines Object Storage as durable binary/artifact plane; Neon as business-state plane; Modal as compute plane; Backend as control plane. |

## Reviews and point-in-time evidence

| Document | Type | Evidence Boundary | Role and Limitation |
|---|---|---|---|
| [Current Storage Review](current-storage-review.md) | Review / Evidence Record | Earlier M1 repository/code inspection | Historical point-in-time evidence; not a permanent target architecture. |

## Storage navigation boundary

This index does not by itself:

- adopt a final legal/commercial retention policy;
- authorize destructive cleanup or historical object migration;
- make an object-storage reference equal to user ownership;
- permit cross-user access because a hash/object exists;
- supersede accepted contracts/ADRs outside its domain;
- claim runtime conformance with the new dedupe/reuse design before implementation and tests exist.
