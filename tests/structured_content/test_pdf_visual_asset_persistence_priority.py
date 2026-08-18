from __future__ import annotations

import app.models_v2  # noqa: F401
import app.models_v2_selection  # noqa: F401
import app.routers.reader_v2 as reader_v2_router
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document
from app.reader_v2.assets import build_selected_reader_v2_asset
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind, SpatialAnchor
from app.storage.errors import ObjectNotFound
from app.structured_content_v2.model import (
    AssetRecoveryStateV2,
    AssetReferenceV2,
    AssetRenditionReferenceV2,
    AssetRenditionRoleV2,
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

_NORMALIZED_REF = "src_22222222222222222222222222222222"
_SOURCE_REF = "src_11111111111111111111111111111111"
_DIAGNOSTIC_REF = "src_33333333333333333333333333333333"
_DIAGNOSTIC_RENDITION_ID = "mmm-opencv-candidate"


class _MissingPreferredStorage:
    def __init__(self) -> None:
        self.references: list[str] = []

    def get(self, reference):
        normalized = str(reference)
        self.references.append(normalized)
        if normalized == _NORMALIZED_REF:
            raise ObjectNotFound(normalized)
        if normalized == _SOURCE_REF:
            return b"raw-source-png"
        if normalized == _DIAGNOSTIC_REF:
            return b"rejected-opencv-candidate-png"
        raise AssertionError(f"unexpected storage reference: {normalized}")


def _candidate() -> StructuredContentCandidateV2:
    page = SourceUnit(
        "page-1",
        SourceUnitKind.PHYSICAL_PAGE,
        0,
        "pdf",
        dimensions=SourceUnitDimensions(612, 792),
    )
    anchor = SpatialAnchor("page-1", 0.1, 0.1, 0.9, 0.9)
    asset = AssetReferenceV2(
        asset_id="asset-1",
        role=AssetRoleV2.FIGURE,
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
        source_unit_ids=("page-1",),
        source_anchors=(anchor,),
        rendition_ids=(
            "aaa-ocr-source",
            _DIAGNOSTIC_RENDITION_ID,
            "zzz-normalized",
        ),
        metadata={
            "diagnostic_opencv_candidate": {
                "status": "available",
                "selected_for_reader": False,
                "rendition_id": _DIAGNOSTIC_RENDITION_ID,
                "artifact_ref": _DIAGNOSTIC_REF,
            }
        },
    )
    source = AssetRenditionReferenceV2(
        rendition_id="aaa-ocr-source",
        asset_id=asset.asset_id,
        role=AssetRenditionRoleV2.OCR_SOURCE,
        artifact_ref=_SOURCE_REF,
        media_type="image/png",
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
    )
    diagnostic = AssetRenditionReferenceV2(
        rendition_id=_DIAGNOSTIC_RENDITION_ID,
        asset_id=asset.asset_id,
        # The current public enum has no diagnostic role. The asset metadata marks
        # this exact rendition as diagnostic, and Reader selection explicitly
        # excludes it from normal fallback.
        role=AssetRenditionRoleV2.ORIGINAL,
        artifact_ref=_DIAGNOSTIC_REF,
        media_type="image/png",
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
    )
    normalized = AssetRenditionReferenceV2(
        rendition_id="zzz-normalized",
        asset_id=asset.asset_id,
        role=AssetRenditionRoleV2.NORMALIZED,
        artifact_ref=_NORMALIZED_REF,
        media_type="image/png",
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
    )
    node = ContentNodeV2(
        node_id="figure-1",
        lineage_key="figure-lineage",
        node_type=ContentNodeTypeV2.FIGURE,
        source_unit_ids=("page-1",),
        sibling_order=0,
        source_anchors=(anchor,),
        asset_ids=(asset.asset_id,),
    )
    return StructuredContentCandidateV2(
        document_ref="doc-priority",
        candidate_id="candidate-priority",
        lineage_key="candidate-priority-lineage",
        recovery_summary=ContentRecoverySummaryV2(
            ContentRecoveryStateV2.COMPLETE,
            total_source_units=1,
            complete_source_units=1,
        ),
        source_units=(StructuredSourceUnit(page),),
        nodes=(node,),
        assets=(asset,),
        renditions=(source, diagnostic, normalized),
    )


def _persisted_candidate_database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    candidates = StructuredContentCandidateV2Repository()
    selections = StructuredContentV2SelectionRepository(candidates)
    candidate = _candidate()
    with factory.begin() as session:
        session.add(
            Document(
                id=candidate.document_ref,
                title="Priority",
                file_type="pdf",
                status="completed",
            )
        )
        candidates.create_candidate(session, candidate)
        selections.set_selection(
            session,
            document_ref=candidate.document_ref,
            candidate_id=candidate.candidate_id,
            expected_version=0,
            selection_actor_ref="test",
        )
    return engine, factory, candidates, selections, candidate


def test_reader_prefers_normalized_rendition_after_database_round_trip() -> None:
    engine, factory, candidates, selections, candidate = _persisted_candidate_database()
    try:
        with factory() as session:
            delivery = build_selected_reader_v2_asset(
                session=session,
                document_ref=candidate.document_ref,
                candidate_id=candidate.candidate_id,
                asset_id="asset-1",
                candidates=candidates,
                selections=selections,
            )

        assert delivery.delivery_state == "available"
        assert delivery.rendition_id == "zzz-normalized"
        assert delivery.rendition_role == AssetRenditionRoleV2.NORMALIZED.value
    finally:
        engine.dispose()


def test_reader_content_falls_back_without_ever_using_diagnostic_candidate(monkeypatch) -> None:
    engine, factory, _candidates, _selections, candidate = _persisted_candidate_database()
    storage = _MissingPreferredStorage()
    monkeypatch.setattr(reader_v2_router, "get_storage_provider", lambda: storage)
    try:
        with factory() as session:
            response = reader_v2_router.get_reader_v2_asset_content(
                document_ref=candidate.document_ref,
                asset_id="asset-1",
                candidate_id=candidate.candidate_id,
                db=session,
            )

        assert response.body == b"raw-source-png"
        assert response.media_type == "image/png"
        assert storage.references == [_NORMALIZED_REF, _SOURCE_REF]
        assert _DIAGNOSTIC_REF not in storage.references
    finally:
        engine.dispose()


def test_opencv_diagnostic_candidate_has_explicit_attachment_download(monkeypatch) -> None:
    engine, factory, _candidates, _selections, candidate = _persisted_candidate_database()
    storage = _MissingPreferredStorage()
    monkeypatch.setattr(reader_v2_router, "get_storage_provider", lambda: storage)
    try:
        with factory() as session:
            response = reader_v2_router.download_reader_v2_opencv_candidate(
                document_ref=candidate.document_ref,
                asset_id="asset-1",
                candidate_id=candidate.candidate_id,
                db=session,
            )

        assert response.body == b"rejected-opencv-candidate-png"
        assert response.media_type == "image/png"
        assert response.headers["content-disposition"] == 'attachment; filename="opencv-candidate.png"'
        assert storage.references == [_DIAGNOSTIC_REF]
    finally:
        engine.dispose()
