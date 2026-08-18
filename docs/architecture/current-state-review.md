# Current-State Cross-Repository Review

| Field | Value |
|---|---|
| Document Type | Current-State Review |
| Evidence Role | Point-in-time architecture repository review |
| Assessment Date | 2026-07-11 |
| Authority Domain | Architecture repository-state findings at the documented inspection boundary |

Date: 2026-07-11

## Scope and inspection status

This review uses `docs/architecture/document-intelligence-platform.md` as the target direction, not as a description of the current implementation.

Repositories inspected:

- `pdf-ocr-service`: inspected locally in `/workspace/pdf-ocr-service`.
- `speed-reading-trainer`: Git clone to `/workspace/speed-reading-trainer` still failed from the shell with `CONNECT tunnel failed, response 403`, but after the repository was made public it was inspected through GitHub web/raw views at `CarsonHHS2023/speed-reading-trainer` on 2026-07-11. Important frontend findings below cite exact repository paths and symbols from that web inspection. No production code was changed in that repository.

Commands used for repository discovery included `find /workspace -maxdepth 2 -type d -name .git -print`, `find /workspace -maxdepth 3 -type d -iname '*speed*' -print`, `git remote -v`, `git clone https://github.com/CarsonHHS2023/speed-reading-trainer.git /workspace/speed-reading-trainer`, and GitHub web/raw inspection after shell Git access failed.

## 1. Repository overview

### `pdf-ocr-service`

- **Language/framework:** Python FastAPI service using SQLAlchemy ORM, Pydantic schemas, PyMuPDF, OpenCV, PaddleOCR/PaddleOCR-VL, and optional `magic-pdf`/MinerU-style post-processing.
- **Entrypoints:** `app.py` runs `uvicorn` against `app.main:app`; `app/main.py` constructs the FastAPI app, configures permissive CORS, includes the active routers, and initializes database tables at startup.
- **Major directories:** `app/routers` contains active HTTP routes; `app/services` contains page OCR, database, PDF-processing, and MinerU-Popo services; root-level `app/*.py` contains models, schemas, configuration, OCR/PDF/image/book services; `tests` contains pytest suites; `docs/architecture` contains the target architecture.
- **Persistence:** Default SQLAlchemy URL is `sqlite:///./ocr_tasks.db`, with non-SQLite URLs allowed through `DATABASE_URL`. Tables are created by `Base.metadata.create_all`; no migration framework is present. Uploaded TXT/PDF files are temporarily written to `uploads`; processed TXT output is written to `output`; PDF page images, cropped images/tables, and OCR JSON are stored in database rows.
- **Deployment model:** `Dockerfile`, `Procfile`, `render.yaml`, `runtime.txt`, `build.sh`, and `run.sh` indicate container/Render/Hugging Face Spaces-style deployment. The runtime app listens on `0.0.0.0:7860`.
- **Test framework:** `pytest` with `pytest.ini`, `requirements-test.txt`, and helper scripts `run_tests.sh` and `run_light_tests.sh`. Some tests are marked/informally described as heavy because they require real OCR/PDF dependencies.
- **Current responsibilities:** The service currently owns bookshelf records, TXT/PDF upload, PDF rendering into page images, in-process PaddleOCR-VL inference, MinerU-Popo normalization, image/table crop storage, content assembly, and image serving.

### `speed-reading-trainer`

The repository is a static, native JavaScript frontend. The inspected files are `README.md`, `index.html`, `app.js`, `bookshelf.js`, `style.css`, and `.github/workflows`. There is no `package.json` or lock file in the repository listing, so there is no npm framework/build step to document. `index.html` is the browser entrypoint and loads the reader/bookhelf scripts and CSS. `bookshelf.js` defines `API_BASE_URL = 'https://carsonhhs-pdf-ocr-service.hf.space'` and a `BookShelf` class that owns upload, bookshelf rendering, category UI, polling, selection, and deletion. `app.js` owns reader state, focus/page display modes, tokenization, image-marker handling, speed timing, progress slider, theme persistence, and reading controls. The repository uses GitHub Pages/static hosting rather than a bundled frontend framework.

## 2. Actual runtime architecture

The current real architecture across the inspected backend and public frontend is below.

```mermaid
flowchart LR
    Browser[Browser / API client]
    SRT[speed-reading-trainer static JS\nindex.html + app.js + bookshelf.js]
    API[pdf-ocr-service FastAPI\napp.main:app]
    DB[(SQLAlchemy DB\ndefault SQLite ocr_tasks.db)]
    Uploads[(uploads/\ntemporary originals)]
    Output[(output/\nprocessed TXT + debug artifacts)]
    PageDB[(pdf_pages.page_image_data\nPNG bytes in DB)]
    ImageDB[(book_images.image_data\ncropped PNG bytes in DB)]
    PaddleLocal[PaddleOCR-VL local Python package]
    LegacyOCR[PaddleOCR / PP-Structure wrappers]
    MagicPDF[optional magic-pdf / built-in MinerU-Popo rules]

    Browser --> SRT
    SRT -->|GET /api/v1/books; POST /api/v1/upload; GET /api/v1/books/{book_id}; GET /content; DELETE; GET /images/{image_id}| API
    Browser -->|direct HTTP possible| API
    API --> DB
    API --> Uploads
    API --> Output
    API --> PageDB
    API --> ImageDB
    API --> PaddleLocal
    API --> LegacyOCR
    API --> MagicPDF
```

Important distinction from the target architecture: `paddle-vl-api` is not used as a separate service in the inspected code. OCR compute is invoked inside `pdf-ocr-service` through `from paddleocr import PaddleOCRVL`.

## 3. Existing domain model

Actual ORM entities in `app/models.py`:

- `OCRTask`: `id`, `filename`, `status`, `created_at`, `updated_at`, `result_text`, `error_message`, `pages_count`. This appears legacy; current upload flow uses `Bookshelf`/`PdfPage` instead.
- `Bookshelf`: `id`, `book_title`, `author`, `publication_date`, `pages_count`, `file_type`, `processed_file_path`, `original_file_path`, `status`, `error_message`, timestamps, and relationships to `ContentBlock`, `BookImage`, `PdfPage`, and `MineruResult`.
- `ContentBlock`: `book_id`, `page_num`, `block_index`, `block_type`, `content`, `bbox`, `confidence`.
- `BookImage`: `book_id`, `image_id`, `image_format`, `image_data`, `image_size`, `page_num`, `bbox`, `block_type`.
- `PdfPage`: `book_id`, 1-based `page_num`, `status`, `page_image_data`, `page_width`, `page_height`, `ocr_raw_json`, `error_message`, timestamps.
- `MineruResult`: one row per book via unique `book_id`, `status`, `result_json`, `error_message`, timestamps.

Missing target entities include `documents`, `source_files`, `document_versions`, `document_pages` as a stable universal model, `document_assets`, `processing_runs`, `ocr_runs`, `ocr_pages`, `ocr_blocks`, `document_revisions`, `document_nodes`, `node_regions`, `node_relations`, archive-intelligence records, and learning records.

## 4. Current API contract

Active endpoints included by `app/main.py`:

| Method | Path | Source | Request/response role | Known/likely caller | Status |
|---|---|---|---|---|---|
| GET | `/` | `app/main.py` | service metadata | browser/health/manual | stable utility |
| GET | `/api/v1/health` | `app/routers/health.py` | health response | deployment checks/tests | stable |
| POST | `/api/v1/upload` | `app/routers/ocr.py` | upload PDF/TXT; TXT synchronous, PDF async; returns `UploadBookResponse` | likely frontend/import UI | important/stable current path |
| POST | `/api/v1/ocr/{task_id}` | `app/routers/ocr.py` | process legacy in-memory OCR task | no active upload task creator found | experimental/legacy/possibly unused |
| POST | `/api/v1/structure/{task_id}` | `app/routers/ocr.py` | process legacy in-memory structure task | no active upload task creator found | experimental/legacy/possibly unused |
| GET | `/api/v1/result/{task_id}` | `app/routers/ocr.py` | read legacy in-memory task result | no active upload task creator found | experimental/legacy/possibly unused |
| GET | `/api/v1/books` | `app/routers/books.py` | list `Bookshelf` records | likely bookshelf/document picker | stable current path |
| GET | `/api/v1/books/{book_id}` | `app/routers/books.py` | book metadata | likely frontend detail/polling | stable current path |
| GET | `/api/v1/books/{book_id}/content` | `app/routers/books.py` | assembled TXT content with image markers | likely reader content loader | stable current path |
| DELETE | `/api/v1/books/{book_id}` | `app/routers/books.py` | delete DB book plus associated processed/original files | likely admin/UI delete | stable but retention-sensitive |
| GET | `/api/v1/images/{image_id}` | `app/routers/images.py` | return cropped stored image bytes | frontend rendering image/table markers | stable current path |
| GET | `/api/v1/images/page_crop/{book_id}/{page_num}` | `app/routers/images.py` | crop from stored full page image | focus/region tooling or debugging | useful but route-order risk, see debt |
| DELETE | `/api/v1/images/{image_id}` | `app/routers/images.py` | delete one cropped image row | manual/admin | stable but broad |

Inactive routes in `app/api/pdf_endpoints.py` are not included by `app/main.py`; they define `/api/pdf/upload-and-process`, `/api/pdf/process-status/{book_id}`, `/api/pdf/book-text/{book_id}`, `/api/pdf/book-images/{book_id}`, and `/api/pdf/image/{image_id}`. They appear duplicated/legacy unless another uninspected entrypoint imports them; `app.py` points to `app.main:app`, so they are not active in the default runtime.

## 5. Current storage behavior

- Uploaded PDF files are written temporarily to `uploads/{book_id}_original.pdf` by `POST /api/v1/upload`, opened with PyMuPDF, rendered to per-page PNG bytes, and then deleted immediately.
- Uploaded TXT files are written temporarily to `uploads/{book_id}_original.txt`, processed, written to `output/{book_id}_processed.txt`, and then the original TXT is deleted.
- Original files are not retained in the primary current flow. `Bookshelf.original_file_path` is explicitly treated as deprecated/compatibility data.
- PDFs are not split into separate PDF files; they are rendered page-by-page into PNG bytes stored in `PdfPage.page_image_data`.
- Page records do exist for PDF uploads through `PdfPage`; numbering is 1-based.
- Page images and cropped image/table content are stored as binary `LargeBinary` columns in the database, not in object storage.
- OCR output is stored as JSON text in `PdfPage.ocr_raw_json`, then normalized into one `MineruResult.result_json` JSON string per book.
- Processed TXT for TXT uploads remains on disk under `output`; PDF content is assembled from `MineruResult`, not a retained processed TXT in the active `/api/v1/upload` flow.
- Deletion through `DELETE /api/v1/books/{book_id}` removes `processed_file_path` and `original_file_path` if present and deletes the `Bookshelf` row, cascading related page/image/content rows.
- Storage ownership is partially clear inside the single service but not aligned to the target: durable originals are absent, database stores large binaries, and `Book` remains the top-level abstraction.

## 6. Current speed-reading functionality

Implemented frontend behavior in `speed-reading-trainer`:

- `bookshelf.js::loadBooksFromBackend` calls `GET /api/v1/books`, expects a JSON object with `books`, filters out `status === 'processing'`, and normalizes `book_id`/`id`, `book_title`/`title`/`name`, `file_type`, `created_at`, `pages_count`, `author`, and `status`.
- `bookshelf.js::handleFileUpload` and `handleMultiFileUpload` upload files with `POST /api/v1/upload` using multipart field `file`; they branch on `result.status === 'processing'` or `completed`, rely on `result.book_id`, `result.book_title`, and optionally `result.pages_count`, and poll processing PDFs through `GET /api/v1/books/{book_id}`.
- `bookshelf.js::_pollBookStatus` polls `GET /api/v1/books/{book_id}` every 5 seconds and treats `status === 'completed'` and `status === 'failed'` as terminal states; it optionally displays `progress` if the backend returns it.
- `bookshelf.js::selectBook` calls `GET /api/v1/books/{book_id}/content`, expects `result.content` to be a string, wraps it in a browser `File`, and sets `state.cachedContentBlob`; reader tokenization does not happen until the user starts reading.
- `bookshelf.js::deleteBook` calls `DELETE /api/v1/books/{book_id}` and removes the local book from the in-memory shelf.
- `app.js::tokenizeContent` splits backend text on `CONTENT_DELIMITER = '$%$%$%'`; the text between delimiter pairs is treated as an image ID, stored in `state.imageMarkerMap`, and represented in `state.units` by the delimiter token. Therefore the exact marker format `$%$%$%{image_id}$%$%$%` is a hard compatibility constraint.
- `app.js::fetchImageData` calls `GET /api/v1/images/{image_id}` and supports either binary image responses or JSON with `image_data`; current backend binary streaming is compatible.
- `app.js` implements two display modes: focus mode (`displayMode === 'focus'`) and page/full-page mode (`displayMode !== 'focus'`). Focus mode batches units with `getFocusBatchInfo` and `startFocusLoop`; page mode builds `state.pages` in `generatePages` and advances through them in `startPageLoop`.
- Reading controls are a single toggle button plus click-to-pause/resume on the reading panel. `startReading`, `pauseReading`, `resumeReading`, and `stopReading` maintain in-memory `state.isPlaying`, `state.isPaused`, `startTime`, `pausedTime`, and `totalPausedDuration`.
- Timing is speed-based rather than measured WPM analytics: focus mode computes intervals as `(60000 / state.speed) * effectiveChars` with a minimum batch interval, and page mode computes `(60000 / state.speed) * currentPage.charCount`. The UI label says `词/分钟`; no persisted WPM result or comprehension-adjusted metric exists.
- Progress is in-memory only: `updateProgress` sets current position, total units, progress slider value, and elapsed time while playing. `seekToProgress` seeks by ratio and skips image-marker positions.
- The only confirmed `localStorage` key is `theme`, used by `app.js::initTheme` and `applyTheme`. No `sessionStorage` or `indexedDB` usage was found in inspected frontend files. Books, categories, expanded categories, selected book, reading position, speed, display mode, WPM/timer state, and upload state are not persisted across reloads in the inspected code.
- Image/table display is marker-driven, not layout-driven: images pause reading in `pauseForImageMarker`, show a chart/image overlay, and allow rotate/flip transformations before continuing. The frontend does not use `GET /api/v1/images/page_crop/{book_id}/{page_num}`.
- There are no implemented notes, summaries, quizzes, authentication flows, or durable reading-session/progress APIs in inspected frontend files.
- Page numbering assumptions are indirect: the frontend does not request numbered pages from the backend. It derives local `state.pages` from tokenized content and page-mode settings, so backend `PdfPage.page_num` can evolve internally as long as content and image IDs remain compatible.

## 7. Current OCR and document flow

Actual active `POST /api/v1/upload` flow:

1. Upload accepts `.pdf` or `.txt` only.
2. TXT path:
   - Save original TXT temporarily in `uploads`.
   - Create a `Bookshelf` row with `status=processing`.
   - Use `get_ocr_service().process_txt` to read/extract text.
   - Write processed text to `output/{book_id}_processed.txt`.
   - Delete original TXT.
   - Mark book completed.
3. PDF path:
   - Save original PDF temporarily in `uploads`.
   - Create a `Bookshelf` row with `status=processing`.
   - Open with PyMuPDF and render each page at 300 DPI to PNG bytes.
   - Create `PdfPage` rows with 1-based page numbers and full-page PNG bytes.
   - Delete original PDF immediately.
   - Schedule `process_book_background(book_id)`.
4. Background OCR:
   - Query pending `PdfPage` rows for the book.
   - Decode each stored page PNG and invoke local `PaddleOCRVL` via the Python package.
   - Serialize `parsing_res_list` into `PdfPage.ocr_raw_json`.
   - On success, pass all pages to `MineruPopoService`.
5. Normalization:
   - Parse page OCR JSON into internal blocks.
   - Crop visual/table regions from full-page PNG bytes into `BookImage` rows.
   - Try `magic-pdf` if available; otherwise use built-in reconstruction rules.
   - Store normalized list JSON in `MineruResult.result_json`.
6. API display:
   - `GET /api/v1/books/{book_id}/content` converts `MineruResult.result_json` into plain text with image markers.
   - `GET /api/v1/images/{image_id}` returns image/table crops.

`paddle-vl-api` is not invoked. Durable ownership currently resides in `pdf-ocr-service` database rows and filesystem output, but original-file ownership is missing because originals are deleted.

## 8. Existing strengths to preserve

- The active upload route already creates `PdfPage` rows and stores page dimensions, providing a partial page model that can be adapted before introducing a universal `Document` model.
- The service has a useful backward-compatible reader contract: list books, get book metadata, get assembled content, and fetch image/table blocks.
- `MineruPopoService` centralizes OCR-output normalization and visual crop extraction, so future OCR ingestion can be redirected to produce the same normalized result without immediate frontend changes.
- `BookService.delete_book` gives a single deletion path for bookshelf rows and filesystem references.
- Tests already cover API, page OCR serialization, phase-one/phase-two flows, and PDF pipeline pieces; these should be expanded rather than bypassed.
- The target architecture document is explicit that `Book` should not be the universal top-level object, which is a strong planning guardrail.

## 9. Gaps against target architecture

### Document Core

- Current top-level entity is `Bookshelf`, not universal `Document` plus optional `BookProfile`.
- No stable source identity, document versions, canonical revisions, or provenance graph exists.

### Source / Archive

- Original uploads are deleted, contrary to the target immutable-original archive model.
- No object storage key/hash/size/content-type metadata model exists.

### Page model

- `PdfPage` is a useful partial page record, but it is tied to `book_id`, stores full PNG bytes in the DB, and lacks durable asset references, source-file versioning, normalized page dimensions, and page-level provenance.

### OCR ingestion

- OCR compute runs in-process through PaddleOCR-VL, not via a `paddle-vl-api` provider contract.
- OCR observations are stored as one raw JSON text per page rather than normalized `ocr_pages`/`ocr_blocks` records with processing-run provenance.

### Observation layer

- No `processing_runs`, `ocr_runs`, `ocr_blocks`, or artifact records exist.

### Canonical document model

- `MineruResult.result_json` is a useful intermediate, but not a revisioned canonical node/region/relation model.

### Reading functionality

- The frontend currently depends on reader-compatible book/content/image APIs but keeps reading sessions/progress in browser memory only. Backend reading-session/progress records are absent.

### Archive intelligence

- No classifications, metadata candidates, extracted facts, entities, evidence records, or archive queries exist.

### Learning platform

- No notes, summaries, concepts, flashcards, mind maps, question items/attempts, study sessions, or mastery records exist in the inspected backend.

### Operations

- Database schema creation is automatic `create_all`; no migrations are present.
- Large binary data is kept in the database instead of S3/R2-compatible object storage.
- Background processing uses FastAPI `BackgroundTasks`; there is no durable queue or job retry model.

### Security

- CORS allows all origins.
- No authentication/authorization layer was found.
- Uploaded file validation is limited to extension and filename separator checks.

### Testing

- Tests exist in `pdf-ocr-service`, but no cross-repository contract tests protect the exact `speed-reading-trainer` calls and marker parsing. The inspected frontend repository itself does not expose package-based unit/e2e test scripts because no `package.json` was present.
- No migration tests exist because there are no migrations.

### Deployment

- Deployment files support the current monolith. There is no deployment wiring for an external `paddle-vl-api`, object storage, PostgreSQL migrations, or worker process.

## 10. Technical debt and risk

| Priority | Repository | Path/symbol | Why it matters | Likely consequence | Recommended timing |
|---|---|---|---|---|---|
| Critical before further development | `pdf-ocr-service` | `app/routers/ocr.py::upload_file` | Original PDFs are deleted after rendering. | Cannot support archive provenance, reprocessing, legal/evidentiary retention, or target source model. | First production-code PR should add durable original/source metadata while preserving existing API shape. |
| Critical before further development | `pdf-ocr-service` | no migrations; `app/database.py::init_db` | `create_all` hides schema evolution. | Risky production schema changes and hard rollbacks. | Before adding new durable tables. |
| Important soon | `pdf-ocr-service` | `app/models.py::BookImage.image_data`, `PdfPage.page_image_data` | Large binaries in DB do not match target object-storage design. | DB bloat, backup/restore pain, slow queries, difficult retention policy. | After source ownership baseline; add asset adapter before moving data. |
| Important soon | `pdf-ocr-service` | `app/services/page_ocr_service.py::PageOCRService` | OCR compute is directly coupled to local PaddleOCR-VL package. | Hard to move compute to `paddle-vl-api` and hard to isolate failures/resources. | After page/source model is stable. |
| Important soon | `pdf-ocr-service` | `app/api/pdf_endpoints.py` | Defines duplicated/inactive `/api/pdf/*` routes not included in `app.main`. | Confusing contract surface and tests/plans may target dead code. | Document as legacy now; remove only after contract tests. |
| Important soon | `pdf-ocr-service` | `app/routers/images.py` route order | `/{image_id}` is declared before `/page_crop/{book_id}/{page_num}`. | Static path `page_crop` may be captured as `image_id` depending router matching behavior. | Add route test before changing behavior. |
| Can defer | `pdf-ocr-service` | `app/models.py::OCRTask`, `app/routers/ocr.py::TASKS` | Legacy in-memory OCR task flow lacks an active upload creator. | Confusing API docs; state lost on restart. | Defer deletion; first mark/contract-test actual usage. |
| Do not change yet | `pdf-ocr-service` | `GET /api/v1/books/{book_id}/content` marker format | Reader may depend on exact `$%$%$%{image_id}$%$%$%` markers. | Frontend rendering regressions. | Preserve until compatibility adapter or frontend tests exist. |
| Do not change yet | `pdf-ocr-service` | `PdfPage.page_num` | Page numbers are 1-based. | Off-by-one reader/focus bugs. | Preserve in compatibility APIs. |
| Important soon | `speed-reading-trainer` | `bookshelf.js::API_BASE_URL` | Backend URL is hard-coded to the deployed Hugging Face Space. | Local/staging backend testing and rollback are harder; environment-specific configuration requires code edits. | Add a documented runtime/config adapter before changing backend contracts. |

## 11. Cross-repository ownership recommendation

| Capability | Recommended owner | Rationale |
|---|---|---|
| Original uploaded document | `pdf-ocr-service` | Durable source/archive state belongs in backend Document Core. |
| Source-file metadata | `pdf-ocr-service` | Needs hashes, storage keys, versions, provenance. |
| Page records | `pdf-ocr-service` | Stable page identity under Document Core. |
| Page images | `pdf-ocr-service` storage/object-storage layer | Durable derivative assets referenced by page records. |
| Cropped assets | `pdf-ocr-service` | Evidence and rendering assets need provenance and retention. |
| OCR orchestration | `pdf-ocr-service` | Backend should own durable processing runs and call compute providers. |
| OCR compute | `paddle-vl-api` | Target architecture assigns model execution and temporary job artifacts there. |
| OCR result ingestion | `pdf-ocr-service` | Convert temporary compute output into durable observations/canonical content. |
| Canonical nodes | `pdf-ocr-service` | Shared document foundation for read/archive/learn. |
| Reading sessions | Initially `speed-reading-trainer`; later shared backend if multi-device/durable analytics are required | Preserve current behavior until frontend is inspected; transient/session UI may remain frontend-owned. |
| Browser-only UI state | `speed-reading-trainer` | No reason to move ephemeral presentation state. |
| Progress | Split: local UI progress may remain frontend; durable cross-device progress should reference backend document/revision IDs | Avoid moving without clear product requirement. |
| Summaries | `pdf-ocr-service` for generated durable artifacts; frontend for display state | Needs evidence and canonical-node references. |
| Notes | Backend if durable/syncable; frontend only for drafts | Anchored notes need document/page/node references. |
| Quizzes | Backend for question items/attempts if persisted; frontend may render | Evidence-backed generation requires canonical content. |
| Archive facts | `pdf-ocr-service` | Queryable facts require provenance and source evidence. |
| Flashcards | Backend if sync/mastery is required; external integrations optional | Needs source evidence and review state. |
| Mind maps | Backend for generated durable maps; frontend for layout/UI state | Generated content should reference canonical nodes. |
| Learning mastery | Backend | Durable study/progress analytics. |

## 12. Compatibility constraints

Known backend constraints:

- Preserve `/api/v1/upload`, `/api/v1/books`, `/api/v1/books/{book_id}`, `/api/v1/books/{book_id}/content`, `DELETE /api/v1/books/{book_id}`, and `/api/v1/images/{image_id}` until a deliberate frontend compatibility adapter is shipped.
- Preserve response field names such as `book_id`, `book_title`, `file_type`, `status`, `pages_count`, `processed_file_path`, `original_file_path`, and `content` in current APIs.
- Preserve UUID-like `book_id` semantics for current bookshelf APIs.
- Preserve 1-based page numbering in `PdfPage.page_num` and any compatibility page APIs.
- Preserve image/table marker format `$%$%$%{image_id}$%$%$%` in assembled content.
- Preserve current deletion semantics for existing bookshelf rows until retention requirements are deliberately changed.
- Preserve deployment defaults: app on port `7860`, `DATABASE_URL` optional, default SQLite for local/dev, directories `uploads` and `output`.

Frontend constraints now confirmed from `speed-reading-trainer`:

- Hard-coded backend base URL: `https://carsonhhs-pdf-ocr-service.hf.space` in `bookshelf.js::API_BASE_URL`.
- Endpoint paths that must remain stable or be adapted: `/api/v1/books`, `/api/v1/upload`, `/api/v1/books/{book_id}`, `/api/v1/books/{book_id}/content`, `/api/v1/images/{image_id}`, and `DELETE /api/v1/books/{book_id}`.
- Response fields used by the frontend: `books`, `book_id`, `id`, `book_title`, `title`, `name`, `file_type`, `created_at`, `pages_count`, `total_pages`, `author`, `status`, `error_message`, optional `progress`, and `content`.
- The frontend depends on `book_id`/Bookshelf-compatible IDs for selection, polling, content loading, and deletion.
- The frontend depends on DB-backed image IDs only as opaque strings embedded between `$%$%$%` delimiters and then passed to `/api/v1/images/{image_id}`.
- The frontend depends on the exact marker format `$%$%$%{image_id}$%$%$%`.
- The only confirmed persisted browser key is `localStorage['theme']` with value `light` or `dark`; current reading/session/progress state is in memory and is lost on reload.
- The frontend does not consume backend page-numbered APIs today; page mode is generated locally from text units and settings.

## 13. Frontend route/component/API map (`speed-reading-trainer`)

Local shell checkout path attempted: `/workspace/speed-reading-trainer`. The shell clone failed with `CONNECT tunnel failed, response 403`, so the inspected source of truth was the public GitHub web/raw view for `CarsonHHS2023/speed-reading-trainer`.

| Area | Repository path | Symbol / element | Finding |
|---|---|---|---|
| Entrypoint | `speed-reading-trainer/index.html` | static page | Defines the single-page UI: shelf, upload zone, settings, progress, focus/page displays, image controls, modals, and script/style includes. |
| Reader state | `speed-reading-trainer/app.js` | `state` | Holds content, cached content file, units, local pages, current indexes, play/pause flags, speed, line/page/font settings, display/training mode, theme, and image marker state. |
| Book/API client | `speed-reading-trainer/bookshelf.js` | `API_BASE_URL`, `BookShelf` | Hard-codes the backend to the deployed `pdf-ocr-service` URL and implements all backend calls with `fetch`. |
| Upload flow | `speed-reading-trainer/bookshelf.js` | `handleFileUpload`, `handleMultiFileUpload` | Uploads `FormData` field `file` to `/api/v1/upload`, supports single and batch upload, and polls processing PDFs. |
| Document selection | `speed-reading-trainer/bookshelf.js` | `selectBook` | Uses book IDs from the backend to fetch `/api/v1/books/{book_id}/content` and prepares a browser `File` containing `result.content`. |
| Focus mode | `speed-reading-trainer/app.js` | `startFocusLoop`, `getFocusBatchInfo`, `updateFocusDisplay` | Displays batches of tokenized units and advances based on configured speed and effective character count. |
| Page mode | `speed-reading-trainer/app.js` | `generatePages`, `startPageLoop`, `updatePageDisplay` | Creates local pages from text units using line width and max lines; does not consume backend page records. |
| Image/table display | `speed-reading-trainer/app.js` | `CONTENT_DELIMITER`, `fetchImageData`, `pauseForImageMarker` | Parses `$%$%$%image_id$%$%$%`, pauses reading, fetches `/api/v1/images/{image_id}`, and displays an overlay with rotate/flip controls. |
| Persistence | `speed-reading-trainer/app.js` | `initTheme`, `applyTheme` | Persists only `theme` in `localStorage`; no inspected persisted reading sessions/progress/settings. |
| Deployment | `.github/workflows` and static files | GitHub Pages/static hosting | Repository is deployable as static HTML/CSS/JS; no npm build configuration was present in the repository listing. |
