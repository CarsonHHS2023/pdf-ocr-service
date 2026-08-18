"""Transitional local + object-store StorageProvider regressions."""
from __future__ import annotations

from app.storage.errors import ObjectNotFound
from app.storage.federated import FederatedStorageProvider
from app.storage.models import PutResult, StorageReference


class MemoryProvider:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.exists_calls = 0

    def put(self, data: bytes, reference=None, *, expected_size=None, expected_sha256=None):
        ref = reference if isinstance(reference, StorageReference) else (
            StorageReference.parse(reference) if reference else StorageReference.generate()
        )
        self.objects[str(ref)] = bytes(data)
        return PutResult(ref, len(data), "0" * 64)

    def get(self, reference):
        key = str(reference)
        if key not in self.objects:
            raise ObjectNotFound("Object not found")
        return self.objects[key]

    def exists(self, reference):
        self.exists_calls += 1
        return str(reference) in self.objects

    def delete(self, reference):
        key = str(reference)
        if key not in self.objects:
            raise ObjectNotFound("Object not found")
        del self.objects[key]


def test_federated_storage_reads_legacy_local_and_new_remote_refs():
    local = MemoryProvider()
    remote = MemoryProvider()
    provider = FederatedStorageProvider(local, remote)
    local_ref = StorageReference.generate()
    remote_ref = StorageReference.generate()
    local.objects[str(local_ref)] = b"legacy"
    remote.objects[str(remote_ref)] = b"direct"

    assert provider.get(local_ref) == b"legacy"
    assert provider.get(remote_ref) == b"direct"
    assert provider.exists(local_ref)
    assert provider.exists(remote_ref)


def test_federated_storage_preserves_existing_writes_on_primary():
    local = MemoryProvider()
    remote = MemoryProvider()
    provider = FederatedStorageProvider(local, remote)
    reference = StorageReference.generate()

    provider.put(b"derived", reference)

    assert local.get(reference) == b"derived"
    assert not remote.exists(reference)


def test_legacy_primary_hit_does_not_touch_secondary():
    local = MemoryProvider()
    remote = MemoryProvider()
    provider = FederatedStorageProvider(local, remote)
    reference = StorageReference.generate()
    local.objects[str(reference)] = b"legacy"

    assert provider.get(reference) == b"legacy"
    assert remote.exists_calls == 0
    assert provider.exists(reference) is True
    assert remote.exists_calls == 0

    provider.delete(reference)
    assert remote.exists_calls == 0
