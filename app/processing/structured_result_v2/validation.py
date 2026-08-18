from __future__ import annotations

from collections import Counter

from app.source_units import SourceAnchor

from .model import StructuredProcessingResultV2


def _duplicates(values: list[str]) -> set[str]:
    counts = Counter(values)
    return {value for value, count in counts.items() if count > 1}


def _validate_anchor_unit(anchor: SourceAnchor, known_units: set[str], *, allowed_units: set[str] | None = None) -> None:
    unit_id = anchor.source_unit_id
    if unit_id not in known_units:
        raise ValueError(f"anchor references missing source unit: {unit_id}")
    if allowed_units is not None and unit_id not in allowed_units:
        raise ValueError(f"anchor source unit {unit_id} is outside its owner source units")


def _validate_hierarchy(parent_by_node: dict[str, str | None]) -> None:
    for node_id, parent_id in parent_by_node.items():
        if parent_id == node_id:
            raise ValueError(f"node {node_id} cannot parent itself")
        if parent_id is not None and parent_id not in parent_by_node:
            raise ValueError(f"node {node_id} references missing parent: {parent_id}")

    for node_id in parent_by_node:
        seen: set[str] = set()
        current: str | None = node_id
        while current is not None:
            if current in seen:
                raise ValueError(f"node hierarchy contains a cycle involving {current}")
            seen.add(current)
            current = parent_by_node[current]


def validate_spr_v2(spr: StructuredProcessingResultV2) -> None:
    unit_ids = [unit.source_unit_id for unit in spr.source_units]
    observation_ids = [item.observation_id for item in spr.observations]
    node_ids = [item.node_id for item in spr.nodes]
    evidence_ids = [item.evidence_id for item in spr.evidence]

    for label, values in (
        ("source unit", unit_ids),
        ("observation", observation_ids),
        ("node", node_ids),
        ("evidence", evidence_ids),
    ):
        duplicates = _duplicates(values)
        if duplicates:
            raise ValueError(f"duplicate {label} ids: {sorted(duplicates)}")

    source_orders = [unit.source_order for unit in spr.source_units]
    duplicate_orders = [order for order, count in Counter(source_orders).items() if count > 1]
    if duplicate_orders:
        raise ValueError(f"duplicate source_order values: {sorted(duplicate_orders)}")

    known_units = set(unit_ids)
    known_observations = set(observation_ids)
    known_evidence = set(evidence_ids)

    for observation in spr.observations:
        if observation.source_unit_id not in known_units:
            raise ValueError(
                f"observation {observation.observation_id} references missing source unit: {observation.source_unit_id}"
            )
        for anchor in observation.anchors:
            _validate_anchor_unit(anchor, known_units, allowed_units={observation.source_unit_id})
        for evidence_id in observation.evidence_ids:
            if evidence_id not in known_evidence:
                raise ValueError(
                    f"observation {observation.observation_id} references missing evidence: {evidence_id}"
                )

    parent_by_node = {node.node_id: node.parent_id for node in spr.nodes}
    _validate_hierarchy(parent_by_node)

    for node in spr.nodes:
        allowed_units = set(node.source_unit_ids)
        missing_units = allowed_units - known_units
        if missing_units:
            raise ValueError(f"node {node.node_id} references missing source units: {sorted(missing_units)}")
        for anchor in node.anchors:
            _validate_anchor_unit(anchor, known_units, allowed_units=allowed_units)
        for observation_id in node.observation_ids:
            if observation_id not in known_observations:
                raise ValueError(f"node {node.node_id} references missing observation: {observation_id}")
        for evidence_id in node.evidence_ids:
            if evidence_id not in known_evidence:
                raise ValueError(f"node {node.node_id} references missing evidence: {evidence_id}")

    for evidence in spr.evidence:
        if evidence.source_unit_id is not None and evidence.source_unit_id not in known_units:
            raise ValueError(
                f"evidence {evidence.evidence_id} references missing source unit: {evidence.source_unit_id}"
            )
        allowed_units = {evidence.source_unit_id} if evidence.source_unit_id is not None else None
        for anchor in evidence.anchors:
            _validate_anchor_unit(anchor, known_units, allowed_units=allowed_units)
        if evidence.observation_id is not None and evidence.observation_id not in known_observations:
            raise ValueError(
                f"evidence {evidence.evidence_id} references missing observation: {evidence.observation_id}"
            )
