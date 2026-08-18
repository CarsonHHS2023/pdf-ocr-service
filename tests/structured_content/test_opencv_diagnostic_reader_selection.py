from __future__ import annotations

from types import SimpleNamespace

from app.reader_v2.assets import _ordered_renditions
from app.source_units import SpatialAnchor
from app.structured_content_v2.model import (
    AssetRecoveryStateV2,
    AssetReferenceV2,
    AssetRenditionReferenceV2,
    AssetRenditionRoleV2,
    AssetRoleV2,
)


def _rendition(rendition_id: str, role: AssetRenditionRoleV2, ref: str):
    return AssetRenditionReferenceV2(
        rendition_id=rendition_id,
        asset_id="asset-1",
        role=role,
        artifact_ref=ref,
        media_type="image/png",
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
    )


def _asset(*, diagnostic_id: str, selected_for_reader: bool, rendition_ids: tuple[str, ...]):
    return AssetReferenceV2(
        asset_id="asset-1",
        role=AssetRoleV2.TABLE_RENDERING,
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
        source_unit_ids=("page-1",),
        source_anchors=(SpatialAnchor("page-1", 0.1, 0.1, 0.9, 0.9),),
        rendition_ids=rendition_ids,
        metadata={
            "diagnostic_opencv_candidate": {
                "status": "available",
                "selected_for_reader": selected_for_reader,
                "rendition_id": diagnostic_id,
            }
        },
    )


def test_accepted_opencv_candidate_remains_normal_reader_rendition() -> None:
    normalized = _rendition(
        "normalized",
        AssetRenditionRoleV2.NORMALIZED,
        "src_11111111111111111111111111111111",
    )
    source = _rendition(
        "source",
        AssetRenditionRoleV2.OCR_SOURCE,
        "src_22222222222222222222222222222222",
    )
    asset = _asset(
        diagnostic_id="normalized",
        selected_for_reader=True,
        rendition_ids=("source", "normalized"),
    )

    ordered = _ordered_renditions(SimpleNamespace(renditions=(source, normalized)), asset)

    assert [item.rendition_id for item in ordered] == ["normalized", "source"]


def test_rejected_opencv_candidate_is_never_normal_reader_fallback() -> None:
    normalized = _rendition(
        "normalized",
        AssetRenditionRoleV2.NORMALIZED,
        "src_11111111111111111111111111111111",
    )
    source = _rendition(
        "source",
        AssetRenditionRoleV2.OCR_SOURCE,
        "src_22222222222222222222222222222222",
    )
    diagnostic = _rendition(
        "opencv-candidate",
        AssetRenditionRoleV2.ORIGINAL,
        "src_33333333333333333333333333333333",
    )
    asset = _asset(
        diagnostic_id="opencv-candidate",
        selected_for_reader=False,
        rendition_ids=("source", "opencv-candidate", "normalized"),
    )

    ordered = _ordered_renditions(
        SimpleNamespace(renditions=(source, diagnostic, normalized)),
        asset,
    )

    assert [item.rendition_id for item in ordered] == ["normalized", "source"]
    assert all(item.rendition_id != "opencv-candidate" for item in ordered)
