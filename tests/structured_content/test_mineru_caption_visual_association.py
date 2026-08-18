from __future__ import annotations

from app.processing.mineru_popo_pdf_recovery import recover_pdf_observations_via_mineru_popo
from app.processing.normalized_observations import NormalizedObservationBundle
from app.processing.structured_result_v2.model import ProcessingEvidence, ProcessingObservation, ProcessingNodeKind
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind, SpatialAnchor
from app.structured_content_v2.transformation import TransformationContextV2, transform_spr_v2_to_candidate


UNIT_ID = "pdf-page:000001"


def _pair(order: int, kind: str, text: str | None, bbox: tuple[float, float, float, float]):
    observation_id = f"obs-{order}"
    evidence_id = f"ev-{order}"
    anchor = SpatialAnchor(UNIT_ID, *bbox)
    observation = ProcessingObservation(
        observation_id=observation_id,
        source_unit_id=UNIT_ID,
        order=order,
        observed_kind=kind,
        text=text,
        anchors=(anchor,),
        evidence_ids=(evidence_id,),
    )
    evidence = ProcessingEvidence(
        evidence_id=evidence_id,
        source_unit_id=UNIT_ID,
        anchors=(anchor,),
        observation_id=observation_id,
        processing_run_ref="run-1",
        raw_result_ref="raw-1",
        provider_ref="paddle-vl",
    )
    return observation, evidence


def _bundle(*pairs) -> NormalizedObservationBundle:
    return NormalizedObservationBundle(
        document_ref="doc-1",
        source_ref="source-1",
        processing_run_ref="run-1",
        raw_result_ref="raw-1",
        source_units=(
            SourceUnit(
                source_unit_id=UNIT_ID,
                kind=SourceUnitKind.PHYSICAL_PAGE,
                source_order=0,
                source_ref="source-1",
                dimensions=SourceUnitDimensions(600, 800),
            ),
        ),
        observations=tuple(pair[0] for pair in pairs),
        evidence=tuple(pair[1] for pair in pairs),
    )


def test_late_figure_caption_reparents_to_visual_after_intervening_text_and_formula() -> None:
    pairs = (
        _pair(0, "paragraph_title", "1.5 证明定理", (0.08, 0.05, 0.45, 0.09)),
        _pair(1, "figure", None, (0.22, 0.70, 0.62, 0.88)),
        _pair(2, "text", "即", (0.08, 0.73, 0.14, 0.76)),
        _pair(3, "formula", "P(A')=1-P(A)", (0.42, 0.77, 0.72, 0.81)),
        _pair(4, "text", "(b)从图1-7可以看到", (0.08, 0.83, 0.44, 0.87)),
        _pair(
            5,
            "figure_caption",
            "图 1-7",
            (0.37279596977329976, 0.8991097922848664, 0.41981528127623846, 0.9115727002967359),
        ),
    )

    spr = recover_pdf_observations_via_mineru_popo(_bundle(*pairs))
    figure = next(node for node in spr.nodes if node.kind is ProcessingNodeKind.FIGURE)
    caption = next(node for node in spr.nodes if node.kind is ProcessingNodeKind.CAPTION)

    assert caption.parent_id == figure.node_id
    assert caption.metadata["caption_association_policy"] == "same_page_spatial_visual_v1"
    assert caption.metadata["caption_association_recovered"] is True
    assert caption.metadata["caption_association_target_kind"] == "figure"
    assert caption.metadata["caption_association_vertical_gap"] < 0.03

    candidate = transform_spr_v2_to_candidate(
        spr,
        context=TransformationContextV2(
            document_ref="doc-1",
            candidate_id="candidate-1",
            lineage_key="lineage-1",
            structured_processing_result_ref="spr-1",
        ),
    )
    canonical_figure = next(node for node in candidate.nodes if node.node_type.value == "figure")
    canonical_caption = next(node for node in candidate.nodes if node.node_type.value == "caption")
    assert canonical_caption.parent_id == canonical_figure.node_id


def test_table_title_can_associate_to_a_table_that_appears_later_in_provider_order() -> None:
    pairs = (
        _pair(0, "paragraph_title", "统计表", (0.08, 0.05, 0.30, 0.09)),
        _pair(1, "table_title", "表 1-2", (0.28, 0.20, 0.55, 0.24)),
        _pair(2, "text", "说明", (0.08, 0.26, 0.18, 0.29)),
        _pair(3, "table", None, (0.18, 0.25, 0.82, 0.58)),
    )

    spr = recover_pdf_observations_via_mineru_popo(_bundle(*pairs))
    table = next(node for node in spr.nodes if node.kind is ProcessingNodeKind.TABLE)
    caption = next(node for node in spr.nodes if node.kind is ProcessingNodeKind.CAPTION)

    assert caption.parent_id == table.node_id
    assert caption.metadata["caption_association_target_kind"] == "table"


def test_table_title_replaces_wrong_immediate_figure_parent_with_table() -> None:
    pairs = (
        _pair(0, "paragraph_title", "统计表", (0.08, 0.05, 0.30, 0.09)),
        _pair(1, "figure", None, (0.08, 0.10, 0.38, 0.30)),
        _pair(2, "table_title", "表 1-2", (0.25, 0.35, 0.75, 0.39)),
        _pair(3, "table", None, (0.18, 0.40, 0.82, 0.70)),
    )

    spr = recover_pdf_observations_via_mineru_popo(_bundle(*pairs))
    figure = next(node for node in spr.nodes if node.kind is ProcessingNodeKind.FIGURE)
    table = next(node for node in spr.nodes if node.kind is ProcessingNodeKind.TABLE)
    caption = next(node for node in spr.nodes if node.kind is ProcessingNodeKind.CAPTION)

    assert caption.parent_id == table.node_id
    assert caption.parent_id != figure.node_id
    assert caption.metadata["caption_association_original_parent_id"] == figure.node_id
    assert caption.metadata["caption_association_target_kind"] == "table"


def test_far_caption_is_not_force_attached_to_a_visual() -> None:
    pairs = (
        _pair(0, "paragraph_title", "章节", (0.08, 0.05, 0.30, 0.09)),
        _pair(1, "figure", None, (0.15, 0.12, 0.45, 0.30)),
        _pair(2, "text", "正文", (0.08, 0.40, 0.80, 0.48)),
        _pair(3, "figure_caption", "远处标题", (0.20, 0.80, 0.40, 0.84)),
    )

    spr = recover_pdf_observations_via_mineru_popo(_bundle(*pairs))
    figure = next(node for node in spr.nodes if node.kind is ProcessingNodeKind.FIGURE)
    caption = next(node for node in spr.nodes if node.kind is ProcessingNodeKind.CAPTION)

    assert caption.parent_id != figure.node_id
    assert "caption_association_policy" not in (caption.metadata or {})


def test_ambiguous_caption_between_two_visuals_is_left_unbound() -> None:
    pairs = (
        _pair(0, "paragraph_title", "章节", (0.08, 0.05, 0.30, 0.09)),
        _pair(1, "figure", None, (0.10, 0.30, 0.42, 0.58)),
        _pair(2, "figure", None, (0.58, 0.30, 0.90, 0.58)),
        _pair(3, "text", "正文", (0.08, 0.60, 0.92, 0.64)),
        _pair(4, "caption", "共同标题", (0.32, 0.60, 0.68, 0.64)),
    )

    spr = recover_pdf_observations_via_mineru_popo(_bundle(*pairs))
    figures = [node for node in spr.nodes if node.kind is ProcessingNodeKind.FIGURE]
    caption = next(node for node in spr.nodes if node.kind is ProcessingNodeKind.CAPTION)

    assert all(caption.parent_id != figure.node_id for figure in figures)
    assert "caption_association_policy" not in (caption.metadata or {})
