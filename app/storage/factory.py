"""Storage provider construction from settings."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import Settings
from app.storage.base import StorageProvider
from app.storage.federated import FederatedStorageProvider
from app.storage.local import LocalStorageProvider

if TYPE_CHECKING:
    from app.storage.s3 import S3StorageProvider


def object_storage_is_configured(settings: Settings) -> bool:
    return all(
        [
            settings.object_storage_endpoint_url,
            settings.object_storage_bucket,
            settings.object_storage_access_key_id,
            settings.object_storage_secret_access_key,
        ]
    )


def create_object_storage_provider(settings: Settings) -> "S3StorageProvider | None":
    if not object_storage_is_configured(settings):
        return None
    # boto3 remains an optional runtime dependency until object storage is
    # actually configured. Focused local/CI paths can continue using Storage v1.
    from app.storage.s3 import S3StorageProvider

    return S3StorageProvider(
        endpoint_url=str(settings.object_storage_endpoint_url),
        bucket=str(settings.object_storage_bucket),
        access_key_id=str(settings.object_storage_access_key_id),
        secret_access_key=str(settings.object_storage_secret_access_key),
        region=settings.object_storage_region,
        prefix=settings.object_storage_prefix,
    )


def create_storage_provider(settings: Settings) -> StorageProvider:
    local = LocalStorageProvider(settings.storage_root)
    remote = create_object_storage_provider(settings)
    if remote is None:
        return local
    return FederatedStorageProvider(local, remote)
