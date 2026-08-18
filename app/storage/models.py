"""Small provider-independent storage value objects."""
from __future__ import annotations

from dataclasses import dataclass
import re
import uuid

_REFERENCE_RE = re.compile(r"^src_[0-9a-f]{32}$")

@dataclass(frozen=True)
class StorageReference:
    """Opaque logical object reference stored in business metadata."""

    value: str

    @classmethod
    def generate(cls) -> "StorageReference":
        return cls(f"src_{uuid.uuid4().hex}")

    @classmethod
    def parse(cls, value: str) -> "StorageReference":
        from app.storage.errors import InvalidReference
        if not value or not _REFERENCE_RE.fullmatch(value):
            raise InvalidReference("Invalid storage reference")
        return cls(value)

    def __str__(self) -> str:
        return self.value

@dataclass(frozen=True)
class PutResult:
    reference: StorageReference
    byte_size: int
    checksum_sha256: str
