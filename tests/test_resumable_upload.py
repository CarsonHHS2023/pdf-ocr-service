"""Resumable large-file upload transport regressions."""
from __future__ import annotations

import io
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, Document, SourceFile
from app.storage.dependencies import get_storage_provider
from app.storage.local import LocalStorageProvider


@pytest.fixture()
def resumable_env(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    storage = LocalStorageProvider(tmp_path / "storage" / "objects")

    def override_get_db():
        yield db

    monkeypatch.setattr("app.routers.resumable_upload.CHUNK_SIZE_BYTES", 4)
    monkeypatch.setattr("app.routers.resumable_upload.UPLOAD_SPOOL_ROOT", tmp_path / "upload-spool")
    monkeypatch.setattr("app.routers.ocr.process_txt_document_background", lambda *args: None)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_storage_provider] = lambda: storage
    with TestClient(app) as client:
        yield client, db, storage, tmp_path
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def _create(client: TestClient, filename: str, data: bytes, content_type: str = "text/plain"):
    response = client.post(
        "/api/v1/upload-sessions",
        json={"filename": filename, "byte_size": len(data), "content_type": content_type},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _upload_all_chunks(
    client: TestClient,
    upload_id: str,
    data: bytes,
    chunk_size: int,
    *,
    method: str = "post",
) -> None:
    for index, start in enumerate(range(0, len(data), chunk_size)):
        chunk = data[start : start + chunk_size]
        response = client.request(
            method.upper(),
            f"/api/v1/upload-sessions/{upload_id}/chunks/{index}",
            content=chunk,
            headers={"content-type": "application/octet-stream"},
        )
        assert response.status_code == 200, response.text


def _minimal_pdf() -> bytes:
    import fitz  # type: ignore[import]

    document = fitz.open()
    document.new_page(width=100, height=100)
    output = io.BytesIO()
    document.save(output)
    document.close()
    return output.getvalue()


def test_resumable_session_spool_is_separate_from_durable_storage(resumable_env):
    client, _, _, tmp_path = resumable_env
    created = _create(client, "book.txt", b"abcdef")
    upload_id = created["upload_id"]

    assert (tmp_path / "upload-spool" / upload_id / "session.json").is_file()
    assert not (tmp_path / "storage" / "upload-sessions").exists()


def test_resumable_upload_reassembles_and_reuses_canonical_acceptance(resumable_env):
    client, db, storage, tmp_path = resumable_env
    data = b"hello resumable upload"
    created = _create(client, "book.txt", data)
    upload_id = created["upload_id"]
    chunk_size = created["chunk_size_bytes"]
    assert chunk_size == 4
    assert created["chunk_count"] > 1

    _upload_all_chunks(client, upload_id, data, chunk_size)

    status = client.get(f"/api/v1/upload-sessions/{upload_id}")
    assert status.status_code == 200
    assert status.json()["received_bytes"] == len(data)

    complete = client.post(f"/api/v1/upload-sessions/{upload_id}/complete")
    assert complete.status_code == 200, complete.text
    payload = complete.json()
    assert payload["status"] == "processing"

    document = db.query(Document).filter_by(id=payload["book_id"]).one()
    source = db.query(SourceFile).filter_by(document_id=document.id).one()
    assert storage.get(source.storage_reference) == data
    assert not (tmp_path / "upload-spool" / upload_id).exists()


def test_resumable_pdf_reuses_existing_pdf_acceptance_path(resumable_env, monkeypatch):
    client, db, storage, tmp_path = resumable_env
    pdf = _minimal_pdf()
    monkeypatch.setattr("app.routers.resumable_upload.CHUNK_SIZE_BYTES", 128)
    with patch("app.routers.ocr.process_pdf_document_background") as background:
        created = _create(client, "book.pdf", pdf, "application/pdf")
        upload_id = created["upload_id"]
        chunk_size = created["chunk_size_bytes"]
        assert created["chunk_count"] > 1
        _upload_all_chunks(client, upload_id, pdf, chunk_size)
        complete = client.post(f"/api/v1/upload-sessions/{upload_id}/complete")

    assert complete.status_code == 200, complete.text
    payload = complete.json()
    assert payload["status"] == "processing"
    assert payload["file_type"] == "pdf"
    document = db.query(Document).filter_by(id=payload["book_id"]).one()
    source = db.query(SourceFile).filter_by(document_id=document.id).one()
    assert document.pages_count == 1
    assert source.mime_type == "application/pdf"
    assert storage.get(source.storage_reference) == pdf
    assert not (tmp_path / "upload-spool" / upload_id).exists()
    background.assert_called_once()


def test_resumable_chunk_post_and_put_share_idempotent_semantics(resumable_env):
    client, *_ = resumable_env
    data = b"abcdef"
    created = _create(client, "book.txt", data)
    upload_id = created["upload_id"]

    first = client.post(f"/api/v1/upload-sessions/{upload_id}/chunks/0", content=b"abcd")
    retry = client.put(f"/api/v1/upload-sessions/{upload_id}/chunks/0", content=b"abcd")
    conflict = client.post(f"/api/v1/upload-sessions/{upload_id}/chunks/0", content=b"wxyz")

    assert first.status_code == 200
    assert retry.status_code == 200
    assert retry.json()["idempotent"] is True
    assert conflict.status_code == 409


def test_resumable_multipart_chunk_matches_raw_idempotent_semantics(resumable_env):
    client, *_ = resumable_env
    data = b"abcdef"
    created = _create(client, "book.txt", data)
    upload_id = created["upload_id"]

    first = client.post(
        f"/api/v1/upload-sessions/{upload_id}/chunks/0/multipart",
        files={"chunk": ("chunk-0.bin", b"abcd", "application/octet-stream")},
    )
    retry = client.put(f"/api/v1/upload-sessions/{upload_id}/chunks/0", content=b"abcd")
    conflict = client.post(
        f"/api/v1/upload-sessions/{upload_id}/chunks/0/multipart",
        files={"chunk": ("chunk-0.bin", b"wxyz", "application/octet-stream")},
    )

    assert first.status_code == 200, first.text
    assert retry.status_code == 200, retry.text
    assert retry.json()["idempotent"] is True
    assert conflict.status_code == 409


def test_resumable_multipart_chunk_logs_diagnostic_stages(resumable_env):
    client, *_ = resumable_env
    created = _create(client, "book.txt", b"abcdef")
    upload_id = created["upload_id"]

    with patch("app.routers.resumable_upload.logger.info") as log_info:
        response = client.post(
            f"/api/v1/upload-sessions/{upload_id}/chunks/0/multipart",
            files={"chunk": ("chunk-0.bin", b"abcd", "application/octet-stream")},
        )

    assert response.status_code == 200, response.text
    messages = [call.args[0] % call.args[1:] for call in log_info.call_args_list]
    markers = [
        "RESUMABLE_UPLOAD_MULTIPART_ENTERED",
        "RESUMABLE_UPLOAD_MULTIPART_PARSED",
        "RESUMABLE_UPLOAD_MULTIPART_READ",
        "RESUMABLE_UPLOAD_CHUNK_RECEIVED",
        "RESUMABLE_UPLOAD_MULTIPART_STORED",
    ]
    positions = [
        next(index for index, message in enumerate(messages) if message.startswith(marker))
        for marker in markers
    ]
    assert positions == sorted(positions)

    entered = next(message for message in messages if message.startswith(markers[0]))
    read = next(message for message in messages if message.startswith(markers[2]))
    stored = next(message for message in messages if message.startswith(markers[4]))
    assert "content_length=" in entered
    assert "content_type=multipart/form-data" in entered
    assert "received_bytes=4" in read
    assert "elapsed_ms=" in read
    assert "idempotent=False" in stored
    assert "elapsed_ms=" in stored


def test_resumable_complete_rejects_missing_chunk_without_destroying_session(resumable_env):
    client, *_ = resumable_env
    data = b"abcdefghij"
    created = _create(client, "book.txt", data)
    upload_id = created["upload_id"]
    response = client.post(f"/api/v1/upload-sessions/{upload_id}/chunks/0", content=b"abcd")
    assert response.status_code == 200

    complete = client.post(f"/api/v1/upload-sessions/{upload_id}/complete")
    assert complete.status_code == 409
    assert client.get(f"/api/v1/upload-sessions/{upload_id}").status_code == 200
