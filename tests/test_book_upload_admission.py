from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import BackgroundTasks, HTTPException
import pytest

from app.routers import direct_upload, health, ocr, resumable_upload
from app.upload_policy import (
    DEFAULT_BOOK_SOURCE_MAX_BYTES,
    BookSourceTooLarge,
    book_source_max_bytes,
    validate_book_source_size,
)


def test_default_book_source_ceiling_matches_current_100_mib_processing_envelope() -> None:
    settings = SimpleNamespace(book_source_max_bytes=DEFAULT_BOOK_SOURCE_MAX_BYTES)

    assert DEFAULT_BOOK_SOURCE_MAX_BYTES == 100 * 1024 * 1024
    assert book_source_max_bytes(settings) == 100 * 1024 * 1024
    assert validate_book_source_size(100 * 1024 * 1024, settings).max_bytes == (
        100 * 1024 * 1024
    )
    with pytest.raises(BookSourceTooLarge):
        validate_book_source_size(100 * 1024 * 1024 + 1, settings)


def test_upload_capabilities_report_application_and_transport_contract(monkeypatch) -> None:
    monkeypatch.setattr(health.settings, "book_source_max_bytes", 123)
    monkeypatch.setattr(health.settings, "direct_upload_enabled", True)
    monkeypatch.setattr(health.settings, "direct_upload_signing_secret", "s" * 32)
    monkeypatch.setattr(health.settings, "direct_upload_single_put_max_bytes", 456)
    monkeypatch.setattr(health, "object_storage_is_configured", lambda settings_obj: True)

    response = asyncio.run(health.upload_capabilities())

    assert response.schema_version == 1
    assert response.application_max_bytes == 123
    assert response.supported_file_types == ["pdf", "txt"]
    assert response.direct_upload_available is True
    assert response.direct_upload_file_types == ["pdf"]
    assert response.direct_single_put_max_bytes == 456
    assert response.resumable_upload_available is True
    assert response.resumable_upload_file_types == ["pdf", "txt"]
    assert response.resumable_transport_max_bytes == resumable_upload.MAX_UPLOAD_BYTES


def test_upload_capabilities_fail_closed_on_incomplete_direct_configuration(monkeypatch) -> None:
    monkeypatch.setattr(health.settings, "direct_upload_enabled", True)
    monkeypatch.setattr(health.settings, "direct_upload_signing_secret", "short")
    monkeypatch.setattr(health, "object_storage_is_configured", lambda settings_obj: True)

    response = asyncio.run(health.upload_capabilities())

    assert response.direct_upload_available is False


def test_direct_oversize_rejects_before_runtime_or_presign(monkeypatch) -> None:
    monkeypatch.setattr(direct_upload.settings, "book_source_max_bytes", 5)
    monkeypatch.setattr(direct_upload.settings, "direct_upload_single_put_max_bytes", 100)

    def forbidden_runtime():
        raise AssertionError("oversize admission must run before direct-upload runtime")

    monkeypatch.setattr(direct_upload, "_runtime", forbidden_runtime)
    request = direct_upload.DirectUploadCreateRequest(
        filename="book.pdf",
        byte_size=6,
        checksum_sha256="a" * 64,
        content_type="application/pdf",
    )

    with pytest.raises(HTTPException) as exc_info:
        direct_upload.create_direct_upload_session(request)

    assert exc_info.value.status_code == 413
    assert "application upload limit" in str(exc_info.value.detail)


def _oversize_direct_claims():
    return SimpleNamespace(
        upload_id="a" * 32,
        document_id="doc",
        source_file_id="source",
        storage_reference="src_" + "1" * 32,
        filename="book.pdf",
        byte_size=6,
        checksum_sha256="b" * 64,
        content_type="application/pdf",
    )


def test_direct_complete_rechecks_application_ceiling_before_publish_and_cleans_ingress(
    monkeypatch,
) -> None:
    monkeypatch.setattr(direct_upload.settings, "book_source_max_bytes", 5)

    class Provider:
        def __init__(self) -> None:
            self.delete_calls = []

        def publish_ingress(self, **kwargs):
            raise AssertionError("oversize completion must not publish ingress")

        def delete_ingress(self, upload_id):
            self.delete_calls.append(upload_id)

    class Db:
        def get(self, *args, **kwargs):
            return None

    provider = Provider()
    claims = _oversize_direct_claims()
    monkeypatch.setattr(direct_upload, "_runtime", lambda: (provider, "s" * 64))
    monkeypatch.setattr(direct_upload, "_claims_from_token", lambda *args: claims)

    with pytest.raises(HTTPException) as exc_info:
        direct_upload.complete_direct_upload_session(
            claims.upload_id,
            direct_upload.DirectUploadCompleteRequest(completion_token="x" * 20),
            BackgroundTasks(),
            Db(),
        )

    assert exc_info.value.status_code == 413
    assert provider.delete_calls == [claims.upload_id]


def test_direct_existing_commit_remains_idempotent_after_ceiling_is_lowered(monkeypatch) -> None:
    monkeypatch.setattr(direct_upload.settings, "book_source_max_bytes", 5)
    claims = _oversize_direct_claims()

    class Provider:
        def __init__(self) -> None:
            self.delete_calls = []

        def publish_ingress(self, **kwargs):
            raise AssertionError("existing commit must not publish again")

        def delete_ingress(self, upload_id):
            self.delete_calls.append(upload_id)
            raise AssertionError("existing committed upload must not delete ingress")

    document = SimpleNamespace(
        id=claims.document_id,
        title="book",
        file_type="pdf",
        status="processing",
        processed_file_path=None,
        original_file_path=None,
        error_message=None,
    )
    source = SimpleNamespace(
        document_id=claims.document_id,
        storage_reference=claims.storage_reference,
        byte_size=claims.byte_size,
        checksum_sha256=claims.checksum_sha256,
        retained=1,
    )

    class Db:
        def get(self, model, key):
            if model is direct_upload.Document:
                return document
            if model is direct_upload.SourceFile:
                return source
            raise AssertionError("unexpected model lookup")

    provider = Provider()
    monkeypatch.setattr(direct_upload, "_runtime", lambda: (provider, "s" * 64))
    monkeypatch.setattr(direct_upload, "_claims_from_token", lambda *args: claims)

    response = direct_upload.complete_direct_upload_session(
        claims.upload_id,
        direct_upload.DirectUploadCompleteRequest(completion_token="x" * 20),
        BackgroundTasks(),
        Db(),
    )

    assert response.book_id == claims.document_id
    assert "already committed" in response.message
    assert provider.delete_calls == []


def test_resumable_oversize_rejects_before_spool_session(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(resumable_upload.settings, "book_source_max_bytes", 5)
    monkeypatch.setattr(resumable_upload, "UPLOAD_SPOOL_ROOT", tmp_path / "spool")
    request = resumable_upload.CreateUploadSessionRequest(
        filename="book.pdf",
        byte_size=6,
        content_type="application/pdf",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(resumable_upload.create_upload_session(request))

    assert exc_info.value.status_code == 413
    assert not (tmp_path / "spool").exists()


def test_resumable_complete_rechecks_ceiling_if_policy_changed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(resumable_upload, "UPLOAD_SPOOL_ROOT", tmp_path / "spool")
    monkeypatch.setattr(resumable_upload.settings, "book_source_max_bytes", 10)
    created = asyncio.run(
        resumable_upload.create_upload_session(
            resumable_upload.CreateUploadSessionRequest(
                filename="book.txt",
                byte_size=6,
                content_type="text/plain",
            )
        )
    )
    session_dir = resumable_upload._session_dir(created.upload_id)
    assert session_dir.is_dir()

    monkeypatch.setattr(resumable_upload.settings, "book_source_max_bytes", 5)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            resumable_upload.complete_upload_session(
                created.upload_id,
                BackgroundTasks(),
                None,
                None,
            )
        )

    assert exc_info.value.status_code == 413
    assert session_dir.is_dir()


class _GuardedUpload:
    def __init__(self, *, declared_size: int | None, payload: bytes) -> None:
        self.filename = "book.txt"
        self.size = declared_size
        self.content_type = "text/plain"
        self.payload = payload
        self.read_calls = 0

    async def read(self) -> bytes:
        self.read_calls += 1
        return self.payload


def test_canonical_upload_declared_oversize_rejects_before_whole_file_read(monkeypatch) -> None:
    monkeypatch.setattr(ocr.settings, "book_source_max_bytes", 5)
    upload = _GuardedUpload(declared_size=6, payload=b"123456")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(ocr.upload_file(BackgroundTasks(), upload, None, None))

    assert exc_info.value.status_code == 413
    assert upload.read_calls == 0


def test_canonical_upload_actual_size_is_rechecked_when_metadata_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(ocr.settings, "book_source_max_bytes", 5)
    upload = _GuardedUpload(declared_size=None, payload=b"123456")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(ocr.upload_file(BackgroundTasks(), upload, None, None))

    assert exc_info.value.status_code == 413
    assert upload.read_calls == 1
