"""Close structure-refinement batch references and bound full execution time."""
from __future__ import annotations

from pathlib import Path

BATCH_RUNTIME_PATH = Path("app/processing/batched_structure_refinement.py")
IMAGE_RUNTIME_PATH = Path("app/processing/pdf_structure_refinement_images.py")
REGRESSION_TEST_PATH = Path("tests/test_staging_deployment_contract.py")

_SCOPED_SPR_ANCHOR = '''def _scoped_spr(
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
'''
_SCOPED_SPR_REPLACEMENT = '''def _scoped_spr(
    spr: StructuredProcessingResultV2,
    source_unit_ids: Sequence[str],
) -> StructuredProcessingResultV2:
    """Project one image batch without dangling cross-batch references."""

    selected_units = frozenset(source_unit_ids)
    selected_nodes = tuple(
        node
        for node in spr.nodes
        if selected_units.intersection(node.source_unit_ids)
    )
    selected_node_ids = frozenset(node.node_id for node in selected_nodes)

    observation_by_id = {
        observation.observation_id: observation
        for observation in spr.observations
    }
    evidence_by_id = {item.evidence_id: item for item in spr.evidence}
    retained_observation_ids = {
        observation.observation_id
        for observation in spr.observations
        if observation.source_unit_id in selected_units
    }
    retained_observation_ids.update(
        observation_id
        for node in selected_nodes
        for observation_id in node.observation_ids
        if observation_id in observation_by_id
    )
    retained_evidence_ids = {
        evidence_id
        for node in selected_nodes
        for evidence_id in node.evidence_ids
        if evidence_id in evidence_by_id
    }

    # Keep existing page-local context, then close only references reachable from
    # those observations/evidence or explicitly from selected nodes. Cross-page
    # dependencies may add source units for referential integrity, but never add
    # their nodes, so mandatory heading review scope remains page-batch bounded.
    while True:
        previous_sizes = (
            len(retained_observation_ids),
            len(retained_evidence_ids),
        )
        retained_evidence_ids.update(
            item.evidence_id
            for item in spr.evidence
            if item.source_unit_id in selected_units
            or item.observation_id in retained_observation_ids
        )
        retained_evidence_ids.update(
            evidence_id
            for observation_id in tuple(retained_observation_ids)
            if observation_id in observation_by_id
            for evidence_id in observation_by_id[observation_id].evidence_ids
            if evidence_id in evidence_by_id
        )
        retained_observation_ids.update(
            evidence_by_id[evidence_id].observation_id
            for evidence_id in tuple(retained_evidence_ids)
            if evidence_id in evidence_by_id
            and evidence_by_id[evidence_id].observation_id is not None
            and evidence_by_id[evidence_id].observation_id in observation_by_id
        )
        if previous_sizes == (
            len(retained_observation_ids),
            len(retained_evidence_ids),
        ):
            break

    observations = tuple(
        observation
        for observation in spr.observations
        if observation.observation_id in retained_observation_ids
    )
    evidence = tuple(
        item
        for item in spr.evidence
        if item.evidence_id in retained_evidence_ids
    )

    nodes = tuple(
        replace(
            node,
            source_unit_ids=tuple(
                unit_id
                for unit_id in node.source_unit_ids
                if unit_id in selected_units
            ),
            parent_id=(
                node.parent_id
                if node.parent_id in selected_node_ids
                else None
            ),
            anchors=tuple(
                anchor
                for anchor in node.anchors
                if getattr(anchor, "source_unit_id", None) in selected_units
            ),
            observation_ids=tuple(
                observation_id
                for observation_id in node.observation_ids
                if observation_id in retained_observation_ids
            ),
            evidence_ids=tuple(
                evidence_id
                for evidence_id in node.evidence_ids
                if evidence_id in retained_evidence_ids
            ),
        )
        for node in selected_nodes
    )

    required_source_unit_ids = set(selected_units)
    required_source_unit_ids.update(
        observation.source_unit_id for observation in observations
    )
    required_source_unit_ids.update(
        item.source_unit_id
        for item in evidence
        if item.source_unit_id is not None
    )
    required_source_unit_ids.update(
        anchor.source_unit_id
        for owner in (*observations, *evidence)
        for anchor in owner.anchors
    )
    source_units = tuple(
        unit
        for unit in spr.source_units
        if unit.source_unit_id in required_source_unit_ids
    )

    return StructuredProcessingResultV2(
        document_ref=spr.document_ref,
        processing_run_ref=spr.processing_run_ref,
        raw_result_ref=spr.raw_result_ref,
        source_units=source_units,
        observations=observations,
        nodes=nodes,
        evidence=evidence,
        schema_id=spr.schema_id,
        schema_version=spr.schema_version,
    )
'''
_SCOPED_SPR_MARKER = "selected_node_ids = frozenset(node.node_id for node in selected_nodes)"

_TIMEOUT_ANCHOR = '''def _batch_execution_timeout_seconds(probe) -> float:
    # Bound one full batch independently from one provider HTTP attempt. The
    # outer budget covers the initial semantic request plus at most one targeted
    # missing-heading repair, including each request's bounded provider retries.
    retry_delay_budget = sum(
        min(
            probe.max_backoff_seconds,
            probe.initial_backoff_seconds * (2 ** retry_index),
        )
        for retry_index in range(max(0, probe.max_attempts - 1))
    )
    one_semantic_request_budget = (
        probe.timeout_seconds * probe.max_attempts + retry_delay_budget
    )
    return max(420.0, 2 * one_semantic_request_budget + 30.0)
'''
_TIMEOUT_REPLACEMENT = '''def _batch_execution_timeout_seconds(probe) -> float:
    # Bound one full batch independently from one provider HTTP attempt. Each
    # retry may honor Retry-After up to max_backoff_seconds, so use that true
    # worst-case delay rather than only the local exponential-backoff schedule.
    retry_delay_budget = (
        max(0, probe.max_attempts - 1) * probe.max_backoff_seconds
    )
    one_semantic_request_budget = (
        probe.timeout_seconds * probe.max_attempts + retry_delay_budget
    )
    # Cover the initial semantic request plus at most one targeted missing-
    # heading repair, with bounded local parse/validation overhead.
    return max(420.0, 2 * one_semantic_request_budget + 30.0)
'''
_TIMEOUT_MARKER = "max(0, probe.max_attempts - 1) * probe.max_backoff_seconds"

_REGRESSION_MARKER = (
    "def test_structure_refinement_scoped_batch_closes_cross_page_references("
)
_REGRESSION_BLOCK = r'''


def test_structure_refinement_scoped_batch_closes_cross_page_references() -> None:
    from app.processing.batched_structure_refinement import (
        _heading_candidate_ids,
        _scoped_spr,
    )
    from app.processing.structured_result_v2.model import (
        ProcessingEvidence,
        ProcessingNode,
        ProcessingNodeKind,
        ProcessingObservation,
        StructuredProcessingResultV2,
    )
    from app.processing.structured_result_v2.validation import validate_spr_v2
    from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind

    units = tuple(
        SourceUnit(
            f"page-{index}",
            SourceUnitKind.PHYSICAL_PAGE,
            index - 1,
            "source",
            dimensions=SourceUnitDimensions(600, 900),
        )
        for index in (1, 2, 3)
    )
    spr = StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        source_units=units,
        observations=(
            ProcessingObservation(
                "obs-page-2",
                "page-2",
                0,
                "text",
                evidence_ids=("evidence-page-2",),
            ),
            ProcessingObservation(
                "obs-cross-page",
                "page-3",
                1,
                "text",
                evidence_ids=("evidence-cross-page",),
            ),
        ),
        nodes=(
            ProcessingNode(
                "heading-parent",
                ProcessingNodeKind.HEADING,
                0,
                ("page-1",),
                text="Parent",
                heading_level=1,
            ),
            ProcessingNode(
                "heading-child",
                ProcessingNodeKind.HEADING,
                1,
                ("page-2",),
                parent_id="heading-parent",
                text="Child",
                heading_level=2,
                observation_ids=("obs-cross-page",),
                evidence_ids=("evidence-cross-page",),
            ),
        ),
        evidence=(
            ProcessingEvidence(
                "evidence-page-2",
                source_unit_id="page-2",
                observation_id="obs-page-2",
            ),
            ProcessingEvidence(
                "evidence-cross-page",
                source_unit_id="page-3",
                observation_id="obs-cross-page",
            ),
        ),
    )

    scoped = _scoped_spr(spr, ("page-2",))
    validate_spr_v2(scoped)

    assert _heading_candidate_ids(scoped) == ("heading-child",)
    assert tuple(node.node_id for node in scoped.nodes) == ("heading-child",)
    assert scoped.nodes[0].parent_id is None
    assert tuple(unit.source_unit_id for unit in scoped.source_units) == (
        "page-2",
        "page-3",
    )
    assert tuple(item.observation_id for item in scoped.observations) == (
        "obs-page-2",
        "obs-cross-page",
    )
    assert tuple(item.evidence_id for item in scoped.evidence) == (
        "evidence-page-2",
        "evidence-cross-page",
    )
'''


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} anchor")
    return source.replace(old, new, 1)


def _patch_scoped_spr() -> None:
    source = BATCH_RUNTIME_PATH.read_text(encoding="utf-8")
    if _SCOPED_SPR_MARKER in source:
        return
    source = _replace_once(
        source,
        _SCOPED_SPR_ANCHOR,
        _SCOPED_SPR_REPLACEMENT,
        label="batch-scoped SPR projection",
    )
    BATCH_RUNTIME_PATH.write_text(source, encoding="utf-8")


def _patch_timeout_budget() -> None:
    source = IMAGE_RUNTIME_PATH.read_text(encoding="utf-8")
    if _TIMEOUT_MARKER in source:
        return
    source = _replace_once(
        source,
        _TIMEOUT_ANCHOR,
        _TIMEOUT_REPLACEMENT,
        label="batch execution timeout budget",
    )
    IMAGE_RUNTIME_PATH.write_text(source, encoding="utf-8")


def _append_regression() -> None:
    source = REGRESSION_TEST_PATH.read_text(encoding="utf-8")
    if _REGRESSION_MARKER in source:
        return
    REGRESSION_TEST_PATH.write_text(
        source.rstrip() + "\n\n" + _REGRESSION_BLOCK.rstrip() + "\n",
        encoding="utf-8",
    )


def main() -> None:
    _patch_scoped_spr()
    _patch_timeout_budget()
    _append_regression()


if __name__ == "__main__":
    main()
