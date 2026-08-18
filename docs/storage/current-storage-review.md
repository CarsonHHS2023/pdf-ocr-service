# M1-003A Current Storage Architecture Review

| Field | Value |
|---|---|
| Document Type | Current-State Review |
| Evidence Role | Point-in-time storage implementation and documentation review |
| Authority Domain | Storage findings and recommendations at the documented assessment boundary |

## Status

Documentation-only architecture review for **M1-003A Review Current Storage Architecture and Define Atlas Digital Object Taxonomy**.

This review does not implement a Storage Adapter, does not change production code, does not change APIs, does not change database models, does not add migrations, and does not change runtime behavior. Implementation of any recommendation requires future human approval.

M1-003A findings led directly to M1-003B policy/design work. The follow-up documents are [Source Retention Strategy](source-retention-strategy.md), [Storage Ownership Model](storage-ownership-model.md), and [Storage Adapter Design](storage-adapter-design.md). They define proposed retention semantics, ownership boundaries, and the proposed infrastructure boundary before future Storage Adapter implementation work.

## Evidence inspected

This review is based on the current repository documentation and code inspection, including README, roadmap, M1 milestone documentation, product strategy, Atlas architecture documents, database foundation and Alembic strategy documents, ADR-001, current testing documents, engineering principles, and the current application and test modules.

Minimum storage search coverage included repository searches for `open(`, `write(`, `read(`, `tempfile`, `TemporaryDirectory`, `NamedTemporaryFile`, `shutil`, `Path(`, `mkdir`, `unlink`, `rmtree`, `save`, `save_image`, `fitz`, `PyMuPDF`, `uploads`, `tmp`, `cache`, `storage`, `image`, `markdown`, `json`, `pdf`, `png`, `jpg`, `mineru`, and OCR output terms.

## Current state summary

Atlas currently uses a mixed storage model:

1. Uploaded TXT and PDF bytes are first written to local filesystem paths under `uploads/`.
2. Original uploaded files are deleted after TXT extraction or after PDF page rendering.
3. Processed TXT output is written to `output/` for TXT uploads and some legacy paths.
4. Rendered PDF page PNG bytes are stored in the database in `pdf_pages.page_image_data`.
5. Extracted image/table PNG bytes are stored in the database in `book_images.image_data`.
6. Page OCR output is stored as JSON text in `pdf_pages.ocr_raw_json`.
7. MinerU-Popo structured results are stored as JSON text in `mineru_results.result_json`.
8. Optional layout debug JSON artifacts are written under `output/layout_debug` when enabled.
9. The Reader retrieves TXT content from `processed_file_path` for TXT books, but retrieves PDF content by assembling `MineruResult.result_json` into marker-bearing text.
10. Storage ownership and business ownership are partially aligned with the newer `Document` and `SourceFile` concepts, but file/blob placement remains coupled to Reader compatibility and processing flow.

## Current storage locations

| Location | Medium | Current contents | Created by | Durable today? | Notes |
|---|---|---|---|---|---|
| `uploads/` | Local filesystem | Temporary original upload bytes named with `book_id` and original extension. | Upload router. | No. | Originals are deleted after processing/rendering, and `SourceFile.retained` is currently false. |
| `output/` | Local filesystem | Processed TXT files for TXT uploads and legacy/alternate processing paths. | Upload router and book/PDF service paths. | Yes for TXT Reader content today. | This is durable application output, but it is path-coupled to local filesystem. |
| `output/layout_debug/` | Local filesystem | Optional page-level layout debug JSON files. | Enhanced PDF service. | No, unless manually retained. | Diagnostic artifacts are not part of the Reader contract. |
| `documents.processed_file_path` | Database metadata | Path to processed TXT output. | Upload/book services. | Yes as metadata. | Stores a filesystem reference, not object bytes. |
| `documents.original_file_path` | Database metadata | Legacy/source path reference. | Upload/book services. | Mostly null in current success paths. | Compatibility field remains in responses. |
| `source_files` | Database metadata | Original filename, type, MIME, byte size, checksum, retention flag, optional storage reference. | Upload router. | Yes as metadata. | Records source evidence metadata without retaining bytes. |
| `pdf_pages.page_image_data` | Database blob | Rendered full-page PNG bytes from uploaded PDFs. | Upload router. | Yes while book remains. | Processing intermediate and presentation fallback are stored as durable DB blobs. |
| `pdf_pages.ocr_raw_json` | Database text | Page-level OCR JSON payload. | Page OCR background service. | Yes while book remains. | Processing observation stored on page row. |
| `book_images.image_data` | Database blob | Cropped PNG images/tables referenced by `image_id`. | Image service and MinerU-Popo crop path. | Yes while book remains. | Application output consumed by Reader image endpoint. |
| `mineru_results.result_json` | Database text | Structured post-processing block list. | Page OCR background service and MinerU-Popo service. | Yes while book remains. | Current PDF Reader content source. |
| Process-local memory | Memory | Uploaded bytes, page arrays, OCR results, image crops, legacy image task state. | Routers/services. | No. | Temporary compute state only. |
| OS temp files | Temporary filesystem | PaddleX fallback JPGs and legacy endpoint temp PDFs. | Enhanced PDF service and legacy PDF endpoint. | No. | Some paths use explicit cleanup in `finally` blocks. |

## Current file lifecycle

### TXT upload lifecycle

1. The upload endpoint reads the entire uploaded file into memory.
2. The TXT bytes are written to `uploads/{book_id}_original.txt`.
3. A `Document` row and `SourceFile` metadata row are created.
4. The OCR service reads the original file path and decodes the text.
5. Extracted text is written to `output/{book_id}_processed.txt`.
6. The temporary original in `uploads/` is deleted.
7. `Document.processed_file_path` points to the processed TXT file and `Document.original_file_path` is set to null.
8. Reader content for TXT books is loaded by reading `processed_file_path`.
9. Deleting the book attempts to unlink `processed_file_path` and `original_file_path`, then deletes the database row.

### PDF upload lifecycle

1. The upload endpoint reads the entire uploaded PDF into memory.
2. The PDF bytes are written to `uploads/{book_id}_original.pdf` so PyMuPDF can open a path.
3. A `Document` row and `SourceFile` metadata row are created.
4. PyMuPDF renders each page into PNG bytes.
5. One `PdfPage` row is created per page, storing the page PNG bytes and dimensions.
6. The original PDF in `uploads/` is deleted immediately after rendering.
7. Background OCR processes each stored page image, stores `PdfPage.ocr_raw_json`, then invokes MinerU-Popo post-processing.
8. MinerU-Popo crops visual blocks from stored page images and persists cropped PNGs in `book_images`.
9. MinerU-Popo stores the structured block list in `mineru_results.result_json`.
10. The PDF `Document` is marked completed when post-processing succeeds.
11. Reader content for PDFs is assembled from `mineru_results.result_json`, not from a filesystem TXT file.
12. Image markers resolve to `book_images.image_data`; page crop requests decode `pdf_pages.page_image_data` on demand.
13. Deleting the document cascades database rows and attempts filesystem cleanup for stored path fields.

### Optional diagnostic lifecycle

When layout debug is enabled, `EnhancedPDFService` writes page-level JSON artifacts to `output/layout_debug/page_NNNN.json`. These artifacts are intended for troubleshooting. They are not owned by a durable business object and do not have a documented cleanup policy.

### Legacy and alternate paths

The repository still contains alternate PDF endpoints and older processing services that write temporary PDFs, processed TXT files, and image data through service-layer helpers. These paths are not the main Reader upload path but remain compatibility and technical-debt considerations because they demonstrate storage assumptions that a future abstraction must either retire or support during migration.

## Current ownership

| Object | Current owner | Current storage owner | Future architectural direction |
|---|---|---|---|
| Document / book identity | `Document` row, exposed through Bookshelf-compatible responses. | Database. | `Document` remains durable business aggregate root. |
| Source evidence metadata | `SourceFile` row. | Database metadata. | `SourceFile` should own immutable source evidence identity and eventual retained original storage reference. |
| Original TXT/PDF bytes | Temporarily the upload router; not retained after success. | Local `uploads/` during processing only. | `SourceFile` should own retained original evidence when original retention is approved. |
| Processed TXT content | `Document`/Reader compatibility path. | Local `output/` file referenced by `Document.processed_file_path`. | Should become a Digital Object with business ownership separate from storage location. |
| Rendered page image | `PdfPage` row. | Database blob. | Likely a derived processing/presentation artifact owned by document page or future processing run/asset concept. |
| OCR raw JSON | `PdfPage` row. | Database text. | Future `ProcessingRun`/Observation direction, not yet implemented. |
| MinerU result JSON | `MineruResult` row. | Database text. | Derived structured artifact/observation feeding canonical knowledge. |
| Cropped book images/tables | `BookImage` row. | Database blob. | Likely future Asset/Artifact owned by Document or canonical/presentation layer depending purpose. |
| Layout debug JSON | No business owner. | Local filesystem diagnostic path. | Processing diagnostic artifact; should remain outside durable Storage unless explicitly retained. |
| Reader marker protocol | Reader/API compatibility contract. | Text content assembled from DB JSON or TXT files. | Presentation/compatibility object, not a storage ownership model. |

## Temporary vs durable files

### Temporary today

- Uploaded originals under `uploads/`.
- OS temp JPGs used as fallback inputs for PaddleX prediction.
- Legacy endpoint temp PDFs.
- In-memory upload bytes, NumPy arrays, OCR pipeline outputs, and image crops before persistence.

### Durable or semi-durable today

- Processed TXT files under `output/` for TXT content.
- Database rows for `Document`, `SourceFile`, `PdfPage`, `BookImage`, and `MineruResult`.
- Database blobs for rendered pages and extracted visual blocks.
- OCR JSON and MinerU JSON stored as database text.

### Ambiguous today

- Layout debug artifacts are filesystem artifacts that may persist indefinitely if enabled, but they are diagnostic by intent.
- Rendered page images are derived and theoretically reproducible from the original PDF, but current behavior deletes the original PDF, making regeneration impossible without re-upload.
- Cropped image/table PNGs are derived from page images and OCR/layout boxes, but they are part of the current Reader output contract through `image_id` markers.

## Current path handling

Accepted observations:

- `Settings` defines `upload_dir`, `output_dir`, and `layout_debug_dir` as relative `Path` defaults.
- The upload router creates `uploads/` and `output/` at import time.
- `BookService.create_book_from_txt` creates `output/` at write time and sanitizes a title-based filename for legacy/alternate TXT creation.
- Main upload paths use UUID-based filenames for original and processed files.
- File references are stored as strings in database fields.
- The current code assumes local filesystem semantics: path existence checks, direct `open`, direct `unlink`, and synchronous file writes.
- There is no central path allocator, no storage namespace policy, and no consistent distinction between user-visible filename, object key, local path, and storage reference.

## Current cleanup behavior

| Cleanup event | Current behavior | Gap |
|---|---|---|
| TXT success | Deletes temporary original upload file. | Original evidence is not retained. |
| TXT failure | Deletes temporary original upload file. | SourceFile metadata may exist without retained source bytes. |
| PDF render success | Deletes temporary original PDF after pages are rendered. | Rendered page images become the only durable source for visual extraction. |
| PDF render failure | Deletes temporary original PDF and deletes page rows for that book if present. | Partial metadata/source records may remain with failed document state. |
| Page OCR failure | Deletes all `PdfPage` records for the book and marks document failed. | Loss of rendered page evidence and partial diagnostics. |
| Book deletion | Unlinks `processed_file_path` and `original_file_path`; deletes document row and cascades DB blobs/results. | No generalized object cleanup model; only path fields are handled. |
| Image deletion | Deletes `BookImage` DB row. | No storage-object abstraction. |
| Layout debug artifacts | No documented automatic cleanup. | Potential accumulation when enabled. |
| OS temp image fallback | Explicit `finally` cleanup. | Best-effort only; orphan temp files possible on process crash. |

## Current coupling

1. **Business identity is coupled to local paths.** `Document.processed_file_path` and `original_file_path` expose filesystem location details in database state and API responses.
2. **Reader content is coupled to storage representation.** TXT books read a filesystem file, while PDF books assemble content from `MineruResult.result_json`.
3. **Image presentation is coupled to database blobs.** The image endpoint streams `BookImage.image_data` directly.
4. **Processing is coupled to durable storage shape.** Page OCR reads `PdfPage.page_image_data` and writes `PdfPage.ocr_raw_json`; MinerU reads the same page blobs and writes `MineruResult`.
5. **Original evidence is decoupled from source metadata.** `SourceFile` records checksums and metadata, but the original file is deleted and `storage_reference` remains empty.
6. **Compatibility contracts constrain migration.** Current Reader behavior depends on `book_id`, `image_id`, Bookshelf-shaped responses, and `$%$%$%{image_id}$%$%$%` markers.
7. **Diagnostics are coupled to local filesystem.** Layout debug writes JSON artifacts directly to a configured local directory.

## Current technical debt

| Area | Debt | Risk |
|---|---|---|
| Original evidence retention | Source metadata exists but original bytes are deleted. | Reprocessing and auditability are limited. |
| Local filesystem path persistence | Database stores local paths as durable references. | Hard to migrate to cloud/object storage without compatibility adapters. |
| DB blob storage | Rendered pages and images are stored in database blobs. | Database growth, backup cost, migration complexity, and provider lock-in to SQL blob behavior. |
| Mixed content sources | TXT content uses filesystem TXT; PDF content uses MinerU JSON. | Reader behavior and storage semantics are inconsistent. |
| Derived artifacts as de facto source | Page images are derived, but original deletion makes them unrebuildable. | Derived artifacts become accidental evidence. |
| Cleanup semantics | Cleanup is path-specific and row-cascade-specific, not object-lifecycle-based. | Orphan files/artifacts or accidental deletion can occur during future migration. |
| Debug artifact lifecycle | Optional debug JSON has no owner or retention policy. | Unbounded local disk usage if enabled. |
| Legacy paths | Alternate endpoint/service paths still contain direct file writes and temp files. | Future adapter work may miss non-main code paths. |
| Object naming | No central key schema or namespace. | Future migration can produce inconsistent object references. |
| Ownership boundaries | Processing, storage, business ownership, and presentation are intertwined. | Hard to introduce multi-provider storage safely. |

## Current compatibility constraints

Future storage work must preserve current Reader-facing behavior until explicitly versioned:

- Existing `/api/v1` endpoint paths for upload, books, content, delete, and images.
- Bookshelf-shaped response compatibility.
- `book_id` behavior.
- `image_id` behavior.
- `$%$%$%{image_id}$%$%$%` marker protocol.
- Current TXT and PDF reading behavior.
- Current PDF completed-content assembly behavior, unless a future approved task deliberately changes it.
- Current deletion responses and not-found behavior.

Compatibility does not require preserving the current physical storage layout forever. It requires a transition plan that maps stable contracts to new storage references without changing observable behavior accidentally.

## Storage boundary analysis

### What belongs inside Storage

Storage should manage Digital Object bytes and storage references, such as original source files, retained derived artifacts, exported content, page renderings selected for retention, cropped visual assets, and diagnostic artifacts only if they are explicitly retained.

Storage should answer storage questions:

- Where are the bytes?
- How are they referenced?
- Can they be read, written, copied, or deleted?
- What storage-level metadata is required to retrieve them safely?

### What belongs outside Storage

Storage should not own business meaning, Reader presentation behavior, processing decisions, application workflows, or canonical knowledge semantics.

Outside Storage:

- `Document` owns business identity.
- `SourceFile` owns source evidence identity and metadata.
- Future `ProcessingRun` should own processing provenance.
- Future Knowledge concepts should own canonical facts, nodes, summaries, or learning outputs.
- Reader/application layers own presentation protocols and UI-specific rendering.

### Why boundaries matter

Separating business ownership from storage location allows Atlas to migrate from local disk to object storage without changing business identity. Separating processing objects from storage objects prevents temporary OCR artifacts from becoming accidental durable business records. Separating presentation objects from storage objects keeps Reader marker compatibility from dictating long-term storage design.

## Ownership analysis

| Digital object | Current owner | Future owner direction | Notes |
|---|---|---|---|
| Original uploaded source | `SourceFile` metadata only; bytes not retained. | `SourceFile`. | Retention requires a future approved task. |
| Processed TXT | `Document`/Reader compatibility path. | `Document` or future canonical/presentation output, depending accepted content model. | Needs decision whether TXT remains durable output or rebuildable artifact. |
| Rendered page image | `PdfPage`. | Future page/processing artifact owner. | Do not introduce `ProcessingRun` or Asset in this task. |
| Page OCR JSON | `PdfPage`. | Future `ProcessingRun`/Observation. | Current schema keeps it attached to page for compatibility. |
| MinerU JSON | `MineruResult`. | Future ProcessingRun output or canonicalization input. | It is derived and may be rebuildable if source and processing version are available. |
| Cropped image/table PNG | `BookImage`. | Future Asset/Artifact owned by Document or derived from canonical layout. | Current `image_id` contract makes it application-visible. |
| Book cover | Not distinct; may be represented as image block when cover mode is enabled. | Future Presentation or Artifact depending use. | Current behavior is configuration-dependent. |
| Layout debug JSON | No owner. | Processing diagnostic object outside durable Storage by default. | Human decision required if retained. |

Where ownership is not implemented, this document records future architectural direction only. It does not authorize new tables, APIs, adapters, or persistence models.

## Storage evolution

Expected long-term conceptual evolution:

```text
Current mixed filesystem + database blobs
    ↓
Local filesystem with explicit object boundaries
    ↓
Abstract Storage
    ↓
Multiple providers
    ↓
Cloud object storage
    ↓
Distributed storage
```

This evolution is conceptual. It does not define an interface, provider API, object key format, lifecycle policy, or migration plan.

## Accepted decisions

- Storage stores Digital Objects.
- Applications consume Digital Objects.
- Storage is application-independent.
- Business ownership is separate from storage location.
- Original evidence is durable.
- Derived artifacts should be reproducible whenever practical.
- Architecture guides storage.
- Current requirements justify storage.
- Compatibility governs storage evolution.
- `pdf-ocr-service` is the durable business system of record under ADR-001.
- `paddle-vl-api`/OCR compute may own temporary artifacts during execution but does not own durable business data.

## Deferred decisions

- Exact Storage Adapter interface.
- Provider choices such as local filesystem, S3, R2, Azure, Modal Volume, or HF Volume.
- Object key schema and namespace conventions.
- Whether page images remain durable after original PDF retention is implemented.
- Whether processed TXT is durable canonical content, derived presentation output, or compatibility cache.
- Whether `BookImage` evolves into an Asset concept.
- Whether `ProcessingRun` owns OCR JSON and MinerU JSON.
- How to migrate existing database blobs.
- Retention periods for originals, derived artifacts, diagnostics, and failed processing remnants.
- Garbage collection and background cleanup.
- Versioning, deduplication, checksums beyond current source checksum metadata, compression, encryption, and lifecycle policies.

## Codex recommendations requiring human approval

1. Approve original source retention semantics before implementing any storage adapter.
2. Define a small conceptual Digital Object vocabulary before naming adapter methods or database fields.
3. Preserve Reader contracts through compatibility adapters rather than exposing storage locations.
4. Treat current `SourceFile` metadata-without-bytes behavior as transitional, not the final evidence model.
5. Avoid moving DB blobs to object storage until ownership and regeneration rules are accepted.
6. Decide whether processed TXT is canonical durable content or a rebuildable presentation artifact.
7. Document a cleanup policy before adding background cleanup or garbage collection.
8. Keep diagnostic artifacts outside durable Storage unless a concrete debugging/audit requirement justifies retention.

## Risks

- Deleting original PDFs makes derived page images the only durable visual basis for current PDF extraction.
- Local paths in database fields complicate cloud storage migration.
- Database blob growth may affect backup, migration, and performance.
- Multiple current storage patterns increase risk that future adapter work only covers the happy path.
- Reader marker compatibility may accidentally become a storage model if boundaries are not explicit.
- Failed or partial processing cleanup can remove useful diagnostics before root cause analysis.

## Open questions

1. Must all original uploaded sources be retained starting in M1-004, or only PDFs?
2. Should `SourceFile.storage_reference` point to a retained original object when retention begins?
3. Should page renderings be kept after successful OCR if the original source is retained?
4. Should cropped image/table PNGs be treated as durable application output or rebuildable derived artifacts?
5. Should PDF Reader content continue to be assembled from MinerU JSON, or should a durable content stream become the Reader source?
6. What is the expected deletion behavior for retained originals when a user deletes a document?
7. Are layout debug artifacts ever business/audit evidence, or always disposable diagnostics?
8. What storage compatibility behavior is required for existing test databases once Alembic baseline work proceeds?

## M1-003D current state update

Original uploaded TXT/PDF bytes are now retained through the Storage Adapter Local provider in the configured storage root. In the current Hugging Face test deployment, no Persistent Storage is configured, so this local root is ephemeral and may be lost with SQLite data during rebuilds. Temporary upload files remain only as processing inputs and are deleted after TXT processing or PDF page rendering. Processed TXT remains in `output/`; PDF page images remain database BLOBs; OCR and MinerU payloads remain in their existing database text fields.
