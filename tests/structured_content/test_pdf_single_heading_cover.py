from __future__ import annotations

import hashlib

import fitz

from app.processing.pdf_visual_assets import (
    candidate_needs_pdf_assets,
    enrich_candidate_with_pdf_visual_assets,
)
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind, SpatialAnchor
from app.storage.models import PutResult, StorageReference
from app.structured_content_v2.model import (
    AssetRoleV2,
    ContentNodeTypeV2,
    ContentNodeV2,
    ContentRecoveryStateV2,
    ContentRecoverySummaryV2,
    StructuredContentCandidateV2,
    StructuredSourceUnit,
)


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, data, reference=None, *, expected_size=None, expected_sha256=None):
        parsed = reference if isinstance(reference, StorageReference) else StorageReference.parse(reference)
        checksum = hashlib.sha256(data).hexdigest()
        assert expected_size in (None, len(data))
        assert expected_sha256 in (None, checksum)
        self.objects[str(parsed)] = data
        return PutResult(parsed, len(data), checksum)


def _pdf() -> bytes:
    document = fitz.open()
    document.new_page(width=200, height=300)
    payload = document.tobytes()
    document.close()
    return payload


def _candidate() -> StructuredContentCandidateV2:
    unit = SourceUnit(
        source_unit_id="pdf-page:000001",
        kind=SourceUnitKind.PHYSICAL_PAGE,
        source_order=0,
        source_ref="source",
        dimensions=SourceUnitDimensions(200, 300),
    )
    title = ContentNodeV2(
        node_id="cover-title",
        lineage_key="cover-title-lineage",
        node_type=ContentNodeTypeV2.HEADING,
        source_unit_ids=(unit.source_unit_id,),
        sibling_order=0,
        text="战胜\n股神\n鹿希武",
        heading_level=1,
        source_anchors=(SpatialAnchor(unit.source_unit_id, 0.12, 0.15, 0.84, 0.46),),
    )
    return StructuredContentCandidateV2(
        document_ref="doc",
        candidate_id="single-heading-cover-candidate",
        lineage_key="single-heading-cover-lineage",
        recovery_summary=ContentRecoverySummaryV2(
            ContentRecoveryStateV2.COMPLETE,
            total_source_units=1,
            complete_source_units=1,
        ),
        source_units=(StructuredSourceUnit(unit),),
        nodes=(title,),
    )


def test_single_short_heading_cover_gets_full_page_source_rendering() -> None:
    storage = MemoryStorage()
    candidate = _candidate()

    assert candidate_needs_pdf_assets(candidate)
    enriched = enrich_candidate_with_pdf_visual_assets(candidate, pdf_bytes=_pdf(), storage=storage)

    assert len(enriched.assets) == 1
    asset = enriched.assets[0]
    assert asset.role is AssetRoleV2.SOURCE_RENDERING
    assert enriched.nodes[0].asset_ids == (asset.asset_id,)
    assert enriched.nodes[0].metadata["page_kind"] == "cover"
    assert enriched.nodes[0].metadata["presentation_mode"] == "source_rendering"
    assert enriched.nodes[0].metadata["source_rendering_asset_id"] == asset.asset_id
