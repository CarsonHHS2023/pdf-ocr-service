"""Root-confined Local filesystem storage provider."""
from __future__ import annotations

import errno
import hashlib
import os
import tempfile
from pathlib import Path

from app.storage.errors import (
    DeleteFailure,
    IntegrityMismatch,
    InvalidReference,
    ObjectAlreadyExists,
    ObjectNotFound,
    ProviderUnavailable,
    ReadFailure,
    WriteFailure,
)
from app.storage.models import PutResult, StorageReference


class LocalStorageProvider:
    """Local provider using opaque src_<uuidhex> references as object keys."""

    def __init__(self, root: Path | str):
        configured_root = Path(root)
        if configured_root.exists() and configured_root.is_symlink():
            raise ProviderUnavailable("Storage root must not be a symlink")
        self.root = configured_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ProviderUnavailable("Storage root must not be a symlink")

    def _ref(self, reference: StorageReference | str) -> StorageReference:
        if isinstance(reference, StorageReference):
            return StorageReference.parse(reference.value)
        return StorageReference.parse(str(reference))

    def _ensure_under_root(self, path: Path) -> None:
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise InvalidReference("Storage reference escapes root") from exc

    def _path_for(self, reference: StorageReference | str) -> Path:
        ref = self._ref(reference)
        # Shard for directory size without exposing provider mechanics in ref.
        candidate = (self.root / ref.value[4:6] / ref.value[6:8] / ref.value).resolve()
        self._ensure_under_root(candidate)
        return candidate

    def _safe_parent_for_write(self, final_path: Path) -> Path:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        parent = final_path.parent.resolve()
        self._ensure_under_root(parent)
        if parent.is_symlink() or parent.parent.is_symlink():
            raise WriteFailure("Unsafe symlink at storage destination")
        return parent

    @staticmethod
    def _assert_existing_matches(final_path: Path, actual_size: int, actual_sha: str) -> None:
        if final_path.is_symlink():
            raise WriteFailure("Unsafe symlink at storage destination")
        try:
            existing = final_path.read_bytes()
        except Exception as exc:
            raise ReadFailure(str(exc)) from exc
        existing_sha = hashlib.sha256(existing).hexdigest()
        if len(existing) == actual_size and existing_sha == actual_sha:
            return
        raise ObjectAlreadyExists("Object reference already exists with different bytes")

    def _publish_exclusive_copy(
        self,
        tmp_path: Path,
        final_path: Path,
        actual_size: int,
        actual_sha: str,
    ) -> None:
        """Create-only fallback for mounts that do not implement hard links.

        The destination is opened with ``xb`` so an object that appears during the
        publish race is never overwritten. This path is intentionally used only
        when the filesystem explicitly reports hard-link support is unavailable.
        """
        created = False
        try:
            with final_path.open("xb") as destination:
                created = True
                with tmp_path.open("rb") as source:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        destination.write(chunk)
                destination.flush()
        except FileExistsError:
            self._assert_existing_matches(final_path, actual_size, actual_sha)
        except Exception:
            if created:
                try:
                    final_path.unlink(missing_ok=True)
                except Exception:
                    pass
            raise

    def put(
        self,
        data: bytes,
        reference: StorageReference | str | None = None,
        *,
        expected_size: int | None = None,
        expected_sha256: str | None = None,
    ) -> PutResult:
        ref = self._ref(reference) if reference is not None else StorageReference.generate()
        actual_size = len(data)
        actual_sha = hashlib.sha256(data).hexdigest()
        if expected_size is not None and expected_size != actual_size:
            raise IntegrityMismatch("Expected byte size does not match actual bytes")
        if expected_sha256 is not None and expected_sha256.lower() != actual_sha:
            raise IntegrityMismatch("Expected SHA-256 does not match actual bytes")

        final_path = self._path_for(ref)
        if final_path.is_symlink():
            raise WriteFailure("Unsafe symlink at storage destination")
        if final_path.exists():
            self._assert_existing_matches(final_path, actual_size, actual_sha)
            return PutResult(ref, actual_size, actual_sha)

        parent = self._safe_parent_for_write(final_path)
        tmp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=parent,
                prefix=f".{final_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp_name = tmp.name
                tmp.write(data)
                tmp.flush()
            tmp_path = Path(tmp_name)
            if tmp_path.is_symlink():
                raise WriteFailure("Unsafe symlink temporary file")
            # Prefer a hard-link create-only publish on normal POSIX filesystems.
            # Some mounted object stores (including HF Storage Buckets) reject
            # hard links with EOPNOTSUPP/ENOTSUP. In that bounded case only, fall
            # back to an exclusive-create copy that preserves no-overwrite rules.
            try:
                os.link(tmp_path, final_path)
            except FileExistsError:
                self._assert_existing_matches(final_path, actual_size, actual_sha)
            except OSError as exc:
                unsupported_link_errnos = {errno.EOPNOTSUPP, errno.ENOTSUP}
                if exc.errno not in unsupported_link_errnos:
                    raise
                self._publish_exclusive_copy(tmp_path, final_path, actual_size, actual_sha)
            finally:
                tmp_path.unlink(missing_ok=True)
        except Exception as exc:
            if tmp_name:
                Path(tmp_name).unlink(missing_ok=True)
            if isinstance(exc, (IntegrityMismatch, ObjectAlreadyExists, ReadFailure, WriteFailure)):
                raise
            raise WriteFailure(str(exc)) from exc
        return PutResult(ref, actual_size, actual_sha)

    def get(self, reference: StorageReference | str) -> bytes:
        path = self._path_for(reference)
        if path.is_symlink():
            raise ReadFailure("Unsafe symlink object")
        if not path.exists():
            raise ObjectNotFound("Object not found")
        try:
            return path.read_bytes()
        except Exception as exc:
            raise ReadFailure(str(exc)) from exc

    def exists(self, reference: StorageReference | str) -> bool:
        path = self._path_for(reference)
        return path.exists() and not path.is_symlink()

    def delete(self, reference: StorageReference | str) -> None:
        path = self._path_for(reference)
        if path.is_symlink():
            raise DeleteFailure("Unsafe symlink object")
        if not path.exists():
            raise ObjectNotFound("Object not found")
        try:
            path.unlink()
            for parent in [path.parent, path.parent.parent]:
                if parent == self.root or self.root not in parent.parents:
                    break
                try:
                    parent.rmdir()
                except OSError:
                    break
        except Exception as exc:
            if isinstance(exc, DeleteFailure):
                raise
            raise DeleteFailure(str(exc)) from exc
