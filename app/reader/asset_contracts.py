from __future__ import annotations

from dataclasses import dataclass

from app.structured_content.model import AssetReference, TableAttributes

from .contracts import ReaderContentState


class ReaderAssetError(Exception):
    """Base bounded error for Reader asset/table delivery."""


class ReaderAssetNotFound(ReaderAssetError):
    """Raised when an asset is not part of the explicit selected candidate."""


class ReaderTableNotFound(ReaderAssetError):
    """Raised when a requested selected node is not a structured table."""


class ReaderSelectionChanged(ReaderAssetError):
    """Raised when a candidate-bound Reader request no longer matches selection."""


@dataclass(frozen=True, slots=True)
class ReaderAssetDelivery:
    document_ref: str
    candidate_id: str
    candidate_schema_id: str
    candidate_schema_version: int
    asset: AssetReference
    delivery_state: str
    storage_ref: str | None
    delivery_media_type: str | None
    delivery_byte_size: int | None


@dataclass(frozen=True, slots=True)
class ReaderTableDelivery:
    document_ref: str
    candidate_id: str
    candidate_schema_id: str
    candidate_schema_version: int
    page_id: str
    node_id: str
    content_state: ReaderContentState
    attributes: TableAttributes


__all__ = [
    "ReaderAssetDelivery",
    "ReaderAssetError",
    "ReaderAssetNotFound",
    "ReaderSelectionChanged",
    "ReaderTableDelivery",
    "ReaderTableNotFound",
]
