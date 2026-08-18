from __future__ import annotations

import hashlib

import fitz

from app.processing.pdf_visual_asset_enhancement import PdfVisualAssetEnhancementResult
from app.processing.pdf_visual_assets import (
    candidate_needs_pdf_assets,
    enrich_candidate_with_pdf_visual_assets,
)
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind, SpatialAnchor
from app.storage.models import PutResult, StorageReference
from app.structured_content_v2.model import (
    AssetRecoveryStateV2,
    AssetRenditionRoleV2,
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
        existing = self.objects.get(str(parsed))
        assert existing in (None, data)
        self.objects[str(parsed)] = data
        return PutResult(parsed, len(data), checksum)

    def get(self, reference):
        return self.objects[str(reference)]

    def delete(self, reference):
        self.objects.pop(str(reference), None)

    def exists(self, reference):
        return str(reference) in self.objects


class EchoEnhancer:
    def enhance(self, *, png_bytes, asset_role, alt_text=None, source_unit_id=None):
        return PdfVisualAssetEnhancementResult(
            png_bytes=png_bytes,
            provider="test-enhancer",
            model_id="test-model",
            metadata={"asset_role": asset_role.value, "source_unit_id": source_unit_id},
        )


class CountingEnhancer(EchoEnhancer):
    def __init__(self) -> None:
        self.calls = 0

    def enhance(self, **kwargs):
        self.calls += 1
        return super().enhance(**kwargs)


class FailingEnhancer:
    def enhance(self, *, png_bytes, asset_role, alt_text=None, source_unit_id=None):
        raise RuntimeError("boom")


def _pdf() -> bytes:
    document = fitz.open()
    page = document.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(20, 20, 180, 180), color=(0, 0, 0), fill=(1, 1, 1))
    page.draw_rect(fitz.Rect(50, 60, 150, 140), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
    payload = document.tobytes()
    document.close()
    return payload


def _unit() -> SourceUnit:
    return SourceUnit(
        source_unit_id="pdf-page:000001",
        kind=SourceUnitKind.PHYSICAL_PAGE,
        source_order=0,
        source_ref="source",
        dimensions=SourceUnitDimensions(200, 200),
    )


def _candidate(*, with_anchor: bool = True) -> StructuredContentCandidateV2:
    unit = _unit()
    anchors = (SpatialAnchor(unit.source_unit_id, 0.25, 0.30, 0.75, 0.70),) if with_anchor else ()
    figure = ContentNodeV2(
        node_id="figure-1",
        lineage_key="figure-lineage",
        node_type=ContentNodeTypeV2.FIGURE,
        source_unit_ids=(unit.source_unit_id,),
        sibling_order=0,
        text="Trend chart",
        source_anchors=anchors,
    )
    paragraph = ContentNodeV2(
        node_id="paragraph-1",
        lineage_key="paragraph-lineage",
        node_type=ContentNodeTypeV2.PARAGRAPH,
        source_unit_ids=(unit.source_unit_id,),
        sibling_order=1,
        text="Body text makes this a normal content page, not a cover.",
        source_anchors=(SpatialAnchor(unit.source_unit_id, 0.1, 0.05, 0.9, 0.15),),
    )
    return StructuredContentCandidateV2(
        document_ref="doc",
        candidate_id="candidate",
        lineage_key="candidate-lineage",
        recovery_summary=ContentRecoverySummaryV2(
            ContentRecoveryStateV2.COMPLETE,
            total_source_units=1,
            complete_source_units=1,
        ),
        source_units=(StructuredSourceUnit(unit),),
        nodes=(figure, paragraph),
    )


def _cover_candidate() -> StructuredContentCandidateV2:
    unit = _unit()
    title = ContentNodeV2(
        node_id="cover-title",
        lineage_key="cover-title-lineage",
        node_type=ContentNodeTypeV2.HEADING,
        source_unit_ids=(unit.source_unit_id,),
        sibling_order=0,
        text="战胜股神",
        heading_level=1,
        source_anchors=(SpatialAnchor(unit.source_unit_id, 0.15, 0.2, 0.7, 0.45),),
    )
    author = ContentNodeV2(
        node_id="cover-author",
        lineage_key="cover-author-lineage",
        node_type=ContentNodeTypeV2.HEADING,
        source_unit_ids=(unit.source_unit_id,),
        sibling_order=1,
        text="鹿希武",
        heading_level=2,
        source_anchors=(SpatialAnchor(unit.source_unit_id, 0.65, 0.45, 0.85, 0.6),),
    )
    artwork = ContentNodeV2(
        node_id="cover-artwork",
        lineage_key="cover-artwork-lineage",
        node_type=ContentNodeTypeV2.FIGURE,
        source_unit_ids=(unit.source_unit_id,),
        sibling_order=2,
        text="Cover artwork",
        source_anchors=(SpatialAnchor(unit.source_unit_id, 0.1, 0.55, 0.9, 0.95),),
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
        nodes=(title, author, artwork),
    )


def test_visual_node_gets_available_persisted_png_rendition() -> None:
    storage = MemoryStorage()
    candidate = _candidate()
    assert candidate_needs_pdf_assets(candidate)
    enriched = enrich_candidate_with_pdf_visual_assets(candidate, pdf_bytes=_pdf(), storage=storage)

    assert len(enriched.assets) == 1
    assert len(enriched.renditions) == 1
    asset = enriched.assets[0]
    rendition = enriched.renditions[0]
    assert asset.recovery_state is AssetRecoveryStateV2.AVAILABLE
    assert rendition.recovery_state is AssetRecoveryStateV2.AVAILABLE
    assert rendition.media_type == "image/png"
    assert asset.metadata["post_crop_enhancement"] == "not_applied"
    assert asset.metadata["visual_enhancement"] == {"status": "not_configured"}
    assert enriched.nodes[0].asset_ids == (asset.asset_id,)
    assert enriched.nodes[1].asset_ids == ()
    png = storage.get(rendition.artifact_ref)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    image = fitz.Pixmap(png)
    assert image.width == 200
    assert image.height == 160


def test_visual_node_with_llm_enhancement_prefers_normalized_rendition() -> None:
    storage = MemoryStorage()
    enriched = enrich_candidate_with_pdf_visual_assets(
        _candidate(),
        pdf_bytes=_pdf(),
        storage=storage,
        enhancer=EchoEnhancer(),
    )

    assert len(enriched.assets) == 1
    assert len(enriched.renditions) == 2
    asset = enriched.assets[0]
    normalized, source = enriched.renditions
    assert asset.rendition_ids == (normalized.rendition_id, source.rendition_id)
    assert normalized.role is AssetRenditionRoleV2.NORMALIZED
    assert source.role is AssetRenditionRoleV2.OCR_SOURCE
    assert asset.metadata["post_crop_enhancement"] == "applied"
    assert asset.metadata["background_cleanup"] == "applied"
    assert asset.metadata["bleed_through_cleanup"] == "applied"
    assert asset.metadata["noise_cleanup"] == "applied"
    assert asset.metadata["visual_beautification"] == "applied"
    assert asset.metadata["visual_enhancement"]["status"] == "applied"
    assert asset.metadata["visual_enhancement"]["provider"] == "test-enhancer"
    assert storage.get(normalized.artifact_ref).startswith(b"\x89PNG\r\n\x1a\n")
    assert storage.get(source.artifact_ref).startswith(b"\x89PNG\r\n\x1a\n")


def test_visual_node_enhancement_failure_falls_back_to_raw_rendition() -> None:
    storage = MemoryStorage()
    enriched = enrich_candidate_with_pdf_visual_assets(
        _candidate(),
        pdf_bytes=_pdf(),
        storage=storage,
        enhancer=FailingEnhancer(),
    )

    assert len(enriched.assets) == 1
    assert len(enriched.renditions) == 1
    asset = enriched.assets[0]
    rendition = enriched.renditions[0]
    assert rendition.role is AssetRenditionRoleV2.NORMALIZED
    assert asset.metadata["post_crop_enhancement"] == "failed"
    assert asset.metadata["visual_enhancement"] == {
        "status": "failed",
        "error_type": "RuntimeError",
    }
    assert storage.get(rendition.artifact_ref).startswith(b"\x89PNG\r\n\x1a\n")


def test_visual_node_without_spatial_anchor_is_rebuildable() -> None:
    storage = MemoryStorage()
    enriched = enrich_candidate_with_pdf_visual_assets(
        _candidate(with_anchor=False),
        pdf_bytes=_pdf(),
        storage=storage,
    )

    assert len(enriched.assets) == 1
    assert not enriched.renditions
    assert not storage.objects
    assert enriched.assets[0].recovery_state is AssetRecoveryStateV2.REBUILDABLE
    assert enriched.nodes[0].asset_ids == (enriched.assets[0].asset_id,)


def test_conservative_cover_gets_full_page_source_rendering_without_llm_edit() -> None:
    storage = MemoryStorage()
    candidate = _cover_candidate()
    enhancer = CountingEnhancer()
    assert candidate_needs_pdf_assets(candidate)

    enriched = enrich_candidate_with_pdf_visual_assets(
        candidate,
        pdf_bytes=_pdf(),
        storage=storage,
        enhancer=enhancer,
    )

    assert enhancer.calls == 0
    assert len(enriched.assets) == 1
    assert len(enriched.renditions) == 1
    asset = enriched.assets[0]
    rendition = enriched.renditions[0]
    assert asset.role is AssetRoleV2.SOURCE_RENDERING
    assert asset.source_anchors == (SpatialAnchor("pdf-page:000001", 0.0, 0.0, 1.0, 1.0),)
    assert rendition.media_type == "image/png"
    assert rendition.recovery_state is AssetRecoveryStateV2.AVAILABLE
    assert storage.get(rendition.artifact_ref).startswith(b"\x89PNG\r\n\x1a\n")

    carrier = enriched.nodes[0]
    assert carrier.asset_ids == (asset.asset_id,)
    assert enriched.nodes[2].asset_ids == ()
    for node in enriched.nodes:
        assert node.metadata["page_kind"] == "cover"
        assert node.metadata["presentation_mode"] == "source_rendering"
        assert node.metadata["source_rendering_asset_id"] == asset.asset_id
