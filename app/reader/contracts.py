"""Immutable, derived Reader application contracts.

These contracts are distinct from the compatibility-only Reader Content Stream
v2 format.  They are not canonical content and carry no persistence behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.structured_content.enums import ContentNodeType
from app.structured_content.identity import (
    AssetId,
    ContentCandidateId,
    ContentNodeId,
    ContentPageId,
    DocumentRef,
)

READER_APPLICATION_CONTRACT_VERSION = "1"
SUPPORTED_READER_APPLICATION_CONTRACT_VERSIONS = frozenset(
    {READER_APPLICATION_CONTRACT_VERSION}
)


class ReaderProcessingState(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReaderContentState(str, Enum):
    READY = "ready"
    # Usable content remains, but some expected semantic content is absent.
    PARTIAL = "partial"
    # Usable content remains with a recovery or quality degradation.
    DEGRADED = "degraded"
    NO_USABLE_SEMANTIC_CONTENT = "no_usable_semantic_content"
    UNAVAILABLE = "unavailable"


class ReaderWarningCode(str, Enum):
    CONTENT_DEGRADED = "content_degraded"
    CONTENT_UNAVAILABLE = "content_unavailable"
    ASSET_UNAVAILABLE = "asset_unavailable"
    UNSUPPORTED_CONTENT = "unsupported_content"


class ReaderNavigationKind(str, Enum):
    HEADING = "heading"


@dataclass(frozen=True, slots=True)
class ReaderWarning:
    """A bounded product-safe warning; arbitrary diagnostic text is excluded."""

    code: ReaderWarningCode


@dataclass(frozen=True, slots=True)
class ReaderLocation:
    document_ref: DocumentRef
    candidate_id: ContentCandidateId
    candidate_schema_id: str
    candidate_schema_version: int
    contract_version: str = READER_APPLICATION_CONTRACT_VERSION
    page_id: ContentPageId | None = None
    node_id: ContentNodeId | None = None
    segment_index: int | None = None


@dataclass(frozen=True, slots=True)
class ReaderDocumentMetadata:
    title: str | None = None
    page_count: int = 0


@dataclass(frozen=True, slots=True)
class ReaderNodeView:
    location: ReaderLocation
    node_id: ContentNodeId
    node_type: ContentNodeType
    order: int
    content_state: ReaderContentState
    text: str | None = None
    heading_level: int | None = None
    parent_ref: ContentNodeId | None = None
    child_refs: tuple[ContentNodeId, ...] = ()
    asset_refs: tuple[AssetId, ...] = ()
    warnings: tuple[ReaderWarning, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "child_refs", tuple(self.child_refs))
        object.__setattr__(self, "asset_refs", tuple(self.asset_refs))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True, slots=True)
class ReaderPageView:
    location: ReaderLocation
    page_id: ContentPageId
    page_order: int
    content_state: ReaderContentState
    nodes: tuple[ReaderNodeView, ...] = ()
    warnings: tuple[ReaderWarning, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True, slots=True)
class ReaderNavigationEntry:
    location: ReaderLocation
    label: str
    order: int
    heading_level: int
    kind: ReaderNavigationKind = ReaderNavigationKind.HEADING


@dataclass(frozen=True, slots=True)
class ReaderDocumentView:
    document_ref: DocumentRef
    candidate_id: ContentCandidateId
    candidate_schema_id: str
    candidate_schema_version: int
    processing_state: ReaderProcessingState
    content_state: ReaderContentState
    contract_version: str = READER_APPLICATION_CONTRACT_VERSION
    metadata: ReaderDocumentMetadata = ReaderDocumentMetadata()
    pages: tuple[ReaderPageView, ...] = ()
    navigation: tuple[ReaderNavigationEntry, ...] = ()
    warnings: tuple[ReaderWarning, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "pages", tuple(self.pages))
        object.__setattr__(self, "navigation", tuple(self.navigation))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True, slots=True)
class ReaderContinuation:
    """Ordered, nonpersistent continuation separate from stable location identity."""

    location: ReaderLocation
    page_order: int


@dataclass(frozen=True, slots=True)
class ReaderContentChunk:
    """A bounded application result; pagination and transport are out of scope."""

    document_ref: DocumentRef
    candidate_id: ContentCandidateId
    candidate_schema_id: str
    candidate_schema_version: int
    pages: tuple[ReaderPageView, ...]
    has_more: bool
    contract_version: str = READER_APPLICATION_CONTRACT_VERSION
    continuation: ReaderContinuation | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "pages", tuple(self.pages))
