from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.processing.transport import (
    ExpiredGrant,
    GrantNotFound,
    InMemoryTransportGrantService,
    InvalidGrantInput,
    InvalidToken,
    RetrievalLimitExceeded,
    RevokedGrant,
    TransportGrantServicePolicy,
    TransportGrantState,
    UnsafeMetadata,
)
from app.storage.models import StorageReference

SHA = "a" * 64
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: int) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def service(clock: Clock) -> InMemoryTransportGrantService:
    return InMemoryTransportGrantService(clock=clock)


def create(service: InMemoryTransportGrantService, **kwargs):
    params = {
        "storage_reference": StorageReference.generate(),
        "atlas_attempt_id": "attempt-1",
        "document_id": "doc-1",
        "source_file_id": "source-1",
        "source_sha256": SHA,
        "source_byte_size": 1024,
        "media_type": "application/pdf",
    }
    params.update(kwargs)
    return service.create_grant(**params)


def test_create_grant_returns_one_plain_token_and_safe_record(service, clock):
    result = create(service, filename="invoice.pdf", provider_job_id="job-1")

    assert result.descriptor.state == TransportGrantState.ACTIVE
    assert result.descriptor.expires_at == clock.now + timedelta(minutes=20)
    assert TOKEN_RE.fullmatch(result.token)
    assert len(result.token) >= 40
    assert result.token not in repr(service)
    assert result.token not in repr(result)
    stored = service._by_digest[next(iter(service._by_digest))]
    assert result.token not in repr(stored)
    assert stored.token_digest != result.token
    assert stored.token_digest not in repr(result)
    assert stored.token_digest not in repr(result.descriptor)
    assert result.descriptor.policy.replay_allowed is True
    assert result.descriptor.filename == "invoice.pdf"


def test_tokens_and_ids_are_unique_and_opaque(service):
    first = create(service, document_id="document-business-id")
    second = create(service, document_id="document-business-id")

    assert first.token != second.token
    assert first.descriptor.grant_id != second.descriptor.grant_id
    assert "document-business-id" not in first.token
    assert first.descriptor.source_file_id not in first.token
    assert str(first.descriptor.storage_reference) not in first.token


def test_explicit_ttl_and_maximum_ttl_are_enforced(service, clock):
    result = create(service, ttl=timedelta(minutes=5))
    assert result.descriptor.expires_at == clock.now + timedelta(minutes=5)

    with pytest.raises(InvalidGrantInput):
        create(service, ttl=timedelta(hours=2))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"atlas_attempt_id": ""},
        {"document_id": " "},
        {"source_file_id": ""},
        {"source_sha256": "bad"},
        {"source_byte_size": -1},
        {"media_type": ""},
        {"ttl": timedelta(0)},
        {"ttl": timedelta(seconds=-1)},
        {"max_retrieval_count": 0},
        {"max_retrieval_count": -1},
        {"atlas_attempt_id": None},
        {"document_id": " "},
    ],
)
def test_invalid_create_inputs_are_rejected(service, kwargs):
    with pytest.raises(InvalidGrantInput):
        create(service, **kwargs)


def test_invalid_storage_reference_and_source_size_limit(clock):
    service = InMemoryTransportGrantService(
        clock=clock,
        policy=TransportGrantServicePolicy(default_max_source_bytes=10),
    )
    with pytest.raises(InvalidGrantInput):
        service.create_grant(
            storage_reference="src_not_a_value_object",
            atlas_attempt_id="attempt",
            document_id="doc",
            source_file_id="src",
            source_sha256=SHA,
            source_byte_size=1,
            media_type="application/pdf",
        )
    with pytest.raises(InvalidGrantInput):
        create(service, source_byte_size=11)


@pytest.mark.parametrize(
    "metadata",
    [
        {"token": "x"},
        {"safe": {"Download-URL": "x"}},
        {"headers": {"x": "y"}},
        {"credentials": "x"},
        {"X-Amz-Signature": "x"},
    ],
)
def test_unsafe_metadata_and_caller_credentials_are_rejected(service, metadata):
    with pytest.raises(UnsafeMetadata):
        create(service, safe_metadata=metadata)
    with pytest.raises(InvalidGrantInput):
        create(service, token="caller-token")
    with pytest.raises(InvalidGrantInput):
        create(service, source_url="https://example.invalid/file.pdf")
    with pytest.raises(InvalidGrantInput):
        create(service, local_path="/tmp/file.pdf")


def test_metadata_false_positive_values_and_count_keys_are_allowed(service):
    result = create(
        service,
        safe_metadata={
            "token_count": 3,
            "path_count": 4,
            "note": "contains the word secret as a business value",
        },
    )

    assert result.descriptor.policy.safe_metadata["token_count"] == 3


def test_authorize_returns_safe_descriptor_without_token_or_digest(service):
    result = create(service)
    authorized = service.authorize(result.token)

    assert authorized.grant_id == result.descriptor.grant_id
    assert authorized.storage_reference == result.descriptor.storage_reference
    text = repr(authorized)
    assert result.token not in text
    assert "digest" not in text.lower()


@pytest.mark.parametrize("token", ["", "   ", "not path safe!", "short"])
def test_blank_and_malformed_tokens_are_rejected(service, token):
    with pytest.raises(InvalidToken):
        service.authorize(token)


def test_unknown_expired_and_revoked_tokens_are_rejected_safely(service, clock):
    with pytest.raises(GrantNotFound) as unknown:
        service.authorize("A" * 48)
    assert "A" * 48 not in str(unknown.value)

    expired = create(service, ttl=timedelta(minutes=1))
    clock.advance(minutes=1)
    with pytest.raises(ExpiredGrant):
        service.authorize(expired.token)

    active = create(service)
    service.revoke(active.descriptor.grant_id)
    with pytest.raises(RevokedGrant):
        service.authorize(active.token)


def test_repeated_successful_retrievals_count_and_do_not_revoke(service, clock):
    result = create(service)
    first = service.record_retrieval(result.token)
    clock.advance(seconds=5)
    second = service.record_retrieval(result.token)

    summary = service.inspect(result.descriptor.grant_id)
    assert first.grant_id == second.grant_id
    assert summary.retrieval_count == 2
    assert summary.first_retrieved_at == datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    assert summary.last_retrieved_at == clock.now
    assert summary.state == TransportGrantState.ACTIVE


def test_failed_authorization_does_not_count_and_limit_exhausts(service):
    result = create(service, max_retrieval_count=1)
    with pytest.raises(GrantNotFound):
        service.record_retrieval("B" * 48)
    assert service.inspect(result.descriptor.grant_id).retrieval_count == 0
    service.record_retrieval(result.token)
    assert service.inspect(result.descriptor.grant_id).state == TransportGrantState.EXHAUSTED
    with pytest.raises(RetrievalLimitExceeded):
        service.authorize(result.token)
    with pytest.raises(RetrievalLimitExceeded):
        service.record_retrieval(result.token)


def test_expiry_at_exact_boundary_blocks_after_prior_retrieval(service, clock):
    result = create(service, ttl=timedelta(minutes=1))
    service.record_retrieval(result.token)
    clock.advance(minutes=1)
    assert service.inspect(result.descriptor.grant_id).state == TransportGrantState.EXPIRED
    with pytest.raises(ExpiredGrant):
        service.record_retrieval(result.token)


def test_revocation_is_idempotent_and_unknown_safe(service):
    result = create(service)
    first = service.revoke(result.descriptor.grant_id)
    second = service.revoke(result.descriptor.grant_id)

    assert first.revoked_at == second.revoked_at
    assert service.revoke("tg_unknown") is None
    with pytest.raises(RevokedGrant):
        service.authorize(result.token)


def test_cleanup_is_bounded_and_keeps_active_grants(service, clock):
    expired = create(service, ttl=timedelta(seconds=1))
    active = create(service)
    revoked = create(service)
    service.revoke(revoked.descriptor.grant_id)
    clock.advance(seconds=1)

    removed = service.cleanup_expired(limit=1)
    assert len(removed) == 1
    removed += service.cleanup_expired(limit=10)
    assert {expired.descriptor.grant_id, revoked.descriptor.grant_id}.issubset(set(removed))
    assert service.inspect(active.descriptor.grant_id).state == TransportGrantState.ACTIVE
    assert expired.token not in repr(removed)


def test_policy_and_clock_validation(clock):
    with pytest.raises(InvalidGrantInput):
        InMemoryTransportGrantService(
            clock=clock,
            policy=TransportGrantServicePolicy(default_max_retrieval_count=0),
        )
    naive_service = InMemoryTransportGrantService(clock=lambda: datetime(2026, 7, 15, 12, 0))
    with pytest.raises(InvalidGrantInput):
        create(naive_service)


def test_exact_source_size_limit_is_allowed(clock):
    service = InMemoryTransportGrantService(
        clock=clock,
        policy=TransportGrantServicePolicy(default_max_source_bytes=1024),
    )
    result = create(service, source_byte_size=1024)
    assert result.descriptor.source_byte_size == 1024


def test_policy_metadata_is_defensively_frozen(service):
    metadata = {"safe": ["value"]}
    result = create(service, safe_metadata=metadata)
    metadata["safe"].append("mutated")

    assert result.descriptor.policy.safe_metadata["safe"] == ("value",)
    with pytest.raises(TypeError):
        result.descriptor.policy.safe_metadata["new"] = "blocked"


def test_concurrent_retrieval_accounting_does_not_lose_updates(service):
    result = create(service)
    errors = []

    def worker():
        try:
            service.record_retrieval(result.token)
        except Exception as exc:  # pragma: no cover - assertion below reports failures
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(25)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert service.inspect(result.descriptor.grant_id).retrieval_count == 25


def test_no_route_database_storage_or_provider_dependencies_imported():
    import app.processing.transport.service as module

    assert "Storage.get" not in module.__loader__.get_source(module.__name__)
    assert "Storage.put" not in module.__loader__.get_source(module.__name__)
    assert "sqlalchemy" not in module.__loader__.get_source(module.__name__).lower()
    assert "fastapi" not in module.__loader__.get_source(module.__name__).lower()
    assert "paddle" not in module.__loader__.get_source(module.__name__).lower()


def test_concurrent_revocation_race_fails_safely(service):
    result = create(service)
    outcomes = []

    def retrieve():
        try:
            service.record_retrieval(result.token)
            outcomes.append("retrieved")
        except RevokedGrant:
            outcomes.append("revoked")

    threads = [threading.Thread(target=retrieve) for _ in range(10)]
    for thread in threads:
        thread.start()
    service.revoke(result.descriptor.grant_id)
    for thread in threads:
        thread.join()

    assert set(outcomes).issubset({"retrieved", "revoked"})
    assert service.inspect(result.descriptor.grant_id).state == TransportGrantState.REVOKED
    with pytest.raises(RevokedGrant):
        service.authorize(result.token)
