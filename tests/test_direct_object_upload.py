"""Browser-direct PDF upload control-plane regressions."""
from __future__ import annotations

import hashlib
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, Document, SourceFile
from app.storage.models import PutResult


class FakeDirectObjectStore:
    def __init__(self) -> None:
        self.generated: list[dict] = []
        self.verified: list[dict] = []
        self.published: list[dict] = []
        self.deleted_ingress: list[str] = []
        self.deleted_refs: list[str] = []

    def generate_ingress_put_url(self, **kwargs):
        self.generated.append(kwargs)
        return (
            f"https://objects.example.test/{kwargs['upload_id']}?signature=test",
            {
                "Content-Type": kwargs["content_type"],
                "x-amz-meta-sha256": kwargs["checksum_sha256"],
                "x-amz-meta-upload-id": kwargs["upload_id"],
            },
        )

    def verify_ingress(self, **kwargs) -> None:
        self.verified.append(kwargs)

    def publish_ingress(self, **kwargs) -> PutResult:
        self.published.append(kwargs)
        return PutResult(
            reference=kwargs["reference"],
            byte_size=kwargs["expected_size"],
            checksum_sha256=kwargs["expected_sha256"],
        )

    def delete_ingress(self, upload_id: str) -> None:
        self.deleted_ingress.append(upload_id)

    def delete(self, reference) -> None:
        self.deleted_refs.append(str(reference))


@pytest.fixture()
def direct_upload_env(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    store = FakeDirectObjectStore()

    def override_get_db():
        yield db

    from app.routers import direct_upload

    monkeypatch.setattr(direct_upload.settings, "direct_upload_enabled", True)
    monkeypatch.setattr(direct_upload.settings, "direct_upload_signing_secret", "s" * 64)
    monkeypatch.setattr(direct_upload.settings, "direct_upload_url_ttl_seconds", 900)
    monkeypatch.setattr(direct_upload.settings, "direct_upload_single_put_max_bytes", 100 * 1024 * 1024)
    monkeypatch.setattr(direct_upload, "object_storage_is_configured", lambda settings: True)
    monkeypatch.setattr(direct_upload, "create_object_storage_provider", lambda settings: store)
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client, db, store, direct_upload

    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def _create(client: TestClient, *, size: int = 65_445_424):
    checksum = hashlib.sha256(b"atlas-direct-upload-fixture").hexdigest()
    response = client.post(
        "/api/v1/direct-upload-sessions",
        json={
            "filename": "book.pdf",
            "byte_size": size,
            "checksum_sha256": checksum,
            "content_type": "application/pdf",
        },
    )
    return response, checksum


def test_direct_upload_session_is_control_plane_only(direct_upload_env):
    client, db, store, _ = direct_upload_env
    response, checksum = _create(client)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["upload_mode"] == "single_put"
    assert payload["upload_method"] == "PUT"
    assert payload["upload_url"].startswith("https://objects.example.test/")
    assert payload["upload_headers"]["Content-Type"] == "application/pdf"
    assert payload["upload_headers"]["x-amz-meta-sha256"] == checksum
    assert payload["completion_token"]
    assert db.query(Document).count() == 0
    assert db.query(SourceFile).count() == 0
    assert len(store.generated) == 1


def test_direct_upload_complete_publishes_then_commits_and_queues_processing(direct_upload_env):
    client, db, store, _ = direct_upload_env
    created, checksum = _create(client)
    session = created.json()

    with patch("app.routers.direct_upload.process_pdf_document_background") as background:
        completed = client.post(
            f"/api/v1/direct-upload-sessions/{session['upload_id']}/complete",
            json={"completion_token": session["completion_token"]},
        )

    assert completed.status_code == 200, completed.text
    payload = completed.json()
    assert payload["status"] == "processing"
    document = db.query(Document).filter_by(id=payload["book_id"]).one()
    source = db.query(SourceFile).filter_by(document_id=document.id).one()
    assert document.pages_count is None
    assert source.byte_size == 65_445_424
    assert source.checksum_sha256 == checksum
    assert source.retained == 1
    assert source.storage_reference.startswith("src_")
    assert len(store.verified) == 1
    assert len(store.published) == 1
    assert store.deleted_ingress == [session["upload_id"]]
    background.assert_called_once()


def test_direct_upload_complete_is_idempotent_after_database_commit(direct_upload_env):
    client, db, store, _ = direct_upload_env
    created, _ = _create(client)
    session = created.json()

    with patch("app.routers.direct_upload.process_pdf_document_background") as background:
        first = client.post(
            f"/api/v1/direct-upload-sessions/{session['upload_id']}/complete",
            json={"completion_token": session["completion_token"]},
        )
        second = client.post(
            f"/api/v1/direct-upload-sessions/{session['upload_id']}/complete",
            json={"completion_token": session["completion_token"]},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["book_id"] == first.json()["book_id"]
    assert db.query(Document).count() == 1
    assert db.query(SourceFile).count() == 1
    assert len(store.published) == 1
    background.assert_called_once()


def test_direct_upload_rejects_over_single_put_limit(direct_upload_env):
    client, db, store, _ = direct_upload_env
    response, _ = _create(client, size=100 * 1024 * 1024 + 1)

    assert response.status_code == 413
    assert db.query(Document).count() == 0
    assert store.generated == []


def test_direct_upload_token_tamper_fails_before_publish(direct_upload_env):
    client, db, store, _ = direct_upload_env
    created, _ = _create(client)
    session = created.json()
    token = session["completion_token"]
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

    response = client.post(
        f"/api/v1/direct-upload-sessions/{session['upload_id']}/complete",
        json={"completion_token": tampered},
    )

    assert response.status_code == 400
    assert db.query(Document).count() == 0
    assert store.published == []
