from app.reader_v2.assets import _select_rendition
from app.structured_content_v2.model import (
    AssetRecoveryStateV2,
    AssetReferenceV2,
    AssetRenditionReferenceV2,
    AssetRenditionRoleV2,
    AssetRoleV2,
    ContentRecoveryStateV2,
    ContentRecoverySummaryV2,
    StructuredContentCandidateV2,
)


def test_reader_prefers_enhanced_normalized_rendition_before_original_crop() -> None:
    asset = AssetReferenceV2(
        asset_id="asset-1",
        role=AssetRoleV2.FIGURE,
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
        source_unit_ids=("page-1",),
        rendition_ids=("aaa-source", "zzz-enhanced"),
    )
    enhanced = AssetRenditionReferenceV2(
        rendition_id="zzz-enhanced",
        asset_id=asset.asset_id,
        role=AssetRenditionRoleV2.NORMALIZED,
        artifact_ref="src_11111111111111111111111111111111",
        media_type="image/png",
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
    )
    source = AssetRenditionReferenceV2(
        rendition_id="aaa-source",
        asset_id=asset.asset_id,
        role=AssetRenditionRoleV2.OCR_SOURCE,
        artifact_ref="src_22222222222222222222222222222222",
        media_type="image/png",
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
    )
    candidate = StructuredContentCandidateV2(
        document_ref="doc",
        candidate_id="candidate",
        lineage_key="lineage",
        recovery_summary=ContentRecoverySummaryV2(
            ContentRecoveryStateV2.COMPLETE,
            total_source_units=0,
        ),
        source_units=(),
        nodes=(),
        assets=(asset,),
        renditions=(source, enhanced),
    )

    selected = _select_rendition(candidate, asset)

    assert selected is enhanced
    assert selected.role is AssetRenditionRoleV2.NORMALIZED
