"""Prepare and validate mandatory LLM review for unresolved PDF nodes."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
import re

from app.processing.llm_structure_refinement import (
    RefinementOperationKind,
    StructureRefinementPatch,
)
from app.processing.structured_result_v2.model import (
    ProcessingNode,
    ProcessingNodeKind,
    ProcessingNodeRecoveryState,
    StructuredProcessingResultV2,
)
from app.processing.structured_result_v2.validation import validate_spr_v2
from app.source_units import SourceAnchor, SpatialAnchor

_PRIMARY_DISPOSITION_KINDS = frozenset(
    {
        RefinementOperationKind.RECLASSIFY_NODE,
        RefinementOperationKind.SUPPRESS_AS_ARTIFACT,
    }
)
_TOC_LINE_END_RE = re.compile(
    r"(?:[.．·]{2,}|…+)\s*[（(]?\s*\d{1,4}\s*[）)]?\s*$"
)
_TOC_SPLIT_RULE = "llm_pre_refinement_toc_line"


class RequiredUnresolvedReviewError(RuntimeError):
    """Unknown/degraded nodes were not given one auditable disposition each."""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        expected_unresolved_count: int,
        reviewed_unresolved_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.expected_unresolved_count = expected_unresolved_count
        self.reviewed_unresolved_count = reviewed_unresolved_count


def is_unresolved_node(node: ProcessingNode) -> bool:
    return (
        node.kind is ProcessingNodeKind.UNKNOWN
        or node.recovery_state is ProcessingNodeRecoveryState.DEGRADED
    )


def unresolved_review_target_ids(
    spr: StructuredProcessingResultV2,
) -> tuple[str, ...]:
    return tuple(
        node.node_id
        for node in sorted(spr.nodes, key=lambda item: (item.order, item.node_id))
        if is_unresolved_node(node)
    )


def unresolved_review_target_reasons(
    spr: StructuredProcessingResultV2,
) -> dict[str, list[str]]:
    reasons: dict[str, list[str]] = {}
    for node in sorted(spr.nodes, key=lambda item: (item.order, item.node_id)):
        values: list[str] = []
        if node.kind is ProcessingNodeKind.UNKNOWN:
            values.append("unknown_kind")
        if node.recovery_state is ProcessingNodeRecoveryState.DEGRADED:
            values.append("degraded_recovery_state")
        if (node.metadata or {}).get("recovery_rule") == _TOC_SPLIT_RULE:
            values.append("split_multiline_toc_candidate")
        if values:
            reasons[node.node_id] = values
    return reasons


def prepare_unresolved_nodes_for_refinement(
    spr: StructuredProcessingResultV2,
) -> StructuredProcessingResultV2:
    """Split only unmistakable multiline TOC blocks before mandatory review.

    The split is deterministic and preserves the original evidence. It does not
    ask the model to invent node ids or geometry. Every resulting line remains
    unknown/degraded until the model supplies one bounded disposition.
    """

    ordered_nodes = sorted(spr.nodes, key=lambda item: (item.order, item.node_id))
    existing_ids = {node.node_id for node in ordered_nodes}
    parent_ids = {node.parent_id for node in ordered_nodes if node.parent_id is not None}
    prepared: list[ProcessingNode] = []
    next_order = 0

    for node in ordered_nodes:
        lines = _multiline_toc_lines(node)
        if not lines or node.node_id in parent_ids:
            prepared.append(replace(node, order=next_order))
            next_order += 1
            continue

        for index, line in enumerate(lines):
            node_id = f"{node.node_id}:toc-line:{index + 1:03d}"
            if node_id in existing_ids:
                raise ValueError(f"generated TOC review node_id collision: {node_id}")
            metadata = dict(node.metadata or {})
            metadata.update(
                {
                    "recovery_engine": "llm_pre_refinement_v1",
                    "recovery_rule": _TOC_SPLIT_RULE,
                    "split_from_node_id": node.node_id,
                    "split_line_index": index,
                    "split_line_count": len(lines),
                    "split_original_kind": node.kind.value,
                    "split_original_recovery_state": node.recovery_state.value,
                    "spr_node_kind": ProcessingNodeKind.UNKNOWN.value,
                }
            )
            prepared.append(
                ProcessingNode(
                    node_id=node_id,
                    kind=ProcessingNodeKind.UNKNOWN,
                    order=next_order,
                    source_unit_ids=node.source_unit_ids,
                    parent_id=node.parent_id,
                    text=line,
                    anchors=_split_anchors(node.anchors, index, len(lines)),
                    observation_ids=node.observation_ids,
                    evidence_ids=node.evidence_ids,
                    recovery_state=ProcessingNodeRecoveryState.DEGRADED,
                    metadata=metadata,
                )
            )
            next_order += 1

    result = replace(spr, nodes=tuple(prepared))
    validate_spr_v2(result)
    return result


def order_unresolved_patch_operations(
    spr: StructuredProcessingResultV2,
    patch: StructureRefinementPatch,
) -> StructureRefinementPatch:
    """Ensure unresolved TOC nodes are reclassified before setting toc_level.

    The model is allowed to return operations in any array order. The core patch
    applier requires a node to already be ``list_item`` before ``set_toc_level``.
    This stable normalization moves only an early TOC-level operation for an
    unresolved node behind that same node's later reclassification.
    """

    unresolved_ids = frozenset(unresolved_review_target_ids(spr))
    pending_toc: dict[str, list[object]] = {}
    seen_reclassification: set[str] = set()
    ordered: list[object] = []

    for operation in patch.operations:
        if (
            operation.node_id in unresolved_ids
            and operation.kind is RefinementOperationKind.SET_TOC_LEVEL
            and operation.node_id not in seen_reclassification
        ):
            pending_toc.setdefault(operation.node_id, []).append(operation)
            continue
        ordered.append(operation)
        if (
            operation.node_id in unresolved_ids
            and operation.kind is RefinementOperationKind.RECLASSIFY_NODE
        ):
            seen_reclassification.add(operation.node_id)
            ordered.extend(pending_toc.pop(operation.node_id, ()))

    for operation in patch.operations:
        queued = pending_toc.get(operation.node_id)
        if queued and operation is queued[0]:
            ordered.extend(queued)
            pending_toc.pop(operation.node_id, None)

    return replace(patch, operations=tuple(ordered))


def validate_required_unresolved_review(
    spr: StructuredProcessingResultV2,
    patch: StructureRefinementPatch,
) -> tuple[int, int]:
    """Require one primary disposition for every unknown/degraded node."""

    expected = frozenset(unresolved_review_target_ids(spr))
    reviews = Counter(
        operation.node_id
        for operation in patch.operations
        if operation.node_id in expected
        and operation.kind in _PRIMARY_DISPOSITION_KINDS
    )
    reviewed = frozenset(reviews)
    duplicate_count = sum(count - 1 for count in reviews.values() if count > 1)
    missing_count = len(expected - reviewed)
    if missing_count or duplicate_count:
        raise RequiredUnresolvedReviewError(
            "required unknown/degraded node review coverage is incomplete",
            stage="unresolved_review_coverage",
            expected_unresolved_count=len(expected),
            reviewed_unresolved_count=len(reviewed),
        )
    return len(expected), len(reviewed)


def finalize_unresolved_review_states(
    original: StructuredProcessingResultV2,
    refined: StructuredProcessingResultV2,
    patch: StructureRefinementPatch,
) -> StructuredProcessingResultV2:
    """Record semantic resolution without overstating content recovery quality.

    Reclassification establishes a semantic kind but does not repair missing or
    degraded text/evidence. Preserve the original recovery state for ordinary
    nodes. The only bounded exception is a deterministic split-TOC line: the
    preprocessing step itself restores the row boundary, so a visually confirmed
    non-unknown classification may mark that synthetic line complete.
    """

    original_by_id = {node.node_id: node for node in original.nodes}
    primary_by_id = {
        operation.node_id: operation
        for operation in patch.operations
        if operation.kind in _PRIMARY_DISPOSITION_KINDS
    }
    nodes: list[ProcessingNode] = []
    for node in refined.nodes:
        original_node = original_by_id.get(node.node_id)
        operation = primary_by_id.get(node.node_id)
        if original_node is None or operation is None:
            nodes.append(node)
            continue
        history = (node.metadata or {}).get("llm_structure_refinement") or []
        applied = any(
            isinstance(entry, dict)
            and entry.get("operation") == operation.kind.value
            and entry.get("applied") is True
            for entry in history
        )
        if (
            not applied
            or operation.kind is not RefinementOperationKind.RECLASSIFY_NODE
            or operation.target_kind is ProcessingNodeKind.UNKNOWN
        ):
            nodes.append(node)
            continue
        split_toc_repaired = (
            (original_node.metadata or {}).get("recovery_rule") == _TOC_SPLIT_RULE
        )
        recovery_state = (
            ProcessingNodeRecoveryState.COMPLETE
            if split_toc_repaired
            else original_node.recovery_state
        )
        metadata = dict(node.metadata or {})
        metadata.update(
            {
                "llm_unresolved_review_resolved": True,
                "llm_unresolved_review_original_kind": original_node.kind.value,
                "llm_unresolved_review_original_recovery_state": (
                    original_node.recovery_state.value
                ),
                "llm_unresolved_review_recovery_state_policy": (
                    "complete_after_deterministic_toc_split"
                    if split_toc_repaired
                    else "preserve_original_quality_state"
                ),
            }
        )
        nodes.append(
            replace(
                node,
                recovery_state=recovery_state,
                metadata=metadata,
            )
        )

    result = replace(refined, nodes=tuple(nodes))
    validate_spr_v2(result)
    return result


def _multiline_toc_lines(node: ProcessingNode) -> tuple[str, ...]:
    if not is_unresolved_node(node):
        return ()
    text = node.text or ""
    lines = tuple(line.strip() for line in text.splitlines() if line.strip())
    if len(lines) < 2 or any(len(line) > 240 for line in lines):
        return ()
    if not all(_TOC_LINE_END_RE.search(line) for line in lines):
        return ()
    return lines


def _split_anchors(
    anchors: tuple[SourceAnchor, ...],
    index: int,
    count: int,
) -> tuple[SourceAnchor, ...]:
    split: list[SourceAnchor] = []
    for anchor in anchors:
        if not isinstance(anchor, SpatialAnchor):
            split.append(anchor)
            continue
        height = (anchor.bottom - anchor.top) / count
        if height <= 0:
            split.append(anchor)
            continue
        top = anchor.top + height * index
        bottom = anchor.bottom if index == count - 1 else anchor.top + height * (index + 1)
        split.append(
            SpatialAnchor(
                anchor.source_unit_id,
                anchor.left,
                top,
                anchor.right,
                bottom,
            )
        )
    return tuple(split)


__all__ = [
    "RequiredUnresolvedReviewError",
    "finalize_unresolved_review_states",
    "is_unresolved_node",
    "order_unresolved_patch_operations",
    "prepare_unresolved_nodes_for_refinement",
    "unresolved_review_target_ids",
    "unresolved_review_target_reasons",
    "validate_required_unresolved_review",
]
