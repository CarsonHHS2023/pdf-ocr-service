from __future__ import annotations
from app.structured_content.enums import AssetRecoveryState, ContentNodeType, PageRecoveryState
from app.structured_content.model import AssetReference, FigureAttributes, HeadingAttributes, TableAttributes, StructuredContentCandidate
from app.structured_document.types import StructuredDocument
from .reader_v2 import make_heading_line, make_image_marker, serialize_reader_content_stream_v2
from .types import *
from .validation import validate_projection, validate_projection_input

_TEXT_NODE_TYPES = {ContentNodeType.PARAGRAPH, ContentNodeType.LIST_ITEM, ContentNodeType.CAPTION, ContentNodeType.FORMULA, ContentNodeType.UNKNOWN}
_OMIT_TYPES = {ContentNodeType.HEADER, ContentNodeType.FOOTER, ContentNodeType.FOOTNOTE}

def _asset_compatible(asset: AssetReference | None) -> bool:
    if asset is None or asset.recovery_state is not AssetRecoveryState.AVAILABLE: return False
    unsafe = str(asset.asset_id) + " " + (asset.media_type or "") + " " + (asset.checksum or "") + " " + repr(asset.extensions)
    return not any(t in unsafe for t in ("http://", "https://", "file://", "/tmp/", "X-Amz-Signature"))

def project_structured_document(document: StructuredDocument, *, candidate: StructuredContentCandidate, projection_type: ProjectionType = ProjectionType.READER_CONTENT_STREAM_V2, policy: ProjectionPolicy = DEFAULT_PROJECTION_POLICY) -> ReaderContentStreamV2Projection:
    validate_projection_input(document, candidate, ProjectionType(projection_type), SUPPORTED_READER_CONTENT_STREAM_V2_PROJECTION_VERSION)
    if policy.projection_policy_version != SUPPORTED_PROJECTION_POLICY_VERSION: raise UnsupportedProjectionVersion("unsupported projection policy version")
    nodes={n.node_id:n for n in candidate.nodes}; pages={p.page_id:p for p in candidate.pages}; assets={a.asset_id:a for a in candidate.assets}
    entries=[]; losses=[]
    def loss(code, node=None, asset=None, detail=""):
        losses.append(ProjectionLoss(len(losses), code, source_page_ref=(node.page_id if node else None), source_node_ref=(node.node_id if node else None), source_asset_ref=(asset.asset_id if asset else None), evidence_refs=(node.evidence_ids if node else ()), detail=detail))
    for page in document.pages:
        cp = pages[page.source_page_id]
        if cp.recovery_state in (PageRecoveryState.DEGRADED, PageRecoveryState.PARTIAL, PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT, PageRecoveryState.UNAVAILABLE):
            losses.append(ProjectionLoss(len(losses), ProjectionLossCode.RECOVERY_NOT_EXPRESSIBLE_IN_STREAM, source_page_ref=cp.page_id, evidence_refs=cp.evidence_ids, detail=cp.recovery_state.value))
        for ref in page.reading_order_node_refs:
            node=nodes[ref]; text=(node.text or "").strip()
            if node.node_type in (ContentNodeType.HEADING, ContentNodeType.SECTION):
                if not text: continue
                level = 2
                if isinstance(node.attributes, HeadingAttributes): level = node.attributes.level
                entries.append(ReaderContentStreamEntry(len(entries), ReaderContentStreamEntryType.HEADING, make_heading_line(text, level), node.page_id, node.node_id, evidence_refs=node.evidence_ids))
                continue
            if node.node_type is ContentNodeType.LIST:
                loss(ProjectionLossCode.STRUCTURE_DROPPED, node, detail="list container omitted")
                if node.parent_id is not None: loss(ProjectionLossCode.LIST_NESTING_DROPPED, node)
                continue
            if node.node_type is ContentNodeType.TABLE:
                asset_id = node.attributes.rendered_asset_id if isinstance(node.attributes, TableAttributes) else (node.asset_ids[0] if node.asset_ids else None)
                asset = assets.get(asset_id) if asset_id is not None else None
                if _asset_compatible(asset): entries.append(ReaderContentStreamEntry(len(entries), ReaderContentStreamEntryType.IMAGE_MARKER, make_image_marker(asset.asset_id), node.page_id, node.node_id, asset.asset_id, node.evidence_ids))
                else: loss(ProjectionLossCode.ASSET_UNAVAILABLE, node, None, detail="table rendered asset unavailable")
                loss(ProjectionLossCode.TABLE_STRUCTURE_DROPPED, node, asset)
                continue
            if node.node_type is ContentNodeType.FIGURE:
                asset_id = node.attributes.rendered_asset_id if isinstance(node.attributes, FigureAttributes) else (node.asset_ids[0] if node.asset_ids else None)
                asset=assets.get(asset_id) if asset_id is not None else None
                if _asset_compatible(asset): entries.append(ReaderContentStreamEntry(len(entries), ReaderContentStreamEntryType.IMAGE_MARKER, make_image_marker(asset.asset_id), node.page_id, node.node_id, asset.asset_id, node.evidence_ids))
                else: loss(ProjectionLossCode.ASSET_UNAVAILABLE, node, None, detail="figure asset unavailable")
                continue
            if node.node_type in _OMIT_TYPES and not policy.include_headers_footers:
                loss(ProjectionLossCode.HEADER_FOOTER_OMITTED, node, detail=node.node_type.value)
                continue
            if node.node_type in _TEXT_NODE_TYPES or node.node_type in _OMIT_TYPES:
                if text: entries.append(ReaderContentStreamEntry(len(entries), ReaderContentStreamEntryType.PARAGRAPH, text, node.page_id, node.node_id, evidence_refs=node.evidence_ids))
                if node.node_type is ContentNodeType.LIST_ITEM and node.parent_id is not None:
                    parent=nodes.get(node.parent_id)
                    if parent and parent.parent_id is not None: loss(ProjectionLossCode.LIST_NESTING_DROPPED, node)
                continue
            loss(ProjectionLossCode.UNSUPPORTED_NODE_TYPE, node, detail=node.node_type.value)
    recovery=ProjectionRecoverySummary(candidate.recovery_summary.state.value, candidate.recovery_summary.total_pages, candidate.recovery_summary.degraded_pages, candidate.recovery_summary.unavailable_pages, candidate.recovery_summary.no_usable_semantic_content_pages, warning_refs=candidate.recovery_summary.warning_ids, no_usable_page_refs=tuple(p.page_id for p in candidate.pages if p.recovery_state is PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT), degraded_page_refs=tuple(p.page_id for p in candidate.pages if p.recovery_state is PageRecoveryState.DEGRADED))
    proj=ReaderContentStreamV2Projection(ProjectionType.READER_CONTENT_STREAM_V2, SUPPORTED_PROJECTION_SCHEMA_VERSION, SUPPORTED_READER_CONTENT_STREAM_V2_PROJECTION_VERSION, policy, SourceDocumentRef(document.document_ref, document.source_candidate_id, document.source_candidate_schema_id, document.source_candidate_schema_version, document.source_candidate_lineage_key, document.schema_version, document.assembly_policy_version), serialize_reader_content_stream_v2(tuple(entries)), tuple(entries), tuple(losses), recovery)
    validate_projection(proj, document=document, candidate=candidate)
    return proj
