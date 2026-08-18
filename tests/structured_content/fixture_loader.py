from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.structured_content.enums import (
    AssetRecoveryState, AssetRenditionRole, AssetRole, ContentNodeType,
    ContentRecoveryState, EvidenceKind, NodeRecoveryState, PageRecoveryState,
    WarningSeverity,
)
from app.structured_content.identity import (
    AssetId, AssetRenditionId, ContentCandidateId, ContentLineageKey,
    ContentNodeId, ContentPageId, DocumentRef, EvidenceReferenceId,
    ProcessingRunRef, RawResultRef, SourceFileRef, StructuredProcessingResultRef,
    TransformationPolicyRef, TransformerRef,
)
from app.structured_content.model import (
    AssetReference, CaptionAttributes, ContentNode, ContentPage,
    ContentRecoverySummary, ContentWarning, CoordinateFrame, EvidenceReference,
    FigureAttributes, FormulaAttributes, HeadingAttributes, ListAttributes,
    ListItemAttributes, NormalizedBoundingBox, PageDimensions, SourceLocation,
    SourceTextSpan, StructuredContentCandidate, TableAttributes, TableCell,
    TableStructure,
)


def load_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_manifest(base_path: Path | str) -> dict[str, Any]:
    base = Path(base_path)
    path = base / "manifest.json" if base.is_dir() else base
    return load_json(path)


def load_expected_validation(path: Path | str) -> dict[str, Any]:
    return load_json(path)


def load_expected_canonical(path: Path | str) -> dict[str, Any]:
    return load_json(path)


def _ref(cls: type, value: str | None) -> Any | None:
    return cls(value) if value is not None else None


def _bbox(data: dict[str, Any] | None) -> NormalizedBoundingBox | None:
    return NormalizedBoundingBox(**data) if data is not None else None


def _span(data: dict[str, Any] | None) -> SourceTextSpan | None:
    return SourceTextSpan(**data) if data is not None else None


def _dimensions(data: dict[str, Any] | None) -> PageDimensions | None:
    return PageDimensions(**data) if data is not None else None


def _coordinate_frame(data: dict[str, Any] | None) -> CoordinateFrame | None:
    return CoordinateFrame(**data) if data is not None else None


def _loc(data: dict[str, Any] | None) -> SourceLocation | None:
    if data is None:
        return None
    return SourceLocation(data["source_page_index"], _bbox(data.get("bounding_box")), _span(data.get("text_span")))


def _table_structure(data: dict[str, Any]) -> TableStructure:
    cells = tuple(TableCell(**cell) for cell in data.get("cells", ()))
    return TableStructure(data["row_count"], data["column_count"], cells)


def _node_type(value: str) -> ContentNodeType:
    try:
        return ContentNodeType(value)
    except ValueError as exc:
        raise ValueError(f"unsupported node type: {value}") from exc


def _attrs(node_type: str, data: dict[str, Any] | None) -> Any | None:
    if data is None:
        return None
    data = dict(data)
    attribute_type = data.pop("attribute_type", node_type)
    try:
        kind = ContentNodeType(attribute_type)
    except ValueError as exc:
        raise ValueError(f"unsupported node type: {node_type}") from exc
    if kind is ContentNodeType.HEADING:
        return HeadingAttributes(**data)
    if kind is ContentNodeType.LIST:
        return ListAttributes(**data)
    if kind is ContentNodeType.LIST_ITEM:
        return ListItemAttributes(**data)
    if kind is ContentNodeType.TABLE:
        if "structure" not in data:
            raise ValueError("unsupported attribute shape for table: missing structure")
        return TableAttributes(_table_structure(data["structure"]), rendered_asset_id=_ref(AssetId, data.get("rendered_asset_id")), extensions=data.get("extensions", {}))
    if kind is ContentNodeType.FIGURE:
        return FigureAttributes(caption_node_id=_ref(ContentNodeId, data.get("caption_node_id")), rendered_asset_id=_ref(AssetId, data.get("rendered_asset_id")), extensions=data.get("extensions", {}))
    if kind is ContentNodeType.CAPTION:
        return CaptionAttributes(target_node_id=_ref(ContentNodeId, data.get("target_node_id")), target_asset_id=_ref(AssetId, data.get("target_asset_id")), extensions=data.get("extensions", {}))
    if kind is ContentNodeType.FORMULA:
        return FormulaAttributes(**data)
    if attribute_type != node_type or any(key in data for key in ("level", "ordered", "structure", "caption_node_id", "target_node_id", "notation")):
        raise ValueError(f"unsupported attribute shape for {node_type}")
    return dict(data)


def candidate_from_dict(data: dict[str, Any]) -> StructuredContentCandidate:
    d = deepcopy(data)
    evidence = tuple(EvidenceReference(EvidenceReferenceId(e["evidence_id"]), EvidenceKind(e["kind"]), source_file_ref=_ref(SourceFileRef, e.get("source_file_ref")), source_page_index=e.get("source_page_index"), source_location=_loc(e.get("source_location")), raw_result_ref=_ref(RawResultRef, e.get("raw_result_ref")), structured_processing_result_ref=_ref(StructuredProcessingResultRef, e.get("structured_processing_result_ref")), spr_node_ref=e.get("spr_node_ref"), spr_observation_ref=e.get("spr_observation_ref"), spr_evidence_ref=e.get("spr_evidence_ref"), warning_ref=e.get("warning_ref"), extensions=e.get("extensions", {})) for e in d.get("evidence", ()))
    pages = tuple(ContentPage(ContentPageId(p["page_id"]), p["source_page_index"], p["page_order"], PageRecoveryState(p["recovery_state"]), tuple(ContentNodeId(x) for x in p.get("root_node_ids", ())), page_label=p.get("page_label"), dimensions=_dimensions(p.get("dimensions")), rotation_degrees=p.get("rotation_degrees"), coordinate_frame=_coordinate_frame(p.get("coordinate_frame")), evidence_ids=tuple(EvidenceReferenceId(x) for x in p.get("evidence_ids", ())), warning_ids=tuple(p.get("warning_ids", ())), extensions=p.get("extensions", {})) for p in d.get("pages", ()))
    nodes = tuple(ContentNode(ContentNodeId(n["node_id"]), ContentLineageKey(n["lineage_key"]), _node_type(n["node_type"]), ContentPageId(n["page_id"]), n["sibling_order"], NodeRecoveryState(n["recovery_state"]), parent_id=_ref(ContentNodeId, n.get("parent_id")), text=n.get("text"), attributes=_attrs(n["node_type"], n.get("attributes")), source_locations=tuple(_loc(x) for x in n.get("source_locations", ())), evidence_ids=tuple(EvidenceReferenceId(x) for x in n.get("evidence_ids", ())), asset_ids=tuple(AssetId(x) for x in n.get("asset_ids", ())), warning_ids=tuple(n.get("warning_ids", ())), extensions=n.get("extensions", {})) for n in d.get("nodes", ()))
    assets = tuple(AssetReference(AssetId(a["asset_id"]), AssetRole(a["role"]), AssetRecoveryState(a["recovery_state"]), source_location=_loc(a.get("source_location")), media_type=a.get("media_type"), checksum=a.get("checksum"), byte_size=a.get("byte_size"), dimensions=_dimensions(a.get("dimensions")), rendition_refs=tuple(AssetRenditionId(x) for x in a.get("rendition_refs", ())), evidence_ids=tuple(EvidenceReferenceId(x) for x in a.get("evidence_ids", ())), caption=a.get("caption"), alt_text=a.get("alt_text"), description=a.get("description"), extensions=a.get("extensions", {})) for a in d.get("assets", ()))
    warnings = tuple(ContentWarning(w["warning_id"], w["code"], WarningSeverity(w["severity"]), w["scope_path"], w["safe_summary"], evidence_ids=tuple(EvidenceReferenceId(x) for x in w.get("evidence_ids", ())), recoverable=w.get("recoverable", True), blocking_hint=w.get("blocking_hint"), details=w.get("details", {}), extensions=w.get("extensions", {})) for w in d.get("warnings", ()))
    rs = d["recovery_summary"]
    summary = ContentRecoverySummary(ContentRecoveryState(rs["state"]), rs["total_pages"], rs.get("complete_pages", 0), rs.get("partial_pages", 0), rs.get("degraded_pages", 0), rs.get("unavailable_pages", 0), rs.get("no_usable_semantic_content_pages", 0), tuple(rs.get("warning_ids", ())), rs.get("recovery_policy_ref"))
    return StructuredContentCandidate(d["schema_id"], d["schema_version"], DocumentRef(d["document_ref"]), ContentCandidateId(d["candidate_id"]), ContentLineageKey(d["lineage_key"]), summary, pages, nodes, evidence, assets, warnings, d.get("extensions", {}), transformer_ref=_ref(TransformerRef, d.get("transformer_ref")), transformation_policy_ref=_ref(TransformationPolicyRef, d.get("transformation_policy_ref")), processing_run_ref=_ref(ProcessingRunRef, d.get("processing_run_ref")), raw_result_ref=_ref(RawResultRef, d.get("raw_result_ref")), structured_processing_result_ref=_ref(StructuredProcessingResultRef, d.get("structured_processing_result_ref")))


def load_candidate(path: Path | str) -> StructuredContentCandidate:
    return candidate_from_dict(load_json(path))
