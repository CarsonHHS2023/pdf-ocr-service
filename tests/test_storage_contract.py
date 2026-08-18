"""Reusable Storage Adapter v1 provider contract tests for Local provider."""
from __future__ import annotations

import errno
import hashlib
from pathlib import Path

import pytest

from app.storage.errors import IntegrityMismatch, InvalidReference, ObjectAlreadyExists, ObjectNotFound, ProviderUnavailable, WriteFailure
from app.storage.local import LocalStorageProvider
from app.storage.models import StorageReference

@pytest.fixture
def provider(tmp_path):
    return LocalStorageProvider(tmp_path / "objects")

def test_put_get_exists_delete_round_trip(provider):
    result = provider.put(b"hello")
    assert result.byte_size == 5
    assert result.checksum_sha256 == hashlib.sha256(b"hello").hexdigest()
    assert not str(result.reference).startswith("/")
    assert provider.exists(result.reference)
    assert provider.get(result.reference) == b"hello"
    provider.delete(result.reference)
    assert not provider.exists(result.reference)

@pytest.mark.parametrize("bad", ["", "../x", "..\\x", "/tmp/x", "C:\\tmp\\x", "\\\\server\\share", "src_../bad", "local:src_" + "a"*32, "src_" + "g"*32])
def test_invalid_references_are_rejected(provider, bad):
    with pytest.raises(InvalidReference):
        provider.get(bad)

def test_create_only_idempotent_retry_and_conflict(provider):
    ref = StorageReference.generate()
    first = provider.put(b"same", ref)
    second = provider.put(b"same", ref)
    assert second == first
    with pytest.raises(ObjectAlreadyExists):
        provider.put(b"different", ref)

def test_missing_get_and_delete_are_distinguishable(provider):
    ref = StorageReference.generate()
    with pytest.raises(ObjectNotFound):
        provider.get(ref)
    with pytest.raises(ObjectNotFound):
        provider.delete(ref)

def test_expected_integrity_mismatch_does_not_publish(provider):
    ref = StorageReference.generate()
    with pytest.raises(IntegrityMismatch):
        provider.put(b"bytes", ref, expected_size=999)
    assert not provider.exists(ref)
    with pytest.raises(IntegrityMismatch):
        provider.put(b"bytes", ref, expected_sha256="0" * 64)
    assert not provider.exists(ref)

def test_test_root_isolation_and_no_absolute_reference(tmp_path):
    p1 = LocalStorageProvider(tmp_path / "one")
    p2 = LocalStorageProvider(tmp_path / "two")
    result = p1.put(b"isolated")
    assert p1.exists(result.reference)
    assert not p2.exists(result.reference)
    assert str(tmp_path) not in str(result.reference)

def test_symlink_destination_fails_closed(tmp_path):
    provider = LocalStorageProvider(tmp_path / "objects")
    ref = StorageReference.generate()
    path = provider._path_for(ref)  # provider-internal inspection for security regression
    path.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "outside"
    target.write_bytes(b"outside")
    path.symlink_to(target)
    with pytest.raises((InvalidReference, WriteFailure)):
        provider.put(b"new", ref)
    assert target.read_bytes() == b"outside"


def test_root_symlink_is_rejected(tmp_path):
    target = tmp_path / "outside-root"
    target.mkdir()
    link = tmp_path / "root-link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ProviderUnavailable):
        LocalStorageProvider(link)


def test_create_only_publish_race_does_not_overwrite(tmp_path, monkeypatch):
    provider = LocalStorageProvider(tmp_path / "objects")
    ref = StorageReference.generate()
    final_path = provider._path_for(ref)

    def racing_link(src, dst):
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_bytes(b"winner")
        raise FileExistsError

    monkeypatch.setattr("app.storage.local.os.link", racing_link)
    with pytest.raises(ObjectAlreadyExists):
        provider.put(b"loser", ref)
    assert provider.get(ref) == b"winner"
    assert not list(final_path.parent.glob("*.tmp"))


def test_hard_link_unsupported_falls_back_to_exclusive_copy(tmp_path, monkeypatch):
    provider = LocalStorageProvider(tmp_path / "objects")
    ref = StorageReference.generate()

    def unsupported_link(src, dst):
        raise OSError(errno.EOPNOTSUPP, "Operation not supported")

    monkeypatch.setattr("app.storage.local.os.link", unsupported_link)
    result = provider.put(b"hf-bucket-compatible", ref)

    assert result.reference == ref
    assert provider.get(ref) == b"hf-bucket-compatible"
    final_path = provider._path_for(ref)
    assert not list(final_path.parent.glob("*.tmp"))


def test_hard_link_fallback_preserves_idempotency_and_conflict(tmp_path, monkeypatch):
    provider = LocalStorageProvider(tmp_path / "objects")
    ref = StorageReference.generate()

    def unsupported_link(src, dst):
        raise OSError(errno.ENOTSUP, "Operation not supported")

    monkeypatch.setattr("app.storage.local.os.link", unsupported_link)
    first = provider.put(b"same", ref)
    second = provider.put(b"same", ref)

    assert second == first
    with pytest.raises(ObjectAlreadyExists):
        provider.put(b"different", ref)
    assert provider.get(ref) == b"same"


def test_non_unsupported_link_error_still_fails_closed(tmp_path, monkeypatch):
    provider = LocalStorageProvider(tmp_path / "objects")
    ref = StorageReference.generate()

    def permission_denied_link(src, dst):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr("app.storage.local.os.link", permission_denied_link)
    with pytest.raises(WriteFailure):
        provider.put(b"bytes", ref)

    assert not provider.exists(ref)
