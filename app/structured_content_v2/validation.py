from __future__ import annotations

from collections import Counter, defaultdict

from app.source_units import SourceUnitRecoveryState

from .model import (
    ContentRecoveryStateV2,
    ContentNodeV2,
    StructuredContentCandidateV2,
)


def _assert_unique(values: list[str], name: str) -> None:
    duplicates = sorted(item for item, count in Counter(values).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate {name}: {', '.join(duplicates)}")


def _validate_anchor_refs(candidate: StructuredContentCandidateV2, unit_ids: set[str]) -> None:
    def check(anchor, owner_unit_ids: set[str] | None, label: str) -> None:
        if anchor.source_unit_id not in unit_ids:
            raise ValueError(f"{label} anchor references missing source unit: {anchor.source_unit_id}")
        if owner_unit_ids is not None and anchor.source_unit_id not in owner_unit_ids:
            raise ValueError(f"{label} anchor references a source unit not owned by the object")

    for node in candidate.nodes:
        owned = set(node.source_unit_ids)
        for anchor in node.source_anchors:
            check(anchor, owned, f"node {node.node_id}")
    for evidence in candidate.evidence:
        owned = {evidence.source_unit_id} if evidence.source_unit_id is not None else None
        for anchor in evidence.source_anchors:
            check(anchor, owned, f"evidence {evidence.evidence_id}")
    for asset in candidate.assets:
        owned = set(asset.source_unit_ids)
        for anchor in asset.source_anchors:
            check(anchor, owned, f"asset {asset.asset_id}")


def _validate_hierarchy(nodes: tuple[ContentNodeV2, ...]) -> None:
    node_by_id = {node.node_id: node for node in nodes}
    for node in nodes:
        if node.parent_id == node.node_id:
            raise ValueError(f"node {node.node_id} cannot parent itself")
        if node.parent_id is not None and node.parent_id not in node_by_id:
            raise ValueError(f"node {node.node_id} references missing parent {node.parent_id}")

    state: dict[str, int] = {}

    def visit(node_id: str) -> None:
        marker = state.get(node_id, 0)
        if marker == 1:
            raise ValueError("content hierarchy contains a cycle")
        if marker == 2:
            return
        state[node_id] = 1
        parent_id = node_by_id[node_id].parent_id
        if parent_id is not None:
            visit(parent_id)
        state[node_id] = 2

    for node_id in node_by_id:
        visit(node_id)

    sibling_orders: dict[str | None, set[int]] = defaultdict(set)
    for node in nodes:
        orders = sibling_orders[node.parent_id]
        if node.sibling_order in orders:
            parent = node.parent_id or "<root>"
            raise ValueError(f"duplicate sibling_order {node.sibling_order} under {parent}")
        orders.add(node.sibling_order)


def _validate_asset_rendition_ownership(candidate: StructuredContentCandidateV2) -> None:
    rendition_ids_by_asset: dict[str, list[str]] = defaultdict(list)
    for rendition in candidate.renditions:
        rendition_ids_by_asset[rendition.asset_id].append(rendition.rendition_id)

    for asset in candidate.assets:
        declared = list(asset.rendition_ids)
        _assert_unique(declared, f"rendition_id in asset {asset.asset_id}")
        expected = rendition_ids_by_asset.get(asset.asset_id, [])
        if set(declared) != set(expected):
            missing = sorted(set(expected) - set(declared))
            extra = sorted(set(declared) - set(expected))
            detail = []
            if missing:
                detail.append(f"missing owned renditions {missing}")
            if extra:
                detail.append(f"lists renditions owned by another asset {extra}")
            raise ValueError(
                f"asset {asset.asset_id} rendition registry does not match rendition ownership: "
                + "; ".join(detail)
            )


def _validate_references(candidate: StructuredContentCandidateV2) -> None:
    unit_ids = {item.source_unit.source_unit_id for item in candidate.source_units}
    evidence_ids = {item.evidence_id for item in candidate.evidence}
    asset_ids = {item.asset_id for item in candidate.assets}
    warning_ids = {item.warning_id for item in candidate.warnings}
    rendition_ids = {item.rendition_id for item in candidate.renditions}

    for item in candidate.source_units:
        missing_evidence = set(item.evidence_ids) - evidence_ids
        missing_warnings = set(item.warning_ids) - warning_ids
        if missing_evidence:
            raise ValueError(f"source unit references missing evidence: {sorted(missing_evidence)}")
        if missing_warnings:
            raise ValueError(f"source unit references missing warnings: {sorted(missing_warnings)}")

    for node in candidate.nodes:
        missing_units = set(node.source_unit_ids) - unit_ids
        if missing_units:
            raise ValueError(f"node {node.node_id} references missing source units: {sorted(missing_units)}")
        if set(node.evidence_ids) - evidence_ids:
            raise ValueError(f"node {node.node_id} references missing evidence")
        if set(node.asset_ids) - asset_ids:
            raise ValueError(f"node {node.node_id} references missing assets")
        if set(node.warning_ids) - warning_ids:
            raise ValueError(f"node {node.node_id} references missing warnings")

    for evidence in candidate.evidence:
        if evidence.source_unit_id is not None and evidence.source_unit_id not in unit_ids:
            raise ValueError(f"evidence {evidence.evidence_id} references missing source unit")
        if evidence.warning_ref is not None and evidence.warning_ref not in warning_ids:
            raise ValueError(f"evidence {evidence.evidence_id} references missing warning")

    for warning in candidate.warnings:
        if set(warning.evidence_ids) - evidence_ids:
            raise ValueError(f"warning {warning.warning_id} references missing evidence")

    for asset in candidate.assets:
        if set(asset.source_unit_ids) - unit_ids:
            raise ValueError(f"asset {asset.asset_id} references missing source units")
        if set(asset.evidence_ids) - evidence_ids:
            raise ValueError(f"asset {asset.asset_id} references missing evidence")
        if set(asset.rendition_ids) - rendition_ids:
            raise ValueError(f"asset {asset.asset_id} references missing renditions")

    for rendition in candidate.renditions:
        if rendition.asset_id not in asset_ids:
            raise ValueError(f"rendition {rendition.rendition_id} references missing asset")

    _validate_asset_rendition_ownership(candidate)

    if set(candidate.recovery_summary.warning_ids) - warning_ids:
        raise ValueError("recovery summary references missing warnings")

    _validate_anchor_refs(candidate, unit_ids)


def _validate_recovery_summary(candidate: StructuredContentCandidateV2) -> None:
    summary = candidate.recovery_summary
    states = Counter(item.source_unit.recovery_state for item in candidate.source_units)
    expected = {
        "total_source_units": len(candidate.source_units),
        "complete_source_units": states[SourceUnitRecoveryState.COMPLETE],
        "degraded_source_units": states[SourceUnitRecoveryState.DEGRADED],
        "no_usable_semantic_content_source_units": states[SourceUnitRecoveryState.NO_USABLE_SEMANTIC_CONTENT],
        "unavailable_source_units": states[SourceUnitRecoveryState.UNAVAILABLE],
    }
    for field_name, expected_value in expected.items():
        if getattr(summary, field_name) != expected_value:
            raise ValueError(f"recovery summary {field_name} must be {expected_value}")

    if not candidate.source_units:
        expected_state = ContentRecoveryStateV2.COMPLETE
    elif states[SourceUnitRecoveryState.UNAVAILABLE] == len(candidate.source_units):
        expected_state = ContentRecoveryStateV2.UNAVAILABLE
    elif states[SourceUnitRecoveryState.COMPLETE] == len(candidate.source_units):
        expected_state = ContentRecoveryStateV2.COMPLETE
    else:
        expected_state = ContentRecoveryStateV2.DEGRADED
    if summary.state is not expected_state:
        raise ValueError(f"recovery summary state must be {expected_state.value}")


def _validate_durable_renditions(candidate: StructuredContentCandidateV2) -> None:
    forbidden_fragments = (
        "http://",
        "https://",
        "file://",
        "signature=",
        "x-amz-signature",
        "x-amz-credential",
        "token=",
    )
    for rendition in candidate.renditions:
        lowered = rendition.artifact_ref.lower()
        if any(fragment in lowered for fragment in forbidden_fragments):
            raise ValueError(f"rendition {rendition.rendition_id} has a transient or local artifact_ref")


def validate_candidate_v2(candidate: StructuredContentCandidateV2) -> StructuredContentCandidateV2:
    source_units = [item.source_unit for item in candidate.source_units]
    _assert_unique([item.source_unit_id for item in source_units], "source_unit_id")
    if len({item.source_order for item in source_units}) != len(source_units):
        raise ValueError("source_unit source_order values must be unique")
    _assert_unique([item.node_id for item in candidate.nodes], "node_id")
    _assert_unique([item.evidence_id for item in candidate.evidence], "evidence_id")
    _assert_unique([item.asset_id for item in candidate.assets], "asset_id")
    _assert_unique([item.rendition_id for item in candidate.renditions], "rendition_id")
    _assert_unique([item.warning_id for item in candidate.warnings], "warning_id")

    _validate_hierarchy(candidate.nodes)
    _validate_references(candidate)
    _validate_recovery_summary(candidate)
    _validate_durable_renditions(candidate)
    return candidate
