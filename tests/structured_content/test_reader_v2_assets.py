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
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind, SpatialAnchor
from app.structured_content_v2.model import (
    AssetRecoveryStateV2,
    AssetRenditionReferenceV2,
    AssetRenditionRoleV2,
    AssetReferenceV2,
    AssetRoleV2,
    ContentNodeTypeV2,
    ContentNodeV2,
    ContentRecoveryStateV2,
    ContentRecoverySummaryV2,
    StructuredContentCandidateV2,
    StructuredSourceUnit,
)
from app.structured_content_v2.repository import StructuredContentCandidateV2Repository
from app.structured_content_v2.selection import StructuredContentV2SelectionRepository


ARTIFACT_REF = "src_" + "3" * 32


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as session:
        session.add(Document(id="doc-assets", title="assets", file_type="pdf", status="completed"))
    return engine, factory


def _candidate(*, media_type: str = "image/png", recovery_state=AssetRecoveryStateV2.AVAILABLE):
    page = SourceUnit("p1", SourceUnitKind.PHYSICAL_PAGE, 0, "pdf", dimensions=SourceUnitDimensions(612, 792))
    anchor = SpatialAnchor("p1", 0.1, 0.1, 0.8, 0.8)
    asset = AssetReferenceV2(
        asset_id="asset-1",
        role=AssetRoleV2.FIGURE,
        recovery_state=recovery_state,
        source_unit_ids=("p1",),
        source_anchors=(anchor,),
        rendition_ids=("rend-1",),
        caption="Figure caption",
        alt_text="Figure alt",
    )
    rendition = AssetRenditionReferenceV2(
        rendition_id="rend-1",
        asset_id="asset-1",
        role=AssetRenditionRoleV2.ORIGINAL,
        artifact_ref=ARTIFACT_REF,
        media_type=media_type,
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
    )
    node = ContentNodeV2(
        node_id="fig-1",
        lineage_key="lf1",
        node_type=ContentNodeTypeV2.FIGURE,
        source_unit_ids=("p1",),
        sibling_order=0,
        source_anchors=(anchor,),
        asset_ids=("asset-1",),
    )
    return StructuredContentCandidateV2(
        document_ref="doc-assets",
        candidate_id="c-assets",
        lineage_key="l-assets",
        recovery_summary=ContentRecoverySummaryV2(ContentRecoveryStateV2.COMPLETE, 1, complete_source_units=1),
        source_units=(StructuredSourceUnit(page),),
        nodes=(node,),
        assets=(asset,),
        renditions=(rendition,),
    )


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


def _client(factory):
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


def test_reader_v2_asset_metadata_is_selected_candidate_bound_and_storage_safe() -> None:
    engine, factory = _db()
    try:
        _persist_and_select(factory, _candidate())
        client = _client(factory)
        response = client.get(
            "/api/reader/v2/documents/doc-assets/assets/asset-1",
            params={"candidate_id": "c-assets"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["asset_id"] == "asset-1"
        assert body["role"] == "figure"
        assert body["delivery_state"] == "available"
        assert body["rendition_id"] == "rend-1"
        assert body["rendition_media_type"] == "image/png"
        assert body["source_anchors"][0]["kind"] == "spatial"
        assert body["caption"] == "Figure caption"
        assert "artifact_ref" not in response.text
        assert ARTIFACT_REF not in response.text
    finally:
        engine.dispose()


def test_reader_v2_asset_content_returns_safe_bytes(monkeypatch) -> None:
    engine, factory = _db()
    try:
        _persist_and_select(factory, _candidate())

        class Storage:
            def get(self, reference):
                assert str(reference) == ARTIFACT_REF
                return b"png-bytes"

        monkeypatch.setattr("app.routers.reader_v2.get_storage_provider", lambda: Storage())
        response = _client(factory).get(
            "/api/reader/v2/documents/doc-assets/assets/asset-1/content",
            params={"candidate_id": "c-assets"},
        )
        assert response.status_code == 200
        assert response.content == b"png-bytes"
        assert response.headers["content-type"].startswith("image/png")
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
    finally:
        engine.dispose()


def test_reader_v2_asset_stale_candidate_and_missing_asset_are_bounded() -> None:
    engine, factory = _db()
    try:
        _persist_and_select(factory, _candidate())
        client = _client(factory)
        stale = client.get(
            "/api/reader/v2/documents/doc-assets/assets/asset-1",
            params={"candidate_id": "old"},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "reader_selection_changed"

        missing = client.get(
            "/api/reader/v2/documents/doc-assets/assets/missing",
            params={"candidate_id": "c-assets"},
        )
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "reader_asset_not_found"
    finally:
        engine.dispose()


def test_reader_v2_asset_unsafe_media_and_unavailable_assets_never_deliver() -> None:
    for candidate in (
        _candidate(media_type="text/html"),
        _candidate(recovery_state=AssetRecoveryStateV2.REBUILDABLE),
    ):
        engine, factory = _db()
        try:
            _persist_and_select(factory, candidate)
            client = _client(factory)
            metadata = client.get(
                "/api/reader/v2/documents/doc-assets/assets/asset-1",
                params={"candidate_id": "c-assets"},
            )
            assert metadata.status_code == 200
            assert metadata.json()["delivery_state"] in {"degraded", "rebuildable"}
            content = client.get(
                "/api/reader/v2/documents/doc-assets/assets/asset-1/content",
                params={"candidate_id": "c-assets"},
            )
            assert content.status_code == 409
            assert content.json()["detail"]["code"] == "reader_asset_unavailable"
        finally:
            engine.dispose()


def test_reader_v2_asset_modules_do_not_import_legacy_reader_or_asset_tables() -> None:
    source = (
        Path("app/reader_v2/assets.py").read_text(encoding="utf-8")
        + Path("app/routers/reader_v2.py").read_text(encoding="utf-8")
    )
    forbidden = (
        "app.reader_asset_service",
        "app.reader.",
        "StructuredContentAsset",
        "BookImage",
        "PdfPage",
        "/api/v1/images/",
        "latest",
    )
    assert not any(item in source for item in forbidden)
