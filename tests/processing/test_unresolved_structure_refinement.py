from __future__ import annotations

import pytest

from app.processing.llm_structure_refinement import (
    RefinementOperationKind,
    StructureRefinementOperation,
    StructureRefinementPatch,
    apply_structure_refinement_patch,
)
from app.processing.llm_structure_refinement_request import (
    build_structure_refinement_request,
)
from app.processing.structured_result_v2.model import (
    ProcessingNode,
    ProcessingNodeKind,
    ProcessingNodeRecoveryState,
    StructuredProcessingResultV2,
)
from app.processing.unresolved_structure_refinement import (
    RequiredUnresolvedReviewError,
    finalize_unresolved_review_states,
    order_unresolved_patch_operations,
    prepare_unresolved_nodes_for_refinement,
    unresolved_review_target_ids,
    validate_required_unresolved_review,
)
from app.source_units import (
    SourceUnit,
    SourceUnitDimensions,
    SourceUnitKind,
    SpatialAnchor,
)


def _source_unit(source_unit_id: str, order: int) -> SourceUnit:
    return SourceUnit(
        source_unit_id,
        SourceUnitKind.PHYSICAL_PAGE,
        order,
        "pdf-source",
        dimensions=SourceUnitDimensions(1000, 1400),
    )


def _spr() -> StructuredProcessingResultV2:
    return StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        source_units=(
            _source_unit("pdf-page:000001", 0),
            _source_unit("pdf-page:000002", 1),
            _source_unit("pdf-page:000003", 2),
        ),
        observations=(),
        nodes=(
            ProcessingNode(
                "toc-heading",
                ProcessingNodeKind.HEADING,
                0,
                ("pdf-page:000002",),
                text="目录",
                heading_level=1,
            ),
            ProcessingNode(
                "toc-block",
                ProcessingNodeKind.UNKNOWN,
                1,
                ("pdf-page:000002",),
                parent_id="toc-heading",
                text=(
                    "成长之路..... (3)\n"
                    "人生要有大格局..... (4)\n"
                    "赢得未来..... (16)"
                ),
                anchors=(
                    SpatialAnchor(
                        "pdf-page:000002",
                        0.15,
                        0.30,
                        0.90,
                        0.60,
                    ),
                ),
                recovery_state=ProcessingNodeRecoveryState.DEGRADED,
                metadata={
                    "recovery_engine": "mineru_popo_v2",
                    "recovery_rule": "mineru_popo_semantic_block",
                },
            ),
            ProcessingNode(
                "degraded-paragraph",
                ProcessingNodeKind.PARAGRAPH,
                2,
                ("pdf-page:000002",),
                text="可见但恢复质量不足",
                recovery_state=ProcessingNodeRecoveryState.DEGRADED,
            ),
        ),
    )


def test_prepare_splits_unmistakable_multiline_toc_block_into_review_targets() -> None:
    prepared = prepare_unresolved_nodes_for_refinement(_spr())

    split = [
        node
        for node in prepared.nodes
        if (node.metadata or {}).get("split_from_node_id") == "toc-block"
    ]
    assert [node.text for node in split] == [
        "成长之路..... (3)",
        "人生要有大格局..... (4)",
        "赢得未来..... (16)",
    ]
    assert all(node.kind is ProcessingNodeKind.UNKNOWN for node in split)
    assert all(
        node.recovery_state is ProcessingNodeRecoveryState.DEGRADED
        for node in split
    )
    assert all(node.parent_id == "toc-heading" for node in split)
    assert [node.node_id for node in split] == [
        "toc-block:toc-line:001",
        "toc-block:toc-line:002",
        "toc-block:toc-line:003",
    ]
    spatial = [node.anchors[0] for node in split]
    assert [round(anchor.top, 2) for anchor in spatial] == [0.30, 0.40, 0.50]
    assert [round(anchor.bottom, 2) for anchor in spatial] == [0.40, 0.50, 0.60]


def test_prepare_does_not_split_arbitrary_multiline_unknown_text() -> None:
    spr = _spr()
    ordinary = ProcessingNode(
        "ordinary-unknown",
        ProcessingNodeKind.UNKNOWN,
        3,
        ("pdf-page:000002",),
        text="第一行正文\n第二行正文",
        recovery_state=ProcessingNodeRecoveryState.DEGRADED,
    )
    prepared = prepare_unresolved_nodes_for_refinement(
        StructuredProcessingResultV2(
            document_ref=spr.document_ref,
            processing_run_ref=spr.processing_run_ref,
            source_units=spr.source_units,
            observations=spr.observations,
            nodes=spr.nodes + (ordinary,),
        )
    )

    retained = next(node for node in prepared.nodes if node.node_id == "ordinary-unknown")
    assert retained.text == "第一行正文\n第二行正文"


def test_request_selects_and_requires_every_unknown_or_degraded_node() -> None:
    prepared = prepare_unresolved_nodes_for_refinement(_spr())
    request = build_structure_refinement_request(prepared)
    scope = request["review_scope"]

    assert request["request_version"] == 5
    assert scope["unresolved_candidate_node_ids"] == list(
        unresolved_review_target_ids(prepared)
    )
    assert scope["unresolved_review_required"] is True
    assert scope["required_unresolved_disposition_operations"] == [
        "reclassify_node",
        "suppress_as_artifact",
    ]
    assert scope["exactly_one_unresolved_disposition_per_candidate"] is True
    assert scope["unresolved_heading_candidate_node_ids"] == []
    assert request["decision_policy"][
        "unresolved_heading_artifact_suppression_satisfies_both_reviews"
    ] is True
    assert request["page_selection_reasons"]["pdf-page:000002"] == [
        "degraded_node_page",
        "heading_candidate_page",
        "unknown_node_page",
    ]


def test_request_marks_degraded_heading_as_overlapping_mandatory_target() -> None:
    spr = _spr()
    degraded_heading = ProcessingNode(
        "degraded-heading",
        ProcessingNodeKind.HEADING,
        3,
        ("pdf-page:000002",),
        text="透印伪标题",
        heading_level=2,
        recovery_state=ProcessingNodeRecoveryState.DEGRADED,
    )
    prepared = prepare_unresolved_nodes_for_refinement(
        StructuredProcessingResultV2(
            document_ref=spr.document_ref,
            processing_run_ref=spr.processing_run_ref,
            source_units=spr.source_units,
            observations=spr.observations,
            nodes=spr.nodes + (degraded_heading,),
        )
    )

    request = build_structure_refinement_request(prepared)

    assert request["review_scope"]["unresolved_heading_candidate_node_ids"] == [
        "degraded-heading"
    ]
    assert "suppression alone satisfies both" in request["unresolved_review_policy"][
        "artifact_rule"
    ]


def test_missing_or_duplicate_unresolved_dispositions_fail_closed() -> None:
    prepared = prepare_unresolved_nodes_for_refinement(_spr())
    expected = unresolved_review_target_ids(prepared)

    with pytest.raises(RequiredUnresolvedReviewError) as missing:
        validate_required_unresolved_review(
            prepared,
            StructureRefinementPatch(model_id="test-model", operations=()),
        )
    assert missing.value.expected_unresolved_count == len(expected)
    assert missing.value.reviewed_unresolved_count == 0

    first = expected[0]
    duplicate = StructureRefinementPatch(
        model_id="test-model",
        operations=(
            StructureRefinementOperation(
                RefinementOperationKind.RECLASSIFY_NODE,
                first,
                0.95,
                ("toc_entry",),
                target_kind=ProcessingNodeKind.LIST_ITEM,
            ),
            StructureRefinementOperation(
                RefinementOperationKind.SUPPRESS_AS_ARTIFACT,
                first,
                0.95,
                ("duplicate_ocr",),
            ),
        ),
    )
    with pytest.raises(RequiredUnresolvedReviewError):
        validate_required_unresolved_review(prepared, duplicate)


def test_suppress_as_artifact_is_a_complete_primary_disposition() -> None:
    prepared = prepare_unresolved_nodes_for_refinement(_spr())
    operations = tuple(
        StructureRefinementOperation(
            RefinementOperationKind.SUPPRESS_AS_ARTIFACT,
            node_id,
            0.95,
            ("not_visible_in_page_image",),
        )
        for node_id in unresolved_review_target_ids(prepared)
    )
    patch = StructureRefinementPatch(model_id="test-model", operations=operations)

    assert validate_required_unresolved_review(prepared, patch) == (
        len(operations),
        len(operations),
    )


def test_toc_level_is_moved_after_reclassification_for_same_unresolved_node() -> None:
    prepared = prepare_unresolved_nodes_for_refinement(_spr())
    node_id = "toc-block:toc-line:001"
    patch = StructureRefinementPatch(
        model_id="test-model",
        operations=(
            StructureRefinementOperation(
                RefinementOperationKind.SET_TOC_LEVEL,
                node_id,
                0.95,
                ("toc_indentation",),
                toc_level=2,
            ),
            StructureRefinementOperation(
                RefinementOperationKind.RECLASSIFY_NODE,
                node_id,
                0.95,
                ("toc_entry",),
                target_kind=ProcessingNodeKind.LIST_ITEM,
            ),
        ),
    )

    ordered = order_unresolved_patch_operations(prepared, patch)

    assert [operation.kind for operation in ordered.operations] == [
        RefinementOperationKind.RECLASSIFY_NODE,
        RefinementOperationKind.SET_TOC_LEVEL,
    ]
    refined = apply_structure_refinement_patch(prepared, ordered)
    node = next(item for item in refined.nodes if item.node_id == node_id)
    assert node.kind is ProcessingNodeKind.LIST_ITEM
    assert node.metadata["toc_level"] == 2


def test_reviewed_toc_lines_become_complete_but_original_degraded_state_is_preserved() -> None:
    prepared = prepare_unresolved_nodes_for_refinement(_spr())
    targets = unresolved_review_target_ids(prepared)
    operations: list[StructureRefinementOperation] = []
    for node_id in targets:
        target_kind = (
            ProcessingNodeKind.PARAGRAPH
            if node_id == "degraded-paragraph"
            else ProcessingNodeKind.LIST_ITEM
        )
        operations.append(
            StructureRefinementOperation(
                RefinementOperationKind.RECLASSIFY_NODE,
                node_id,
                0.95,
                ("visually_supported_structure",),
                target_kind=target_kind,
            )
        )
        if target_kind is ProcessingNodeKind.LIST_ITEM:
            operations.append(
                StructureRefinementOperation(
                    RefinementOperationKind.SET_TOC_LEVEL,
                    node_id,
                    0.95,
                    ("toc_indentation",),
                    toc_level=2,
                )
            )
    patch = StructureRefinementPatch(
        model_id="test-model",
        operations=tuple(operations),
    )

    assert validate_required_unresolved_review(prepared, patch) == (
        len(targets),
        len(targets),
    )
    refined = apply_structure_refinement_patch(prepared, patch)
    finalized = finalize_unresolved_review_states(prepared, refined, patch)

    split = [
        node
        for node in finalized.nodes
        if (node.metadata or {}).get("split_from_node_id") == "toc-block"
    ]
    assert all(node.kind is ProcessingNodeKind.LIST_ITEM for node in split)
    assert all(
        node.recovery_state is ProcessingNodeRecoveryState.COMPLETE
        for node in split
    )
    assert all((node.metadata or {}).get("toc_level") == 2 for node in split)
    assert all(
        (node.metadata or {}).get("llm_unresolved_review_resolved") is True
        for node in split
    )
    assert all(
        (node.metadata or {}).get("llm_unresolved_review_recovery_state_policy")
        == "complete_after_deterministic_toc_split"
        for node in split
    )

    degraded = next(
        node for node in finalized.nodes if node.node_id == "degraded-paragraph"
    )
    assert degraded.kind is ProcessingNodeKind.PARAGRAPH
    assert degraded.recovery_state is ProcessingNodeRecoveryState.DEGRADED
    assert degraded.metadata[
        "llm_unresolved_review_recovery_state_policy"
    ] == "preserve_original_quality_state"


def test_unknown_unavailable_reclassification_preserves_unavailable_state() -> None:
    unit = _source_unit("pdf-page:000001", 0)
    original = StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        source_units=(unit,),
        observations=(),
        nodes=(
            ProcessingNode(
                "missing-node",
                ProcessingNodeKind.UNKNOWN,
                0,
                (unit.source_unit_id,),
                text=None,
                recovery_state=ProcessingNodeRecoveryState.UNAVAILABLE,
            ),
        ),
    )
    patch = StructureRefinementPatch(
        model_id="test-model",
        operations=(
            StructureRefinementOperation(
                RefinementOperationKind.RECLASSIFY_NODE,
                "missing-node",
                0.95,
                ("semantic_role_visible_but_text_missing",),
                target_kind=ProcessingNodeKind.PARAGRAPH,
            ),
        ),
    )

    refined = apply_structure_refinement_patch(original, patch)
    finalized = finalize_unresolved_review_states(original, refined, patch)
    node = finalized.nodes[0]

    assert node.kind is ProcessingNodeKind.PARAGRAPH
    assert node.recovery_state is ProcessingNodeRecoveryState.UNAVAILABLE
    assert node.metadata[
        "llm_unresolved_review_recovery_state_policy"
    ] == "preserve_original_quality_state"
