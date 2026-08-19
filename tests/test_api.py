"""Light API tests: upload and book management endpoints.

These tests use an in-memory SQLite database. TXT and PDF canonical background
runners are mocked at the API boundary so the suite remains provider-independent;
focused Structured Content tests cover deterministic TXT decoding/recovery/runtime.
"""

from __future__ import annotations

from datetime import datetime
import io
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, Document
from app.processing.ingestion_dispatch_model import IngestionDispatch
from app.routers import ocr as ocr_router

# ---------------------------------------------------------------------------
# Test database fixture: in-memory SQLite, one DB per test
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite:///:memory:"


def _make_test_db():
    engine = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return TestingSessionLocal


@pytest.fixture()
def client(monkeypatch):
    """TestClient with a fresh in-memory DB for every test."""
    TestingSessionLocal = _make_test_db()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # In the durable Staging overlay, BackgroundTasks kicks the real dispatch
    # runner rather than importing a worker directly from this router. Keep that
    # runner on the same in-memory database as the request, while deliberately
    # suppressing terminal reconciliation because these API tests mock the
    # worker as an immediate return and assert the upload response remains
    # ``processing``. Focused dispatch tests cover real terminal/fencing logic.
    if hasattr(ocr_router, "run_ingestion_dispatch"):
        from app.processing import ingestion_dispatch as dispatch_module

        durable_runner = ocr_router.run_ingestion_dispatch

        async def run_test_dispatch(dispatch_id: str):
            return await durable_runner(
                dispatch_id,
                session_factory=TestingSessionLocal,
            )

        monkeypatch.setattr(ocr_router, "run_ingestion_dispatch", run_test_dispatch)
        monkeypatch.setattr(
            dispatch_module,
            "finalize_dispatch_from_document",
            lambda _claim, *, session_factory: True,
        )

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c._atlas_testing_session_factory = TestingSessionLocal
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _txt_file(content: str = "这是测试文本。\n第二行内容。", name: str = "test.txt"):
    return ("file", (name, io.BytesIO(content.encode("utf-8")), "text/plain"))


def _txt_file_bytes(content: bytes, name: str = "test.txt"):
    return ("file", (name, io.BytesIO(content), "text/plain"))


def _txt_runner_target() -> str:
    if hasattr(ocr_router, "process_txt_document_background"):
        return "app.routers.ocr.process_txt_document_background"
    return "app.processing.txt.ingestion.process_txt_document_background"


def _pdf_runner_target() -> str:
    if hasattr(ocr_router, "process_pdf_document_background"):
        return "app.routers.ocr.process_pdf_document_background"
    return "app.processing.pdf_ingestion.process_pdf_document_background"


def _upload_txt(client, content: str = "这是测试文本。\n第二行内容。", name: str = "test.txt"):
    with patch(_txt_runner_target()):
        return client.post("/api/v1/upload", files=[_txt_file(content, name)])


def _upload_txt_bytes(client, content: bytes, name: str = "test.txt"):
    with patch(_txt_runner_target()):
        return client.post("/api/v1/upload", files=[_txt_file_bytes(content, name)])


def _mark_book_terminal_for_delete(client, book_id: str) -> None:
    """Finish mocked processing so delete-success tests reflect production semantics."""
    SessionLocal = client._atlas_testing_session_factory
    db = SessionLocal()
    try:
        document = db.get(Document, book_id)
        assert document is not None
        document.status = "completed"
        dispatch = db.query(IngestionDispatch).filter_by(document_id=book_id).one_or_none()
        if dispatch is not None:
            dispatch.status = "succeeded"
            dispatch.claim_token = None
            dispatch.claim_expires_at = None
            dispatch.error_message = None
            dispatch.finished_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /api/v1/upload – TXT file
# ---------------------------------------------------------------------------

class TestTXTUpload:
    """Tests for retained-source TXT canonical ingestion queueing."""

    def test_txt_upload_returns_200(self, client):
        resp = _upload_txt(client)
        assert resp.status_code == 200, resp.text

    def test_txt_upload_status_processing(self, client):
        """LLM/canonical processing runs outside the upload request."""
        resp = _upload_txt(client, content="Hello, 世界!")
        assert resp.json()["status"] == "processing"

    def test_txt_upload_file_type(self, client):
        resp = _upload_txt(client)
        assert resp.json()["file_type"] == "txt"

    def test_txt_upload_book_title_from_filename(self, client):
        resp = _upload_txt(client, name="我的书.txt")
        assert resp.json()["book_title"] == "我的书"

    def test_txt_upload_has_book_id(self, client):
        book_id = _upload_txt(client).json().get("book_id", "")
        assert len(book_id) > 0

    def test_txt_upload_has_no_legacy_processed_file_path(self, client):
        resp = _upload_txt(client)
        assert resp.json()["processed_file_path"] is None

    def test_txt_upload_has_no_legacy_original_file_path(self, client):
        resp = _upload_txt(client)
        assert resp.json()["original_file_path"] is None

    def test_txt_upload_queues_canonical_background_runner(self, client):
        with patch(_txt_runner_target()) as runner:
            resp = client.post("/api/v1/upload", files=[_txt_file("Book\nBody")])
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"
        runner.assert_called_once()
        args = runner.call_args.args
        assert len(args) == 3
        assert args[0] == resp.json()["book_id"]
        assert args[1]
        assert args[2].processing_run_ref.startswith("txt-ingest-")

    def test_txt_upload_accepts_gbk_bytes_for_later_deterministic_decode(self, client):
        """Upload acceptance retains bytes; focused normalization tests verify GBK decoding."""
        text = "市委书记的两规日子\n第二行内容"
        resp = _upload_txt_bytes(client, text.encode("gbk"), name="gbk-book.txt")

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "processing"
        assert data["processed_file_path"] is None
        detail = client.get(f"/api/v1/books/{data['book_id']}")
        assert detail.status_code == 200
        assert detail.json()["status"] == "processing"


class TestUnsupportedFileType:
    """Unsupported file types must be rejected."""

    def test_png_rejected(self, client):
        resp = client.post(
            "/api/v1/upload",
            files=[("file", ("photo.png", io.BytesIO(b"data"), "image/png"))],
        )
        assert resp.status_code == 400

    def test_docx_rejected(self, client):
        resp = client.post(
            "/api/v1/upload",
            files=[("file", ("doc.docx", io.BytesIO(b"data"), "application/octet-stream"))],
        )
        assert resp.status_code == 400

    def test_empty_filename_rejected(self, client):
        resp = client.post(
            "/api/v1/upload",
            files=[("file", ("noext", io.BytesIO(b"data"), "application/octet-stream"))],
        )
        assert resp.status_code == 400


class TestPDFUploadMocked:
    """PDF upload tests for retained-source Modal canonical ingestion."""

    def _make_minimal_pdf(self) -> bytes:
        try:
            import fitz  # type: ignore[import]

            doc = fitz.open()
            doc.new_page(width=595, height=842)
            buf = io.BytesIO()
            doc.save(buf)
            return buf.getvalue()
        except Exception:
            return b"%PDF-1.4 fake"

    def test_pdf_upload_returns_processing(self, client):
        with patch(_pdf_runner_target()):
            pdf_bytes = self._make_minimal_pdf()
            resp = client.post(
                "/api/v1/upload",
                files=[("file", ("book.pdf", io.BytesIO(pdf_bytes), "application/pdf"))],
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["file_type"] == "pdf"
        assert data["status"] in ("processing", "failed")

    def test_pdf_upload_has_no_legacy_original_file_path(self, client):
        with patch(_pdf_runner_target()):
            pdf_bytes = self._make_minimal_pdf()
            resp = client.post(
                "/api/v1/upload",
                files=[("file", ("book.pdf", io.BytesIO(pdf_bytes), "application/pdf"))],
            )

        assert resp.json().get("original_file_path") is None

    def test_pdf_upload_invalid_pdf_fails(self, client):
        resp = client.post(
            "/api/v1/upload",
            files=[("file", ("bad.pdf", io.BytesIO(b"not a pdf"), "application/pdf"))],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert data["original_file_path"] is None
        assert data["error_message"] is not None


# ---------------------------------------------------------------------------
# GET /api/v1/books
# ---------------------------------------------------------------------------

class TestListBooks:
    def test_empty_list(self, client):
        resp = client.get("/api/v1/books")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["books"] == []

    def test_list_after_upload(self, client):
        _upload_txt(client, name="第一章.txt")
        data = client.get("/api/v1/books").json()
        assert data["total"] == 1
        assert data["books"][0]["book_title"] == "第一章"
        assert data["books"][0]["status"] == "processing"

    def test_multiple_books(self, client):
        _upload_txt(client, name="book1.txt")
        _upload_txt(client, name="book2.txt")
        data = client.get("/api/v1/books").json()
        assert data["total"] == 2


# ---------------------------------------------------------------------------
# GET /api/v1/books/{book_id}
# ---------------------------------------------------------------------------

class TestGetBookDetail:
    def test_get_existing_book(self, client):
        upload_data = _upload_txt(client, name="detail_test.txt").json()
        book_id = upload_data["book_id"]

        resp = client.get(f"/api/v1/books/{book_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["book_id"] == book_id
        assert data["book_title"] == "detail_test"
        assert data["status"] == "processing"
        assert data["file_type"] == "txt"
        assert data["processed_file_path"] is None
        assert data["original_file_path"] is None

    def test_get_nonexistent_book_returns_404(self, client):
        resp = client.get("/api/v1/books/nonexistent-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Legacy GET /api/v1/books/{book_id}/content
# ---------------------------------------------------------------------------

class TestGetBookContent:
    def test_processing_txt_does_not_expose_legacy_processed_text_content(self, client):
        upload_data = _upload_txt(client, content="测试内容 line1\n测试内容 line2").json()
        resp = client.get(f"/api/v1/books/{upload_data['book_id']}/content")
        assert resp.status_code == 404
        assert "status: processing" in resp.json()["detail"]

    def test_content_nonexistent_book(self, client):
        resp = client.get("/api/v1/books/nonexistent-id/content")
        assert resp.status_code == 404

    def test_content_failed_book_returns_404(self, client):
        upload_data = client.post(
            "/api/v1/upload",
            files=[("file", ("fail.pdf", io.BytesIO(b"not a pdf"), "application/pdf"))],
        ).json()

        book_id = upload_data["book_id"]
        resp = client.get(f"/api/v1/books/{book_id}/content")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/books/{book_id}
# ---------------------------------------------------------------------------

class TestDeleteBook:
    def test_delete_processing_book_returns_409(self, client):
        book_id = _upload_txt(client).json()["book_id"]
        resp = client.delete(f"/api/v1/books/{book_id}")
        assert resp.status_code == 409
        assert resp.json()["detail"] == "Book is still being processed and cannot be deleted yet"

    def test_delete_existing_terminal_book(self, client):
        book_id = _upload_txt(client).json()["book_id"]
        _mark_book_terminal_for_delete(client, book_id)
        resp = client.delete(f"/api/v1/books/{book_id}")
        assert resp.status_code == 200
        assert book_id in resp.json()["message"]

    def test_delete_terminal_book_removes_from_list(self, client):
        book_id = _upload_txt(client, name="to_delete.txt").json()["book_id"]
        _mark_book_terminal_for_delete(client, book_id)
        resp = client.delete(f"/api/v1/books/{book_id}")
        assert resp.status_code == 200
        data = client.get("/api/v1/books").json()
        ids = [b["book_id"] for b in data["books"]]
        assert book_id not in ids

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/v1/books/nonexistent-id")
        assert resp.status_code == 404

    def test_rejected_invalid_pdf_is_not_persisted_for_delete(self, client):
        upload_data = client.post(
            "/api/v1/upload",
            files=[("file", ("fail.pdf", io.BytesIO(b"not a pdf"), "application/pdf"))],
        ).json()

        book_id = upload_data["book_id"]
        resp = client.delete(f"/api/v1/books/{book_id}")
        assert resp.status_code == 404


class TestOCRRouteRegistration:
    """Ensure OCR legacy task routes are not duplicated."""

    def test_structure_route_registered_once(self):
        matches = [
            route
            for route in app.routes
            if getattr(route, "path", None) == "/api/v1/structure/{task_id}"
            and "POST" in getattr(route, "methods", set())
        ]
        assert len(matches) == 1

    def test_result_route_registered_once(self):
        matches = [
            route
            for route in app.routes
            if getattr(route, "path", None) == "/api/v1/result/{task_id}"
            and "GET" in getattr(route, "methods", set())
        ]
        assert len(matches) == 1
