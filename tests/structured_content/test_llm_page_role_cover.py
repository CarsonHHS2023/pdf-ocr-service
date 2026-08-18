from __future__ import annotations

import hashlib

import fitz

from app.processing.llm_structure_refinement import (
    PageRole,
    PageRoleReview,
    StructureRefinementPatch,
    apply_structure_refinement_patch,
)
from app.processing.pdf_visual_assets import (
    candidate_needs_pdf_assets,
    enrich_candidate_with_pdf_visual_assets,
)
from app.processing.structured_result_v2.model import (
    ProcessingNode,
    ProcessingNodeKind,
    StructuredProcessingResultV2,
)
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind, SpatialAnchor
from app.storage.models import PutResult, StorageReference
from app.structured_content_v2.model import AssetRoleV2, ContentNodeTypeV2
from app.structured_content_v2.transformation.transformer import (
    TransformationContextV2,
    transform_spr_v2_to_candidate,
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
    document.new_page(width=560, height=790)
    payload = document.tobytes()
    document.close()
    return payload


def _cover_spr() -> StructuredProcessingResultV2:
    unit = SourceUnit(
        "pdf-page:000001",
        SourceUnitKind.PHYSICAL_PAGE,
        0,
        "pdf-source",
        dimensions=SourceUnitDimensions(560, 790),
    )
    return StructuredProcessingResultV2(
        document_ref="doc-cover",
        processing_run_ref="run-cover",
        source_units=(unit,),
        observations=(),
        nodes=(
            ProcessingNode(
                "author",
                ProcessingNodeKind.PARAGRAPH,
                0,
                (unit.source_unit_id,),
                text="大牛",
                anchors=(SpatialAnchor(unit.source_unit_id, 0.15, 0.10, 0.30, 0.14),),
            ),
            ProcessingNode(
                "title",
                ProcessingNodeKind.HEADING,
                1,
                (unit.source_unit_id,),
                text="股票投资精英训练营",
                heading_level=1,
                anchors=(SpatialAnchor(unit.source_unit_id, 0.12, 0.25, 0.75, 0.40),),
            ),
            ProcessingNode(
                "artwork",
                ProcessingNodeKind.FIGURE,
                2,
                (unit.source_unit_id,),
                anchors=(SpatialAnchor(unit.source_unit_id, 0.08, 0.40, 0.94, 0.96),),
            ),
        ),
    )


def _candidate_from_review(page_role: PageRole, confidence: float):
    spr = _cover_spr()
    refined = apply_structure_refinement_patch(
        spr,
        StructureRefinementPatch(
            model_id="test-model",
            operations=(),
            page_reviews=(
                PageRoleReview(
                    source_unit_id="pdf-page:000001",
                    page_role=page_role,
                    confidence=confidence,
                    reason_codes=("page_image_layout",),
                ),
            ),
        ),
    )
    return transform_spr_v2_to_candidate(
        refined,
        context=TransformationContextV2(
            document_ref=refined.document_ref,
            candidate_id="candidate-cover",
            lineage_key="lineage-cover",
            structured_processing_result_ref="spr-cover",
        ),
    )


def test_high_confidence_llm_cover_overrides_paragraph_disallow_rule() -> None:
    candidate = _candidate_from_review(PageRole.COVER, 0.97)

    assert candidate.nodes[0].node_type is ContentNodeTypeV2.PARAGRAPH
    assert candidate_needs_pdf_assets(candidate) is True

    enriched = enrich_candidate_with_pdf_visual_assets(
        candidate,
        pdf_bytes=_pdf(),
        storage=MemoryStorage(),
    )

    source_assets = [asset for asset in enriched.assets if asset.role is AssetRoleV2.SOURCE_RENDERING]
    assert len(source_assets) == 1
    source_asset = source_assets[0]
    assert source_asset.metadata["generation"] == "pdf_full_page_render_v2"
    for node in enriched.nodes:
        assert node.metadata["page_kind"] == "cover"
        assert node.metadata["presentation_mode"] == "source_rendering"
        assert node.metadata["source_rendering_asset_id"] == source_asset.asset_id
        review = node.metadata["llm_page_role_review"][0]
        assert review["page_role"] == "cover"
        assert review["confidence"] == 0.97


def test_high_confidence_non_cover_review_blocks_heuristic_cover_rendering() -> None:
    candidate = _candidate_from_review(PageRole.BODY, 0.96)

    assert candidate_needs_pdf_assets(candidate) is True  # figure crop still requires the PDF
    enriched = enrich_candidate_with_pdf_visual_assets(
        candidate,
        pdf_bytes=_pdf(),
        storage=MemoryStorage(),
    )

    assert all(asset.role is not AssetRoleV2.SOURCE_RENDERING for asset in enriched.assets)
    assert all((node.metadata or {}).get("page_kind") != "cover" for node in enriched.nodes)
