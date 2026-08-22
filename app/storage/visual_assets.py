"""Durable storage selection for Reader visual renditions.

Reader figure/table PNGs outlive a processing container.  In a federated
configuration they therefore belong on the durable secondary object store,
not on the ephemeral/local primary.  Local-only environments keep their
existing storage provider unchanged.
"""
from __future__ import annotations

from app.storage.base import StorageProvider
from app.storage.federated import FederatedStorageProvider


def select_visual_asset_storage(storage: StorageProvider) -> StorageProvider:
    """Return storage whose successful writes survive an HF/container restart."""
    if isinstance(storage, FederatedStorageProvider):
        return storage.secondary
    return storage


__all__ = ["select_visual_asset_storage"]
