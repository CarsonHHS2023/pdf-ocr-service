"""Deterministic evidence projection supplied to a PDF refinement model."""
from __future__ import annotations

import os
from typing import Mapping

from app.processing.structured_result_v2.model import StructuredProcessingResultV2, normalize_spr_v2
from app.processing.unresolved_structure_refinement import (
    unresolved_review_target_ids,
    unresolved_review_target_reasons,
)

_HEADING_KINDS = {"title", "heading"}
_TOC_RULE = "mineru_popo_toc_item"
_SUMMARY_KIND_TOKENS = {"abstract", "summary", "overview", "chapter_summary", "executive_summary"}
_SUMMARY_TEXT_TOKENS = ("摘要", "概要", "内容概要", "abstract", "summary", "overview")
_TEXT_CORRECTION_MODEL_CONFIDENCE = 0.90
_PAGE_ROLES = (
    "cover",
    "back_cover",
    "title_page",
    "copyright_page",
    "body",
    "unknown",
)


def build_structure_refinement_request(
    spr: StructuredProcessingResultV2,
    *,
    page_role_review_positions: Mapping[str, str] | None = None,
) -> dict[str, object]:
    normalized = normalize_spr_v2(spr)
    low_ocr_threshold = float(os.getenv("PDF_STRUCTURE_REFINEMENT_LOW_OCR_CONFIDENCE", "0.80"))
    source_unit_ids = [
        str(unit.get("source_unit_id"))
        for unit in normalized.get("source_units") or []
        if isinstance(unit, dict) and isinstance(unit.get("source_unit_id"), str)
    ]
    heading_candidate_node_ids = [
        str(node.get("node_id"))
        for node in normalized.get("nodes") or []
        if isinstance(node, dict)
        and str(node.get("kind") or "").lower() in _HEADING_KINDS
        and isinstance(node.get("node_id"), str)
    ]
    unresolved_candidate_node_ids = list(unresolved_review_target_ids(spr))
    unresolved_candidate_reasons = unresolved_review_target_reasons(spr)
    unresolved_heading_candidate_node_ids = sorted(
        set(heading_candidate_node_ids).intersection(unresolved_candidate_node_ids)
    )
    page_role_positions = _page_role_review_positions(
        normalized,
        explicit=page_role_review_positions,
    )
    return {
        "request_schema": "atlas.pdf-structure-refinement-request",
        "request_version": 5,
        "document_ref": spr.document_ref,
        "processing_run_ref": spr.processing_run_ref,
        "review_scope": {
            "source_unit_ids": source_unit_ids,
            "heading_candidate_node_ids": heading_candidate_node_ids,
            "heading_review_required": True,
            "required_heading_operation": "reclassify_node",
            "unresolved_heading_candidate_node_ids": unresolved_heading_candidate_node_ids,
            "unresolved_heading_artifact_exception": (
                "an unresolved title/heading confirmed as non-page artifact may return only "
                "suppress_as_artifact; that one operation satisfies heading and unresolved review"
            ),
            "exactly_one_heading_disposition_per_candidate": True,
            "unchanged_heading_contract": (
                "return reclassify_node with the current title/heading kind and the "
                "validated current heading_level"
            ),
            "unresolved_candidate_node_ids": unresolved_candidate_node_ids,
            "unresolved_candidate_reasons": unresolved_candidate_reasons,
            "unresolved_review_required": bool(unresolved_candidate_node_ids),
            "required_unresolved_disposition_operations": [
                "reclassify_node",
                "suppress_as_artifact",
            ],
            "exactly_one_unresolved_disposition_per_candidate": True,
            "unchanged_unresolved_contract": (
                "return reclassify_node with the current kind when visual evidence "
                "supports preserving the node"
            ),
            "page_role_review_positions": page_role_positions,
            "page_role_review_source_unit_ids": list(page_role_positions),
            "page_role_review_required": bool(page_role_positions),
            "exactly_one_page_role_review_per_source_unit": True,
            "allowed_page_roles": list(_PAGE_ROLES),
            "operations_outside_scope_forbidden": True,
        },
        "tasks": [
            "return_exactly_one_page_role_review_for_every_first_or_last_page_in_scope",
            "return_exactly_one_heading_disposition_for_every_heading_candidate_in_scope",
            "return_exactly_one_primary_disposition_for_every_unknown_or_degraded_node_in_scope",
            "recover_split_multiline_toc_candidates_as_individual_list_items_when_visually_supported",
            "prefer_the_dominant_existing_peer_kind_when_a_summary_or_outline_heading_is_an_outlier",
            "validate_heading_identity_and_heading_level",
            "assign_toc_level_to_toc_list_items",
            "correct_high-confidence_ocr_errors_and_suppress_visual_artifacts",
        ],
        "allowed_operations": [
            "reclassify_node", "set_toc_level", "set_parent",
            "suppress_as_artifact", "correct_text", "add_warning",
        ],
        "decision_policy": {
            "preserve_node_ids": True,
            "preserve_original_text_evidence": True,
            "do_not_infer_from_font_size_alone": True,
            "use_page_position_and_cross_page_repetition": True,
            "use_observation_confidence_and_context": True,
            "use_visual_relationships_when_crops_are_available": True,
            "toc_level_belongs_to_list_item_metadata": True,
            "low_confidence_changes_must_not_be_auto_applied": True,
            "context_cannot_replace_visual_evidence_for_text_correction": True,
            "show_through_must_not_be_rewritten_as_current_page_text": True,
            "every_scoped_heading_candidate_requires_one_heading_disposition": True,
            "unresolved_heading_artifact_suppression_satisfies_both_reviews": True,
            "do_not_return_reclassification_with_heading_artifact_suppression": True,
            "unchanged_heading_candidates_still_require_an_auditable_operation": True,
            "every_scoped_unknown_or_degraded_node_requires_one_primary_disposition": True,
            "unchanged_unknown_or_degraded_nodes_still_require_an_auditable_operation": True,
            "every_scoped_boundary_page_requires_one_page_role_review": True,
            "do_not_return_operations_for_nodes_outside_review_scope": True,
            "prefer_dominant_existing_peer_kind_for_outlier_heading": True,
            "numbering_marker_alone_does_not_imply_list_item": True,
            "do_not_reclassify_matching_paragraph_peers_when_only_the_heading_is_wrong": True,
            "do_not_merge_or_drop_deterministically_split_toc_lines": True,
        },
        "unresolved_review_policy": {
            "scope": "every node listed in review_scope.unresolved_candidate_node_ids",
            "required_primary_disposition": [
                "reclassify_node",
                "suppress_as_artifact",
            ],
            "preserve_rule": (
                "when the current kind is visually supported, return reclassify_node "
                "with that same kind so the decision remains auditable"
            ),
            "unknown_rule": (
                "classify unknown nodes from the page image and neighboring structure; "
                "use target_kind unknown only when evidence is still insufficient"
            ),
            "degraded_rule": (
                "review degraded nodes even when their current kind is not unknown; "
                "confirm, correct, or suppress them from visual evidence"
            ),
            "split_toc_rule": (
                "nodes with recovery_rule llm_pre_refinement_toc_line are deterministic "
                "line splits from one degraded multiline block; when the image shows a "
                "TOC entry, reclassify each line to list_item and return set_toc_level"
            ),
            "artifact_rule": (
                "use suppress_as_artifact for bleed-through, stains, decoration, duplicate "
                "OCR, or text not actually present on the page; when such a node is also a "
                "title/heading candidate, suppression alone satisfies both mandatory reviews"
            ),
        },
        "page_role_review_policy": {
            "scope": "the first and last physical pages identified in review_scope",
            "allowed_roles": list(_PAGE_ROLES),
            "cover_rule": (
                "a front cover may contain title, subtitle, author, editor, translator, "
                "publisher, logo, and large artwork; these may currently be recovered as "
                "heading, paragraph, figure, or unknown"
            ),
            "back_cover_rule": (
                "a back cover may contain marketing text, barcode, publisher marks, blurbs, "
                "or artwork and should be distinguished from ordinary body prose"
            ),
            "paragraph_rule": (
                "do not reject a cover merely because author, editor, translator, or "
                "publisher text is classified as paragraph"
            ),
            "body_rule": (
                "do not classify a normal chapter-opening page or continuous body-text page "
                "as a cover"
            ),
            "evidence": [
                "page_image",
                "page_position",
                "amount_of_continuous_body_prose",
                "title_author_publisher_layout",
                "typography",
                "large_artwork_or_full_page_graphic_design",
                "logos_barcodes_and_publisher_marks",
            ],
            "uncertainty_rule": "return unknown when visual evidence is insufficient",
        },
        "heading_peer_consistency_policy": {
            "scope": (
                "a title or heading candidate inside a summary, overview, chapter-summary, "
                "checklist, or outline block"
            ),
            "compare_with": [
                "immediately_adjacent_nodes",
                "same_visual_indentation",
                "same_typography",
                "same_numbering_pattern",
                "same_spacing",
                "parallel_semantic_role",
            ],
            "outlier_rule": (
                "when the candidate is the only title or heading among visually and "
                "semantically parallel peers, reclassify only that candidate to the "
                "dominant existing peer kind"
            ),
            "paragraph_example": {
                "input_kinds": ["heading", "paragraph", "paragraph"],
                "output_kinds": ["paragraph", "paragraph", "paragraph"],
                "instruction": (
                    "the heading is the outlier; preserve the established paragraph peers"
                ),
            },
            "list_item_example": {
                "input_kinds": ["heading", "list_item", "list_item"],
                "output_kinds": ["list_item", "list_item", "list_item"],
                "instruction": (
                    "the heading is the outlier; preserve the established list_item peers"
                ),
            },
            "numbering_rule": (
                "a Chinese numeral, Arabic numeral, bullet-like prefix, or enumeration "
                "marker is not sufficient evidence to choose list_item"
            ),
            "uncertainty_rule": (
                "when visual peer evidence is not strong, preserve the current heading "
                "classification rather than inventing a new list structure"
            ),
        },
        "ocr_correction_policy": {
            "correct_text_model_confidence_must_be_strictly_greater_than": (
                _TEXT_CORRECTION_MODEL_CONFIDENCE
            ),
            "correct_text_requires_every_linked_observation_confidence_strictly_below": (
                low_ocr_threshold
            ),
            "missing_linked_observation_confidence_forbids_correct_text": True,
            "correct_text_is_only_for_genuine_front_side_page_text": True,
            "do_not_correct_or_preserve_show_through_text": True,
            "clear_show_through_requires_suppress_as_artifact": True,
            "readable_or_semantically_coherent_ghost_text_can_still_be_show_through": True,
            "show_through_indicators": [
                "faint_or_lower_contrast_than_normal_front_side_ink",
                "mirrored_reversed_or_ghosted_character_shapes",
                "offset_or_overlapping_with_real_front_side_text",
                "outside_the_normal_reading_flow_or_after_the_page_content_ends",
                "unrelated_to_neighboring_headings_or_paragraphs",
                "multi_line_text_visible_through_thin_or_aged_paper",
            ],
            "when_show_through_is_uncertain_use_add_warning_or_no_operation": True,
        },
        "low_ocr_confidence_threshold": low_ocr_threshold,
        "page_selection_reasons": _page_selection_reasons(normalized, low_ocr_threshold),
        "spr": normalized,
    }


def _page_role_review_positions(
    normalized: dict[str, object],
    *,
    explicit: Mapping[str, str] | None,
) -> dict[str, str]:
    source_units = [
        unit
        for unit in normalized.get("source_units") or []
        if isinstance(unit, dict) and isinstance(unit.get("source_unit_id"), str)
    ]
    known = {str(unit["source_unit_id"]) for unit in source_units}
    if explicit is not None:
        positions: dict[str, str] = {}
        for source_unit_id, position in explicit.items():
            if source_unit_id not in known:
                raise ValueError(
                    "page-role review scope references a source unit outside the request"
                )
            normalized_position = str(position).strip()
            if normalized_position not in {"first_page", "last_page", "first_and_last_page"}:
                raise ValueError("invalid page-role review position")
            positions[source_unit_id] = normalized_position
        return dict(sorted(positions.items()))

    ordered = sorted(
        source_units,
        key=lambda item: (item.get("source_order", 2**31), item.get("source_unit_id", "")),
    )
    if not ordered:
        return {}
    first_id = str(ordered[0]["source_unit_id"])
    last_id = str(ordered[-1]["source_unit_id"])
    if first_id == last_id:
        return {first_id: "first_and_last_page"}
    return {first_id: "first_page", last_id: "last_page"}


def _page_selection_reasons(normalized: dict[str, object], low_ocr_threshold: float) -> dict[str, list[str]]:
    source_units = list(normalized.get("source_units") or [])
    ordered = sorted(
        (unit for unit in source_units if isinstance(unit, dict)),
        key=lambda item: (item.get("source_order", 2**31), item.get("source_unit_id", "")),
    )
    reasons: dict[str, set[str]] = {}

    def add(source_unit_id: object, reason: str) -> None:
        if isinstance(source_unit_id, str) and source_unit_id:
            reasons.setdefault(source_unit_id, set()).add(reason)

    if ordered:
        add(ordered[0].get("source_unit_id"), "first_page")
        add(ordered[-1].get("source_unit_id"), "last_page")

    for node in normalized.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        kind = str(node.get("kind") or "").lower()
        recovery_state = str(node.get("recovery_state") or "").lower()
        metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        text = str(node.get("text") or "").strip().lower()
        unit_ids = node.get("source_unit_ids") or []
        node_reasons: set[str] = set()
        if kind in _HEADING_KINDS:
            node_reasons.add("heading_candidate_page")
        if kind == "unknown":
            node_reasons.add("unknown_node_page")
        if recovery_state == "degraded":
            node_reasons.add("degraded_node_page")
        if metadata.get("recovery_rule") == _TOC_RULE or metadata.get("toc_level") is not None:
            node_reasons.add("toc_page")
        observed_kind = str(metadata.get("observed_kind") or metadata.get("provider_label") or "").lower()
        if any(token in observed_kind for token in _SUMMARY_KIND_TOKENS) or any(token in text for token in _SUMMARY_TEXT_TOKENS):
            node_reasons.add("summary_page")
        for unit_id in unit_ids:
            for reason in node_reasons:
                add(unit_id, reason)

    for observation in normalized.get("observations") or []:
        if not isinstance(observation, dict):
            continue
        confidence = observation.get("confidence")
        try:
            is_low = confidence is not None and float(confidence) < low_ocr_threshold
        except (TypeError, ValueError):
            is_low = False
        if is_low:
            add(observation.get("source_unit_id"), "low_ocr_confidence_page")
        observed_kind = str(observation.get("observed_kind") or "").lower()
        if "title" in observed_kind or "heading" in observed_kind:
            add(observation.get("source_unit_id"), "heading_candidate_page")
        if "toc" in observed_kind or "table_of_contents" in observed_kind:
            add(observation.get("source_unit_id"), "toc_page")
        if any(token in observed_kind for token in _SUMMARY_KIND_TOKENS):
            add(observation.get("source_unit_id"), "summary_page")

    return {
        source_unit_id: sorted(values)
        for source_unit_id, values in sorted(reasons.items())
    }


__all__ = ["build_structure_refinement_request"]
