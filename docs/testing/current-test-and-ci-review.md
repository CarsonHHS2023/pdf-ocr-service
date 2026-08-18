# M1-001A Current Test and CI Review

| Field | Value |
|---|---|
| Document Type | Current-State Review |
| Evidence Role | Point-in-time test and CI evidence review |
| Authority Domain | Test and CI findings at the documented inspection boundary |

Status: Documentation-only review. No tests, CI files, dependencies, production code, OCR behavior, schemas, or Alembic files were changed.

## Evidence inspected

Workflow and test-support files inspected:

- `.github/workflows/backend-tests.yml`
- `pytest.ini`
- `requirements.txt`
- `requirements-test.txt`
- `TESTING.md`
- `TEST_QUICK_START.md`
- `run_tests.sh`
- `run_light_tests.sh`

Minimum test files inspected:

- `tests/conftest.py`
- `tests/test_api.py`
- `tests/test_heavy.py`
- `tests/test_page_ocr_service.py`
- `tests/test_pdf_pipeline.py`
- `tests/test_phase1.py`
- `tests/test_phase2_integration.py`
- `tests/test_phase2_light.py`

Application modules imported, patched, or directly relevant to the tests were also inspected, including:

- `app/main.py`
- `app/database.py`
- `app/models.py`
- `app/routers/ocr.py`
- `app/routers/books.py`
- `app/routers/images.py`
- `app/book_service.py`
- `app/image_service.py`
- `app/ocr_service.py`
- `app/pdf_service.py`
- `app/paddleocr_vl_service.py`
- `app/enhanced_pdf_service.py`
- `app/services/database_service.py`
- `app/services/page_ocr_service.py`
- `app/services/pdf_processing_service.py`
- `app/services/mineru_popo_service.py`

Search terms used included `pytest.mark`, `slow`, `unit`, `PaddleOCR`, `PaddleOCRVL`, `MinerU`, `magic_pdf`, `model`, `download`, `network`, `GPU`, `CUDA`, `BackgroundTasks`, `create_all`, `original_file_path`, `image marker`, `$%$%$%`, `/api/v1/`, `mock`, `patch`, `skip`, and `xfail`.

## Classification categories

| Category | Meaning in this review |
| --- | --- |
| `KEEP_REQUIRED` | Recommended for future required PR CI once dependencies and workflow are made deterministic. |
| `KEEP_OPTIONAL` | Useful but not required for every PR. |
| `REWRITE_WITH_FAKE_PROVIDER` | Behavior remains important, but current tests are too coupled to local OCR implementation details and should move behind a fake provider seam. |
| `MOVE_TO_PADDLE_VL_API` | Better validated against the future remote OCR compute service, normally in manual/trusted workflows. |
| `LEGACY_MANUAL` | Retain for manually validating old local OCR/MinerU behavior while it remains useful. |
| `RETIRE_AFTER_REPLACEMENT` | Do not remove now; retire only after replacement tests or architecture changes are accepted. |
| `PENDING_DECISION` | Evidence is incomplete or the classification depends on a human architecture decision. |

## Test file classification table

| File | Purpose | Test level | Test names / cited assertions | Modules and symbols exercised | OCR/model mode | Network/model/GPU requirements | Runtime category | Standard GitHub CPU runner? | Protects current public contract? | Assumes old local OCR architecture? | Conflicts with Atlas target architecture? | Recommendation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `tests/test_api.py` | Reader-facing upload, listing, detail, content, deletion, failed-content behavior, and route registration. | API contract / integration with in-memory SQLite. | `test_txt_upload_returns_200`, `test_txt_upload_status_completed`, `test_txt_upload_has_book_id`, `test_txt_upload_original_file_path_null_on_success`, `test_pdf_upload_returns_processing`, `test_pdf_upload_no_original_file_retained`, `test_pdf_upload_invalid_pdf_fails`, `test_empty_list`, `test_list_after_upload`, `test_get_existing_book`, `test_content_matches_uploaded_text`, `test_delete_existing_book`, `test_structure_route_registered_once`, `test_result_route_registered_once`. | `app.main.app`, `app.database.get_db`, `app.models.Base`, `app.routers.ocr.upload_file`, `app.routers.ocr.process_book_background`, `app.routers.books.list_books`, `get_book_detail`, `get_book_content`, `delete_book`. | TXT path uses real `get_ocr_service().process_txt`; PDF background task is patched with `patch("app.routers.ocr.process_book_background")`; rendering still touches PyMuPDF for valid PDFs. | No GPU. No network. Requires installed app dependencies, including FastAPI, SQLAlchemy, PyMuPDF for PDF tests, and importable OCR modules because app imports them. | Fast to medium. | Yes after lightweight dependency split; today CI installs full OCR stack. | Yes: covers `/api/v1/upload`, `/api/v1/books`, `/api/v1/books/{book_id}`, `/api/v1/books/{book_id}/content`, deletion, `book_id`, statuses, TXT behavior, Bookshelf-shaped responses. | Partially: asserts deletion/non-retention of `original_file_path` and uses `create_all` setup. | Yes for original PDF retention if Atlas intends to retain source files; `create_all` conflicts with Alembic target. | `KEEP_REQUIRED` for stable Reader API cases; `REWRITE_WITH_FAKE_PROVIDER` for PDF processing orchestration; `RETIRE_AFTER_REPLACEMENT` for original-file deletion assertions after accepted replacement. |
| `tests/test_pdf_pipeline.py` | Layout-to-TXT formatting, image marker creation, upload content behavior, fallback engine diagnostics, preprocessing, cover-page/header/footer logic. | Unit and mocked integration, very broad. | `test_marker_format_exactly`, `test_pdf_upload_content_includes_image_markers`, `test_pdf_upload_passes_book_id_and_db_to_extraction`, `test_legacy_pdf_upload_endpoint_removed`, `test_fallback_engine_logs_reason`, `test_paddlex_selected_when_import_succeeds`, `test_cover_page_produces_image_marker`, `test_repeated_header_block_filtered`, and many formatting tests. | `app.pdf_service.PDFService.extract_pdf_content`, `_get_enhanced_pdf_service`, `_get_ocr_service`, `get_image_service`, `app.enhanced_pdf_service.EnhancedPDFService`, API upload/content path. | Mostly mocked PaddleX/OCR with `patch`; some tests import OpenCV/Numpy/PyMuPDF-dependent modules. | No network/GPU in mocked path, but imports require local OCR-adjacent dependencies from `requirements.txt`. | Medium; 92 tests. | Potentially, if dependencies are split and tests are marker-organized. | Yes for `$%$%$%{image_id}$%$%$%` markers, content assembly, `/api/v1/upload`, and removed legacy endpoint behavior. | Yes: deeply tied to `PDFService` local PaddleOCR-VL/PaddleX fallback architecture. | Yes where it asserts local fallback engine behavior, PaddleX selection, in-process image extraction, and local layout/OCR pipeline internals. | `REWRITE_WITH_FAKE_PROVIDER` for orchestration and marker contracts; `KEEP_REQUIRED` for pure formatting helpers after split; `RETIRE_AFTER_REPLACEMENT` for local fallback/PaddleX-specific assertions after replacements exist. |
| `tests/test_page_ocr_service.py` | Per-page PaddleOCR-VL result serialization and MinerU-Popo/PaddleOCR-VL bbox parsing edge cases. | Unit tests with monkeypatched dependencies. | `test_process_page_bytes_reads_dict_result`, `test_serializes_paddleocr_block_objects_for_json_storage`, `test_mineru_popo_service_parses_quad_bbox_lists`, `test_paddleocr_vl_service_parses_quad_bbox_arrays`, `test_extract_pdf_content_reads_dict_result`. | `app.services.page_ocr_service.PageOCRService`, `process_page_bytes`, `serialize_paddle_result`, `app.services.mineru_popo_service.MineruPopoService`, `app.paddleocr_vl_service.PaddleOCRVLPDFService`. | Mocked/monkeypatched PaddleOCR-VL and cv2; no real model invocation in the tested paths. | No network/GPU if imports are satisfied. | Fast. | Yes after dependency split, but today imports production PaddleOCR-VL wrappers. | Indirectly protects JSON/storage compatibility for OCR results; less directly reader-facing. | Yes: centered on in-process `PageOCRService` and local PaddleOCR-VL wrappers. | Potentially: future provider may return a different remote contract, but bbox and serialization compatibility may remain valuable. | `REWRITE_WITH_FAKE_PROVIDER`; `KEEP_OPTIONAL` for serialization helpers until remote provider contract is accepted; `PENDING_DECISION` for MinerU-Popo compatibility scope. |
| `tests/test_phase2_light.py` | Database service and image/content persistence behavior using mocks/in-memory database. | Unit/light integration. | `test_generate_image_id_hash_based`, `test_create_book`, `test_save_content_block`, `test_save_book_image`, `test_get_book_content_blocks_by_page`, `test_get_image_by_id`, `test_transaction_rollback_on_error`, `test_multiple_books_isolation`. | `app.services.database_service.DatabaseService`, `app.models.Bookshelf`, `ContentBlock`, `BookImage`, `Base`. | No OCR. | No network/GPU/model. Requires SQLAlchemy only. | Fast. | Yes after dependency split. | Partially protects persistence semantics used by Reader image/content flows, not all API contracts. | Uses `Base.metadata.create_all` in service setup and tests. | Yes for create_all-based schema setup once Alembic is introduced. | `KEEP_REQUIRED` for persistence contracts initially; later add migration-backed setup and mark create_all dependency for replacement. |
| `tests/test_phase1.py` | Image preprocessing and enhanced PDF service local layout pipeline behavior. | Unit plus local PDF/layout integration. | `test_grayscale_conversion`, `test_denoise`, `test_skew_detection`, `test_service_initialization`, `test_pdf_loading`, `test_fallback_layout_analysis`, `test_process_pdf_single_page`, `test_phase1_complete_workflow`. | `app.image_preprocessing`, `app.enhanced_pdf_service.EnhancedPDFService`. | Real local preprocessing; local PDF rendering; layout fallback can touch local pipeline behavior. | No network by intent, but local model dependencies may initialize or be required for non-fallback paths; no GPU guaranteed. | Medium to slow depending samples/environment. | Not reliably for every PR. | No direct Reader API contract. | Yes: old local layout/PaddleX architecture. | Yes where local layout pipeline is expected to remain part of default processing. | `LEGACY_MANUAL`; extract pure image preprocessing unit tests to `KEEP_REQUIRED` later if dependency-light. |
| `tests/test_phase2_integration.py` | Heavy real-library phase 2 PDF-to-database workflow. | Heavy integration/manual acceptance. | `test_service_initialization`, `test_process_text_block_real`, `test_process_image_block_real`, `test_process_pdf_file_with_valid_pdf`, `test_pdf_to_database_complete_workflow`, `test_page_error_recovery`, `test_image_hash_uniqueness_real`. | `app.services.pdf_processing_service.PDFProcessingService`, `app.services.database_service.DatabaseService`, real file fixtures. | Real libraries; no broad mocking. | Requires local PDF/OCR/image libraries and sample files; may be slow; no network by design but model availability is environment-dependent. | Slow. | No for required PR CI. | Partially protects image persistence and orchestration, but not Reader endpoints. | Yes: local PDF processing service. | Yes for target remote OCR provider. | `LEGACY_MANUAL`; `REWRITE_WITH_FAKE_PROVIDER` for orchestration coverage. |
| `tests/test_heavy.py` | Heavy API acceptance using real files from `test_samples`, with TXT and PDF upload lifecycle. | Heavy API integration/manual. | `test_txt_upload_succeeds`, `test_txt_content_readable`, `test_txt_can_be_deleted`, `test_pdf_upload`, `test_pdf_completed_content_readable`, `test_pdf_failed_book_deletable`; asserts `original_file_path is None` on success and handles failed PDF original path. | `app.main.app`, `app.models.Base`, `/api/v1/upload`, `/api/v1/books`, `/api/v1/books/{book_id}/content`, `DELETE /api/v1/books/{book_id}`. | No mocks; real processing path. | Explicitly documented as slow and requiring GPU-capable hardware with PaddleOCR installed; sample files required. | Slow/heavy. | No. | Yes for API lifecycle, but duplicates lighter contract tests. | Yes: real local PaddleOCR/PDF processing. | Yes: local model and original-file deletion behavior. | `LEGACY_MANUAL`; keep TXT-only lifecycle coverage as `KEEP_REQUIRED` through `tests/test_api.py`; move remote OCR smoke to paddle-vl-api workflow later. |
| `tests/conftest.py` | Shared test DB/client/sample PDF fixtures. | Test infrastructure. | Fixtures `test_db`, `client`, `sample_pdf_path`. | `app.database.get_db`, `app.models.Base`, `app.main.app`. | No OCR directly. | No network/GPU. | Fast. | Useful but implementation creates schema with `Base.metadata.create_all`. | Supports API contract tests. | Yes: create_all fixture model. | Yes after Alembic migration framework exists. | `KEEP_REQUIRED` short term; `RETIRE_AFTER_REPLACEMENT` for create_all setup after migration-backed test DB exists. |

## Reader-facing API coverage

| Endpoint | Current coverage | Gaps / notes | Recommendation |
| --- | --- | --- | --- |
| `POST /api/v1/upload` | `tests/test_api.py` covers TXT success, invalid extensions, PDF processing response, PDF invalid failure, `book_id`, `file_type`, `status`, processed path, and original-file deletion. `tests/test_heavy.py` covers real TXT/PDF lifecycle. `tests/test_pdf_pipeline.py` covers upload/content integration with mocked extraction. | Current PDF tests are mixed: some patch background processing; valid PDF upload still renders pages locally before scheduling background OCR. | Required PR CI should keep TXT and fake-provider PDF contract cases; real local PDF cases should not block PRs. |
| `GET /api/v1/books` | `tests/test_api.py` covers empty list, list after upload, multiple books. `tests/test_heavy.py` duplicates lifecycle list coverage. | Should explicitly lock Bookshelf response shape for status/error fields during future Document Core changes. | `KEEP_REQUIRED` and strengthen contract tests later. |
| `GET /api/v1/books/{book_id}` | `tests/test_api.py` covers existing and missing books; `tests/test_heavy.py` covers TXT/PDF saved book lookup. | Detail response currently exposes `original_file_path`; future retention/source-file work needs compatibility decision. | `KEEP_REQUIRED`; mark original-file assertions pending future source-file decision. |
| `GET /api/v1/books/{book_id}/content` | `tests/test_api.py` covers TXT content, missing book, failed book returns 404. `tests/test_pdf_pipeline.py` covers PDF content with image markers. | Needs deterministic fake-provider PDF content contract after provider seam exists. | `KEEP_REQUIRED` for TXT/current status behavior; `REWRITE_WITH_FAKE_PROVIDER` for PDF content. |
| `DELETE /api/v1/books/{book_id}` | `tests/test_api.py` covers existing, nonexistent, list removal, failed book deletion. `tests/test_heavy.py` duplicates deletion lifecycle. | Deletion semantics for retained source files/assets need future decision. | `KEEP_REQUIRED` for public response and removal semantics; storage cleanup behavior is `PENDING_DECISION`. |
| `GET /api/v1/images/{image_id}` | `tests/test_phase2_light.py` covers image retrieval at service layer. Existing inspected API tests do not directly cover successful HTTP image streaming, only image-related lifecycle in pipeline tests and nonexistent endpoint coverage appears in older docs. | Add explicit API-level success/404 content-type tests with stored fake `BookImage`. | `KEEP_REQUIRED` after adding deterministic API contract tests. |

## Current protocol compatibility findings

- `book_id`: covered by upload/detail/list/content/delete tests in `tests/test_api.py` and heavy tests. Keep as a required Reader contract.
- `image_id`: covered mostly at service/pipeline level through image marker and image service tests. API-level `GET /api/v1/images/{image_id}` needs stronger required coverage.
- Bookshelf-shaped responses: current list/detail tests exercise `BookSchema`, `BookDetailSchema`, and status fields through API responses. Future Document Core work should preserve this compatibility layer or explicitly version it.
- `$%$%$%{image_id}$%$%$%` markers: strongly covered in `tests/test_pdf_pipeline.py` and assembly code in `app.routers.books._assemble_txt_from_mineru`. Keep the marker contract required, but decouple it from local OCR/PaddleX internals.
- TXT content behavior: covered in `tests/test_api.py`; should remain required because it is deterministic and cheap.
- PDF processing statuses: `tests/test_api.py` covers `processing` and `failed`; fake-provider integration tests should eventually cover `completed` without real model inference.

## Architecture-conflicting assertions and assumptions

Do not change these yet; these are findings only.

| Conflict | Evidence | Tests affected | Recommended disposition |
| --- | --- | --- | --- |
| Deletion/non-retention of original uploaded PDFs | `app.routers.ocr.upload_file` deletes TXT/PDF originals and returns `original_file_path=None`; `app.models.Bookshelf.original_file_path` is noted as retained for old-data compatibility. | `tests/test_api.py::test_txt_upload_original_file_path_null_on_success`, `test_pdf_upload_no_original_file_retained`; `tests/test_heavy.py::test_txt_upload_succeeds`, `test_pdf_upload`. | `RETIRE_AFTER_REPLACEMENT` after M1 original PDF retention/source-file decisions and replacement tests are accepted. |
| In-process PaddleOCR-VL execution | `app.services.page_ocr_service.PageOCRService` and `app.paddleocr_vl_service.PaddleOCRVLPDFService` instantiate `PaddleOCRVL` locally. | `tests/test_page_ocr_service.py`; `tests/test_phase2_integration.py`; portions of `tests/test_pdf_pipeline.py`. | `REWRITE_WITH_FAKE_PROVIDER`; retain local coverage as `LEGACY_MANUAL`. |
| Local model availability and PaddleX/MinerU integration | `app.ocr_service`, `app.enhanced_pdf_service`, and `app.services.mineru_popo_service` import local model stacks and optionally `magic_pdf`. | `tests/test_phase1.py`, `tests/test_phase2_integration.py`, `tests/test_heavy.py`, fallback/PaddleX tests in `tests/test_pdf_pipeline.py`. | Keep manual until remote provider contract replaces it; do not require in PR CI. |
| Direct MinerU integration | `app.services.page_ocr_service.process_book_background` runs MinerU-Popo after page OCR; `app.routers.books.get_book_content` reads `MineruResult`. | `tests/test_page_ocr_service.py`, PDF content assembly tests. | `PENDING_DECISION` whether MinerU-Popo remains in pdf-ocr-service after remote OCR integration. |
| `create_all` schema setup | `app.database.init_db`, `app.services.database_service.DatabaseService`, `tests/conftest.py`, `tests/test_api.py`, `tests/test_heavy.py`, and `tests/test_pdf_pipeline.py` create metadata directly. | Many test fixtures and services. | Accept short-term only; replace with Alembic-backed test DB after migrations exist. |

## Current workflow quality audit

| Area | Finding | Recommendation |
| --- | --- | --- |
| Trigger correctness | `.github/workflows/backend-tests.yml` defines `workflow_dispatch` twice. Duplicate YAML keys make behavior ambiguous and should be fixed before depending on the workflow. | Fix syntax in first implementation PR. |
| Branch triggers | Push and PR run on `main` and `develop`. Heavy tests also run on main pushes via job `if`. | Avoid heavyweight local OCR on normal main pushes unless explicitly approved. |
| Python version matrix | Light tests run on 3.9, 3.10, 3.11. The project has no documented multi-version support target in this review. | Use a single supported CI version initially, or document the support matrix before keeping all three. |
| Dependency installation cost | Light and heavy jobs install `requirements.txt`, which includes `paddlepaddle`, `paddleocr`, and `paddlex[ocr]`, plus test requirements. | Split runtime/test/OCR dependencies before making CI required. |
| Cache usage | No pip cache configured. | Add setup-python pip caching later. |
| Light/heavy separation | There are separate jobs, but light still installs heavy dependencies; heavy runs on main pushes. | Separate dependency sets and triggers. |
| Timeout controls | No job timeout-minutes. | Add timeouts per layer. |
| Concurrency cancellation | No `concurrency` group. | Add PR concurrency cancellation later. |
| Permissions | No explicit `permissions`. | Add least-privilege `contents: read` for tests. |
| Secret handling / fork safety | No secrets in workflow; Codecov upload uses no token and `fail_ci_if_error: false`. Heavy workflow does not call external secrets. | Future paddle-vl-api smoke must be trusted/manual only and secret-gated. |
| Artifact upload | No test artifacts are uploaded. Coverage XML is sent to Codecov only. | Optional: upload coverage/test logs for failed runs. |
| Coverage behavior | Coverage is generated in a second pytest invocation, duplicating test runtime. Codecov failures do not fail CI. | Run tests once with coverage if coverage is needed; do not duplicate by default. |
| Lint failure behavior | `flake8` uses `--exit-zero`; `black --check` and `isort --check-only` are followed by `|| true`. Lint cannot fail CI. | Make lint checks real in a future PR. |
| Action versions | Uses `actions/checkout@v3`, `actions/setup-python@v4`, `codecov/codecov-action@v3`. | Upgrade action versions in a workflow-fix PR. |
| Main pushes and heavy OCR | Heavy job runs for `github.ref == 'refs/heads/main'`, which can run local OCR/model tests unnecessarily. | Move legacy local OCR to manual/trusted optional workflow or keep manual marker command only. |

## Test dependency design

`requirements-test.txt` is lightweight by itself (`pytest`, `pytest-asyncio`, `httpx`, `pytest-cov`), but the current workflow and docs install `requirements.txt` first. That forces local OCR/model dependencies into even light jobs: `paddlepaddle`, `paddleocr`, `paddlex[ocr]`, OpenCV, PyMuPDF, and related libraries.

Codex Recommendation — Human Confirmation Required:

- Consider a future split such as:
  - `requirements-core.txt`: FastAPI, SQLAlchemy, Pydantic/settings, python-multipart, requests/aiohttp if still core.
  - `requirements-test.txt`: pytest, pytest-cov, httpx, lint tools if not in dev.
  - `requirements-ocr-local.txt`: `paddlepaddle`, `paddleocr`, `paddlex[ocr]`, OpenCV/PyMuPDF if only needed for local OCR.
  - `requirements-hf.txt`: Hugging Face deployment runtime, excluding local OCR if remote OCR becomes default.
  - `requirements-dev.txt`: local developer convenience tools.
- These names are examples only; no dependency changes were made in this review.

## Tests recommended for required CI

Initial required set after workflow/dependency cleanup:

- `tests/test_api.py` Reader contract tests that do not require real PDF OCR/model inference.
- `tests/test_phase2_light.py` database/image/content service tests, with an explicit note that `create_all` setup is temporary until Alembic exists.
- Pure formatting/marker tests from `tests/test_pdf_pipeline.py` after isolating them from local PaddleX/OCR imports.
- Collection/import smoke for app routers and schemas.
- Real lint/format/import-order checks once configured to fail CI.

## Tests recommended for mocked integration

- PDF upload-to-content orchestration currently spread across `tests/test_api.py` and `tests/test_pdf_pipeline.py` should be rewritten against a fake OCR provider/provider seam.
- Marker/content assembly should use deterministic fake provider outputs with text, title, toc, image, and table blocks.
- Status transitions should be verified without `PaddleOCRVL`, PaddleX, MinerU model downloads, GPU, or external `paddle-vl-api` calls.

## Tests recommended for external/manual execution

- `tests/test_heavy.py`
- `tests/test_phase2_integration.py`
- Local PaddleX/PaddleOCR/PaddleOCR-VL behavior in `tests/test_phase1.py` and `tests/test_pdf_pipeline.py`
- Future paddle-vl-api smoke tests should be a separate trusted/manual workflow, not part of fork PR CI.

## Pending human decisions

- Whether the Reader API must continue exposing `original_file_path` and what value it should have after M1 original PDF retention.
- Whether MinerU-Popo remains inside `pdf-ocr-service` or moves behind the remote OCR/provider boundary.
- Which Python versions are officially supported in CI.
- Whether to keep the existing workflow and make it manual, or add a new minimal required workflow while preserving the legacy workflow.
- Exact dependency file names and deployment dependency policy.
- Whether the M1 task numbering should change or this review should remain an unnumbered prerequisite/subtask.
