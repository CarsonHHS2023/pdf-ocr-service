from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models import Base, Document
import app.models_v2  # noqa: F401
import app.models_v2_selection  # noqa: F401
from app.routers.reader_v2 import router
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


def _client(factory) -> TestClient:
    app = FastAPI()
    app.include_router(router)

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _pdf_candidate() -> StructuredContentCandidateV2:
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
    return StructuredContentCandidateV2(
        document_ref="doc-pdf", candidate_id="c-pdf", lineage_key="l-pdf",
        recovery_summary=ContentRecoverySummaryV2(ContentRecoveryStateV2.COMPLETE, 2, complete_source_units=2),
        source_units=(StructuredSourceUnit(page2), StructuredSourceUnit(page1)),
        nodes=(paragraph, heading),
    )


def _txt_candidate() -> StructuredContentCandidateV2:
    flow1 = SourceUnit("f1", SourceUnitKind.TEXT_FLOW, 0, "txt", source_span=TextSpanAnchor("f1", 0, 20))
    flow2 = SourceUnit("f2", SourceUnitKind.TEXT_FLOW, 1, "txt", source_span=TextSpanAnchor("f2", 20, 50))
    heading = ContentNodeV2(
        node_id="h1", lineage_key="lh1", node_type=ContentNodeTypeV2.HEADING,
        source_unit_ids=("f1",), sibling_order=0, text="Title", heading_level=1,
        source_anchors=(TextSpanAnchor("f1", 0, 5),),
    )
    first = ContentNodeV2(
        node_id="n1", lineage_key="ln1", node_type=ContentNodeTypeV2.PARAGRAPH,
        source_unit_ids=("f1", "f2"), sibling_order=0, parent_id="h1", text="Body across units",
        source_anchors=(TextSpanAnchor("f1", 6, 20), TextSpanAnchor("f2", 20, 37)),
    )
    second = ContentNodeV2(
        node_id="n2", lineage_key="ln2", node_type=ContentNodeTypeV2.PARAGRAPH,
        source_unit_ids=("f2",), sibling_order=1, parent_id="h1", text="Second",
        source_anchors=(TextSpanAnchor("f2", 38, 44),),
    )
    return StructuredContentCandidateV2(
        document_ref="doc-txt", candidate_id="c-txt", lineage_key="l-txt",
        recovery_summary=ContentRecoverySummaryV2(ContentRecoveryStateV2.COMPLETE, 2, complete_source_units=2),
        source_units=(StructuredSourceUnit(flow1), StructuredSourceUnit(flow2)),
        nodes=(heading, first, second),
    )


def test_reader_v2_open_pdf_serializes_physical_units_and_spatial_anchor() -> None:
    engine, factory = _db("doc-pdf", "pdf")
    try:
        _persist_and_select(factory, _pdf_candidate())
        response = _client(factory).get("/api/reader/v2/documents/doc-pdf")
        assert response.status_code == 200
        body = response.json()
        assert body["contract_version"] == "2"
        assert body["candidate_id"] == "c-pdf"
        assert [item["kind"] for item in body["source_units"]] == ["physical_page", "physical_page"]
        assert body["metadata"]["physical_page_count"] == 2
        assert body["navigation"][0]["location"]["source_anchor"]["kind"] == "spatial"
        assert "page_id" not in response.text
    finally:
        engine.dispose()


def test_reader_v2_open_txt_serializes_text_flow_without_presentation_pages() -> None:
    engine, factory = _db("doc-txt", "txt")
    try:
        _persist_and_select(factory, _txt_candidate())
        response = _client(factory).get("/api/reader/v2/documents/doc-txt")
        assert response.status_code == 200
        body = response.json()
        assert [item["kind"] for item in body["source_units"]] == ["text_flow", "text_flow"]
        assert body["metadata"]["physical_page_count"] == 0
        assert body["metadata"]["reflowable_source_unit_count"] == 2
        assert body["source_units"][0]["source_span"]["kind"] == "text_span"
        assert "page_id" not in response.text
    finally:
        engine.dispose()


def test_reader_v2_navigation_and_bounded_node_content_use_node_order_continuation() -> None:
    engine, factory = _db("doc-txt", "txt")
    try:
        _persist_and_select(factory, _txt_candidate())
        client = _client(factory)
        nav = client.get("/api/reader/v2/documents/doc-txt/navigation")
        assert nav.status_code == 200
        assert [(item["label"], item["heading_level"]) for item in nav.json()["navigation"]] == [("Title", 1)]

        first = client.get("/api/reader/v2/documents/doc-txt/content", params={"limit": 2})
        assert first.status_code == 200
        body = first.json()
        assert [node["node_id"] for node in body["nodes"]] == ["h1", "n1"]
        assert body["nodes"][1]["source_unit_ids"] == ["f1", "f2"]
        assert body["nodes"][1]["source_anchors"][0]["kind"] == "text_span"
        assert body["has_more"] is True
        assert body["next_node_order"] == 2

        second = client.get(
            "/api/reader/v2/documents/doc-txt/content",
            params={"start_node_order": body["next_node_order"], "limit": 2, "candidate_id": "c-txt"},
        )
        assert second.status_code == 200
        assert [node["node_id"] for node in second.json()["nodes"]] == ["n2"]
        assert second.json()["has_more"] is False
        assert second.json()["next_node_order"] is None
    finally:
        engine.dispose()


def test_reader_v2_stale_candidate_and_missing_selection_are_bounded_409s() -> None:
    engine, factory = _db("doc-txt", "txt")
    try:
        _persist_and_select(factory, _txt_candidate())
        stale = _client(factory).get(
            "/api/reader/v2/documents/doc-txt/content",
            params={"candidate_id": "old-candidate"},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "reader_selection_changed"
    finally:
        engine.dispose()

    engine, factory = _db("doc-empty", "txt")
    try:
        missing = _client(factory).get("/api/reader/v2/documents/doc-empty")
        assert missing.status_code == 409
        assert missing.json()["detail"]["code"] == "reader_not_ready"
    finally:
        engine.dispose()


def test_reader_v2_router_is_mounted_and_does_not_fallback_to_v1_or_legacy_content() -> None:
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/api/reader/v2/documents/{document_ref}" in paths
    assert "/api/reader/v2/documents/{document_ref}/navigation" in paths
    assert "/api/reader/v2/documents/{document_ref}/content" in paths

    source = Path("app/routers/reader_v2.py").read_text(encoding="utf-8") + Path("app/reader_v2/api_models.py").read_text(encoding="utf-8")
    forbidden = (
        "app.reader.",
        "build_selected_reader_document",
        "/api/v1/books/",
        "ReaderPage",
        "start_page_order",
        "latest",
    )
    assert not any(item in source for item in forbidden)
