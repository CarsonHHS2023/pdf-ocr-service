from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.processing.transport.dependencies import get_storage_provider_factory
from app.routers import processing_operator
from app.storage.errors import ObjectAlreadyExists, ProviderUnavailable, WriteFailure
from app.storage.local import LocalStorageProvider
from app.storage.models import PutResult, StorageReference

TOKEN = "op_" + "b" * 40
SHA = "fb084e43d06e039118d2a72a40353eebcec09abdbe732cf30917608723126420"
REF = "src_" + hashlib.sha256(f"source-transport-smoke/{SHA}.pdf".encode("ascii")).hexdigest()[:32]
ROUTE = "/internal/operator/prepare-smoke-fixture"


class CountingStorage:
    def __init__(self, *, put_error=None, get_error=None):
        self.objects = {}
        self.calls = {"exists": 0, "put": 0, "get": 0, "delete": 0}
        self.put_error = put_error
        self.get_error = get_error

    def exists(self, reference):
        self.calls["exists"] += 1
        return str(reference) in self.objects

    def put(self, data, reference=None, *, expected_size=None, expected_sha256=None):
        self.calls["put"] += 1
        if self.put_error:
            raise self.put_error
        ref = StorageReference.parse(str(reference))
        actual_sha = hashlib.sha256(data).hexdigest()
        if expected_size != len(data) or expected_sha256 != actual_sha:
            raise AssertionError("unexpected integrity metadata")
        existing = self.objects.get(str(ref))
        if existing is not None and existing != data:
            raise ObjectAlreadyExists("different bytes")
        self.objects[str(ref)] = data
        return PutResult(ref, len(data), actual_sha)

    def get(self, reference):
        self.calls["get"] += 1
        if self.get_error:
            raise self.get_error
        return self.objects[str(reference)]

    def delete(self, reference):
        self.calls["delete"] += 1
        raise AssertionError("delete must not be called")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    app.dependency_overrides.clear()
    monkeypatch.setattr(processing_operator.settings, "processing_operator_enabled", False)
    monkeypatch.setattr(processing_operator.settings, "processing_operator_token", None)
    yield
    app.dependency_overrides.clear()


def enable(monkeypatch, storage):
    monkeypatch.setattr(processing_operator.settings, "processing_operator_enabled", True)
    monkeypatch.setattr(processing_operator.settings, "processing_operator_token", TOKEN)
    calls = {"factory": 0}

    def factory():
        calls["factory"] += 1
        return storage

    app.dependency_overrides[get_storage_provider_factory] = lambda: factory
    return calls


def post(token=TOKEN, **kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return TestClient(app).post(ROUTE, headers=headers, **kwargs)


def test_runtime_and_committed_fixture_integrity_match():
    paths = [
        Path("tests/fixtures/source_transport/test-only-source-transport.pdf"),
        Path("app/resources/source_transport/test-only-source-transport.pdf"),
    ]
    payloads = [path.read_bytes() for path in paths]
    assert payloads[0] == payloads[1]
    for data in payloads:
        assert len(data) == 605
        assert hashlib.sha256(data).hexdigest() == SHA
        assert data.startswith(b"%PDF-")


def test_disabled_and_bad_auth_collapse_before_fixture_or_storage(monkeypatch):
    storage = CountingStorage()
    factory_calls = enable(monkeypatch, storage)
    read_calls = {"count": 0}

    def fail_if_read():
        read_calls["count"] += 1
        raise AssertionError("fixture should not be read")

    monkeypatch.setattr(processing_operator, "_load_verified_smoke_fixture", fail_if_read)
    for token in (None, "wrong", "  " + TOKEN):
        response = post(token=token)
        assert response.status_code == 404
    monkeypatch.setattr(processing_operator.settings, "processing_operator_enabled", False)
    assert post(token=TOKEN).status_code == 404
    assert read_calls == {"count": 0}
    assert factory_calls == {"factory": 0}
    assert storage.calls == {"exists": 0, "put": 0, "get": 0, "delete": 0}


def test_post_only_hidden_and_no_query_or_body(monkeypatch):
    storage = CountingStorage()
    enable(monkeypatch, storage)
    client = TestClient(app)
    assert ROUTE not in str(client.get("/openapi.json").json())
    assert client.get(ROUTE, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 405
    assert client.put(ROUTE, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 405
    assert client.delete(ROUTE, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 405
    assert client.head(ROUTE, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 405
    assert post(params={"token": TOKEN}).status_code == 422
    assert post(json={"token": TOKEN}).status_code == 422
    assert post(content="{not-json", token="wrong").status_code == 404
    assert storage.calls["put"] == 0


def test_authorized_request_writes_verifies_and_is_idempotent(monkeypatch):
    storage = CountingStorage()
    enable(monkeypatch, storage)
    first = post()
    assert first.status_code == 200
    body = first.json()
    assert body == {
        "status": "ready",
        "fixture_id": "test-only-source-transport",
        "storage_reference": REF,
        "sha256": SHA,
        "byte_size": 605,
        "media_type": "application/pdf",
        "disposition": "retained_or_already_present",
        "message": "Smoke fixture retained and verified for controlled operator use.",
    }
    assert storage.objects[REF] == Path("app/resources/source_transport/test-only-source-transport.pdf").read_bytes()
    second = post()
    assert second.status_code == 200
    assert second.json()["storage_reference"] == REF
    assert second.json()["disposition"] == "retained_or_already_present"
    assert storage.calls == {"exists": 0, "put": 2, "get": 2, "delete": 0}


def test_response_does_not_expose_unsafe_material(monkeypatch):
    storage = CountingStorage()
    enable(monkeypatch, storage)
    text = post().text
    forbidden = ["app/resources", "tests/fixtures", "%PDF", TOKEN, "Authorization", "paddle", "http://", "https://"]
    for value in forbidden:
        assert value not in text


def test_fixture_missing_or_modified_fails_before_storage(monkeypatch):
    storage = CountingStorage()
    enable(monkeypatch, storage)
    monkeypatch.setattr(processing_operator, "_TEST_FIXTURE_RESOURCE", Path("/no/such/file.pdf"))
    assert post().status_code == 500
    assert storage.calls["put"] == 0

    monkeypatch.setattr(processing_operator, "_load_verified_smoke_fixture", lambda: (_ for _ in ()).throw(RuntimeError("bad")))
    assert post().status_code == 500
    assert storage.calls["put"] == 0


def test_different_existing_object_conflicts_without_overwrite(monkeypatch):
    storage = CountingStorage()
    storage.objects[REF] = b"different"
    enable(monkeypatch, storage)
    response = post()
    assert response.status_code == 409
    assert storage.objects[REF] == b"different"
    assert storage.calls["delete"] == 0


@pytest.mark.parametrize("error, expected", [(ProviderUnavailable("down"), 503), (WriteFailure("boom"), 503), (RuntimeError("secret"), 500)])
def test_storage_failures_map_safely(monkeypatch, error, expected):
    storage = CountingStorage(put_error=error)
    enable(monkeypatch, storage)
    response = post()
    assert response.status_code == expected
    assert "secret" not in response.text
    assert "boom" not in response.text


def test_actual_local_storage_concurrent_same_bytes_are_idempotent(monkeypatch, tmp_path):
    storage = LocalStorageProvider(tmp_path)
    enable(monkeypatch, storage)

    def hit():
        return post().status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(lambda _: hit(), range(2)))

    assert statuses == [200, 200]
    assert storage.get(REF) == Path("app/resources/source_transport/test-only-source-transport.pdf").read_bytes()


def test_post_write_get_mismatch_and_non_bytes_fail_safely(monkeypatch):
    for retained in (b"not the fixture", "not-bytes"):
        storage = CountingStorage()
        enable(monkeypatch, storage)
        monkeypatch.setattr(storage, "get", lambda reference, retained=retained: retained)
        response = post()
        assert response.status_code == 500
        assert "not the fixture" not in response.text
        app.dependency_overrides.clear()


def test_actual_local_storage_contract_idempotency_and_conflict(monkeypatch, tmp_path):
    storage = LocalStorageProvider(tmp_path)
    enable(monkeypatch, storage)
    first = post()
    assert first.status_code == 200
    second = post()
    assert second.status_code == 200
    assert first.json()["storage_reference"] == second.json()["storage_reference"] == REF
    assert first.json()["disposition"] == second.json()["disposition"] == "retained_or_already_present"
    assert storage.get(REF) == Path("app/resources/source_transport/test-only-source-transport.pdf").read_bytes()

    conflict_root = tmp_path / "conflict"
    conflict_storage = LocalStorageProvider(conflict_root)
    conflict_storage.put(b"different", REF, expected_size=9, expected_sha256=hashlib.sha256(b"different").hexdigest())
    app.dependency_overrides.clear()
    enable(monkeypatch, conflict_storage)
    response = post()
    assert response.status_code == 409
    assert conflict_storage.get(REF) == b"different"
