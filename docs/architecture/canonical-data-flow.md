# Canonical Data Flow

| Field | Value |
|---|---|
| Document Type | Conceptual Data Flow |
| Approval Status | Accepted |
| Authority Domain | Atlas conceptual document-information flow |
| Implementation Status | Architecture model only; no runtime sequencing or implementation authorization |

## Status and intent

This document records the accepted conceptual data flow for Atlas as a Document Intelligence Platform. It is architecture only and does not define database tables, migrations, API payloads, service classes, physical persistence, or implementation sequencing.

### Roadmap v3 alignment note

The accepted conceptual model remains valid at an abstract level. Roadmap v3 introduces explicit retained-processing, normalized-processing, accepted-content, and projection stages between source evidence and applications. This revision clarifies how the accepted conceptual stages map to that Roadmap v3 decomposition without approving physical schemas, tables, APIs, providers, UI, deployment, implementation, release, or production readiness.

## Current conceptual flow

```text
Source Evidence / SourceFile
  ↓
Storage
  ↓
Processing Provider
  ↓
Raw Processing Result
  ↓
Structured Processing Result (SPR)
  ↓
Structured Content / Structured Document
  ↓
derived projections
  ↓
Reader / Smart Reading Intelligence / Smart Archive
```

This current-facing flow maps the original conceptual relationship into the Roadmap v3 delivery stages:

- Source Evidence / `SourceFile` identifies retained source material and source provenance. It is evidence source material, not generated application content.
- Storage owns source-byte retention and retrieval mechanics without owning processing interpretation or application content.
- Processing Provider performs provider execution and returns provider-native output.
- Raw Processing Result is retained provider-specific processing evidence, may contain provider-native payloads, is noncanonical, and belongs to the M2 boundary.
- Structured Processing Result (SPR) is provider-independent normalized processing output. It contains recovery, diagnostics, topology, and evidence links; it is noncanonical and belongs to the completed revised M3 boundary.
- Structured Content / Structured Document is the application-independent accepted/current document-content boundary. Its exact lifecycle remains an M4 decision and may use SCV, accepted snapshot, selected candidate, or another approved model; this document does not choose one.
- Derived projections are Reader/API/application-compatible forms rebuilt from accepted/current content. They are noncanonical. Reader Content Stream is one possible compatibility/projection serialization, not canonical content.
- Reader MVP, Smart Reading Intelligence, and Smart Archive are peer/downstream consumers. They do not own canonical source content.

## Original conceptual relationship

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

This relationship is conceptual rather than the only concrete sequential data flow. Under Roadmap v3, `ProcessingRun` and `Observation` map across Raw Processing Result, SPR diagnostics/evidence, and later evidence structures depending on approved design. The current document-content realization of the broader Canonical Knowledge idea is Structured Content / Structured Document.

## Canonicality roles

| Artifact | Role | Canonical |
|---|---|---|
| SourceFile/source evidence | Retained source evidence | Evidence source, not generated content |
| Raw Processing Result | Provider-specific retained result | No |
| SPR | Provider-independent normalized result | No |
| Structured Content | Accepted/current content boundary | According to M4 selected lifecycle |
| Structured Document | Application-independent assembled view | According to M4 selected lifecycle |
| Reader projection | Derived delivery form | No |
| Reader Content Stream | Compatibility/projection serialization | No |
| Semantic/retrieval index | Derived/rebuildable index | No |
| Generated summaries/Q&A/etc. | Generated intelligence | No |
| Archive metadata | Application metadata | No replacement of document content |
## Document

`Document` is the aggregate root for durable business identity. It represents a real-world information object, not a file format.

A document may be a book, receipt, invoice, contract, medical record, research paper, note, picture, audio, video, email, web page, or another future document type.

`Document` should store identity, type, status, metadata, ownership, and lifecycle. It should not store raw OCR results or become a dumping ground for model output.

## SourceFile

`SourceFile` represents immutable original evidence. A document may have one source file or many source files.

Source files can include PDFs, text files, Markdown, images, DOCX, EPUB, audio, video, HTML, email, ZIP archives, and future source formats.

Source files support evidence, provenance, replayability, reprocessing, and verification.

## ProcessingRun

`ProcessingRun` is a conceptual identity for an execution attempt or processing lifecycle over source evidence. It may connect `SourceFile`, Raw Processing Result, SPR, diagnostics, retry/rebuild behavior, status, inputs, models, parameters, timing, and provenance.

This document does not approve a `ProcessingRun` table, schema, API, or durable persistence model. Durable persistence remains an M4 decision and future implementation must introduce it only when approved requirements justify it.

## Observation

`Observation` is a conceptual machine, model, or tool observation or evidence unit. Depending on the approved design, an Observation may map to Raw Processing Result evidence, SPR diagnostics/evidence, or later evidence structures.

Examples include OCR text, headings, paragraphs, captions, formulas, entities, summaries, keywords, speakers, scenes, and language detections.

Observations are not the same as Structured Content / Structured Document or Canonical Knowledge. Durable Observation rows are not automatically required; persistence remains deferred to M4 based on provenance, citation, query, lifecycle, and audit needs.

## Canonical Knowledge

Canonical Knowledge is retained only as a broad conceptual umbrella for normalized, reusable, evidence-backed representation. Its current document-content realization is Structured Content / Structured Document, whose accepted/current lifecycle remains an M4 decision.

SPR is not Canonical Knowledge. Projections are not Canonical Knowledge. Generated M6 intelligence is derived output, not canonical document content. Archive metadata does not replace canonical document content. This document does not create a new knowledge ontology.

## Applications

Applications consume Structured Content / Structured Document through derived projections instead of coupling directly to raw OCR, Raw Processing Results, provider JSON, SPR as canonical truth, or model-specific observations.

Examples include:

- Reader
- Learning
- Archive
- Search
- Analytics

This separation lets Atlas improve processing providers and observation quality without forcing each application to reinvent document understanding.

## Compatibility and evolution

Current Reader compatibility may continue exposing Bookshelf-shaped API responses during transition. Internally, the durable long-term business object is `Document`, not `Bookshelf`.

The temporary schema is not a long-term contract. Reader API compatibility is a long-term contract until deliberately versioned.

Schema evolution should follow this accepted principle:

```text
Architecture guides the schema.
Current requirements justify the schema.
Compatibility governs schema evolution.
```

## Implementation boundaries

This document intentionally defers implementation details for:

- database tables;
- Alembic migrations;
- API shapes;
- storage keys;
- canonical node schemas;
- observation schemas;
- processing orchestration internals;
- fact, learning, or archive intelligence models.

Future implementation must proceed through small, validated iterations. This conceptual architecture does not approve physical persistence, authorize implementation, mark M4 Complete, approve release, or declare production readiness.
