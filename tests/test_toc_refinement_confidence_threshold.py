from __future__ import annotations

from app.processing.llm_structure_refinement import (
    DEFAULT_STRUCTURE_AUTO_APPLY_THRESHOLD,
    DEFAULT_TOC_LEVEL_AUTO_APPLY_THRESHOLD,
    RefinementOperationKind,
    StructureRefinementOperation,
    StructureRefinementPatch,
    apply_structure_refinement_patch,
)
from app.processing.structured_result_v2 import (
    ProcessingNode,
    ProcessingNodeKind,
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
    return StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        source_units=(unit,),
        observations=(),
        nodes=(
            ProcessingNode(
                "toc-item",
                ProcessingNodeKind.LIST_ITEM,
                0,
                ("page-1",),
                text="§1.1 百年帝国.....2",
                metadata={"recovery_rule": "mineru_popo_toc_item"},
            ),
            ProcessingNode(
                "heading",
                ProcessingNodeKind.HEADING,
                1,
                ("page-1",),
                text="普通标题",
                heading_level=2,
            ),
        ),
    )


def test_default_toc_threshold_accepts_confidence_088() -> None:
    assert DEFAULT_TOC_LEVEL_AUTO_APPLY_THRESHOLD == 0.85
    patch = StructureRefinementPatch(
        model_id="gpt-5.6-sol",
        operations=(
            StructureRefinementOperation(
                RefinementOperationKind.SET_TOC_LEVEL,
                "toc-item",
                0.88,
                ("reading_order_conflict",),
                toc_level=2,
            ),
        ),
    )

    node = apply_structure_refinement_patch(_spr(), patch).nodes[0]

    assert node.metadata["toc_level"] == 2
    assert node.metadata["toc_level_confidence"] == 0.88
    assert node.metadata["llm_structure_refinement"][0]["applied"] is True


def test_non_toc_operations_keep_the_090_threshold() -> None:
    assert DEFAULT_STRUCTURE_AUTO_APPLY_THRESHOLD == 0.90
    patch = StructureRefinementPatch(
        model_id="gpt-5.6-sol",
        operations=(
            StructureRefinementOperation(
                RefinementOperationKind.RECLASSIFY_NODE,
                "heading",
                0.88,
                ("semantic_discontinuity",),
                target_kind=ProcessingNodeKind.PARAGRAPH,
            ),
        ),
    )

    node = apply_structure_refinement_patch(_spr(), patch).nodes[1]

    assert node.kind is ProcessingNodeKind.HEADING
    assert node.metadata["llm_structure_refinement"][0]["applied"] is False


def test_caller_can_raise_the_toc_threshold_for_stricter_runs() -> None:
    patch = StructureRefinementPatch(
        model_id="gpt-5.6-sol",
        operations=(
            StructureRefinementOperation(
                RefinementOperationKind.SET_TOC_LEVEL,
                "toc-item",
                0.88,
                ("reading_order_conflict",),
                toc_level=2,
            ),
        ),
    )

    node = apply_structure_refinement_patch(
        _spr(),
        patch,
        toc_level_auto_apply_threshold=0.90,
    ).nodes[0]

    assert "toc_level" not in node.metadata
    assert node.metadata["llm_structure_refinement"][0]["applied"] is False
