"""Suppress duplicate visual nodes created by unresolved-node reclassification.

The MinerU/Popo recovery stage can already contain a native figure/table while an
overlapping unknown semantic block is sent through mandatory LLM review. If that
unknown is later reclassified to the same visual kind, publishing both nodes
creates duplicate Reader visuals for one source visual. This bounded pass runs
after semantic refinement and only collapses a reclassified visual when both
nodes are single-page, have unambiguous geometry, share the same parent, and are
near-contained with comparable area.
"""
from __future__ import annotations

from dataclasses import replace

from app.processing.structured_result_v2.model import (
    ProcessingNode,
    ProcessingNodeKind,
    StructuredProcessingResultV2,
)
from app.processing.structured_result_v2.validation import validate_spr_v2
from app.source_units import SpatialAnchor

_NATIVE_VISUAL_RULE = "mineru_popo_visual"
_RECLASSIFIED_VISUAL_RULE = "mineru_popo_semantic_block"
_RECLASSIFIED_ORIGINAL_KIND = "unknown"
_MIN_SMALLER_CONTAINMENT = 0.92
_MIN_AREA_RATIO = 0.45
_VISUAL_KINDS = frozenset({ProcessingNodeKind.FIGURE, ProcessingNodeKind.TABLE})
_POLICY_VERSION = "duplicate_refined_visual_containment_v1"


def _single_spatial_anchor(node: ProcessingNode, source_unit_id: str) -> SpatialAnchor | None:
    matches = tuple(
        anchor
        for anchor in node.anchors
        if isinstance(anchor, SpatialAnchor)
        and anchor.source_unit_id == source_unit_id
    )
    return matches[0] if len(matches) == 1 else None


def _area(anchor: SpatialAnchor) -> float:
    return max(0.0, anchor.right - anchor.left) * max(0.0, anchor.bottom - anchor.top)


def _intersection_area(left: SpatialAnchor, right: SpatialAnchor) -> float:
    width = max(0.0, min(left.right, right.right) - max(left.left, right.left))
    height = max(0.0, min(left.bottom, right.bottom) - max(left.top, right.top))
    return width * height


def _containment_metrics(left: SpatialAnchor, right: SpatialAnchor) -> tuple[float, float]:
    left_area = _area(left)
    right_area = _area(right)
    smaller = min(left_area, right_area)
    larger = max(left_area, right_area)
    if smaller <= 0.0 or larger <= 0.0:
        return 0.0, 0.0
    intersection = _intersection_area(left, right)
    return intersection / smaller, smaller / larger


def _is_native_visual(node: ProcessingNode) -> bool:
    return (
        node.kind in _VISUAL_KINDS
        and (node.metadata or {}).get("recovery_rule") == _NATIVE_VISUAL_RULE
    )


def _is_reclassified_visual(node: ProcessingNode) -> bool:
    metadata = node.metadata or {}
    return (
        node.kind in _VISUAL_KINDS
        and metadata.get("recovery_rule") == _RECLASSIFIED_VISUAL_RULE
        and metadata.get("llm_unresolved_review_original_kind") == _RECLASSIFIED_ORIGINAL_KIND
        and metadata.get("llm_unresolved_review_resolved") is True
    )


def _duplicate_pair(native: ProcessingNode, candidate: ProcessingNode) -> tuple[float, float] | None:
    if not _is_native_visual(native) or not _is_reclassified_visual(candidate):
        return None
    if native.kind is not candidate.kind:
        return None
    if native.parent_id != candidate.parent_id:
        return None
    if len(native.source_unit_ids) != 1 or len(candidate.source_unit_ids) != 1:
        return None
    if native.source_unit_ids[0] != candidate.source_unit_ids[0]:
        return None
    source_unit_id = native.source_unit_ids[0]
    native_anchor = _single_spatial_anchor(native, source_unit_id)
    candidate_anchor = _single_spatial_anchor(candidate, source_unit_id)
    if native_anchor is None or candidate_anchor is None:
        return None
    containment, area_ratio = _containment_metrics(native_anchor, candidate_anchor)
    if containment < _MIN_SMALLER_CONTAINMENT or area_ratio < _MIN_AREA_RATIO:
        return None
    return containment, area_ratio


def collapse_duplicate_refined_visuals(
    spr: StructuredProcessingResultV2,
) -> StructuredProcessingResultV2:
    """Remove only near-contained LLM-reclassified duplicates of native visuals.

    The native visual node is preserved unchanged except for audit metadata. Raw
    observations/evidence remain in SPR v2, so the suppressed candidate is still
    traceable without becoming a second canonical Reader visual. Children of a
    suppressed node are conservatively reparented to the retained native node.
    """

    ordered = sorted(spr.nodes, key=lambda item: (item.order, item.node_id))
    natives = [node for node in ordered if _is_native_visual(node)]
    suppressed_to_keeper: dict[str, tuple[str, float, float]] = {}

    for candidate in ordered:
        if not _is_reclassified_visual(candidate):
            continue
        matches: list[tuple[float, float, ProcessingNode]] = []
        for native in natives:
            metrics = _duplicate_pair(native, candidate)
            if metrics is None:
                continue
            containment, area_ratio = metrics
            matches.append((containment, area_ratio, native))
        if not matches:
            continue
        containment, area_ratio, keeper = max(
            matches,
            key=lambda item: (item[0], item[1], -item[2].order),
        )
        suppressed_to_keeper[candidate.node_id] = (
            keeper.node_id,
            containment,
            area_ratio,
        )

    if not suppressed_to_keeper:
        return spr

    suppressed_by_keeper: dict[str, list[tuple[str, float, float]]] = {}
    for suppressed_id, (keeper_id, containment, area_ratio) in suppressed_to_keeper.items():
        suppressed_by_keeper.setdefault(keeper_id, []).append(
            (suppressed_id, containment, area_ratio)
        )

    kept: list[ProcessingNode] = []
    for node in ordered:
        if node.node_id in suppressed_to_keeper:
            continue
        parent_id = node.parent_id
        if parent_id in suppressed_to_keeper:
            parent_id = suppressed_to_keeper[parent_id][0]
        metadata = dict(node.metadata or {})
        suppressed = suppressed_by_keeper.get(node.node_id)
        if suppressed:
            metadata.update(
                {
                    "duplicate_visual_refinement_policy": _POLICY_VERSION,
                    "duplicate_visual_suppressed_node_ids": [item[0] for item in suppressed],
                    "duplicate_visual_suppression_metrics": [
                        {
                            "node_id": item[0],
                            "smaller_containment": round(item[1], 6),
                            "area_ratio": round(item[2], 6),
                        }
                        for item in suppressed
                    ],
                }
            )
        kept.append(replace(node, parent_id=parent_id, metadata=metadata))

    renumbered = tuple(replace(node, order=index) for index, node in enumerate(kept))
    result = replace(spr, nodes=renumbered)
    validate_spr_v2(result)
    return result


def collapse_duplicate_refined_visuals_fail_open(
    spr: StructuredProcessingResultV2,
    *,
    logger=None,
) -> StructuredProcessingResultV2:
    """Run optional duplicate suppression without making document recovery fatal."""

    try:
        return collapse_duplicate_refined_visuals(spr)
    except Exception as exc:
        if logger is not None:
            logger.warning(
                "PDF_DUPLICATE_VISUAL_REFINEMENT_DEGRADED error_type=%s",
                type(exc).__name__,
            )
        return spr


__all__ = [
    "collapse_duplicate_refined_visuals",
    "collapse_duplicate_refined_visuals_fail_open",
]
