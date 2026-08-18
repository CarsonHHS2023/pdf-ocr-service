"""M4 Slice 4D legacy Reader v2 shadow/parity characterization tests.

These tests intentionally live at the test boundary: they characterize current
legacy Reader serialization and compare it with the Slice 4C projection without
changing production Reader or projection code.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum

from app.routers.books import _assemble_txt_from_mineru
from app.structured_content.enums import *
from app.structured_content.identity import *
from app.structured_content.model import *
from app.structured_document.assembler import assemble_structured_document
from app.structured_document.projection import project_structured_document
from app.structured_document.projection.types import ProjectionLossCode


class ReaderParityClassification(str, Enum):
    REQUIRED_SEMANTIC_PARITY = "required_semantic_parity"
    INTENTIONAL_RICHER_CANONICAL_SOURCE = "intentional_richer_canonical_source"
    INTENTIONAL_LEGACY_LOSS = "intentional_legacy_loss"
    UNSUPPORTED_LEGACY_FEATURE = "unsupported_legacy_feature"
    RECOVERY_DIFFERENCE = "recovery_difference"
    ORDERING_DIFFERENCE_REQUIRES_INVESTIGATION = "ordering_difference_requires_investigation"


@dataclass(frozen=True)
class ParityObservation:
    case: str
    classification: ReaderParityClassification
    blocking: bool
    legacy_payload: str
    projected_payload: str
    evidence: str


def nid(value: str) -> ContentNodeId: return ContentNodeId(value)
def pid(value: str) -> ContentPageId: return ContentPageId(value)
def aid(value: str) -> AssetId: return AssetId(value)
def ev(value: str) -> EvidenceReferenceId: return EvidenceReferenceId(value)


def n(value: str, page: str, order: int, node_type: ContentNodeType = ContentNodeType.PARAGRAPH, text: str = "", attributes=None, parent: str | None = None, assets=(), evidence=()):
    return ContentNode(nid(value), ContentLineageKey(f"line-{value}"), node_type, pid(page), order, NodeRecoveryState.COMPLETE, parent_id=nid(parent) if parent else None, text=text, attributes=attributes, asset_ids=tuple(assets), evidence_ids=tuple(evidence))


def candidate(nodes, pages, assets=(), evidence=(), warnings=()):
    return StructuredContentCandidate(SCHEMA_ID, SCHEMA_VERSION, DocumentRef("doc-parity"), ContentCandidateId("cand-parity"), ContentLineageKey("lineage-parity"), ContentRecoverySummary(ContentRecoveryState.DEGRADED if any(p.recovery_state is not PageRecoveryState.COMPLETE for p in pages) else ContentRecoveryState.COMPLETE, len(pages), complete_pages=sum(p.recovery_state is PageRecoveryState.COMPLETE for p in pages), degraded_pages=sum(p.recovery_state is PageRecoveryState.DEGRADED for p in pages), unavailable_pages=sum(p.recovery_state is PageRecoveryState.UNAVAILABLE for p in pages), no_usable_semantic_content_pages=sum(p.recovery_state is PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT for p in pages), warning_ids=tuple(w.warning_id for w in warnings)), tuple(nodes), tuple(evidence), tuple(assets), tuple(warnings), {}, processing_run_ref=ProcessingRunRef("run-parity"), raw_result_ref=RawResultRef("raw-parity"), structured_processing_result_ref=StructuredProcessingResultRef("spr-parity"))


def page(value: str, order: int, node_ids, recovery=PageRecoveryState.COMPLETE):
    return ContentPage(pid(value), order, order, recovery, tuple(nid(i) if isinstance(i, str) else i for i in node_ids), evidence_ids=(ev(f"ev-{value}"),))


def project(c):
    return project_structured_document(assemble_structured_document(c), candidate=c)


def classify(case: str, classification: ReaderParityClassification, legacy_payload: str, projected_payload: str, evidence: str, *, blocking: bool = False) -> ParityObservation:
    return ParityObservation(case, classification, blocking, legacy_payload, projected_payload, evidence)


def test_legacy_reader_v2_current_mineru_serialization_characterization():
    mineru_json = """[
      {"type":"title","level":9,"content":"  Deep Title  "},
      {"type":"title","level":0,"content":"Low Title"},
      {"type":"text","content":"  paragraph  "},
      {"type":"toc","content":"  toc row  "},
      {"type":"image","image_id":"img-1","caption":" caption "},
      {"type":"table","image_id":"tbl-1","continuation_image_id":"tbl-1b","caption":" table cap "},
      {"type":"text","content":"   "},
      {"type":"image","image_id":"","caption":"caption only"}
    ]"""
    assert _assemble_txt_from_mineru(mineru_json) == "###### Deep Title\n# Low Title\nparagraph\ntoc row\n$%$%$%img-1$%$%$%\ncaption\n$%$%$%tbl-1$%$%$%\n$%$%$%tbl-1b$%$%$%\ntable cap\ncaption only"
    assert _assemble_txt_from_mineru("not json") == "not json"


def test_simple_text_heading_caption_formula_and_ordering_required_semantic_parity():
    legacy = _assemble_txt_from_mineru('[{"type":"title","level":1,"content":"Book"},{"type":"text","content":"First"},{"type":"text","content":"Second"},{"type":"text","content":"Caption"},{"type":"text","content":"x=1"}]')
    nodes = [n("h", "p1", 0, ContentNodeType.HEADING, "Book", HeadingAttributes(1)), n("p1", "p1", 1, text=" First "), n("p2", "p1", 2, text="Second"), n("cap", "p1", 3, ContentNodeType.CAPTION, "Caption"), n("formula", "p1", 4, ContentNodeType.FORMULA, "x=1")]
    projected = project(candidate(nodes, [page("p1", 0, [x.node_id for x in nodes])])).payload
    obs = classify("text-heading-caption-formula-order", ReaderParityClassification.REQUIRED_SEMANTIC_PARITY, legacy, projected, "visible text, heading marker, trim, separator, and order match")
    assert obs.legacy_payload == obs.projected_payload == "# Book\nFirst\nSecond\nCaption\nx=1"
    assert not obs.blocking


def test_image_and_table_marker_parity_and_intentional_table_structure_loss():
    fig_asset = AssetReference(aid("img-1"), AssetRole.FIGURE, AssetRecoveryState.AVAILABLE)
    table_asset = AssetReference(aid("tbl-1"), AssetRole.TABLE_RENDERING, AssetRecoveryState.AVAILABLE)
    legacy = _assemble_txt_from_mineru('[{"type":"image","image_id":"img-1","caption":"Fig cap"},{"type":"table","image_id":"tbl-1","caption":"Table cap"}]')
    nodes = [n("fig", "p1", 0, ContentNodeType.FIGURE, attributes=FigureAttributes(rendered_asset_id=aid("img-1")), assets=(aid("img-1"),)), n("figcap", "p1", 1, ContentNodeType.CAPTION, "Fig cap"), n("tbl", "p1", 2, ContentNodeType.TABLE, attributes=TableAttributes(TableStructure(1, 1, (TableCell(0, 0, text="A"),)), rendered_asset_id=aid("tbl-1")), assets=(aid("tbl-1"),)), n("tblcap", "p1", 3, ContentNodeType.CAPTION, "Table cap")]
    projection = project(candidate(nodes, [page("p1", 0, [x.node_id for x in nodes])], assets=(fig_asset, table_asset)))
    assert projection.payload == legacy
    assert ProjectionLossCode.TABLE_STRUCTURE_DROPPED in [loss.code for loss in projection.losses]
    obs = classify("table-structure-loss", ReaderParityClassification.INTENTIONAL_LEGACY_LOSS, legacy, projection.payload, "visible stream matches while canonical table structure is lossily represented in Reader v2")
    assert not obs.blocking


def test_list_flattening_header_footer_footnote_unknown_and_recovery_classifications():
    nodes = [n("list", "p1", 0, ContentNodeType.LIST), n("li1", "p1", 1, ContentNodeType.LIST_ITEM, "Item 1", parent="list"), n("nested", "p1", 2, ContentNodeType.LIST, parent="list"), n("li2", "p1", 3, ContentNodeType.LIST_ITEM, "Item 2", parent="nested"), n("hdr", "p2", 0, ContentNodeType.HEADER, "Header"), n("foot", "p2", 1, ContentNodeType.FOOTNOTE, "Footnote"), n("unknown", "p2", 2, ContentNodeType.UNKNOWN, "Unknown text")]
    projection = project(candidate(nodes, [page("p1", 0, ["list"]), page("p2", 1, ["hdr", "foot", "unknown"], PageRecoveryState.DEGRADED)]))
    assert projection.payload == "Item 1\nItem 2\nUnknown text"
    codes = [loss.code for loss in projection.losses]
    assert ProjectionLossCode.STRUCTURE_DROPPED in codes
    assert ProjectionLossCode.LIST_NESTING_DROPPED in codes
    assert codes.count(ProjectionLossCode.HEADER_FOOTER_OMITTED) == 2
    assert ProjectionLossCode.RECOVERY_NOT_EXPRESSIBLE_IN_STREAM in codes
    observations = [
        classify("list-visible-order", ReaderParityClassification.REQUIRED_SEMANTIC_PARITY, "Item 1\nItem 2", projection.payload.split("\nUnknown")[0], "list item visible order is preserved"),
        classify("header-footer-footnote", ReaderParityClassification.UNSUPPORTED_LEGACY_FEATURE, "", "", "Reader v2 has no dedicated header/footer/footnote grammar"),
        classify("degraded-recovery", ReaderParityClassification.RECOVERY_DIFFERENCE, "", projection.payload, "projection records recovery losses outside the plain text payload"),
    ]
    assert all(not obs.blocking for obs in observations)


def test_evidence_metadata_is_richer_and_unsafe_assets_do_not_leak():
    bad = AssetReference(aid("https://signed.example/img?X-Amz-Signature=abc"), AssetRole.FIGURE, AssetRecoveryState.AVAILABLE)
    evidence = EvidenceReference(ev("ev-node"), EvidenceKind.STRUCTURED_PROCESSING_RESULT, source_file_ref=SourceFileRef("source-1"), raw_result_ref=RawResultRef("raw-1"), structured_processing_result_ref=StructuredProcessingResultRef("spr-1"), spr_observation_ref="obs-1")
    nodes = [n("fig", "p1", 0, ContentNodeType.FIGURE, attributes=FigureAttributes(rendered_asset_id=bad.asset_id), assets=(bad.asset_id,), evidence=(ev("ev-node"),)), n("cap", "p1", 1, ContentNodeType.CAPTION, "Safe caption", evidence=(ev("ev-node"),))]
    projection = project(candidate(nodes, [page("p1", 0, [x.node_id for x in nodes])], assets=(bad,), evidence=(evidence,)))
    assert projection.payload == "Safe caption"
    assert "https://" not in projection.payload and "X-Amz-Signature" not in projection.payload
    assert projection.entries[0].evidence_refs == (ev("ev-node"),)
    assert projection.losses[0].code is ProjectionLossCode.ASSET_UNAVAILABLE
    obs = classify("evidence-and-unsafe-asset", ReaderParityClassification.INTENTIONAL_RICHER_CANONICAL_SOURCE, "Safe caption", projection.payload, "evidence refs are metadata; unsafe transient asset ids are not copied into Reader v2 payload")
    assert not obs.blocking


def test_parity_summary_counts_are_deterministic_and_nonblocking():
    observations = [
        classify("simple-text", ReaderParityClassification.REQUIRED_SEMANTIC_PARITY, "p", "p", "exact"),
        classify("heading", ReaderParityClassification.REQUIRED_SEMANTIC_PARITY, "# H", "# H", "exact"),
        classify("image-marker", ReaderParityClassification.REQUIRED_SEMANTIC_PARITY, "$%$%$%img$%$%$%", "$%$%$%img$%$%$%", "exact"),
        classify("caption", ReaderParityClassification.REQUIRED_SEMANTIC_PARITY, "cap", "cap", "exact"),
        classify("ordering", ReaderParityClassification.REQUIRED_SEMANTIC_PARITY, "a\nb", "a\nb", "exact"),
        classify("evidence", ReaderParityClassification.INTENTIONAL_RICHER_CANONICAL_SOURCE, "", "", "metadata only"),
        classify("source-anchors", ReaderParityClassification.INTENTIONAL_RICHER_CANONICAL_SOURCE, "", "", "metadata only"),
        classify("table-structure", ReaderParityClassification.INTENTIONAL_LEGACY_LOSS, "$%$%$%tbl$%$%$%", "$%$%$%tbl$%$%$%", "structure dropped"),
        classify("header", ReaderParityClassification.UNSUPPORTED_LEGACY_FEATURE, "", "", "omitted"),
        classify("footer-footnote", ReaderParityClassification.UNSUPPORTED_LEGACY_FEATURE, "", "", "omitted"),
        classify("recovery", ReaderParityClassification.RECOVERY_DIFFERENCE, "", "", "metadata only"),
    ]
    counts = Counter(obs.classification for obs in observations)
    assert counts == {ReaderParityClassification.REQUIRED_SEMANTIC_PARITY: 5, ReaderParityClassification.INTENTIONAL_RICHER_CANONICAL_SOURCE: 2, ReaderParityClassification.INTENTIONAL_LEGACY_LOSS: 1, ReaderParityClassification.UNSUPPORTED_LEGACY_FEATURE: 2, ReaderParityClassification.RECOVERY_DIFFERENCE: 1}
    assert not any(obs.blocking for obs in observations)
    assert ReaderParityClassification.ORDERING_DIFFERENCE_REQUIRES_INVESTIGATION not in counts
