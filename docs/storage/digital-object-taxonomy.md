# Atlas Digital Object Taxonomy

| Field | Value |
|---|---|
| Document Type | Architecture Taxonomy |
| Authority Domain | digital-object classification and storage-role distinctions |
| Applies To | Source, Artifact, Knowledge, Presentation, Business Object, Storage Object, Processing Object, Presentation Object |

## Status

Documentation-only architecture taxonomy for **M1-003A Review Current Storage Architecture and Define Atlas Digital Object Taxonomy**.

This document is conceptual only. It does not define database tables, APIs, storage providers, adapter interfaces, object key formats, migrations, or implementation tasks. Implementation requires future human approval.

## Purpose

Atlas needs a shared vocabulary for what it stores before implementing storage abstraction. The goal is to distinguish source evidence, processing artifacts, canonical knowledge, and presentation outputs so storage can evolve without confusing business ownership with byte location.

## Core taxonomy

### Source

A **Source** is original evidence received by Atlas or referenced by Atlas. It is the closest available representation of the real-world information object before Atlas processing changes it.

Responsibilities:

- Preserve provenance.
- Support auditability and reprocessing.
- Remain connected to the `Document` business object through `SourceFile` direction.
- Avoid being overwritten by derived or corrected outputs.

Lifecycle:

- Created at ingestion or source registration.
- Should be durable when source retention is approved.
- May have metadata recorded even before bytes are retained.
- Deleted only according to an explicit future document/source deletion policy.

Classification:

- Durable: yes, when retained.
- Rebuildable: no; it is original evidence.
- Derived: no.
- Business evidence: yes.
- Application output: no.
- Processing intermediate: no.

### Artifact

An **Artifact** is an object produced by processing a Source or another Artifact. It may be retained because it is expensive, useful, application-visible, or needed for compatibility, but it is not the original evidence.

Responsibilities:

- Represent processing outputs such as rendered pages, OCR JSON, layout results, cropped figures, extracted tables, or diagnostic files.
- Remain traceable to its source and processing context when that context exists.
- Be reproducible whenever practical.

Lifecycle:

- Created during processing.
- May be temporary or durable depending purpose.
- Should be safe to regenerate if source evidence and processing versions are available.
- May be deleted independently from Sources if explicitly classified as rebuildable.

Classification:

- Durable: sometimes.
- Rebuildable: usually, when source and processing instructions remain available.
- Derived: yes.
- Business evidence: usually no, except when retained as part of an audit trail.
- Application output: sometimes.
- Processing intermediate: sometimes.

### Knowledge

**Knowledge** is structured, reusable understanding derived from Sources and Artifacts. It includes canonical text, document structure, facts, semantic relationships, embeddings, indexes, and future learning/archival intelligence.

Responsibilities:

- Represent what Atlas understands, not merely where bytes live.
- Remain connected to evidence.
- Support applications such as Smart Reading OS and Smart Archive without duplicating document identity.
- Preserve distinction between observations, accepted canonical knowledge, and generated learning outputs.

Lifecycle:

- Created through canonicalization, extraction, validation, or future AI workflows.
- Updated through explicit revision/version concepts in future tasks.
- Should remain traceable to Sources and Artifacts.

Classification:

- Durable: often, when accepted as canonical or product data.
- Rebuildable: sometimes, but human decisions or model versions may make exact regeneration impossible.
- Derived: yes.
- Business evidence: no by itself; it must link to evidence.
- Application output: sometimes.
- Processing intermediate: no when canonical; yes when provisional observation.

### Presentation

A **Presentation** object is an application-facing representation optimized for a user experience or compatibility contract. It may be derived from Knowledge or Artifacts.

Responsibilities:

- Serve Reader or future application views.
- Preserve stable public protocols such as the current image marker format until versioned.
- Avoid owning business identity or source evidence.

Lifecycle:

- Created for application consumption.
- May be cached, exported, or regenerated.
- May change when a presentation contract is versioned.

Classification:

- Durable: sometimes, when required by compatibility or export needs.
- Rebuildable: usually.
- Derived: yes.
- Business evidence: no.
- Application output: yes.
- Processing intermediate: no.


## Orthogonal classification and ownership

Information layer and ownership are orthogonal. The information layer classifies what an object represents: Source, Artifact, Knowledge, or Presentation. Ownership/responsibility identifies who gives it meaning, who stores it, who produces it, and who consumes it: Business, Storage, Processing, or Application.

`Document` is not itself a Digital Object. It owns business identity, relationships, lifecycle, and meaning. Stored bytes and serialized objects belong to the Storage dimension mechanically, even when Business policy decides why they exist and how long they should be retained.

A single object may therefore be Source in information classification, Business-owned in policy, and Storage-managed in mechanics. For example, an original PDF is source evidence associated with a `SourceFile`; Business policy decides retention, while Storage manages bytes and retrieval. Retention Policy, Deletion Authority, and Rebuildability are also separate dimensions; labels such as diagnostic, cache, evidence, processing output, or application output describe object purpose, not retention classes. See [Storage Ownership Model](storage-ownership-model.md) for the detailed ownership model and [Source Retention Strategy](source-retention-strategy.md) for proposed retention policy.

## Boundary vocabulary

| Boundary | Meaning | Does it store bytes? | Owner |
|---|---|---:|---|
| Business Object | A domain object such as `Document` or `SourceFile` that owns meaning, identity, and lifecycle. | Not necessarily. | Domain model. |
| Storage Object | A stored byte object or storage reference. | Yes. | Storage layer. |
| Processing Object | Temporary or retained output used to execute or explain processing. | Sometimes. | Processing flow or future `ProcessingRun`. |
| Presentation Object | User/application-facing representation. | Sometimes. | Application/Reader layer. |

These boundaries matter because the same bytes may serve multiple purposes. A rendered page image can be a processing artifact, a presentation fallback, and a temporary substitute for a deleted original. Those roles must be named separately so future storage work does not make accidental ownership decisions.

## Digital Object Inventory

| Digital object | Concept | Purpose | Owner | Lifetime | Can be regenerated? | Business value | Future direction |
|---|---|---|---|---|---|---|---|
| Original PDF | Source | Original uploaded PDF evidence. | Current: `SourceFile` metadata; bytes temporary. Future: `SourceFile`. | Current: deleted after rendering. Future: durable if approved. | No. | High evidence and reprocessing value. | Retain as source evidence in future approved original-retention task. |
| Original TXT | Source | Original uploaded text evidence. | Current: `SourceFile` metadata; bytes temporary. Future: `SourceFile`. | Current: deleted after extraction. Future: durable if approved. | No. | Medium to high evidence value. | Decide retention alongside PDF/source policy. |
| Original Image | Source | Future still-image source. | Future `SourceFile`. | Deferred. | No. | High evidence value for picture/archive use cases. | Conceptual only; no implementation in this task. |
| Future Audio | Source | Future audio recording source. | Future `SourceFile`. | Deferred. | No. | High evidence value for transcripts and archive. | Conceptual only. |
| Future Video | Source | Future video recording source. | Future `SourceFile`. | Deferred. | No. | High evidence value for multimodal archive/learning. | Conceptual only. |
| Rendered Page Image | Artifact | PNG rendering of a PDF page for OCR, cropping, and page crop endpoint. | Current: `PdfPage`. Future: page artifact or processing artifact. | Current: durable while document remains unless failure cleanup deletes pages. | Yes if original PDF retained; no if original deleted. | High current operational value. | Classify as derived; decide retention after original retention. |
| OCR JSON | Artifact / Observation | Raw page OCR/layout output. | Current: `PdfPage`. Future: `ProcessingRun`/Observation. | Current: durable while pages remain. | Yes if source and model/version available, but exact output may vary. | Medium traceability and debugging value. | Keep conceptual distinction from canonical knowledge. |
| OCR Markdown | Presentation / Artifact | Possible markdown rendering of OCR output. | Not currently distinct. Future application or processing owner. | Deferred. | Usually yes. | Medium user/export value. | Do not implement unless a Reader/export requirement justifies it. |
| Layout Results | Artifact / Observation | Layout block boxes, labels, confidence, and diagnostics. | Current: in memory, OCR JSON, optional debug JSON. Future: processing observation. | Current: mixed temporary/durable. | Usually yes with same model/version. | Medium; supports explainability and image extraction. | Separate durable observations from disposable diagnostics. |
| MinerU Results | Artifact / Presentation input | Cross-page structured block list used to assemble PDF content. | Current: `MineruResult`. Future: processing output feeding canonical/presentation layers. | Current: durable while document remains. | Usually yes if source/page images and OCR JSON remain. | High current Reader value. | Decide whether it remains Reader source or becomes ingestion artifact. |
| PP-Structure Results | Artifact / Observation | Legacy/local layout results from earlier architecture. | Current: legacy/manual paths only. | Current: not primary. | Yes if legacy pipeline available. | Low current value; historical compatibility. | Do not expand without human approval. |
| Book Cover | Presentation / Artifact | Cover image shown or represented as first-page visual. | Current: not a separate object; may be image marker when enabled. Future: presentation artifact. | Configuration-dependent. | Yes from source if retained. | Medium Reader value. | Keep conceptual until cover product requirements are explicit. |
| Extracted Tables | Artifact / Presentation | Cropped table PNGs and future structured table data. | Current: `BookImage` for PNG. Future: Artifact/Knowledge depending representation. | Current: durable while document remains. | PNG crop yes if source/page/layout remains; structured table depends extraction. | High reading/archive value. | Distinguish visual crop from structured table knowledge. |
| Extracted Figures | Artifact / Presentation | Cropped figure/image PNGs referenced by `image_id`. | Current: `BookImage`. Future: Artifact/Asset direction if approved. | Current: durable while document remains. | Yes if source/page/layout remains. | High Reader value. | Preserve `image_id` compatibility while decoupling storage location. |
| Layout Debug JSON | Artifact / Diagnostic | Troubleshooting metadata for layout blocks. | Current: no business owner; local debug directory. | Current: indefinite if enabled. | Yes by reprocessing, roughly. | Low to medium diagnostic value. | Treat as disposable unless audit need is approved. |
| Processed TXT File | Presentation / Artifact | Reader-compatible text for TXT uploads and legacy paths. | Current: `Document.processed_file_path`. Future: presentation output or canonical content decision pending. | Current: durable local file while document remains. | For TXT, yes from retained source; currently no if original deleted. | High current Reader value. | Decide whether to keep as durable output or rebuildable cache. |
| Image Marker Text | Presentation | `$%$%$%{image_id}$%$%$%` content reference protocol. | Current: Reader/API compatibility layer. | Durable as part of content output. | Yes from structured block list. | High compatibility value. | Preserve until explicitly versioned. |
| Future Mind Maps | Knowledge / Presentation | Learning representation derived from document knowledge. | Future Knowledge/application owner. | Deferred. | Maybe; exact AI output may vary. | Future learning value. | Conceptual only; no persistence now. |
| Future Flashcards | Knowledge / Presentation | Study cards derived from canonical knowledge/evidence. | Future Learning/Knowledge owner. | Deferred. | Maybe; exact AI output may vary. | Future learning value. | Conceptual only. |
| Future AI Notes | Knowledge / Presentation | Generated or user-assisted notes. | Future Knowledge/Application owner. | Deferred. | Generated notes may be partially rebuildable; user notes are not. | Future product value. | Distinguish generated notes from user-authored notes later. |
| Future Embeddings | Knowledge / Index Artifact | Vector representation for retrieval. | Future retrieval/index owner. | Deferred. | Yes if model and source text remain, but exact values depend version. | High future search/reasoning value. | Treat as rebuildable index artifact unless accepted otherwise. |
| Future Search Indexes | Knowledge / Index Artifact | Keyword/semantic retrieval structures. | Future retrieval/index owner. | Deferred. | Yes. | High future archive value. | Keep outside source evidence; design with rebuild strategy. |
| Future Knowledge Graphs | Knowledge | Entities, relationships, evidence links. | Future Knowledge owner. | Deferred. | Partially; validated graph edits may not be exactly rebuildable. | High future archive/reasoning value. | Requires separate design and human approval. |

## Storage boundary decisions for the inventory

### Business Object vs Storage Object

A `Document` is a business object. An original PDF object is a storage object owned conceptually by `SourceFile`. A `SourceFile` is not the bytes themselves; it is the business/provenance record that should reference the bytes when retention is implemented.

### Processing Object vs Storage Object

OCR JSON, layout boxes, rendered page PNGs, and MinerU results are processing objects. If retained, Storage stores their bytes or serialized payloads, but Storage does not decide whether they are authoritative.

### Presentation Object vs Storage Object

Processed TXT, Markdown, image markers, covers, and rendered reader assets are presentation objects. Storage may store them, but the Reader/application layer owns their contract and meaning.

## Ownership analysis

| Owner | Should own | Should not own |
|---|---|---|
| `Document` | Business identity, document-level lifecycle, relationship to source evidence and application-visible state. | Raw byte locations as business meaning; provider-specific storage details. |
| `SourceFile` | Immutable source evidence metadata and future retained source reference. | Derived OCR/layout outputs, Reader presentation content. |
| Future `ProcessingRun` | Processing execution context, model/tool version, observations, temporary/retained processing outputs. | Document identity, source evidence ownership, user-facing Reader contracts. |
| Future Knowledge | Canonical content, facts, relationships, reusable understanding, learning/archive intelligence. | Original evidence bytes or storage-provider concerns. |
| Future Application | Presentation formats, Reader streams, learning views, archive views. | Durable evidence ownership and provider-specific storage operations. |
| Storage | Bytes, references, retrieval and deletion mechanics. | Business meaning, canonical truth, UI protocol semantics. |

Where these owners are not implemented, this table documents architectural direction only.

## Architecture principles

Accepted principles for storage and digital objects:

1. Storage stores Digital Objects.
2. Applications consume Digital Objects.
3. Storage is application-independent.
4. Business ownership is separate from storage location.
5. Original evidence is durable.
6. Derived artifacts should be reproducible whenever practical.
7. Architecture guides storage.
8. Current requirements justify storage.
9. Compatibility governs storage evolution.

These principles are intentionally small. Additional principles should be added only when justified by future human decisions.

## Current state vs future direction

### Current state

- `Document` and `SourceFile` concepts exist, but source bytes are not retained.
- Durable bytes are split between local filesystem and database blobs.
- Derived page images and cropped image/table PNGs are durable today because the Reader and OCR pipeline need them.
- PDF content is assembled from MinerU JSON; TXT content is read from processed TXT files.
- Storage location is exposed as local path metadata in compatibility responses.

### Future direction

- Treat original sources as durable evidence once approved.
- Treat rendered pages, OCR JSON, MinerU JSON, and crops as classified artifacts with explicit retention/regeneration rules.
- Keep Storage provider-independent.
- Keep Reader presentation contracts stable while storage internals evolve.
- Introduce richer owners such as `ProcessingRun`, Asset, or Knowledge only through future approved tasks.

## Deferred concepts

The following are intentionally deferred:

- Storage Adapter implementation.
- Storage providers and provider APIs.
- Asset model.
- ProcessingRun implementation.
- Knowledge persistence.
- Search persistence.
- Embedding storage.
- Versioning.
- Deduplication.
- Additional checksum policy beyond current source checksum metadata.
- Compression.
- Encryption.
- Object lifecycle policies.
- Garbage collection.
- Background cleanup.

## Accepted decisions

- Atlas stores and consumes Digital Objects, not merely local files.
- `Document` is the durable business aggregate root direction.
- `SourceFile` represents immutable source evidence direction.
- OCR compute outputs are observations/artifacts, not durable business ownership.
- Reader marker compatibility must be preserved until deliberately versioned.

## Deferred decisions

- Which Digital Objects are retained in M1 vs later milestones.
- Whether retained originals apply to all supported source types immediately.
- Whether processed TXT is canonical content or presentation cache.
- Whether image/table crops are future Assets or retained presentation artifacts.
- Whether layout/OCR/MinerU JSON become ProcessingRun-owned observations.
- Exact deletion semantics for source evidence and derived artifacts.

## Codex recommendations requiring human approval

1. Use this taxonomy to review future storage adapter scope before coding.
2. Make original source retention the first durable storage policy decision.
3. Classify every new byte-producing feature as Source, Artifact, Knowledge, or Presentation before implementation.
4. Treat rebuildable derived artifacts differently from original evidence.
5. Preserve current Reader compatibility with adapters rather than freezing current storage layout.
6. Document owner and lifetime before adding future mind maps, flashcards, embeddings, search indexes, or knowledge graphs.

## Risks

- Without taxonomy, derived artifacts can become accidental business evidence.
- Without source retention, Atlas cannot reliably regenerate derived objects.
- Without owner separation, storage-provider migration can leak into product/API contracts.
- Without explicit presentation boundaries, Reader markers may over-constrain long-term object design.

## Open questions

1. Which source formats must be retained first: PDF only, or PDF/TXT/image together?
2. Is exact reprocessing required, or is best-effort regeneration acceptable for derived artifacts?
3. Should OCR JSON be retained for traceability after canonical knowledge exists?
4. Should rendered page images be deleted once originals and crops are retained?
5. Are generated learning objects considered Knowledge, Presentation, or both in future product design?
6. What user-facing deletion semantics should apply when a document has source evidence, artifacts, knowledge, and presentation outputs?
