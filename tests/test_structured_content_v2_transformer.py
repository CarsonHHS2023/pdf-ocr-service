from __future__ import annotations

from app.processing.structured_result_v2 import (
    ProcessingNode,
    ProcessingNodeKind,
    ProcessingObservation,
    StructuredProcessingResultV2,
)
from app.source_units import (
    SourceUnit,
    SourceUnitDimensions,
    SourceUnitKind,
    SpatialAnchor,
    TextSpanAnchor,
)
from app.structured_content_v2 import ContentNodeTypeV2, normalize_candidate_v2
from app.structured_content_v2.transformation import (
    TransformationContextV2,
    transform_spr_v2_to_candidate,
)


def _context(document_ref: str = "doc-1") -> TransformationContextV2:
    return TransformationContextV2(
        document_ref=document_ref,
        candidate_id="candidate-v2-1",
        lineage_key="lineage-v2-1",
        structured_processing_result_ref="spr-v2-artifact-1",
    )


def _pdf_spr() -> StructuredProcessingResultV2:
    page1 = SourceUnit(
        source_unit_id="page-1",
        kind=SourceUnitKind.PHYSICAL_PAGE,
        source_order=0,
        source_ref="source-file-1",
        dimensions=SourceUnitDimensions(1000, 1400),
    )
    page2 = SourceUnit(
        source_unit_id="page-2",
        kind=SourceUnitKind.PHYSICAL_PAGE,
        source_order=1,
        source_ref="source-file-1",
        dimensions=SourceUnitDimensions(1000, 1400),
    )
    h_anchor = SpatialAnchor("page-1", 0.1, 0.1, 0.8, 0.2)
    p_anchor = SpatialAnchor("page-2", 0.1, 0.1, 0.9, 0.3)
    observations = (
        ProcessingObservation("obs-h", "page-1", 0, "heading", "Chapter 1", (h_anchor,)),
        ProcessingObservation("obs-p", "page-2", 0, "text", "Body text", (p_anchor,)),
    )
    nodes = (
        ProcessingNode(
            node_id="h1",
            kind=ProcessingNodeKind.HEADING,
            order=0,
            source_unit_ids=("page-1",),
            text="Chapter 1",
            heading_level=1,
            anchors=(h_anchor,),
            observation_ids=("obs-h",),
        ),
        ProcessingNode(
            node_id="p1",
            kind=ProcessingNodeKind.PARAGRAPH,
            order=1,
            source_unit_ids=("page-2",),
            parent_id="h1",
            text="Body text",
            anchors=(p_anchor,),
            observation_ids=("obs-p",),
        ),
    )
    return StructuredProcessingResultV2(
        document_ref="doc-1",
        processing_run_ref="run-1",
        raw_result_ref="raw-1",
        source_units=(page1, page2),
        observations=observations,
        nodes=nodes,
    )


def test_pdf_cross_source_unit_hierarchy_survives_transformation() -> None:
    candidate = transform_spr_v2_to_candidate(_pdf_spr(), context=_context())

    heading = next(node for node in candidate.nodes if node.node_type is ContentNodeTypeV2.HEADING)
    paragraph = next(node for node in candidate.nodes if node.node_type is ContentNodeTypeV2.PARAGRAPH)

    assert heading.source_unit_ids == ("page-1",)
    assert paragraph.source_unit_ids == ("page-2",)
    assert paragraph.parent_id == heading.node_id
    assert paragraph.source_anchors[0].source_unit_id == "page-2"
    assert candidate.processing_run_ref == "run-1"
    assert candidate.raw_result_ref == "raw-1"
    assert candidate.structured_processing_result_ref == "spr-v2-artifact-1"


def test_txt_uses_text_flow_and_preserves_multi_unit_semantic_node() -> None:
    flow1 = SourceUnit(
        source_unit_id="flow-1",
        kind=SourceUnitKind.TEXT_FLOW,
        source_order=0,
        source_ref="source-txt",
        source_span=TextSpanAnchor("flow-1", 0, 100),
    )
    flow2 = SourceUnit(
        source_unit_id="flow-2",
        kind=SourceUnitKind.TEXT_FLOW,
        source_order=1,
        source_ref="source-txt",
        source_span=TextSpanAnchor("flow-2", 100, 200),
    )
    title_anchor = TextSpanAnchor("flow-1", 0, 8)
    paragraph_anchor_1 = TextSpanAnchor("flow-1", 9, 100)
    paragraph_anchor_2 = TextSpanAnchor("flow-2", 100, 140)
    spr = StructuredProcessingResultV2(
        document_ref="doc-txt",
        processing_run_ref="run-txt",
        source_units=(flow1, flow2),
        observations=(
            ProcessingObservation("obs-title", "flow-1", 0, "title", "My Book", (title_anchor,)),
            ProcessingObservation("obs-p1", "flow-1", 1, "text", "first", (paragraph_anchor_1,)),
            ProcessingObservation("obs-p2", "flow-2", 0, "text", "second", (paragraph_anchor_2,)),
        ),
        nodes=(
            ProcessingNode(
                "title",
                ProcessingNodeKind.TITLE,
                0,
                ("flow-1",),
                text="My Book",
                anchors=(title_anchor,),
                observation_ids=("obs-title",),
            ),
            ProcessingNode(
                "paragraph",
                ProcessingNodeKind.PARAGRAPH,
                1,
                ("flow-1", "flow-2"),
                parent_id="title",
                text="first\r\nsecond",
                anchors=(paragraph_anchor_1, paragraph_anchor_2),
                observation_ids=("obs-p1", "obs-p2"),
            ),
        ),
    )
    context = TransformationContextV2("doc-txt", "candidate-txt", "lineage-txt", "spr-txt")
    candidate = transform_spr_v2_to_candidate(spr, context=context)

    assert all(item.source_unit.kind is SourceUnitKind.TEXT_FLOW for item in candidate.source_units)
    assert all(item.source_unit.dimensions is None for item in candidate.source_units)
    title = next(node for node in candidate.nodes if node.node_type is ContentNodeTypeV2.HEADING)
    paragraph = next(node for node in candidate.nodes if node.node_type is ContentNodeTypeV2.PARAGRAPH)
    assert title.heading_level == 1
    assert paragraph.source_unit_ids == ("flow-1", "flow-2")
    assert paragraph.text == "first\nsecond"


def test_repeated_and_permuted_spr_input_is_canonically_identical() -> None:
    original = _pdf_spr()
    permuted = StructuredProcessingResultV2(
        document_ref=original.document_ref,
        processing_run_ref=original.processing_run_ref,
        raw_result_ref=original.raw_result_ref,
        source_units=tuple(reversed(original.source_units)),
        observations=tuple(reversed(original.observations)),
        nodes=tuple(reversed(original.nodes)),
        evidence=tuple(reversed(original.evidence)),
    )

    first = transform_spr_v2_to_candidate(original, context=_context())
    second = transform_spr_v2_to_candidate(original, context=_context())
    third = transform_spr_v2_to_candidate(permuted, context=_context())

    assert first == second
    assert normalize_candidate_v2(first) == normalize_candidate_v2(second)
    assert normalize_candidate_v2(first) == normalize_candidate_v2(third)


def test_unknown_processing_kind_becomes_unknown_node_with_warning() -> None:
    flow = SourceUnit(
        source_unit_id="flow",
        kind=SourceUnitKind.TEXT_FLOW,
        source_order=0,
        source_ref="source",
        source_span=TextSpanAnchor("flow", 0, 20),
    )
    anchor = TextSpanAnchor("flow", 0, 7)
    spr = StructuredProcessingResultV2(
        document_ref="doc-u",
        processing_run_ref="run-u",
        source_units=(flow,),
        observations=(),
        nodes=(ProcessingNode("u", ProcessingNodeKind.UNKNOWN, 0, ("flow",), text="mystery", anchors=(anchor,)),),
    )
    context = TransformationContextV2("doc-u", "candidate-u", "lineage-u", "spr-u")

    candidate = transform_spr_v2_to_candidate(spr, context=context)

    assert candidate.nodes[0].node_type is ContentNodeTypeV2.UNKNOWN
    assert len(candidate.warnings) == 1
    assert candidate.warnings[0].code == "UNKNOWN_ELEMENT_KIND"
    assert candidate.nodes[0].warning_ids == (candidate.warnings[0].warning_id,)
    assert candidate.recovery_summary.warning_ids == (candidate.warnings[0].warning_id,)


def test_context_document_must_match_spr_document() -> None:
    try:
        transform_spr_v2_to_candidate(_pdf_spr(), context=_context("other-doc"))
    except ValueError as exc:
        assert "document_ref" in str(exc)
    else:
        raise AssertionError("expected document mismatch to fail")
