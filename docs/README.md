# Atlas Documentation

## Purpose

This directory contains Atlas architecture, contracts, ADRs, milestone records, implementation designs, reviews, release evidence, product documents, governance documents, and related references.

## Documentation Governance

The documentation governance policy is maintained at [project/document-governance.md](project/document-governance.md).

Atlas documentation authority is domain-specific. Document type, Approval Status, Lifecycle Status, Release Status, authority domain, and explicit scope determine how a document may be relied upon; directory placement is informative but not sufficient. Proposed documents do not override Accepted normative documents or rewrite Released historical baselines. Historical records preserve point-in-time evidence.

## Current implementation guidance — 2026-08-15

Before starting new Reader/platform work, use this chain rather than relying on old milestone status text or conversation history:

1. **Product milestone:** [M5 — Reader MVP](milestones/M5.md)
2. **Current progress evidence:** [M5 Progress Reconciliation — 2026-08-15](reviews/m5-progress-reconciliation-2026-08-15.md)
3. **Current Roadmap:** [Atlas Roadmap](roadmap/roadmap.md)
4. **Scalable platform target:** [Scalable Storage and Processing Architecture](architecture/scalable-storage-and-processing-architecture.md)
5. **Storage/dedup design:** [Content-Addressed Artifacts and Duplicate Document Reuse](storage/content-addressed-artifacts-and-document-reuse.md)
6. **Execution contract:** [Processing Attempt and Artifact Manifest Contract v1](contracts/processing-attempt-and-artifact-manifest-v1.md)
7. **Implementation sequence:** [Scalable Processing Migration Plan](plans/scalable-processing-migration-plan.md)

The old statement that M5 Slice 1 is Not Started is obsolete. M5 remains **In Progress** because completion evidence across all 22 criteria is still open. The S0–S9 scalability track is horizontal platform work supporting M5/M6/M7 and the external-pilot gate; it does not redefine M6 product scope.

For implementation PRs affected by the scalability track, record both:

```text
Product milestone: M5 / M6 / M7 / horizontal-only
Scalability phase: S0..S9 / N/A
```

## Documentation areas

| Directory | Primary Role |
|---|---|
| `adr` | Preferred central discovery location for ADRs; ADRs record accepted decisions within explicit scope. |
| `architecture` | Conceptual boundaries, semantic ownership, layers, responsibilities, and target platform models. |
| `contracts` | Verifiable behavior, schemas, protocols, compatibility, and conformance. |
| `database` | Database schema, migration, and persistence design. |
| `engineering` | Engineering workflow, repository practice, and development guidance. |
| `handoffs` | Cross-stage or cross-repository handoff records. |
| `milestones` | Milestone scope, task relationships, acceptance evidence, and declared delivery state. |
| `planning` | Advisory planning material. |
| `plans` | Concrete implementation plans and phased execution guidance. |
| `processing` | Internal processing designs, procedures, fixtures, results, and evidence according to document type. |
| `product` | Product intent and user-facing capability framing. |
| `project` | Governance, glossary, and reference material. |
| `releases` | Historical evidence of what was released. |
| `reviews` | Reviews, audits, findings, progress reconciliations, and point-in-time evidence. |
| `roadmap` | Product sequencing and dependency direction. |
| `storage` | Storage mechanics, physical/content ownership distinctions, dedup/reuse, and storage design. |
| `testing` | Test/CI strategy, transition plans, compatibility evidence, and reviews. |

## Authority and implementation boundary

Indexes provide discovery; they do not automatically accept child documents or claim runtime conformance.

In particular:

- the scalable target architecture does not by itself migrate Production;
- the processing-attempt v1 contract does not claim the current runtime already satisfies single-flight/reconciliation requirements;
- the M5 reconciliation does not declare M5 Complete;
- content-addressed reuse does not make a physical object ownerless or grant cross-user access;
- the scalability plan does not authorize destructive database/storage cleanup;
- external pilot/commercial readiness remains a separate gate.

## Navigation status

Centralized indexes exist for the major current domains, but some contract-like, ADR-like, and review documents remain in domain-local directories. Relocation is not implied. Future navigation work should index documents without changing their authority.
