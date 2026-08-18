"""Pure source-unit-aware Reader v2 application contracts."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.source_units import SourceAnchor, SourceUnit, SourceUnitKind
from app.structured_content_v2.model import ContentNodeTypeV2

READER_V2_CONTRACT_VERSION = "2"


class ReaderV2ContentState(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    NO_USABLE_SEMANTIC_CONTENT = "no_usable_semantic_content"
    UNAVAILABLE = "unavailable"


class ReaderV2WarningCode(str, Enum):
    CONTENT_DEGRADED = "content_degraded"
    CONTENT_UNAVAILABLE = "content_unavailable"
    ASSET_UNAVAILABLE = "asset_unavailable"


@dataclass(frozen=True, slots=True)
class ReaderV2Warning:
    code: ReaderV2WarningCode


@dataclass(frozen=True, slots=True)
class ReaderLocationV2:
    document_ref: str
    candidate_id: str
    candidate_schema_id: str
    candidate_schema_version: int
    node_id: str | None = None
    source_unit_id: str | None = None
    source_anchor: SourceAnchor | None = None
    contract_version: str = READER_V2_CONTRACT_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.document_ref, "document_ref"),
            (self.candidate_id, "candidate_id"),
            (self.candidate_schema_id, "candidate_schema_id"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if self.node_id is not None and not self.node_id.strip():
            raise ValueError("node_id must be non-empty when supplied")
        if self.source_unit_id is not None and not self.source_unit_id.strip():
            raise ValueError("source_unit_id must be non-empty when supplied")
        if self.source_anchor is not None:
            if self.source_unit_id is None:
                raise ValueError("source_anchor requires source_unit_id")
            if self.source_anchor.source_unit_id != self.source_unit_id:
                raise ValueError("source_anchor must reference location source_unit_id")


@dataclass(frozen=True, slots=True)
class ReaderSourceUnitViewV2:
    source_unit: SourceUnit
    content_state: ReaderV2ContentState
    warnings: tuple[ReaderV2Warning, ...] = ()


@dataclass(frozen=True, slots=True)
class ReaderNodeViewV2:
    location: ReaderLocationV2
    node_id: str
    node_type: ContentNodeTypeV2
    order: int
    content_state: ReaderV2ContentState
    source_unit_ids: tuple[str, ...]
    source_anchors: tuple[SourceAnchor, ...] = ()
    text: str | None = None
    heading_level: int | None = None
    parent_ref: str | None = None
    child_refs: tuple[str, ...] = ()
    asset_refs: tuple[str, ...] = ()
    warnings: tuple[ReaderV2Warning, ...] = ()
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ReaderNavigationEntryV2:
    location: ReaderLocationV2
    label: str
    order: int
    heading_level: int


@dataclass(frozen=True, slots=True)
class ReaderDocumentMetadataV2:
    source_unit_count: int
    physical_page_count: int
    reflowable_source_unit_count: int


@dataclass(frozen=True, slots=True)
class ReaderDocumentViewV2:
    document_ref: str
    candidate_id: str
    candidate_schema_id: str
    candidate_schema_version: int
    content_state: ReaderV2ContentState
    source_units: tuple[ReaderSourceUnitViewV2, ...]
    nodes: tuple[ReaderNodeViewV2, ...]
    navigation: tuple[ReaderNavigationEntryV2, ...]
    metadata: ReaderDocumentMetadataV2
    warnings: tuple[ReaderV2Warning, ...] = ()
    contract_version: str = READER_V2_CONTRACT_VERSION


@dataclass(frozen=True, slots=True)
class ReaderContentChunkV2:
    document_ref: str
    candidate_id: str
    nodes: tuple[ReaderNodeViewV2, ...]
    has_more: bool
    next_node_order: int | None = None
    contract_version: str = READER_V2_CONTRACT_VERSION


REFLOWABLE_SOURCE_UNIT_KINDS = frozenset(
    {
        SourceUnitKind.TEXT_FLOW,
        SourceUnitKind.HTML_SECTION,
        SourceUnitKind.EBOOK_SPINE_ITEM,
        SourceUnitKind.DOCUMENT_PART,
    }
)