from __future__ import annotations

from app.source_units import (
    DomAnchor,
    SourceUnit,
    SourceUnitDimensions,
    SourceUnitKind,
    SourceUnitRecoveryState,
    SpatialAnchor,
    TemporalAnchor,
    TextSpanAnchor,
)
from app.structured_content_v2 import (
    AssetRecoveryStateV2,
    AssetReferenceV2,
    AssetRenditionReferenceV2,
    AssetRenditionRoleV2,
    AssetRoleV2,
    ContentNodeTypeV2,
    ContentNodeV2,
    ContentRecoveryStateV2,
    ContentRecoverySummaryV2,
    EvidenceReferenceV2,
    NodeRecoveryStateV2,
    StructuredContentCandidateV2,
    StructuredSourceUnit,
    normalize_candidate_v2,
    validate_candidate_v2,
)


def _summary(*units: SourceUnit) -> ContentRecoverySummaryV2:
    states = [unit.recovery_state for unit in units]
    if not units or all(state is SourceUnitRecoveryState.COMPLETE for state in states):
        state = ContentRecoveryStateV2.COMPLETE
    elif all(state is SourceUnitRecoveryState.UNAVAILABLE for state in states):
        state = ContentRecoveryStateV2.UNAVAILABLE
    else:
        state = ContentRecoveryStateV2.DEGRADED
    return ContentRecoverySummaryV2(
        state=state,
        total_source_units=len(units),
        complete_source_units=sum(state_ is SourceUnitRecoveryState.COMPLETE for state_ in states),
        degraded_source_units=sum(state_ is SourceUnitRecoveryState.DEGRADED for state_ in states),
        no_usable_semantic_content_source_units=sum(
            state_ is SourceUnitRecoveryState.NO_USABLE_SEMANTIC_CONTENT for state_ in states
        ),
        unavailable_source_units=sum(state_ is SourceUnitRecoveryState.UNAVAILABLE for state_ in states),
    )


def test_pdf_candidate_supports_cross_page_semantic_hierarchy_and_original_page_rendition() -> None:
    page1 = SourceUnit("page-1", SourceUnitKind.PHYSICAL_PAGE, 0, "pdf-source", dimensions=SourceUnitDimensions(1000, 1400))
    page2 = SourceUnit("page-2", SourceUnitKind.PHYSICAL_PAGE, 1, "pdf-source", dimensions=SourceUnitDimensions(1000, 1400))
    heading = ContentNodeV2(
        node_id="h1",
        lineage_key="lineage-h1",
        node_type=ContentNodeTypeV2.HEADING,
        source_unit_ids=("page-1",),
        sibling_order=0,
        text="Architecture",
        heading_level=1,
        source_anchors=(SpatialAnchor("page-1", 0.1, 0.1, 0.9, 0.18),),
    )
    paragraph = ContentNodeV2(
        node_id="p1",
        lineage_key="lineage-p1",
        node_type=ContentNodeTypeV2.PARAGRAPH,
        source_unit_ids=("page-2",),
        parent_id="h1",
        sibling_order=0,
        text="The section continues on the next physical page.",
        source_anchors=(SpatialAnchor("page-2", 0.1, 0.1, 0.9, 0.3),),
        asset_ids=("page-render-2",),
    )
    asset = AssetReferenceV2(
        asset_id="page-render-2",
        role=AssetRoleV2.SOURCE_RENDERING,
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
        source_unit_ids=("page-2",),
        source_anchors=(SpatialAnchor("page-2", 0, 0, 1, 1),),
        rendition_ids=("page-render-2-original",),
    )
    rendition = AssetRenditionReferenceV2(
        rendition_id="page-render-2-original",
        asset_id="page-render-2",
        role=AssetRenditionRoleV2.ORIGINAL,
        artifact_ref="storage://documents/doc-1/pages/2/original.png",
        media_type="image/png",
    )
    candidate = StructuredContentCandidateV2(
        document_ref="doc-1",
        candidate_id="candidate-1",
        lineage_key="candidate-lineage",
        recovery_summary=_summary(page1, page2),
        source_units=(StructuredSourceUnit(page1), StructuredSourceUnit(page2)),
        nodes=(heading, paragraph),
        assets=(asset,),
        renditions=(rendition,),
        transformer_ref="atlas.transformer.v2",
        transformation_policy_ref="atlas.mapping.v2",
        processing_run_ref="run-1",
        structured_processing_result_ref="spr-1",
    )

    assert validate_candidate_v2(candidate) is candidate
    assert candidate.nodes[1].parent_id == "h1"
    assert candidate.nodes[1].source_unit_ids == ("page-2",)


def test_txt_candidate_has_no_fake_pages_and_can_span_bounded_text_flow_units() -> None:
    flow1 = SourceUnit(
        "txt-0",
        SourceUnitKind.TEXT_FLOW,
        0,
        "txt-source",
        source_span=TextSpanAnchor("txt-0", 0, 1000),
    )
    flow2 = SourceUnit(
        "txt-1",
        SourceUnitKind.TEXT_FLOW,
        1,
        "txt-source",
        source_span=TextSpanAnchor("txt-1", 1000, 2000),
    )
    heading = ContentNodeV2(
        "h1",
        "lh1",
        ContentNodeTypeV2.HEADING,
        ("txt-0",),
        0,
        text="第一章 绪论",
        heading_level=1,
        source_anchors=(TextSpanAnchor("txt-0", 0, 6),),
    )
    paragraph = ContentNodeV2(
        "p1",
        "lp1",
        ContentNodeTypeV2.PARAGRAPH,
        ("txt-0", "txt-1"),
        0,
        parent_id="h1",
        text="A recovered semantic paragraph can cross a processing chunk boundary.",
        source_anchors=(TextSpanAnchor("txt-0", 950, 1000), TextSpanAnchor("txt-1", 1000, 1050)),
    )
    candidate = StructuredContentCandidateV2(
        document_ref="txt-doc",
        candidate_id="txt-candidate",
        lineage_key="txt-lineage",
        recovery_summary=_summary(flow1, flow2),
        source_units=(StructuredSourceUnit(flow1), StructuredSourceUnit(flow2)),
        nodes=(heading, paragraph),
    )

    validate_candidate_v2(candidate)
    normalized = normalize_candidate_v2(candidate)
    assert normalized["source_units"][0]["kind"] == "text_flow"
    assert "dimensions" not in normalized["source_units"][0]
    assert "page_id" not in normalized["nodes"][0]


def test_candidate_normalization_is_input_order_independent() -> None:
    first = SourceUnit("flow-0", SourceUnitKind.TEXT_FLOW, 0, "txt", source_span=TextSpanAnchor("flow-0", 0, 10))
    second = SourceUnit("flow-1", SourceUnitKind.TEXT_FLOW, 1, "txt", source_span=TextSpanAnchor("flow-1", 10, 20))
    n1 = ContentNodeV2("n1", "l1", ContentNodeTypeV2.PARAGRAPH, ("flow-0",), 0, text="one")
    n2 = ContentNodeV2("n2", "l2", ContentNodeTypeV2.PARAGRAPH, ("flow-1",), 1, text="two")
    e1 = EvidenceReferenceV2("e1", source_unit_id="flow-0", source_anchors=(TextSpanAnchor("flow-0", 0, 3),))

    common = dict(
        document_ref="doc",
        candidate_id="cand",
        lineage_key="lineage",
        recovery_summary=_summary(first, second),
    )
    a = StructuredContentCandidateV2(
        **common,
        source_units=(StructuredSourceUnit(first), StructuredSourceUnit(second)),
        nodes=(n1, n2),
        evidence=(e1,),
    )
    b = StructuredContentCandidateV2(
        **common,
        source_units=(StructuredSourceUnit(second), StructuredSourceUnit(first)),
        nodes=(n2, n1),
        evidence=(e1,),
    )

    validate_candidate_v2(a)
    validate_candidate_v2(b)
    assert normalize_candidate_v2(a) == normalize_candidate_v2(b)


def test_future_format_anchors_fit_without_page_contracts() -> None:
    html = SourceUnit("html-1", SourceUnitKind.HTML_SECTION, 0, "web")
    audio = SourceUnit("audio-1", SourceUnitKind.AUDIO_SEGMENT, 1, "audio", duration_ms=5000)
    video = SourceUnit("video-1", SourceUnitKind.VIDEO_SEGMENT, 2, "video", duration_ms=5000, dimensions=SourceUnitDimensions(1920, 1080))
    html_node = ContentNodeV2(
        "html-n",
        "html-l",
        ContentNodeTypeV2.PARAGRAPH,
        ("html-1",),
        0,
        source_anchors=(DomAnchor("html-1", "html/body/main/p[1]"),),
    )
    audio_node = ContentNodeV2(
        "audio-n",
        "audio-l",
        ContentNodeTypeV2.PARAGRAPH,
        ("audio-1",),
        1,
        source_anchors=(TemporalAnchor("audio-1", 0, 5000),),
    )
    video_node = ContentNodeV2(
        "video-n",
        "video-l",
        ContentNodeTypeV2.FIGURE,
        ("video-1",),
        2,
        source_anchors=(TemporalAnchor("video-1", 0, 5000), SpatialAnchor("video-1", 0.1, 0.1, 0.9, 0.9)),
    )
    candidate = StructuredContentCandidateV2(
        document_ref="multi",
        candidate_id="multi-candidate",
        lineage_key="multi-lineage",
        recovery_summary=_summary(html, audio, video),
        source_units=(StructuredSourceUnit(html), StructuredSourceUnit(audio), StructuredSourceUnit(video)),
        nodes=(html_node, audio_node, video_node),
    )

    validate_candidate_v2(candidate)
