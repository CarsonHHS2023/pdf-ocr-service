# Atlas Product Strategy

| Field | Value |
|---|---|
| Document Type | Product Strategy |
| Approval Status | Accepted |
| Authority Domain | Atlas product direction and product-domain boundaries |
| Applies To | Atlas product identity, mission, product description, platform-to-application organization, accepted applications, product principles, and future application possibilities |
| Implementation Status | Product direction only; this document does not authorize implementation, roadmap changes, milestone changes, release commitments, delivery commitments, or commercial commitments |

## Status

Accepted product direction.

This document records the accepted long-term product direction for Atlas. It explains the product layer: how Atlas is organized as one Document Intelligence Platform, how applications sit on that platform, and how future applications can be introduced without fragmenting the shared foundation.

Future application examples in this document remain non-committed possibilities unless they appear in the approved roadmap. They do not create implementation scope, release commitments, database scope, API scope, Alembic scope, CI scope, or application repository scope.

## Mission

Transform real-world information into structured, verifiable, reusable knowledge.

## Engineering Motto

Think long-term. Build incrementally. Verify continuously.

## Product Description

Atlas is a Document Intelligence Platform that transforms real-world information into structured, verifiable, reusable knowledge. It helps you read faster, learn deeper, remember more effectively, and build an intelligent personal knowledge base that understands your documents, reasons across them, and traces every answer back to the original evidence.

The phrase "intelligent personal knowledge base" describes the current personal-use perspective. Smart Archive is not permanently limited to personal use: it may support individuals, teams, departments, companies, factories, hospitals, universities, and other organizations without changing the shared platform architecture.

## Atlas Is a Platform

Atlas is a long-lived platform rather than a single application.

Atlas is not only an OCR service. OCR is one possible processing capability within the broader platform direction.

Atlas is not only a Reader. Smart Reading OS is an application built on the platform, not the whole platform.

Atlas is not only an archive. Smart Archive is an application built on the platform, not a separate platform.

Atlas is one Document Intelligence Platform supporting multiple applications.

Conceptually:

- **Platform** means the shared product and architecture foundation that supports multiple applications.
- **Document Intelligence Core** means the shared foundation that connects source evidence, processing, canonical knowledge, and evidence-backed reuse.
- **Application** means an Atlas product built on the shared platform for a particular user workflow or market need.
- **Product experience** means the user-facing workflow, interface, and capability set delivered by an application.

These terms are conceptual product definitions. They do not define implementation-specific classes, tables, services, migrations, or API resources.

## Product Architecture

The accepted product structure is:

```text
Atlas
    ↓
Document Intelligence Platform
    ↓
Document Intelligence Core
    ↓
Atlas Applications
```

The shared Document Intelligence Core may eventually include capabilities such as:

- document ingestion;
- OCR and multimodal processing;
- canonicalization;
- evidence linking;
- knowledge extraction;
- reasoning support;
- retrieval.

These capabilities are architectural directions, not authorization to implement all of them now.

Applications may evolve independently, but they share:

- the same Document Intelligence Core;
- the same canonical data model;
- the same evidence model;
- the same architecture principles;
- the same engineering principles.

## Atlas Applications

The current accepted Atlas applications are:

1. Smart Reading OS
2. Smart Archive

Future applications may be introduced without creating separate, incompatible platforms. A new application should reuse the shared Document Intelligence Core and canonical knowledge foundation instead of creating its own disconnected document model.

## Smart Reading OS

Smart Reading OS is the first Atlas application.

Purpose: help users:

- read faster;
- learn deeper;
- remember more effectively.

Possible product capabilities include, as product direction unless already implemented:

- structured reading;
- focus mode;
- summaries;
- notes;
- quizzes;
- flashcards;
- mind maps;
- reading analytics;
- spaced review;
- comprehension testing.

Flashcards, mind maps, quizzes, summaries, notes, and review workflows are learning strategies that help users remember more effectively. This document does not claim that these capabilities are already implemented unless their implementation is verified elsewhere.

## Smart Archive

Smart Archive is the second Atlas application.

Purpose: transform unstructured information into an intelligent, evidence-backed knowledge resource.

Smart Archive is not merely a traditional archive or document management system. Traditional systems commonly focus on:

- storage;
- folders;
- metadata entry;
- organization;
- keyword search.

Atlas Smart Archive aims to add:

- document understanding;
- fact and number extraction;
- cross-document reasoning;
- question answering;
- traceability to original evidence;
- reusable organizational knowledge.

Personal-use examples include:

- receipts;
- medical records;
- contracts;
- notes;
- photos;
- audio;
- video;
- web content.

Enterprise-use examples include:

- contracts;
- invoices;
- receipts;
- production records;
- manufacturing process documents;
- quality manuals;
- inspection reports;
- test records;
- product manuals;
- specifications;
- engineering documentation;
- training media;
- websites;
- audiovisual records.

Companies often have mature structured operational databases for areas such as finance, inventory, production, sales, or ERP data, while large amounts of unstructured information remain fragmented and underused.

Smart Archive is intended to help convert that unstructured information into knowledge that can be understood, reasoned over, and traced back to evidence.

Smart Archive may support individuals, teams, departments, companies, factories, hospitals, universities, and other organizations. This document does not commit to a specific enterprise product release, implementation timeline, deployment architecture, permissions model, compliance model, or pricing model.

## One Core, Multiple Applications

Applications may evolve independently, but they always share the same Document Intelligence Core and the same canonical data model.

The same Document may support more than one application.

Examples:

- A book may support reading, learning, flashcards, and notes.
- A contract may support archive retrieval, fact extraction, and evidence-backed answers.
- A test report may support engineering search, quality analysis, and compliance.
- A video may support transcription, learning, archive retrieval, and timeline analysis.

This product structure allows application experiences to diverge without duplicating document identity, source evidence, canonical knowledge, or platform principles.

## Shared Conceptual Data Flow

The accepted canonical flow is documented in [Canonical Data Flow](../architecture/canonical-data-flow.md). Product Strategy references that flow rather than redefining it:

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

Smart Reading OS and Smart Archive consume different views of the same shared knowledge foundation. Smart Reading OS may emphasize reading, learning, notes, review, and comprehension. Smart Archive may emphasize retrieval, reasoning, evidence-backed answers, and reusable knowledge management.

This section does not create database or API designs.

## Product Principles

The accepted product principles are:

1. The same information object may support both learning and knowledge management.

2. Knowledge must remain connected to original evidence.

3. AI may assist understanding and reasoning, but evidence remains authoritative.

4. Learning should improve understanding and effective memory, not memorization alone.

5. Product applications may evolve independently without fragmenting the shared platform.

6. Shared platform capabilities should be reusable across applications.

7. Architecture guides the platform. Current product requirements justify implementation. Compatibility governs evolution.

8. Do not build every possible future application today.

9. Do not make current implementation shortcuts that prevent future applications.

10. Think long-term. Build incrementally. Verify continuously.

## Product Evolution

```text
                    Atlas
        Document Intelligence Platform
                    │
        Document Intelligence Core
                    │
  ┌─────────────────┼─────────────────┐
  │                 │                 │
Smart Reading OS  Smart Archive  Future Applications
  │                 │                 │
  └─────────────────┼─────────────────┘
                    │
   Shared Canonical Data and Engineering Principles
```

Smart Reading OS and Smart Archive are applications. They are not separate platforms. Future applications should reuse the same core, and the core must not become application-specific.

## Future Application Possibilities

Ideas, not committed roadmap items.

Possible future application ideas include:

- Research Assistant
- Engineering Knowledge Assistant
- Compliance Assistant
- Medical Knowledge Assistant
- Enterprise Knowledge Workspace
- Quality Knowledge Assistant
- Training and Learning Workspace

These are not added to the official roadmap by this document. They are not approved products, and they do not create implementation scope.

## Relationship to Existing Documentation

This Product Strategy links to and complements existing Atlas documentation:

- [Atlas Philosophy](../architecture/atlas-philosophy.md) defines why and how Atlas thinks.
- [Canonical Data Flow](../architecture/canonical-data-flow.md) defines the information lifecycle from source evidence to application-consumable knowledge.
- [Document Intelligence Platform Architecture](../architecture/document-intelligence-platform.md) defines service and platform structure.
- [ADR-001 Service Boundaries](../architecture/adr/ADR-001-service-boundaries.md) records accepted service-boundary responsibilities for this repository.
- [Foundation Schema Design](../database/foundation-schema-design.md) defines the foundation schema direction separately from product strategy.
- [Roadmap](../roadmap/roadmap.md) defines committed implementation sequence.
- [Engineering Principles](../engineering/engineering-principles.md) defines engineering expectations for how Atlas is built.

Product Strategy defines platform-to-application product organization. It does not replace the Philosophy, Canonical Data Flow, Architecture, Roadmap, ADR, Foundation Schema Design, or Engineering Principles documents.

## Non-goals

This document does not:

- implement Smart Archive;
- implement enterprise features;
- redesign the database;
- redesign APIs;
- add application repositories;
- add product-specific services;
- alter the roadmap;
- authorize future data tables;
- create ProcessingRun, Observation, Fact, or Canonical Node schemas;
- commit future applications to release dates;
- change repository responsibilities;
- change the accepted mission, motto, or product description.
