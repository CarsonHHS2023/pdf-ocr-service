from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from app.structured_content.identity import AssetId, ContentCandidateId, ContentNodeId, ContentPageId, DocumentRef, EvidenceReferenceId

SUPPORTED_PROJECTION_SCHEMA_VERSION = 1
SUPPORTED_READER_CONTENT_STREAM_V2_PROJECTION_VERSION = 1
SUPPORTED_PROJECTION_POLICY_VERSION = 1

class ProjectionType(str, Enum):
    READER_CONTENT_STREAM_V2 = "reader_content_stream_v2"
class ReaderContentStreamEntryType(str, Enum):
    HEADING = "heading"; PARAGRAPH = "paragraph"; IMAGE_MARKER = "image_marker"
class ProjectionLossCode(str, Enum):
    STRUCTURE_DROPPED = "structure_dropped"; LIST_NESTING_DROPPED = "list_nesting_dropped"; TABLE_STRUCTURE_DROPPED = "table_structure_dropped"; ASSET_UNAVAILABLE = "asset_unavailable"; HEADER_FOOTER_OMITTED = "header_footer_omitted"; UNSUPPORTED_NODE_TYPE = "unsupported_node_type"; RECOVERY_NOT_EXPRESSIBLE_IN_STREAM = "recovery_not_expressible_in_stream"; EVIDENCE_NOT_EXPRESSIBLE_IN_STREAM = "evidence_not_expressible_in_stream"

@dataclass(frozen=True, slots=True)
class ProjectionPolicy:
    projection_policy_version:int = SUPPORTED_PROJECTION_POLICY_VERSION
    include_headers_footers:bool = False

DEFAULT_PROJECTION_POLICY = ProjectionPolicy()

@dataclass(frozen=True, slots=True)
class SourceDocumentRef:
    document_ref: DocumentRef; source_candidate_id: ContentCandidateId; source_candidate_schema_id: str; source_candidate_schema_version: int; source_candidate_lineage_key: object; structured_document_schema_version: int; assembly_policy_version: int

@dataclass(frozen=True, slots=True)
class ReaderContentStreamEntry:
    entry_index:int; entry_type:ReaderContentStreamEntryType; text:str; source_page_ref:ContentPageId|None=None; source_node_ref:ContentNodeId|None=None; source_asset_ref:AssetId|None=None; evidence_refs:tuple[EvidenceReferenceId,...]=()
    def __post_init__(self): object.__setattr__(self, 'evidence_refs', tuple(self.evidence_refs))

@dataclass(frozen=True, slots=True)
class ProjectionLoss:
    loss_index:int; code:ProjectionLossCode; source_page_ref:ContentPageId|None=None; source_node_ref:ContentNodeId|None=None; source_asset_ref:AssetId|None=None; evidence_refs:tuple[EvidenceReferenceId,...]=(); detail:str=""
    def __post_init__(self): object.__setattr__(self, 'evidence_refs', tuple(self.evidence_refs))

@dataclass(frozen=True, slots=True)
class ProjectionRecoverySummary:
    state:str; total_pages:int; degraded_pages:int; unavailable_pages:int; no_usable_semantic_content_pages:int; warning_refs:tuple[object,...]=(); no_usable_page_refs:tuple[ContentPageId,...]=(); degraded_page_refs:tuple[ContentPageId,...]=()
    def __post_init__(self):
        object.__setattr__(self, 'warning_refs', tuple(self.warning_refs)); object.__setattr__(self, 'no_usable_page_refs', tuple(self.no_usable_page_refs)); object.__setattr__(self, 'degraded_page_refs', tuple(self.degraded_page_refs))

@dataclass(frozen=True, slots=True)
class ReaderContentStreamV2Projection:
    projection_type:ProjectionType; projection_schema_version:int; projection_version:int; projection_policy:ProjectionPolicy; source:SourceDocumentRef; payload:str; entries:tuple[ReaderContentStreamEntry,...]; losses:tuple[ProjectionLoss,...]; recovery:ProjectionRecoverySummary
    def __post_init__(self): object.__setattr__(self, 'entries', tuple(self.entries)); object.__setattr__(self, 'losses', tuple(self.losses))
