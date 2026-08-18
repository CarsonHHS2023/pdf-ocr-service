"""Deterministic batching and conflict-safe merge for structure refinement."""
from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, replace
import logging
from time import perf_counter
from typing import Awaitable, Callable, Mapping, Sequence

from app.processing.llm_structure_refinement import (
    PageRoleReview,
    RefinementOperationKind,
    StructureRefinementOperation,
    StructureRefinementPatch,
)
from app.processing.structured_result_v2.model import (
    ProcessingNodeKind,
    StructuredProcessingResultV2,
)
from app.processing.unresolved_structure_refinement import (
    RequiredUnresolvedReviewError,
    is_unresolved_node,
    unresolved_review_target_ids,
    validate_required_unresolved_review,
)

BatchPlanner = Callable[[StructuredProcessingResultV2], Sequence[Mapping[str, str]]]
BatchRefinerFactory = Callable[[Mapping[str, str]], object]
RefinementEventSink = Callable[[str, Mapping[str, object]], None]
AsyncPermit = Callable[[], Awaitable[object]]

_logger = logging.getLogger("uvicorn.error")
_HEADING_KINDS = frozenset({ProcessingNodeKind.TITLE, ProcessingNodeKind.HEADING})
_PAGE_ROLE_PROMPT_TOKEN = "v4_page_roles"


class RequiredHeadingReviewError(RuntimeError):
    """A batch containing headings failed or did not review every candidate."""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        expected_heading_count: int,
        reviewed_heading_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.expected_heading_count = expected_heading_count
        self.reviewed_heading_count = reviewed_heading_count


class RequiredPageRoleReviewError(RuntimeError):
    """A boundary-page batch failed or omitted a required page-role decision."""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        expected_page_role_count: int,
        reviewed_page_role_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.expected_page_role_count = expected_page_role_count
        self.reviewed_page_role_count = reviewed_page_role_count


def _log_refinement_event(event: str, fields: Mapping[str, object]) -> None:
    payload = " ".join(f"{name}={value}" for name, value in sorted(fields.items()))
    _logger.info("%s %s", event, payload)


def _batch_failure_fields(exc: Exception) -> dict[str, object]:
    fields: dict[str, object] = {"error_type": type(exc).__name__}
    error_stage = getattr(exc, "stage", None)
    if isinstance(error_stage, str) and error_stage:
        fields["error_stage"] = error_stage[:80]
        fields["error_summary"] = " ".join(str(exc).split())[:180]
    for name in (
        "expected_heading_count",
        "reviewed_heading_count",
        "expected_page_role_count",
        "reviewed_page_role_count",
        "expected_unresolved_count",
        "reviewed_unresolved_count",
        "operation_index",
    ):
        value = getattr(exc, name, None)
        if isinstance(value, int) and not isinstance(value, bool):
            fields[name] = value
    operation_kind = getattr(exc, "operation_kind", None)
    if isinstance(operation_kind, str) and operation_kind:
        fields["operation_kind"] = operation_kind[:64]
    null_fields = getattr(exc, "null_fields", ())
    if isinstance(null_fields, tuple) and all(isinstance(item, str) for item in null_fields):
        fields["null_fields"] = ",".join(null_fields)[:180]
    return fields


def _heading_candidate_ids(spr: StructuredProcessingResultV2) -> tuple[str, ...]:
    return tuple(
        node.node_id
        for node in sorted(spr.nodes, key=lambda item: (item.order, item.node_id))
        if node.kind in _HEADING_KINDS
    )


def _heading_review_counts(
    spr: StructuredProcessingResultV2,
    patch: StructureRefinementPatch,
) -> Counter[str]:
    """Count one valid heading disposition per scoped heading candidate.

    Ordinary headings require ``reclassify_node``. A title/heading that is also
    an unresolved target may instead be suppressed as a visual artifact; that
    one suppression satisfies both mandatory contracts. Returning both remains
    a duplicate and is rejected by coverage validation.
    """

    expected = frozenset(_heading_candidate_ids(spr))
    unresolved_headings = frozenset(
        node.node_id
        for node in spr.nodes
        if node.node_id in expected and is_unresolved_node(node)
    )
    return Counter(
        operation.node_id
        for operation in patch.operations
        if operation.node_id in expected
        and (
            operation.kind is RefinementOperationKind.RECLASSIFY_NODE
            or (
                operation.kind is RefinementOperationKind.SUPPRESS_AS_ARTIFACT
                and operation.node_id in unresolved_headings
            )
        )
    )


def _document_boundary_positions(spr: StructuredProcessingResultV2) -> dict[str, str]:
    ordered = sorted(
        spr.source_units,
        key=lambda unit: (unit.source_order, unit.source_unit_id),
    )
    if not ordered:
        return {}
    first_id = ordered[0].source_unit_id
    last_id = ordered[-1].source_unit_id
    if first_id == last_id:
        return {first_id: "first_and_last_page"}
    return {first_id: "first_page", last_id: "last_page"}


def _scoped_spr(
    spr: StructuredProcessingResultV2,
    source_unit_ids: Sequence[str],
) -> StructuredProcessingResultV2:
    """Project one image batch to only its pages, observations, nodes, and evidence."""

    selected_units = frozenset(source_unit_ids)
    source_units = tuple(
        unit for unit in spr.source_units if unit.source_unit_id in selected_units
    )
    observations = tuple(
        observation
        for observation in spr.observations
        if observation.source_unit_id in selected_units
    )
    observation_ids = frozenset(item.observation_id for item in observations)

    nodes = []
    for node in spr.nodes:
        scoped_unit_ids = tuple(
            unit_id for unit_id in node.source_unit_ids if unit_id in selected_units
        )
        if not scoped_unit_ids:
            continue
        nodes.append(
            replace(
                node,
                source_unit_ids=scoped_unit_ids,
                anchors=tuple(
                    anchor
                    for anchor in node.anchors
                    if getattr(anchor, "source_unit_id", None) in selected_units
                ),
                observation_ids=tuple(
                    observation_id
                    for observation_id in node.observation_ids
                    if observation_id in observation_ids
                ),
            )
        )

    referenced_evidence_ids = {
        evidence_id
        for observation in observations
        for evidence_id in observation.evidence_ids
    }
    referenced_evidence_ids.update(
        evidence_id for node in nodes for evidence_id in node.evidence_ids
    )
    evidence = tuple(
        item
        for item in spr.evidence
        if item.evidence_id in referenced_evidence_ids
        or item.source_unit_id in selected_units
        or item.observation_id in observation_ids
    )

    return StructuredProcessingResultV2(
        document_ref=spr.document_ref,
        processing_run_ref=spr.processing_run_ref,
        raw_result_ref=spr.raw_result_ref,
        source_units=source_units,
        observations=observations,
        nodes=tuple(nodes),
        evidence=evidence,
        schema_id=spr.schema_id,
        schema_version=spr.schema_version,
    )


def _validate_batch_patch(
    spr: StructuredProcessingResultV2,
    patch: StructureRefinementPatch,
    *,
    required_page_role_source_unit_ids: Sequence[str] = (),
) -> tuple[int, int, int, int, int, int]:
    """Require complete heading, unresolved-node, and boundary-page coverage."""

    scoped_node_ids = frozenset(node.node_id for node in spr.nodes)
    outside_scope_count = sum(
        operation.node_id not in scoped_node_ids for operation in patch.operations
    )
    if outside_scope_count:
        raise ValueError(
            "structure refinement batch returned operations outside the batch scope"
        )

    scoped_source_unit_ids = frozenset(unit.source_unit_id for unit in spr.source_units)
    if any(review.source_unit_id not in scoped_source_unit_ids for review in patch.page_reviews):
        raise ValueError(
            "structure refinement batch returned page reviews outside the batch scope"
        )

    expected_headings = frozenset(_heading_candidate_ids(spr))
    heading_reviews = _heading_review_counts(spr, patch)
    reviewed_headings = frozenset(heading_reviews)
    duplicate_heading_count = sum(
        count - 1 for count in heading_reviews.values() if count > 1
    )
    missing_heading_count = len(expected_headings - reviewed_headings)
    unexpected_heading_count = len(reviewed_headings - expected_headings)
    if missing_heading_count or duplicate_heading_count or unexpected_heading_count:
        raise RequiredHeadingReviewError(
            "required heading review coverage is incomplete",
            stage="heading_review_coverage",
            expected_heading_count=len(expected_headings),
            reviewed_heading_count=len(reviewed_headings),
        )

    expected_unresolved_count, reviewed_unresolved_count = (
        validate_required_unresolved_review(spr, patch)
    )

    expected_page_roles = frozenset(required_page_role_source_unit_ids)
    reviewed_page_roles: frozenset[str] = frozenset()
    if _PAGE_ROLE_PROMPT_TOKEN in patch.prompt_version:
        page_role_reviews = Counter(
            review.source_unit_id for review in patch.page_reviews
        )
        reviewed_page_roles = frozenset(page_role_reviews)
        duplicate_page_role_count = sum(
            count - 1 for count in page_role_reviews.values() if count > 1
        )
        missing_page_role_count = len(expected_page_roles - reviewed_page_roles)
        unexpected_page_role_count = len(reviewed_page_roles - expected_page_roles)
        if (
            missing_page_role_count
            or duplicate_page_role_count
            or unexpected_page_role_count
        ):
            raise RequiredPageRoleReviewError(
                "required page-role review coverage is incomplete",
                stage="page_role_review_coverage",
                expected_page_role_count=len(expected_page_roles),
                reviewed_page_role_count=len(reviewed_page_roles),
            )

    return (
        len(expected_headings),
        len(reviewed_headings),
        expected_unresolved_count,
        reviewed_unresolved_count,
        len(expected_page_roles),
        len(reviewed_page_roles),
    )


@dataclass(frozen=True, slots=True)
class BatchedStructureRefiner:
    """Run page-scoped image batches concurrently, then merge successful patches once."""

    model_id: str
    batch_planner: BatchPlanner
    refiner_factory: BatchRefinerFactory
    prompt_version: str = "pdf_structure_refinement_v2_batched"
    event_sink: RefinementEventSink = _log_refinement_event
    max_concurrent_batches: int = 2
    batch_timeout_seconds: float = 60.0
    global_semaphore: asyncio.Semaphore | None = None
    fail_closed: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.max_concurrent_batches, bool) or self.max_concurrent_batches < 1:
            raise ValueError("max_concurrent_batches must be a positive integer")
        if self.batch_timeout_seconds <= 0:
            raise ValueError("batch_timeout_seconds must be positive")

    async def propose_async(self, spr: StructuredProcessingResultV2) -> StructureRefinementPatch:
        started = perf_counter()
        planning_started = perf_counter()
        image_batches = tuple(self.batch_planner(spr))
        boundary_positions = _document_boundary_positions(spr)
        self.event_sink(
            "PDF_STRUCTURE_REFINEMENT_PLANNED",
            {
                "batch_count": len(image_batches),
                "page_count": sum(len(batch) for batch in image_batches),
                "page_role_review_count": len(boundary_positions),
                "planning_ms": round((perf_counter() - planning_started) * 1000),
                "max_concurrent_batches": self.max_concurrent_batches,
            },
        )

        document_semaphore = asyncio.Semaphore(self.max_concurrent_batches)

        async def run_batch(
            batch_index: int,
            image_batch: Mapping[str, str],
        ) -> StructureRefinementPatch | None:
            batch_started = perf_counter()
            batch_spr = _scoped_spr(spr, tuple(image_batch))
            expected_heading_count = len(_heading_candidate_ids(batch_spr))
            expected_unresolved_count = len(unresolved_review_target_ids(batch_spr))
            required_page_role_ids = tuple(
                source_unit_id
                for source_unit_id in boundary_positions
                if source_unit_id in image_batch
            )
            expected_page_role_count = len(required_page_role_ids)
            self.event_sink(
                "PDF_STRUCTURE_REFINEMENT_BATCH_STARTED",
                {
                    "batch_index": batch_index,
                    "batch_count": len(image_batches),
                    "page_count": len(image_batch),
                    "node_count": len(batch_spr.nodes),
                    "heading_candidate_count": expected_heading_count,
                    "required_heading_review": expected_heading_count > 0,
                    "unresolved_candidate_count": expected_unresolved_count,
                    "required_unresolved_review": expected_unresolved_count > 0,
                    "page_role_review_count": expected_page_role_count,
                    "required_page_role_review": expected_page_role_count > 0,
                },
            )
            try:
                async with document_semaphore:
                    if self.global_semaphore is None:
                        patch = await asyncio.wait_for(
                            self._propose_one_async(
                                batch_spr,
                                image_batch,
                                required_page_role_source_unit_ids=required_page_role_ids,
                            ),
                            timeout=self.batch_timeout_seconds,
                        )
                    else:
                        async with self.global_semaphore:
                            patch = await asyncio.wait_for(
                                self._propose_one_async(
                                    batch_spr,
                                    image_batch,
                                    required_page_role_source_unit_ids=required_page_role_ids,
                                ),
                                timeout=self.batch_timeout_seconds,
                            )
            except Exception as exc:
                failure = {
                    "batch_index": batch_index,
                    "batch_count": len(image_batches),
                    "page_count": len(image_batch),
                    "node_count": len(batch_spr.nodes),
                    "heading_candidate_count": expected_heading_count,
                    "required_heading_review": expected_heading_count > 0,
                    "unresolved_candidate_count": expected_unresolved_count,
                    "required_unresolved_review": expected_unresolved_count > 0,
                    "page_role_review_count": expected_page_role_count,
                    "required_page_role_review": expected_page_role_count > 0,
                    "duration_ms": round((perf_counter() - batch_started) * 1000),
                }
                failure.update(_batch_failure_fields(exc))
                self.event_sink("PDF_STRUCTURE_REFINEMENT_BATCH_FAILED", failure)
                if isinstance(
                    exc,
                    (
                        RequiredHeadingReviewError,
                        RequiredPageRoleReviewError,
                        RequiredUnresolvedReviewError,
                    ),
                ):
                    raise
                if expected_heading_count:
                    raise RequiredHeadingReviewError(
                        "required heading review batch failed",
                        stage="heading_review_batch_execution",
                        expected_heading_count=expected_heading_count,
                    ) from exc
                if expected_page_role_count:
                    raise RequiredPageRoleReviewError(
                        "required page-role review batch failed",
                        stage="page_role_review_batch_execution",
                        expected_page_role_count=expected_page_role_count,
                    ) from exc
                if expected_unresolved_count:
                    raise RequiredUnresolvedReviewError(
                        "required unknown/degraded node review batch failed",
                        stage="unresolved_review_batch_execution",
                        expected_unresolved_count=expected_unresolved_count,
                    ) from exc
                if self.fail_closed:
                    raise
                return None

            reviewed_heading_count = len(_heading_review_counts(batch_spr, patch))
            reviewed_unresolved_count = expected_unresolved_count
            reviewed_page_role_count = sum(
                1
                for review in patch.page_reviews
                if review.source_unit_id in frozenset(required_page_role_ids)
            )
            self.event_sink(
                "PDF_STRUCTURE_REFINEMENT_BATCH_COMPLETED",
                {
                    "batch_index": batch_index,
                    "batch_count": len(image_batches),
                    "page_count": len(image_batch),
                    "node_count": len(batch_spr.nodes),
                    "heading_candidate_count": expected_heading_count,
                    "reviewed_heading_count": reviewed_heading_count,
                    "unresolved_candidate_count": expected_unresolved_count,
                    "reviewed_unresolved_count": reviewed_unresolved_count,
                    "page_role_review_count": expected_page_role_count,
                    "reviewed_page_role_count": reviewed_page_role_count,
                    "operation_count": len(patch.operations),
                    "duration_ms": round((perf_counter() - batch_started) * 1000),
                },
            )
            return patch

        results = await asyncio.gather(
            *(run_batch(index, batch) for index, batch in enumerate(image_batches, start=1))
        )
        patches = tuple(patch for patch in results if patch is not None)
        merged = merge_structure_refinement_patches(
            patches,
            model_id=self.model_id,
            prompt_version=self.prompt_version,
        )
        self.event_sink(
            "PDF_STRUCTURE_REFINEMENT_COMPLETED",
            {
                "batch_count": len(image_batches),
                "failed_batch_count": len(image_batches) - len(patches),
                "successful_batch_count": len(patches),
                "page_count": sum(len(batch) for batch in image_batches),
                "page_role_review_count": len(merged.page_reviews),
                "operation_count": len(merged.operations),
                "duration_ms": round((perf_counter() - started) * 1000),
            },
        )
        return merged

    async def _propose_one_async(
        self,
        spr: StructuredProcessingResultV2,
        image_batch: Mapping[str, str],
        *,
        required_page_role_source_unit_ids: Sequence[str] = (),
    ) -> StructureRefinementPatch:
        refiner = self.refiner_factory(dict(image_batch))
        propose_async = getattr(refiner, "propose_async", None)
        if callable(propose_async):
            patch = await propose_async(spr)
        else:
            propose = getattr(refiner, "propose", None)
            if not callable(propose):
                raise TypeError("batch refiner must expose propose_async(spr) or propose(spr)")
            patch = await asyncio.to_thread(propose, spr)
        if not isinstance(patch, StructureRefinementPatch):
            raise TypeError("batch refiner must return StructureRefinementPatch")
        _validate_batch_patch(
            spr,
            patch,
            required_page_role_source_unit_ids=required_page_role_source_unit_ids,
        )
        return patch

    def propose(self, spr: StructuredProcessingResultV2) -> StructureRefinementPatch:
        """Compatibility adapter for existing synchronous worker call sites."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.propose_async(spr))
        raise RuntimeError(
            "BatchedStructureRefiner.propose() cannot run inside an active event loop; "
            "await propose_async() instead"
        )


def merge_structure_refinement_patches(
    patches: Sequence[StructureRefinementPatch],
    *,
    model_id: str,
    prompt_version: str,
) -> StructureRefinementPatch:
    """Deduplicate identical proposals and reject incompatible proposals."""

    merged: list[StructureRefinementOperation] = []
    exact_seen: set[tuple[object, ...]] = set()
    targets: dict[tuple[str, str], tuple[object, ...]] = {}
    page_reviews: list[PageRoleReview] = []
    page_review_targets: dict[str, tuple[object, ...]] = {}

    for patch in patches:
        for review in patch.page_reviews:
            signature = _page_review_signature(review)
            previous = page_review_targets.get(review.source_unit_id)
            if previous is not None:
                if previous != signature:
                    raise ValueError(
                        "conflicting page-role reviews for "
                        f"source_unit_id={review.source_unit_id}"
                    )
                continue
            page_review_targets[review.source_unit_id] = signature
            page_reviews.append(review)

        for operation in patch.operations:
            exact = _operation_signature(operation)
            if exact in exact_seen:
                continue
            conflict_key = (operation.node_id, operation.kind.value)
            previous = targets.get(conflict_key)
            if previous is not None and previous != exact:
                raise ValueError(
                    "conflicting refinement proposals for "
                    f"node_id={operation.node_id} operation={operation.kind.value}"
                )
            targets[conflict_key] = exact
            exact_seen.add(exact)
            merged.append(operation)

    return StructureRefinementPatch(
        model_id=model_id,
        prompt_version=prompt_version,
        operations=tuple(merged),
        page_reviews=tuple(page_reviews),
    )


def _operation_signature(operation: StructureRefinementOperation) -> tuple[object, ...]:
    return (
        operation.node_id,
        operation.kind.value,
        operation.target_kind.value if operation.target_kind is not None else None,
        operation.heading_level,
        operation.toc_level,
        operation.parent_id,
        operation.original_text,
        operation.corrected_text,
        operation.warning,
        operation.confidence,
        operation.reason_codes,
    )


def _page_review_signature(review: PageRoleReview) -> tuple[object, ...]:
    return (
        review.source_unit_id,
        review.page_role.value,
        review.confidence,
        review.reason_codes,
    )


__all__ = [
    "BatchedStructureRefiner",
    "RefinementEventSink",
    "RequiredHeadingReviewError",
    "RequiredPageRoleReviewError",
    "merge_structure_refinement_patches",
]
