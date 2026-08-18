from __future__ import annotations

import inspect

from app.processing import pdf_visual_asset_enhancement_bridge as bridge
from app.processing import pdf_visual_assets
from app.structured_content_v2.model import ContentNodeTypeV2


def test_bridge_can_still_enhance_when_explicitly_called(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(bridge, "visual_asset_enhancement_enabled", lambda: True)

    def fake_enhance(image_data, *, block_type=None):
        calls.append((image_data, block_type))
        return b"enhanced", {
            "fallback_used": False,
            "output_format": "png",
            "applied_steps": ["deskew"],
        }

    monkeypatch.setattr(bridge, "enhance_visual_asset_bytes", fake_enhance)

    output, metadata = bridge.enhance_pdf_visual_crop(
        b"original",
        node_type=ContentNodeTypeV2.FIGURE,
    )

    assert output == b"enhanced"
    assert metadata["fallback_used"] is False
    assert calls == [(b"original", "figure")]


def test_bridge_preserves_exact_original_bytes_on_fallback(monkeypatch) -> None:
    original = b"exact-original-png"
    monkeypatch.setattr(bridge, "visual_asset_enhancement_enabled", lambda: True)
    monkeypatch.setattr(
        bridge,
        "enhance_visual_asset_bytes",
        lambda image_data, *, block_type=None: (
            b"reencoded-but-rejected",
            {"fallback_used": True, "reason": "quality_gate_rejected"},
        ),
    )

    output, metadata = bridge.enhance_pdf_visual_crop(
        original,
        node_type=ContentNodeTypeV2.FIGURE,
    )

    assert output is original
    assert metadata["fallback_used"] is True


def test_reader_v2_pdf_asset_pipeline_bypasses_post_crop_enhancement() -> None:
    source = inspect.getsource(pdf_visual_assets.enrich_candidate_with_pdf_visual_assets)

    assert "enhance_pdf_visual_crop(" not in source
    assert '"post_crop_enhancement": "not_applied"' in source
    assert 'source_kind: str = "retained_source_pdf"' in source
