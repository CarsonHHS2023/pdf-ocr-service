from __future__ import annotations

from app.processing.llm_structure_refinement_request import build_structure_refinement_request
from app.processing.structured_result_v2 import (
    ProcessingNode,
    ProcessingNodeKind,
    ProcessingObservation,
    StructuredProcessingResultV2,
)
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind


def _spr() -> StructuredProcessingResultV2:
    unit = SourceUnit(
        "page-1",
        SourceUnitKind.PHYSICAL_PAGE,
        0,
        "pdf-source",
        dimensions=SourceUnitDimensions(1000, 1400),
    )
    observation = ProcessingObservation(
        "obs-1",
        "page-1",
        0,
        "text",
        text="faint ghost text",
        confidence=0.42,
    )
    paragraph = ProcessingNode(
        "node-1",
        ProcessingNodeKind.PARAGRAPH,
        0,
        ("page-1",),
        text="faint ghost text",
        observation_ids=("obs-1",),
    )
    heading = ProcessingNode(
        "heading-1",
        ProcessingNodeKind.HEADING,
        1,
        ("page-1",),
        text="一、趋势交易法流程",
        heading_level=2,
    )
    peer_two = ProcessingNode(
        "paragraph-2",
        ProcessingNodeKind.PARAGRAPH,
        2,
        ("page-1",),
        text="二、趋势线",
    )
    peer_three = ProcessingNode(
        "paragraph-3",
        ProcessingNodeKind.PARAGRAPH,
        3,
        ("page-1",),
        text="三、心语",
    )
    return StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        source_units=(unit,),
        observations=(observation,),
        nodes=(paragraph, heading, peer_two, peer_three),
    )


def test_request_states_strict_ocr_correction_and_show_through_policy(monkeypatch) -> None:
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_LOW_OCR_CONFIDENCE", "0.80")

    request = build_structure_refinement_request(_spr())
    policy = request["ocr_correction_policy"]

    assert policy["correct_text_model_confidence_must_be_strictly_greater_than"] == 0.90
    assert (
        policy["correct_text_requires_every_linked_observation_confidence_strictly_below"]
        == 0.80
    )
    assert policy["missing_linked_observation_confidence_forbids_correct_text"] is True
    assert policy["correct_text_is_only_for_genuine_front_side_page_text"] is True
    assert policy["do_not_correct_or_preserve_show_through_text"] is True
    assert policy["clear_show_through_requires_suppress_as_artifact"] is True
    assert policy["readable_or_semantically_coherent_ghost_text_can_still_be_show_through"] is True
    assert "outside_the_normal_reading_flow_or_after_the_page_content_ends" in policy[
        "show_through_indicators"
    ]


def test_request_requires_one_auditable_decision_for_every_scoped_heading() -> None:
    request = build_structure_refinement_request(_spr())
    scope = request["review_scope"]
    decision_policy = request["decision_policy"]

    assert scope["source_unit_ids"] == ["page-1"]
    assert scope["heading_candidate_node_ids"] == ["heading-1"]
    assert scope["heading_review_required"] is True
    assert scope["required_heading_operation"] == "reclassify_node"
    assert scope["exactly_one_heading_disposition_per_candidate"] is True
    assert scope["operations_outside_scope_forbidden"] is True
    assert decision_policy[
        "every_scoped_heading_candidate_requires_one_heading_disposition"
    ] is True
    assert decision_policy[
        "unchanged_heading_candidates_still_require_an_auditable_operation"
    ] is True
    assert (
        "return_exactly_one_heading_disposition_for_every_heading_candidate_in_scope"
        in request["tasks"]
    )


def test_request_requires_first_and_last_page_role_review() -> None:
    request = build_structure_refinement_request(_spr())
    scope = request["review_scope"]
    page_policy = request["page_role_review_policy"]

    assert request["request_version"] == 5
    assert scope["page_role_review_positions"] == {
        "page-1": "first_and_last_page"
    }
    assert scope["page_role_review_source_unit_ids"] == ["page-1"]
    assert scope["page_role_review_required"] is True
    assert scope["exactly_one_page_role_review_per_source_unit"] is True
    assert scope["allowed_page_roles"] == [
        "cover",
        "back_cover",
        "title_page",
        "copyright_page",
        "body",
        "unknown",
    ]
    assert request["tasks"][0] == (
        "return_exactly_one_page_role_review_for_every_first_or_last_page_in_scope"
    )
    assert "paragraph" in page_policy["paragraph_rule"]
    assert "chapter-opening" in page_policy["body_rule"]


def test_explicit_batch_scope_does_not_relabel_batch_boundaries() -> None:
    request = build_structure_refinement_request(
        _spr(),
        page_role_review_positions={},
    )

    assert request["review_scope"]["page_role_review_positions"] == {}
    assert request["review_scope"]["page_role_review_required"] is False


def test_request_prefers_existing_summary_peer_kind_for_outlier_heading() -> None:
    request = build_structure_refinement_request(_spr())
    decision_policy = request["decision_policy"]
    peer_policy = request["heading_peer_consistency_policy"]

    assert request["request_version"] == 5
    assert (
        "prefer_the_dominant_existing_peer_kind_when_a_summary_or_outline_heading_is_an_outlier"
        in request["tasks"]
    )
    assert decision_policy["prefer_dominant_existing_peer_kind_for_outlier_heading"] is True
    assert decision_policy["numbering_marker_alone_does_not_imply_list_item"] is True
    assert decision_policy[
        "do_not_reclassify_matching_paragraph_peers_when_only_the_heading_is_wrong"
    ] is True
    assert peer_policy["paragraph_example"]["input_kinds"] == [
        "heading",
        "paragraph",
        "paragraph",
    ]
    assert peer_policy["paragraph_example"]["output_kinds"] == [
        "paragraph",
        "paragraph",
        "paragraph",
    ]
    assert peer_policy["list_item_example"]["output_kinds"] == [
        "list_item",
        "list_item",
        "list_item",
    ]
    assert "not sufficient evidence" in peer_policy["numbering_rule"]
