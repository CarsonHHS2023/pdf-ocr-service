# Atlas Implementation Plans

| Field | Value |
|---|---|
| Document Type | Reference / Index |
| Approval Status | Accepted |
| Lifecycle Status | Active |
| Date | 2026-08-15 |
| Authority Domain | Navigation and discovery only |
| Applies To | Implementation plan discovery |
| Related Governance | [Atlas Documentation Governance](../project/document-governance.md) |

## Purpose

This index provides navigation to implementation plans. It does not approve, reject, supersede, or reclassify an indexed plan beyond the plan's own declared metadata.

## Current active implementation guidance

| Document | Date | Scope | Current use |
|---|---|---|---|
| [M5 Reader MVP Implementation Plan](m5-reader-mvp-implementation-plan.md) | 2026-07-24 | Cross-repository Reader MVP product slices | Accepted historical/current M5 slice model. Progress status is reconciled separately; do not use the old assumption that M5 remains Planned or Slice 1 is Not Started. |
| [Scalable Processing Migration Plan](scalable-processing-migration-plan.md) | 2026-08-15 | Cross-repository storage/compute/reliability migration S0–S9 | Current implementation sequence for multi-user concurrency, object/artifact plane, durable attempts, direct Modal transport, CPU/GPU scaling, shards/retry, SPR boundary, and duplicate-document reuse. |

Before starting M5 work, read [M5 Progress Reconciliation — 2026-08-15](../reviews/m5-progress-reconciliation-2026-08-15.md). Before starting S0–S9 work, read the scalable target architecture and v1 attempt/artifact contract linked by the plan.

## Historical / completed-milestone plans

| Document | Date | Scope | Status Signal |
|---|---|---|---|
| [M4 Slice 2 Structured Content Persistence Plan](m4-slice-2-structured-content-persistence-plan.md) | 2026-07-23 | Structured Content persistence planning | Historical M4 plan |
| [M4 Slice 3 SPR to Structured Content Transformation Plan](m4-slice-3-spr-to-structured-content-transformation-plan.md) | 2026-07-23 | SPR-to-Structured Content transformation planning | Historical M4 plan |
| [M4 Slice 4 Structured Document Projection Plan](m4-slice-4-structured-document-projection-plan.md) | 2026-07-24 | Structured Document and projection planning | Historical M4 plan |

## Dual-tracking rule

New implementation PRs should identify both dimensions where applicable:

```text
Product milestone: M5 / M6 / M7 / horizontal-only
Scalability phase: S0..S9 / N/A
```

This keeps product sequencing and platform migration aligned without pretending that the scalability program is an M6 product feature.
