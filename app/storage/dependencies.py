"""FastAPI dependency for storage injection."""
from app.config import settings
from app.storage.base import StorageProvider
from app.storage.factory import create_storage_provider

def get_storage_provider() -> StorageProvider:
    return create_storage_provider(settings)
