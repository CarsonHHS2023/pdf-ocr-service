"""Add page-presentation data to the canonical PDF SPR result.

The MinerU/Popo recovery engine owns document semantics and intentionally keeps
page furniture out of the body hierarchy. Semantic full-page reading still
needs those visible page elements, the original per-page fragments of a
cross-page canonical node, and distinct row geometry for TOC items recovered
from one provider block. This layer restores those presentation details without
changing the body recovery algorithm.
"""
from __future__ import annotations

from collections import defaultdict
import logging

from app.processing.batched_structure_refinement import (
    RequiredHeadingReviewError,
    RequiredPageRoleReviewError,
)
from app.processing.duplicate_visual_refinement import collapse_duplicate_refined_visuals_fail_open
from app.processing.llm_structure_refinement import (
    StructureRefiner,
    apply_structure_refinement_patch,
)
from app.processing.mineru_popo_pdf_recovery import recover_pdf_observations_via_mineru_popo
from app.processing.normalized_observations import NormalizedObservationBundle
from app.processing.structured_result_v2.model import (
    ProcessingNode,
    ProcessingNodeKind,
    StructuredProcessingResultV2,
)
from app.processing.structured_result_v2.validation import validate_spr_v2
from app.processing.unresolved_structure_refinement import (
    RequiredUnresolvedReviewError,
    finalize_unresolved_review_states,
    order_unresolved_patch_operations,
    prepare_unresolved_nodes_for_refinement,
    unresolved_review_target_ids,
    validate_required_unresolved_review,
)
from app.source_units import SpatialAnchor, anchor_to_dict

_logger = logging.getLogger("uvicorn.error")
_HEADER_KINDS = frozenset({"header", "page_header", "header_image"})
_FOOTER_KINDS = frozenset({"footer", "page_footer", "footer_image"})
_NUMBER_KINDS = frozenset({"number", "page_number"})
_ASIDE_KINDS = frozenset({"aside_text", "sidebar", "marginal_note"})
_TOC_ITEM_RECOVERY_RULE = "mineru_popo_toc_item"
_NUMBER_HEADER_MAX_CENTER = 0.20
_NUMBER_FOOTER_MIN_CENTER = 0.80
_NUMBER_POSITION_RULE = "bounded_page_furniture_band_v1"


def _kind(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _spatial_vertical_center(anchors) -> float | None:
    spatial = next((anchor for anchor in anchors or () if isinstance(anchor, SpatialAnchor)), None)
    if spatial is None:
        return None
    return (float(spatial.top) + float(spatial.bottom)) / 2.0


def _number_position(center: float | None) -> tuple[ProcessingNodeKind, str]:
    if center is None:
        return ProcessingNodeKind.FOOTER, "legacy_footer_fallback_no_spatial_anchor"
    if center <= _NUMBER_HEADER_MAX_CENTER:
        return ProcessingNodeKind.HEADER, _NUMBER_POSITION_RULE
    if center >= _NUMBER_FOOTER_MIN_CENTER:
        return ProcessingNodeKind.FOOTER, _NUMBER_POSITION_RULE
    return ProcessingNodeKind.FOOTER, "ambiguous_middle_footer_fallback_v1"


def _presentation_kind(observed_kind: str, anchors=()) -> ProcessingNodeKind | None:
    """Resolve furniture kind from semantic role plus bounded page position.

    Provider ``number`` observations identify page-number furniture but do not
    encode whether the number belongs to the top or bottom page band. Spatial
    geometry is therefore used only when it clearly falls inside a top or bottom
    furniture band. Missing or middle-page geometry preserves the historical
    FOOTER behavior instead of making an aggressive positional guess.
    """
    normalized = _kind(observed_kind)
    if normalized in _HEADER_KINDS:
        return ProcessingNodeKind.HEADER
    if normalized in _FOOTER_KINDS:
        return ProcessingNodeKind.FOOTER
    if normalized in _NUMBER_KINDS:
        node_kind, _ = _number_position(_spatial_vertical_center(anchors))
        return node_kind
    if normalized in _ASIDE_KINDS:
        return ProcessingNodeKind.FOOTNOTE
    return None


def _presentation_position_metadata(
    observed_kind: str,
    node_kind: ProcessingNodeKind,
    anchors=(),
) -> dict[str, object]:
    normalized = _kind(observed_kind)
    if normalized not in _NUMBER_KINDS:
        return {}
    center = _spatial_vertical_center(anchors)
    _, position_rule = _number_position(center)
    return {
        "presentation_number_position_rule": position_rule,
        "presentation_number_vertical_center": center,
        "presentation_position_role": (
            "header" if node_kind is ProcessingNodeKind.HEADER else "footer"
        ),
    }


def _replace_node(node: ProcessingNode, *, anchors=None, metadata=None) -> ProcessingNode:
    return ProcessingNode(
        node_id=node.node_id,
        kind=node.kind,
        order=node.order,
        source_unit_ids=node.source_unit_ids,
        parent_id=node.parent_id,
        text=node.text,
        heading_level=node.heading_level,
        anchors=node.anchors if anchors is None else tuple(anchors),
        observation_ids=node.observation_ids,
        evidence_ids=node.evidence_ids,
        recovery_state=node.recovery_state,
        metadata=node.metadata if metadata is None else metadata,
    )


def _toc_item_groups(nodes) -> dict[str, list[ProcessingNode]]:
    groups: dict[str, list[ProcessingNode]] = defaultdict(list)
    for node in nodes:
        if (
            node.kind is ProcessingNodeKind.LIST_ITEM
            and node.parent_id is not None
            and (node.metadata or {}).get("recovery_rule") == _TOC_ITEM_RECOVERY_RULE
        ):
            groups[node.parent_id].append(node)
    for group in groups.values():
        group.sort(key=lambda item: (item.order, item.node_id))
    return groups


def _split_toc_item_anchors(nodes):
    """Assign one vertical slice of a shared TOC block bbox to each item."""
    groups = _toc_item_groups(nodes)
    replacement: dict[str, ProcessingNode] = {}
    for items in groups.values():
        if len(items) <= 1:
            continue
        shared = next(
            (anchor for anchor in items[0].anchors if isinstance(anchor, SpatialAnchor)),
            None,
        )
        if shared is None:
            continue
        row_height = (shared.bottom - shared.top) / len(items)
        if row_height <= 0:
            continue
        for index, item in enumerate(items):
            top = shared.top + row_height * index
            bottom = (
                shared.bottom
                if index == len(items) - 1
                else shared.top + row_height * (index + 1)
            )
            row_anchor = SpatialAnchor(
                shared.source_unit_id,
                shared.left,
                top,
                shared.right,
                bottom,
            )
            anchors = tuple(
                row_anchor if isinstance(anchor, SpatialAnchor) else anchor
                for anchor in item.anchors
            )
            replacement[item.node_id] = _replace_node(
                item,
                anchors=anchors,
                metadata={
                    **(item.metadata or {}),
                    "presentation_anchor_rule": "split_toc_block_rows",
                    "presentation_row_index": index,
                    "presentation_row_count": len(items),
                },
            )
    return [replacement.get(node.node_id, node) for node in nodes]


def _page_fragment(observation) -> dict[str, object]:
    spatial_anchor = next(
        (
            anchor_to_dict(anchor)
            for anchor in observation.anchors
            if anchor_to_dict(anchor).get("kind") == "spatial"
        ),
        None,
    )
    return {
        "source_unit_id": observation.source_unit_id,
        "text": (observation.text or "").strip(),
        "source_anchor": spatial_anchor,
    }


def _retain_cross_page_fragments(nodes, observations_by_id):
    retained = []
    for node in nodes:
        if len(node.source_unit_ids) <= 1:
            retained.append(node)
            continue
        fragments = tuple(
            _page_fragment(observations_by_id[observation_id])
            for observation_id in node.observation_ids
            if observation_id in observations_by_id
        )
        retained.append(
            _replace_node(
                node,
                metadata={**(node.metadata or {}), "page_fragments": fragments},
            )
        )
    return retained


def recover_pdf_observations_for_page_presentation(
    bundle: NormalizedObservationBundle,
    *,
    structure_refiner: StructureRefiner | None = None,
    refinement_auto_apply_threshold: float = 0.90,
    refinement_fail_closed: bool = False,
) -> StructuredProcessingResultV2:
    """Recover semantics, refine them, then retain presentation data.

    Heading candidates, boundary-page roles, and every unknown/degraded node are
    mandatory review targets. Missing coverage or proposal execution failure
    raises when mandatory targets are present, so canonicalization cannot
    publish a partially reviewed candidate. Other optional provider failures
    remain fail-open unless ``refinement_fail_closed`` is enabled.
    """
    recovered = recover_pdf_observations_via_mineru_popo(bundle)
    if structure_refiner is None:
        _logger.info("PDF_STRUCTURE_REFINEMENT_SKIPPED reason=not_configured")
    else:
        prepared = prepare_unresolved_nodes_for_refinement(recovered)
        unresolved_review_required = bool(unresolved_review_target_ids(prepared))
        try:
            patch = order_unresolved_patch_operations(
                prepared,
                structure_refiner.propose(prepared),
            )
            expected_unresolved_count, reviewed_unresolved_count = (
                validate_required_unresolved_review(prepared, patch)
            )
            refined = apply_structure_refinement_patch(
                prepared,
                patch,
                auto_apply_threshold=refinement_auto_apply_threshold,
            )
            recovered = finalize_unresolved_review_states(prepared, refined, patch)
            applied_count = sum(
                1
                for node in recovered.nodes
                for entry in ((node.metadata or {}).get("llm_structure_refinement") or [])
                if entry.get("applied") is True
            )
            _logger.info(
                "PDF_STRUCTURE_REFINEMENT_APPLIED operation_count=%s applied_count=%s "
                "unresolved_target_count=%s reviewed_unresolved_count=%s",
                len(patch.operations),
                applied_count,
                expected_unresolved_count,
                reviewed_unresolved_count,
            )
        except Exception as exc:
            required_review = unresolved_review_required or isinstance(
                exc,
                (
                    RequiredHeadingReviewError,
                    RequiredPageRoleReviewError,
                    RequiredUnresolvedReviewError,
                ),
            )
            _logger.warning(
                "PDF_STRUCTURE_REFINEMENT_DEGRADED error_type=%s fail_closed=%s "
                "required_review=%s unresolved_review_required=%s",
                type(exc).__name__,
                refinement_fail_closed,
                required_review,
                unresolved_review_required,
            )
            if refinement_fail_closed or required_review:
                raise

    recovered = collapse_duplicate_refined_visuals_fail_open(recovered, logger=_logger)

    source_order = {
        unit.source_unit_id: unit.source_order for unit in recovered.source_units
    }
    observations = sorted(
        bundle.observations,
        key=lambda item: (
            source_order.get(item.source_unit_id, 2**31),
            item.order,
            item.observation_id,
        ),
    )
    observations_by_id = {item.observation_id: item for item in observations}

    nodes = _split_toc_item_anchors(recovered.nodes)
    nodes = _retain_cross_page_fragments(nodes, observations_by_id)
    for observation in observations:
        node_kind = _presentation_kind(
            observation.observed_kind,
            observation.anchors,
        )
        if node_kind is None:
            continue
        observed_kind = _kind(observation.observed_kind)
        nodes.append(
            ProcessingNode(
                node_id=f"page-presentation-node:{observation.observation_id}",
                kind=node_kind,
                order=len(nodes),
                source_unit_ids=(observation.source_unit_id,),
                parent_id=None,
                text=(observation.text or "").strip() or None,
                anchors=tuple(observation.anchors),
                observation_ids=(observation.observation_id,),
                evidence_ids=tuple(observation.evidence_ids),
                metadata={
                    "recovery_engine": "pdf_page_presentation_v1",
                    "recovery_rule": "retain_page_furniture",
                    "content_class": "furniture",
                    "presentation_role": observed_kind,
                    **_presentation_position_metadata(
                        observation.observed_kind,
                        node_kind,
                        observation.anchors,
                    ),
                },
            )
        )

    result = StructuredProcessingResultV2(
        document_ref=recovered.document_ref,
        processing_run_ref=recovered.processing_run_ref,
        raw_result_ref=recovered.raw_result_ref,
        source_units=recovered.source_units,
        observations=recovered.observations,
        nodes=tuple(nodes),
        evidence=recovered.evidence,
        schema_id=recovered.schema_id,
        schema_version=recovered.schema_version,
    )
    validate_spr_v2(result)
    return result


__all__ = ["recover_pdf_observations_for_page_presentation"]
