from __future__ import annotations

from dataclasses import dataclass

from app.structured_content.identity import (
    ContentCandidateId,
    ContentLineageKey,
    ContentNodeId,
    ContentPageId,
    DocumentRef,
    ProcessingRunRef,
    RawResultRef,
    StructuredProcessingResultRef,
    TransformationPolicyRef,
    TransformerRef,
)
from app.structured_content.model import SCHEMA_ID as STRUCTURED_CONTENT_SCHEMA_ID
from app.structured_content.model import SCHEMA_VERSION as STRUCTURED_CONTENT_SCHEMA_VERSION
from app.structured_content.model import StructuredContentCandidate

SUPPORTED_STRUCTURED_DOCUMENT_SCHEMA_VERSION = 1
SUPPORTED_ASSEMBLY_POLICY_VERSION = 1


@dataclass(frozen=True, slots=True)
class StructuredDocumentAssemblyPolicy:
    structured_document_schema_version: int = SUPPORTED_STRUCTURED_DOCUMENT_SCHEMA_VERSION
    assembly_policy_version: int = SUPPORTED_ASSEMBLY_POLICY_VERSION


DEFAULT_STRUCTURED_DOCUMENT_ASSEMBLY_POLICY = StructuredDocumentAssemblyPolicy()


@dataclass(frozen=True, slots=True)
class StructuredDocumentPageView:
    source_page_id: ContentPageId
    source_page_index: int
    page_order: int
    root_node_refs: tuple[ContentNodeId, ...] = ()
    reading_order_node_refs: tuple[ContentNodeId, ...] = ()
    evidence_refs: tuple[object, ...] = ()
    warning_refs: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.source_page_id, ContentPageId):
            raise ValueError("source_page_id must be ContentPageId")
        if not isinstance(self.source_page_index, int) or self.source_page_index < 0:
            raise ValueError("source_page_index must be nonnegative")
        if not isinstance(self.page_order, int) or self.page_order < 0:
            raise ValueError("page_order must be nonnegative")
        object.__setattr__(self, "root_node_refs", tuple(self.root_node_refs))
        object.__setattr__(self, "reading_order_node_refs", tuple(self.reading_order_node_refs))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        object.__setattr__(self, "warning_refs", tuple(self.warning_refs))


@dataclass(frozen=True, slots=True)
class StructuredDocumentNodeView:
    source_node_id: ContentNodeId
    parent_ref: ContentNodeId | None
    child_refs: tuple[ContentNodeId, ...]
    traversal_index: int
    section_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_node_id, ContentNodeId):
            raise ValueError("source_node_id must be ContentNodeId")
        if self.parent_ref is not None and not isinstance(self.parent_ref, ContentNodeId):
            raise ValueError("parent_ref must be ContentNodeId")
        if not isinstance(self.traversal_index, int) or self.traversal_index < 0:
            raise ValueError("traversal_index must be nonnegative")
        object.__setattr__(self, "child_refs", tuple(self.child_refs))


@dataclass(frozen=True, slots=True)
class StructuredDocument:
    schema_version: int
    document_ref: DocumentRef
    source_candidate_id: ContentCandidateId
    source_candidate_schema_id: str
    source_candidate_schema_version: int
    source_candidate_lineage_key: ContentLineageKey
    assembly_policy_version: int
    assembly_policy: StructuredDocumentAssemblyPolicy
    source_transformer_ref: TransformerRef | None = None
    source_transformation_policy_ref: TransformationPolicyRef | None = None
    source_processing_run_ref: ProcessingRunRef | None = None
    source_raw_result_ref: RawResultRef | None = None
    source_structured_processing_result_ref: StructuredProcessingResultRef | None = None
    pages: tuple[StructuredDocumentPageView, ...] = ()
    node_views: tuple[StructuredDocumentNodeView, ...] = ()
    document_reading_order_refs: tuple[ContentNodeId, ...] = ()

    @classmethod
    def from_candidate_identity(
        cls,
        candidate: StructuredContentCandidate,
        *,
        policy: StructuredDocumentAssemblyPolicy = DEFAULT_STRUCTURED_DOCUMENT_ASSEMBLY_POLICY,
        schema_version: int = SUPPORTED_STRUCTURED_DOCUMENT_SCHEMA_VERSION,
    ) -> "StructuredDocument":
        return cls(
            schema_version=schema_version,
            document_ref=candidate.document_ref,
            source_candidate_id=candidate.candidate_id,
            source_candidate_schema_id=candidate.schema_id,
            source_candidate_schema_version=candidate.schema_version,
            source_candidate_lineage_key=candidate.lineage_key,
            assembly_policy_version=policy.assembly_policy_version,
            assembly_policy=policy,
            source_transformer_ref=candidate.transformer_ref,
            source_transformation_policy_ref=candidate.transformation_policy_ref,
            source_processing_run_ref=candidate.processing_run_ref,
            source_raw_result_ref=candidate.raw_result_ref,
            source_structured_processing_result_ref=candidate.structured_processing_result_ref,
        )
