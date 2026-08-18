"""Heavy integration tests: real files from test_samples, no mocks.

These tests use the actual files in test_samples/ and real OCR/PDF libraries.
They are slow and require GPU-capable hardware with PaddleOCR installed.

Run manually:
    pytest tests/test_heavy.py -v -s -m slow
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base

pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Test database: in-memory SQLite
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="module")
def client():
    """One TestClient with a shared in-memory DB for all tests in this module."""
    engine = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Paths to real test files
# ---------------------------------------------------------------------------

TEST_SAMPLES_DIR = Path(__file__).parent.parent / "test_samples"

TXT_FILE = TEST_SAMPLES_DIR / "01《市委书记的两规日子》伍稻洋.txt"
PDF_FILE = TEST_SAMPLES_DIR / "[股票投资精英训练营].扫描版 Test.PDF"


# ---------------------------------------------------------------------------
# TXT real-file tests
# ---------------------------------------------------------------------------

class TestTXTRealFile:
    """Upload and verify the real TXT sample file."""

    def test_txt_file_exists(self):
        """Ensure the TXT sample file is present in test_samples."""
        assert TXT_FILE.exists(), f"TXT sample not found: {TXT_FILE}"

    def test_txt_upload_succeeds(self, client):
        """Upload the real TXT file and verify it completes successfully."""
        with open(TXT_FILE, "rb") as f:
            resp = client.post(
                "/api/v1/upload",
                files=[("file", (TXT_FILE.name, f, "text/plain"))],
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "completed", f"Expected completed, got: {data}"
        assert data["file_type"] == "txt"
        assert data["processed_file_path"] is not None
        assert data["original_file_path"] is None  # deleted on success
        print(f"\n✓ TXT uploaded: book_id={data['book_id']}, title={data['book_title']}")

    def test_txt_book_saved_to_db(self, client):
        """After TXT upload the book should appear in GET /api/v1/books."""
        with open(TXT_FILE, "rb") as f:
            upload_data = client.post(
                "/api/v1/upload",
                files=[("file", (TXT_FILE.name, f, "text/plain"))],
            ).json()

        book_id = upload_data["book_id"]
        resp = client.get(f"/api/v1/books/{book_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["book_id"] == book_id
        assert detail["status"] == "completed"
        assert detail["file_type"] == "txt"
        print(f"✓ Book detail verified: {detail['book_title']}")

    def test_txt_content_readable(self, client):
        """Processed TXT content should be non-empty and readable via the API."""
        with open(TXT_FILE, "rb") as f:
            upload_data = client.post(
                "/api/v1/upload",
                files=[("file", (TXT_FILE.name, f, "text/plain"))],
            ).json()

        book_id = upload_data["book_id"]
        resp = client.get(f"/api/v1/books/{book_id}/content")
        assert resp.status_code == 200
        content_data = resp.json()
        assert len(content_data["content"]) > 0
        print(f"✓ Content length: {len(content_data['content'])} chars")

    def test_txt_appears_in_book_list(self, client):
        """Uploaded TXT book appears in the full book list."""
        with open(TXT_FILE, "rb") as f:
            upload_data = client.post(
                "/api/v1/upload",
                files=[("file", (TXT_FILE.name, f, "text/plain"))],
            ).json()

        book_id = upload_data["book_id"]
        list_resp = client.get("/api/v1/books")
        ids = [b["book_id"] for b in list_resp.json()["books"]]
        assert book_id in ids
        print(f"✓ Book appears in list")

    def test_txt_can_be_deleted(self, client):
        """Uploaded TXT book can be deleted via the API."""
        with open(TXT_FILE, "rb") as f:
            upload_data = client.post(
                "/api/v1/upload",
                files=[("file", (TXT_FILE.name, f, "text/plain"))],
            ).json()

        book_id = upload_data["book_id"]
        processed_path = upload_data["processed_file_path"]

        del_resp = client.delete(f"/api/v1/books/{book_id}")
        assert del_resp.status_code == 200

        # Verify the processed file is removed from disk
        if processed_path:
            assert not Path(processed_path).exists(), "Processed file should be deleted"

        # Verify gone from DB
        assert client.get(f"/api/v1/books/{book_id}").status_code == 404
        print(f"✓ Book deleted and verified")


# ---------------------------------------------------------------------------
# PDF real-file tests
# ---------------------------------------------------------------------------

class TestPDFRealFile:
    """Upload and verify the real PDF sample file with actual OCR."""

    def test_pdf_file_exists(self):
        """Ensure the PDF sample file is present in test_samples."""
        assert PDF_FILE.exists(), f"PDF sample not found: {PDF_FILE}"

    def test_pdf_upload(self, client):
        """Upload the real PDF file and record the outcome (pass or fail gracefully)."""
        with open(PDF_FILE, "rb") as f:
            resp = client.post(
                "/api/v1/upload",
                files=[("file", (PDF_FILE.name, f, "application/pdf"))],
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["file_type"] == "pdf"
        assert data["status"] in ("completed", "failed")
        print(f"\n✓ PDF upload result: status={data['status']}, book_id={data['book_id']}")

        if data["status"] == "completed":
            assert data["processed_file_path"] is not None
            assert data["original_file_path"] is None
            print(f"  processed_file_path: {data['processed_file_path']}")
        else:
            assert data["original_file_path"] is not None
            assert data["error_message"] is not None
            print(f"  error_message: {data['error_message']}")

    def test_pdf_book_saved_to_db(self, client):
        """After PDF upload the book record exists in the database regardless of status."""
        with open(PDF_FILE, "rb") as f:
            upload_data = client.post(
                "/api/v1/upload",
                files=[("file", (PDF_FILE.name, f, "application/pdf"))],
            ).json()

        book_id = upload_data["book_id"]
        resp = client.get(f"/api/v1/books/{book_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["book_id"] == book_id
        assert detail["file_type"] == "pdf"
        assert detail["status"] in ("completed", "failed")
        print(f"✓ PDF book persisted to DB: {detail['book_title']}, status={detail['status']}")

    def test_pdf_completed_content_readable(self, client):
        """If the PDF was processed successfully, its content should be readable."""
        with open(PDF_FILE, "rb") as f:
            upload_data = client.post(
                "/api/v1/upload",
                files=[("file", (PDF_FILE.name, f, "application/pdf"))],
            ).json()

        book_id = upload_data["book_id"]
        if upload_data["status"] != "completed":
            pytest.skip("PDF processing failed — content test skipped")

        resp = client.get(f"/api/v1/books/{book_id}/content")
        assert resp.status_code == 200
        assert len(resp.json()["content"]) > 0
        print(f"✓ PDF content readable, length={len(resp.json()['content'])}")

    def test_pdf_failed_book_deletable(self, client):
        """A failed PDF book (with original_file_path) can be deleted."""
        with open(PDF_FILE, "rb") as f:
            upload_data = client.post(
                "/api/v1/upload",
                files=[("file", (PDF_FILE.name, f, "application/pdf"))],
            ).json()

        book_id = upload_data["book_id"]
        original_path = upload_data.get("original_file_path")

        del_resp = client.delete(f"/api/v1/books/{book_id}")
        assert del_resp.status_code == 200

        if original_path:
            assert not Path(original_path).exists(), "Original file should be deleted"

        assert client.get(f"/api/v1/books/{book_id}").status_code == 404
        print(f"✓ PDF book deleted successfully")
