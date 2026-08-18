# ADR-001 Service Boundaries

| Field | Value |
|---|---|
| Document Type | ADR |
| Approval Status | Accepted |
| Date | 2026-07-11 |
| Authority Domain | Service-boundary ownership decision |
| Applies To | `paddle-vl-api`, `pdf-ocr-service`, and `speed-reading-trainer` responsibilities |

## Status

Accepted

## Date

2026-07-11

## Context

The document-processing system originally treated OCR, document management, reading, archive, and learning capabilities as loosely coupled parts of one workflow. That model was sufficient while the product scope was limited, but it does not define durable ownership boundaries for shared document data.

The project is evolving into two accepted peer applications:

- Smart Reading OS, including Speed Reading, Flashcards, Mind Map, and Notes
- Smart Archive

Both applications, and any future applications, require a shared Document Core. That core must provide stable ownership of source documents, page identity, canonical document structure, revisions, evidence, generated assets, archive facts, and learning objects. OCR compute is an input to that core, not the owner of the business domain.

## Problem

Allowing the OCR service to own durable business data creates unclear responsibility boundaries and makes the platform harder to evolve.

Specific problems include:

- Coupling OCR compute to document, archive, learning, and reading workflows.
- Making deployment of business features dependent on OCR runtime changes.
- Scaling business APIs and OCR workloads as if they had the same resource profile.
- Slowing independent evolution of OCR models, document storage, archive workflows, and learning features.
- Creating ambiguous data ownership for documents, revisions, facts, notes, and user progress.
- Making tests depend on OCR infrastructure when they should validate business behavior.
- Increasing operational complexity by mixing transient compute state with durable system-of-record data.

## Decision

`paddle-vl-api` is a durable-business-stateless OCR compute service.

`pdf-ocr-service` is the durable business system of record.

`speed-reading-trainer` is a user-facing reading application.

### `paddle-vl-api` responsibilities

`paddle-vl-api` owns OCR compute responsibilities:

- OCR execution.
- Async jobs.
- Temporary job state.
- Temporary artifacts.
- Page-level OCR observations.
- Result normalization.
- Compute optimization.
- No durable business ownership.

Durable-business-stateless means the service may manage state needed to execute OCR work, but it does not become the long-term owner of business entities or workflows. It produces observations and normalized OCR results for ingestion by the durable system of record.

This does not mean:

- Literally no transient state.
- No temporary cache.
- No async jobs.

This does mean no long-term ownership of:

- Documents.
- Books.
- Notes.
- Facts.
- Flashcards.
- Mind maps.
- User progress.
- Learning records.
- Archive metadata.
- Business workflows.

### `pdf-ocr-service` responsibilities

`pdf-ocr-service` owns durable business responsibilities:

- Document ownership.
- Source files.
- Page records.
- OCR ingestion.
- Processing runs.
- Canonical document revisions.
- Canonical nodes.
- Assets.
- Archive facts.
- Learning objects.
- User annotations.
- Version history.

### `speed-reading-trainer` responsibilities

`speed-reading-trainer` owns reading experience responsibilities:

- Reading UI.
- Reading sessions.
- Browser interaction.
- User presentation.
- Focus mode.
- Reading controls.

## Consequences

Positive consequences:

- Clear ownership for compute, durable document data, and reading presentation.
- Simpler deployment boundaries.
- Independent scaling for OCR workloads and business APIs.
- Reusable OCR service across multiple products.
- Reusable Document Core across reading, archive, and learning applications.
- Easier testing because business behavior can be tested without requiring OCR execution.
- Cleaner APIs between compute services, the system of record, and user-facing applications.

Tradeoffs:

- More API boundaries between services.
- A defined ingestion pipeline is required for OCR outputs.
- Some workflows become eventually consistent.
- Slightly more orchestration is required across compute, ingestion, and presentation layers.

## Alternatives considered

### Alternative A: OCR service owns everything

In this model, the OCR service would own document records, source files, page records, canonical content, archive metadata, learning data, notes, flashcards, and user progress.

This was rejected because it couples compute infrastructure to business workflows, forces unrelated features to share the OCR deployment lifecycle, complicates scaling, and makes data ownership unclear.

### Alternative B: Single monolith

In this model, OCR compute, document storage, reading features, archive workflows, and learning features would remain in one deployable application.

This was rejected because the product is evolving into multiple applications with different runtime profiles, release cadences, and user-facing responsibilities. A monolith would make OCR infrastructure, durable business data, and browser presentation harder to evolve independently.

### Alternative C: Current chosen architecture

In this model, `paddle-vl-api` remains durable-business-stateless, `pdf-ocr-service` owns the durable Document Core and related business records, and `speed-reading-trainer` owns the reading experience.

This alternative is accepted.

## Ownership table

| Capability | `paddle-vl-api` | `pdf-ocr-service` | `speed-reading-trainer` |
| --- | --- | --- | --- |
| OCR compute | Owns | Uses | Does not own |
| Temporary artifacts | Owns during job execution | May ingest selected outputs | Does not own |
| Original documents | Does not own | Owns | Does not own |
| Document revisions | Does not own | Owns | Does not own |
| Canonical nodes | Does not own | Owns | Uses |
| Processing runs | Reports job observations | Owns durable run records | Does not own |
| Archive facts | Does not own | Owns | Does not own |
| Learning content | Does not own | Owns | May present when needed |
| Reading sessions | Does not own | May record durable progress | Owns interaction flow |
| Browser UI state | Does not own | Does not own | Owns |
| Flashcards | Does not own | Owns | May present when needed |
| Mind maps | Does not own | Owns | May present when needed |
| Notes | Does not own | Owns | May capture or present through APIs |
| Summaries | Does not own | Owns | May present when needed |
| Images/pages | May produce temporary page observations | Owns durable page and asset records | Renders through APIs |
| Version history | Does not own | Owns | Does not own |

## Future implications

Future services may reuse `paddle-vl-api` without depending on `speed-reading-trainer`. OCR compute should remain available to any product that needs document observations while business ownership remains outside the OCR service.

Examples include:

- Enterprise document processing.
- Legal archive.
- Medical archive.
- Education platform.
- Search and indexing.

Future services should depend on explicit APIs and ingestion contracts instead of assuming that OCR compute owns documents, archive metadata, learning records, or reading workflows.

## Related documents

- [Document Intelligence Platform Architecture Proposal](../document-intelligence-platform.md)
- [Current-State Cross-Repository Review](../current-state-review.md)
- [Initial Modification Plan](../../planning/initial-modification-plan.md)
