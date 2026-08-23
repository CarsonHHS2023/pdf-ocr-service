"""Durable storage selection for Reader visual renditions.

Reader visual PNGs outlive a processing container.  The deployed Staging
artifact carries a validated ``staging-revision.txt`` marker, so only that
installation routes federated visual writes to the durable secondary object
store.  Production and local-only environments keep their established storage
placement unchanged.
"""
from __future__ import annotations

from pathlib import Path
import re

from app.storage.base import StorageProvider
from app.storage.federated import FederatedStorageProvider


_RUNTIME_ROOT = Path(__file__).resolve().parents[2]
_STAGING_REVISION_FILE = _RUNTIME_ROOT / "staging-revision.txt"
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


def _staging_artifact_is_active() -> bool:
    """Return whether this process is running from a verified Staging artifact."""
    try:
        revision = _STAGING_REVISION_FILE.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return False
    return _REVISION_RE.fullmatch(revision) is not None


def select_visual_asset_storage(storage: StorageProvider) -> StorageProvider:
    """Use durable secondary placement only for the deployed Staging artifact."""
    if isinstance(storage, FederatedStorageProvider) and _staging_artifact_is_active():
        return storage.secondary
    return storage


__all__ = ["select_visual_asset_storage"]
