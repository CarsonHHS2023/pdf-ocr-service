from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.processing.llm_structure_refinement import (
    RefinementOperationKind,
    StructureRefinementOperation,
    StructureRefinementPatch,
)
from app.processing.llm_structure_refinement_provider import (
    JsonStructureRefiner,
    parse_structure_refinement_response,
)
from app.processing.pdf_page_presentation_recovery import (
    recover_pdf_observations_for_page_presentation,
)
from app.processing.structured_result_v2.model import (
    ProcessingNode,
    ProcessingNodeKind,
    ProcessingNodeRecoveryState,
    StructuredProcessingResultV2,
)
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind


def _spr() -> StructuredProcessingResultV2:
    unit = SourceUnit(
        "page-1",
        SourceUnitKind.PHYSICAL_PAGE,
        0,
        "source",
        dimensions=SourceUnitDimensions(1000, 1400),
    )
    return StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        raw_result_ref="raw",
        source_units=(unit,),
        observations=(),
        nodes=(
            ProcessingNode(
                "toc-item",
                ProcessingNodeKind.LIST_ITEM,
                0,
                ("page-1",),
                text="Section...... 3",
            ),
        ),
    )


def _unresolved_spr(
    kind: ProcessingNodeKind,
    recovery_state: ProcessingNodeRecoveryState,
) -> StructuredProcessingResultV2:
    base = _spr()
    return StructuredProcessingResultV2(
        document_ref=base.document_ref,
        processing_run_ref=base.processing_run_ref,
        raw_result_ref=base.raw_result_ref,
        source_units=base.source_units,
        observations=base.observations,
        nodes=(
            ProcessingNode(
                "unresolved-node",
                kind,
                0,
                ("page-1",),
                text="Unresolved visible text",
                recovery_state=recovery_state,
            ),
        ),
    )


def test_json_provider_parses_only_bounded_operations() -> None:
    patch = parse_structure_refinement_response(
        {
            "operations": [
                {
                    "op": "set_toc_level",
                    "node_id": "toc-item",
                    "confidence": 0.97,
                    "reason_codes": ["layout_hierarchy"],
                    "toc_level": 2,
                }
            ]
        },
        model_id="test-model",
    )
    assert patch.model_id == "test-model"
    assert patch.operations[0].kind is RefinementOperationKind.SET_TOC_LEVEL
    assert patch.operations[0].toc_level == 2


def test_json_provider_rejects_unbounded_or_malformed_output() -> None:
    with pytest.raises(ValueError):
        parse_structure_refinement_response({"document": "rewritten"}, model_id="test-model")
    with pytest.raises(ValueError):
        parse_structure_refinement_response(
            {"operations": [{"op": "replace_document", "node_id": "x", "confidence": 1, "reason_codes": ["x"]}]},
            model_id="test-model",
        )


def test_json_refiner_sends_deterministic_request() -> None:
    seen = []
    refiner = JsonStructureRefiner(
        "test-model",
        lambda request: seen.append(request) or {"operations": []},
    )
    patch = refiner.propose(_spr())
    assert patch.operations == ()
    assert seen[0]["document_ref"] == "doc"
    assert seen[0]["nodes"][0]["node_id"] == "toc-item"


def test_page_presentation_applies_injected_refiner_before_decoration(monkeypatch) -> None:
    recovered = _spr()
    monkeypatch.setattr(
        "app.processing.pdf_page_presentation_recovery.recover_pdf_observations_via_mineru_popo",
        lambda bundle: recovered,
    )

    class Refiner:
        def propose(self, spr):
            return StructureRefinementPatch(
                model_id="test-model",
                operations=(
                    StructureRefinementOperation(
                        kind=RefinementOperationKind.SET_TOC_LEVEL,
                        node_id="toc-item",
                        confidence=0.99,
                        reason_codes=("layout_hierarchy",),
                        toc_level=2,
                    ),
                ),
            )

    result = recover_pdf_observations_for_page_presentation(
        SimpleNamespace(observations=()),
        structure_refiner=Refiner(),
    )
    assert result.nodes[0].metadata["toc_level"] == 2
    assert result.nodes[0].metadata["toc_level_source"] == "llm_structure_refinement"


def test_optional_provider_failure_degrades_by_default_and_can_fail_closed(monkeypatch) -> None:
    recovered = _spr()
    monkeypatch.setattr(
        "app.processing.pdf_page_presentation_recovery.recover_pdf_observations_via_mineru_popo",
        lambda bundle: recovered,
    )

    class BrokenRefiner:
        def propose(self, spr):
            raise RuntimeError("provider unavailable")

    result = recover_pdf_observations_for_page_presentation(
        SimpleNamespace(observations=()),
        structure_refiner=BrokenRefiner(),
    )
    assert result.nodes[0].metadata is None

    with pytest.raises(RuntimeError, match="provider unavailable"):
        recover_pdf_observations_for_page_presentation(
            SimpleNamespace(observations=()),
            structure_refiner=BrokenRefiner(),
            refinement_fail_closed=True,
        )


@pytest.mark.parametrize(
    ("kind", "recovery_state"),
    (
        (ProcessingNodeKind.UNKNOWN, ProcessingNodeRecoveryState.COMPLETE),
        (ProcessingNodeKind.PARAGRAPH, ProcessingNodeRecoveryState.DEGRADED),
    ),
)
def test_provider_execution_failure_fails_closed_for_unresolved_targets(
    monkeypatch,
    kind: ProcessingNodeKind,
    recovery_state: ProcessingNodeRecoveryState,
) -> None:
    recovered = _unresolved_spr(kind, recovery_state)
    monkeypatch.setattr(
        "app.processing.pdf_page_presentation_recovery.recover_pdf_observations_via_mineru_popo",
        lambda bundle: recovered,
    )

    class BrokenRefiner:
        def propose(self, spr):
            raise RuntimeError("provider response parse failed")

    with pytest.raises(RuntimeError, match="provider response parse failed"):
        recover_pdf_observations_for_page_presentation(
            SimpleNamespace(observations=()),
            structure_refiner=BrokenRefiner(),
        )
