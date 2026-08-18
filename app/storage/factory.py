"""Storage provider construction from settings."""
from app.config import Settings
from app.storage.local import LocalStorageProvider
from app.storage.base import StorageProvider

def create_storage_provider(settings: Settings) -> StorageProvider:
    return LocalStorageProvider(settings.storage_root)
