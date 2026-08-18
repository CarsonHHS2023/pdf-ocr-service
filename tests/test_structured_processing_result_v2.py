from __future__ import annotations

import copy

import pytest

from app.processing.structured_result_v2 import (
    ProcessingEvidence,
    ProcessingNode,
    ProcessingNodeKind,
    ProcessingObservation,
    StructuredProcessingResultV2,
    normalize_spr_v2,
    validate_spr_v2,
)
from app.source_units import (
    DomAnchor,
    SourceUnit,
    SourceUnitDimensions,
    SourceUnitKind,
    SpatialAnchor,
    TemporalAnchor,
    TextSpanAnchor,
)


def _pdf_spr() -> StructuredProcessingResultV2:
    p1 = SourceUnit(
        "page-1",
        SourceUnitKind.PHYSICAL_PAGE,
        0,
        "pdf-source",
        dimensions=SourceUnitDimensions(1000, 1400),
    )
    p2 = SourceUnit(
        "page-2",
        SourceUnitKind.PHYSICAL_PAGE,
        1,
        "pdf-source",
        dimensions=SourceUnitDimensions(1000, 1400),
    )
    h_obs = ProcessingObservation(
        "obs-heading",
        "page-1",
        0,
        "heading",
        text="Chapter 1",
        anchors=(SpatialAnchor("page-1", 0.1, 0.1, 0.8, 0.18),),
    )
    p_obs = ProcessingObservation(
        "obs-paragraph",
        "page-2",
        0,
        "paragraph",
        text="Paragraph on the next physical page.",
        anchors=(SpatialAnchor("page-2", 0.1, 0.2, 0.9, 0.35),),
    )
    heading = ProcessingNode(
        "node-heading",
        ProcessingNodeKind.HEADING,
        0,
        ("page-1",),
        text="Chapter 1",
        heading_level=1,
        anchors=h_obs.anchors,
        observation_ids=(h_obs.observation_id,),
    )
    paragraph = ProcessingNode(
        "node-paragraph",
        ProcessingNodeKind.PARAGRAPH,
        1,
        ("page-2",),
        parent_id="node-heading",
        text="Paragraph on the next physical page.",
        anchors=p_obs.anchors,
        observation_ids=(p_obs.observation_id,),
    )
    return StructuredProcessingResultV2(
        document_ref="doc-pdf",
        processing_run_ref="run-pdf",
        raw_result_ref="raw-pdf",
        source_units=(p1, p2),
        observations=(h_obs, p_obs),
        nodes=(heading, paragraph),
    )


def test_pdf_allows_cross_source_unit_semantic_hierarchy() -> None:
    spr = _pdf_spr()
    validate_spr_v2(spr)

    assert spr.nodes[1].parent_id == "node-heading"
    assert spr.nodes[0].source_unit_ids == ("page-1",)
    assert spr.nodes[1].source_unit_ids == ("page-2",)


def test_txt_uses_text_flow_and_can_span_bounded_source_units_without_fake_pages() -> None:
    u1 = SourceUnit(
        "text-0",
        SourceUnitKind.TEXT_FLOW,
        0,
        "txt-source",
        source_span=TextSpanAnchor("text-0", 0, 1000),
    )
    u2 = SourceUnit(
        "text-1",
        SourceUnitKind.TEXT_FLOW,
        1,
        "txt-source",
        source_span=TextSpanAnchor("text-1", 1000, 2000),
    )
    h = ProcessingObservation(
        "obs-h",
        "text-0",
        0,
        "heading",
        text="第一章 绪论",
        anchors=(TextSpanAnchor("text-0", 0, 5),),
    )
    p1 = ProcessingObservation(
        "obs-p1",
        "text-0",
        1,
        "paragraph",
        text="第一部分",
        anchors=(TextSpanAnchor("text-0", 6, 10),),
    )
    p2 = ProcessingObservation(
        "obs-p2",
        "text-1",
        0,
        "paragraph",
        text="继续内容",
        anchors=(TextSpanAnchor("text-1", 1000, 1004),),
    )
    heading = ProcessingNode(
        "n-h",
        ProcessingNodeKind.HEADING,
        0,
        ("text-0",),
        text="第一章 绪论",
        heading_level=1,
        anchors=h.anchors,
        observation_ids=("obs-h",),
    )
    merged_paragraph = ProcessingNode(
        "n-p",
        ProcessingNodeKind.PARAGRAPH,
        1,
        ("text-0", "text-1"),
        parent_id="n-h",
        text="第一部分继续内容",
        anchors=(p1.anchors[0], p2.anchors[0]),
        observation_ids=("obs-p1", "obs-p2"),
    )
    spr = StructuredProcessingResultV2(
        document_ref="doc-txt",
        processing_run_ref="run-txt",
        source_units=(u1, u2),
        observations=(h, p1, p2),
        nodes=(heading, merged_paragraph),
    )

    validate_spr_v2(spr)
    payload = normalize_spr_v2(spr)
    assert all(unit["kind"] == "text_flow" for unit in payload["source_units"])
    assert all("dimensions" not in unit for unit in payload["source_units"])
    assert payload["nodes"][1]["source_unit_ids"] == ["text-0", "text-1"]


def test_normalization_is_independent_of_input_tuple_order() -> None:
    spr = _pdf_spr()
    permuted = StructuredProcessingResultV2(
        document_ref=spr.document_ref,
        processing_run_ref=spr.processing_run_ref,
        raw_result_ref=spr.raw_result_ref,
        source_units=tuple(reversed(spr.source_units)),
        observations=tuple(reversed(spr.observations)),
        nodes=tuple(reversed(spr.nodes)),
        evidence=tuple(reversed(spr.evidence)),
    )

    validate_spr_v2(spr)
    validate_spr_v2(permuted)
    assert normalize_spr_v2(spr) == normalize_spr_v2(permuted)


def test_future_format_fitness_uses_dom_and_temporal_anchors() -> None:
    html = SourceUnit("html-0", SourceUnitKind.HTML_SECTION, 0, "html-source")
    audio = SourceUnit("audio-0", SourceUnitKind.AUDIO_SEGMENT, 1, "audio-source", duration_ms=30_000)
    video = SourceUnit(
        "video-0",
        SourceUnitKind.VIDEO_SEGMENT,
        2,
        "video-source",
        duration_ms=12_000,
        dimensions=SourceUnitDimensions(1920, 1080),
    )
    observations = (
        ProcessingObservation("o-html", "html-0", 0, "paragraph", anchors=(DomAnchor("html-0", "body/main/p[1]"),)),
        ProcessingObservation("o-audio", "audio-0", 0, "speech", anchors=(TemporalAnchor("audio-0", 0, 5000),)),
        ProcessingObservation(
            "o-video",
            "video-0",
            0,
            "scene_text",
            anchors=(TemporalAnchor("video-0", 1000, 3000), SpatialAnchor("video-0", 0.1, 0.1, 0.9, 0.9)),
        ),
    )
    nodes = (
        ProcessingNode("n-html", ProcessingNodeKind.PARAGRAPH, 0, ("html-0",), anchors=observations[0].anchors),
        ProcessingNode("n-audio", ProcessingNodeKind.PARAGRAPH, 1, ("audio-0",), anchors=observations[1].anchors),
        ProcessingNode("n-video", ProcessingNodeKind.PARAGRAPH, 2, ("video-0",), anchors=observations[2].anchors),
    )
    spr = StructuredProcessingResultV2(
        document_ref="future-doc",
        processing_run_ref="future-run",
        source_units=(html, audio, video),
        observations=observations,
        nodes=nodes,
    )

    validate_spr_v2(spr)


def test_validation_rejects_missing_anchor_unit_and_cross_owner_observation_anchor() -> None:
    unit = SourceUnit(
        "text-0",
        SourceUnitKind.TEXT_FLOW,
        0,
        "txt-source",
        source_span=TextSpanAnchor("text-0", 0, 100),
    )
    bad_observation = ProcessingObservation(
        "obs",
        "text-0",
        0,
        "paragraph",
        anchors=(TextSpanAnchor("other", 0, 1),),
    )
    spr = StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        source_units=(unit,),
        observations=(bad_observation,),
        nodes=(),
    )

    with pytest.raises(ValueError, match="missing source unit"):
        validate_spr_v2(spr)


def test_validation_rejects_duplicate_source_order() -> None:
    one = SourceUnit("html-a", SourceUnitKind.HTML_SECTION, 0, "source")
    two = SourceUnit("html-b", SourceUnitKind.HTML_SECTION, 0, "source")
    spr = StructuredProcessingResultV2("doc", "run", (one, two), (), ())

    with pytest.raises(ValueError, match="duplicate source_order"):
        validate_spr_v2(spr)


def test_validation_rejects_missing_parent_self_parent_and_cycles() -> None:
    unit = SourceUnit("html", SourceUnitKind.HTML_SECTION, 0, "source")

    missing_parent = StructuredProcessingResultV2(
        "doc",
        "run",
        (unit,),
        (),
        (ProcessingNode("a", ProcessingNodeKind.PARAGRAPH, 0, ("html",), parent_id="missing"),),
    )
    with pytest.raises(ValueError, match="missing parent"):
        validate_spr_v2(missing_parent)

    self_parent = StructuredProcessingResultV2(
        "doc",
        "run",
        (unit,),
        (),
        (ProcessingNode("a", ProcessingNodeKind.PARAGRAPH, 0, ("html",), parent_id="a"),),
    )
    with pytest.raises(ValueError, match="cannot parent itself"):
        validate_spr_v2(self_parent)

    cycle = StructuredProcessingResultV2(
        "doc",
        "run",
        (unit,),
        (),
        (
            ProcessingNode("a", ProcessingNodeKind.PARAGRAPH, 0, ("html",), parent_id="b"),
            ProcessingNode("b", ProcessingNodeKind.PARAGRAPH, 1, ("html",), parent_id="a"),
        ),
    )
    with pytest.raises(ValueError, match="cycle"):
        validate_spr_v2(cycle)


def test_evidence_references_are_validated() -> None:
    unit = SourceUnit("html", SourceUnitKind.HTML_SECTION, 0, "source")
    observation = ProcessingObservation("obs", "html", 0, "paragraph")
    evidence = ProcessingEvidence(
        "ev",
        source_unit_id="html",
        observation_id="obs",
        provider_ref="provider-result-1",
        processing_run_ref="run",
    )
    node = ProcessingNode(
        "node",
        ProcessingNodeKind.PARAGRAPH,
        0,
        ("html",),
        observation_ids=("obs",),
        evidence_ids=("ev",),
    )
    spr = StructuredProcessingResultV2(
        "doc",
        "run",
        (unit,),
        (observation,),
        (node,),
        evidence=(evidence,),
    )

    validate_spr_v2(spr)

    bad = copy.copy(spr)
    object.__setattr__(bad, "evidence", (ProcessingEvidence("ev", observation_id="missing"),))
    with pytest.raises(ValueError, match="missing observation"):
        validate_spr_v2(bad)
