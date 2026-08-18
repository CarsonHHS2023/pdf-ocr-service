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
from app.structured_content_v2.model import (
    AssetRoleV2,
    ContentNodeTypeV2,
    NodeRecoveryStateV2,
)
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


def _unit() -> SourceUnit:
    return SourceUnit(
        "pdf-page:000001",
        SourceUnitKind.PHYSICAL_PAGE,
        0,
        "pdf-source",
        dimensions=SourceUnitDimensions(560, 790),
    )


def _spr(nodes: tuple[ProcessingNode, ...]) -> StructuredProcessingResultV2:
    unit = _unit()
    return StructuredProcessingResultV2(
        document_ref="doc-cover-regression",
        processing_run_ref="run-cover-regression",
        source_units=(unit,),
        observations=(),
        nodes=nodes,
    )


def _candidate(spr: StructuredProcessingResultV2, page_role: PageRole, confidence: float):
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
    candidate = transform_spr_v2_to_candidate(
        refined,
        context=TransformationContextV2(
            document_ref=refined.document_ref,
            candidate_id=f"candidate-{page_role.value}",
            lineage_key=f"lineage-{page_role.value}",
            structured_processing_result_ref=f"spr-{page_role.value}",
        ),
    )
    return refined, candidate


def test_node_less_cover_review_survives_transformation_and_renders_full_page() -> None:
    refined, candidate = _candidate(_spr(()), PageRole.COVER, 0.97)

    assert len(refined.nodes) == 1
    carrier = refined.nodes[0]
    assert carrier.kind is ProcessingNodeKind.REFERENCE
    assert carrier.metadata["llm_page_role_carrier"] is True
    assert carrier.metadata["suppressed_as_artifact"] is True
    assert carrier.metadata["llm_page_role_review"][0]["page_role"] == "cover"

    assert len(candidate.nodes) == 1
    assert candidate.nodes[0].node_type is ContentNodeTypeV2.REFERENCE
    assert candidate_needs_pdf_assets(candidate) is True

    enriched = enrich_candidate_with_pdf_visual_assets(
        candidate,
        pdf_bytes=_pdf(),
        storage=MemoryStorage(),
    )

    source_assets = [asset for asset in enriched.assets if asset.role is AssetRoleV2.SOURCE_RENDERING]
    assert len(source_assets) == 1
    assert len(enriched.assets) == 1
    promoted = enriched.nodes[0]
    assert promoted.node_type is ContentNodeTypeV2.FIGURE
    assert promoted.recovery_state is NodeRecoveryStateV2.RECOVERED
    assert promoted.metadata["llm_page_role_carrier"] is True
    assert promoted.metadata["llm_page_role_carrier_promoted"] is True
    assert promoted.metadata["page_kind"] == "cover"
    assert promoted.metadata["presentation_mode"] == "source_rendering"
    assert promoted.metadata.get("suppressed_as_artifact") is None
    assert promoted.asset_ids == (source_assets[0].asset_id,)
    assert promoted.source_anchors == (
        SpatialAnchor("pdf-page:000001", 0.0, 0.0, 1.0, 1.0),
    )


def test_high_confidence_unknown_page_role_falls_back_to_cover_heuristic() -> None:
    unit = _unit()
    heading = ProcessingNode(
        "cover-heading",
        ProcessingNodeKind.HEADING,
        0,
        (unit.source_unit_id,),
        text="股票投资精英训练营",
        heading_level=1,
        anchors=(SpatialAnchor(unit.source_unit_id, 0.12, 0.20, 0.80, 0.36),),
    )
    _, candidate = _candidate(_spr((heading,)), PageRole.UNKNOWN, 0.99)

    assert candidate_needs_pdf_assets(candidate) is True
    enriched = enrich_candidate_with_pdf_visual_assets(
        candidate,
        pdf_bytes=_pdf(),
        storage=MemoryStorage(),
    )

    source_assets = [asset for asset in enriched.assets if asset.role is AssetRoleV2.SOURCE_RENDERING]
    assert len(source_assets) == 1
    assert enriched.nodes[0].metadata["page_kind"] == "cover"


def test_explicit_high_confidence_body_still_blocks_cover_heuristic() -> None:
    unit = _unit()
    heading = ProcessingNode(
        "body-heading",
        ProcessingNodeKind.HEADING,
        0,
        (unit.source_unit_id,),
        text="第一章 趋势线",
        heading_level=1,
        anchors=(SpatialAnchor(unit.source_unit_id, 0.12, 0.20, 0.80, 0.36),),
    )
    _, candidate = _candidate(_spr((heading,)), PageRole.BODY, 0.99)

    assert candidate_needs_pdf_assets(candidate) is False
