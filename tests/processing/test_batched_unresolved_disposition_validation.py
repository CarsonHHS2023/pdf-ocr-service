from __future__ import annotations

import asyncio

import pytest

from app.processing.batched_structure_refinement import BatchedStructureRefiner
from app.processing.llm_structure_refinement import (
    RefinementOperationKind,
    StructureRefinementOperation,
    StructureRefinementPatch,
)
from app.processing.structured_result_v2.model import (
    ProcessingNode,
    ProcessingNodeKind,
    ProcessingNodeRecoveryState,
    StructuredProcessingResultV2,
)
from app.processing.unresolved_structure_refinement import (
    RequiredUnresolvedReviewError,
)
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind


def _unresolved_spr() -> StructuredProcessingResultV2:
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
                "unknown-1",
                ProcessingNodeKind.UNKNOWN,
                0,
                (unit.source_unit_id,),
                text="Recovered but unresolved text",
                recovery_state=ProcessingNodeRecoveryState.DEGRADED,
            ),
        ),
    )


def _reclassification() -> StructureRefinementOperation:
    return StructureRefinementOperation(
        RefinementOperationKind.RECLASSIFY_NODE,
        "unknown-1",
        0.98,
        ("visually_supported_paragraph",),
        target_kind=ProcessingNodeKind.PARAGRAPH,
    )


def test_duplicate_identical_unresolved_dispositions_fail_before_merge() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    operation = _reclassification()

    class Refiner:
        def __init__(self, _images):
            pass

        async def propose_async(self, _spr):
            return StructureRefinementPatch(
                model_id="model",
                prompt_version="pdf_structure_refinement_v5_unresolved_review",
                operations=(operation, operation),
            )

    refiner = BatchedStructureRefiner(
        model_id="model",
        batch_planner=lambda _spr: ({"page-1": "data:image/jpeg;base64,AA=="},),
        refiner_factory=Refiner,
        event_sink=lambda event, fields: events.append((event, dict(fields))),
    )

    with pytest.raises(
        RequiredUnresolvedReviewError,
        match="coverage is incomplete",
    ) as caught:
        asyncio.run(refiner.propose_async(_unresolved_spr()))

    assert caught.value.expected_unresolved_count == 1
    assert caught.value.reviewed_unresolved_count == 1
    failed = [
        fields
        for event, fields in events
        if event == "PDF_STRUCTURE_REFINEMENT_BATCH_FAILED"
    ]
    assert failed[0]["required_unresolved_review"] is True
    assert failed[0]["expected_unresolved_count"] == 1
    assert failed[0]["reviewed_unresolved_count"] == 1
    assert "PDF_STRUCTURE_REFINEMENT_COMPLETED" not in [
        event for event, _fields in events
    ]


def test_missing_unresolved_disposition_fails_required_batch() -> None:
    class Refiner:
        def __init__(self, _images):
            pass

        async def propose_async(self, _spr):
            return StructureRefinementPatch(
                model_id="model",
                prompt_version="pdf_structure_refinement_v5_unresolved_review",
                operations=(),
            )

    refiner = BatchedStructureRefiner(
        model_id="model",
        batch_planner=lambda _spr: ({"page-1": "data:image/jpeg;base64,AA=="},),
        refiner_factory=Refiner,
    )

    with pytest.raises(RequiredUnresolvedReviewError) as caught:
        asyncio.run(refiner.propose_async(_unresolved_spr()))

    assert caught.value.expected_unresolved_count == 1
    assert caught.value.reviewed_unresolved_count == 0
