from __future__ import annotations

from app.processing.mineru_popo_pdf_recovery import recover_pdf_observations_via_mineru_popo
from app.processing.normalized_observations import NormalizedObservationBundle
from app.processing.structured_result_v2.model import ProcessingEvidence, ProcessingObservation
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind, SpatialAnchor
from app.structured_content_v2.transformation import TransformationContextV2, transform_spr_v2_to_candidate


def _observation(order: int, kind: str, text: str):
    unit_id = "pdf-page:000001"
    observation_id = f"obs-{order}"
    evidence_id = f"ev-{order}"
    anchor = SpatialAnchor(unit_id, 0.1, 0.1 + order * 0.1, 0.9, 0.16 + order * 0.1)
    return (
        ProcessingObservation(
            observation_id=observation_id,
            source_unit_id=unit_id,
            order=order,
            observed_kind=kind,
            text=text,
            anchors=(anchor,),
            evidence_ids=(evidence_id,),
        ),
        ProcessingEvidence(
            evidence_id=evidence_id,
            source_unit_id=unit_id,
            anchors=(anchor,),
            observation_id=observation_id,
            processing_run_ref="run-1",
            raw_result_ref="raw-1",
            provider_ref="paddle-vl",
        ),
    )


def test_mineru_recovery_semantics_survive_spr_to_structured_content() -> None:
    pairs = (
        _observation(0, "header", "第一章 趋势线"),
        _observation(1, "paragraph_title", "第一章 趋势线"),
        _observation(2, "paragraph_title", "【本章内容概要】"),
        _observation(3, "toc", "一、趋势交易法流程……1\n二、趋势线……1\n三、心语……12"),
        _observation(4, "text", "趋势交易法的流程是："),
    )
    bundle = NormalizedObservationBundle(
        document_ref="doc-1",
        source_ref="source-1",
        processing_run_ref="run-1",
        raw_result_ref="raw-1",
        source_units=(
            SourceUnit(
                source_unit_id="pdf-page:000001",
                kind=SourceUnitKind.PHYSICAL_PAGE,
                source_order=0,
                source_ref="source-1",
                dimensions=SourceUnitDimensions(600, 800),
            ),
        ),
        observations=tuple(pair[0] for pair in pairs),
        evidence=tuple(pair[1] for pair in pairs),
    )

    spr = recover_pdf_observations_via_mineru_popo(bundle)
    candidate = transform_spr_v2_to_candidate(
        spr,
        context=TransformationContextV2(
            document_ref="doc-1",
            candidate_id="candidate-1",
            lineage_key="lineage-1",
            structured_processing_result_ref="spr-1",
        ),
    )

    assert [node.node_type.value for node in candidate.nodes] == [
        "heading",
        "heading",
        "list",
        "list_item",
        "list_item",
        "list_item",
        "paragraph",
    ]
    assert [node.heading_level for node in candidate.nodes[:2]] == [1, 2]
    assert candidate.nodes[0].text == "第一章 趋势线"
    assert [node.text for node in candidate.nodes[3:6]] == [
        "一、趋势交易法流程……1",
        "二、趋势线……1",
        "三、心语……12",
    ]
