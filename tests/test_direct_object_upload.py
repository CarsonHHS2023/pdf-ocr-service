"""Browser-direct PDF upload control-plane regressions."""
from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, Document, SourceFile
from app.processing.ingestion_dispatch_model import IngestionDispatch
from app.storage.direct_upload import DirectUploadTokenError, verify_direct_upload_token
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
        self.verify_ingress(
            upload_id=kwargs["upload_id"],
            expected_size=kwargs["expected_size"],
            expected_sha256=kwargs["expected_sha256"],
            expected_content_type=kwargs["expected_content_type"],
        )
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

    durable_dispatch = hasattr(direct_upload, "run_ingestion_dispatch")
    worker = AsyncMock(return_value=True)
    if durable_dispatch:
        monkeypatch.setattr(direct_upload, "run_ingestion_dispatch", worker)
    else:
        monkeypatch.setattr(direct_upload, "process_pdf_document_background", worker)
    monkeypatch.setattr(direct_upload, "_test_worker", worker, raising=False)
    monkeypatch.setattr(
        direct_upload,
        "_test_durable_dispatch",
        durable_dispatch,
        raising=False,
    )

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
    client, db, store, direct_upload = direct_upload_env
    created, checksum = _create(client)
    session = created.json()
    worker = direct_upload._test_worker

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
    assert worker.call_count == 1
    if direct_upload._test_durable_dispatch:
        assert db.query(IngestionDispatch).count() == 1


def test_direct_upload_complete_is_idempotent_after_database_commit(direct_upload_env):
    client, db, store, direct_upload = direct_upload_env
    created, _ = _create(client)
    session = created.json()
    worker = direct_upload._test_worker

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
    assert len(store.verified) == 1
    assert len(store.published) == 1
    assert worker.call_count == (2 if direct_upload._test_durable_dispatch else 1)
    if direct_upload._test_durable_dispatch:
        assert db.query(IngestionDispatch).count() == 1


def test_direct_durable_retry_survives_post_commit_task_registration_crash(
    direct_upload_env,
    monkeypatch,
):
    client, db, store, direct_upload = direct_upload_env
    if not direct_upload._test_durable_dispatch:
        pytest.skip("durable direct overlay is a staging integration contract")

    created, _ = _create(client)
    session = created.json()

    class CrashingBackgroundTasks:
        def add_task(self, *args, **kwargs):
            raise RuntimeError("simulated crash after durable acceptance commit")

    with pytest.raises(RuntimeError, match="simulated crash"):
        direct_upload.complete_direct_upload_session(
            session["upload_id"],
            direct_upload.DirectUploadCompleteRequest(
                completion_token=session["completion_token"]
            ),
            CrashingBackgroundTasks(),
            db,
        )

    assert db.query(Document).count() == 1
    assert db.query(SourceFile).count() == 1
    assert db.query(IngestionDispatch).count() == 1
    assert len(store.published) == 1

    def forbidden_runtime():
        raise AssertionError("durable committed retry must not require object-storage runtime")

    monkeypatch.setattr(direct_upload, "_runtime", forbidden_runtime)
    retry_tasks = BackgroundTasks()
    retried = direct_upload.complete_direct_upload_session(
        session["upload_id"],
        direct_upload.DirectUploadCompleteRequest(
            completion_token=session["completion_token"]
        ),
        retry_tasks,
        db,
    )

    assert retried.book_id == db.query(Document).one().id
    assert "already committed" in retried.message
    assert db.query(Document).count() == 1
    assert db.query(SourceFile).count() == 1
    assert db.query(IngestionDispatch).count() == 1
    assert len(store.published) == 1
    assert len(retry_tasks.tasks) == 1


def test_direct_upload_rejects_over_single_put_limit(direct_upload_env):
    client, db, store, _ = direct_upload_env
    response, _ = _create(client, size=100 * 1024 * 1024 + 1)

    assert response.status_code == 413
    assert db.query(Document).count() == 0
    assert store.generated == []


def test_direct_upload_token_rejects_noncanonical_signature_alias(direct_upload_env):
    client, _, _, direct_upload = direct_upload_env
    created, _ = _create(client)
    token = created.json()["completion_token"]
    payload, signature = token.split(".", 1)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    last_index = alphabet.index(signature[-1])
    assert last_index % 4 == 0  # 32-byte HMAC => two unused low bits
    alias_signature = signature[:-1] + alphabet[last_index + 1]
    alias = f"{payload}.{alias_signature}"

    with pytest.raises(DirectUploadTokenError, match="encoding"):
        verify_direct_upload_token(
            alias,
            direct_upload.settings.direct_upload_signing_secret,
        )


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
    assert store.verified == []
    assert store.published == []
