"""Object-storage access helpers for derived provider-input PDFs.

The general StorageProvider contract deliberately stays bytes-first and keeps
federated writes on the legacy primary. Provider-input PDFs are different: they
are large, temporary execution artifacts that a remote OCR provider must read.
This adapter attempts one durable S3-compatible write using the bytes already
produced by S0, but falls back to the existing federated primary for a recoverable
secondary outage without re-running preprocessing.
"""
from __future__ import annotations

import math
import re
from urllib.parse import urlparse

from app.storage.errors import ProviderUnavailable, WriteFailure
from app.storage.models import PutResult, StorageReference


_CONTROL_OR_WHITESPACE_RE = re.compile(r"[\x00-\x20\x7f]")
_MIN_PRESIGNED_SECONDS = 60
_MAX_PRESIGNED_SECONDS = 7 * 24 * 60 * 60


def _presigned_get_capable(provider: object) -> bool:
    client = getattr(provider, "client", None)
    return bool(
        client is not None
        and callable(getattr(client, "generate_presigned_url", None))
        and isinstance(getattr(provider, "bucket", None), str)
        and bool(str(getattr(provider, "bucket", "")).strip())
        and callable(getattr(provider, "object_key", None))
        and callable(getattr(provider, "exists", None))
    )


def presigned_provider_storage(storage: object) -> object | None:
    """Return the direct or federated remote storage capable of safe presigned reads."""
    if _presigned_get_capable(storage):
        return storage
    secondary = getattr(storage, "secondary", None)
    return secondary if _presigned_get_capable(secondary) else None


def generate_presigned_provider_get_url(
    storage: object,
    reference: StorageReference | str,
    *,
    expires_seconds: int,
) -> str:
    """Create and validate an HTTPS presigned GetObject URL for one Atlas ref."""
    if not _presigned_get_capable(storage):
        raise ProviderUnavailable("Provider-input storage cannot issue presigned reads")

    try:
        ttl = int(expires_seconds)
    except (TypeError, ValueError) as exc:
        raise ProviderUnavailable("Provider-input read expiry is invalid") from exc
    if not math.isfinite(float(ttl)) or ttl < _MIN_PRESIGNED_SECONDS or ttl > _MAX_PRESIGNED_SECONDS:
        raise ProviderUnavailable("Provider-input read expiry is outside the supported range")

    bucket = str(getattr(storage, "bucket"))
    try:
        key = storage.object_key(reference)
        url = storage.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=ttl,
            HttpMethod="GET",
        )
    except Exception as exc:
        raise ProviderUnavailable("Could not create provider-input read URL") from exc

    text = str(url or "")
    if not text or _CONTROL_OR_WHITESPACE_RE.search(text):
        raise ProviderUnavailable("Provider-input read URL was malformed")
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ProviderUnavailable("Provider-input read URL was not a safe HTTPS URL")
    if parsed.fragment:
        raise ProviderUnavailable("Provider-input read URL must not contain a fragment")
    return text


def generate_existing_provider_read_url(
    storage: object,
    reference: StorageReference | str,
    *,
    expires_seconds: int,
) -> str:
    """Presign only when the exact provider reference already exists remotely."""
    remote = presigned_provider_storage(storage)
    if remote is None:
        raise ProviderUnavailable("No presign-capable provider-input storage is configured")
    try:
        exists = bool(remote.exists(reference))
    except ProviderUnavailable:
        raise
    except Exception as exc:
        raise ProviderUnavailable("Could not verify remote provider-input object") from exc
    if not exists:
        raise ProviderUnavailable("Provider input is not present in presigned storage")
    return generate_presigned_provider_get_url(
        remote,
        reference,
        expires_seconds=expires_seconds,
    )


class ProviderInputStorageRouter:
    """Place one run's provider-input refs remotely when possible, otherwise locally."""

    def __init__(self, storage: object) -> None:
        self.storage = storage
        self.remote = presigned_provider_storage(storage)
        self._remote_references: set[str] = set()

    @staticmethod
    def _key(reference: StorageReference | str) -> str:
        return StorageReference.parse(str(reference)).value

    def put(
        self,
        data: bytes,
        reference: StorageReference | str | None = None,
        *,
        expected_size: int | None = None,
        expected_sha256: str | None = None,
    ) -> PutResult:
        if self.remote is not None:
            try:
                result = self.remote.put(
                    data,
                    reference,
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                )
            except (ProviderUnavailable, WriteFailure):
                if self.remote is self.storage:
                    # A direct S3 provider has no distinct local primary to fall
                    # back to; retrying the same provider would only duplicate the
                    # failing network operation.
                    raise
                # Recoverable federated-secondary outages must not force S0 to
                # run a second time. The exact already-produced bytes are placed
                # by the existing primary instead.
            else:
                self._remote_references.add(self._key(result.reference))
                return result
        return self.storage.put(
            data,
            reference,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )

    def get(self, reference: StorageReference | str) -> bytes:
        return self.storage.get(reference)

    def delete(self, reference: StorageReference | str) -> None:
        self.storage.delete(reference)
        self._remote_references.discard(self._key(reference))

    def exists(self, reference: StorageReference | str) -> bool:
        return bool(self.storage.exists(reference))

    def placed_remotely(self, reference: StorageReference | str) -> bool:
        return self._key(reference) in self._remote_references

    def generate_provider_read_url(
        self,
        reference: StorageReference | str,
        *,
        expires_seconds: int,
    ) -> str:
        if self.remote is None or not self.placed_remotely(reference):
            raise ProviderUnavailable("Provider input is not available from presigned storage")
        return generate_presigned_provider_get_url(
            self.remote,
            reference,
            expires_seconds=expires_seconds,
        )


def select_provider_input_storage(storage: object) -> ProviderInputStorageRouter:
    """Return a run-local router that prefers durable remote provider-input placement."""
    return ProviderInputStorageRouter(storage)


__all__ = [
    "ProviderInputStorageRouter",
    "generate_existing_provider_read_url",
    "generate_presigned_provider_get_url",
    "presigned_provider_storage",
    "select_provider_input_storage",
]
