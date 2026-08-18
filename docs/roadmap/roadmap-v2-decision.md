# Roadmap v2 Decision

| Field | Value |
|---|---|
| Document Type | Roadmap Decision |
| Approval Status | Accepted |
| Decision Date | 2026-07-14 |
| Authority Domain | Accepted Roadmap v2 realignment decision |
| Implementation Status | Decision record only; not implementation, release, delivery, or commercial authorization |

- **Decision date**: 2026-07-14
- **Status**: Accepted

## Problem

The historical roadmap placed Structured Reader work before the processing and
structured-content foundations it depends on. That order risked turning Stream
Text into implicit canonical data and blurred the boundary between current
transitional processing and the target `paddle-vl-api` architecture.

## Decision

Adopt Atlas Roadmap v2:

1. M1 — Foundation
2. M2 — Document Processing Foundation
3. M3 — Document Core & Structured Content Foundation
4. M4 — Smart Reading OS
5. M5 — Smart Archive

Smart Reading OS and Smart Archive are peer applications sharing one Document
Intelligence Core.

## Old-to-new mapping

| Historical milestone/scope | Roadmap v2 placement |
|---|---|
| Old M2 Structured Reader | M4 Smart Reading OS |
| Old M3 Document Core | Split: `Document`/`SourceFile` foundation remains in M1; structured/canonical content moves to M3 |
| Old M4 OCR Integration | M2 Document Processing Foundation |
| Old M5 Archive Intelligence | M5 Smart Archive |
| Original M1-004 PDF Retention | Absorbed by completed M1 Storage work |

## Rationale

Processing must produce normalized structured output before Atlas can define a
durable structured-content model. Smart Reading presentation should consume that
shared model rather than define canonical data through Stream Text. Smart Archive
should also consume the same shared core instead of diverging into a separate
application data model.

## Consequences

- M1 remains In Progress until the Storage Persistence Architecture and M1-to-M2
  Processing Handoff design task is completed.
- M2 owns actual `paddle-vl-api` integration and old local PaddleOCR-VL path
  isolation/removal.
- M3 owns durable Structured Content design informed by real M2 output.
- M4 owns Smart Reading OS features: Speed Reading, Flashcards, Mind Map, and
  Notes.
- M5 owns Smart Archive over the shared core.
- Stream Text is presentation/compatibility for Speed Reading, not canonical
  data.

## Historical preservation

Roadmap v2 is a realignment from the prior roadmap. Documentation should preserve
that history and use explicit absorbed/realigned status for old labels rather
than pretending Roadmap v2 always existed.

## Next step

Complete the M1 closeout task: **Storage Persistence Architecture and M1-to-M2
Processing Handoff**.
