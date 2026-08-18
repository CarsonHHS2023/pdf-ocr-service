from __future__ import annotations

import unicodedata
from decimal import Decimal
from typing import Any, Mapping, NoReturn

from app.processing.structured_result.models import StructuredProcessingResult, StructuredPageStatus
from app.processing.structured_result.validation import StructuredResultValidationError, validate_structured_processing_result
from app.structured_content.enums import AssetRecoveryState, AssetRenditionRole, AssetRole, ContentNodeType, ContentRecoveryState, EvidenceKind, NodeRecoveryState, PageRecoveryState, WarningSeverity
from app.structured_content.identity import AssetId, AssetRenditionId, ContentCandidateId, ContentLineageKey, ContentNodeId, ContentPageId, DocumentRef, EvidenceReferenceId, ProcessingRunRef, RawResultRef, SourceFileRef, StructuredProcessingResultRef, TransformationPolicyRef, TransformerRef
from app.structured_content.model import AssetReference, AssetRenditionReference, CaptionAttributes, CoordinateFrame, ContentNode, ContentPage, ContentRecoverySummary, ContentWarning, EvidenceReference, FigureAttributes, FormulaAttributes, HeadingAttributes, ListAttributes, ListItemAttributes, NormalizedBoundingBox, PageDimensions, SourceLocation, StructuredContentCandidate, TableAttributes, TableCell, TableStructure
from app.structured_content.validation import validate_content_candidate

from .errors import InvalidStructuredProcessingResult, InvalidTransformationContext, MissingTransformationContext, StructuredContentValidationFailed, TransformationInvariantViolation, TransformationNotImplemented, UnsupportedMappingVersion, UnsupportedStructuredProcessingResultVersion, UnsupportedTransformationPolicyVersion
from .types import DEFAULT_TRANSFORMATION_POLICY, SUPPORTED_MAPPING_VERSION, SUPPORTED_SPR_SCHEMA_VERSION, SUPPORTED_TRANSFORMATION_POLICY_VERSION, TransformationContext, TransformationPolicy

SUPPORTED_SPR_NODE_TYPE_TO_CONTENT_NODE_TYPE: Mapping[str, ContentNodeType] = {
    "title": ContentNodeType.HEADING,
    "heading": ContentNodeType.HEADING,
    "paragraph": ContentNodeType.PARAGRAPH,
    "text": ContentNodeType.PARAGRAPH,
    "list": ContentNodeType.LIST,
    "list_item": ContentNodeType.LIST_ITEM,
    "caption": ContentNodeType.CAPTION,
    "formula": ContentNodeType.FORMULA,
    "header": ContentNodeType.HEADER,
    "footer": ContentNodeType.FOOTER,
    "footnote": ContentNodeType.FOOTNOTE,
    "table": ContentNodeType.TABLE,
    "image": ContentNodeType.FIGURE,
    "figure": ContentNodeType.FIGURE,
}
GENERIC_TEXTUAL_SPR_NODE_TYPES = frozenset({"quote", "code", "page_number", "reference", "unknown", "other"})
UNSUPPORTED_SLICE_3D_SPR_NODE_TYPES = frozenset({"table_cell", "diagram", "rendered_table_image", "image_crop"})
SUPPORTED_SPR_OBSERVATION_TYPES = frozenset(SUPPORTED_SPR_NODE_TYPE_TO_CONTENT_NODE_TYPE) | GENERIC_TEXTUAL_SPR_NODE_TYPES | UNSUPPORTED_SLICE_3D_SPR_NODE_TYPES
TRANSFORMER_REF = "atlas.m4.slice3d.spr-to-structured-content"


def _raise_invalid_spr(reason: str, exc: Exception | None = None) -> NoReturn:
    error = InvalidStructuredProcessingResult(reason)
    if exc is None:
        raise error
    raise error from exc


def _validate_context(context: TransformationContext | None) -> None:
    if context is None:
        raise MissingTransformationContext()
    if not isinstance(context, TransformationContext):
        raise InvalidTransformationContext("context must be a TransformationContext")


def _validate_policy(policy: TransformationPolicy) -> None:
    if not isinstance(policy, TransformationPolicy):
        raise UnsupportedTransformationPolicyVersion(policy_version=type(policy).__name__, supported_policy_version=SUPPORTED_TRANSFORMATION_POLICY_VERSION)
    if policy.spr_schema_version != SUPPORTED_SPR_SCHEMA_VERSION:
        raise UnsupportedStructuredProcessingResultVersion(schema_version=policy.spr_schema_version, supported_schema_version=SUPPORTED_SPR_SCHEMA_VERSION)
    if policy.transformation_policy_version != SUPPORTED_TRANSFORMATION_POLICY_VERSION:
        raise UnsupportedTransformationPolicyVersion(policy_version=policy.transformation_policy_version, supported_policy_version=SUPPORTED_TRANSFORMATION_POLICY_VERSION)
    if policy.mapping_version != SUPPORTED_MAPPING_VERSION:
        raise UnsupportedMappingVersion(mapping_version=policy.mapping_version, supported_mapping_version=SUPPORTED_MAPPING_VERSION)


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value.strip())


def _ref(prefix: str, *parts: object) -> str:
    return prefix + ":" + ":".join(_safe(str(part)) for part in parts)


def _bbox(geometry: Any) -> NormalizedBoundingBox | None:
    if geometry is None:
        return None
    if not isinstance(geometry, Mapping):
        raise TransformationInvariantViolation("invalid source geometry")
    values = geometry.get("normalized_bbox")
    if not isinstance(values, list) or len(values) != 4:
        raise TransformationInvariantViolation("invalid source geometry")
    try:
        return NormalizedBoundingBox(*(float(Decimal(str(v))) for v in values))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise TransformationInvariantViolation("invalid source geometry") from exc


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        raise TransformationInvariantViolation("mapped text node lacks text")
    text = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in text or any((ord(ch) < 32 and ch not in "\n\t") for ch in text):
        raise TransformationInvariantViolation("mapped text contains unsupported control characters")
    return text


def _node_text(node: Mapping[str, Any], observations: Mapping[str, Mapping[str, Any]]) -> str:
    if "text" in node:
        return _normalize_text(node["text"])
    for oid in node.get("observation_ids", ()):
        content = observations.get(oid, {}).get("content", {})
        if isinstance(content, Mapping) and "text" in content:
            return _normalize_text(content["text"])
    raise TransformationInvariantViolation("mapped text node lacks text")


def _kind(node: Mapping[str, Any], observations: Mapping[str, Mapping[str, Any]]) -> str:
    raw = node.get("node_type")
    if raw in SUPPORTED_SPR_OBSERVATION_TYPES:
        return str(raw)
    for oid in node.get("observation_ids", ()):
        otype = observations.get(oid, {}).get("observation_type")
        if otype in SUPPORTED_SPR_OBSERVATION_TYPES:
            return str(otype)
    return str(raw or "unknown")


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or value < 1:
        raise TransformationInvariantViolation(f"invalid table {name}")
    return value


def _nonnegative_index(value: Any, name: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise TransformationInvariantViolation(f"invalid table {name}")
    return value


def _asset_ref(context: TransformationContext, source_asset_id: str) -> AssetId:
    return AssetId(_ref("sca", context.candidate_id, source_asset_id))


def _is_durable_artifact(ref: Any) -> bool:
    if not isinstance(ref, str) or not ref.strip():
        return False
    low = ref.lower()
    return not (low.startswith(("http://", "https://", "file://")) or "signature=" in low or "x-amz-" in low or "token=" in low)


def _asset_role(kind: str, node_kind: str | None = None) -> AssetRole:
    k = kind.lower()
    if "table" in k or node_kind == "table":
        return AssetRole.TABLE_RENDERING
    if "formula" in k:
        return AssetRole.FORMULA_RENDERING
    return AssetRole.FIGURE


def _rendition_role(value: Any) -> AssetRenditionRole:
    try:
        return AssetRenditionRole(str(value or AssetRenditionRole.ORIGINAL.value))
    except ValueError:
        return AssetRenditionRole.ORIGINAL


def _dimensions(meta: Mapping[str, Any]) -> PageDimensions | None:
    width = meta.get("width"); height = meta.get("height")
    if width is None or height is None:
        return None
    return PageDimensions(float(width), float(height), unit=str(meta.get("unit", "pixel")))


def _table_structure(node: Mapping[str, Any]) -> TableStructure:
    table = node.get("table") if isinstance(node.get("table"), Mapping) else node
    rows = _positive_int(table.get("row_count", table.get("rows")), "row_count")
    cols = _positive_int(table.get("column_count", table.get("columns")), "column_count")
    raw_cells = table.get("cells")
    if not isinstance(raw_cells, list):
        raise TransformationInvariantViolation("invalid table structure")
    occupied: set[tuple[int, int]] = set(); cell_ids: set[str] = set(); cells=[]
    for idx, raw in enumerate(raw_cells):
        if not isinstance(raw, Mapping):
            raise TransformationInvariantViolation("invalid table cell")
        rid = str(raw.get("cell_id", f"cell-{idx}"))
        if rid in cell_ids:
            raise TransformationInvariantViolation("duplicate table cell identity")
        cell_ids.add(rid)
        r = _nonnegative_index(raw.get("row_index"), "row_index"); c = _nonnegative_index(raw.get("column_index"), "column_index")
        rs = _positive_int(raw.get("row_span", 1), "row_span"); cs = _positive_int(raw.get("column_span", 1), "column_span")
        if r + rs > rows or c + cs > cols:
            raise TransformationInvariantViolation("table cell exceeds declared dimensions")
        covered={(rr,cc) for rr in range(r,r+rs) for cc in range(c,c+cs)}
        if occupied & covered:
            raise TransformationInvariantViolation("overlapping table cells")
        occupied |= covered
        ext={}
        if raw.get("header") is not None: ext["org.atlas.transform.header"] = bool(raw.get("header"))
        cells.append(TableCell(r,c,rs,cs,_normalize_text(raw["text"]) if isinstance(raw.get("text"), str) else None, ext))
    return TableStructure(rows, cols, tuple(sorted(cells, key=lambda x:(x.row_index,x.column_index,x.text or ""))))


def _target_type(kind: str) -> ContentNodeType:
    if kind in UNSUPPORTED_SLICE_3D_SPR_NODE_TYPES:
        raise TransformationNotImplemented(f"SPR node type {kind!r} is reserved for M4 Slice 3D table/asset mapping")
    return SUPPORTED_SPR_NODE_TYPE_TO_CONTENT_NODE_TYPE.get(kind, ContentNodeType.UNKNOWN)


def _attrs(kind: str, node: Mapping[str, Any], node_id_map: Mapping[str, ContentNodeId] | None = None, asset_id_map: Mapping[str, AssetId] | None = None) -> Any | None:
    meta = node.get("extensions") if isinstance(node.get("extensions"), Mapping) else {}
    if kind in {"title", "heading"}:
        level = meta.get("level", 1)
        return HeadingAttributes(level=level if isinstance(level, int) and level > 0 else 1)
    if kind == "list":
        ordered = bool(meta.get("ordered", False))
        marker_style = meta.get("marker_style") if isinstance(meta.get("marker_style"), str) else None
        return ListAttributes(ordered=ordered, marker_style=marker_style)
    if kind == "list_item":
        ordinal = meta.get("ordinal")
        return ListItemAttributes(marker=meta.get("marker") if isinstance(meta.get("marker"), str) else None, ordinal=ordinal if isinstance(ordinal, int) and ordinal >= 0 else None)
    if kind == "table":
        rendered = meta.get("rendered_asset_ref") or meta.get("asset_ref")
        rendered_asset_id = asset_id_map.get(str(rendered)) if asset_id_map and rendered else None
        return TableAttributes(structure=_table_structure(node), rendered_asset_id=rendered_asset_id)
    if kind in {"image", "figure"}:
        rendered = meta.get("asset_ref") or meta.get("rendered_asset_ref")
        rendered_asset_id = asset_id_map.get(str(rendered)) if asset_id_map and rendered else None
        caption = meta.get("caption_ref")
        caption_node_id = node_id_map.get(str(caption)) if node_id_map and caption else None
        return FigureAttributes(caption_node_id=caption_node_id, rendered_asset_id=rendered_asset_id)
    if kind == "caption":
        target = meta.get("target_ref")
        target_node_id = node_id_map.get(str(target)) if node_id_map and target else None
        target_asset = meta.get("target_asset_ref")
        target_asset_id = asset_id_map.get(str(target_asset)) if asset_id_map and target_asset else None
        return CaptionAttributes(target_node_id=target_node_id, target_asset_id=target_asset_id, extensions={"org.atlas.transform.unresolved_target_ref": str(target)} if target and target_node_id is None else {})
    if kind == "formula":
        formula = node.get("formula") if isinstance(node.get("formula"), Mapping) else {}
        notation = formula.get("notation") or ("latex" if formula.get("latex") else None)
        role = formula.get("role")
        ext = {}
        asset_ref = formula.get("asset_ref") or meta.get("asset_ref")
        if asset_ref and asset_id_map and str(asset_ref) in asset_id_map:
            ext["org.atlas.transform.asset_id"] = asset_id_map[str(asset_ref)].value
        return FormulaAttributes(notation=notation if isinstance(notation, str) else None, role=role if isinstance(role, str) else None, extensions=ext)
    return None


def _order(node: Mapping[str, Any], idx: int) -> tuple[Any, ...]:
    ordinal = node.get("ordinal")
    return (0 if isinstance(ordinal, int) else 1, ordinal if isinstance(ordinal, int) else 0, str(node.get("node_id")), idx)


def transform_spr_to_candidate(spr: StructuredProcessingResult, *, context: TransformationContext, policy: TransformationPolicy = DEFAULT_TRANSFORMATION_POLICY) -> StructuredContentCandidate:
    if not isinstance(spr, StructuredProcessingResult):
        _raise_invalid_spr("expected StructuredProcessingResult")
    schema_version = spr.data.get("schema_version")
    if schema_version != SUPPORTED_SPR_SCHEMA_VERSION:
        raise UnsupportedStructuredProcessingResultVersion(schema_version=schema_version, supported_schema_version=SUPPORTED_SPR_SCHEMA_VERSION)
    try:
        validate_structured_processing_result(spr.data)
    except StructuredResultValidationError as exc:
        _raise_invalid_spr("invalid structured processing result", exc)
    _validate_context(context)
    _validate_policy(policy)

    data = spr.data
    pages_in = sorted(data.get("pages", ()), key=lambda p: (p["page_index"], str(p["page_id"])))
    observations = {o["observation_id"]: o for o in data.get("normalized_observations", ())}
    evidence_by_id = {e["evidence_link_id"]: e for e in data.get("evidence_links", ())}
    page_id_map = {p["page_id"]: ContentPageId(_ref("scp", context.candidate_id, p["page_id"], p["page_index"])) for p in pages_in}
    raw_result_ref = RawResultRef(data["raw_result"]["raw_result_id"]) if isinstance(data.get("raw_result"), Mapping) and data["raw_result"].get("raw_result_id") else None
    spr_ref = StructuredProcessingResultRef(str(data["result_id"])) if data.get("result_id") else None

    nodes_in = list(data.get("nodes", ()))
    if len({n["node_id"] for n in nodes_in}) != len(nodes_in):
        raise TransformationInvariantViolation("duplicate source node identity")
    by_node_id = {n["node_id"]: n for n in nodes_in}
    for n in nodes_in:
        kind = _kind(n, observations)
        _target_type(kind)
        if len(n.get("page_ids", ())) != 1:
            raise TransformationInvariantViolation("mapped node must reference exactly one page")
        parent_id = n.get("parent_id")
        if parent_id == n.get("node_id"):
            raise TransformationInvariantViolation("source hierarchy contains self-parent")
        if parent_id is not None and parent_id in by_node_id:
            parent = by_node_id[parent_id]
            if parent.get("page_ids") != n.get("page_ids"):
                raise TransformationInvariantViolation("source hierarchy crosses pages")
            if _target_type(_kind(parent, observations)) in {ContentNodeType.UNKNOWN}:
                raise TransformationNotImplemented("SPR hierarchy references unsupported parent kind")
    for n in nodes_in:
        seen: set[str] = set()
        current = n
        while current.get("parent_id") is not None and current.get("parent_id") in by_node_id:
            pid = current["parent_id"]
            if pid in seen:
                raise TransformationInvariantViolation("source hierarchy contains a cycle")
            seen.add(pid)
            current = by_node_id[pid]

    evidence: list[EvidenceReference] = []
    evidence_seen: set[str] = set()
    nodes: list[ContentNode] = []
    node_id_map = {n["node_id"]: ContentNodeId(_ref("scn", context.candidate_id, n["node_id"])) for n in nodes_in}
    source_assets = {str(a.get("asset_id")): a for a in data.get("assets", ()) if isinstance(a, Mapping) and a.get("asset_id")}
    asset_id_map = {aid: _asset_ref(context, aid) for aid in sorted(source_assets)}
    page_nodes: dict[str, list[ContentNodeId]] = {p["page_id"]: [] for p in pages_in}
    child_counts: dict[str, int] = {}
    warnings: list[ContentWarning] = []
    page_warning_ids: dict[str, list[str]] = {p["page_id"]: [] for p in pages_in}
    node_ordered = sorted(nodes_in, key=lambda item: (str(item.get("page_ids", [""])[0]), _order(item, nodes_in.index(item))))
    for idx, n in enumerate(node_ordered):
        kind = _kind(n, observations)
        page_id = n["page_ids"][0]
        source_locations = (SourceLocation(source_page_index=next(p["page_index"] for p in pages_in if p["page_id"] == page_id), bounding_box=_bbox(n.get("geometry"))),)
        ev_ids=[]
        for evid in sorted(n.get("evidence_link_ids", ()), key=str):
            e = evidence_by_id.get(evid)
            if e and evid not in evidence_seen:
                evidence_seen.add(evid)
                box = _bbox(e.get("geometry"))
                evidence.append(EvidenceReference(EvidenceReferenceId(_ref("sce", context.candidate_id, evid)), EvidenceKind.SOURCE_LOCATION, source_file_ref=SourceFileRef(context.source_file_ref) if context.source_file_ref else None, source_page_index=e.get("source_page_index"), source_location=SourceLocation(e.get("source_page_index", source_locations[0].source_page_index), box), raw_result_ref=raw_result_ref, structured_processing_result_ref=spr_ref, spr_node_ref=str(n["node_id"]), spr_observation_ref=str((n.get("observation_ids") or [""])[0]) or None, spr_evidence_ref=str(evid)))
            ev_ids.append(EvidenceReferenceId(_ref("sce", context.candidate_id, evid)))
        target_type = _target_type(kind)
        parent_ref = node_id_map.get(n.get("parent_id"))
        warn_ids: list[str] = []
        recovery = NodeRecoveryState.COMPLETE
        if target_type is ContentNodeType.UNKNOWN:
            wid = _ref("scw", context.candidate_id, page_id, n["node_id"], "UNKNOWN_ELEMENT_KIND")
            warnings.append(ContentWarning(wid, "UNKNOWN_ELEMENT_KIND", WarningSeverity.WARNING, f"$.nodes[{n['node_id']!r}]", "Unknown SPR node kind preserved as generic content.", evidence_ids=tuple(ev_ids), details={"source_node_id": str(n["node_id"]), "source_kind": kind}))
            warn_ids.append(wid); page_warning_ids[page_id].append(wid); recovery = NodeRecoveryState.DEGRADED
        if kind == "list_item" and parent_ref is None:
            wid = _ref("scw", context.candidate_id, page_id, n["node_id"], "MISSING_PARENT")
            warnings.append(ContentWarning(wid, "MISSING_PARENT", WarningSeverity.WARNING, f"$.nodes[{n['node_id']!r}].parent_id", "Recoverable source parent was missing; node was kept as a page root.", evidence_ids=tuple(ev_ids), details={"source_node_id": str(n["node_id"])}))
            warn_ids.append(wid); page_warning_ids[page_id].append(wid); recovery = NodeRecoveryState.RECOVERED
        if kind == "caption" and isinstance(n.get("extensions"), Mapping) and n["extensions"].get("target_ref") and str(n["extensions"].get("target_ref")) not in node_id_map:
            wid = _ref("scw", context.candidate_id, page_id, n["node_id"], "UNRESOLVED_CAPTION_ASSOCIATION")
            warnings.append(ContentWarning(wid, "UNRESOLVED_CAPTION_ASSOCIATION", WarningSeverity.WARNING, f"$.nodes[{n['node_id']!r}].attributes", "Caption target was not resolved; caption text was preserved.", evidence_ids=tuple(ev_ids), details={"source_node_id": str(n["node_id"])}))
            warn_ids.append(wid); page_warning_ids[page_id].append(wid); recovery = NodeRecoveryState.DEGRADED
        missing_asset_ref = isinstance(n.get("extensions"), Mapping) and any(ref and str(ref) not in source_assets for ref in (n["extensions"].get("asset_ref"), n["extensions"].get("rendered_asset_ref")))
        if missing_asset_ref:
            wid = _ref("scw", context.candidate_id, page_id, n["node_id"], "MISSING_ASSET_REFERENCE")
            warnings.append(ContentWarning(wid, "MISSING_ASSET_REFERENCE", WarningSeverity.WARNING, f"$.nodes[{n['node_id']!r}].asset_ids", "Referenced logical asset was missing; content node was preserved without fabricating asset data.", evidence_ids=tuple(ev_ids), details={"source_node_id": str(n["node_id"])}))
            warn_ids.append(wid); page_warning_ids[page_id].append(wid); recovery = NodeRecoveryState.DEGRADED
        sibling_order = child_counts.get(str(n.get("parent_id")), 0) if parent_ref is not None else len(page_nodes[page_id])
        if parent_ref is not None: child_counts[str(n.get("parent_id"))] = sibling_order + 1
        node_asset_refs = []
        if isinstance(n.get("extensions"), Mapping):
            for ref in (n["extensions"].get("asset_ref"), n["extensions"].get("rendered_asset_ref")):
                if ref and str(ref) in source_assets:
                    node_asset_refs.append(asset_id_map[str(ref)])
        cn = ContentNode(node_id_map[n["node_id"]], ContentLineageKey(_ref("lineage", context.candidate_lineage_seed, n["node_id"])), target_type, page_id_map[page_id], sibling_order, recovery, parent_id=parent_ref, text=(_normalize_text(n["text"]) if kind in {"table", "image", "figure"} and isinstance(n.get("text"), str) and n.get("text") else (_node_text(n, observations) if kind not in {"table", "image", "figure"} else None)), attributes=_attrs(kind, n, node_id_map, asset_id_map), source_locations=source_locations, evidence_ids=tuple(ev_ids), asset_ids=tuple(sorted(set(node_asset_refs), key=lambda a:a.value)), warning_ids=tuple(warn_ids), extensions={"org.atlas.transform.source_kind": kind} if target_type is ContentNodeType.UNKNOWN else {})
        nodes.append(cn)
        if parent_ref is None:
            page_nodes[page_id].append(cn.node_id)

    warnings = sorted(warnings, key=lambda w: (w.scope_path, w.code, w.warning_id))
    pages=[]
    for order, p in enumerate(pages_in):
        if p["status"] is StructuredPageStatus.NO_USABLE_SEMANTIC_CONTENT:
            state = PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT
        elif page_warning_ids[p["page_id"]]:
            state = PageRecoveryState.DEGRADED
        else:
            state = PageRecoveryState.COMPLETE
        pages.append(ContentPage(page_id_map[p["page_id"]], p["page_index"], order, state, tuple(page_nodes[p["page_id"]]), page_label=str(p.get("page_number")) if p.get("page_number") is not None else None, dimensions=PageDimensions(float(p["width"]), float(p["height"])), rotation_degrees=float(p.get("rotation_degrees", 0)), coordinate_frame=CoordinateFrame(origin=str(p.get("coordinate_origin", "top_left")), unit="normalized", rotation_applied=p.get("coordinate_frame") == "displayed_post_rotation"), warning_ids=tuple(page_warning_ids[p["page_id"]])))

    assets=[]
    renditions=[]
    for aid, asset in sorted(source_assets.items()):
        page_index = asset.get("source_page_index") if isinstance(asset.get("source_page_index"), int) else None
        source_location = SourceLocation(page_index) if page_index is not None else None
        asset_rendition_ids=[]
        source_renditions = asset.get("renditions", ()) if isinstance(asset.get("renditions"), list) else ()
        for rendition_order, raw_rendition in enumerate(source_renditions):
            if not isinstance(raw_rendition, Mapping):
                continue
            artifact_ref = raw_rendition.get("artifact_ref") or raw_rendition.get("storage_ref") or raw_rendition.get("location_ref")
            if not _is_durable_artifact(artifact_ref):
                continue
            source_rendition_id = raw_rendition.get("rendition_id") or f"rendition-{rendition_order}"
            rendition_id = AssetRenditionId(_ref("scr", context.candidate_id, aid, source_rendition_id))
            renditions.append(AssetRenditionReference(
                rendition_id=rendition_id,
                asset_id=asset_id_map[aid],
                role=_rendition_role(raw_rendition.get("role")),
                media_type=raw_rendition.get("media_type") if isinstance(raw_rendition.get("media_type"), str) else (asset.get("media_type") if isinstance(asset.get("media_type"), str) else None),
                checksum=raw_rendition.get("checksum") if isinstance(raw_rendition.get("checksum"), str) else None,
                dimensions=_dimensions(raw_rendition),
                artifact_ref=str(artifact_ref),
                recovery_state=AssetRecoveryState.AVAILABLE,
                rebuildable=bool(raw_rendition.get("rebuildable", False)),
            ))
            asset_rendition_ids.append(rendition_id)
        assets.append(AssetReference(
            asset_id_map[aid],
            _asset_role(str(asset.get("kind", "figure"))),
            AssetRecoveryState.AVAILABLE if asset_rendition_ids else AssetRecoveryState.DEGRADED,
            source_location=source_location,
            media_type=asset.get("media_type") if isinstance(asset.get("media_type"), str) else None,
            checksum=asset.get("checksum") if isinstance(asset.get("checksum"), str) else None,
            byte_size=asset.get("byte_size") if isinstance(asset.get("byte_size"), int) else None,
            dimensions=_dimensions(asset),
            rendition_refs=tuple(asset_rendition_ids),
            caption=asset.get("caption") if isinstance(asset.get("caption"), str) else None,
            alt_text=asset.get("alt_text") if isinstance(asset.get("alt_text"), str) else None,
            description=asset.get("description") if isinstance(asset.get("description"), str) else None,
        ))
    assets = sorted(assets, key=lambda a: a.asset_id.value)
    renditions = sorted(renditions, key=lambda r: r.rendition_id.value)
    summary_state = ContentRecoveryState.COMPLETE if all(p.recovery_state is PageRecoveryState.COMPLETE for p in pages) else (ContentRecoveryState.DEGRADED if any(p.recovery_state is PageRecoveryState.DEGRADED for p in pages) else ContentRecoveryState.PARTIAL)
    candidate = StructuredContentCandidate("atlas.structured-content-candidate", 1, DocumentRef(context.document_ref), ContentCandidateId(context.candidate_id), ContentLineageKey(context.candidate_lineage_seed), ContentRecoverySummary(summary_state, len(pages), complete_pages=sum(p.recovery_state is PageRecoveryState.COMPLETE for p in pages), degraded_pages=sum(p.recovery_state is PageRecoveryState.DEGRADED for p in pages), no_usable_semantic_content_pages=sum(p.recovery_state is PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT for p in pages), warning_ids=tuple(w.warning_id for w in warnings), recovery_policy_ref="m4-slice-3d"), tuple(pages), tuple(nodes), tuple(sorted(evidence, key=lambda e: e.evidence_id.value)), tuple(assets), tuple(warnings), {"org.atlas.transform.mapping_version": policy.mapping_version, "org.atlas.transform.policy_version": policy.transformation_policy_version}, transformer_ref=TransformerRef(TRANSFORMER_REF), transformation_policy_ref=TransformationPolicyRef(f"m4-slice-3d-policy-v{policy.transformation_policy_version}"), processing_run_ref=ProcessingRunRef(context.processing_run_ref) if context.processing_run_ref else None, raw_result_ref=raw_result_ref, structured_processing_result_ref=spr_ref, renditions=tuple(renditions))
    result = validate_content_candidate(candidate)
    if not result.is_valid:
        raise StructuredContentValidationFailed(result.blocking_issue_count)
    return candidate
