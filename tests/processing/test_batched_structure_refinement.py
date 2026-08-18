from __future__ import annotations

import asyncio

import pytest

from app.processing.batched_structure_refinement import (
    BatchedStructureRefiner,
    RequiredHeadingReviewError,
    merge_structure_refinement_patches,
)
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
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind


def _spr(
    page_count: int = 2,
    *,
    heading_pages: tuple[int, ...] = (1,),
) -> StructuredProcessingResultV2:
    units = tuple(
        SourceUnit(
            f"page-{index}",
            SourceUnitKind.PHYSICAL_PAGE,
            index - 1,
            "source",
            dimensions=SourceUnitDimensions(600, 900),
        )
        for index in range(1, page_count + 1)
    )
    nodes = []
    for index, unit in enumerate(units, start=1):
        if index in heading_pages:
            nodes.append(
                ProcessingNode(
                    f"heading-{index}",
                    ProcessingNodeKind.HEADING,
                    index - 1,
                    (unit.source_unit_id,),
                    text=f"Heading {index}",
                    heading_level=2,
                )
            )
        else:
            nodes.append(
                ProcessingNode(
                    f"paragraph-{index}",
                    ProcessingNodeKind.PARAGRAPH,
                    index - 1,
                    (unit.source_unit_id,),
                    text=f"Paragraph {index}",
                )
            )
    return StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        source_units=units,
        observations=(),
        nodes=tuple(nodes),
    )


def _operation(
    level: int = 2,
    *,
    node_id: str = "heading-1",
) -> StructureRefinementOperation:
    return StructureRefinementOperation(
        RefinementOperationKind.RECLASSIFY_NODE,
        node_id,
        0.98,
        ("outline_consistency",),
        target_kind=ProcessingNodeKind.HEADING,
        heading_level=level,
    )


def test_merge_deduplicates_identical_operations() -> None:
    patch = StructureRefinementPatch("model", (_operation(),))

    merged = merge_structure_refinement_patches(
        (patch, patch),
        model_id="model",
        prompt_version="batched",
    )

    assert merged.operations == (_operation(),)


def test_merge_rejects_conflicting_operations_for_same_node_and_kind() -> None:
    first = StructureRefinementPatch("model", (_operation(1),))
    second = StructureRefinementPatch("model", (_operation(2),))

    with pytest.raises(ValueError, match="conflicting refinement proposals"):
        merge_structure_refinement_patches(
            (first, second),
            model_id="model",
            prompt_version="batched",
        )


def test_batched_refiner_scopes_each_request_to_its_image_pages() -> None:
    seen_images: list[dict[str, str]] = []
    seen_sprs: list[StructuredProcessingResultV2] = []
    events: list[tuple[str, dict[str, object]]] = []

    class Refiner:
        def __init__(self, images):
            self.images = dict(images)

        async def propose_async(self, spr):
            seen_images.append(self.images)
            seen_sprs.append(spr)
            operations = (_operation(),) if "page-1" in self.images else ()
            return StructureRefinementPatch("model", operations)

    refiner = BatchedStructureRefiner(
        model_id="model",
        batch_planner=lambda _spr: (
            {"page-1": "data:image/jpeg;base64,AA=="},
            {"page-2": "data:image/jpeg;base64,AA=="},
        ),
        refiner_factory=Refiner,
        event_sink=lambda event, fields: events.append((event, dict(fields))),
    )

    patch = asyncio.run(refiner.propose_async(_spr()))

    assert seen_images == [
        {"page-1": "data:image/jpeg;base64,AA=="},
        {"page-2": "data:image/jpeg;base64,AA=="},
    ]
    assert [tuple(unit.source_unit_id for unit in item.source_units) for item in seen_sprs] == [
        ("page-1",),
        ("page-2",),
    ]
    assert [tuple(node.node_id for node in item.nodes) for item in seen_sprs] == [
        ("heading-1",),
        ("paragraph-2",),
    ]
    assert patch.operations == (_operation(),)
    event_names = [event for event, _ in events]
    assert event_names[0] == "PDF_STRUCTURE_REFINEMENT_PLANNED"
    assert event_names[-1] == "PDF_STRUCTURE_REFINEMENT_COMPLETED"
    assert event_names.count("PDF_STRUCTURE_REFINEMENT_BATCH_STARTED") == 2
    assert event_names.count("PDF_STRUCTURE_REFINEMENT_BATCH_COMPLETED") == 2
    completed = [fields for event, fields in events if event == "PDF_STRUCTURE_REFINEMENT_BATCH_COMPLETED"]
    assert completed[0]["heading_candidate_count"] == 1
    assert completed[0]["reviewed_heading_count"] == 1
    assert completed[1]["heading_candidate_count"] == 0
    assert events[-1][1]["failed_batch_count"] == 0
    assert all("Heading 1" not in str(fields) for _, fields in events)
    assert all("data:image" not in str(fields) for _, fields in events)


def test_missing_heading_decision_fails_required_batch() -> None:
    class Refiner:
        def __init__(self, _images):
            pass

        async def propose_async(self, _spr):
            return StructureRefinementPatch("model", ())

    refiner = BatchedStructureRefiner(
        model_id="model",
        batch_planner=lambda _spr: ({"page-1": "data:image/jpeg;base64,AA=="},),
        refiner_factory=Refiner,
    )

    with pytest.raises(RequiredHeadingReviewError, match="coverage is incomplete") as caught:
        asyncio.run(refiner.propose_async(_spr(page_count=1)))

    assert caught.value.expected_heading_count == 1
    assert caught.value.reviewed_heading_count == 0


def test_unresolved_degraded_heading_may_be_suppressed_as_its_only_heading_disposition() -> None:
    unit = SourceUnit(
        "page-1",
        SourceUnitKind.PHYSICAL_PAGE,
        0,
        "source",
        dimensions=SourceUnitDimensions(600, 900),
    )
    spr = StructuredProcessingResultV2(
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
                text="Bleed-through heading",
                heading_level=2,
                recovery_state=ProcessingNodeRecoveryState.DEGRADED,
            ),
        ),
    )
    suppression = StructureRefinementOperation(
        RefinementOperationKind.SUPPRESS_AS_ARTIFACT,
        "heading-1",
        0.99,
        ("probable_show_through",),
    )

    class Refiner:
        def __init__(self, _images):
            pass

        async def propose_async(self, _spr):
            return StructureRefinementPatch("model", (suppression,))

    refiner = BatchedStructureRefiner(
        model_id="model",
        batch_planner=lambda _spr: ({"page-1": "data:image/jpeg;base64,AA=="},),
        refiner_factory=Refiner,
    )

    patch = asyncio.run(refiner.propose_async(spr))

    assert patch.operations == (suppression,)


def test_complete_heading_suppression_does_not_replace_required_reclassification() -> None:
    suppression = StructureRefinementOperation(
        RefinementOperationKind.SUPPRESS_AS_ARTIFACT,
        "heading-1",
        0.99,
        ("probable_show_through",),
    )

    class Refiner:
        def __init__(self, _images):
            pass

        async def propose_async(self, _spr):
            return StructureRefinementPatch("model", (suppression,))

    refiner = BatchedStructureRefiner(
        model_id="model",
        batch_planner=lambda _spr: ({"page-1": "data:image/jpeg;base64,AA=="},),
        refiner_factory=Refiner,
    )

    with pytest.raises(RequiredHeadingReviewError, match="coverage is incomplete"):
        asyncio.run(refiner.propose_async(_spr(page_count=1)))


def test_heading_batch_provider_failure_is_mandatory_even_when_fail_open() -> None:
    class Refiner:
        def __init__(self, _images):
            pass

        async def propose_async(self, _spr):
            raise TimeoutError("provider timeout")

    refiner = BatchedStructureRefiner(
        model_id="model",
        batch_planner=lambda _spr: ({"page-1": "data:image/jpeg;base64,AA=="},),
        refiner_factory=Refiner,
    )

    with pytest.raises(RequiredHeadingReviewError, match="batch failed"):
        asyncio.run(refiner.propose_async(_spr(page_count=1)))


def test_batched_refiner_limits_per_document_concurrency() -> None:
    active = 0
    peak = 0
    lock = asyncio.Lock()

    class Refiner:
        def __init__(self, _images):
            pass

        async def propose_async(self, _spr):
            nonlocal active, peak
            async with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.01)
            async with lock:
                active -= 1
            return StructureRefinementPatch("model", ())

    refiner = BatchedStructureRefiner(
        model_id="model",
        batch_planner=lambda _spr: tuple(
            {f"page-{index}": "data:image/jpeg;base64,AA=="}
            for index in range(1, 7)
        ),
        refiner_factory=Refiner,
        max_concurrent_batches=2,
    )

    asyncio.run(refiner.propose_async(_spr(6, heading_pages=())))

    assert peak == 2


def test_non_heading_batch_failure_remains_fail_open() -> None:
    events: list[tuple[str, dict[str, object]]] = []

    class Refiner:
        def __init__(self, images):
            self.should_fail = "page-2" in images

        async def propose_async(self, _spr):
            if self.should_fail:
                raise TimeoutError("secret OCR text must not be logged")
            return StructureRefinementPatch("model", (_operation(),))

    refiner = BatchedStructureRefiner(
        model_id="model",
        batch_planner=lambda _spr: (
            {"page-1": "data:image/jpeg;base64,AA=="},
            {"page-2": "data:image/jpeg;base64,AA=="},
        ),
        refiner_factory=Refiner,
        event_sink=lambda event, fields: events.append((event, dict(fields))),
    )

    patch = asyncio.run(refiner.propose_async(_spr()))

    assert patch.operations == (_operation(),)
    failed = [fields for event, fields in events if event == "PDF_STRUCTURE_REFINEMENT_BATCH_FAILED"]
    assert failed[0]["error_type"] == "TimeoutError"
    assert failed[0]["required_heading_review"] is False
    assert "secret OCR text" not in str(failed[0])
    assert events[-1][1]["successful_batch_count"] == 1
    assert events[-1][1]["failed_batch_count"] == 1


def test_batched_refiner_fail_closed_raises_non_heading_batch_failure() -> None:
    class FailingRefiner:
        def __init__(self, _images):
            pass

        async def propose_async(self, _spr):
            raise TimeoutError("provider timeout")

    refiner = BatchedStructureRefiner(
        model_id="model",
        batch_planner=lambda _spr: ({"page-1": "data:image/jpeg;base64,AA=="},),
        refiner_factory=FailingRefiner,
        fail_closed=True,
    )

    with pytest.raises(TimeoutError):
        asyncio.run(refiner.propose_async(_spr(page_count=1, heading_pages=())))


def test_batched_refiner_times_out_non_heading_batch_and_continues() -> None:
    class Refiner:
        def __init__(self, images):
            self.slow = "page-2" in images

        async def propose_async(self, _spr):
            if self.slow:
                await asyncio.sleep(0.05)
            return StructureRefinementPatch("model", ())

    refiner = BatchedStructureRefiner(
        model_id="model",
        batch_planner=lambda _spr: (
            {"page-1": "data:image/jpeg;base64,AA=="},
            {"page-2": "data:image/jpeg;base64,AA=="},
        ),
        refiner_factory=Refiner,
        batch_timeout_seconds=0.01,
    )

    patch = asyncio.run(refiner.propose_async(_spr(2, heading_pages=())))

    assert patch.operations == ()


def test_sync_adapter_remains_available_outside_event_loop() -> None:
    class Refiner:
        def __init__(self, _images):
            pass

        async def propose_async(self, _spr):
            return StructureRefinementPatch("model", (_operation(),))

    refiner = BatchedStructureRefiner(
        model_id="model",
        batch_planner=lambda _spr: ({"page-1": "data:image/jpeg;base64,AA=="},),
        refiner_factory=Refiner,
    )

    assert refiner.propose(_spr(page_count=1)).operations == (_operation(),)
