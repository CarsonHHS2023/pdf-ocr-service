from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from app.processing.structured_result import StructuredProcessingResult
from app.reader_asset_service import build_selected_reader_asset
from app.structured_content.enums import AssetRecoveryState, AssetRenditionRole, AssetRole
from app.structured_content.identity import AssetId, AssetRenditionId
from app.structured_content.model import AssetReference, AssetRenditionReference, PageDimensions
from app.structured_content.repository import StructuredContentCandidateRepository
from app.structured_content.selection_repository import StructuredContentSelectionRepository
from app.structured_content.serialization import serialize_structured_content_candidate
from app.structured_content.transformation import CandidateIdentityInput, TransformationContext, transform_spr_to_candidate
from app.structured_content.validation import ContentValidationCode, validate_content_candidate
from tests.structured_content.candidate_factory import make_linear_candidate
from tests.structured_content.integration_factory import add_document, sqlite_session


def _candidate_with_rendition():
    base = make_linear_candidate(1, 1)
    asset_id = AssetId("asset-image")
    rendition_id = AssetRenditionId("rendition-original")
    asset = AssetReference(
        asset_id=asset_id,
        role=AssetRole.FIGURE,
        recovery_state=AssetRecoveryState.AVAILABLE,
        media_type="image/png",
        rendition_refs=(rendition_id,),
    )
    rendition = AssetRenditionReference(
        rendition_id=rendition_id,
        asset_id=asset_id,
        role=AssetRenditionRole.ORIGINAL,
        media_type="image/png",
        checksum="sha256:rendition",
        dimensions=PageDimensions(640.0, 480.0, "pixel"),
        artifact_ref="src_0123456789abcdef0123456789abcdef",
        recovery_state=AssetRecoveryState.AVAILABLE,
        rebuildable=False,
    )
    node = replace(base.nodes[0], asset_ids=(asset_id,))
    return replace(base, assets=(asset,), nodes=(node,), renditions=(rendition,))


def test_rendition_registry_is_canonical_and_deterministic():
    candidate = _candidate_with_rendition()
    assert validate_content_candidate(candidate).is_valid
    payload = serialize_structured_content_candidate(candidate).decode("utf-8")
    assert '"renditions"' in payload
    assert "src_0123456789abcdef0123456789abcdef" in payload


def test_rendition_registry_rejects_asset_mismatch():
    candidate = _candidate_with_rendition()
    other = replace(candidate.renditions[0], asset_id=AssetId("asset-other"))
    result = validate_content_candidate(replace(candidate, renditions=(other,)))
    assert result.is_valid is False
    assert result.has_code(ContentValidationCode.RENDITION_ASSET_MISMATCH) or result.has_code(ContentValidationCode.DANGLING_ASSET_REFERENCE)


def test_spr_durable_renditions_enter_canonical_registry():
    data = json.loads(Path("tests/fixtures/structured_content/transformation/tables_assets_spr.json").read_text(encoding="utf-8"))
    candidate = transform_spr_to_candidate(
        StructuredProcessingResult(data),
        context=TransformationContext(
            "doc-renditions",
            CandidateIdentityInput("candidate-renditions", "lineage-renditions"),
            source_file_ref="source-renditions",
        ),
    )
    assert len(candidate.assets) == 2
    assert len(candidate.renditions) == 2
    assert all(asset.recovery_state is AssetRecoveryState.AVAILABLE for asset in candidate.assets)
    assert all(len(asset.rendition_refs) == 1 for asset in candidate.assets)
    assert {rendition.artifact_ref for rendition in candidate.renditions} == {
        "r2://bucket/fig.png",
        "r2://bucket/table.png",
    }
    assert validate_content_candidate(candidate).is_valid


def test_rendition_metadata_round_trips_through_existing_schema():
    session, engine = sqlite_session()
    try:
        candidate = _candidate_with_rendition()
        add_document(session, str(candidate.document_ref))
        repo = StructuredContentCandidateRepository()
        persisted = repo.create_candidate(session, candidate)
        reconstructed = repo.get_candidate(session, candidate.candidate_id)
        assert persisted == candidate
        assert reconstructed == candidate
        assert reconstructed.renditions[0].artifact_ref == "src_0123456789abcdef0123456789abcdef"
        assert reconstructed.renditions[0].role is AssetRenditionRole.ORIGINAL
        assert reconstructed.renditions[0].dimensions == PageDimensions(640.0, 480.0, "pixel")
        assert serialize_structured_content_candidate(reconstructed) == serialize_structured_content_candidate(candidate)
    finally:
        session.close()
        engine.dispose()


def test_selected_reader_asset_uses_canonical_rendition_without_orm_patch():
    session, engine = sqlite_session()
    try:
        candidate = _candidate_with_rendition()
        add_document(session, str(candidate.document_ref))
        repo = StructuredContentCandidateRepository()
        repo.create_candidate(session, candidate)
        StructuredContentSelectionRepository(repo).set_selection(
            session,
            document_ref=candidate.document_ref,
            candidate_id=candidate.candidate_id,
            expected_version=0,
        )
        delivery = build_selected_reader_asset(
            session=session,
            document_ref=candidate.document_ref,
            candidate_id=str(candidate.candidate_id),
            asset_id="asset-image",
        )
        assert delivery.delivery_state == "available"
        assert delivery.storage_ref == "src_0123456789abcdef0123456789abcdef"
        assert delivery.delivery_media_type == "image/png"
    finally:
        session.close()
        engine.dispose()


def test_non_storage_canonical_artifact_remains_durable_but_reader_degrades_safely():
    session, engine = sqlite_session()
    try:
        candidate = _candidate_with_rendition()
        candidate = replace(
            candidate,
            renditions=(replace(candidate.renditions[0], artifact_ref="r2://bucket/figure.png"),),
        )
        add_document(session, str(candidate.document_ref))
        repo = StructuredContentCandidateRepository()
        repo.create_candidate(session, candidate)
        StructuredContentSelectionRepository(repo).set_selection(
            session,
            document_ref=candidate.document_ref,
            candidate_id=candidate.candidate_id,
            expected_version=0,
        )
        delivery = build_selected_reader_asset(
            session=session,
            document_ref=candidate.document_ref,
            candidate_id=str(candidate.candidate_id),
            asset_id="asset-image",
        )
        assert candidate.assets[0].recovery_state is AssetRecoveryState.AVAILABLE
        assert delivery.delivery_state == "degraded"
        assert delivery.storage_ref is None
    finally:
        session.close()
        engine.dispose()


def test_legacy_candidate_without_rendition_registry_remains_valid():
    base = make_linear_candidate(1, 1)
    asset = AssetReference(
        asset_id=AssetId("legacy-asset"),
        role=AssetRole.FIGURE,
        recovery_state=AssetRecoveryState.AVAILABLE,
        rendition_refs=(AssetRenditionId("legacy-rendition"),),
    )
    candidate = replace(base, assets=(asset,), nodes=(replace(base.nodes[0], asset_ids=(asset.asset_id,)),))
    assert candidate.renditions == ()
    assert validate_content_candidate(candidate).is_valid
