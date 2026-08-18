"""Transitional storage federation for legacy local and new object-store refs."""
from __future__ import annotations

from app.storage.errors import ObjectNotFound
from app.storage.models import PutResult, StorageReference


class FederatedStorageProvider:
    """Keep current writes local while resolving new durable source refs remotely.

    Atlas business rows persist opaque ``src_*`` references, so provider placement
    stays an infrastructure concern. Existing sources and derived artifacts stay
    on the current local/HF bucket provider; browser-direct sources can live in an
    S3-compatible durable provider without changing business contracts.

    Primary hits short-circuit before touching the secondary. This is deliberate:
    an object-store outage must not make existing local/HF-bucket books unreadable.
    The opaque 128-bit reference space makes accidental cross-provider collision
    negligible; retained-source checksum verification still fails closed if a
    collision were ever observed during processing.
    """

    def __init__(self, primary, secondary) -> None:
        self.primary = primary
        self.secondary = secondary

    def put(
        self,
        data: bytes,
        reference: StorageReference | str | None = None,
        *,
        expected_size: int | None = None,
        expected_sha256: str | None = None,
    ) -> PutResult:
        # Preserve current placement for all existing processing/derived writes.
        # Direct browser uploads publish to the secondary explicitly before the
        # SourceFile row is committed.
        return self.primary.put(
            data,
            reference,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )

    def get(self, reference: StorageReference | str) -> bytes:
        if self.primary.exists(reference):
            return self.primary.get(reference)
        if self.secondary.exists(reference):
            return self.secondary.get(reference)
        raise ObjectNotFound("Object not found")

    def exists(self, reference: StorageReference | str) -> bool:
        if self.primary.exists(reference):
            return True
        return self.secondary.exists(reference)

    def delete(self, reference: StorageReference | str) -> None:
        if self.primary.exists(reference):
            self.primary.delete(reference)
            return
        if self.secondary.exists(reference):
            self.secondary.delete(reference)
            return
        raise ObjectNotFound("Object not found")
