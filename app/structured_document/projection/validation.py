from __future__ import annotations
from app.structured_content.model import SCHEMA_ID as CONTENT_SCHEMA_ID, SCHEMA_VERSION as CONTENT_SCHEMA_VERSION, StructuredContentCandidate
from app.structured_document.types import SUPPORTED_STRUCTURED_DOCUMENT_SCHEMA_VERSION, StructuredDocument
from .errors import InvalidProjectionInput, ProjectionSourceMismatch, ProjectionValidationFailed, UnsupportedProjectionType, UnsupportedProjectionVersion
from .reader_v2 import serialize_reader_content_stream_v2
from .types import ProjectionType, ReaderContentStreamV2Projection, SUPPORTED_PROJECTION_POLICY_VERSION, SUPPORTED_PROJECTION_SCHEMA_VERSION, SUPPORTED_READER_CONTENT_STREAM_V2_PROJECTION_VERSION

_FORBIDDEN = ("Bearer ", "api_key", "sk-", "X-Amz-Signature", "http://", "https://", "file://", "/tmp/", "raw_result", "provider_payload", "structured_processing_result_payload")

def validate_projection_input(document: StructuredDocument, candidate: StructuredContentCandidate, projection_type: ProjectionType, projection_version: int) -> None:
    if not isinstance(document, StructuredDocument): raise InvalidProjectionInput("expected StructuredDocument")
    if not isinstance(candidate, StructuredContentCandidate): raise InvalidProjectionInput("expected StructuredContentCandidate")
    try: ptype = ProjectionType(projection_type)
    except Exception as exc: raise UnsupportedProjectionType("unsupported projection type") from exc
    if ptype is not ProjectionType.READER_CONTENT_STREAM_V2: raise UnsupportedProjectionType("unsupported projection type")
    if projection_version != SUPPORTED_READER_CONTENT_STREAM_V2_PROJECTION_VERSION: raise UnsupportedProjectionVersion("unsupported projection version")
    if document.schema_version != SUPPORTED_STRUCTURED_DOCUMENT_SCHEMA_VERSION: raise UnsupportedProjectionVersion("unsupported structured document version")
    if candidate.schema_id != CONTENT_SCHEMA_ID or candidate.schema_version != CONTENT_SCHEMA_VERSION: raise UnsupportedProjectionVersion("unsupported source candidate version")
    if document.source_candidate_id != candidate.candidate_id or document.document_ref != candidate.document_ref or document.source_candidate_lineage_key != candidate.lineage_key: raise ProjectionSourceMismatch("structured document source candidate mismatch")
    if document.source_candidate_schema_id != candidate.schema_id or document.source_candidate_schema_version != candidate.schema_version: raise ProjectionSourceMismatch("structured document source schema mismatch")

def validate_projection(projection: ReaderContentStreamV2Projection, *, document: StructuredDocument, candidate: StructuredContentCandidate) -> None:
    validate_projection_input(document, candidate, projection.projection_type, projection.projection_version)
    if projection.projection_schema_version != SUPPORTED_PROJECTION_SCHEMA_VERSION: raise ProjectionValidationFailed("unsupported projection schema version")
    if projection.projection_policy.projection_policy_version != SUPPORTED_PROJECTION_POLICY_VERSION: raise ProjectionValidationFailed("unsupported projection policy version")
    if projection.source.document_ref != candidate.document_ref or projection.source.source_candidate_id != candidate.candidate_id: raise ProjectionValidationFailed("projection source mismatch")
    if projection.payload != serialize_reader_content_stream_v2(projection.entries): raise ProjectionValidationFailed("payload serialization mismatch")
    indexes = [e.entry_index for e in projection.entries]
    if indexes != list(range(len(indexes))): raise ProjectionValidationFailed("entry indexes must be contiguous")
    loss_indexes = [l.loss_index for l in projection.losses]
    if loss_indexes != list(range(len(loss_indexes))): raise ProjectionValidationFailed("loss indexes must be contiguous")
    node_ids={n.node_id for n in candidate.nodes}; page_ids={p.page_id for p in candidate.pages}; asset_ids={a.asset_id for a in candidate.assets}; ev_ids={e.evidence_id for e in candidate.evidence}
    for e in projection.entries:
        if e.source_node_ref is not None and e.source_node_ref not in node_ids: raise ProjectionValidationFailed("entry source node missing")
        if e.source_page_ref is not None and e.source_page_ref not in page_ids: raise ProjectionValidationFailed("entry source page missing")
        if e.source_asset_ref is not None and e.source_asset_ref not in asset_ids: raise ProjectionValidationFailed("entry source asset missing")
        if any(ref not in ev_ids for ref in e.evidence_refs): raise ProjectionValidationFailed("entry evidence missing")
    for l in projection.losses:
        if l.source_node_ref is not None and l.source_node_ref not in node_ids: raise ProjectionValidationFailed("loss source node missing")
        if l.source_page_ref is not None and l.source_page_ref not in page_ids: raise ProjectionValidationFailed("loss source page missing")
        if l.source_asset_ref is not None and l.source_asset_ref not in asset_ids: raise ProjectionValidationFailed("loss source asset missing")
        if any(ref not in ev_ids for ref in l.evidence_refs): raise ProjectionValidationFailed("loss evidence missing")
    blob = repr(projection)
    if any(token in blob for token in _FORBIDDEN): raise ProjectionValidationFailed("projection contains unsafe payload")
