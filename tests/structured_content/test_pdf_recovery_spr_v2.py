from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.processing.normalized_observations import NormalizedObservationBundle
from app.processing.pdf_recovery import recover_pdf_observations_to_spr_v2
from app.processing.structured_result_v2.model import (
    ProcessingEvidence,
    ProcessingNodeKind,
    ProcessingObservation,
    normalize_spr_v2,
)
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind, SpatialAnchor


def _unit(page: int) -> SourceUnit:
    return SourceUnit(
        source_unit_id=f"pdf-page:{page:06d}",
        kind=SourceUnitKind.PHYSICAL_PAGE,
        source_order=page - 1,
        source_ref="source-pdf",
        dimensions=SourceUnitDimensions(600, 800),
    )


def _obs(
    page: int,
    order: int,
    kind: str,
    text: str | None,
    *,
    heading_level: int | None = None,
    top: float | None = None,
    bottom: float | None = None,
):
    unit_id = f"pdf-page:{page:06d}"
    obs_id = f"obs-{page}-{order}-{kind}"
    ev_id = f"ev-{page}-{order}-{kind}"
    resolved_top = top if top is not None else 0.1 + order * 0.05
    resolved_bottom = bottom if bottom is not None else resolved_top + 0.04
    anchor = SpatialAnchor(unit_id, 0.1, resolved_top, 0.9, resolved_bottom)
    metadata = {"heading_level": heading_level} if heading_level is not None else None
    observation = ProcessingObservation(
        observation_id=obs_id,
        source_unit_id=unit_id,
        order=order,
        observed_kind=kind,
        text=text,
        anchors=(anchor,),
        confidence=0.9,
        evidence_ids=(ev_id,),
        metadata=metadata,
    )
    evidence = ProcessingEvidence(
        evidence_id=ev_id,
        source_unit_id=unit_id,
        anchors=(anchor,),
        observation_id=obs_id,
        processing_run_ref="run-1",
        raw_result_ref="raw-1",
        provider_ref="provider-normalized",
    )
    return observation, evidence


def _bundle(observations, evidence, units=None):
    return NormalizedObservationBundle(
        document_ref="doc-1",
        source_ref="source-pdf",
        processing_run_ref="run-1",
        raw_result_ref="raw-1",
        source_units=tuple(units or (_unit(1), _unit(2))),
        observations=tuple(observations),
        evidence=tuple(evidence),
    )


def test_recovery_builds_heading_hierarchy_and_preserves_lineage() -> None:
    title, title_ev = _obs(1, 0, "doc_title", "Atlas")
    heading, heading_ev = _obs(1, 1, "paragraph_title", "1.1 Background")
    paragraph, paragraph_ev = _obs(2, 0, "text", "Body on page two.")

    spr = recover_pdf_observations_to_spr_v2(
        _bundle((paragraph, heading, title), (paragraph_ev, heading_ev, title_ev))
    )

    assert [node.kind for node in spr.nodes] == [
        ProcessingNodeKind.TITLE,
        ProcessingNodeKind.HEADING,
        ProcessingNodeKind.PARAGRAPH,
    ]
    assert [node.heading_level for node in spr.nodes[:2]] == [1, 2]
    assert spr.nodes[1].parent_id == spr.nodes[0].node_id
    assert spr.nodes[2].parent_id == spr.nodes[1].node_id
    assert spr.nodes[2].observation_ids == (paragraph.observation_id,)
    assert spr.nodes[2].metadata["recovery_engine"] == "mineru_popo_v2"


def test_page_furniture_is_retained_as_non_body_presentation_content() -> None:
    observations = []
    evidence = []
    for order, (kind, text) in enumerate(
        (
            ("header", "第一章 趋势线"),
            ("footer", "版权信息"),
            ("number", "XIV"),
            ("aside_text", "边注"),
            ("text", "可阅读正文。"),
        )
    ):
        obs, ev = _obs(1, order, kind, text)
        observations.append(obs)
        evidence.append(ev)

    spr = recover_pdf_observations_to_spr_v2(_bundle(observations, evidence, units=(_unit(1),)))

    assert [node.kind for node in spr.nodes] == [
        ProcessingNodeKind.PARAGRAPH,
        ProcessingNodeKind.HEADER,
        ProcessingNodeKind.FOOTER,
        ProcessingNodeKind.FOOTER,
        ProcessingNodeKind.FOOTNOTE,
    ]
    assert [node.text for node in spr.nodes] == [
        "可阅读正文。",
        "第一章 趋势线",
        "版权信息",
        "XIV",
        "边注",
    ]
    assert all(node.parent_id is None for node in spr.nodes[1:])
    assert all(node.metadata["content_class"] == "furniture" for node in spr.nodes[1:])
    assert len(spr.observations) == 5
    assert len(spr.evidence) == 5


@pytest.mark.parametrize("text", ["12", "XIV", "iv", "十二", "第十二页"])
def test_page_number_classification_never_depends_on_number_script(text: str) -> None:
    number, number_ev = _obs(1, 0, "page-number", text)
    spr = recover_pdf_observations_to_spr_v2(_bundle((number,), (number_ev,), units=(_unit(1),)))
    assert len(spr.nodes) == 1
    assert spr.nodes[0].kind is ProcessingNodeKind.HEADER
    assert spr.nodes[0].text == text
    assert spr.nodes[0].metadata["presentation_role"] == "page_number"
    assert spr.nodes[0].metadata["presentation_position_role"] == "header"
    assert spr.nodes[0].metadata["presentation_number_position_rule"] == "bounded_page_furniture_band_v1"
    assert spr.observations[0].text == text


def test_formula_number_remains_formula_content() -> None:
    formula_number, ev = _obs(1, 0, "formula_number", "(12)")
    spr = recover_pdf_observations_to_spr_v2(_bundle((formula_number,), (ev,), units=(_unit(1),)))
    assert len(spr.nodes) == 1
    assert spr.nodes[0].kind is ProcessingNodeKind.FORMULA
    assert spr.nodes[0].text == "(12)"


def test_toc_observation_becomes_list_with_independent_items() -> None:
    toc, ev = _obs(1, 0, "toc", "一、趋势交易法流程……1\n二、趋势线……1\n三、心语……12")
    spr = recover_pdf_observations_to_spr_v2(_bundle((toc,), (ev,), units=(_unit(1),)))

    assert [node.kind for node in spr.nodes] == [
        ProcessingNodeKind.LIST,
        ProcessingNodeKind.LIST_ITEM,
        ProcessingNodeKind.LIST_ITEM,
        ProcessingNodeKind.LIST_ITEM,
    ]
    assert [node.text for node in spr.nodes[1:]] == [
        "一、趋势交易法流程……1",
        "二、趋势线……1",
        "三、心语……12",
    ]
    assert all(node.parent_id == spr.nodes[0].node_id for node in spr.nodes[1:])


def test_cross_page_paragraph_continuation_is_recovered_before_spr() -> None:
    first, first_ev = _obs(1, 0, "text", "这是跨页但没有结束的自然段", top=0.82, bottom=0.96)
    second, second_ev = _obs(2, 0, "text", "继续到下一页并在这里结束。", top=0.02, bottom=0.14)

    spr = recover_pdf_observations_to_spr_v2(
        _bundle((first, second), (first_ev, second_ev), units=(_unit(1), _unit(2)))
    )

    assert len(spr.nodes) == 1
    node = spr.nodes[0]
    assert node.kind is ProcessingNodeKind.PARAGRAPH
    assert node.text == "这是跨页但没有结束的自然段继续到下一页并在这里结束。"
    assert node.source_unit_ids == ("pdf-page:000001", "pdf-page:000002")
    assert node.observation_ids == (first.observation_id, second.observation_id)
    assert node.metadata["recovery_rule"] == "mineru_popo_cross_page_paragraph"


def test_explicit_and_numbered_heading_levels_are_preserved() -> None:
    h1, h1_ev = _obs(1, 0, "paragraph_title", "第一章 趋势线", heading_level=1)
    h2, h2_ev = _obs(1, 1, "paragraph_title", "2.3 Scope")
    h3, h3_ev = _obs(1, 2, "paragraph_title", "2.3.1 Details")
    spr = recover_pdf_observations_to_spr_v2(
        _bundle((h1, h2, h3), (h1_ev, h2_ev, h3_ev), units=(_unit(1),))
    )
    assert [node.heading_level for node in spr.nodes] == [1, 2, 3]
    assert spr.nodes[1].parent_id == spr.nodes[0].node_id
    assert spr.nodes[2].parent_id == spr.nodes[1].node_id


def test_recovery_is_deterministic_for_equivalent_tuple_order() -> None:
    a, a_ev = _obs(1, 0, "doc_title", "Title")
    b, b_ev = _obs(2, 0, "text", "Body.")
    units = (_unit(1), _unit(2))
    first = recover_pdf_observations_to_spr_v2(_bundle((a, b), (a_ev, b_ev), units=units))
    second = recover_pdf_observations_to_spr_v2(
        _bundle((b, a), (b_ev, a_ev), units=tuple(reversed(units)))
    )
    assert first == second
    assert normalize_spr_v2(first) == normalize_spr_v2(second)


def test_invalid_normalized_graph_fails_closed_before_recovery() -> None:
    observation, evidence = _obs(1, 0, "text", "Body")
    broken = ProcessingObservation(
        observation_id=observation.observation_id,
        source_unit_id=observation.source_unit_id,
        order=observation.order,
        observed_kind=observation.observed_kind,
        text=observation.text,
        anchors=observation.anchors,
        confidence=observation.confidence,
        evidence_ids=("missing-evidence",),
    )
    with pytest.raises(ValueError, match="references missing evidence"):
        recover_pdf_observations_to_spr_v2(_bundle((broken,), (evidence,), units=(_unit(1),)))


def test_pdf_recovery_has_no_provider_runtime_or_persistence_dependencies() -> None:
    imported: set[str] = set()
    for path in (
        Path("app/processing/pdf_recovery.py"),
        Path("app/processing/mineru_popo_pdf_recovery.py"),
        Path("app/processing/pdf_page_presentation_recovery.py"),
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    forbidden_prefixes = (
        "sqlalchemy", "fastapi", "modal", "requests", "httpx",
        "app.database", "app.models", "app.routers", "app.services",
        "app.processing.paddle_vl", "app.structured_content_v2", "app.reader",
    )
    assert not any(name.startswith(forbidden_prefixes) for name in imported)
