"""Original TXT/PDF source retention integration and failure tests."""
from __future__ import annotations

import hashlib
import io
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, Document, PdfPage, SourceFile
from app.storage.dependencies import get_storage_provider
from app.storage.errors import DeleteFailure, WriteFailure
from app.storage.local import LocalStorageProvider


@pytest.fixture()
def retention_env(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    storage = LocalStorageProvider(tmp_path / "objects")
    local_scratch = tmp_path / "legacy-local-scratch"
    local_scratch.mkdir()

    def override_get_db():
        yield db

    # Source-retention tests exercise the upload/storage transaction boundary, not
    # the external TXT structure provider. Keep the queued task inert unless a test
    # explicitly replaces it with a controlled failure/completion simulation.
    monkeypatch.setattr("app.routers.ocr.process_txt_document_background", lambda *args: None)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_storage_provider] = lambda: storage
    with TestClient(app) as client:
        yield client, db, storage, local_scratch, SessionLocal
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def test_txt_upload_retains_original_and_queues_canonical_processing(retention_env):
    client, db, storage, local_scratch, _ = retention_env
    original = "hello retained source".encode()
    with patch("app.routers.ocr.process_txt_document_background") as background:
        resp = client.post(
            "/api/v1/upload",
            files=[("file", ("book.txt", io.BytesIO(original), "text/plain"))],
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "processing"
    assert data["processed_file_path"] is None
    assert data["original_file_path"] is None
    assert "storage_reference" not in data

    source = db.query(SourceFile).filter_by(document_id=data["book_id"]).one()
    assert source.retained == 1
    assert source.is_primary == 1
    assert source.storage_reference
    assert not source.storage_reference.startswith("/")
    assert storage.get(source.storage_reference) == original
    assert source.byte_size == len(original)
    assert source.checksum_sha256 == hashlib.sha256(original).hexdigest()

    document = db.query(Document).filter_by(id=data["book_id"]).one()
    assert document.status == "processing"
    assert document.original_file_path is None
    assert document.processed_file_path is None
    assert client.get(f"/api/v1/books/{data['book_id']}/content").status_code == 404
    assert list(local_scratch.rglob("*_processing.txt")) == []
    assert list(local_scratch.rglob("*_processed.txt")) == []

    background.assert_called_once()
    args = background.call_args.args
    assert args[0] == data["book_id"]
    assert args[1] == source.id
    assert args[2].processing_run_ref.startswith("txt-ingest-")


def _minimal_pdf() -> bytes:
    import fitz  # type: ignore[import]

    doc = fitz.open()
    doc.new_page(width=100, height=100)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def test_pdf_upload_retains_original_without_page_blobs(retention_env):
    client, db, storage, local_scratch, _ = retention_env
    pdf = _minimal_pdf()
    with patch("app.routers.ocr.process_pdf_document_background") as background:
        resp = client.post(
            "/api/v1/upload",
            files=[("file", ("book.pdf", io.BytesIO(pdf), "application/pdf"))],
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "processing"
    source = db.query(SourceFile).filter_by(document_id=data["book_id"]).one()
    assert source.retained == 1
    assert source.is_primary == 1
    assert source.mime_type == "application/pdf"
    assert storage.get(source.storage_reference) == pdf
    assert db.query(PdfPage).filter_by(book_id=data["book_id"]).count() == 0
    assert list(local_scratch.rglob("*_original.pdf")) == []
    background.assert_called_once()


def test_storage_write_failure_returns_error_and_no_metadata(retention_env):
    client, db, *_ = retention_env

    class FailingStorage:
        def put(self, *a, **k):
            raise WriteFailure("boom")

        def get(self, reference):
            raise AssertionError

        def delete(self, reference):
            raise AssertionError

        def exists(self, reference):
            return False

    app.dependency_overrides[get_storage_provider] = lambda: FailingStorage()
    resp = client.post(
        "/api/v1/upload",
        files=[("file", ("fail.txt", io.BytesIO(b"x"), "text/plain"))],
    )
    assert resp.status_code == 500
    assert db.query(SourceFile).count() == 0
    assert db.query(Document).count() == 0


def test_processing_failure_keeps_retained_source(retention_env, monkeypatch):
    client, db, storage, *_ = retention_env

    def fail_canonical_processing(document_id, source_file_id, ingestion_ids):
        _ = source_file_id, ingestion_ids
        document = db.query(Document).filter_by(id=document_id).one()
        document.status = "failed"
        document.error_message = "TXT structure analysis provider failed"
        db.commit()

    monkeypatch.setattr(
        "app.routers.ocr.process_txt_document_background",
        fail_canonical_processing,
    )
    resp = client.post(
        "/api/v1/upload",
        files=[("file", ("bad.txt", io.BytesIO(b"evidence"), "text/plain"))],
    )
    data = resp.json()
    assert data["status"] == "processing", "upload acknowledges queueing before background terminal state"
    source = db.query(SourceFile).filter_by(document_id=data["book_id"]).one()
    assert source.retained == 1
    assert storage.get(source.storage_reference) == b"evidence"
    document = db.query(Document).filter_by(id=data["book_id"]).one()
    assert document.status == "failed"
    assert document.error_message == "TXT structure analysis provider failed"


def test_delete_book_explicitly_deletes_retained_source(retention_env):
    client, db, storage, *_ = retention_env
    resp = client.post(
        "/api/v1/upload",
        files=[("file", ("book.txt", io.BytesIO(b"delete me"), "text/plain"))],
    )
    book_id = resp.json()["book_id"]
    source = db.query(SourceFile).filter_by(document_id=book_id).one()
    ref = source.storage_reference
    assert storage.exists(ref)
    delete = client.delete(f"/api/v1/books/{book_id}")
    assert delete.status_code == 200
    assert not storage.exists(ref)


def test_initial_db_commit_failure_cleans_retained_object(retention_env, monkeypatch):
    client, db, storage, local_scratch, _ = retention_env
    original_commit = db.commit
    calls = {"count": 0}

    def fail_first_commit():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("commit failed")
        return original_commit()

    monkeypatch.setattr(db, "commit", fail_first_commit)
    with pytest.raises(RuntimeError, match="commit failed"):
        client.post(
            "/api/v1/upload",
            files=[("file", ("dbfail.txt", io.BytesIO(b"db fail"), "text/plain"))],
        )
    assert db.query(SourceFile).count() == 0
    assert db.query(Document).count() == 0
    assert not any(storage.root.rglob("src_*"))
    assert list(local_scratch.rglob("*_processing.txt")) == []


def test_delete_db_commit_failure_restores_retained_source(retention_env, monkeypatch):
    client, db, storage, *_ = retention_env
    resp = client.post(
        "/api/v1/upload",
        files=[("file", ("restore.txt", io.BytesIO(b"restore"), "text/plain"))],
    )
    book_id = resp.json()["book_id"]
    ref = db.query(SourceFile).filter_by(document_id=book_id).one().storage_reference
    original_commit = db.commit
    state = {"fail_delete_commit": False}

    def commit_with_delete_failure():
        if state["fail_delete_commit"]:
            raise RuntimeError("delete commit failed")
        return original_commit()

    monkeypatch.setattr(db, "commit", commit_with_delete_failure)
    state["fail_delete_commit"] = True
    delete = client.delete(f"/api/v1/books/{book_id}")
    assert delete.status_code == 500
    assert storage.get(ref) == b"restore"


def test_multi_source_delete_failure_restores_prior_deleted_source(retention_env):
    client, db, storage, *_ = retention_env
    resp = client.post(
        "/api/v1/upload",
        files=[("file", ("multi.txt", io.BytesIO(b"first"), "text/plain"))],
    )
    book_id = resp.json()["book_id"]
    first_source = db.query(SourceFile).filter_by(document_id=book_id).one()
    first_ref = first_source.storage_reference
    second_result = storage.put(b"second")
    second_ref = str(second_result.reference)
    db.add(
        SourceFile(
            document_id=book_id,
            original_filename="second.txt",
            file_type="txt",
            mime_type="text/plain",
            byte_size=second_result.byte_size,
            checksum_sha256=second_result.checksum_sha256,
            storage_reference=second_ref,
            retained=1,
            is_primary=0,
        )
    )
    db.commit()

    class FailsOnSecondDelete:
        def __init__(self, inner):
            self.inner = inner
            self.delete_calls = 0

        def put(self, *args, **kwargs):
            return self.inner.put(*args, **kwargs)

        def get(self, *args, **kwargs):
            return self.inner.get(*args, **kwargs)

        def exists(self, *args, **kwargs):
            return self.inner.exists(*args, **kwargs)

        def delete(self, reference):
            self.delete_calls += 1
            if self.delete_calls == 2:
                raise DeleteFailure("second delete failed")
            return self.inner.delete(reference)

    app.dependency_overrides[get_storage_provider] = lambda: FailsOnSecondDelete(storage)
    delete = client.delete(f"/api/v1/books/{book_id}")

    assert delete.status_code == 500
    assert db.query(Document).filter_by(id=book_id).count() == 1
    assert db.query(SourceFile).filter_by(document_id=book_id).count() == 2
    assert storage.get(first_ref) == b"first"
    assert storage.get(second_ref) == b"second"
