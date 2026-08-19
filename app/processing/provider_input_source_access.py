"""Safe provider source access for large derived PDF inputs."""
from __future__ import annotations

from datetime import timedelta
import logging
from urllib.parse import urlparse

from app.processing.integration import TemporarySourceTransportUrl
from app.storage.errors import ProviderUnavailable
from app.storage.models import StorageReference
from app.storage.provider_input_access import generate_existing_provider_read_url


logger = logging.getLogger("uvicorn.error")


def build_provider_input_source_url_factory(
    *,
    storage: object,
    reference: StorageReference,
    byte_size: int,
):
    """Return a redacted factory that uses a remote object only after it exists."""
    safe_size = max(0, int(byte_size))

    def factory(ttl: timedelta) -> TemporarySourceTransportUrl | None:
        expires_seconds = max(1, int(ttl.total_seconds()))
        try:
            url = generate_existing_provider_read_url(
                storage,
                reference,
                expires_seconds=expires_seconds,
            )
        except ProviderUnavailable as exc:
            logger.warning(
                "PDF_PROVIDER_SOURCE_ACCESS route=atlas_source_transport_fallback "
                "byte_size=%s expires_seconds=%s reason=%s",
                safe_size,
                expires_seconds,
                type(exc).__name__,
            )
            return None

        parsed = urlparse(url)
        logger.info(
            "PDF_PROVIDER_SOURCE_ACCESS route=presigned_object_get "
            "host=%s byte_size=%s expires_seconds=%s",
            parsed.hostname or "unknown",
            safe_size,
            expires_seconds,
        )
        return TemporarySourceTransportUrl(url)

    return factory


__all__ = ["build_provider_input_source_url_factory"]
