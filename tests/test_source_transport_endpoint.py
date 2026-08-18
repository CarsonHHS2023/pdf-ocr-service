from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.processing.transport import InMemoryTransportGrantService, TransportGrantServicePolicy
from app.processing.transport.dependencies import get_storage_provider_factory, get_transport_grant_service
from app.routers.source_transport import router
from app.storage.errors import InvalidReference, ObjectNotFound, ProviderUnavailable, ReadFailure
from app.storage.models import StorageReference

PDF = b"%PDF-1.7\nprivate source\n%%EOF\n"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    def __call__(self):
        return self.now
    def advance(self, **kw):
        self.now += timedelta(**kw)


class MemoryStorage:
    def __init__(self, data=None, exc=None):
        self.data = data or {}
        self.exc = exc
        self.seen = []
    def put(self, *a, **k):
        raise AssertionError("route must not put")
    def get(self, reference):
        self.seen.append(reference)
        if self.exc:
            raise self.exc
        if reference not in self.data:
            raise ObjectNotFound("missing")
        return self.data[reference]
    def delete(self, reference):
        raise AssertionError("route must not delete")
    def exists(self, reference):
        raise AssertionError("route must not exists")


@pytest.fixture
def env():
    clock = Clock()
    service = InMemoryTransportGrantService(clock=clock)
    storage = MemoryStorage()
    app = FastAPI()
    app.include_router(router)
    storage.factory_calls = 0
    def storage_factory():
        storage.factory_calls += 1
        return storage
    app.dependency_overrides[get_transport_grant_service] = lambda: service
    app.dependency_overrides[get_storage_provider_factory] = lambda: storage_factory
    with TestClient(app) as client:
        yield client, service, storage, clock


def grant(service, storage, body=PDF, **kw):
    ref = StorageReference.generate()
    storage.data[ref] = body
    params = dict(
        storage_reference=ref,
        atlas_attempt_id="attempt-1",
        document_id="doc-1",
        source_file_id="source-1",
        source_sha256=hashlib.sha256(body).hexdigest(),
        source_byte_size=len(body),
        media_type="application/pdf",
    )
    params.update(kw)
    return service.create_grant(**params)


def collapsed(client, token):
    return client.get(f"/internal/source-transport/{token}")


def test_valid_token_returns_exact_pdf_headers_and_counts(env):
    client, service, storage, _ = env
    result = grant(service, storage, filename="secret.pdf")

    resp = collapsed(client, result.token)

    assert resp.status_code == 200
    assert resp.content == PDF
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-length"] == str(len(PDF))
    assert resp.headers["cache-control"] == "private, no-store"
    assert resp.headers["pragma"] == "no-cache"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "content-disposition" not in resp.headers
    assert result.token.encode() not in resp.content
    assert result.token not in str(resp.headers)
    inspected = service.inspect(result.descriptor.grant_id)
    assert inspected.retrieval_count == 1
    assert inspected.first_retrieved_at is not None
    assert inspected.last_retrieved_at is not None
    assert storage.seen == [result.descriptor.storage_reference]
    assert storage.factory_calls == 1

    second = collapsed(client, result.token)
    assert second.status_code == 200
    assert storage.factory_calls == 2
    assert service.inspect(result.descriptor.grant_id).retrieval_count == 2


@pytest.mark.parametrize("bad", ["short", "has.dot", "with space"])
def test_malformed_tokens_collapse(env, bad):
    client, *_ = env
    resp = collapsed(client, bad)
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not found"}


def test_unknown_expired_revoked_and_exhausted_tokens_collapse_identically(env):
    client, service, storage, clock = env
    expired = grant(service, storage, ttl=timedelta(seconds=1))
    revoked = grant(service, storage)
    exhausted = grant(service, storage, max_retrieval_count=1)
    assert collapsed(client, exhausted.token).status_code == 200
    service.revoke(revoked.descriptor.grant_id)
    clock.advance(seconds=2)

    responses = [
        collapsed(client, "A" * 43),
        collapsed(client, expired.token),
        collapsed(client, revoked.token),
        collapsed(client, exhausted.token),
    ]
    assert {(r.status_code, r.text) for r in responses} == {(404, '{"detail":"Not found"}')}


def test_storage_factory_is_not_called_for_credential_failures(env):
    client, service, storage, clock = env
    expired = grant(service, storage, ttl=timedelta(seconds=1))
    revoked = grant(service, storage)
    exhausted = grant(service, storage, max_retrieval_count=1)
    assert collapsed(client, exhausted.token).status_code == 200
    service.revoke(revoked.descriptor.grant_id)
    clock.advance(seconds=2)

    cases = ["short", "A" * 43, expired.token, revoked.token, exhausted.token]
    for token in cases:
        storage.factory_calls = 0
        resp = collapsed(client, token)
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Not found"}
        assert storage.factory_calls == 0


def test_valid_token_storage_factory_construction_failure_maps_safely(env):
    client, service, storage, _ = env
    result = grant(service, storage)
    secret = str(result.descriptor.storage_reference)

    def unavailable_factory():
        raise ProviderUnavailable(f"unavailable {secret} /tmp/source.pdf")

    client.app.dependency_overrides[get_storage_provider_factory] = lambda: unavailable_factory
    resp = collapsed(client, result.token)
    assert resp.status_code == 503
    assert resp.json() == {"detail": "Source transport failed"}
    assert secret not in resp.text
    assert "/tmp/source.pdf" not in resp.text
    assert result.token not in resp.text
    assert service.inspect(result.descriptor.grant_id).retrieval_count == 0


def test_valid_token_unexpected_storage_factory_failure_maps_safely(env):
    client, service, storage, _ = env
    result = grant(service, storage)
    secret = str(result.descriptor.storage_reference)

    def broken_factory():
        raise RuntimeError(f"boom {secret} /var/private/source.pdf")

    client.app.dependency_overrides[get_storage_provider_factory] = lambda: broken_factory
    resp = collapsed(client, result.token)
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Source transport failed"}
    assert secret not in resp.text
    assert "/var/private/source.pdf" not in resp.text
    assert result.token not in resp.text
    assert service.inspect(result.descriptor.grant_id).retrieval_count == 0


@pytest.mark.parametrize("exc,status", [(ObjectNotFound("missing"), 404), (InvalidReference("bad"), 404), (ReadFailure("boom"), 503), (RuntimeError("boom"), 500)])
def test_storage_failure_mapping_uses_injected_storage(env, exc, status):
    client, service, storage, _ = env
    result = grant(service, storage)
    storage.exc = exc
    resp = collapsed(client, result.token)
    assert resp.status_code == status
    assert str(result.descriptor.storage_reference) not in resp.text
    assert service.inspect(result.descriptor.grant_id).retrieval_count == 0


@pytest.mark.parametrize("body", [PDF + b"x", b"X" * len(PDF)])
def test_integrity_mismatch_rejected_without_count(env, body):
    client, service, storage, _ = env
    result = grant(service, storage)
    storage.data[result.descriptor.storage_reference] = body
    resp = collapsed(client, result.token)
    assert resp.status_code == 500
    assert resp.content != body
    assert service.inspect(result.descriptor.grant_id).retrieval_count == 0


def test_exactly_at_policy_limit_object_is_accepted():
    service = InMemoryTransportGrantService(policy=TransportGrantServicePolicy(default_max_source_bytes=len(PDF)))
    storage = MemoryStorage()
    app = FastAPI(); app.include_router(router)
    storage.factory_calls = 0
    def storage_factory():
        storage.factory_calls += 1
        return storage
    app.dependency_overrides[get_transport_grant_service] = lambda: service
    app.dependency_overrides[get_storage_provider_factory] = lambda: storage_factory
    result = grant(service, storage)
    with TestClient(app) as client:
        resp = collapsed(client, result.token)
    assert resp.status_code == 200
    assert resp.content == PDF


def test_non_bytes_and_unsupported_media_type_rejected(env):
    client, service, storage, _ = env
    non_bytes = grant(service, storage)
    storage.data[non_bytes.descriptor.storage_reference] = "not bytes"
    assert collapsed(client, non_bytes.token).status_code == 500
    assert service.inspect(non_bytes.descriptor.grant_id).retrieval_count == 0

    html = grant(service, storage, media_type="text/html")
    assert collapsed(client, html.token).status_code == 500
    assert service.inspect(html.descriptor.grant_id).retrieval_count == 0


def test_pdf_media_type_parameters_are_accepted(env):
    client, service, storage, _ = env
    result = grant(service, storage, media_type="Application/PDF; charset=binary")
    assert collapsed(client, result.token).status_code == 200


def test_revoked_or_expired_between_get_and_reauthorize_do_not_count(env):
    for mode in ("revoke", "expire"):
        clock = Clock()
        service = InMemoryTransportGrantService(clock=clock)
        storage = MemoryStorage()
        app = FastAPI(); app.include_router(router)
        app.dependency_overrides[get_transport_grant_service] = lambda: service
        app.dependency_overrides[get_storage_provider_factory] = lambda: (lambda: storage)
        result = grant(service, storage, ttl=timedelta(seconds=10))
        class RacingStorage(MemoryStorage):
            def get(self, reference):
                if mode == "revoke":
                    service.revoke(result.descriptor.grant_id)
                else:
                    clock.advance(seconds=11)
                return super().get(reference)
        racing = RacingStorage(storage.data)
        app.dependency_overrides[get_storage_provider_factory] = lambda: (lambda: racing)
        with TestClient(app) as client:
            resp = collapsed(client, result.token)
        assert resp.status_code == 404
        assert service.inspect(result.descriptor.grant_id).retrieval_count == 0


def test_retrieval_limit_concurrency_only_one_success():
    service = InMemoryTransportGrantService()
    storage = MemoryStorage()
    app = FastAPI(); app.include_router(router)
    result = grant(service, storage, max_retrieval_count=1)
    barrier = threading.Barrier(2)
    class SlowStorage(MemoryStorage):
        def get(self, reference):
            barrier.wait(timeout=5)
            time.sleep(0.05)
            return super().get(reference)
    slow = SlowStorage(storage.data)
    app.dependency_overrides[get_transport_grant_service] = lambda: service
    app.dependency_overrides[get_storage_provider_factory] = lambda: (lambda: slow)
    outcomes = []
    def hit():
        with TestClient(app) as client:
            outcomes.append(client.get(f"/internal/source-transport/{result.token}"))
    threads = [threading.Thread(target=hit), threading.Thread(target=hit)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sorted(r.status_code for r in outcomes) == [200, 404]
    assert sum(r.content == PDF for r in outcomes) == 1
    assert service.inspect(result.descriptor.grant_id).retrieval_count == 1


def test_head_is_405_and_does_not_count(env):
    client, service, storage, _ = env
    result = grant(service, storage)
    resp = client.head(f"/internal/source-transport/{result.token}")
    assert resp.status_code == 405
    assert service.inspect(result.descriptor.grant_id).retrieval_count == 0


def test_internal_route_is_excluded_from_openapi(env):
    client, *_ = env
    schema = client.get("/openapi.json").json()
    assert "/internal/source-transport/{token}" not in schema.get("paths", {})


def test_app_route_persists_single_registry_across_requests(env):
    client, service, storage, _ = env
    result = grant(service, storage)
    assert collapsed(client, result.token).status_code == 200
    assert collapsed(client, result.token).status_code == 200
    assert service.inspect(result.descriptor.grant_id).retrieval_count == 2
