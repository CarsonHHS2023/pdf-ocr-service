"""Repair one semantically incomplete mandatory heading-review batch narrowly."""
from __future__ import annotations

from pathlib import Path

RUNTIME_PATH = Path("app/processing/batched_structure_refinement.py")
REGRESSION_TEST_PATH = Path("tests/test_staging_deployment_contract.py")

_CONSTANT_ANCHOR = '''_PAGE_ROLE_PROMPT_TOKEN = "v4_page_roles"\n'''
_CONSTANT_REPLACEMENT = '''_PAGE_ROLE_PROMPT_TOKEN = "v4_page_roles"\n_HEADING_REVIEW_SEMANTIC_MAX_ATTEMPTS = 2\n'''

_BASE_METHOD = '''    async def _propose_one_async(
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
'''

_LEGACY_BLIND_RETRY_MARKER = (
    'for semantic_attempt in range(1, _HEADING_REVIEW_SEMANTIC_MAX_ATTEMPTS + 1):'
)
_TARGETED_REPAIR_MARKER = '"PDF_STRUCTURE_REFINEMENT_SEMANTIC_REPAIR_SCOPED"'

_TARGETED_METHOD = '''    async def _propose_one_async(
        self,
        spr: StructuredProcessingResultV2,
        image_batch: Mapping[str, str],
        *,
        required_page_role_source_unit_ids: Sequence[str] = (),
    ) -> StructureRefinementPatch:
        async def propose_once(
            candidate_spr: StructuredProcessingResultV2,
            candidate_images: Mapping[str, str],
        ) -> StructureRefinementPatch:
            refiner = self.refiner_factory(dict(candidate_images))
            propose_async = getattr(refiner, "propose_async", None)
            if callable(propose_async):
                candidate_patch = await propose_async(candidate_spr)
            else:
                propose = getattr(refiner, "propose", None)
                if not callable(propose):
                    raise TypeError(
                        "batch refiner must expose propose_async(spr) or propose(spr)"
                    )
                candidate_patch = await asyncio.to_thread(propose, candidate_spr)
            if not isinstance(candidate_patch, StructureRefinementPatch):
                raise TypeError("batch refiner must return StructureRefinementPatch")
            return candidate_patch

        patch = await propose_once(spr, image_batch)
        try:
            _validate_batch_patch(
                spr,
                patch,
                required_page_role_source_unit_ids=required_page_role_source_unit_ids,
            )
        except RequiredHeadingReviewError as exc:
            if (
                exc.stage != "heading_review_coverage"
                or _HEADING_REVIEW_SEMANTIC_MAX_ATTEMPTS < 2
            ):
                raise

            expected_heading_ids = frozenset(_heading_candidate_ids(spr))
            heading_review_counts = _heading_review_counts(spr, patch)
            reviewed_heading_ids = frozenset(heading_review_counts)
            missing_heading_ids = expected_heading_ids - reviewed_heading_ids
            duplicate_heading_count = sum(
                count - 1
                for count in heading_review_counts.values()
                if count > 1
            )
            existing_primary_dispositions = frozenset(
                operation.node_id
                for operation in patch.operations
                if operation.node_id in missing_heading_ids
                and operation.kind
                in {
                    RefinementOperationKind.RECLASSIFY_NODE,
                    RefinementOperationKind.SUPPRESS_AS_ARTIFACT,
                }
            )
            repairable = (
                bool(missing_heading_ids)
                and duplicate_heading_count == 0
                and not existing_primary_dispositions
            )
            if not repairable:
                raise

            repair_nodes = tuple(
                node for node in spr.nodes if node.node_id in missing_heading_ids
            )
            repair_source_unit_ids = frozenset(
                source_unit_id
                for node in repair_nodes
                for source_unit_id in node.source_unit_ids
            )
            repair_source_units = tuple(
                unit
                for unit in spr.source_units
                if unit.source_unit_id in repair_source_unit_ids
            )
            repair_observation_ids = frozenset(
                observation_id
                for node in repair_nodes
                for observation_id in node.observation_ids
            )
            repair_observations = tuple(
                observation
                for observation in spr.observations
                if observation.observation_id in repair_observation_ids
            )
            repair_evidence_ids = {
                evidence_id
                for node in repair_nodes
                for evidence_id in node.evidence_ids
            }
            repair_evidence_ids.update(
                evidence_id
                for observation in repair_observations
                for evidence_id in observation.evidence_ids
            )
            repair_evidence = tuple(
                item
                for item in spr.evidence
                if item.evidence_id in repair_evidence_ids
                or getattr(item, "source_unit_id", None) in repair_source_unit_ids
                or getattr(item, "observation_id", None) in repair_observation_ids
            )
            repair_spr = StructuredProcessingResultV2(
                document_ref=spr.document_ref,
                processing_run_ref=spr.processing_run_ref,
                raw_result_ref=spr.raw_result_ref,
                source_units=repair_source_units,
                observations=repair_observations,
                nodes=repair_nodes,
                evidence=repair_evidence,
                schema_id=spr.schema_id,
                schema_version=spr.schema_version,
            )
            repair_images = {
                source_unit_id: image_batch[source_unit_id]
                for source_unit_id in sorted(repair_source_unit_ids)
                if source_unit_id in image_batch
            }
            if not repair_images:
                raise RuntimeError(
                    "missing heading repair has no page image inside the batch scope"
                )

            # Preserve the existing retry event contract exactly.  New bounded
            # targeted-repair diagnostics use a distinct event.
            self.event_sink(
                "PDF_STRUCTURE_REFINEMENT_SEMANTIC_RETRY_SCHEDULED",
                {
                    "semantic_attempt": 1,
                    "next_semantic_attempt": 2,
                    "max_semantic_attempts": (
                        _HEADING_REVIEW_SEMANTIC_MAX_ATTEMPTS
                    ),
                    "error_stage": exc.stage,
                    "expected_heading_count": exc.expected_heading_count,
                    "reviewed_heading_count": exc.reviewed_heading_count,
                },
            )
            self.event_sink(
                "PDF_STRUCTURE_REFINEMENT_SEMANTIC_REPAIR_SCOPED",
                {
                    "retry_mode": "missing_heading_repair",
                    "missing_heading_count": len(missing_heading_ids),
                    "repair_page_count": len(repair_images),
                },
            )
            raw_repair_patch = await propose_once(repair_spr, repair_images)
            unexpected_repair_node_ids = frozenset(
                operation.node_id
                for operation in raw_repair_patch.operations
                if operation.node_id not in expected_heading_ids
            )
            if unexpected_repair_node_ids:
                raise ValueError(
                    "heading repair returned operations outside the original heading scope"
                )
            repair_patch = StructureRefinementPatch(
                model_id=raw_repair_patch.model_id,
                prompt_version=raw_repair_patch.prompt_version,
                operations=tuple(
                    operation
                    for operation in raw_repair_patch.operations
                    if operation.node_id in missing_heading_ids
                ),
                page_reviews=(),
            )
            try:
                _validate_batch_patch(
                    repair_spr,
                    repair_patch,
                    required_page_role_source_unit_ids=(),
                )
            except RequiredHeadingReviewError:
                # Keep the original batch-level coverage contract and counts.
                raise exc
            merged = merge_structure_refinement_patches(
                (patch, repair_patch),
                model_id=self.model_id,
                prompt_version=self.prompt_version,
            )
            _validate_batch_patch(
                spr,
                merged,
                required_page_role_source_unit_ids=required_page_role_source_unit_ids,
            )
            self.event_sink(
                "PDF_STRUCTURE_REFINEMENT_SEMANTIC_REPAIR_COMPLETED",
                {
                    "expected_heading_count": len(expected_heading_ids),
                    "retained_heading_review_count": len(reviewed_heading_ids),
                    "repaired_heading_count": len(missing_heading_ids),
                    "repair_page_count": len(repair_images),
                },
            )
            return merged
        return patch
'''

_REGRESSION_MARKER = (
    "def test_heading_semantic_retry_repairs_only_missing_heading_scope("
)
_REGRESSION_BLOCK = r'''


def test_heading_semantic_retry_repairs_only_missing_heading_scope() -> None:
    import asyncio

    from app.processing.batched_structure_refinement import BatchedStructureRefiner
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

    units = tuple(
        SourceUnit(
            f"page-{index}",
            SourceUnitKind.PHYSICAL_PAGE,
            index - 1,
            "source",
            dimensions=SourceUnitDimensions(600, 900),
        )
        for index in (1, 2)
    )
    spr = StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        source_units=units,
        observations=(),
        nodes=tuple(
            ProcessingNode(
                f"heading-{index}",
                ProcessingNodeKind.HEADING,
                index - 1,
                (units[index - 1].source_unit_id,),
                text=f"Heading {index}",
                heading_level=2,
            )
            for index in (1, 2)
        ),
    )

    def operation(node_id: str) -> StructureRefinementOperation:
        return StructureRefinementOperation(
            RefinementOperationKind.RECLASSIFY_NODE,
            node_id,
            0.98,
            ("outline_consistency",),
            target_kind=ProcessingNodeKind.HEADING,
            heading_level=2,
        )

    calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    events: list[tuple[str, dict[str, object]]] = []

    class Refiner:
        def __init__(self, images):
            self.images = dict(images)

        async def propose_async(self, scoped_spr):
            calls.append(
                (
                    tuple(sorted(self.images)),
                    tuple(node.node_id for node in scoped_spr.nodes),
                )
            )
            if len(calls) == 1:
                return StructureRefinementPatch("model", (operation("heading-1"),))
            return StructureRefinementPatch("model", (operation("heading-2"),))

    refiner = BatchedStructureRefiner(
        model_id="model",
        batch_planner=lambda _spr: (
            {
                "page-1": "data:image/jpeg;base64,AA==",
                "page-2": "data:image/jpeg;base64,AA==",
            },
        ),
        refiner_factory=Refiner,
        event_sink=lambda event, fields: events.append((event, dict(fields))),
    )

    patch = asyncio.run(refiner.propose_async(spr))

    assert calls == [
        (("page-1", "page-2"), ("heading-1", "heading-2")),
        (("page-2",), ("heading-2",)),
    ]
    assert {operation.node_id for operation in patch.operations} == {
        "heading-1",
        "heading-2",
    }
    scheduled = next(
        fields
        for event, fields in events
        if event == "PDF_STRUCTURE_REFINEMENT_SEMANTIC_RETRY_SCHEDULED"
    )
    assert scheduled == {
        "semantic_attempt": 1,
        "next_semantic_attempt": 2,
        "max_semantic_attempts": 2,
        "error_stage": "heading_review_coverage",
        "expected_heading_count": 2,
        "reviewed_heading_count": 1,
    }
    scoped = next(
        fields
        for event, fields in events
        if event == "PDF_STRUCTURE_REFINEMENT_SEMANTIC_REPAIR_SCOPED"
    )
    assert scoped["retry_mode"] == "missing_heading_repair"
    assert scoped["missing_heading_count"] == 1
    assert scoped["repair_page_count"] == 1
    completed = next(
        fields
        for event, fields in events
        if event == "PDF_STRUCTURE_REFINEMENT_SEMANTIC_REPAIR_COMPLETED"
    )
    assert completed["retained_heading_review_count"] == 1
    assert completed["repaired_heading_count"] == 1
'''


def _replace_method(source: str, old_marker: str, new_method: str) -> str:
    marker_index = source.index(old_marker)
    method_start = source.rfind("    async def _propose_one_async(", 0, marker_index + 1)
    if method_start < 0:
        raise RuntimeError("Could not find heading semantic retry method start")
    method_end = source.find("\n    def propose(", method_start)
    if method_end < 0:
        raise RuntimeError("Could not find heading semantic retry method end")
    return source[:method_start] + new_method + source[method_end:]


def _patch_heading_review_semantic_retry() -> None:
    source = RUNTIME_PATH.read_text(encoding="utf-8")
    if _CONSTANT_REPLACEMENT not in source:
        if source.count(_CONSTANT_ANCHOR) != 1:
            raise RuntimeError(
                "Could not find unique heading semantic retry constant anchor"
            )
        source = source.replace(
            _CONSTANT_ANCHOR,
            _CONSTANT_REPLACEMENT,
            1,
        )

    if _TARGETED_REPAIR_MARKER in source:
        RUNTIME_PATH.write_text(source, encoding="utf-8")
        return

    if _BASE_METHOD in source:
        source = source.replace(_BASE_METHOD, _TARGETED_METHOD, 1)
    elif _LEGACY_BLIND_RETRY_MARKER in source:
        source = _replace_method(
            source,
            _LEGACY_BLIND_RETRY_MARKER,
            _TARGETED_METHOD,
        )
    else:
        raise RuntimeError(
            "Could not find base or legacy heading semantic retry method"
        )
    RUNTIME_PATH.write_text(source, encoding="utf-8")


def _append_regressions() -> None:
    source = REGRESSION_TEST_PATH.read_text(encoding="utf-8")
    if _REGRESSION_MARKER in source:
        return
    REGRESSION_TEST_PATH.write_text(
        source.rstrip() + _REGRESSION_BLOCK.rstrip() + "\n",
        encoding="utf-8",
    )


def main() -> None:
    _patch_heading_review_semantic_retry()
    _append_regressions()


if __name__ == "__main__":
    main()
