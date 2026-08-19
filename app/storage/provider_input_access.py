"""Object-storage access helpers for derived provider-input PDFs.

The general StorageProvider contract deliberately stays bytes-first and keeps
federated writes on the legacy primary. Provider-input PDFs are different: they
are large, temporary execution artifacts that a remote OCR provider must read.
When a federated durable S3-compatible secondary is available, this module makes
that placement explicit and can issue a short-lived HTTPS GetObject URL without
routing the object bytes back through the Atlas web process.
"""
from __future__ import annotations

import math
import re
from urllib.parse import urlparse

from app.storage.errors import ProviderUnavailable
from app.storage.models import StorageReference


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
    )


def select_provider_input_storage(storage: object) -> object:
    """Prefer a presign-capable federated secondary for provider-input writes."""
    secondary = getattr(storage, "secondary", None)
    if secondary is not None and _presigned_get_capable(secondary):
        return secondary
    return storage


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


__all__ = [
    "generate_presigned_provider_get_url",
    "select_provider_input_storage",
]
