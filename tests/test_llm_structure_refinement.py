from __future__ import annotations

import pytest

from app.processing.llm_structure_refinement import (
    RefinementOperationKind,
    StructureRefinementOperation,
    StructureRefinementPatch,
    apply_structure_refinement_patch,
)
from app.processing.structured_result_v2 import (
    ProcessingNode,
    ProcessingNodeKind,
    ProcessingObservation,
    StructuredProcessingResultV2,
)
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind


def _spr(*, ocr_confidence: float | None = 0.79) -> StructuredProcessingResultV2:
    unit = SourceUnit(
        "page-1", SourceUnitKind.PHYSICAL_PAGE, 0, "pdf-source",
        dimensions=SourceUnitDimensions(1000, 1400),
    )
    observations = (
        ProcessingObservation(
            "obs-stop", "page-1", 0, "text", text="STOP",
            confidence=ocr_confidence,
        ),
    )
    nodes = (
        ProcessingNode(
            "toc-item", ProcessingNodeKind.LIST_ITEM, 0, ("page-1",),
            text="一、趋势交易法流程..... 1",
            metadata={"recovery_rule": "mineru_popo_toc_item"},
        ),
        ProcessingNode(
            "false-heading", ProcessingNodeKind.HEADING, 1, ("page-1",),
            text="STOP", heading_level=2, observation_ids=("obs-stop",),
        ),
    )
    return StructuredProcessingResultV2(
        document_ref="doc", processing_run_ref="run",
        source_units=(unit,), observations=observations, nodes=nodes,
    )


def test_sets_toc_level_without_abusing_heading_level() -> None:
    patch = StructureRefinementPatch(
        model_id="test-model",
        operations=(StructureRefinementOperation(
            RefinementOperationKind.SET_TOC_LEVEL, "toc-item", 0.97,
            ("layout_hierarchy", "toc_context"), toc_level=2,
        ),),
    )
    node = apply_structure_refinement_patch(_spr(), patch).nodes[0]
    assert node.kind is ProcessingNodeKind.LIST_ITEM
    assert node.heading_level is None
    assert node.metadata["toc_level"] == 2
    assert node.metadata["toc_level_source"] == "llm_structure_refinement"


def test_reclassifies_false_heading_and_preserves_identity_and_text() -> None:
    patch = StructureRefinementPatch(
        model_id="test-model",
        operations=(StructureRefinementOperation(
            RefinementOperationKind.RECLASSIFY_NODE, "false-heading", 0.99,
            ("embedded_visual_text", "context_mismatch"),
            target_kind=ProcessingNodeKind.CAPTION,
        ),),
    )
    node = apply_structure_refinement_patch(_spr(), patch).nodes[1]
    assert node.node_id == "false-heading"
    assert node.text == "STOP"
    assert node.kind is ProcessingNodeKind.CAPTION
    assert node.heading_level is None


def test_low_confidence_operation_is_audited_but_not_applied() -> None:
    patch = StructureRefinementPatch(
        model_id="test-model",
        operations=(StructureRefinementOperation(
            RefinementOperationKind.SUPPRESS_AS_ARTIFACT, "false-heading", 0.62,
            ("isolated_glyph",),
        ),),
    )
    node = apply_structure_refinement_patch(_spr(), patch).nodes[1]
    assert node.kind is ProcessingNodeKind.HEADING
    assert node.metadata["llm_structure_refinement"][0]["applied"] is False


def _correct_text_patch(confidence: float) -> StructureRefinementPatch:
    return StructureRefinementPatch(
        model_id="test-model",
        operations=(StructureRefinementOperation(
            RefinementOperationKind.CORRECT_TEXT, "false-heading", confidence,
            ("clear_visual_character_evidence",), original_text="STOP", corrected_text="STEP",
        ),),
    )


def test_correct_text_requires_model_confidence_strictly_above_090() -> None:
    exact = apply_structure_refinement_patch(_spr(), _correct_text_patch(0.90)).nodes[1]
    assert exact.text == "STOP"
    audit = exact.metadata["llm_structure_refinement"][0]
    assert audit["applied"] is False
    assert audit["application_policy"]["rejection_reason"] == (
        "model_confidence_not_strictly_above_threshold"
    )

    above = apply_structure_refinement_patch(_spr(), _correct_text_patch(0.91)).nodes[1]
    assert above.text == "STEP"
    assert above.metadata["ocr_text_corrections"][0]["source_ocr_confidence"] == 0.79
    assert above.metadata["llm_structure_refinement"][0]["applied"] is True


def test_correct_text_requires_source_ocr_confidence_strictly_below_080() -> None:
    exact = apply_structure_refinement_patch(
        _spr(ocr_confidence=0.80), _correct_text_patch(0.99)
    ).nodes[1]
    assert exact.text == "STOP"
    assert exact.metadata["llm_structure_refinement"][0]["application_policy"][
        "rejection_reason"
    ] == "source_ocr_confidence_not_strictly_below_threshold"

    high = apply_structure_refinement_patch(
        _spr(ocr_confidence=0.95), _correct_text_patch(0.99)
    ).nodes[1]
    assert high.text == "STOP"


def test_correct_text_rejects_missing_source_ocr_confidence() -> None:
    node = apply_structure_refinement_patch(
        _spr(ocr_confidence=None), _correct_text_patch(0.99)
    ).nodes[1]
    assert node.text == "STOP"
    assert node.metadata["llm_structure_refinement"][0]["application_policy"][
        "rejection_reason"
    ] == "source_ocr_confidence_missing"


def test_correct_text_rejects_stale_original_text_after_passing_gates() -> None:
    patch = StructureRefinementPatch(
        model_id="test-model",
        operations=(StructureRefinementOperation(
            RefinementOperationKind.CORRECT_TEXT, "false-heading", 0.99,
            ("clear_visual_character_evidence",), original_text="STALE", corrected_text="STEP",
        ),),
    )
    with pytest.raises(ValueError, match="does not match"):
        apply_structure_refinement_patch(_spr(), patch)


def test_suppression_records_explicit_reader_filter_metadata() -> None:
    patch = StructureRefinementPatch(
        model_id="test-model",
        operations=(StructureRefinementOperation(
            RefinementOperationKind.SUPPRESS_AS_ARTIFACT, "false-heading", 0.99,
            ("probable_show_through", "very_low_visual_contrast"),
        ),),
    )
    node = apply_structure_refinement_patch(_spr(), patch).nodes[1]
    assert node.kind is ProcessingNodeKind.UNKNOWN
    assert node.metadata["suppressed_as_artifact"] is True
    assert node.metadata["suppressed_original_kind"] == "heading"
    assert node.metadata["suppression_source"] == "llm_structure_refinement"
    assert node.metadata["suppression_confidence"] == 0.99
    assert node.metadata["suppression_reason_codes"] == [
        "probable_show_through", "very_low_visual_contrast"
    ]


def test_rejects_unknown_nodes_and_invalid_toc_targets() -> None:
    unknown = StructureRefinementPatch(
        model_id="test-model",
        operations=(StructureRefinementOperation(
            RefinementOperationKind.ADD_WARNING, "missing", 1.0,
            ("test",), warning="missing",
        ),),
    )
    with pytest.raises(ValueError, match="unknown node_id"):
        apply_structure_refinement_patch(_spr(), unknown)

    wrong_kind = StructureRefinementPatch(
        model_id="test-model",
        operations=(StructureRefinementOperation(
            RefinementOperationKind.SET_TOC_LEVEL, "false-heading", 1.0,
            ("test",), toc_level=1,
        ),),
    )
    with pytest.raises(ValueError, match="list_item"):
        apply_structure_refinement_patch(_spr(), wrong_kind)
