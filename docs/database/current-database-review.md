# Current Database Review

| Field | Value |
|---|---|
| Document Type | Current-State Review |
| Evidence Role | Point-in-time database review |
| Authority Domain | observed database state and review findings at the assessment boundary |
| Applies To | app/models.py, app/database.py, app/main.py, app/routers/ocr.py, app/book_service.py, app/routers/books.py, app/image_service.py, app/routers/images.py, app/services/page_ocr_service.py, OCRTask, Bookshelf, ContentBlock, BookImage, PdfPage, MineruResult |

Task M1-002A is a documentation-only review of the current persistence layer before any Alembic implementation. It records observed behavior from the current application and existing project documents; recommendations are not accepted architecture decisions.

## Confirmed project decision

The project is still at an early stage. The existing database contains test data only, and there is no production database or user data that must be migrated in place. The current Reader and persistence model are also early implementations.

Therefore:

- current table names and columns are evidence about the implementation, not mandatory long-term contracts;
- existing SQLite test data may be discarded;
- no in-place upgrade of existing test databases is required;
- old `create_all()`-created databases are disposable;
- physical schema compatibility is not required;
- API compatibility remains required until deliberately versioned.

## 1. Current temporary persistence model

The service currently uses SQLAlchemy ORM models declared in `app/models.py` with one shared declarative `Base`. Runtime database connectivity is centralized in `app/database.py`: `DATABASE_URL` defaults to `sqlite:///./ocr_tasks.db`, SQLite gets `check_same_thread=False`, non-SQLite URLs are passed directly to `create_engine`, and `SessionLocal` is a process-level `sessionmaker` bound to that engine.

The active FastAPI app includes health, OCR/upload, books, and images routers. On application startup, `app/main.py` calls `init_db()`, which imports the SQLAlchemy `Base` and runs `Base.metadata.create_all(bind=engine)`. There is no Alembic environment, migration version table, or explicit schema upgrade path today.

Persistence is split across:

| Layer | Current responsibility | Observed files |
|---|---|---|
| ORM metadata | Defines current temporary tables, columns, relationships, and enum-backed status for legacy OCR tasks | `app/models.py` |
| Engine/session factory | Selects database URL, creates engine, exposes request-scoped sessions and background-task sessions | `app/database.py`, `app/services/page_ocr_service.py` |
| Upload orchestration | Creates `Bookshelf` rows, renders PDF pages into `PdfPage`, writes TXT files, starts background processing | `app/routers/ocr.py` |
| Bookshelf access | Lists, reads, and deletes books; TXT content is read from `processed_file_path` | `app/book_service.py`, `app/routers/books.py` |
| Image access | Persists and serves cropped image/table blobs by opaque `image_id` | `app/image_service.py`, `app/routers/images.py` |
| OCR post-processing | Updates per-page OCR JSON and stores one MinerU-Popo JSON result per book | `app/services/page_ocr_service.py` |

### Current models

The following tables describe the temporary implementation. They are useful evidence for compatibility and behavior, but they are not automatically the target Atlas foundation schema.

| Model / table | Purpose | Primary key | Relationships | Current usage | Current API exposure | Reader dependency | Long-term status |
|---|---|---|---|---|---|---|---|
| `OCRTask` / `ocr_tasks` | Legacy OCR task record for filename, status, result text, errors, and page count | `id` string UUID default | None | Model exists, but active image OCR task state is also in in-memory `TASKS`; no active query path was found in included routers | Not exposed by current bookshelf reader APIs | None confirmed | Temporary; likely replaceable by future processing/run concepts if needed. |
| `Bookshelf` / `bookshelf` | Current durable book/profile record and compatibility identity for uploads, polling, content loading, and deletion | `id` string UUID default; externally returned as `book_id` | One-to-many `content_blocks`, `images`, `pages`; one-to-one `mineru_result`; cascading delete-orphan | Created by upload paths and `BookService.create_book`; queried by list/detail/content/delete; status tracks processing lifecycle | `POST /api/v1/upload`, `GET /api/v1/books`, `GET /api/v1/books/{book_id}`, `GET /api/v1/books/{book_id}/content`, `DELETE /api/v1/books/{book_id}` | Hard API compatibility dependency through `book_id`, book metadata fields, status, and content routes | Internal table is replaceable; Bookshelf-shaped API responses may need to remain. |
| `ContentBlock` / `content_blocks` | Stores extracted text or image-reference blocks with page number, block order, type, content, bbox, confidence | `id` string UUID default | Many-to-one `Bookshelf` via `book_id` | Written by legacy or inactive PDF paths; active PDF content now reads from `MineruResult`; no active reader route depends on it directly | Not directly exposed by active `/api/v1/books` routes | None confirmed for active Reader | Replaceable/deferable. |
| `BookImage` / `book_images` | Stores cropped image/table PNG bytes and metadata by opaque `image_id` | `id` string UUID default; `image_id` has unique constraint | Many-to-one `Bookshelf` via `book_id` | `ImageService.save_image()` persists visual blocks; `ImageService.get_image()` serves by `image_id`; delete can remove one image | `GET /api/v1/images/{image_id}`, `DELETE /api/v1/images/{image_id}`; image IDs are embedded in book content markers | Hard dependency through marker parsing and image fetch | Physical representation replaceable; `image_id` behavior must remain compatible. |
| `PdfPage` / `pdf_pages` | Stores one PDF page per book, including rendered full-page PNG bytes, dimensions, OCR raw JSON, status, and errors | `id` string UUID default | Many-to-one `Bookshelf` via `book_id` | Created during PDF upload before background OCR; updated with raw page OCR JSON; queried for page crops and post-processing | Indirect through upload, content, and page crop routes | Reader does not depend on page rows directly, but flows depend on successful page processing | Replaceable by `DocumentPage`/asset design if selected. |
| `MineruResult` / `mineru_results` | Stores one normalized post-processed JSON document per book | `id` string UUID default; `book_id` unique | One-to-one `Bookshelf` via `book_id` | Created after all page OCR succeeds; read by book content route for PDF books | `GET /api/v1/books/{book_id}/content` assembles plain text with image markers from `result_json` | Hard behavior dependency through assembled content, not through the table itself | Replaceable by future content representation if API output remains compatible. |

### Current schema creation

`create_all()` is called only by `init_db()` in `app/database.py`. `init_db()` is called from the FastAPI startup event in `app/main.py`, so table creation happens when the application process starts. The current behavior is:

1. Import app and routers.
2. Startup event logs service start.
3. `init_db()` imports `Base` from `app.models`.
4. `Base.metadata.create_all(bind=engine)` creates missing tables only.
5. Startup logs database initialization complete.

Risks:

| Area | Risk |
|---|---|
| Schema drift | `create_all()` does not alter existing tables, remove old columns, create intentional data migrations, or prove the DB matches models. |
| Startup coupling | Schema initialization is tied to every app startup, making production boot both runtime and DDL entrypoint. |
| Disposable databases | Existing SQLite files can be deleted and recreated now, but this behavior is not suitable once real production data exists. |
| Rollback | There is no version history or downgrade plan. |
| Multi-process startup | Multiple instances may attempt DDL at the same time. |
| Reviewability | Model changes are not paired with migration artifacts, so reviewers cannot inspect schema intent. |

No `drop_all()` usage was found.

### Current storage responsibilities

| Category | Stored data | Current location | Notes |
|---|---|---|---|
| Business Data | Bookshelf book identity, title, author, publication date, page count, file type, processing status, errors, timestamps | `bookshelf` | User-visible compatibility surface, not necessarily the long-term root table. |
| Business Data | TXT processed content pointer | `bookshelf.processed_file_path` plus `output/` file | TXT content is not stored in DB; route reads filesystem. |
| Business Data | Visual block identity and retrieval metadata | `book_images.image_id`, format, page, bbox, block type | Reader-visible through markers and image route. |
| Derived Data | Cropped image/table bytes | `book_images.image_data` | Derived from source PDF/page rendering; currently persisted as DB blobs. |
| Derived Data | Full rendered page PNG bytes and dimensions | `pdf_pages.page_image_data`, width, height | Derived from PDF source; used for OCR and optional crop endpoint. |
| Derived Data | Per-page OCR raw JSON | `pdf_pages.ocr_raw_json` | JSON text, not a structured JSON column. |
| Derived Data | MinerU-Popo normalized document JSON | `mineru_results.result_json` | JSON text assembled into reader content. |
| Temporary Data | Uploaded original PDF during render | `uploads/{book_id}_original.pdf` | Deleted after render or failure. |
| Temporary Data | Uploaded original TXT during processing | `uploads/{book_id}_original.txt` | Deleted after processing or failure. |
| Temporary Data | In-memory image OCR task map | `TASKS` in `app/routers/ocr.py` | Process-local only; not durable. |
| Configuration | Database URL | `DATABASE_URL` environment variable, default SQLite file | Not represented in DB. |
| Configuration | Upload/output/layout settings | Pydantic settings from environment / `.env` | Affects paths and OCR behavior, not schema. |
| Background state | Page/book status and error fields | `bookshelf`, `pdf_pages`, `mineru_results` | Background processing uses DB rows as state. |

## 2. Reader/API compatibility constraints

Physical schema compatibility is not required, but Reader-facing behavior remains required until a separate accepted decision changes it.

Active public routes included by `app/main.py` map to persistence as follows:

| Endpoint | Current persistence dependency | Compatibility requirement |
|---|---|---|
| `POST /api/v1/upload` for TXT | `Bookshelf`; `processed_file_path` in `output/` | Preserve upload flow, returned `book_id`, status behavior, and readable content. |
| `POST /api/v1/upload` for PDF | `Bookshelf` -> `PdfPage`; background task later writes `PdfPage.ocr_raw_json`, `BookImage`, `MineruResult` | Preserve upload/polling flow, 1-based page behavior where exposed, and eventual content/image availability. |
| `GET /api/v1/books` | `Bookshelf` | Preserve Bookshelf-shaped list response fields currently consumed by the Reader. |
| `GET /api/v1/books/{book_id}` | `Bookshelf` | Preserve detail lookup by `book_id` and status/error metadata. |
| `GET /api/v1/books/{book_id}/content` for PDF | `Bookshelf` -> `MineruResult` -> `BookImage.image_id` values inside JSON | Preserve assembled plain text and embedded image marker behavior. |
| `GET /api/v1/books/{book_id}/content` for TXT | `Bookshelf` -> filesystem `processed_file_path` | Preserve text content loading behavior. |
| `DELETE /api/v1/books/{book_id}` | `Bookshelf` with cascade to related rows; filesystem paths | Preserve user-visible delete behavior. |
| `GET /api/v1/images/{image_id}` | `BookImage` | Preserve opaque `image_id` lookup and binary image response. |
| `GET /api/v1/images/page_crop/{book_id}/{page_num}` | `PdfPage` | Preserve route behavior if still consumed. |
| `DELETE /api/v1/images/{image_id}` | `BookImage` | Preserve image deletion behavior if still consumed. |

Required compatibility constraints:

| Constraint | Why it matters |
|---|---|
| `/api/v1/upload`, `/api/v1/books`, `/api/v1/books/{book_id}`, `/api/v1/books/{book_id}/content`, `DELETE /api/v1/books/{book_id}`, `/api/v1/images/{image_id}` | Current Reader/frontend contract. |
| Bookshelf-shaped response fields where required | Existing frontend normalizes fields such as `books`, `book_id`, `book_title`, `file_type`, `created_at`, `pages_count`, `status`, and `error_message`. |
| `book_id` behavior | Reader uses it for selection, polling, content loading, image association, and deletion. |
| `image_id` behavior | Reader parses IDs from content markers and fetches images by ID. |
| Exact marker format `$%$%$%{image_id}$%$%$%` | Reader tokenization depends on delimiter semantics. |
| Current upload/list/detail/content/image user flows | These are the compatibility surface even if internals change. |

Inactive duplicate routes in `app/api/pdf_endpoints.py` were inspected as database-related code, but they are not included by `app/main.py` in the default runtime.

## 3. Long-term database constraints

The long-term database should be designed from approved Atlas foundation concepts, not from temporary table preservation. Current SQLAlchemy tables provide evidence about required behavior, identifiers, statuses, and data shapes, but they are not mandatory contracts for the formal schema.

Long-term constraints:

| Constraint | Implication |
|---|---|
| Minimal durable foundation | The first formal baseline should define only the smallest approved foundation, likely centered on `Document` and `SourceFile` unless humans confirm additional concepts. |
| Reproducible creation | New databases should be created by Alembic migrations rather than startup `create_all()`. |
| Disposable current test DBs | Existing SQLite test files may be deleted and recreated; no in-place migration of test data is required. |
| API compatibility over physical compatibility | Application adapters and contract tests should protect Reader behavior instead of preserving obsolete tables. |
| Future evolution | Pages, assets, processing runs, nodes, storage abstraction, and normalized content can be introduced through later migrations when approved. |
| Production readiness boundary | Once real production/user data exists, destructive schema replacement must stop unless paired with accepted backup/migration policy. |

## Current risks and technical debt

| Risk | Current impact under the revised decision |
|---|---|
| Missing migration framework | No versioned schema history, deterministic creation path, or reviewable DDL. |
| `create_all()` limitations | Acceptable only as temporary early-stage bootstrapping; not a foundation for reproducible environments. |
| Binary blob storage | Full pages and cropped visuals can grow the database quickly and complicate future object storage migration. |
| JSON-as-text | OCR and MinerU outputs are stored as text; there is no DB-level JSON validation or queryable structure. |
| Filesystem + DB split | TXT content lives in `output/` while metadata lives in DB; DB backup alone is incomplete. |
| Startup DDL | Runtime startup performs schema creation, which is unsafe as the long-term production upgrade mechanism. |
| Legacy/inactive paths | Duplicate or legacy persistence code may hide compatibility dependencies. |
| Background task state | Background processing is represented by row statuses but not by a durable job/run abstraction. |

## Review conclusion

The current database should be treated as a temporary persistence model for an early Reader implementation. It is valuable for discovering compatibility requirements, but it should not determine the first formal Alembic baseline by default.

The revised strategy should replace **Mirror → Migrate → Extend** with **Design → Baseline → Evolve**:

1. Design the smallest durable Atlas foundation schema.
2. Baseline that approved schema with the first Alembic migration.
3. Evolve through incremental migrations while preserving Reader/API behavior through adapters and tests.
