from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from app.storage.errors import IntegrityMismatch, ProviderUnavailable, WriteFailure
from app.storage.models import PutResult, StorageReference
from app.storage.provider_input_access import (
    generate_existing_provider_read_url,
    generate_presigned_provider_get_url,
    presigned_provider_storage,
    select_provider_input_storage,
)


class FakeS3Client:
    def __init__(self, url: str = "https://s3.hf.co/ns/bucket/object?X-Amz-Signature=redacted") -> None:
        self.url = url
        self.calls = []

    def generate_presigned_url(self, operation, **kwargs):
        self.calls.append((operation, kwargs))
        return self.url


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls = 0
        self.delete_calls = 0
        self.put_error: Exception | None = None
        self.exists_error: Exception | None = None

    @staticmethod
    def _ref(reference) -> StorageReference:
        return (
            StorageReference.generate()
            if reference is None
            else StorageReference.parse(str(reference))
        )

    def put(self, data, reference=None, *, expected_size=None, expected_sha256=None):
        self.put_calls += 1
        if self.put_error is not None:
            raise self.put_error
        ref = self._ref(reference)
        payload = bytes(data)
        digest = hashlib.sha256(payload).hexdigest()
        if expected_size is not None and int(expected_size) != len(payload):
            raise IntegrityMismatch("size")
        if expected_sha256 is not None and expected_sha256.lower() != digest:
            raise IntegrityMismatch("sha")
        self.objects[ref.value] = payload
        return PutResult(ref, len(payload), digest)

    def get(self, reference):
        return self.objects[StorageReference.parse(str(reference)).value]

    def exists(self, reference):
        if self.exists_error is not None:
            raise self.exists_error
        return StorageReference.parse(str(reference)).value in self.objects

    def delete(self, reference):
        self.delete_calls += 1
        del self.objects[StorageReference.parse(str(reference)).value]


class FakeS3Provider(FakeStorage):
    def __init__(self, url: str = "https://s3.hf.co/ns/bucket/object?X-Amz-Signature=redacted") -> None:
        super().__init__()
        self.bucket = "bucket"
        self.client = FakeS3Client(url)

    def object_key(self, reference):
        value = StorageReference.parse(str(reference)).value
        return f"atlas/objects/{value}"


class FakeFederatedStorage:
    def __init__(self, primary: FakeStorage, secondary: object) -> None:
        self.primary = primary
        self.secondary = secondary

    def put(self, *args, **kwargs):
        return self.primary.put(*args, **kwargs)

    def get(self, reference):
        if self.primary.exists(reference):
            return self.primary.get(reference)
        return self.secondary.get(reference)

    def exists(self, reference):
        return self.primary.exists(reference) or self.secondary.exists(reference)

    def delete(self, reference):
        if self.primary.exists(reference):
            return self.primary.delete(reference)
        return self.secondary.delete(reference)


def test_provider_input_remote_write_is_reused_for_presigned_get() -> None:
    primary = FakeStorage()
    secondary = FakeS3Provider()
    router = select_provider_input_storage(FakeFederatedStorage(primary, secondary))
    reference = StorageReference.generate()
    payload = b"provider-input"
    digest = hashlib.sha256(payload).hexdigest()

    result = router.put(
        payload,
        reference,
        expected_size=len(payload),
        expected_sha256=digest,
    )

    assert result.reference == reference
    assert primary.put_calls == 0
    assert secondary.put_calls == 1
    assert secondary.objects[reference.value] == payload
    assert router.placed_remotely(reference) is True

    url = router.generate_provider_read_url(reference, expires_seconds=4200)
    assert url.startswith("https://s3.hf.co/")
    operation, kwargs = secondary.client.calls[-1]
    assert operation == "get_object"
    assert kwargs["Params"] == {
        "Bucket": "bucket",
        "Key": f"atlas/objects/{reference.value}",
    }
    assert kwargs["ExpiresIn"] == 4200
    assert kwargs["HttpMethod"] == "GET"


def test_fresh_resolver_finds_remote_object_without_router_memory_state() -> None:
    primary = FakeStorage()
    secondary = FakeS3Provider()
    federated = FakeFederatedStorage(primary, secondary)
    reference = StorageReference.generate()
    secondary.put(b"remote-provider-pdf", reference)

    assert presigned_provider_storage(federated) is secondary
    url = generate_existing_provider_read_url(
        federated,
        reference,
        expires_seconds=4200,
    )

    assert url.startswith("https://s3.hf.co/")
    assert secondary.client.calls[-1][0] == "get_object"


def test_fresh_resolver_never_presigns_local_only_object() -> None:
    primary = FakeStorage()
    secondary = FakeS3Provider()
    federated = FakeFederatedStorage(primary, secondary)
    reference = StorageReference.generate()
    primary.put(b"local-fallback", reference)

    with pytest.raises(ProviderUnavailable):
        generate_existing_provider_read_url(
            federated,
            reference,
            expires_seconds=4200,
        )

    assert secondary.client.calls == []


def test_fresh_resolver_fails_open_to_caller_on_remote_head_failure() -> None:
    primary = FakeStorage()
    secondary = FakeS3Provider()
    secondary.exists_error = ProviderUnavailable("HEAD unavailable")
    federated = FakeFederatedStorage(primary, secondary)

    with pytest.raises(ProviderUnavailable):
        generate_existing_provider_read_url(
            federated,
            StorageReference.generate(),
            expires_seconds=4200,
        )

    assert secondary.client.calls == []


def test_recoverable_remote_write_failure_falls_back_without_second_payload_build() -> None:
    primary = FakeStorage()
    secondary = FakeS3Provider()
    secondary.put_error = WriteFailure("remote unavailable")
    router = select_provider_input_storage(FakeFederatedStorage(primary, secondary))
    reference = StorageReference.generate()
    payload = b"already-produced-s0-bytes"

    result = router.put(payload, reference)

    assert result.reference == reference
    assert secondary.put_calls == 1
    assert primary.put_calls == 1
    assert primary.objects[reference.value] == payload
    assert router.placed_remotely(reference) is False
    with pytest.raises(ProviderUnavailable):
        router.generate_provider_read_url(reference, expires_seconds=4200)


def test_integrity_failure_never_falls_back_to_primary() -> None:
    primary = FakeStorage()
    secondary = FakeS3Provider()
    secondary.put_error = IntegrityMismatch("remote integrity failure")
    router = select_provider_input_storage(FakeFederatedStorage(primary, secondary))

    with pytest.raises(IntegrityMismatch):
        router.put(b"payload", StorageReference.generate())

    assert secondary.put_calls == 1
    assert primary.put_calls == 0


def test_router_without_presign_capable_secondary_uses_existing_storage() -> None:
    primary = FakeStorage()
    secondary = FakeStorage()
    router = select_provider_input_storage(FakeFederatedStorage(primary, secondary))
    reference = StorageReference.generate()

    router.put(b"payload", reference)

    assert primary.put_calls == 1
    assert secondary.put_calls == 0
    assert router.placed_remotely(reference) is False
    with pytest.raises(ProviderUnavailable):
        router.generate_provider_read_url(reference, expires_seconds=4200)


def test_router_delete_resolves_remote_ref_through_federated_storage() -> None:
    primary = FakeStorage()
    secondary = FakeS3Provider()
    router = select_provider_input_storage(FakeFederatedStorage(primary, secondary))
    reference = StorageReference.generate()
    router.put(b"payload", reference)

    router.delete(reference)

    assert secondary.exists(reference) is False
    assert router.placed_remotely(reference) is False


def test_direct_s3_storage_is_presigned_without_federated_wrapper() -> None:
    storage = FakeS3Provider()
    router = select_provider_input_storage(storage)
    reference = StorageReference.generate()

    router.put(b"payload", reference)

    assert storage.put_calls == 1
    assert router.placed_remotely(reference) is True
    assert router.generate_provider_read_url(reference, expires_seconds=4200).startswith(
        "https://s3.hf.co/"
    )
    assert generate_existing_provider_read_url(
        storage,
        reference,
        expires_seconds=4200,
    ).startswith("https://s3.hf.co/")


def test_direct_s3_failure_is_not_retried_against_same_storage() -> None:
    storage = FakeS3Provider()
    storage.put_error = WriteFailure("direct s3 unavailable")
    router = select_provider_input_storage(storage)

    with pytest.raises(WriteFailure):
        router.put(b"payload", StorageReference.generate())

    assert storage.put_calls == 1


def test_presigned_get_uses_exact_bucket_key_ttl_and_get_method() -> None:
    provider = FakeS3Provider()
    reference = StorageReference.generate()

    url = generate_presigned_provider_get_url(
        provider,
        reference,
        expires_seconds=4200,
    )

    assert url.startswith("https://s3.hf.co/")
    assert len(provider.client.calls) == 1
    operation, kwargs = provider.client.calls[0]
    assert operation == "get_object"
    assert kwargs["Params"] == {
        "Bucket": "bucket",
        "Key": f"atlas/objects/{reference.value}",
    }
    assert kwargs["ExpiresIn"] == 4200
    assert kwargs["HttpMethod"] == "GET"


@pytest.mark.parametrize(
    "url",
    [
        "http://s3.hf.co/bucket/object?sig=x",
        "https://user:password@s3.hf.co/bucket/object?sig=x",
        "https://s3.hf.co/bucket/object?sig=x#fragment",
        "https://s3.hf.co/bucket/object\n?sig=x",
        "",
    ],
)
def test_presigned_get_rejects_unsafe_urls(url: str) -> None:
    provider = FakeS3Provider(url)
    with pytest.raises(ProviderUnavailable):
        generate_presigned_provider_get_url(
            provider,
            StorageReference.generate(),
            expires_seconds=4200,
        )


@pytest.mark.parametrize("ttl", [0, 59, 7 * 24 * 60 * 60 + 1])
def test_presigned_get_rejects_out_of_range_expiry(ttl: int) -> None:
    with pytest.raises(ProviderUnavailable):
        generate_presigned_provider_get_url(
            FakeS3Provider(),
            StorageReference.generate(),
            expires_seconds=ttl,
        )


def test_presigned_get_requires_capable_storage() -> None:
    with pytest.raises(ProviderUnavailable):
        generate_presigned_provider_get_url(
            SimpleNamespace(),
            StorageReference.generate(),
            expires_seconds=4200,
        )
