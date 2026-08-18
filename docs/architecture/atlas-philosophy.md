# Atlas Philosophy

| Field | Value |
|---|---|
| Document Type | Architecture Principles |
| Approval Status | Accepted |
| Authority Domain | Atlas architecture principles and system-level design boundaries |
| Implementation Status | Architecture principles only; no full-platform implementation authorization |

## Status and intent

This document records accepted Atlas architecture principles. It is an architecture document, not an implementation design, schema specification, or migration plan.

Atlas has evolved beyond a PDF OCR service. The long-term conceptual model is a Document Intelligence Platform that transforms real-world information into structured, verifiable, reusable knowledge.

The concepts below should guide future implementation decisions, but they do not authorize implementing the full future platform at once.

## Mission

Atlas transforms real-world information into structured, verifiable, reusable knowledge.

## Design principles

1. Atlas is a Document Intelligence Platform, not only an OCR system.
2. `Document` is the durable business aggregate root.
3. `Document` does not mean PDF; it represents a real-world information object.
4. `Document` replaces `Bookshelf` as the long-term business object.
5. `SourceFile` represents immutable original evidence associated with a `Document`.
6. AI processing outputs observations, not business identity.
7. Applications consume canonical knowledge rather than raw OCR output.
8. Architecture guides the schema. Current requirements justify the schema. Compatibility governs schema evolution.
9. The temporary physical schema is not a long-term contract; Reader API compatibility is a long-term contract.
10. Atlas should evolve through small, validated iterations rather than implementing the entire future platform at once.

## Information lifecycle

The accepted conceptual lifecycle is:

```text
Document
  ↓
SourceFile
  ↓
ProcessingRun
  ↓
Observation
  ↓
Canonical Knowledge
  ↓
Applications
```

This lifecycle is architectural direction only. It does not create database tables, API contracts, or implementation obligations for every concept in the diagram.

## Document

`Document` is the business aggregate root. It represents a durable real-world information object, such as:

- Book
- Receipt
- Invoice
- Contract
- Medical record
- Research paper
- Note
- Picture
- Audio
- Video
- Email
- Web page

Future document types may be added.

`Document` stores business identity, type, status, metadata, ownership, and lifecycle. It must not become a container for OCR results or model-specific processing output. AI processing belongs in separate processing and observation concepts.

## SourceFile

`SourceFile` represents original evidence. A `Document` may have one or many source files.

A `SourceFile` is immutable. It records an original input or evidence artifact, such as:

- PDF
- TXT
- Markdown
- JPEG
- PNG
- DOCX
- EPUB
- Audio
- Video
- HTML
- Email
- ZIP

Source files preserve provenance and support future reprocessing, verification, and evidence-backed knowledge.

## ProcessingRun

`ProcessingRun` is a future conceptual record of AI or processing activity over source evidence. It may eventually describe which model, tool, parameters, inputs, outputs, and timestamps were involved in a processing step.

`ProcessingRun` is deferred architectural direction. It is not approved here as a database table, API resource, or implementation requirement.

## Observation

`Observation` is the conceptual output of AI or processing activity before promotion into canonical knowledge.

Examples include:

- OCR text
- Heading
- Paragraph
- Caption
- Formula
- Entity
- Summary
- Keyword
- Speaker
- Scene
- Language

Observations are not implementation yet. Future tasks must decide persistence, schema, confidence handling, provenance links, and compatibility behavior before observations become durable implementation objects.

## Canonical Knowledge

Canonical Knowledge is the normalized, reusable representation that applications should consume. It is derived from source evidence and observations, with enough provenance to remain verifiable.

Canonical Knowledge is architectural direction. Future implementation work must define its exact boundaries incrementally and avoid committing to unvalidated structures prematurely.

## Applications

Applications should consume Canonical Knowledge rather than raw OCR output. Current and future application examples include:

- Reader
- Learning
- Archive
- Search
- Analytics

Application records should reference durable document knowledge and evidence instead of copying source data into separate product-specific document systems.

## Metadata model

Atlas distinguishes four related but separate concepts.

### Document Type: "What is it?"

Examples:

- `book`
- `receipt`
- `invoice`
- `contract`
- `note`
- `picture`
- `audio`
- `video`
- `email`
- `webpage`
- `other`

Document Type identifies the real-world kind of information object.

### Category: "What is it about?"

Examples:

- Medical
- Finance
- History
- Education
- Family

Category describes topical meaning from a user or product perspective.

### Collection: "How does the user organize it?"

Examples:

- Spanish Learning
- 2026 Taxes
- Research

Collection is user organization and may change without changing what the document is.

### Domain: "How should AI understand it?"

Examples:

- Medical
- Finance
- Education
- Legal

Domain guides AI interpretation, extraction expectations, terminology, validation, and risk posture. Domain is not the same as Document Type, Category, or Collection.

## Implementation principles

- Architecture guides the schema.
- Current requirements justify the schema.
- Compatibility governs schema evolution.
- Current temporary schema is not a long-term contract.
- Reader API compatibility is a long-term contract.
- Future implementation should evolve incrementally.
- Do not implement the entire future platform at once.
- Use small, validated iterations as the project strategy.

## Deferred concepts

The following concepts are architectural direction, not approved implementation scope in this document:

- ProcessingRun persistence
- Observation persistence
- Canonical Knowledge schemas
- Canonical nodes
- Facts
- Learning objects
- Archive intelligence records
- Knowledge graphs
- Cross-document semantic models

Each concept requires a concrete task, compatibility plan, and validation strategy before implementation.

## Design vs implementation

This document defines accepted design philosophy. It does not change production code, database models, Alembic migrations, APIs, or compatibility contracts.

Implementation documents may use this philosophy to justify scoped future changes, but they must still explain the current requirement, migration behavior, compatibility surface, and validation plan.

## Non-goals

This document does not:

- redesign the current application;
- create database tables;
- add Alembic;
- change APIs;
- change production code;
- define a complete future schema;
- make `ProcessingRun`, `Observation`, Canonical Knowledge, Facts, or Learning objects implemented designs;
- remove Reader compatibility requirements;
- require all document types to be implemented immediately.
