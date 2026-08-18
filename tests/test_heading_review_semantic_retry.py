from __future__ import annotations

import asyncio

import pytest

from scripts.apply_heading_review_semantic_retry import main as apply_fix

apply_fix()

from app.processing.batched_structure_refinement import (
    BatchedStructureRefiner,
    RequiredHeadingReviewError,
)
from app.processing.llm_structure_refinement import (
    RefinementOperationKind,
    StructureRefinementOperation,
    StructureRefinementPatch,
)
from app.processing.structured_result_v2.model import (
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
        "source",
        dimensions=SourceUnitDimensions(600, 900),
    )
    return StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        source_units=(unit,),
        observations=(),
        nodes=(
            ProcessingNode(
                "heading-1",
                ProcessingNodeKind.HEADING,
                0,
                (unit.source_unit_id,),
                text="Heading one",
                heading_level=1,
            ),
            ProcessingNode(
                "heading-2",
                ProcessingNodeKind.HEADING,
                1,
                (unit.source_unit_id,),
                text="Heading two",
                heading_level=2,
            ),
        ),
    )


def _operation(node_id: str, level: int) -> StructureRefinementOperation:
    return StructureRefinementOperation(
        kind=RefinementOperationKind.RECLASSIFY_NODE,
        node_id=node_id,
        confidence=0.98,
        reason_codes=("visual_outline_consistency",),
        target_kind=ProcessingNodeKind.HEADING,
        heading_level=level,
    )


def _patch(*node_ids: str) -> StructureRefinementPatch:
    levels = {"heading-1": 1, "heading-2": 2}
    return StructureRefinementPatch(
        model_id="model",
        operations=tuple(_operation(node_id, levels[node_id]) for node_id in node_ids),
        prompt_version="heading-review-semantic-retry-test",
    )


def test_incomplete_heading_coverage_retries_once_and_then_succeeds() -> None:
    calls = 0
    events: list[tuple[str, dict[str, object]]] = []

    class Refiner:
        def __init__(self, _images):
            pass

        async def propose_async(self, _spr):
            nonlocal calls
            calls += 1
            if calls == 1:
                return _patch("heading-1")
            return _patch("heading-1", "heading-2")

    refiner = BatchedStructureRefiner(
        model_id="model",
        batch_planner=lambda _spr: (
            {"page-1": "data:image/jpeg;base64,AA=="},
        ),
        refiner_factory=Refiner,
        event_sink=lambda event, fields: events.append((event, dict(fields))),
    )

    patch = asyncio.run(refiner.propose_async(_spr()))

    assert calls == 2
    assert tuple(operation.node_id for operation in patch.operations) == (
        "heading-1",
        "heading-2",
    )
    retries = [
        fields
        for event, fields in events
        if event == "PDF_STRUCTURE_REFINEMENT_SEMANTIC_RETRY_SCHEDULED"
    ]
    assert retries == [
        {
            "semantic_attempt": 1,
            "next_semantic_attempt": 2,
            "max_semantic_attempts": 2,
            "error_stage": "heading_review_coverage",
            "expected_heading_count": 2,
            "reviewed_heading_count": 1,
        }
    ]
    completed = [
        fields
        for event, fields in events
        if event == "PDF_STRUCTURE_REFINEMENT_BATCH_COMPLETED"
    ]
    assert completed[0]["heading_candidate_count"] == 2
    assert completed[0]["reviewed_heading_count"] == 2


def test_repeated_incomplete_heading_coverage_still_fails_closed() -> None:
    calls = 0
    events: list[tuple[str, dict[str, object]]] = []

    class Refiner:
        def __init__(self, _images):
            pass

        async def propose_async(self, _spr):
            nonlocal calls
            calls += 1
            return _patch("heading-1")

    refiner = BatchedStructureRefiner(
        model_id="model",
        batch_planner=lambda _spr: (
            {"page-1": "data:image/jpeg;base64,AA=="},
        ),
        refiner_factory=Refiner,
        event_sink=lambda event, fields: events.append((event, dict(fields))),
    )

    with pytest.raises(RequiredHeadingReviewError) as caught:
        asyncio.run(refiner.propose_async(_spr()))

    assert calls == 2
    assert caught.value.stage == "heading_review_coverage"
    assert caught.value.expected_heading_count == 2
    assert caught.value.reviewed_heading_count == 1
    assert sum(
        event == "PDF_STRUCTURE_REFINEMENT_SEMANTIC_RETRY_SCHEDULED"
        for event, _ in events
    ) == 1
    failed = [
        fields
        for event, fields in events
        if event == "PDF_STRUCTURE_REFINEMENT_BATCH_FAILED"
    ]
    assert failed[0]["error_stage"] == "heading_review_coverage"
    assert failed[0]["expected_heading_count"] == 2
    assert failed[0]["reviewed_heading_count"] == 1


def test_non_coverage_heading_failure_is_not_semantically_retried() -> None:
    calls = 0
    events: list[tuple[str, dict[str, object]]] = []

    class Refiner:
        def __init__(self, _images):
            pass

        async def propose_async(self, _spr):
            nonlocal calls
            calls += 1
            raise RequiredHeadingReviewError(
                "required heading review batch failed",
                stage="heading_review_batch_execution",
                expected_heading_count=2,
            )

    refiner = BatchedStructureRefiner(
        model_id="model",
        batch_planner=lambda _spr: (
            {"page-1": "data:image/jpeg;base64,AA=="},
        ),
        refiner_factory=Refiner,
        event_sink=lambda event, fields: events.append((event, dict(fields))),
    )

    with pytest.raises(RequiredHeadingReviewError) as caught:
        asyncio.run(refiner.propose_async(_spr()))

    assert calls == 1
    assert caught.value.stage == "heading_review_batch_execution"
    assert all(
        event != "PDF_STRUCTURE_REFINEMENT_SEMANTIC_RETRY_SCHEDULED"
        for event, _ in events
    )
