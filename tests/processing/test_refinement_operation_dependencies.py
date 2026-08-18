from __future__ import annotations

from app.processing.llm_structure_refinement import (
    RefinementOperationKind,
    StructureRefinementOperation,
    StructureRefinementPatch,
    apply_structure_refinement_patch,
)
from app.processing.structured_result_v2.model import (
    ProcessingNode,
    ProcessingNodeKind,
    ProcessingNodeRecoveryState,
    StructuredProcessingResultV2,
)
from app.processing.unresolved_structure_refinement import (
    order_unresolved_patch_operations,
)
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind


def _spr() -> StructuredProcessingResultV2:
    source_unit = SourceUnit(
        "pdf-page:000001",
        SourceUnitKind.PHYSICAL_PAGE,
        0,
        "pdf-source",
        dimensions=SourceUnitDimensions(1000, 1400),
    )
    node = ProcessingNode(
        "toc-line",
        ProcessingNodeKind.UNKNOWN,
        0,
        (source_unit.source_unit_id,),
        text="成长之路..... (3)",
        recovery_state=ProcessingNodeRecoveryState.DEGRADED,
    )
    return StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        source_units=(source_unit,),
        observations=(),
        nodes=(node,),
    )


def _patch() -> StructureRefinementPatch:
    return StructureRefinementPatch(
        model_id="test-model",
        operations=(
            StructureRefinementOperation(
                RefinementOperationKind.SET_TOC_LEVEL,
                "toc-line",
                0.95,
                ("toc_indentation",),
                toc_level=2,
            ),
            StructureRefinementOperation(
                RefinementOperationKind.RECLASSIFY_NODE,
                "toc-line",
                0.89,
                ("toc_entry",),
                target_kind=ProcessingNodeKind.LIST_ITEM,
            ),
        ),
    )


def test_toc_level_is_skipped_when_reclassification_is_below_threshold() -> None:
    spr = _spr()
    patch = order_unresolved_patch_operations(spr, _patch())

    refined = apply_structure_refinement_patch(spr, patch)
    node = refined.nodes[0]

    assert node.kind is ProcessingNodeKind.UNKNOWN
    assert "toc_level" not in (node.metadata or {})
    history = (node.metadata or {})["llm_structure_refinement"]
    assert [entry["operation"] for entry in history] == [
        "reclassify_node",
        "set_toc_level",
    ]
    assert [entry["applied"] for entry in history] == [False, False]
    assert history[1]["application_policy"] == {
        "depends_on": "reclassify_node",
        "dependent_reclassification_applied": False,
        "reclassification_auto_apply_threshold": 0.9,
        "rejection_reason": "dependent_reclassification_not_applied",
    }


def test_toc_level_applies_when_reclassification_clears_custom_threshold() -> None:
    spr = _spr()
    patch = order_unresolved_patch_operations(spr, _patch())

    refined = apply_structure_refinement_patch(
        spr,
        patch,
        auto_apply_threshold=0.80,
    )
    node = refined.nodes[0]

    assert node.kind is ProcessingNodeKind.LIST_ITEM
    assert node.metadata["toc_level"] == 2
    history = node.metadata["llm_structure_refinement"]
    assert [entry["applied"] for entry in history] == [True, True]
