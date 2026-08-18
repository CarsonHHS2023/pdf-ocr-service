"""Storage Adapter v1 synchronous protocol."""
from __future__ import annotations

from typing import Protocol

from app.storage.models import PutResult, StorageReference

class StorageProvider(Protocol):
    """Minimal bytes-first storage boundary.

    Writes are create-only. Re-putting the same reference with the same SHA-256
    is an idempotent retry; different existing bytes must fail closed.
    """

    def put(self, data: bytes, reference: StorageReference | str | None = None, *, expected_size: int | None = None, expected_sha256: str | None = None) -> PutResult: ...
    def get(self, reference: StorageReference | str) -> bytes: ...
    def delete(self, reference: StorageReference | str) -> None: ...
    def exists(self, reference: StorageReference | str) -> bool: ...
