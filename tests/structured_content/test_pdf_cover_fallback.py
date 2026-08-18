from __future__ import annotations

import fitz

from app.processing.pdf_visual_assets import enrich_candidate_with_pdf_visual_assets
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind, SpatialAnchor
from app.structured_content_v2.model import (
    ContentNodeTypeV2,
    ContentNodeV2,
    ContentRecoveryStateV2,
    ContentRecoverySummaryV2,
    StructuredContentCandidateV2,
    StructuredSourceUnit,
)


class FailingStorage:
    def put(self, data, reference=None, *, expected_size=None, expected_sha256=None):
        raise RuntimeError("simulated cover storage failure")


def _pdf() -> bytes:
    document = fitz.open()
    document.new_page(width=200, height=300)
    payload = document.tobytes()
    document.close()
    return payload


def _cover_candidate() -> StructuredContentCandidateV2:
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
        text="战胜股神",
        heading_level=1,
        source_anchors=(SpatialAnchor(unit.source_unit_id, 0.1, 0.2, 0.8, 0.4),),
    )
    author = ContentNodeV2(
        node_id="cover-author",
        lineage_key="cover-author-lineage",
        node_type=ContentNodeTypeV2.HEADING,
        source_unit_ids=(unit.source_unit_id,),
        sibling_order=1,
        text="鹿希武",
        heading_level=2,
        source_anchors=(SpatialAnchor(unit.source_unit_id, 0.5, 0.5, 0.8, 0.6),),
    )
    return StructuredContentCandidateV2(
        document_ref="doc",
        candidate_id="cover-candidate",
        lineage_key="cover-candidate-lineage",
        recovery_summary=ContentRecoverySummaryV2(
            ContentRecoveryStateV2.COMPLETE,
            total_source_units=1,
            complete_source_units=1,
        ),
        source_units=(StructuredSourceUnit(unit),),
        nodes=(title, author),
    )


def test_cover_source_rendering_failure_preserves_semantic_cover() -> None:
    candidate = _cover_candidate()

    enriched = enrich_candidate_with_pdf_visual_assets(
        candidate,
        pdf_bytes=_pdf(),
        storage=FailingStorage(),
    )

    assert enriched.assets == ()
    assert enriched.renditions == ()
    assert enriched.nodes == candidate.nodes
    for node in enriched.nodes:
        metadata = node.metadata or {}
        assert node.asset_ids == ()
        assert "page_kind" not in metadata
        assert "presentation_mode" not in metadata
        assert "source_rendering_asset_id" not in metadata
