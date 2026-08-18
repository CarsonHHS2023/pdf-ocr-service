# Foundation Schema Design

| Field | Value |
|---|---|
| Document Type | Foundation Schema Design |
| Authority Domain | Initial Atlas foundation-schema design |
| Implementation Status | Documentation-only design; no model, API, Alembic, or production changes authorized by this document. |

Task M1-002B-1 is a documentation-only implementation design for the first Atlas foundation schema. It defines what the next SQLAlchemy model work should implement for `Document`, `SourceFile`, and their relationship. It does not modify production code, add Alembic, change APIs, or design future pipeline tables.

## 1. Foundation Design Goals

The first foundation baseline should include only `Document` and `SourceFile` because these are the smallest accepted concepts needed to replace the temporary `Bookshelf` persistence root without expanding into the full Document Intelligence Platform.

`Document` is the durable business object that current Reader flows experience as a book. `SourceFile` is the immutable evidence record for the uploaded or referenced file that gave rise to that document. Together they establish identity, provenance, lifecycle state, and Reader compatibility without prematurely modeling processing internals.

Other concepts remain deferred because they either describe derived processing output, future intelligence capabilities, or storage details that are not required to define the first durable foundation:

| Deferred concept | Why it is deferred |
|---|---|
| `DocumentPage` | Page identity and page-level lifecycle should be designed when page behavior becomes a first-class product or processing requirement. Current Reader compatibility can continue through adapters. |
| `Asset` | Binary/object storage strategy needs its own design. The foundation can reference source storage without designing all rendered pages, crops, thumbnails, or extracted media. |
| `ProcessingRun` | Full processing provenance is important later, but first-baseline status can live on `Document` while processing history remains out of scope. |
| `Observation` | OCR, layout, and AI observations are derived outputs and should not be embedded in the business identity model. |
| Canonical Knowledge | Normalized facts, entities, and claims require future intelligence requirements. |
| Learning | Learning and personalization are future platform concerns, not foundation schema requirements. |
| Archive | Archive and retention behavior should be introduced after the live foundation model is accepted. |

The design rule for the baseline is:

```text
Architecture guides the schema.
Current requirements justify the schema.
Compatibility governs schema evolution.
```

## 2. Document

### Purpose

`Document` represents the durable business identity for a readable or processable item in Atlas. It replaces `Bookshelf` as the long-term persistence root while allowing the current Reader API to continue exposing book-shaped responses.

### Responsibilities

`Document` should own document-level state that is intrinsic to the user-visible item:

| Responsibility | Description |
|---|---|
| Identity | Provide the stable internal aggregate identity and, if selected during implementation, the stable public identifier used as current `book_id`. |
| `document_type` | Store the controlled answer to "What is this?" such as `book`, `invoice`, or `receipt`. |
| Title | Store the current display title used by Reader lists, detail pages, and compatibility responses. |
| Status | Store the current document lifecycle status needed for upload, processing visibility, completion, failure, and deletion semantics. |
| Language | Store the primary language when known or explicitly supplied. |
| Timestamps | Track creation and update timestamps; deletion timestamp may be added if soft deletion is selected. |
| Basic metadata | Store small document-level metadata needed now, such as page count when known, author/name fields needed for Reader compatibility, and minimal user-supplied descriptors. |

### Lifecycle ownership

`Document` owns the current lifecycle state of the user-visible document. It may say that a document is uploaded, processing, completed, failed, or deleted, but it should not own the detailed history of every processing attempt. That history belongs to a future `ProcessingRun` design.

### Business identity

`Document` is the business identity. It is the item a user lists, opens, polls, reads, and deletes. A file can be evidence for a document, but the file is not the long-term business object because a document may later be reprocessed, reimported, corrected, or associated with additional evidence while retaining the same user-visible identity.

### Compatibility role

`Document` is the target internal aggregate behind current Reader book behavior. Current `Book` / `Bookshelf` response shapes should be produced by a compatibility serializer that reads `Document` and related source information and emits existing fields. No permanent `Bookshelf` table should be required by the foundation design.

### Out-of-scope responsibilities

`Document` explicitly does not own:

- OCR output;
- layout output;
- AI observations;
- processing history;
- derived knowledge;
- full page content;
- binary assets;
- extracted image/table payloads;
- archival retention policy;
- learning or personalization state.

### Recommended logical fields

These are logical fields only; they are not SQLAlchemy syntax.

| Logical field | Purpose |
|---|---|
| `id` | Durable internal document identity. |
| `public_id` or compatible identifier | Stable Reader-facing identifier if implementation decides not to expose `id` directly as `book_id`. |
| `document_type` | Controlled type value answering "What is this?" |
| `title` | Display title. |
| `status` | Current document lifecycle status. |
| `language` | Primary language code or unknown value. |
| `page_count` | Basic document-level count when known and needed by Reader compatibility. |
| `metadata` | Small JSON/object metadata for document-level attributes only. |
| `error_message` | Current compatibility-visible failure summary if no `ProcessingRun` exists yet. |
| `created_at` | Creation timestamp. |
| `updated_at` | Last update timestamp. |
| `deleted_at` | Optional soft-delete timestamp if deletion behavior requires it. |

## 3. SourceFile

### Purpose

`SourceFile` represents immutable evidence supplied to or referenced by Atlas. It records the original file or source reference that supports a `Document` without becoming the business identity itself.

### Responsibilities

| Responsibility | Description |
|---|---|
| Evidence identity | Identify one immutable source input or source reference. |
| Provenance | Preserve original filename, media type, size, checksum, and ingestion timestamp when available. |
| Storage reference | Point to retained source bytes when retained, or explicitly record metadata-only evidence when current behavior discards originals. |
| Relationship | Associate the evidence with its owning `Document`. |
| Immutability | Prevent silent mutation of source attributes after creation; replacement should create a new source record. |
| Version expectation | Support future versioning by adding new `SourceFile` rows rather than editing historical evidence. |

### Relationship to Document

A `SourceFile` belongs to one `Document`. The `Document` owns the user-visible identity and lifecycle; the `SourceFile` supplies evidence and provenance. Source records should not be queried or serialized as independent Reader books.

### Immutability

After creation, source evidence fields should be treated as append-only. If a user uploads a corrected file, reimports a different edition, or provides a higher-quality scan, the implementation should create a new `SourceFile` associated with the same or a new `Document` according to the product decision. It should not overwrite the original evidence record.

### Storage abstraction

`SourceFile` should not assume that bytes live in the database, local filesystem, S3, R2, or another object store. It should store a logical storage reference sufficient for the current implementation and compatible with future storage migration.

A retained source should have a storage location/reference and integrity metadata. A metadata-only source should explicitly say that source bytes are not retained so the system does not confuse missing storage with corruption.

### Versioning expectations

The first baseline should not implement a full versioning subsystem. It should use immutable rows so that future versioning can be represented by additional `SourceFile` records plus later relationship metadata if needed.

### Why SourceFile is evidence rather than business identity

A source file answers "What evidence did we receive?" A document answers "What item does the user work with?" The distinction matters because business identity can survive reprocessing, title edits, compatibility serialization, and future knowledge extraction, while evidence must remain historically accurate.

### Recommended logical fields

| Logical field | Purpose |
|---|---|
| `id` | Durable source evidence identity. |
| `document_id` | Owning document reference. |
| `role` | Source role such as `primary` for the initial upload. |
| `original_filename` | User-supplied or upload filename. |
| `media_type` | MIME type when known. |
| `file_extension` | Original extension or normalized extension. |
| `byte_size` | Source byte size when known. |
| `checksum_sha256` | Integrity and duplicate-detection checksum when available. |
| `storage_kind` | Logical storage kind such as local file, object store, external URL, or metadata-only. |
| `storage_uri` | Storage reference when bytes are retained. |
| `retention_state` | Whether bytes are retained, deleted after processing, unavailable, or externally referenced. |
| `ingested_at` | Timestamp when Atlas accepted the source. |
| `created_at` | Row creation timestamp. |

## 4. Relationship

### Option A: One Document to One SourceFile

| Benefit | Cost |
|---|---|
| Matches current single-upload Reader flows. | Makes future replacement, multi-part imports, email attachments, or alternate scans harder to represent. |
| Simpler model and constraints. | Could force a later breaking migration from scalar relationship to collection. |
| Easier compatibility serializer. | Encourages thinking of the file as the document identity. |

### Option B: One Document to Many SourceFiles

| Benefit | Cost |
|---|---|
| Preserves immutable evidence history. | Slightly more implementation complexity. |
| Allows one primary source now and replacement/additional sources later. | Requires a primary-source convention. |
| Better supports future imports with attachments, alternate scans, and source corrections. | Requires clear query behavior for current Reader responses. |
| Keeps `Document` as business identity and `SourceFile` as evidence. | Needs human confirmation for relationship cardinality and primary-source rules. |

### Recommendation

Recommend **one `Document` to many `SourceFile` records**, with exactly one initial `primary` source for current Reader upload flows.

This is still a small foundation because it does not design future pipeline tables or versioning workflows. It simply avoids encoding a false one-file-is-one-document assumption into the first durable schema. Current behavior remains effectively one document to one primary source until a later requirement adds more source records.

### Human confirmation required

Human confirmation is required before implementation for:

1. Whether the first baseline should enforce exactly one primary `SourceFile` per `Document`.
2. Whether multiple `SourceFile` records may exist immediately, or whether the schema should be collection-shaped but application behavior should create only one.
3. Whether source replacement should keep the same `Document` or create a new `Document` in the first implementation.

## 5. Document Type

### Purpose

`document_type` answers:

```text
What is this?
```

It is a controlled, low-cardinality classification of the document's artifact type. It should be stable enough for routing, UI defaults, compatibility, and future processing choices.

### Initial controlled vocabulary

Recommend the initial vocabulary:

| Value | Meaning |
|---|---|
| `book` | A book, long-form reading document, or current Reader-compatible upload. |
| `receipt` | A purchase receipt or transaction slip. |
| `invoice` | A billing invoice. |
| `contract` | A legal or agreement document. |
| `note` | A note, memo, or informal text document. |
| `picture` | A still image whose primary identity is an image. |
| `audio` | An audio recording. |
| `video` | A video recording. |
| `email` | An email message or exported email. |
| `webpage` | A captured or referenced webpage. |
| `other` | Known document whose type is not yet represented. |

For current Reader uploads, the compatibility path should create `Document(document_type="book")`.

### Why Category is different

Category answers a different question, such as:

```text
What is this about?
How should I organize it?
Which user collection, topic, project, or domain does it belong to?
```

A document can be a `book` about programming, a `receipt` for travel, or a `contract` for employment. The type is the artifact form; category is organizational or semantic grouping.

### Why Category should not be stored inside document_type

`document_type` should not encode category because combining artifact form and topic produces unstable values such as `programming_book`, `travel_receipt`, or `employment_contract`. That would make processing rules, UI filters, and compatibility mapping brittle. Categories should be modeled later as application metadata, tags, collections, projects, or knowledge links when requirements justify them.

## 6. Metadata

### Metadata ownership by concept

| Metadata | Document | SourceFile | Future ProcessingRun | Future Knowledge | Future Application |
|---|---:|---:|---:|---:|---:|
| Display title | Yes | No | No | No | Maybe derived display preferences later |
| Artifact type (`document_type`) | Yes | No | No | No | No |
| Current lifecycle status | Yes | No | Maybe detailed run status later | No | No |
| Primary language | Yes | No | Maybe detected-language evidence later | Maybe normalized language facts later | No |
| Page count for Reader compatibility | Yes | No | Maybe computed count evidence later | No | No |
| Original filename | No | Yes | No | No | No |
| MIME type / media type | No | Yes | No | No | No |
| File size | No | Yes | No | No | No |
| File checksum | No | Yes | No | No | No |
| Storage URI/reference | No | Yes | No | No | No |
| Source retention state | No | Yes | No | No | No |
| OCR engine name/version | No | No | Yes | No | No |
| Processing start/end timestamps | No | No | Yes | No | No |
| Processing errors and retries | Only current summary until `ProcessingRun` exists | No | Yes | No | No |
| OCR text output | No | No | Yes, as run output reference | Maybe promoted facts later | No |
| Layout output | No | No | Yes, as run output reference | Maybe promoted structure later | No |
| AI observations | No | No | Yes, as run output/reference | Yes when canonicalized | No |
| Extracted facts/entities | No | No | No | Yes | No |
| Tags, collections, user folders | No for first foundation | No | No | Maybe semantic tags later | Yes when application requirements exist |
| Reader compatibility aliases | Yes if needed for `book_id`/shape | No | No | No | Maybe serializer configuration later |

### First-baseline metadata guidance

| First-baseline location | Include now | Exclude now |
|---|---|---|
| `Document` | title, type, status, language, page count, basic user/display metadata, current error summary if needed | OCR JSON, layout JSON, extracted observations, full processing history, categories/tags unless already required by Reader |
| `SourceFile` | original filename, media type, extension, size, checksum, storage reference, retention state, ingestion timestamp | document title after user edits, Reader status, OCR output, derived assets |

## 7. Reader Compatibility

The current Reader API remains the compatibility boundary. Physical `Bookshelf` persistence should not be required by the foundation schema.

| Current concept | Foundation mapping | Compatibility behavior |
|---|---|---|
| Current Reader `Book` | `Document` | `Document` becomes the authoritative internal aggregate for list, detail, content ownership, and deletion semantics once implementation reaches cutover. |
| Current Reader upload | `Document(document_type="book")` plus one primary `SourceFile` | Upload creates a `Document` with book type and a primary source evidence record. |
| Current Reader responses | Compatibility serializer | Serializer emits Bookshelf-shaped fields such as `book_id`, title/name fields, file type, status, page count, timestamps, and errors from the foundation model. |
| `book_id` | Stable `Document` public identity | Prefer using `Document` identity directly if safe; otherwise add a stable public identifier field. |
| No `Bookshelf` table | Not required | Compatibility should be implemented in application serialization, not by preserving an obsolete physical table as the long-term source of truth. |

During transition, legacy tables may temporarily coexist if implementation sequencing requires it, but the foundation design should not require a permanent `Bookshelf` table.

## 8. Future evolution

The following remain architectural direction only. They should not be implemented in the foundation schema unless a future task approves concrete requirements and compatibility behavior.

| Future concept | Direction, not first-baseline implementation |
|---|---|
| `DocumentPage` | May represent stable page identity and page-level state when page features are required. |
| `Asset` | May represent retained binaries, page renders, thumbnails, extracted images, tables, and object-storage references. |
| `ProcessingRun` | May represent OCR/layout/AI execution history, parameters, outputs, errors, retries, and reproducibility. |
| `Observation` | May represent extracted OCR, layout, vision, or model observations before promotion to knowledge. |
| Canonical Knowledge | May represent normalized facts, entities, claims, relationships, and citations. |
| Learning | May represent personalization, feedback, model improvement, or user-learning state. |
| Archive | May represent retention, preservation, cold storage, and historical lifecycle policy. |

## 9. Implementation Plan

Recommended sequence:

| Step | Work | Rationale |
|---|---|---|
| 1 | Approve this foundation schema design and resolve open questions. | Implementation should begin only after relationship and identity decisions are confirmed. |
| 2 | Add `Document` SQLAlchemy model. | Establish the business identity root first. |
| 3 | Add `SourceFile` SQLAlchemy model. | Add immutable evidence and relationship to `Document`. |
| 4 | Introduce Alembic. | Add migration tooling after the model responsibilities are accepted. |
| 5 | Generate the first baseline migration for the approved `Document` + `SourceFile` schema. | Make the foundation reproducible and reviewable. |
| 6 | Switch database initialization away from long-term reliance on `Base.metadata.create_all()`. | Alembic should become the durable creation path. |
| 7 | Add the Reader compatibility adapter/serializer. | Preserve current API behavior while changing internals. |
| 8 | Move upload/list/detail ownership to the foundation model behind compatibility tests. | Cut over behavior incrementally without changing the Reader contract. |

This sequence is preferable to introducing Alembic first because the first migration should baseline the approved foundation, not mirror temporary tables. Steps 2 and 3 may be implemented in the same PR because the models are meaningful together. Steps 4 and 5 may also be paired if the Alembic setup cannot be validated without a baseline migration.

Do not add `DocumentPage`, `Asset`, `ProcessingRun`, `Observation`, Canonical Knowledge, Learning, or Archive tables in the foundation implementation unless a new approved task changes scope.

## 10. Open Questions

Only these implementation decisions remain unresolved:

1. Should the first implementation use `Document.id` directly as the Reader-facing `book_id`, or should it add a separate stable public identifier?
2. Should the first schema enforce exactly one primary `SourceFile` per `Document`?
3. Should application behavior allow more than one `SourceFile` immediately, or should multiple sources remain schema-ready but unused until a later feature?
4. When source bytes are deleted after processing, what exact `retention_state` value should represent metadata-only evidence?
5. Should first implementation retain uploaded original files, or preserve current deletion behavior and record metadata-only `SourceFile` rows?
6. What initial `Document.status` vocabulary should be accepted for Reader compatibility and future migration safety?

## M1-002B implementation notes

M1-002B implements the accepted foundation cutover without introducing Alembic.
The active SQLAlchemy aggregate is now `Document` in the `documents` table;
`Bookshelf` is retained only as a narrow Python compatibility alias for legacy
type/import boundaries and does not map a separate `bookshelf` table.

Implemented `Document` fields are: `id`, `document_type`, `title`, `author`,
`publication_date`, `pages_count`, `file_type`, `processed_file_path`,
`original_file_path`, `status`, `error_message`, `language`, `created_at`, and
`updated_at`. These fields are limited to durable identity, controlled document
type, Reader-compatible title/status/file/page/error fields, optional language,
and basic timestamps. OCR output, layout output, observations, processing runs,
canonical nodes, facts, learning objects, categories, collections, and domains
remain deferred.

Implemented `SourceFile` fields are: `id`, `document_id`, `original_filename`,
`file_type`, `mime_type`, `byte_size`, `checksum_sha256`, `storage_reference`,
`retained`, `is_primary`, and `created_at`. Current Reader uploads create one
primary metadata record. Existing behavior that deletes the original uploaded
file is preserved, so `retained=0` represents metadata-only source evidence.

The relationship is one `Document` to many `SourceFile` records with ORM
`all, delete-orphan` cascade. Deleting a `Document` also cascades current
SourceFile, content block, image, page, and MinerU result rows. Existing
`PdfPage`, `BookImage`, `ContentBlock`, and `MineruResult` retain their physical
`book_id` column names for Reader/API and processing-risk reduction, but those
foreign keys now target `documents.id`; semantically they reference Document.

Reader compatibility is preserved by continuing to expose `/api/v1/books` and
related routes with `book_id`, `book_title`, `file_type`, `status`, page count,
timestamps, error fields, TXT content behavior, PDF processing-status behavior,
and image marker behavior sourced from `Document`. `/api/v1/books` filters to
`document_type="book"` and does not expose non-book Documents as books.

`document_type` is validated in application code through a string-compatible
`DocumentType` enum/validator and stored as a lowercase string column rather
than a database-native enum. This keeps the first foundation implementation
database-agnostic and reversible before the Alembic baseline.

`Base.metadata.create_all()` remains temporary for the disposable local/test
schema. M1-002C must introduce the Alembic foundation baseline and then replace
or gate create_all-based initialization. Physical compatibility with old local
SQLite test databases is not required for M1-002B; rollback is to revert this PR,
delete/recreate disposable test databases, and run the previous code version.
This rollback posture must be revisited before real production data exists.

## M1-002C Alembic baseline note

The first Alembic baseline follows the implemented M1-002B SQLAlchemy metadata: `documents`, `source_files`, and the transitional Reader support tables currently required by upload/content/image/page behavior. It does not recreate `bookshelf` or `bookshelves` and does not introduce future Document Intelligence Platform tables.

The downgrade is destructive and is valid only while current databases are disposable. This assumption must be revisited before real production data exists.
