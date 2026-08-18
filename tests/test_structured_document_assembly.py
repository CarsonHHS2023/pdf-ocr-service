from __future__ import annotations

import copy
import inspect

import pytest

from app.structured_content.enums import AssetRecoveryState, AssetRole, ContentNodeType, ContentRecoveryState, NodeRecoveryState, PageRecoveryState, WarningSeverity
from app.structured_content.identity import AssetId, ContentCandidateId, ContentLineageKey, ContentNodeId, ContentPageId, DocumentRef, EvidenceReferenceId
from app.structured_content.model import (
    SCHEMA_ID,
    SCHEMA_VERSION,
    AssetReference,
    CaptionAttributes,
    ContentNode,
    ContentPage,
    ContentRecoverySummary,
    ContentWarning,
    FigureAttributes,
    FormulaAttributes,
    HeadingAttributes,
    ListAttributes,
    ListItemAttributes,
    StructuredContentCandidate,
    TableAttributes,
    TableCell,
    TableStructure,
)
from app.structured_document.assembler import assemble_structured_document
from app.structured_document.errors import StructuredDocumentValidationFailed
from app.structured_document.types import StructuredDocument, StructuredDocumentNodeView, StructuredDocumentPageView
from app.structured_document.validation import validate_structured_document_contract


def nid(value: str) -> ContentNodeId: return ContentNodeId(value)
def pid(value: str) -> ContentPageId: return ContentPageId(value)


def make_candidate(pages, nodes, *, assets=(), warnings=(), evidence=()) -> StructuredContentCandidate:
    return StructuredContentCandidate(
        schema_id=SCHEMA_ID,
        schema_version=SCHEMA_VERSION,
        document_ref=DocumentRef("doc-assembly"),
        candidate_id=ContentCandidateId("candidate-assembly"),
        lineage_key=ContentLineageKey("lineage-assembly"),
        recovery_summary=ContentRecoverySummary(
            state=ContentRecoveryState.DEGRADED if any(p.recovery_state is not PageRecoveryState.COMPLETE for p in pages) else ContentRecoveryState.COMPLETE,
            total_pages=len(pages),
            complete_pages=sum(p.recovery_state is PageRecoveryState.COMPLETE for p in pages),
            partial_pages=sum(p.recovery_state is PageRecoveryState.PARTIAL for p in pages),
            degraded_pages=sum(p.recovery_state is PageRecoveryState.DEGRADED for p in pages),
            unavailable_pages=sum(p.recovery_state in {PageRecoveryState.UNAVAILABLE, PageRecoveryState.UNSUPPORTED} for p in pages),
            no_usable_semantic_content_pages=sum(p.recovery_state is PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT for p in pages),
            warning_ids=tuple(w.warning_id for w in warnings),
        ),
        pages=tuple(pages),
        nodes=tuple(nodes),
        evidence=tuple(evidence),
        assets=tuple(assets),
        warnings=tuple(warnings),
        extensions={},
    )


def node(value, page, order, typ=ContentNodeType.PARAGRAPH, parent=None, attrs=None, text=None, assets=(), warnings=()):
    return ContentNode(nid(value), ContentLineageKey(f"lineage-{value}"), typ, pid(page), order, NodeRecoveryState.COMPLETE, parent_id=nid(parent) if parent else None, text=text, attributes=attrs, asset_ids=tuple(assets), warning_ids=tuple(warnings))


def assemble_ids(candidate):
    return tuple(ref.value for ref in assemble_structured_document(candidate).document_reading_order_refs)


def test_one_page_simple_document_assembles_page_and_document_order() -> None:
    c = make_candidate(
        [ContentPage(pid("p1"), 0, 0, PageRecoveryState.COMPLETE, (nid("title"), nid("p-a"), nid("p-b")))],
        [node("p-b", "p1", 2), node("title", "p1", 0, ContentNodeType.HEADING, attrs=HeadingAttributes(1)), node("p-a", "p1", 1)],
    )
    doc = assemble_structured_document(c)
    assert len(doc.pages) == 1
    assert doc.pages[0].root_node_refs == (nid("title"), nid("p-a"), nid("p-b"))
    assert doc.pages[0].reading_order_node_refs == doc.document_reading_order_refs == (nid("title"), nid("p-a"), nid("p-b"))
    assert tuple(v.traversal_index for v in doc.node_views) == (0, 1, 2)
    validate_structured_document_contract(doc)


def test_multi_page_ordering_and_page_local_segments_are_deterministic() -> None:
    pages = [ContentPage(pid("p3"), 2, 2, PageRecoveryState.COMPLETE, (nid("n3"),)), ContentPage(pid("p1"), 0, 0, PageRecoveryState.COMPLETE, (nid("n1"),)), ContentPage(pid("p2"), 1, 1, PageRecoveryState.COMPLETE, (nid("n2"),))]
    c = make_candidate(pages, [node("n3", "p3", 0), node("n2", "p2", 0), node("n1", "p1", 0)])
    doc = assemble_structured_document(c)
    assert tuple(p.source_page_id.value for p in doc.pages) == ("p1", "p2", "p3")
    assert tuple(tuple(r.value for r in p.reading_order_node_refs) for p in doc.pages) == (("n1",), ("n2",), ("n3",))
    assert assemble_ids(c) == ("n1", "n2", "n3")


def test_hierarchy_preorder_roots_children_nested_lists_and_deep_nodes() -> None:
    nodes = [
        node("root-b", "p1", 1), node("root-a", "p1", 0),
        node("list", "p1", 2, ContentNodeType.LIST, parent="root-a", attrs=ListAttributes()),
        node("item-2", "p1", 1, ContentNodeType.LIST_ITEM, parent="list", attrs=ListItemAttributes()),
        node("item-1", "p1", 0, ContentNodeType.LIST_ITEM, parent="list", attrs=ListItemAttributes()),
        node("deep", "p1", 0, parent="item-1"),
        node("leaf", "p1", 0, parent="deep"),
    ]
    c = make_candidate([ContentPage(pid("p1"), 0, 0, PageRecoveryState.COMPLETE, (nid("root-a"), nid("root-b")))], nodes)
    doc = assemble_structured_document(c)
    assert assemble_ids(c) == ("root-a", "list", "item-1", "deep", "leaf", "item-2", "root-b")
    assert doc.node_views[1].child_refs == (nid("item-1"), nid("item-2"))
    assert doc.node_views[-1].child_refs == ()


def test_representative_structural_node_types_all_appear_once() -> None:
    specs = [("title", ContentNodeType.HEADING, HeadingAttributes(1)), ("heading", ContentNodeType.HEADING, HeadingAttributes(2)), ("para", ContentNodeType.PARAGRAPH, None), ("list", ContentNodeType.LIST, ListAttributes()), ("li", ContentNodeType.LIST_ITEM, ListItemAttributes()), ("caption", ContentNodeType.CAPTION, CaptionAttributes()), ("formula", ContentNodeType.FORMULA, FormulaAttributes()), ("header", ContentNodeType.HEADER, None), ("footer", ContentNodeType.FOOTER, None), ("footnote", ContentNodeType.FOOTNOTE, None), ("unknown", ContentNodeType.UNKNOWN, None)]
    nodes = [node(value, "p1", i, typ, attrs=attrs) for i, (value, typ, attrs) in enumerate(specs)]
    c = make_candidate([ContentPage(pid("p1"), 0, 0, PageRecoveryState.COMPLETE, tuple(n.node_id for n in nodes))], nodes)
    assert assemble_ids(c) == tuple(value for value, _, _ in specs)


def test_tables_figures_assets_warnings_recovery_are_preserved_by_source_refs() -> None:
    warning = ContentWarning("warn-asset", "ASSET_MISSING", WarningSeverity.WARNING, "$.assets", "asset missing")
    asset = AssetReference(AssetId("asset-fig"), AssetRole.FIGURE, AssetRecoveryState.MISSING)
    nodes = [
        node("table", "p1", 0, ContentNodeType.TABLE, attrs=TableAttributes(TableStructure(1, 1, (TableCell(0, 0, text="cell"),)))),
        node("cell", "p1", 0, parent="table"),
        node("table-caption", "p1", 1, ContentNodeType.CAPTION, attrs=CaptionAttributes(target_node_id=nid("table"))),
        node("figure", "p1", 2, ContentNodeType.FIGURE, attrs=FigureAttributes(caption_node_id=nid("figure-caption"), rendered_asset_id=AssetId("asset-fig")), assets=(AssetId("asset-fig"),), warnings=("warn-asset",)),
        node("figure-caption", "p1", 3, ContentNodeType.CAPTION, attrs=CaptionAttributes(target_node_id=nid("figure"), target_asset_id=AssetId("asset-fig"))),
    ]
    c = make_candidate([ContentPage(pid("p1"), 0, 0, PageRecoveryState.DEGRADED, (nid("table"), nid("table-caption"), nid("figure"), nid("figure-caption")), warning_ids=("warn-asset",))], nodes, assets=(asset,), warnings=(warning,))
    doc = assemble_structured_document(c)
    assert assemble_ids(c) == ("table", "cell", "table-caption", "figure", "figure-caption")
    assert doc.pages[0].warning_refs == ("warn-asset",)
    assert doc.node_views[0].source_node_id == nid("table")
    assert c.assets[0].recovery_state is AssetRecoveryState.MISSING
    validate_structured_document_contract(doc)


def test_degraded_no_usable_and_empty_pages_remain_represented() -> None:
    c = make_candidate([
        ContentPage(pid("complete"), 0, 0, PageRecoveryState.COMPLETE, (nid("n1"),)),
        ContentPage(pid("degraded"), 1, 1, PageRecoveryState.DEGRADED, (nid("n2"),)),
        ContentPage(pid("no-usable"), 2, 2, PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT, ()),
        ContentPage(pid("empty-unavailable"), 3, 3, PageRecoveryState.UNAVAILABLE, ()),
    ], [node("n1", "complete", 0), node("n2", "degraded", 0)])
    doc = assemble_structured_document(c)
    assert tuple(p.source_page_id.value for p in doc.pages) == ("complete", "degraded", "no-usable", "empty-unavailable")
    assert doc.pages[2].reading_order_node_refs == ()
    assert doc.pages[3].reading_order_node_refs == ()


def test_validation_rejects_graph_invariants() -> None:
    page = StructuredDocumentPageView(pid("p1"), 0, 0, (nid("missing"),), (nid("a"), nid("a")))
    bad = StructuredDocument(schema_version=1, document_ref=DocumentRef("doc"), source_candidate_id=ContentCandidateId("cand"), source_candidate_schema_id=SCHEMA_ID, source_candidate_schema_version=SCHEMA_VERSION, source_candidate_lineage_key=ContentLineageKey("lineage"), assembly_policy_version=1, assembly_policy=__import__("app.structured_document.types", fromlist=["StructuredDocumentAssemblyPolicy"]).StructuredDocumentAssemblyPolicy(), pages=(page,), node_views=(StructuredDocumentNodeView(nid("a"), nid("b"), (nid("b"),), 0), StructuredDocumentNodeView(nid("b"), nid("a"), (nid("a"),), 1)), document_reading_order_refs=(nid("a"), nid("a")))
    with pytest.raises(StructuredDocumentValidationFailed):
        validate_structured_document_contract(bad)


def test_determinism_input_immutability_and_collection_order_perturbation() -> None:
    pages = [ContentPage(pid("p1"), 0, 0, PageRecoveryState.COMPLETE, (nid("root"),))]
    ordered_nodes = [node("root", "p1", 0), node("b", "p1", 1, parent="root"), node("a", "p1", 0, parent="root")]
    c1 = make_candidate(pages, ordered_nodes)
    c2 = make_candidate(tuple(reversed(pages)), tuple(reversed(ordered_nodes)))
    original = copy.deepcopy(c1)
    docs = [assemble_structured_document(c1) for _ in range(5)]
    assert all(doc == docs[0] for doc in docs)
    assert assemble_structured_document(c1) == assemble_structured_document(c2)
    assert c1 == original


def test_scale_regression_100_pages_and_10000_nodes() -> None:
    pages = []
    nodes = []
    for p in range(100):
        root = nid(f"p{p}-n0")
        pages.append(ContentPage(pid(f"p{p}"), p, p, PageRecoveryState.COMPLETE, (root,)))
        nodes.append(node(f"p{p}-n0", f"p{p}", 0))
        for i in range(1, 100):
            nodes.append(node(f"p{p}-n{i}", f"p{p}", i, parent=f"p{p}-n0"))
    c = make_candidate(tuple(pages), tuple(reversed(nodes)))
    doc = assemble_structured_document(c)
    assert len(doc.pages) == 100
    assert len(doc.document_reading_order_refs) == 10000
    assert len(set(doc.document_reading_order_refs)) == 10000
    assert doc == assemble_structured_document(c)
    validate_structured_document_contract(doc)


def test_purity_tripwire_no_forbidden_runtime_dependencies() -> None:
    import app.structured_document.assembler as assembler
    text = inspect.getsource(assembler)
    forbidden = ("sqlalchemy", "repository", "selection", "fastapi", "modal", "paddle", "mineru", "reader", "requests", "httpx", "boto3", "open(", "write_text", "write_bytes")
    assert all(token not in text for token in forbidden)
