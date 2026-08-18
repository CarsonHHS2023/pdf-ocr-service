from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document
import app.models_v2  # noqa: F401
import app.models_v2_selection  # noqa: F401
from app.reader_v2 import NoSelectedReaderV2Content, build_selected_reader_v2_document
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind, SpatialAnchor, TextSpanAnchor
from app.structured_content_v2.model import (
    ContentNodeTypeV2,
    ContentNodeV2,
    ContentRecoveryStateV2,
    ContentRecoverySummaryV2,
    StructuredContentCandidateV2,
    StructuredSourceUnit,
)
from app.structured_content_v2.repository import StructuredContentCandidateV2Repository
from app.structured_content_v2.selection import StructuredContentV2SelectionRepository


def _db(document_id: str, file_type: str):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as session:
        session.add(Document(id=document_id, title=document_id, file_type=file_type, status="completed"))
    return engine, factory


def _persist_and_select(factory, candidate):
    candidates = StructuredContentCandidateV2Repository()
    selections = StructuredContentV2SelectionRepository(candidates)
    with factory.begin() as session:
        candidates.create_candidate(session, candidate)
        selections.set_selection(
            session,
            document_ref=candidate.document_ref,
            candidate_id=candidate.candidate_id,
            expected_version=0,
            selection_actor_ref="test",
        )


def test_pdf_reader_v2_preserves_physical_pages_and_cross_page_semantic_parentage() -> None:
    engine, factory = _db("doc-pdf", "pdf")
    try:
        page1 = SourceUnit("p1", SourceUnitKind.PHYSICAL_PAGE, 0, "pdf", dimensions=SourceUnitDimensions(612, 792))
        page2 = SourceUnit("p2", SourceUnitKind.PHYSICAL_PAGE, 1, "pdf", dimensions=SourceUnitDimensions(612, 792))
        heading = ContentNodeV2(
            node_id="h1", lineage_key="lh1", node_type=ContentNodeTypeV2.HEADING,
            source_unit_ids=("p1",), sibling_order=0, text="Heading", heading_level=1,
            source_anchors=(SpatialAnchor("p1", 0.1, 0.1, 0.9, 0.2),),
        )
        paragraph = ContentNodeV2(
            node_id="n1", lineage_key="ln1", node_type=ContentNodeTypeV2.PARAGRAPH,
            source_unit_ids=("p2",), sibling_order=0, parent_id="h1", text="Body",
            source_anchors=(SpatialAnchor("p2", 0.1, 0.2, 0.9, 0.4),),
        )
        candidate = StructuredContentCandidateV2(
            document_ref="doc-pdf", candidate_id="c-pdf", lineage_key="l-pdf",
            recovery_summary=ContentRecoverySummaryV2(ContentRecoveryStateV2.COMPLETE, 2, complete_source_units=2),
            source_units=(StructuredSourceUnit(page2), StructuredSourceUnit(page1)),
            nodes=(paragraph, heading),
        )
        _persist_and_select(factory, candidate)

        with factory() as session:
            view = build_selected_reader_v2_document(session=session, document_ref="doc-pdf")

        assert [item.source_unit.source_unit_id for item in view.source_units] == ["p1", "p2"]
        assert view.metadata.physical_page_count == 2
        assert view.metadata.reflowable_source_unit_count == 0
        assert [node.node_id for node in view.nodes] == ["h1", "n1"]
        assert view.nodes[1].parent_ref == "h1"
        assert view.nodes[0].child_refs == ("n1",)
        assert view.nodes[1].location.source_unit_id == "p2"
        assert isinstance(view.nodes[1].location.source_anchor, SpatialAnchor)
        assert view.navigation[0].location.node_id == "h1"
    finally:
        engine.dispose()


def test_txt_reader_v2_has_text_flow_locations_without_fake_pages_and_spanning_node_once() -> None:
    engine, factory = _db("doc-txt", "txt")
    try:
        flow1 = SourceUnit("f1", SourceUnitKind.TEXT_FLOW, 0, "txt", source_span=TextSpanAnchor("f1", 0, 20))
        flow2 = SourceUnit("f2", SourceUnitKind.TEXT_FLOW, 1, "txt", source_span=TextSpanAnchor("f2", 20, 50))
        heading = ContentNodeV2(
            node_id="h1", lineage_key="lh1", node_type=ContentNodeTypeV2.HEADING,
            source_unit_ids=("f1",), sibling_order=0, text="Title", heading_level=1,
            source_anchors=(TextSpanAnchor("f1", 0, 5),),
        )
        paragraph = ContentNodeV2(
            node_id="n1", lineage_key="ln1", node_type=ContentNodeTypeV2.PARAGRAPH,
            source_unit_ids=("f1", "f2"), sibling_order=0, parent_id="h1", text="Body across units",
            source_anchors=(TextSpanAnchor("f1", 6, 20), TextSpanAnchor("f2", 20, 37)),
        )
        candidate = StructuredContentCandidateV2(
            document_ref="doc-txt", candidate_id="c-txt", lineage_key="l-txt",
            recovery_summary=ContentRecoverySummaryV2(ContentRecoveryStateV2.COMPLETE, 2, complete_source_units=2),
            source_units=(StructuredSourceUnit(flow1), StructuredSourceUnit(flow2)),
            nodes=(heading, paragraph),
        )
        _persist_and_select(factory, candidate)

        with factory() as session:
            view = build_selected_reader_v2_document(session=session, document_ref="doc-txt")

        assert view.metadata.physical_page_count == 0
        assert view.metadata.reflowable_source_unit_count == 2
        assert [unit.source_unit.kind for unit in view.source_units] == [SourceUnitKind.TEXT_FLOW, SourceUnitKind.TEXT_FLOW]
        assert [node.node_id for node in view.nodes] == ["h1", "n1"]
        assert view.nodes[1].source_unit_ids == ("f1", "f2")
        assert len([node for node in view.nodes if node.node_id == "n1"]) == 1
        assert isinstance(view.nodes[1].location.source_anchor, TextSpanAnchor)
        assert not hasattr(view.nodes[1].location, "page_id")
    finally:
        engine.dispose()


def test_reader_v2_requires_explicit_v2_selection() -> None:
    engine, factory = _db("doc-empty", "txt")
    try:
        with factory() as session, pytest.raises(NoSelectedReaderV2Content):
            build_selected_reader_v2_document(session=session, document_ref="doc-empty")
    finally:
        engine.dispose()


def test_reader_v2_service_does_not_depend_on_v1_reader_or_v1_structured_content() -> None:
    source = Path("app/reader_v2/service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = (
        "app.reader",
        "app.structured_content.repository",
        "app.structured_content.selection_repository",
        "app.structured_document",
        "app.processing",
        "app.services",
        "app.routers",
        "fastapi",
        "modal",
        "httpx",
        "requests",
    )
    assert not any(name == prefix or name.startswith(prefix + ".") for name in imported for prefix in forbidden)
