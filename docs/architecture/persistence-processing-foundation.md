# Atlas Persistence & Processing Foundation

| Field | Value |
|---|---|
| Document Type | Architecture Foundation |
| Authority Domain | Persistence and processing foundation responsibilities from retained Source evidence to application experiences |
| Applies To | Source, Storage, Document Processing, Structured Content, Knowledge, Presentation, Applications, M2 Document Processing Foundation, M3 Document Core & Structured Content Foundation, M4 Smart Reading OS, and M5 Smart Archive |

## Status

Documentation-only architecture contract for **M1-005 Atlas Persistence & Processing Foundation**.

This document closes the M1 architecture foundation by defining how information flows from retained Source evidence to application experiences. It is conceptual only. It does not define database tables, API endpoints, database models, Alembic migrations, CI behavior, dependencies, storage-provider implementation, processing implementation, or runtime behavior changes.

## Purpose

Atlas needs one shared contract for persistence, processing, structured content, and presentation before M2 starts implementation. Existing M1 documents define the product strategy, the Document Intelligence Platform, Roadmap V2, `Document`, `SourceFile`, the storage adapter direction, source retention, and storage ownership. This document adds the missing lifecycle contract: what Atlas persists, where it persists it conceptually, who owns each object, how processing stages exchange data, what becomes canonical, and what remains presentation.

Related M1 references:

- [Atlas Digital Object Taxonomy](../storage/digital-object-taxonomy.md)
- [Storage Ownership Model](../storage/storage-ownership-model.md)
- [Source Retention Strategy](../storage/source-retention-strategy.md)
- [Storage Adapter Design](../storage/storage-adapter-design.md)
- [Document Intelligence Platform](document-intelligence-platform.md)
- [Canonical Data Flow](canonical-data-flow.md)

## Atlas Shared Platform Blueprint

This section defines the shared architectural blueprint followed by M2 Document Processing Foundation, M3 Document Core & Structured Content Foundation, M4 Smart Reading OS, and M5 Smart Archive. The blueprint is an accepted cross-milestone architecture direction. It does not mean all layers are implemented in M1.

```text
                           Atlas Document Intelligence Platform
┌──────────────────────────────────────────────────────────────────────────┐
│                              Original Sources                            │
│                 PDF / TXT / Image / Audio / Video / Web                 │
└──────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                         Storage — Original Evidence
                                      │
                                      ▼
                  M2 — Document Processing Foundation
                                      │
                         paddle-vl-api → MinerU-Popo
                                      │
                                      ▼
                     Structured Processing Output
                                      │
                                      ▼
       M3 — Document Core & Structured Content Foundation
                                      │
                    Provider-independent Structured Content
                    Evidence linkage / ordering / assets /
                    versioning / canonicalization boundaries
                                      │
                   ┌──────────────────┴──────────────────┐
                   ▼                                     ▼
          M4 — Smart Reading OS                  M5 — Smart Archive
                   │                                     │
       Speed Reading / Flashcards /             Search / Collections /
       Mind Map / Notes                         Evidence Navigation /
                                                Archive Intelligence
                   │                                     │
                   └──────── Application Presentation ───┘
```

### Original Sources

Original Sources are original or authoritative evidence received by Atlas.

Examples include:

- PDF;
- TXT;
- image;
- audio;
- video;
- webpage capture;
- email;
- archive/package.

Original Sources are not application presentation.

### Storage

Storage manages object bytes and provider mechanics.

Storage does not determine:

- document meaning;
- retention policy;
- canonical truth;
- application behavior.

### M2 — Document Processing Foundation

M2 transforms retained Sources into normalized structured processing output.

M2 owns:

- source retrieval through Storage;
- `paddle-vl-api` integration;
- processing jobs/status/progress/errors;
- raw processing-result ingestion;
- MinerU-Popo normalization;
- processing provenance and version information;
- retry and idempotency behavior;
- structured processing output contract.

M2 does not define final application presentation.

### M3 — Document Core & Structured Content Foundation

M3 establishes the durable, provider-independent and application-independent Structured Content model.

M3 owns future concepts such as:

- structured blocks/nodes;
- ordering;
- source/page evidence linkage;
- Asset relationships;
- ProcessingRun and Observation boundaries;
- versioning;
- canonicalization;
- database/Object Storage persistence alignment;
- provider-output isolation.

M3 does not own Smart Reading or Smart Archive user experiences.

### M4 — Smart Reading OS

M4 consumes Structured Content through application-specific representations.

Smart Reading OS includes:

- Speed Reading;
- Flashcards;
- Mind Map;
- Notes.

Clarifications:

- Stream Text belongs to Speed Reading presentation;
- Flashcards and Mind Maps are derived learning representations;
- Notes may contain user-created content and links to evidence;
- Smart Reading OS does not own canonical Structured Content.

### M5 — Smart Archive

M5 consumes the same Structured Content and evidence model for personal and organizational archives.

Smart Archive may include:

- collections;
- document organization;
- search;
- evidence-backed answers;
- cross-document retrieval;
- provenance navigation;
- archive intelligence;
- enterprise unstructured-information workflows.

Smart Archive does not duplicate the Document Intelligence Core.

### Cross-milestone rules

Accepted rules:

1. M2 produces normalized structured processing output.
2. M3 converts processing output into durable shared Structured Content.
3. M4 and M5 consume the shared Structured Content.
4. M4 and M5 must not depend directly on `paddle-vl-api`-specific output.
5. Provider-specific OCR/layout results must not become application contracts.
6. Stream Text is not a cross-platform canonical format.
7. Presentation formats may be regenerated from Structured Content.
8. Original evidence must remain traceable through the processing and content layers.
9. Storage location must not determine business meaning.
10. Each milestone may evolve incrementally, but must preserve these boundaries.

### Blueprint usage

This blueprint is the reference architecture for planning and reviewing work in M2, M3, M4, and M5.

Every future milestone design should explain:

- which blueprint layer it changes;
- which upstream contract it consumes;
- which downstream contract it produces;
- which data is authoritative;
- which data is derived;
- which compatibility boundary must remain stable.

The canonical copy of the blueprint remains in this document.

## 1. Atlas Information Lifecycle

Atlas information moves through a layered lifecycle. Each stage has a distinct responsibility and must not absorb responsibility from another stage.

```text
Source
  ↓
Storage
  ↓
Document Processing
  ↓
Normalization
  ↓
Structured Content
  ↓
Knowledge
  ↓
Applications
  ↓
Presentation
```

| Stage | Responsibility | Not responsible for |
|---|---|---|
| Source | Preserve the original evidence received or referenced by Atlas. | Processing interpretation, reader formatting, search ranking, or generated study material. |
| Storage | Persist, retrieve, protect, and delete bytes according to authorized commands and policy. | Business meaning, knowledge truth, application UX, or source-retention decisions. |
| Document Processing | Convert retained source bytes into provider-specific observations and intermediate outputs. | Canonical truth, application presentation, or long-term business identity. |
| Normalization | Translate provider-specific outputs into Atlas-owned, provider-independent structure. | UI formatting, provider execution, or storage mechanics. |
| Structured Content | Hold canonical, evidence-backed document content shared by applications. | Reader-specific stream text, Markdown export, raw OCR JSON, or provider payloads. |
| Knowledge | Add accepted semantic understanding, facts, relationships, retrieval structures, and future intelligence on top of structured content. | Original evidence storage or transient processing execution. |
| Applications | Deliver user workflows such as Smart Reading OS and Smart Archive by consuming Structured Content and Knowledge. | Ownership of source evidence, processing output, or shared structured content. |
| Presentation | Shape application consumption into user-facing views, exports, and caches. | Canonical source of truth. |

The lifecycle is directional for responsibility, not a rule that every deployment must persist every stage. Some stages may be transient, cached, deferred, or rebuilt, but their conceptual boundaries remain separate.

## 2. Persistence Architecture

Persistence decisions are based on information layer, ownership, durability, rebuildability, and evidence value. Storage location is mechanical; ownership describes meaning and lifecycle authority.

### Original Source

- **Purpose:** Preserve original uploaded or referenced evidence, such as a PDF, text file, image, audio file, or video file.
- **Owner:** Business ownership through `Document` and `SourceFile`; Storage owns bytes mechanically.
- **Persistence location:** Current implementation records `SourceFile` metadata and may transitionally delete upload bytes after local processing. Target architecture persists retained source bytes through the Storage boundary.
- **Lifetime:** Durable when retained; deleted only through explicit business policy.
- **Rebuildability:** Not rebuildable. It is the original evidence.
- **Evidence value:** Highest. It is the evidence anchor for reprocessing, audit, and future extraction.
- **Current implementation:** Transitional local OCR path does not yet treat source retention as the universal processing input.
- **Future direction:** Retained Source becomes the required input for the M2 processing pipeline.

### Storage Object

- **Purpose:** Represent stored bytes and the reference needed to retrieve them.
- **Owner:** Storage owns byte mechanics; Business owns why the object exists.
- **Persistence location:** Current local storage paths and database-backed compatibility locations where already present; target Storage provider through stable storage references.
- **Lifetime:** Follows the lifecycle of the business or processing object that references it.
- **Rebuildability:** Depends on the represented object. A Source storage object is not rebuildable; a cache object may be.
- **Evidence value:** Inherited from object purpose, not from storage location.
- **Current implementation:** Mixed local filesystem and database blob/text storage remain transitional.
- **Future direction:** Provider-independent Storage access with no business meaning encoded in provider paths.

### Raw `paddle-vl-api` output

- **Purpose:** Capture provider-specific document-processing observations from `paddle-vl-api`.
- **Owner:** Processing owns creation and interpretation; Storage may store the payload if retained.
- **Persistence location:** Target processing artifact or observation store. No current production path is introduced by this document.
- **Lifetime:** Retained only if needed for traceability, debugging, reproducibility, or cost control.
- **Rebuildability:** Regenerable when retained Source, provider configuration, and compatible model versions remain available; exact output may vary.
- **Evidence value:** Supporting evidence/observation, not canonical truth.
- **Current implementation:** Not the current local OCR path.
- **Future direction:** M2 processing input to normalization and MinerU-Popo.

### MinerU-Popo output

- **Purpose:** Convert raw processing observations into a structured intermediate that can feed Atlas normalization.
- **Owner:** Processing owns the intermediate; Atlas normalization owns what is accepted into Structured Content.
- **Persistence location:** Target processing artifact location if retained; current system has MinerU-related local/database outputs used for Reader compatibility.
- **Lifetime:** Durable only when needed for traceability or compatibility; otherwise rebuildable.
- **Rebuildability:** Regenerable from retained Source and raw processing inputs, subject to version drift.
- **Evidence value:** Processing evidence, not canonical content by itself.
- **Current implementation:** Existing MinerU-style output supports current Reader flows and must not be confused with the target `paddle-vl-api` path.
- **Future direction:** Becomes a processing-stage output that feeds Structured Content creation.

### Structured Content

- **Purpose:** Atlas-owned canonical document content independent of provider and application presentation.
- **Owner:** Business/Knowledge ownership; Processing proposes it through normalization, and applications consume it.
- **Persistence location:** Future durable Atlas persistence. This document does not define schema or tables.
- **Lifetime:** Durable and versionable once accepted.
- **Rebuildability:** Rebuildable in principle from retained Source and processing versions, but accepted versions may be preserved because exact regeneration can vary.
- **Evidence value:** High, because every unit should be traceable to Source evidence or retained observations.
- **Current implementation:** Not implemented as a distinct canonical object.
- **Future direction:** Primary shared content contract for M2 and later applications.

### Knowledge Objects

- **Purpose:** Represent semantic understanding such as facts, relationships, collections, evidence links, and future archive intelligence.
- **Owner:** Future Knowledge/business context.
- **Persistence location:** Future knowledge persistence, not defined here.
- **Lifetime:** Durable when accepted; draft/generated knowledge may have shorter retention.
- **Rebuildability:** Partially rebuildable. Human validation, model changes, and curation may make exact regeneration impossible.
- **Evidence value:** Derivative; valuable only when linked back to evidence.
- **Current implementation:** Deferred.
- **Future direction:** Built on Structured Content after M2 foundation exists.

### Presentation Objects

- **Purpose:** Serve specific application views such as stream text, reader pages, mind maps, flashcards, notes, and search results.
- **Owner:** Application layer.
- **Persistence location:** Application storage, cache, export storage, or not persisted, depending future product design.
- **Lifetime:** As long as useful for the application or user workflow.
- **Rebuildability:** Usually regenerable from Structured Content and Knowledge; user-authored edits may not be.
- **Evidence value:** Not evidence and never canonical.
- **Current implementation:** Current Reader outputs and processed text paths are compatibility presentation artifacts.
- **Future direction:** Regenerated from Structured Content where practical.

### Search Index

- **Purpose:** Accelerate keyword, semantic, or hybrid retrieval.
- **Owner:** Retrieval/Application for serving; Knowledge/Business governs source data eligibility.
- **Persistence location:** Future index provider or local index store; not defined here.
- **Lifetime:** Durable operational artifact, rebuildable on demand.
- **Rebuildability:** Yes from Structured Content and approved Knowledge.
- **Evidence value:** None by itself. Search results must navigate to evidence-backed content.
- **Current implementation:** Deferred.
- **Future direction:** Rebuildable derivative object outside the canonical evidence layer.

### Embeddings

- **Purpose:** Support semantic retrieval, clustering, recommendations, and future intelligence.
- **Owner:** Retrieval/Application for operations; Knowledge governs meaning and provenance.
- **Persistence location:** Future vector store or embedding store; not defined here.
- **Lifetime:** Durable while useful and compatible with the embedding model.
- **Rebuildability:** Yes when input text and model/version are available, with version-specific output.
- **Evidence value:** None by itself.
- **Current implementation:** Deferred.
- **Future direction:** Rebuildable index artifact derived from Structured Content or accepted Knowledge.

### Caches

- **Purpose:** Improve performance or avoid repeated presentation/index computation.
- **Owner:** The layer that uses the cache, usually Application or Processing.
- **Persistence location:** Cache layer, local storage, object storage, or database depending future design.
- **Lifetime:** Temporary or policy-bounded.
- **Rebuildability:** Yes, by definition, or it should not be called a cache.
- **Evidence value:** None.
- **Current implementation:** Mixed implicit compatibility artifacts exist, but no unified cache contract is introduced here.
- **Future direction:** Explicitly disposable and never canonical.

### Temporary processing objects

- **Purpose:** Hold intermediate files, logs, diagnostics, page images, chunks, or payload fragments needed during a processing run.
- **Owner:** Processing.
- **Persistence location:** Temporary workspace or processing artifact storage.
- **Lifetime:** Short-lived unless promoted to a retained artifact or observation.
- **Rebuildability:** Usually yes from retained Source and processing configuration.
- **Evidence value:** Low unless promoted for traceability.
- **Current implementation:** Transitional local OCR flow creates temporary/intermediate local objects.
- **Future direction:** M2 defines cleanup, retry, and artifact-promotion behavior without changing Source ownership.

## 3. Persistence Matrix

This matrix is conceptual. It does not define tables, schema, keys, object naming, APIs, providers, migrations, or implementation tickets.

| Object | Information Layer | Business Owner | Storage Owner | Persistence Target | Durability | Regenerable | Evidence | Current State | Future State |
|---|---|---|---|---|---|---|---|---|---|
| Original Source | Source | `Document` / `SourceFile` | Storage | Retained source storage | Durable when retained | No | Primary evidence | Transitional local path; metadata recorded | Required retained input for processing |
| Storage Object | Source / Artifact / Knowledge / Presentation | Owner of referenced object | Storage | Storage provider or compatibility store | Inherited | Inherited | Inherited | Mixed local/database storage | Provider-independent storage reference |
| Raw `paddle-vl-api` output | Artifact / Observation | Processing | Storage if retained | Processing artifact/observation storage | Optional durable | Usually, with version drift | Supporting observation | Not current path | M2 processing output |
| MinerU-Popo output | Artifact / Processing intermediate | Processing | Storage if retained | Processing artifact storage | Optional durable | Usually, with version drift | Supporting observation | Existing MinerU-like outputs serve Reader compatibility | Intermediate feeding Structured Content |
| Structured Content | Knowledge / Canonical content | Business / Knowledge | Future persistence owner | Durable Atlas content persistence | Durable/versionable | Partially | Evidence-backed canonical content | Not distinct today | Shared canonical application input |
| Knowledge Objects | Knowledge | Future Knowledge/business context | Future persistence owner | Knowledge persistence | Durable when accepted | Partially | Derivative with evidence links | Deferred | Facts, relationships, collections, archive intelligence |
| Presentation Objects | Presentation | Application | Application/cache storage | App store, export store, or cache | Optional | Usually | Not evidence | Reader/processed text compatibility artifacts | Regenerated from Structured Content |
| Search Index | Knowledge / Index artifact | Retrieval/Application; governed by Knowledge | Index provider/storage | Search index | Operational durable | Yes | Not evidence | Deferred | Rebuildable retrieval layer |
| Embeddings | Knowledge / Index artifact | Retrieval/Application; governed by Knowledge | Vector/embedding storage | Embedding/vector store | Operational durable | Yes, model-specific | Not evidence | Deferred | Rebuildable semantic retrieval artifact |
| Caches | Presentation / Artifact | Owning application or processing stage | Cache/storage layer | Cache target | Temporary/policy-bounded | Yes | Not evidence | Implicit and mixed | Explicit disposable cache layer |
| Temporary processing objects | Artifact / Diagnostic | Processing | Temporary workspace/storage | Temporary processing workspace | Short-lived | Usually | Low unless promoted | Transitional local intermediates | M2 retry/cleanup boundary |

## 4. Processing Foundation

The target processing pipeline for M2 is:

```text
Retained Source
  ↓
Storage.get()
  ↓
paddle-vl-api
  ↓
Raw Processing Result
  ↓
MinerU-Popo
  ↓
Structured Content
  ↓
Applications
```

### Boundary responsibilities

| Boundary | Input | Output | Owner | Responsibility | Failure boundary | Retry boundary |
|---|---|---|---|---|---|---|
| Retained Source | Ingested or registered source evidence | Stable source reference | Business via `Document` / `SourceFile` | Provide authoritative input and provenance | Missing or unretained source blocks processing | Retry source retention or mark source unavailable; do not fabricate source |
| `Storage.get()` | Stable source reference | Source bytes/stream | Storage | Retrieve bytes without exposing provider mechanics as business meaning | Retrieval failure is storage/infrastructure failure | Retry retrieval according to storage policy; processing has not started |
| `paddle-vl-api` | Source bytes/stream and processing request | Raw provider-specific result | Processing provider boundary | Produce OCR/layout/document observations | Provider error, timeout, invalid input, unsupported document | Retry provider call when safe; record failure without changing source evidence |
| Raw Processing Result | Provider payload | Retained or transient processing observation | Processing | Preserve provider output long enough for normalization and traceability decision | Invalid or incomplete payload blocks downstream normalization | Retry provider call or revalidate payload; do not promote invalid output |
| MinerU-Popo | Raw processing result | Structured intermediate | Processing normalization boundary | Convert/organize provider output into a form suitable for Atlas normalization | Conversion failure blocks Structured Content creation | Retry conversion from retained raw result or from source if raw result is not retained |
| Structured Content | Structured intermediate plus evidence references | Canonical Atlas content version | Business/Knowledge | Accept provider-independent, evidence-backed document content | Validation/canonicalization failure prevents publication to applications | Retry normalization/canonicalization; applications keep using prior accepted version if one exists |
| Applications | Structured Content | Presentation and workflows | Application | Render, search, teach, archive, and navigate evidence | App rendering failure does not invalidate Structured Content | Retry presentation generation or cache rebuild |

Every boundary should make its input and output explicit. Processing stages may produce temporary objects, retained observations, metrics, logs, or diagnostics, but only Structured Content becomes the shared canonical content contract for applications.

## 5. Structured Content

Structured Content is the Atlas-owned canonical representation of a processed document. It is the reusable, provider-independent, application-independent, evidence-backed content layer that every application may consume.

Structured Content is:

- **Provider-independent:** It does not expose `paddle-vl-api`, MinerU-Popo, local OCR, or any provider payload as its public shape.
- **Application-independent:** It is not optimized for Reader, flashcards, search, notes, or mind maps alone.
- **Evidence-backed:** Its units should trace to retained Source evidence or retained observations when those observations are part of the accepted provenance chain.
- **Canonical:** It is the shared accepted content layer for a document, not one application's preferred rendering.
- **Versionable:** Future processing changes may create new accepted versions without erasing the provenance of older accepted versions.
- **Shared by every application:** Smart Reading OS, Smart Archive, and future applications consume it rather than owning separate canonical copies.

Structured Content is **not**:

- Reader format.
- Stream Text.
- Markdown.
- OCR JSON.
- MinerU output.
- `paddle-vl-api` output.
- A search index.
- Embeddings.
- A cache.
- A database schema defined by this document.

M2 may define how Structured Content is produced and represented, but M1 only defines the contract and boundaries.

## 6. Presentation Layer

Presentation is any application-specific representation created from Structured Content, Knowledge, Artifacts, or Source-derived assets to support a user experience.

Examples include:

- Stream Text.
- Reader pages.
- Mind Maps.
- Flashcards.
- Notes.
- Search results.
- Export formats.
- Reader thumbnails, covers, and page-specific views.

Presentation rules:

- Presentation may be regenerated when its inputs remain available.
- Presentation is application-specific and may change with user experience design.
- Presentation is never canonical.
- Presentation must not own original evidence.
- Presentation must not become the shared document truth merely because it is cached or persisted.
- User-authored presentation changes, such as edited notes, may become durable user data, but they still do not redefine the canonical Structured Content unless a future acceptance workflow explicitly says so.

## 7. Application Consumption

Applications consume Structured Content and may create their own presentation, caches, learning objects, indexes, and workflows. Neither application owns Structured Content.

```text
Structured Content
  ↓
Smart Reading OS
  ├─ Speed Reading
  ├─ Flashcards
  ├─ Mind Map
  └─ Notes

Structured Content
  ↓
Smart Archive
  ├─ Search
  ├─ Knowledge Retrieval
  ├─ Collections
  └─ Evidence Navigation
```

Smart Reading OS uses Structured Content to create reading experiences, learning views, study aids, generated notes, and navigable document views. Smart Archive uses Structured Content and future Knowledge to provide search, retrieval, collections, and evidence navigation. Both applications may ask for presentation outputs, but neither becomes the owner of the canonical content layer.

If an application needs derived objects, those objects must declare whether they are presentation, cache, knowledge draft, accepted knowledge, or user-authored durable data. The application may own its presentation and workflow state, but the shared evidence-backed content remains Atlas-owned.

## 8. M1 → M2 Contract

M1 defines the architecture contract. M2 implements processing.

M2 may assume:

- **Storage guarantees:** Retained Source bytes are accessed through the Storage boundary, not by treating provider paths as business meaning.
- **Source guarantees:** `Document` and `SourceFile` are the business/provenance anchors for source identity and association.
- **Processing inputs:** The target processing input is a retained Source retrieved by `Storage.get()`.
- **Expected outputs:** Processing should produce raw provider observations, MinerU-Popo structured intermediates, and eventually Structured Content suitable for applications.
- **Ownership boundaries:** Storage owns bytes; Business owns source identity and policy; Processing owns processing execution and artifacts; Knowledge owns accepted semantics; Applications own presentation and workflow state.
- **Status/progress concepts:** M2 may introduce processing status and progress concepts around source retrieval, provider execution, conversion, normalization, acceptance, failure, and publication. M1 does not define fields, enums, tables, or APIs.
- **Retry concepts:** M2 may implement retry around storage retrieval, provider execution, raw-result validation, MinerU-Popo conversion, and Structured Content normalization. Retries must not change Source evidence or silently promote invalid outputs.

M2 must not assume that current local OCR artifacts and the target `paddle-vl-api` pipeline are identical. Current implementation is transitional. The target architecture makes retained Source the processing input and Structured Content the shared canonical output.

## 9. Current vs Future

### Current implementation

The current implementation includes a transitional local OCR/Reader path. It uses local processing behavior and existing compatibility artifacts such as processed text, page images, OCR JSON, and MinerU-style outputs to serve current Reader needs. Some bytes and serialized outputs live in local filesystem paths or database fields. This state is operational compatibility, not the final architecture.

Current implementation characteristics:

- Source retention is not yet the universal processing foundation.
- Local OCR processing remains separate from the target `paddle-vl-api` path.
- Reader presentation outputs may be stored or derived from current artifacts.
- Existing MinerU-related outputs are current compatibility artifacts, not automatically canonical Structured Content.
- Database blobs/text and local files may carry operational value, but storage location does not define ownership or canonical status.

### Target architecture

The target architecture for M2 starts from retained Source evidence and uses the Storage boundary to retrieve bytes for processing.

Target characteristics:

- Retained Source is the authoritative processing input.
- `Storage.get()` is the retrieval boundary.
- `paddle-vl-api` produces raw provider-specific observations.
- MinerU-Popo converts raw observations into a structured processing intermediate.
- Atlas normalization produces Structured Content.
- Applications consume Structured Content and generate presentation.
- Search indexes, embeddings, caches, and temporary objects are rebuildable derivatives unless future accepted policy says otherwise.

The current local OCR path and target `paddle-vl-api` path are not identical. M2 may bridge, migrate, or replace current behavior through implementation tasks, but this document does not prescribe the implementation mechanism.

## 10. Deferred Work

The following work is explicitly deferred and must not be treated as implemented by this document:

- `ProcessingRun`.
- Observation.
- `CanonicalNode`.
- Knowledge schema.
- Asset redesign.
- Cloud providers.
- Search implementation.
- Embeddings.
- Vector DB.
- Smart Reading implementation.
- Smart Archive intelligence.
- Database tables, fields, indexes, constraints, and migrations.
- API contracts for processing, status, retrieval, or applications.
- CI, dependency, deployment, and runtime behavior changes.

## 11. M1 Completion

M1 is complete when this foundation is approved because the milestone will have defined the product direction, platform definition, roadmap, core document/source concepts, storage ownership, source retention direction, storage adapter boundary, and the final persistence/processing contract.

This document closes the remaining M1 architecture gap by naming:

- the lifecycle from Source to Applications;
- what Atlas persists and why;
- where persistence responsibility sits conceptually;
- who owns Source, Storage, Processing, Knowledge, Presentation, and Application objects;
- how processing stages exchange data;
- what becomes canonical Structured Content;
- what remains presentation or rebuildable derivative output;
- what M2 may assume and what M2 must implement.

After approval, M2 begins with implementation of the new processing pipeline. M1 defines the contract only; M2 implements processing.
