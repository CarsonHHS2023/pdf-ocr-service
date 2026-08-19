from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.storage.errors import ProviderUnavailable
from app.storage.models import StorageReference
from app.storage.provider_input_access import (
    generate_presigned_provider_get_url,
    select_provider_input_storage,
)


class FakeS3Client:
    def __init__(self, url: str = "https://s3.hf.co/ns/bucket/object?X-Amz-Signature=redacted") -> None:
        self.url = url
        self.calls = []

    def generate_presigned_url(self, operation, **kwargs):
        self.calls.append((operation, kwargs))
        return self.url


class FakeS3Provider:
    def __init__(self, url: str = "https://s3.hf.co/ns/bucket/object?X-Amz-Signature=redacted") -> None:
        self.bucket = "bucket"
        self.client = FakeS3Client(url)

    def object_key(self, reference):
        value = StorageReference.parse(str(reference)).value
        return f"atlas/objects/{value}"


def test_provider_input_prefers_presign_capable_federated_secondary() -> None:
    primary = object()
    secondary = FakeS3Provider()
    federated = SimpleNamespace(primary=primary, secondary=secondary)

    assert select_provider_input_storage(federated) is secondary


def test_provider_input_keeps_existing_storage_without_presign_capability() -> None:
    primary = object()
    secondary = SimpleNamespace()
    federated = SimpleNamespace(primary=primary, secondary=secondary)

    assert select_provider_input_storage(federated) is federated
    assert select_provider_input_storage(primary) is primary


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
