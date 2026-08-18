# Milestones

| Field | Value |
|---|---|
| Document Type | Reference / Index |
| Authority Domain | Milestone navigation, current milestone-status discovery, and detailed milestone-record navigation |
| Applies To | Atlas Roadmap v3 milestone documents M1 through M7 |
| Related Roadmap | [../roadmap/roadmap.md](../roadmap/roadmap.md) |
| Related Roadmap v3 Decision | [../roadmap/roadmap-v3-decision.md](../roadmap/roadmap-v3-decision.md) |
| Related Roadmap v3 Review | [../roadmap/roadmap-v3-review.md](../roadmap/roadmap-v3-review.md) |
| Related Governance | [../project/document-governance.md](../project/document-governance.md) |

This index provides milestone navigation, current milestone status, and links between roadmap authority and detailed milestone records. It does not itself authorize Production deployment, destructive migration, external pilot, or release claims.

## Current Milestone

- **Most recently completed milestone:** M4.
- **Current product milestone:** M5 — Reader MVP.
- **M4 status:** Complete.
- **M5 status:** **In Progress**.
- **Latest M5 reconciliation:** [M5 Progress Reconciliation — 2026-08-15](../reviews/m5-progress-reconciliation-2026-08-15.md).
- **Implementation status:** The previous index statement that M5 Slice 1 was Not Started is obsolete. Original backend Slices 1–4 were implemented and later Reader v2/backend/frontend work substantially advanced Slices 5–6. Slices 7–10 require explicit verification or remain partial, and Slice 11 completion evidence is not complete.
- **Completion status:** M5 is **not Complete** until the 22 exit criteria are explicitly mapped to current cross-repository evidence.

## Horizontal Scalability Track

Atlas now also maintains a horizontal storage/processing scalability track, separate from product milestone numbering:

- [Scalable Storage and Processing Architecture](../architecture/scalable-storage-and-processing-architecture.md)
- [Scalable Processing Migration Plan](../plans/scalable-processing-migration-plan.md)

The implementation phases are S0–S9. This work may support M5, M6, M7, and the external-pilot/commercial gate. It does **not** redefine M6 Smart Reading Intelligence as an infrastructure milestone.

Future PRs should identify both a product milestone relationship and a scalability phase when applicable.

## Current Milestone Index

| Milestone | Current title | Status | Detailed Record | Record State |
|---|---|---|---|---|
| [M1](M1.md) | Foundation | Complete | [M1.md](M1.md) | Reconciled historical record. |
| [M2](M2.md) | Document Processing Foundation | Complete | [M2.md](M2.md) | Complete for revised Raw Processing Result boundary. |
| [M3](M3.md) | Document Core & Structured Content Foundation | Complete for revised scope | [M3.md](M3.md) | Complete for SPR/normalization/recovery/diagnostics/evidence foundation. |
| [M4](M4.md) | Structured Content / Structured Document Foundation | Complete | [M4.md](M4.md) | Completed Roadmap v3 M4 record and M4->M5 handoff. |
| [M5](M5.md) | Reader MVP | **In Progress** | [M5.md](M5.md) | Substantial implementation exists; latest progress reconciliation is 2026-08-15; completion evidence remains open. |
| [M6](M6.md) | Smart Reading Intelligence | Planned | [M6.md](M6.md) | Planned product milestone; not the owner of the horizontal scalability track. |
| [M7](M7.md) | Smart Archive | Planned | [M7.md](M7.md) | Planned detailed milestone plan. |

## M5 Current Guidance

The accepted [M5 Reader MVP Implementation Plan](../plans/m5-reader-mvp-implementation-plan.md) remains the historical slice model and scope authority. The [2026-08-15 progress reconciliation](../reviews/m5-progress-reconciliation-2026-08-15.md) is the current status overlay and must be consulted before starting new M5 work.

Current practical guidance:

1. do not restart work from Slice 1;
2. treat Slices 1–6 as materially implemented/evolved and verify their current evidence rather than reimplementing them;
3. explicitly verify lexical find (Slice 7);
4. reconcile reopen/delete/shared-source lifecycle semantics (Slice 8);
5. record current legacy/parity/cutover posture (Slice 9);
6. assemble integrated scale/accessibility/failure evidence (Slice 10);
7. complete Slice 11-style mapping to all 22 exit criteria before changing M5 to Complete.

## Historical Naming and Scope Treatment

M1, M2, and M3 preserve their official historical titles and statuses. Former M4 Smart Reading OS scope was decomposed into M4–M6, and former M5 Smart Archive moved to M7. Prior descriptions remain historical evidence and are not treated as failed milestones.

## Authority Notes

- Detailed milestone files govern detailed product milestone scope and exit criteria.
- The roadmap governs current sequencing and high-level scope boundaries.
- The 2026-08-15 M5 reconciliation is a point-in-time progress review; it does not erase historical plan/PR evidence.
- The S0–S9 scalability plan is horizontal implementation guidance and does not independently change M5/M6/M7 status.
- Product milestone status does not itself authorize Production changes, Reader cutover, destructive migration/backfill, external pilot, or commercial release.
