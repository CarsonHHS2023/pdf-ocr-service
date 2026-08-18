# Initial Modification Plan

Date: 2026-07-11

This is a documentation/planning-only roadmap based on the inspected `pdf-ocr-service` implementation, the public GitHub web/raw inspection of `CarsonHHS2023/speed-reading-trainer`, and the target direction in `docs/architecture/document-intelligence-platform.md`. Shell `git clone` to `/workspace/speed-reading-trainer` still failed with `CONNECT tunnel failed, response 403`, but frontend source files were inspectable through GitHub after the repository was made public.

## Planning principles applied

- Preserve current reader-compatible APIs and behavior.
- Prefer adapters and compatibility layers before rewrites.
- One main capability per PR.
- Every production task includes automated tests or an explicit reason why not.
- Durable document and processing state should converge toward `pdf-ocr-service`.
- Do not introduce archive or learning complexity before Document Core is stable.
- Do not redesign both repositories at once.

## Candidate first vertical-slice evaluation

| Option | Evaluation | Decision |
|---|---|---|
| A. Existing PDF flow → durable Document and SourceFile record → existing reader unchanged | Still the safest first vertical slice after contract tests. The frontend calls `/api/v1/upload`, polls `/api/v1/books/{book_id}`, loads `/content`, and reads `/images/{image_id}`; Document/SourceFile can be added behind those Bookshelf-compatible responses if marker and ID compatibility are preserved. | Choose first after M0 contract tests. |
| B. Existing page rendering → durable Page records and stable page API → frontend compatibility adapter | Valuable but should follow source ownership. `PdfPage` exists, but page assets are currently DB blobs under `book_id`; changing too much first risks reader regressions. | Second foundation slice. |
| C. Existing OCR flow → ProcessingRun → durable OCR page/block ingestion → current display still works | Important, but OCR observations should reference stable source/page identities. | After M1/M2. |
| D. Existing reading range/session → generate five evidence-backed comprehension questions → record answers and score | Premature. It depends on stable canonical content, evidence, and frontend/session inspection. | Defer. |

## Required decisions

1. **First production-code PR:** API contract/regression tests must come first, then the first feature PR should add a compatibility-safe Document/SourceFile baseline in `pdf-ocr-service` while preserving `/api/v1/upload`, `/api/v1/books/*`, `/content`, `/images/{image_id}`, `book_id`, and marker semantics.
2. **Do not touch initially:** `speed-reading-trainer` static UI behavior, hard-coded endpoint paths, `/api/v1/books/{book_id}/content` JSON shape, image-marker format, current reader controls, local page generation, theme persistence, and deployment files except documentation/config planning.
3. **Reusable existing models:** `Bookshelf` as compatibility/book profile surface; `PdfPage` as seed for page records; `BookImage` as seed for assets; `MineruResult` as seed for canonical-builder input; `ContentBlock` for legacy content compatibility.
4. **Incompatible existing models:** `Bookshelf` as universal top-level object; `BookImage.image_data` and `PdfPage.page_image_data` as long-term binary storage; `MineruResult.result_json` as the only canonical model; in-memory `TASKS`/`OCRTask` as durable processing model.
5. **Compatibility API/adapter required:** Yes. The existing Bookshelf-shaped APIs must remain as a compatibility layer over future Document Core because the frontend normalizes `book_id`/`book_title` and uses `book_id` for selection, polling, content loading, and deletion.
6. **Page rendering location:** Keep rendering in `pdf-ocr-service` initially because it already renders pages and owns current `PdfPage` records. Later extract an internal asset-storage adapter; do not move rendering to the frontend.
7. **Original-file storage ownership:** `pdf-ocr-service`, backed eventually by object storage and `source_files` metadata.
8. **Page records/assets ownership:** `pdf-ocr-service`, eventually in `document_pages` and `document_assets` with object keys rather than DB blobs. Frontend does not consume backend page records today, so page-model changes can be additive if `/content` and `/images/{image_id}` remain stable.
9. **Reading sessions ownership:** Hybrid later, frontend-only now. Current sessions/progress are browser memory only; keep transient reading UI state in `speed-reading-trainer`, and add backend durability only when cross-device progress/comprehension analytics are intentionally introduced.
10. **First useful vertical slice after foundation:** Stable page records/assets with current reader unchanged, then OCR processing-run ingestion.
11. **Archive/learning features deferred:** Archive facts, classification queries, summaries, notes, flashcards, mind maps, mastery tracking, and comprehension-question generation are deferred until Document Core, pages, OCR observations, and canonical nodes are stable.
12. **Changes requiring database migration:** New `documents`, `source_files`, `document_pages`/asset references, `processing_runs`, OCR observation tables, canonical revision/node tables, and all archive/learning tables. Because no migration framework exists, adding migrations is a prerequisite production task.
13. **Changes possible without visible frontend changes:** Add internal document/source metadata, retain originals, add storage adapter, introduce processing-run records, build compatibility reads over new tables, and add contract tests for current APIs.
14. **Rollback for first three production tasks:**
    - Task 1 migrations baseline: rollback by not applying migration changes; app remains on `create_all` branch if kept separate.
    - Task 2 document/source baseline: feature-flag new source retention and leave existing `Bookshelf` path authoritative.
    - Task 3 page asset adapter: dual-write assets while continuing to serve from existing DB blobs; rollback by disabling reads from object/file-backed asset store.

## Milestones and tasks

### M0 Baseline and contracts

#### M0-T1 — Add backend/API contract tests for actual frontend calls

- **Repository:** `pdf-ocr-service`
- **Objective:** Protect the actual `speed-reading-trainer` calls: `GET /api/v1/books`, `POST /api/v1/upload`, `GET /api/v1/books/{book_id}`, `GET /api/v1/books/{book_id}/content`, `GET /api/v1/images/{image_id}`, and `DELETE /api/v1/books/{book_id}` response/behavior before internal changes.
- **Current code affected:** `tests/test_api.py`, `app/routers/books.py`, `app/routers/images.py`, `app/routers/ocr.py`.
- **Dependencies:** None.
- **Explicit non-goals:** No API shape changes; no production refactor.
- **Data-model changes:** None.
- **API changes:** None.
- **Compatibility strategy:** Snapshot/assert `books`, `book_id`, `book_title`, `file_type`, `created_at`, `pages_count`, `author`, `status`, `error_message`, optional `progress`, `content`, binary image serving, and `$%$%$%{image_id}$%$%$%` marker format.
- **Automated tests:** New/expanded pytest tests using test DB fixtures.
- **Manual E2E:** Upload TXT and small PDF, list books, fetch content, fetch image if present.
- **Acceptance criteria:** Tests fail on incompatible JSON field/path changes.
- **Risk level:** Low.
- **Estimated size:** S.

#### M0-T2 — Introduce migration tooling without schema changes

- **Repository:** `pdf-ocr-service`
- **Objective:** Add Alembic or equivalent migration infrastructure before new durable tables are added.
- **Current code affected:** `app/database.py`, migration config files, docs.
- **Dependencies:** M0-T1.
- **Explicit non-goals:** No production schema change; no data migration.
- **Data-model changes:** None.
- **API changes:** None.
- **Compatibility strategy:** Keep `init_db()` behavior for local/dev until migrations are adopted operationally.
- **Automated tests:** Verify metadata imports and current test DB setup still works.
- **Manual E2E:** Start app against empty SQLite DB and hit `/api/v1/health`.
- **Acceptance criteria:** Migration command can create an empty revision; current tests continue to pass.
- **Risk level:** Medium.
- **Estimated size:** S.

### M1 Document/source ownership

#### M1-T1 — Add additive Document and SourceFile records behind existing upload API

- **Repository:** `pdf-ocr-service`
- **Objective:** Create durable `Document`/`SourceFile` records for uploads while returning the existing `book_id` response shape.
- **Current code affected:** `app/models.py`, `app/routers/ocr.py::upload_file`, `app/book_service.py`, tests.
- **Dependencies:** M0-T1, M0-T2.
- **Explicit non-goals:** Do not rename `/api/v1/books`; do not remove `Bookshelf`; do not change frontend behavior.
- **Data-model changes:** Add `documents` and `source_files` tables. Link `Bookshelf` to `documents` if needed while preserving `Bookshelf.id` externally.
- **API changes:** None externally; optional internal-only fields are not exposed.
- **Compatibility strategy:** Existing `book_id` remains the compatibility ID; new document ID is internal until a versioned API is planned.
- **Automated tests:** Upload TXT/PDF creates both existing rows and source rows; existing API tests still pass.
- **Manual E2E:** Existing upload/list/content flow unchanged.
- **Acceptance criteria:** Source metadata exists for every new upload and current reader endpoints are unchanged.
- **Risk level:** Medium.
- **Estimated size:** M.

#### M1-T2 — Retain original files through a storage adapter

- **Repository:** `pdf-ocr-service`
- **Objective:** Stop deleting original uploads by default; store originals through an adapter with metadata on `SourceFile`.
- **Current code affected:** `app/routers/ocr.py::upload_file`, `app/config.py`, new storage adapter module, tests.
- **Dependencies:** M1-T1.
- **Explicit non-goals:** Do not introduce S3/R2 in the first step; use local filesystem adapter first.
- **Data-model changes:** Add source-file storage path/key, byte size, hash, content type, retention status if not already in M1-T1.
- **API changes:** None.
- **Compatibility strategy:** Continue rendering from temp/local path; keep `original_file_path` response stable or null as today unless deliberately versioned.
- **Automated tests:** Verify original bytes are retained via adapter and deletion cleans owned storage according to policy.
- **Manual E2E:** Upload a PDF, confirm reader still works, confirm original exists in configured storage.
- **Acceptance criteria:** Reprocessing from original becomes possible without affecting current reader.
- **Risk level:** Medium.
- **Estimated size:** M.

### M2 Page model and page assets

#### M2-T1 — Add compatibility page asset abstraction for current `PdfPage`

- **Repository:** `pdf-ocr-service`
- **Objective:** Hide whether page images come from DB blobs or future object storage.
- **Current code affected:** `app/models.py::PdfPage`, `app/routers/images.py::get_page_crop`, `app/services/mineru_popo_service.py` crop path, new page asset service.
- **Dependencies:** M1-T2.
- **Explicit non-goals:** Do not move existing blobs yet; do not change image URLs.
- **Data-model changes:** Optional additive asset reference fields or side table.
- **API changes:** None.
- **Compatibility strategy:** Read DB blob first; dual-write/read-through adapter later.
- **Automated tests:** Existing crop/image tests plus adapter unit tests.
- **Manual E2E:** Upload PDF with image/table, open content and image endpoints.
- **Acceptance criteria:** Page crop and image marker rendering remain unchanged.
- **Risk level:** Medium.
- **Estimated size:** M.

#### M2-T2 — Stabilize page API internally before frontend use

- **Repository:** `pdf-ocr-service`
- **Objective:** Define an internal page DTO with document/book ID, 1-based page number, dimensions, status, and asset reference.
- **Current code affected:** page service layer, tests.
- **Dependencies:** M2-T1.
- **Explicit non-goals:** Do not expose a new public page API until `speed-reading-trainer` is inspected.
- **Data-model changes:** None or additive only.
- **API changes:** None.
- **Compatibility strategy:** Keep current `/api/v1/images/page_crop/...` path.
- **Automated tests:** DTO mapping tests from current `PdfPage` rows.
- **Manual E2E:** None beyond existing reader flow; this is internal.
- **Acceptance criteria:** All page consumers use the DTO/service, not raw page blob access.
- **Risk level:** Low.
- **Estimated size:** S.

### M3 OCR integration and ingestion

#### M3-T1 — Add ProcessingRun for current in-process OCR

- **Repository:** `pdf-ocr-service`
- **Objective:** Record durable processing lifecycle without changing compute provider yet.
- **Current code affected:** `app/services/page_ocr_service.py::process_book_background`, `app/models.py`, tests.
- **Dependencies:** M1-T1, M2-T1.
- **Explicit non-goals:** Do not call external `paddle-vl-api` yet.
- **Data-model changes:** Add `processing_runs` or `ocr_runs` with status, provider, started/completed timestamps, error fields.
- **API changes:** None.
- **Compatibility strategy:** Existing `Bookshelf.status` remains the public status.
- **Automated tests:** Success/failure run status transitions with mocked OCR.
- **Manual E2E:** Upload PDF and inspect run row/status while current endpoints work.
- **Acceptance criteria:** Each PDF processing attempt has a durable run record.
- **Risk level:** Medium.
- **Estimated size:** M.

#### M3-T2 — Normalize OCR blocks into observation records

- **Repository:** `pdf-ocr-service`
- **Objective:** Store page/block observations alongside raw JSON for provenance.
- **Current code affected:** `app/services/page_ocr_service.py`, `app/services/mineru_popo_service.py`, models/tests.
- **Dependencies:** M3-T1.
- **Explicit non-goals:** Do not remove `PdfPage.ocr_raw_json` or `MineruResult.result_json` yet.
- **Data-model changes:** Add `ocr_pages` and `ocr_blocks` or equivalent.
- **API changes:** None.
- **Compatibility strategy:** Dual-write observations; current content still assembled from `MineruResult`.
- **Automated tests:** Serialization tests assert one observation per normalized block.
- **Manual E2E:** Upload PDF, compare current content output with observations present.
- **Acceptance criteria:** OCR blocks are queryable with page/run provenance.
- **Risk level:** Medium.
- **Estimated size:** M.

### M4 Canonical document representation

#### M4-T1 — Build canonical nodes from existing MinerU-Popo output

- **Repository:** `pdf-ocr-service`
- **Objective:** Convert `MineruResult.result_json` into revisioned canonical nodes while preserving current text assembly.
- **Current code affected:** `app/services/mineru_popo_service.py`, new canonical builder, models/tests.
- **Dependencies:** M3-T2.
- **Explicit non-goals:** Do not redesign MinerU-Popo heuristics; do not expose a new frontend contract.
- **Data-model changes:** Add `document_revisions`, `document_nodes`, and `node_regions`.
- **API changes:** None initially.
- **Compatibility strategy:** Existing `/content` can later be generated from canonical nodes after parity tests.
- **Automated tests:** Golden conversion tests from sample `result_json` to nodes.
- **Manual E2E:** Existing reader content unchanged for representative PDF/TXT.
- **Acceptance criteria:** New canonical records can reproduce current assembled content for supported blocks.
- **Risk level:** Medium.
- **Estimated size:** M.

### M5 Speed-reading compatibility and improvements

#### M5-T1 — Add frontend compatibility tests/config seam

- **Repository:** documentation in `pdf-ocr-service`; possible tests in both repos after access.
- **Objective:** Add lightweight browser/E2E or static contract tests for the inspected static frontend behavior and replace the hard-coded backend URL with a safe runtime/config seam in a separate frontend PR.
- **Current code affected:** docs and tests only initially.
- **Dependencies:** M0-T1 and access to the public `speed-reading-trainer` repository.
- **Explicit non-goals:** No frontend behavior changes.
- **Data-model changes:** None.
- **API changes:** None.
- **Compatibility strategy:** Treat current frontend behavior as contract until covered by tests.
- **Automated tests:** Add contract tests where feasible after inspection.
- **Manual E2E:** Run frontend against local backend and complete upload/read/resume flows.
- **Acceptance criteria:** No frontend production work proceeds without documented contracts.
- **Risk level:** Low for docs; high if skipped.
- **Estimated size:** S.

### M6+ Deferred archive and learning milestones

- Notes, summaries, comprehension questions, archive classification, extracted facts, flashcards, mind maps, and learning mastery should wait until canonical nodes and evidence links exist.
- The first learning-adjacent vertical slice should be a tiny evidence-backed question-generation prototype only after M4 and `speed-reading-trainer` session/progress contracts are inspected.

## Recommended first five production tasks

1. M0-T1 — Add backend/API contract tests for actual `speed-reading-trainer` calls.
2. M0-T2 — Introduce migration tooling without schema changes.
3. M1-T1 — Add additive Document and SourceFile records behind existing upload API.
4. M1-T2 — Retain original files through a storage adapter.
5. M2-T1 — Add compatibility page asset abstraction for current `PdfPage`.

## Behaviors to preserve

- Existing upload/list/detail/content/image endpoint paths and field names consumed by `bookshelf.js`.
- Image/table marker format `$%$%$%{image_id}$%$%$%`.
- 1-based page numbering.
- Current PDF rendering at upload time until protected by tests.
- Current TXT upload behavior and processed TXT output.
- Existing reader behavior in `speed-reading-trainer`: focus/page modes, local tokenization/page generation, image overlay pause/continue flow, progress slider, and theme key.

## Deferred work

- Public Document API redesign.
- Moving OCR compute to `paddle-vl-api`.
- Replacing DB blobs with S3/R2 object storage.
- Archive intelligence and fact extraction.
- Notes, summaries, quizzes, flashcards, mind maps, and mastery tracking.
- Frontend session/progress migration.

## Frontend-informed compatibility decisions

1. **Currently used backend endpoints:** `GET /api/v1/books`, `POST /api/v1/upload`, `GET /api/v1/books/{book_id}`, `GET /api/v1/books/{book_id}/content`, `DELETE /api/v1/books/{book_id}`, and `GET /api/v1/images/{image_id}`.
2. **Relied-upon response fields/formats:** `books`, `book_id`, `id`, `book_title`, `title`, `name`, `file_type`, `created_at`, `pages_count`, `total_pages`, `author`, `status`, `error_message`, optional `progress`, `content`, binary image responses or JSON `image_data`, and `$%$%$%{image_id}$%$%$%` markers.
3. **Frontend dependencies:** yes for Bookshelf-compatible IDs/`book_id`, DB-backed image IDs as opaque strings, marker format, and specific route shapes; no direct dependency on backend 1-based page numbering today because page mode is local. The only confirmed localStorage key is `theme`.
4. **Invisible Document/SourceFile addition:** yes, if existing Bookshelf-shaped API responses continue to be emitted and `book_id` remains stable or is mapped.
5. **Translation layer:** required. New Document models should not leak into current `/api/v1/books/*` responses until the frontend has an adapter.
6. **First PR ordering:** contract tests first; Document/SourceFile baseline second.
7. **Reader regressions requiring tests:** upload and polling, book list normalization, content fetch, marker tokenization, image fetch/display, focus mode timing, page mode local pagination, progress slider seeking, delete flow, and theme persistence.
8. **Reading-session durability:** frontend-only today; hybrid later only for deliberate cross-device progress/comprehension analytics.
9. **First no-regression vertical slice:** contract tests followed by additive Document/SourceFile records and original retention behind existing API responses.
10. **Reordered tasks:** M0-T1 becomes mandatory before any schema work; frontend config/test seam moves earlier than any visible frontend integration with Document APIs.
