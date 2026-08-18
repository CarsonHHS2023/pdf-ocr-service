"""Generate durable PDF visual renditions for semantic full-page Reader."""
from __future__ import annotations

from dataclasses import replace
import hashlib
from typing import Mapping

from app.processing.pdf_visual_asset_enhancement import (
    PdfVisualAssetEnhancer,
    openai_pdf_visual_asset_enhancer_from_env,
)
from app.source_units import SpatialAnchor
from app.storage.base import StorageProvider
from app.storage.models import StorageReference
from app.structured_content_v2.model import (
    AssetRecoveryStateV2,
    AssetReferenceV2,
    AssetRenditionReferenceV2,
    AssetRenditionRoleV2,
    AssetRoleV2,
    ContentNodeTypeV2,
    NodeRecoveryStateV2,
    StructuredContentCandidateV2,
)

_VISUAL_NODE_TYPES = frozenset({ContentNodeTypeV2.FIGURE, ContentNodeTypeV2.TABLE})
_COVER_DISALLOWED_TYPES = frozenset(
    {
        ContentNodeTypeV2.PARAGRAPH,
        ContentNodeTypeV2.LIST,
        ContentNodeTypeV2.LIST_ITEM,
        ContentNodeTypeV2.TABLE,
        ContentNodeTypeV2.FORMULA,
        ContentNodeTypeV2.CODE,
        ContentNodeTypeV2.QUOTE,
        ContentNodeTypeV2.REFERENCE,
    }
)
_FURNITURE_TYPES = frozenset(
    {ContentNodeTypeV2.HEADER, ContentNodeTypeV2.FOOTER, ContentNodeTypeV2.FOOTNOTE}
)
_AUTHORITATIVE_NON_COVER_ROLES = frozenset(
    {"back_cover", "title_page", "copyright_page", "body"}
)
_RENDER_SCALE = 2.0
_LLM_PAGE_ROLE_CONFIDENCE = 0.85


def candidate_needs_pdf_assets(candidate: StructuredContentCandidateV2) -> bool:
    """Return whether canonicalization must read a coordinate-aligned PDF."""
    return any(node.node_type in _VISUAL_NODE_TYPES for node in candidate.nodes) or _cover_source_unit_id(candidate) is not None


def enrich_candidate_with_pdf_visual_assets(
    candidate: StructuredContentCandidateV2,
    *,
    pdf_bytes: bytes,
    storage: StorageProvider,
    source_kind: str = "retained_source_pdf",
    enhancer: PdfVisualAssetEnhancer | None = None,
) -> StructuredContentCandidateV2:
    """Return a new candidate with durable page and visual PNG assets."""
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes:
        raise ValueError("pdf_bytes must be non-empty bytes")
    if not isinstance(source_kind, str) or not source_kind.strip():
        raise ValueError("source_kind must be non-empty")
    if enhancer is None:
        enhancer = openai_pdf_visual_asset_enhancer_from_env()

    import fitz  # type: ignore[import]

    source_order = {
        item.source_unit.source_unit_id: item.source_unit.source_order
        for item in candidate.source_units
    }
    assets = list(candidate.assets)
    renditions = list(candidate.renditions)
    nodes = list(candidate.nodes)

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        cover_source_unit_id = _cover_source_unit_id(candidate)
        rendered_cover_source_unit_id: str | None = None
        if cover_source_unit_id is not None:
            page_index = source_order.get(cover_source_unit_id)
            if page_index is not None and 0 <= page_index < document.page_count:
                try:
                    nodes, cover_asset, cover_rendition = _cover_source_rendering(
                        candidate,
                        nodes,
                        document[page_index],
                        cover_source_unit_id,
                        storage,
                        source_kind,
                    )
                except Exception:
                    pass
                else:
                    assets.append(cover_asset)
                    renditions.append(cover_rendition)
                    rendered_cover_source_unit_id = cover_source_unit_id

        enriched_nodes = []
        for node in nodes:
            classified_cover_node = (
                cover_source_unit_id is not None
                and cover_source_unit_id in node.source_unit_ids
            )
            if (
                node.node_type not in _VISUAL_NODE_TYPES
                or (_is_page_role_carrier(node) and not classified_cover_node)
                or (
                    rendered_cover_source_unit_id is not None
                    and rendered_cover_source_unit_id in node.source_unit_ids
                )
            ):
                enriched_nodes.append(node)
                continue

            asset_id = _asset_id(candidate.candidate_id, node.node_id)
            anchor = _spatial_anchor(node.source_anchors, source_order)
            role = (
                AssetRoleV2.FIGURE
                if node.node_type is ContentNodeTypeV2.FIGURE
                else AssetRoleV2.TABLE_RENDERING
            )
            asset = _rebuildable_asset(asset_id, role, node, anchor, source_kind)

            if anchor is not None:
                page_index = source_order.get(anchor.source_unit_id)
                if page_index is not None and 0 <= page_index < document.page_count:
                    try:
                        png = _render_crop(document[page_index], anchor)
                        asset, asset_renditions = _persist_visual_asset_renditions(
                            asset_id=asset_id,
                            role=role,
                            node=node,
                            anchor=anchor,
                            png=png,
                            storage=storage,
                            source_kind=source_kind,
                            enhancer=None if classified_cover_node else enhancer,
                            enhancement_skip_reason=(
                                "cover_source_rendering_failed"
                                if classified_cover_node
                                else None
                            ),
                        )
                        renditions.extend(asset_renditions)
                    except Exception:
                        pass

            assets.append(asset)
            enriched_nodes.append(
                replace(node, asset_ids=tuple(dict.fromkeys((*node.asset_ids, asset_id))))
            )
    finally:
        document.close()

    return replace(
        candidate,
        nodes=tuple(enriched_nodes),
        assets=tuple(assets),
        renditions=tuple(renditions),
    )


def _persist_visual_asset_renditions(
    *,
    asset_id: str,
    role: AssetRoleV2,
    node,
    anchor: SpatialAnchor,
    png: bytes,
    storage: StorageProvider,
    source_kind: str,
    enhancer: PdfVisualAssetEnhancer | None,
    enhancement_skip_reason: str | None = None,
) -> tuple[AssetReferenceV2, tuple[AssetRenditionReferenceV2, ...]]:
    if enhancement_skip_reason is not None:
        enhancement_state: dict[str, object] = {
            "status": "skipped",
            "reason": enhancement_skip_reason,
        }
    else:
        enhancement_state = {
            "status": "not_configured" if enhancer is None else "not_applied"
        }
    metadata = {
        "generation": "pdf_bbox_crop_v2",
        "media_type": "image/png",
        "source_pdf_kind": source_kind,
        "post_crop_enhancement": "not_applied",
        "background_cleanup": "not_applied",
        "bleed_through_cleanup": "not_applied",
        "noise_cleanup": "not_applied",
        "visual_beautification": "not_applied",
        "visual_enhancement": enhancement_state,
    }

    raw_checksum = hashlib.sha256(png).hexdigest()
    raw_reference = _rendition_reference("visual", raw_checksum)
    raw_put = storage.put(
        png,
        raw_reference,
        expected_size=len(png),
        expected_sha256=raw_checksum,
    )
    normalized_rendition_id = f"rendition:{asset_id}:normalized"
    normalized_rendition = AssetRenditionReferenceV2(
        rendition_id=normalized_rendition_id,
        asset_id=asset_id,
        role=AssetRenditionRoleV2.NORMALIZED,
        artifact_ref=str(raw_put.reference),
        media_type="image/png",
        checksum=raw_put.checksum_sha256,
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
        rebuildable=True,
    )
    renditions: tuple[AssetRenditionReferenceV2, ...] = (normalized_rendition,)

    if enhancer is not None:
        try:
            enhanced = enhancer.enhance(
                png_bytes=png,
                asset_role=role,
                alt_text=node.text,
                source_unit_id=anchor.source_unit_id,
            )
            enhanced_checksum = hashlib.sha256(enhanced.png_bytes).hexdigest()
            enhanced_put = storage.put(
                enhanced.png_bytes,
                _rendition_reference("visual-enhanced", enhanced_checksum),
                expected_size=len(enhanced.png_bytes),
                expected_sha256=enhanced_checksum,
            )
            source_rendition_id = f"rendition:{asset_id}:ocr_source"
            source_rendition = AssetRenditionReferenceV2(
                rendition_id=source_rendition_id,
                asset_id=asset_id,
                role=AssetRenditionRoleV2.OCR_SOURCE,
                artifact_ref=str(raw_put.reference),
                media_type="image/png",
                checksum=raw_put.checksum_sha256,
                recovery_state=AssetRecoveryStateV2.AVAILABLE,
                rebuildable=True,
            )
            normalized_rendition = AssetRenditionReferenceV2(
                rendition_id=normalized_rendition_id,
                asset_id=asset_id,
                role=AssetRenditionRoleV2.NORMALIZED,
                artifact_ref=str(enhanced_put.reference),
                media_type="image/png",
                checksum=enhanced_put.checksum_sha256,
                recovery_state=AssetRecoveryStateV2.AVAILABLE,
                rebuildable=True,
            )
        except Exception as exc:
            metadata["post_crop_enhancement"] = "failed"
            metadata["visual_enhancement"] = {
                "status": "failed",
                "error_type": type(exc).__name__,
            }
        else:
            renditions = (normalized_rendition, source_rendition)
            metadata.update(
                {
                    "post_crop_enhancement": "applied",
                    "background_cleanup": "applied",
                    "bleed_through_cleanup": "applied",
                    "noise_cleanup": "applied",
                    "visual_beautification": "applied",
                    "visual_enhancement": {
                        "status": "applied",
                        "provider": enhanced.provider,
                        "model_id": enhanced.model_id,
                        "prompt_version": enhanced.prompt_version,
                        **(enhanced.metadata or {}),
                    },
                }
            )

    asset = AssetReferenceV2(
        asset_id=asset_id,
        role=role,
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
        source_unit_ids=(anchor.source_unit_id,),
        source_anchors=(anchor,),
        rendition_ids=tuple(item.rendition_id for item in renditions),
        evidence_ids=node.evidence_ids,
        alt_text=node.text,
        metadata=metadata,
    )
    return asset, renditions


def _cover_source_unit_id(candidate: StructuredContentCandidateV2) -> str | None:
    if not candidate.source_units:
        return None
    first = min(
        candidate.source_units,
        key=lambda item: (item.source_unit.source_order, item.source_unit.source_unit_id),
    ).source_unit
    if first.source_order != 0:
        return None

    all_page_nodes = [
        node
        for node in candidate.nodes
        if first.source_unit_id in node.source_unit_ids and node.node_type not in _FURNITURE_TYPES
    ]
    page_role_review = _latest_page_role_review(all_page_nodes, first.source_unit_id)
    if page_role_review is not None:
        confidence = page_role_review.get("confidence")
        role = page_role_review.get("page_role")
        if (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and float(confidence) >= _LLM_PAGE_ROLE_CONFIDENCE
        ):
            if role == "cover":
                return first.source_unit_id
            if role in _AUTHORITATIVE_NON_COVER_ROLES:
                return None

    page_nodes = [node for node in all_page_nodes if not _is_page_role_carrier(node)]
    if not 1 <= len(page_nodes) <= 8:
        return None
    if any(node.node_type in _COVER_DISALLOWED_TYPES for node in page_nodes):
        return None
    text_length = sum(len((node.text or "").strip()) for node in page_nodes)
    if text_length > 160:
        return None
    if not any(node.node_type is ContentNodeTypeV2.HEADING for node in page_nodes):
        return None
    return first.source_unit_id


def _is_page_role_carrier(node) -> bool:
    metadata = node.metadata if isinstance(node.metadata, Mapping) else {}
    return metadata.get("llm_page_role_carrier") is True


def _latest_page_role_review(nodes, source_unit_id: str) -> Mapping[str, object] | None:
    candidates: list[Mapping[str, object]] = []
    for node in nodes:
        metadata = node.metadata if isinstance(node.metadata, Mapping) else {}
        history = metadata.get("llm_page_role_review")
        if not isinstance(history, (list, tuple)):
            continue
        for entry in history:
            if (
                isinstance(entry, Mapping)
                and entry.get("source_unit_id") == source_unit_id
                and isinstance(entry.get("page_role"), str)
            ):
                candidates.append(entry)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda entry: float(entry.get("confidence", -1))
        if isinstance(entry.get("confidence"), (int, float))
        and not isinstance(entry.get("confidence"), bool)
        else -1.0,
    )


def _cover_source_rendering(candidate, nodes, page, source_unit_id, storage, source_kind):
    anchor = SpatialAnchor(source_unit_id, 0.0, 0.0, 1.0, 1.0)
    pixmap = page.get_pixmap(matrix=_fitz_matrix(), alpha=False)
    png = pixmap.tobytes("png")
    checksum = hashlib.sha256(png).hexdigest()
    asset_id = _cover_asset_id(candidate.candidate_id, source_unit_id)
    rendition_id = f"rendition:{asset_id}:original"
    put = storage.put(
        png,
        _rendition_reference("cover", checksum),
        expected_size=len(png),
        expected_sha256=checksum,
    )
    asset = AssetReferenceV2(
        asset_id=asset_id,
        role=AssetRoleV2.SOURCE_RENDERING,
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
        source_unit_ids=(source_unit_id,),
        source_anchors=(anchor,),
        rendition_ids=(rendition_id,),
        alt_text="Provider-input cover page rendering",
        metadata={
            "generation": "pdf_full_page_render_v2",
            "page_kind": "cover",
            "source_pdf_kind": source_kind,
        },
    )
    rendition = AssetRenditionReferenceV2(
        rendition_id=rendition_id,
        asset_id=asset_id,
        role=AssetRenditionRoleV2.ORIGINAL,
        artifact_ref=str(put.reference),
        media_type="image/png",
        checksum=put.checksum_sha256,
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
        rebuildable=True,
    )

    page_indexes = [index for index, node in enumerate(nodes) if source_unit_id in node.source_unit_ids]
    if not page_indexes:
        raise ValueError("cover source unit requires a candidate node carrier")
    carrier_index = page_indexes[0]
    updated = []
    for index, node in enumerate(nodes):
        if source_unit_id not in node.source_unit_ids:
            updated.append(node)
            continue
        metadata = dict(node.metadata or {})
        page_role_carrier = metadata.get("llm_page_role_carrier") is True
        if page_role_carrier:
            for key in (
                "suppressed_as_artifact",
                "suppressed_original_kind",
                "suppression_source",
            ):
                metadata.pop(key, None)
            metadata["llm_page_role_carrier_promoted"] = True
        metadata.update(
            {
                "page_kind": "cover",
                "presentation_mode": "source_rendering",
                "source_rendering_asset_id": asset_id,
                "source_pdf_kind": source_kind,
            }
        )
        asset_ids = node.asset_ids
        if index == carrier_index:
            asset_ids = tuple(dict.fromkeys((*asset_ids, asset_id)))
        if page_role_carrier:
            updated.append(
                replace(
                    node,
                    node_type=ContentNodeTypeV2.FIGURE,
                    recovery_state=NodeRecoveryStateV2.RECOVERED,
                    source_anchors=(anchor,),
                    metadata=metadata,
                    asset_ids=asset_ids,
                )
            )
        else:
            updated.append(replace(node, metadata=metadata, asset_ids=asset_ids))
    return updated, asset, rendition


def _fitz_matrix():
    import fitz  # type: ignore[import]

    return fitz.Matrix(_RENDER_SCALE, _RENDER_SCALE)


def _spatial_anchor(anchors, source_order: dict[str, int]) -> SpatialAnchor | None:
    candidates = [anchor for anchor in anchors if isinstance(anchor, SpatialAnchor)]
    if not candidates:
        return None
    return min(candidates, key=lambda anchor: (source_order.get(anchor.source_unit_id, 2**31), anchor.top, anchor.left))


def _render_crop(page, anchor: SpatialAnchor) -> bytes:
    import fitz  # type: ignore[import]

    rect = page.rect
    clip = fitz.Rect(
        rect.x0 + anchor.left * rect.width,
        rect.y0 + anchor.top * rect.height,
        rect.x0 + anchor.right * rect.width,
        rect.y0 + anchor.bottom * rect.height,
    )
    if clip.width <= 0 or clip.height <= 0:
        raise ValueError("visual crop must have positive dimensions")
    pixmap = page.get_pixmap(matrix=fitz.Matrix(_RENDER_SCALE, _RENDER_SCALE), clip=clip, alpha=False)
    return pixmap.tobytes("png")


def _asset_id(candidate_id: str, node_id: str) -> str:
    digest = hashlib.sha256(f"{candidate_id}\x1f{node_id}".encode("utf-8")).hexdigest()[:24]
    return f"pdf-visual:{digest}"


def _cover_asset_id(candidate_id: str, source_unit_id: str) -> str:
    digest = hashlib.sha256(f"{candidate_id}\x1f{source_unit_id}\x1fcover".encode("utf-8")).hexdigest()[:24]
    return f"pdf-source-rendering:{digest}"


def _rendition_reference(kind: str, checksum: str) -> StorageReference:
    digest = hashlib.sha256(f"atlas-pdf-{kind}-v1\x1f{checksum}".encode("utf-8")).hexdigest()[:32]
    return StorageReference.parse(f"src_{digest}")


def _rebuildable_asset(asset_id, role, node, anchor, source_kind) -> AssetReferenceV2:
    source_unit_ids = (anchor.source_unit_id,) if anchor is not None else node.source_unit_ids
    source_anchors = (anchor,) if anchor is not None else ()
    return AssetReferenceV2(
        asset_id=asset_id,
        role=role,
        recovery_state=AssetRecoveryStateV2.REBUILDABLE,
        source_unit_ids=source_unit_ids,
        source_anchors=source_anchors,
        evidence_ids=node.evidence_ids,
        alt_text=node.text,
        metadata={
            "generation": "pdf_bbox_crop_v2",
            "rebuildable_from": source_kind,
            "source_pdf_kind": source_kind,
            "post_crop_enhancement": "not_applied",
        },
    )


__all__ = ["candidate_needs_pdf_assets", "enrich_candidate_with_pdf_visual_assets"]
