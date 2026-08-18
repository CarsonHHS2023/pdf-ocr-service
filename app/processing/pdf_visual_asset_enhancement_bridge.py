"""Bridge Reader v2 PDF crops into the shared post-OCR visual enhancer."""
from __future__ import annotations

from typing import Any

from app.services.visual_asset_enhancement import (
    enhance_visual_asset_bytes,
    visual_asset_enhancement_enabled,
)
from app.structured_content_v2.model import ContentNodeTypeV2


def enhance_pdf_visual_crop(
    png: bytes,
    *,
    node_type: ContentNodeTypeV2,
) -> tuple[bytes, dict[str, Any]]:
    """Enhance one rendered Reader v2 figure/table crop without changing OCR.

    The helper is deliberately fail-open. Disabled, rejected, or failed
    enhancement returns the exact original PNG bytes.
    """
    block_type = "table" if node_type is ContentNodeTypeV2.TABLE else "figure"
    if not visual_asset_enhancement_enabled():
        return png, {
            "rendition_kind": "original",
            "block_type": block_type,
            "applied_steps": [],
            "fallback_used": True,
            "reason": "disabled",
        }

    enhanced, metadata = enhance_visual_asset_bytes(png, block_type=block_type)
    if metadata.get("fallback_used", False):
        return png, metadata
    return enhanced, metadata


__all__ = ["enhance_pdf_visual_crop"]
