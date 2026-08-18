"""FastAPI dependencies for process-local source transport grants."""
from __future__ import annotations

from collections.abc import Callable

from app.processing.transport.service import InMemoryTransportGrantService
from app.storage.base import StorageProvider
from app.storage.dependencies import get_storage_provider

_transport_grant_service = InMemoryTransportGrantService()


def get_transport_grant_service() -> InMemoryTransportGrantService:
    """Return the application-lifetime in-memory transport grant registry."""
    return _transport_grant_service


StorageProviderFactory = Callable[[], StorageProvider]


def get_storage_provider_factory() -> StorageProviderFactory:
    """Return a lazy Storage provider resolver without constructing Storage."""
    return get_storage_provider
