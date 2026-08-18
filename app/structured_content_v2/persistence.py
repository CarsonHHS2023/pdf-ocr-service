from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select

from app.models import decode_json_text, encode_json_text
from app.models_v2 import (
    StructuredContentAnchorV2Record as AnchorRow,
    StructuredContentAssetEvidenceV2Record as AssetEvidenceRow,
    StructuredContentAssetRenditionV2Record as RenditionRow,
    StructuredContentAssetSourceUnitV2Record as AssetUnitRow,
    StructuredContentAssetV2Record as AssetRow,
    StructuredContentCandidateV2Record as CandidateRow,
    StructuredContentEvidenceV2Record as EvidenceRow,
    StructuredContentNodeAssetV2Record as NodeAssetRow,
    StructuredContentNodeEvidenceV2Record as NodeEvidenceRow,
    StructuredContentNodeSourceUnitV2Record as NodeUnitRow,
    StructuredContentNodeV2Record as NodeRow,
    StructuredContentNodeWarningV2Record as NodeWarningRow,
    StructuredContentSourceUnitEvidenceV2Record as UnitEvidenceRow,
    StructuredContentSourceUnitV2Record as UnitRow,
    StructuredContentSourceUnitWarningV2Record as UnitWarningRow,
    StructuredContentWarningEvidenceV2Record as WarningEvidenceRow,
    StructuredContentWarningV2Record as WarningRow,
)
from app.source_units import (
    DomAnchor,
    SourceUnit,
    SourceUnitDimensions,
    SourceUnitKind,
    SourceUnitRecoveryState,
    SpatialAnchor,
    TemporalAnchor,
    TextSpanAnchor,
)
from app.structured_content_v2.model import (
    AssetRecoveryStateV2,
    AssetReferenceV2,
    AssetRenditionReferenceV2,
    AssetRenditionRoleV2,
    AssetRoleV2,
    ContentNodeTypeV2,
    ContentNodeV2,
    ContentRecoveryStateV2,
    ContentRecoverySummaryV2,
    ContentWarningV2,
    EvidenceReferenceV2,
    NodeRecoveryStateV2,
    StructuredContentCandidateV2,
    StructuredSourceUnit,
    WarningSeverityV2,
)
from app.structured_content_v2.validation import validate_candidate_v2


def _id() -> str:
    return str(uuid.uuid4())


def _dump(value):
    return encode_json_text(value) if value is not None else None


def _load(value):
    return decode_json_text(value) if value is not None else None


def _anchor_row(candidate_record_id: str, owner_type: str, owner_record_id: str, order: int, anchor, unit_rows):
    row = AnchorRow(
        id=_id(),
        candidate_id=candidate_record_id,
        source_unit_record_id=unit_rows[anchor.source_unit_id].id,
        owner_type=owner_type,
        owner_record_id=owner_record_id,
        anchor_order=order,
    )
    if isinstance(anchor, SpatialAnchor):
        row.anchor_kind = "spatial"
        row.bbox_left, row.bbox_top, row.bbox_right, row.bbox_bottom = anchor.left, anchor.top, anchor.right, anchor.bottom
    elif isinstance(anchor, TextSpanAnchor):
        row.anchor_kind = "text_span"
        row.text_start, row.text_end = anchor.start, anchor.end
    elif isinstance(anchor, TemporalAnchor):
        row.anchor_kind = "temporal"
        row.start_ms, row.end_ms = anchor.start_ms, anchor.end_ms
    elif isinstance(anchor, DomAnchor):
        row.anchor_kind = "dom"
        row.dom_path, row.dom_text_start, row.dom_text_end = anchor.path, anchor.text_start, anchor.text_end
    else:
        raise TypeError(f"unsupported anchor: {type(anchor)!r}")
    return row


def _anchor_from_row(row: AnchorRow, unit_public_id: str):
    if row.anchor_kind == "spatial":
        return SpatialAnchor(unit_public_id, row.bbox_left, row.bbox_top, row.bbox_right, row.bbox_bottom)
    if row.anchor_kind == "text_span":
        return TextSpanAnchor(unit_public_id, row.text_start, row.text_end)
    if row.anchor_kind == "temporal":
        return TemporalAnchor(unit_public_id, row.start_ms, row.end_ms)
    if row.anchor_kind == "dom":
        return DomAnchor(unit_public_id, row.dom_path, row.dom_text_start, row.dom_text_end)
    raise ValueError(f"unsupported persisted anchor kind: {row.anchor_kind}")


def _ordered_ids_by_owner(
    session,
    association_cls,
    owner_cls,
    candidate_record_id: str,
    left_column: str,
    right_column: str,
    public_by_record: dict[str, str],
) -> dict[str, tuple[str, ...]]:
    """Load one association kind for the whole candidate in one SQL query."""
    left = getattr(association_cls, left_column)
    rows = session.execute(
        select(association_cls)
        .join(owner_cls, left == owner_cls.id)
        .where(owner_cls.candidate_id == candidate_record_id)
        .order_by(left, association_cls.association_order, association_cls.id)
    ).scalars().all()
    grouped = defaultdict(list)
    for row in rows:
        grouped[getattr(row, left_column)].append(
            public_by_record[getattr(row, right_column)]
        )
    return {owner_id: tuple(values) for owner_id, values in grouped.items()}


def insert_candidate_v2(session, candidate: StructuredContentCandidateV2) -> None:
    validate_candidate_v2(candidate)
    summary = candidate.recovery_summary
    c = CandidateRow(
        id=_id(), candidate_id=candidate.candidate_id, document_id=candidate.document_ref,
        lineage_key=candidate.lineage_key, schema_id=candidate.schema_id, schema_version=candidate.schema_version,
        transformer_ref=candidate.transformer_ref, transformation_policy_ref=candidate.transformation_policy_ref,
        processing_run_ref=candidate.processing_run_ref, raw_result_ref=candidate.raw_result_ref,
        structured_processing_result_ref=candidate.structured_processing_result_ref,
        recovery_state=summary.state.value, total_source_unit_count=summary.total_source_units,
        complete_source_unit_count=summary.complete_source_units, degraded_source_unit_count=summary.degraded_source_units,
        no_usable_source_unit_count=summary.no_usable_semantic_content_source_units,
        unavailable_source_unit_count=summary.unavailable_source_units,
        recovery_warning_ids_json=_dump(list(summary.warning_ids)), recovery_policy_ref=summary.recovery_policy_ref,
    )
    session.add(c); session.flush()

    unit_rows = {}
    for item in candidate.source_units:
        unit = item.source_unit
        row = UnitRow(
            id=_id(), candidate_id=c.id, source_unit_id=unit.source_unit_id, kind=unit.kind.value,
            source_order=unit.source_order, source_ref=unit.source_ref, recovery_state=unit.recovery_state.value,
            width=unit.dimensions.width if unit.dimensions else None,
            height=unit.dimensions.height if unit.dimensions else None,
            dimension_unit=unit.dimensions.unit if unit.dimensions else None,
            rotation_degrees=unit.rotation_degrees,
            source_span_start=unit.source_span.start if unit.source_span else None,
            source_span_end=unit.source_span.end if unit.source_span else None,
            duration_ms=unit.duration_ms,
        )
        session.add(row); unit_rows[unit.source_unit_id] = row
    session.flush()

    evidence_rows = {}
    for item in candidate.evidence:
        row = EvidenceRow(
            id=_id(), candidate_id=c.id, evidence_id=item.evidence_id,
            source_unit_record_id=unit_rows[item.source_unit_id].id if item.source_unit_id else None,
            processing_run_ref=item.processing_run_ref, raw_result_ref=item.raw_result_ref,
            structured_processing_result_ref=item.structured_processing_result_ref,
            spr_node_ref=item.spr_node_ref, spr_observation_ref=item.spr_observation_ref,
            warning_ref=item.warning_ref, metadata_json=_dump(item.metadata),
        )
        session.add(row); evidence_rows[item.evidence_id] = row
    session.flush()

    warning_rows = {}
    for item in candidate.warnings:
        row = WarningRow(
            id=_id(), candidate_id=c.id, warning_id=item.warning_id, code=item.code,
            severity=item.severity.value, scope_ref=item.scope_ref, safe_summary=item.safe_summary,
            recoverable=item.recoverable, details_json=_dump(item.details),
        )
        session.add(row); warning_rows[item.warning_id] = row
    session.flush()

    asset_rows = {}
    for item in candidate.assets:
        row = AssetRow(
            id=_id(), candidate_id=c.id, asset_id=item.asset_id, role=item.role.value,
            recovery_state=item.recovery_state.value, caption=item.caption, alt_text=item.alt_text,
            metadata_json=_dump(item.metadata),
        )
        session.add(row); asset_rows[item.asset_id] = row
    session.flush()

    node_rows = {}
    for item in candidate.nodes:
        row = NodeRow(
            id=_id(), candidate_id=c.id, node_id=item.node_id, lineage_key=item.lineage_key,
            node_type=item.node_type.value, sibling_order=item.sibling_order,
            recovery_state=item.recovery_state.value, text=item.text,
            heading_level=item.heading_level, metadata_json=_dump(item.metadata),
        )
        session.add(row); node_rows[item.node_id] = row
    session.flush()
    for item in candidate.nodes:
        if item.parent_id is not None:
            node_rows[item.node_id].parent_node_record_id = node_rows[item.parent_id].id
    session.flush()

    rendition_rows = {}
    for item in candidate.renditions:
        row = RenditionRow(
            id=_id(), candidate_id=c.id, rendition_id=item.rendition_id,
            asset_record_id=asset_rows[item.asset_id].id, role=item.role.value,
            artifact_ref=item.artifact_ref, media_type=item.media_type, checksum=item.checksum,
            recovery_state=item.recovery_state.value, rebuildable=item.rebuildable,
        )
        session.add(row); rendition_rows[item.rendition_id] = row
    session.flush()

    for item in candidate.source_units:
        left = unit_rows[item.source_unit.source_unit_id]
        for order, eid in enumerate(item.evidence_ids):
            session.add(UnitEvidenceRow(id=_id(), source_unit_record_id=left.id, evidence_record_id=evidence_rows[eid].id, association_order=order))
        for order, wid in enumerate(item.warning_ids):
            session.add(UnitWarningRow(id=_id(), source_unit_record_id=left.id, warning_record_id=warning_rows[wid].id, association_order=order))

    for item in candidate.nodes:
        left = node_rows[item.node_id]
        for order, uid in enumerate(item.source_unit_ids):
            session.add(NodeUnitRow(id=_id(), node_record_id=left.id, source_unit_record_id=unit_rows[uid].id, association_order=order))
        for order, eid in enumerate(item.evidence_ids):
            session.add(NodeEvidenceRow(id=_id(), node_record_id=left.id, evidence_record_id=evidence_rows[eid].id, association_order=order))
        for order, aid in enumerate(item.asset_ids):
            session.add(NodeAssetRow(id=_id(), node_record_id=left.id, asset_record_id=asset_rows[aid].id, association_order=order))
        for order, wid in enumerate(item.warning_ids):
            session.add(NodeWarningRow(id=_id(), node_record_id=left.id, warning_record_id=warning_rows[wid].id, association_order=order))
        for order, anchor in enumerate(item.source_anchors):
            session.add(_anchor_row(c.id, "node", left.id, order, anchor, unit_rows))

    for item in candidate.evidence:
        left = evidence_rows[item.evidence_id]
        for order, anchor in enumerate(item.source_anchors):
            session.add(_anchor_row(c.id, "evidence", left.id, order, anchor, unit_rows))

    for item in candidate.assets:
        left = asset_rows[item.asset_id]
        for order, uid in enumerate(item.source_unit_ids):
            session.add(AssetUnitRow(id=_id(), asset_record_id=left.id, source_unit_record_id=unit_rows[uid].id, association_order=order))
        for order, eid in enumerate(item.evidence_ids):
            session.add(AssetEvidenceRow(id=_id(), asset_record_id=left.id, evidence_record_id=evidence_rows[eid].id, association_order=order))
        for order, anchor in enumerate(item.source_anchors):
            session.add(_anchor_row(c.id, "asset", left.id, order, anchor, unit_rows))

    for item in candidate.warnings:
        left = warning_rows[item.warning_id]
        for order, eid in enumerate(item.evidence_ids):
            session.add(WarningEvidenceRow(id=_id(), warning_record_id=left.id, evidence_record_id=evidence_rows[eid].id, association_order=order))
    session.flush()


def reconstruct_candidate_v2(session, candidate_id: str) -> StructuredContentCandidateV2:
    c = session.execute(select(CandidateRow).where(CandidateRow.candidate_id == candidate_id)).scalar_one_or_none()
    if c is None:
        raise KeyError(candidate_id)

    units = session.execute(select(UnitRow).where(UnitRow.candidate_id == c.id).order_by(UnitRow.source_order, UnitRow.source_unit_id)).scalars().all()
    unit_public_by_record = {row.id: row.source_unit_id for row in units}

    evidence_rows = session.execute(select(EvidenceRow).where(EvidenceRow.candidate_id == c.id).order_by(EvidenceRow.evidence_id)).scalars().all()
    warning_rows = session.execute(select(WarningRow).where(WarningRow.candidate_id == c.id).order_by(WarningRow.warning_id)).scalars().all()
    asset_rows = session.execute(select(AssetRow).where(AssetRow.candidate_id == c.id).order_by(AssetRow.asset_id)).scalars().all()
    node_rows = session.execute(select(NodeRow).where(NodeRow.candidate_id == c.id).order_by(NodeRow.id)).scalars().all()
    rendition_rows = session.execute(select(RenditionRow).where(RenditionRow.candidate_id == c.id).order_by(RenditionRow.rendition_id)).scalars().all()

    evidence_public = {row.id: row.evidence_id for row in evidence_rows}
    warning_public = {row.id: row.warning_id for row in warning_rows}
    asset_public = {row.id: row.asset_id for row in asset_rows}
    node_public = {row.id: row.node_id for row in node_rows}

    anchor_rows = session.execute(select(AnchorRow).where(AnchorRow.candidate_id == c.id).order_by(AnchorRow.owner_type, AnchorRow.owner_record_id, AnchorRow.anchor_order)).scalars().all()
    anchors = defaultdict(list)
    for row in anchor_rows:
        anchors[(row.owner_type, row.owner_record_id)].append(_anchor_from_row(row, unit_public_by_record[row.source_unit_record_id]))

    unit_evidence_ids = _ordered_ids_by_owner(
        session, UnitEvidenceRow, UnitRow, c.id,
        "source_unit_record_id", "evidence_record_id", evidence_public,
    )
    unit_warning_ids = _ordered_ids_by_owner(
        session, UnitWarningRow, UnitRow, c.id,
        "source_unit_record_id", "warning_record_id", warning_public,
    )
    warning_evidence_ids = _ordered_ids_by_owner(
        session, WarningEvidenceRow, WarningRow, c.id,
        "warning_record_id", "evidence_record_id", evidence_public,
    )
    asset_unit_ids = _ordered_ids_by_owner(
        session, AssetUnitRow, AssetRow, c.id,
        "asset_record_id", "source_unit_record_id", unit_public_by_record,
    )
    asset_evidence_ids = _ordered_ids_by_owner(
        session, AssetEvidenceRow, AssetRow, c.id,
        "asset_record_id", "evidence_record_id", evidence_public,
    )
    node_unit_ids = _ordered_ids_by_owner(
        session, NodeUnitRow, NodeRow, c.id,
        "node_record_id", "source_unit_record_id", unit_public_by_record,
    )
    node_evidence_ids = _ordered_ids_by_owner(
        session, NodeEvidenceRow, NodeRow, c.id,
        "node_record_id", "evidence_record_id", evidence_public,
    )
    node_asset_ids = _ordered_ids_by_owner(
        session, NodeAssetRow, NodeRow, c.id,
        "node_record_id", "asset_record_id", asset_public,
    )
    node_warning_ids = _ordered_ids_by_owner(
        session, NodeWarningRow, NodeRow, c.id,
        "node_record_id", "warning_record_id", warning_public,
    )

    source_units = []
    for row in units:
        dimensions = SourceUnitDimensions(row.width, row.height, row.dimension_unit or "pixel") if row.width is not None else None
        source_span = TextSpanAnchor(row.source_unit_id, row.source_span_start, row.source_span_end) if row.source_span_start is not None else None
        unit = SourceUnit(
            source_unit_id=row.source_unit_id, kind=SourceUnitKind(row.kind), source_order=row.source_order,
            source_ref=row.source_ref, recovery_state=SourceUnitRecoveryState(row.recovery_state),
            dimensions=dimensions, rotation_degrees=row.rotation_degrees, source_span=source_span, duration_ms=row.duration_ms,
        )
        source_units.append(StructuredSourceUnit(
            unit,
            unit_evidence_ids.get(row.id, ()),
            unit_warning_ids.get(row.id, ()),
        ))

    evidence = tuple(
        EvidenceReferenceV2(
            evidence_id=row.evidence_id,
            source_unit_id=unit_public_by_record[row.source_unit_record_id] if row.source_unit_record_id else None,
            source_anchors=tuple(anchors[("evidence", row.id)]),
            processing_run_ref=row.processing_run_ref, raw_result_ref=row.raw_result_ref,
            structured_processing_result_ref=row.structured_processing_result_ref,
            spr_node_ref=row.spr_node_ref, spr_observation_ref=row.spr_observation_ref,
            warning_ref=row.warning_ref, metadata=_load(row.metadata_json),
        ) for row in evidence_rows
    )

    warnings = tuple(
        ContentWarningV2(
            warning_id=row.warning_id, code=row.code, severity=WarningSeverityV2(row.severity),
            scope_ref=row.scope_ref, safe_summary=row.safe_summary,
            evidence_ids=warning_evidence_ids.get(row.id, ()),
            recoverable=row.recoverable, details=_load(row.details_json),
        ) for row in warning_rows
    )

    rendition_ids_by_asset = defaultdict(list)
    renditions = []
    for row in rendition_rows:
        asset_id = asset_public[row.asset_record_id]
        rendition_ids_by_asset[asset_id].append(row.rendition_id)
        renditions.append(AssetRenditionReferenceV2(
            rendition_id=row.rendition_id, asset_id=asset_id, role=AssetRenditionRoleV2(row.role),
            artifact_ref=row.artifact_ref, media_type=row.media_type, checksum=row.checksum,
            recovery_state=AssetRecoveryStateV2(row.recovery_state), rebuildable=row.rebuildable,
        ))

    assets = tuple(
        AssetReferenceV2(
            asset_id=row.asset_id, role=AssetRoleV2(row.role), recovery_state=AssetRecoveryStateV2(row.recovery_state),
            source_unit_ids=asset_unit_ids.get(row.id, ()),
            source_anchors=tuple(anchors[("asset", row.id)]), rendition_ids=tuple(sorted(rendition_ids_by_asset[row.asset_id])),
            evidence_ids=asset_evidence_ids.get(row.id, ()),
            caption=row.caption, alt_text=row.alt_text, metadata=_load(row.metadata_json),
        ) for row in asset_rows
    )

    nodes = tuple(
        ContentNodeV2(
            node_id=row.node_id, lineage_key=row.lineage_key, node_type=ContentNodeTypeV2(row.node_type),
            source_unit_ids=node_unit_ids.get(row.id, ()),
            sibling_order=row.sibling_order, recovery_state=NodeRecoveryStateV2(row.recovery_state),
            parent_id=node_public[row.parent_node_record_id] if row.parent_node_record_id else None,
            text=row.text, heading_level=row.heading_level, source_anchors=tuple(anchors[("node", row.id)]),
            evidence_ids=node_evidence_ids.get(row.id, ()),
            asset_ids=node_asset_ids.get(row.id, ()),
            warning_ids=node_warning_ids.get(row.id, ()),
            metadata=_load(row.metadata_json),
        ) for row in sorted(node_rows, key=lambda r: (node_public.get(r.parent_node_record_id, ""), r.sibling_order, r.node_id))
    )

    summary = ContentRecoverySummaryV2(
        state=ContentRecoveryStateV2(c.recovery_state), total_source_units=c.total_source_unit_count,
        complete_source_units=c.complete_source_unit_count, degraded_source_units=c.degraded_source_unit_count,
        no_usable_semantic_content_source_units=c.no_usable_source_unit_count,
        unavailable_source_units=c.unavailable_source_unit_count,
        warning_ids=tuple(_load(c.recovery_warning_ids_json) or ()), recovery_policy_ref=c.recovery_policy_ref,
    )
    return validate_candidate_v2(StructuredContentCandidateV2(
        document_ref=c.document_id, candidate_id=c.candidate_id, lineage_key=c.lineage_key,
        recovery_summary=summary, source_units=tuple(source_units), nodes=nodes, evidence=evidence,
        assets=assets, warnings=warnings, renditions=tuple(renditions), transformer_ref=c.transformer_ref,
        transformation_policy_ref=c.transformation_policy_ref, processing_run_ref=c.processing_run_ref,
        raw_result_ref=c.raw_result_ref, structured_processing_result_ref=c.structured_processing_result_ref,
        schema_id=c.schema_id, schema_version=c.schema_version,
    ))