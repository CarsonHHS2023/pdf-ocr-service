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

Atlas also maintains a horizontal storage/processing scalability track, separate from product milestone numbering:

- [Scalable Storage and Processing Architecture](../architecture/scalable-storage-and-processing-architecture.md)
- [Scalable Processing Migration Plan](../plans/scalable-processing-migration-plan.md)
- [S0 Observability Closure Plan — 2026-08-25](../plans/s0-observability-closure-plan-2026-08-25.md)
- [S0 Phase 2 Baseline Reconciliation — 2026-08-25](../reviews/s0-phase2-baseline-reconciliation-2026-08-25.md)
- [S0.3.4 Compute Acceptance — 2026-09-02](../reviews/s0-3-4-compute-acceptance-2026-09-02.md)
- [S0.3.6 Failure/Retry Small Acceptance — 2026-09-02](../reviews/s0-3-6-failure-retry-small-acceptance-2026-09-02.md)
- [S0.3.6 Failure/Retry Medium Acceptance — 2026-09-02](../reviews/s0-3-6-failure-retry-medium-acceptance-2026-09-02.md)
- [S0 Worker-CPU Small Acceptance — 2026-09-04](../reviews/s0-preprocessing-worker-cpu-small-acceptance-2026-09-04.md)

The implementation phases are S0–S9. This work may support M5, M6, M7, and the external-pilot/commercial gate. It does **not** redefine M6 Smart Reading Intelligence as an infrastructure milestone.

### Current scalability status — 2026-09-04

- **Current scalability phase:** S0 — Baseline and observability.
- **S0 status:** **In Progress**.
- The original Phase 2 small/medium baseline remains historical evidence on revision `6fe56d35bfb39cf1e1016beb2694464fb1fc2e4f`; S0.3.3 transport/download acceptance subsequently passed on `37a3c41fc6f968ef442a723aaccdec2f90af3ce3`.
- New `pdf-small-v1` and `pdf-medium-v1` S0.3.4 acceptance passed on exact Backend/runtime revision `c5817070b85e6778db3dbdf558cd8fd756ffb904`, paired with isolated Provider deployment `edcdfc6bdfd691facf152ac577e41e520fdec4c9`. OCR duration, raw shard bytes and GPU sampling proxy are observed, including two sequential medium shards. See the report for collector provenance and coverage limits.
- Scoped S0.3.5 Reader first-open/reopen and nonzero-window reopen acceptance subsequently passed; the [closure plan](../plans/s0-observability-closure-plan-2026-08-25.md#s035-reader-open-and-bounded-query-measurements) retains its separate Backend/frontend revisions and coverage limits.
- S0.3.6 **small single-scope and medium sequential two-scope success-path PASS** on `7435aa3fa7ba0766d8cc2584bcacfd735c5ce74c`: 14 and 24 successful Provider method calls respectively, explicit zero failures/retries and complete durable closure. Real nonzero retries and concurrent runtime execution are not claimed.
- The worker-thread-only preprocessing CPU auxiliary passed a fresh one-page Staging acceptance on `ee2f48d83972bfd978060b40b3729b4b6b8405d4`; the required complete-stage CPU metric remains `not_instrumented`.
- **Four** required metrics remain `not_instrumented` in both fresh collectors: upload peak memory, stage-owned preprocessing CPU, visual asset generation duration and upload-to-Reader-ready latency. Historical seven/five-gap checkpoints remain historical, not current status.
- Next: define the S0.3.1 upload-owned memory boundary and remaining instrumentation in [the current action order](../plans/s0-observability-closure-plan-2026-08-25.md#61-next-decisions-and-remaining-instrumentation). No further PDF run is requested for the accepted S0.3.6 success-path target; this index starts no implementation.
- TXT representative timing and the large PDF baseline remain open.
- The 528-page fixture is deferred until the missing instrumentation can produce materially useful closure evidence and execution is explicitly approved.
- **S1/S2 are not started by the current S0 closure plan.**

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
- The maintained S0 closure plan and its dated acceptance reports are the current execution/evidence overlay for S0; they do not authorize S1/S2 or change product milestone status.
- Product milestone status does not itself authorize Production changes, Reader cutover, destructive migration/backfill, external pilot, or commercial release.
