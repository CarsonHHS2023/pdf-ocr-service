from __future__ import annotations

from dataclasses import replace

import app.processing.duplicate_visual_refinement as duplicate_visual_refinement
from app.processing.duplicate_visual_refinement import collapse_duplicate_refined_visuals
from app.processing.structured_result_v2.model import (
    ProcessingNode,
    ProcessingNodeKind,
    StructuredProcessingResultV2,
)
from app.source_units import (
    SourceUnit,
    SourceUnitDimensions,
    SourceUnitKind,
    SpatialAnchor,
)


def _source_unit(source_unit_id: str = "pdf-page:000001", order: int = 0) -> SourceUnit:
    return SourceUnit(
        source_unit_id,
        SourceUnitKind.PHYSICAL_PAGE,
        order,
        "pdf-source",
        dimensions=SourceUnitDimensions(1000, 1400),
    )


def _node(
    node_id: str,
    kind: ProcessingNodeKind,
    order: int,
    bbox: tuple[float, float, float, float],
    *,
    parent_id: str | None = None,
    metadata: dict | None = None,
    source_unit_ids: tuple[str, ...] = ("pdf-page:000001",),
    anchors: tuple[SpatialAnchor, ...] | None = None,
) -> ProcessingNode:
    if anchors is None:
        anchors = (SpatialAnchor(source_unit_ids[0], *bbox),)
    return ProcessingNode(
        node_id,
        kind,
        order,
        source_unit_ids,
        parent_id=parent_id,
        anchors=anchors,
        metadata=metadata or {},
    )


def _native(node_id: str, order: int, bbox, **kwargs) -> ProcessingNode:
    return _node(
        node_id,
        ProcessingNodeKind.FIGURE,
        order,
        bbox,
        metadata={
            "recovery_engine": "mineru_popo_v2",
            "recovery_rule": "mineru_popo_visual",
        },
        **kwargs,
    )


def _reclassified(node_id: str, order: int, bbox, **kwargs) -> ProcessingNode:
    return _node(
        node_id,
        ProcessingNodeKind.FIGURE,
        order,
        bbox,
        metadata={
            "recovery_engine": "mineru_popo_v2",
            "recovery_rule": "mineru_popo_semantic_block",
            "llm_unresolved_review_original_kind": "unknown",
            "llm_unresolved_review_resolved": True,
            "llm_structure_refinement": [
                {
                    "operation": "reclassify_node",
                    "applied": True,
                    "confidence": 0.98,
                }
            ],
        },
        **kwargs,
    )


def _spr(*nodes: ProcessingNode, source_units: tuple[SourceUnit, ...] | None = None) -> StructuredProcessingResultV2:
    return StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        source_units=source_units or (_source_unit(),),
        observations=(),
        nodes=nodes,
    )


def test_collapses_near_contained_reclassified_visual_into_native_visual() -> None:
    native = _native("native", 0, (0.2411, 0.5843, 0.7629, 0.8702))
    duplicate = _reclassified("duplicate", 1, (0.2395, 0.5875, 0.6084, 0.8675))
    caption = _node(
        "caption",
        ProcessingNodeKind.CAPTION,
        2,
        (0.30, 0.88, 0.70, 0.91),
        parent_id="duplicate",
    )

    result = collapse_duplicate_refined_visuals(_spr(native, duplicate, caption))

    assert [node.node_id for node in result.nodes] == ["native", "caption"]
    assert [node.order for node in result.nodes] == [0, 1]
    assert result.nodes[1].parent_id == "native"
    metadata = result.nodes[0].metadata
    assert metadata["duplicate_visual_refinement_policy"] == "duplicate_refined_visual_containment_v1"
    assert metadata["duplicate_visual_suppressed_node_ids"] == ("duplicate",)
    assert metadata["duplicate_visual_suppression_metrics"][0]["smaller_containment"] > 0.99


def test_does_not_collapse_two_native_visuals_or_weak_overlap() -> None:
    native_a = _native("native-a", 0, (0.10, 0.20, 0.45, 0.50))
    native_b = _native("native-b", 1, (0.12, 0.22, 0.43, 0.48))
    weak_candidate = _reclassified("weak", 2, (0.40, 0.20, 0.75, 0.50))

    result = collapse_duplicate_refined_visuals(_spr(native_a, native_b, weak_candidate))

    assert [node.node_id for node in result.nodes] == ["native-a", "native-b", "weak"]


def test_does_not_collapse_different_parent_visuals() -> None:
    section = ProcessingNode(
        "other-section",
        ProcessingNodeKind.HEADING,
        0,
        ("pdf-page:000001",),
        text="Other section",
        heading_level=1,
    )
    native = _native("native", 1, (0.20, 0.30, 0.80, 0.70))
    duplicate = _reclassified(
        "duplicate",
        2,
        (0.21, 0.31, 0.79, 0.69),
        parent_id="other-section",
    )

    result = collapse_duplicate_refined_visuals(_spr(section, native, duplicate))

    assert [node.node_id for node in result.nodes] == ["other-section", "native", "duplicate"]


def test_does_not_collapse_reclassified_visual_from_other_recovery_rule() -> None:
    native = _native("native", 0, (0.20, 0.30, 0.80, 0.70))
    candidate = _reclassified("candidate", 1, (0.21, 0.31, 0.79, 0.69))
    candidate = replace(
        candidate,
        metadata={**candidate.metadata, "recovery_rule": "other_visual_recovery"},
    )

    result = collapse_duplicate_refined_visuals(_spr(native, candidate))

    assert [node.node_id for node in result.nodes] == ["native", "candidate"]


def test_does_not_collapse_fully_contained_but_much_smaller_visual() -> None:
    native = _native("native", 0, (0.10, 0.10, 0.90, 0.90))
    candidate = _reclassified("candidate", 1, (0.20, 0.20, 0.30, 0.30))

    result = collapse_duplicate_refined_visuals(_spr(native, candidate))

    assert [node.node_id for node in result.nodes] == ["native", "candidate"]


def test_does_not_collapse_cross_page_visual_even_with_one_shared_page() -> None:
    page_one = "pdf-page:000001"
    page_two = "pdf-page:000002"
    native = _native(
        "native",
        0,
        (0.20, 0.30, 0.80, 0.70),
        source_unit_ids=(page_one, page_two),
        anchors=(
            SpatialAnchor(page_one, 0.20, 0.30, 0.80, 0.70),
            SpatialAnchor(page_two, 0.20, 0.10, 0.80, 0.40),
        ),
    )
    candidate = _reclassified("candidate", 1, (0.21, 0.31, 0.79, 0.69))

    result = collapse_duplicate_refined_visuals(
        _spr(
            native,
            candidate,
            source_units=(_source_unit(page_one, 0), _source_unit(page_two, 1)),
        )
    )

    assert [node.node_id for node in result.nodes] == ["native", "candidate"]


def test_does_not_collapse_when_page_geometry_is_ambiguous() -> None:
    page = "pdf-page:000001"
    native = _native(
        "native",
        0,
        (0.20, 0.30, 0.80, 0.70),
        anchors=(
            SpatialAnchor(page, 0.20, 0.30, 0.80, 0.70),
            SpatialAnchor(page, 0.22, 0.32, 0.78, 0.68),
        ),
    )
    candidate = _reclassified("candidate", 1, (0.21, 0.31, 0.79, 0.69))

    result = collapse_duplicate_refined_visuals(_spr(native, candidate))

    assert [node.node_id for node in result.nodes] == ["native", "candidate"]


def test_fail_open_wrapper_returns_original_spr_on_unexpected_error(monkeypatch) -> None:
    native = _native("native", 0, (0.20, 0.30, 0.80, 0.70))
    spr = _spr(native)
    warnings: list[tuple[str, str]] = []

    class Logger:
        def warning(self, message, error_type):
            warnings.append((message, error_type))

    def boom(_spr):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(duplicate_visual_refinement, "collapse_duplicate_refined_visuals", boom)

    result = duplicate_visual_refinement.collapse_duplicate_refined_visuals_fail_open(
        spr,
        logger=Logger(),
    )

    assert result is spr
    assert warnings == [
        ("PDF_DUPLICATE_VISUAL_REFINEMENT_DEGRADED error_type=%s", "RuntimeError")
    ]
