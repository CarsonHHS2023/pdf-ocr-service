from __future__ import annotations

import ast
import base64
import hashlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from PIL import Image

from app.processing.pdf_visual_asset_enhancement import (
    OpenAIPdfVisualAssetEnhancer,
    PdfVisualAssetEnhancementError,
    PdfVisualAssetEnhancementResult,
    _parse_openai_image_response,
)
from app.processing.pdf_visual_assets import (
    _persist_visual_asset_renditions,
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

_VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _png(width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _dimensions(data: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(data)) as image:
        return image.size


class _EchoEnhancer:
    def enhance(self, *, png_bytes, asset_role, alt_text=None, source_unit_id=None):
        return PdfVisualAssetEnhancementResult(
            png_bytes=png_bytes,
            provider="test-enhancer",
            model_id="test-model",
        )


class _CountingEnhancer(_EchoEnhancer):
    def __init__(self) -> None:
        self.calls = 0

    def enhance(self, **kwargs):
        self.calls += 1
        return super().enhance(**kwargs)


class _MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls = 0

    def put(self, data, reference=None, *, expected_size=None, expected_sha256=None):
        self.put_calls += 1
        parsed = reference if isinstance(reference, StorageReference) else StorageReference.parse(reference)
        checksum = hashlib.sha256(data).hexdigest()
        assert expected_size in (None, len(data))
        assert expected_sha256 in (None, checksum)
        self.objects[str(parsed)] = data
        return PutResult(parsed, len(data), checksum)

    def get(self, reference):
        return self.objects[str(reference)]


class _FailEnhancedPutStorage(_MemoryStorage):
    def put(self, data, reference=None, *, expected_size=None, expected_sha256=None):
        if self.put_calls == 1:
            self.put_calls += 1
            raise RuntimeError("enhanced storage unavailable")
        return super().put(
            data,
            reference,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )


class _FailFirstPutStorage(_MemoryStorage):
    def put(self, data, reference=None, *, expected_size=None, expected_sha256=None):
        if self.put_calls == 0:
            self.put_calls += 1
            raise RuntimeError("cover storage unavailable")
        return super().put(
            data,
            reference,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )


def _is_session_begin(item: ast.withitem) -> bool:
    expression = item.context_expr
    return (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Attribute)
        and expression.func.attr == "begin"
        and isinstance(expression.func.value, ast.Name)
        and expression.func.value.id == "session"
    )


def _pdf() -> bytes:
    document = fitz.open()
    page = document.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(20, 20, 180, 180), color=(0, 0, 0), fill=(1, 1, 1))
    page.draw_rect(fitz.Rect(50, 60, 150, 140), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
    payload = document.tobytes()
    document.close()
    return payload


def _cover_candidate() -> StructuredContentCandidateV2:
    unit = SourceUnit(
        source_unit_id="pdf-page:000001",
        kind=SourceUnitKind.PHYSICAL_PAGE,
        source_order=0,
        source_ref="source",
        dimensions=SourceUnitDimensions(200, 200),
    )
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
    artwork = ContentNodeV2(
        node_id="cover-artwork",
        lineage_key="cover-artwork-lineage",
        node_type=ContentNodeTypeV2.FIGURE,
        source_unit_ids=(unit.source_unit_id,),
        sibling_order=1,
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
        nodes=(title, artwork),
    )


def test_visual_asset_enrichment_runs_before_database_write_transaction() -> None:
    tree = ast.parse(Path("app/processing/pdf_canonicalization.py").read_text(encoding="utf-8"))
    canonicalize = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "canonicalize"
    )
    enrichment_calls = [
        node
        for node in ast.walk(canonicalize)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "enrich_candidate_with_pdf_visual_assets"
    ]
    write_transactions = [
        node
        for node in ast.walk(canonicalize)
        if isinstance(node, ast.With) and any(_is_session_begin(item) for item in node.items)
    ]

    assert len(enrichment_calls) == 1
    assert len(write_transactions) == 1
    enrichment_call = enrichment_calls[0]
    write_transaction = write_transactions[0]
    assert enrichment_call.lineno < write_transaction.lineno
    assert enrichment_call not in set(ast.walk(write_transaction))


def test_enhanced_storage_failure_preserves_raw_normalized_rendition() -> None:
    storage = _FailEnhancedPutStorage()
    node = SimpleNamespace(text="Trend chart", evidence_ids=())
    anchor = SpatialAnchor("pdf-page:000002", 0.1, 0.2, 0.9, 0.8)

    asset, renditions = _persist_visual_asset_renditions(
        asset_id="asset-1",
        role=AssetRoleV2.FIGURE,
        node=node,
        anchor=anchor,
        png=_VALID_PNG,
        storage=storage,
        source_kind="retained_source_pdf",
        enhancer=_EchoEnhancer(),
    )

    assert storage.put_calls == 2
    assert len(storage.objects) == 1
    assert len(renditions) == 1
    raw = renditions[0]
    assert raw.role is AssetRenditionRoleV2.NORMALIZED
    assert raw.recovery_state is AssetRecoveryStateV2.AVAILABLE
    assert asset.recovery_state is AssetRecoveryStateV2.AVAILABLE
    assert asset.rendition_ids == (raw.rendition_id,)
    assert asset.metadata["post_crop_enhancement"] == "failed"
    assert asset.metadata["visual_enhancement"] == {
        "status": "failed",
        "error_type": "RuntimeError",
    }


def test_noncanonical_base64_image_output_is_rejected() -> None:
    encoded = base64.b64encode(_VALID_PNG).decode("ascii") + "!"

    with pytest.raises(PdfVisualAssetEnhancementError, match="invalid base64"):
        _parse_openai_image_response({"data": [{"b64_json": encoded}]})


def test_truncated_png_image_output_is_rejected_after_signature_check() -> None:
    truncated = b"\x89PNG\r\n\x1a\nnot-a-complete-png"
    encoded = base64.b64encode(truncated).decode("ascii")

    with pytest.raises(PdfVisualAssetEnhancementError, match="invalid PNG"):
        _parse_openai_image_response({"data": [{"b64_json": encoded}]})


def test_wide_crop_uses_landscape_canvas_and_restores_original_geometry() -> None:
    source = _png(800, 200)
    captured: dict[str, object] = {}

    def post(_url, _headers, fields, png_bytes, _timeout_seconds):
        captured["fields"] = dict(fields)
        captured["png_bytes"] = png_bytes
        return {"data": [{"b64_json": base64.b64encode(png_bytes).decode("ascii")}]} 

    enhancer = OpenAIPdfVisualAssetEnhancer(
        api_key="secret",
        model_id="gpt-image-test",
        http_post=post,
        sleep=lambda _seconds: None,
    )

    result = enhancer.enhance(png_bytes=source, asset_role=AssetRoleV2.TABLE_RENDERING)

    assert captured["fields"]["size"] == "1536x1024"
    assert _dimensions(captured["png_bytes"]) == (1536, 1024)
    assert _dimensions(result.png_bytes) == (800, 200)
    assert result.metadata["source_dimensions"] == [800, 200]
    assert result.metadata["provider_canvas_dimensions"] == [1536, 1024]
    assert result.metadata["provider_content_box"] == [0, 320, 1536, 704]
    assert result.metadata["source_downsampled_before_provider"] is False


def test_canvas_selection_prefers_a_larger_canvas_that_avoids_downsampling() -> None:
    source = _png(1100, 1000)
    captured: dict[str, object] = {}

    def post(_url, _headers, fields, png_bytes, _timeout_seconds):
        captured["fields"] = dict(fields)
        captured["png_bytes"] = png_bytes
        return {"data": [{"b64_json": base64.b64encode(png_bytes).decode("ascii")}]}

    enhancer = OpenAIPdfVisualAssetEnhancer(
        api_key="secret",
        model_id="gpt-image-test",
        http_post=post,
        sleep=lambda _seconds: None,
    )

    result = enhancer.enhance(png_bytes=source, asset_role=AssetRoleV2.FIGURE)

    assert captured["fields"]["size"] == "1536x1024"
    assert _dimensions(captured["png_bytes"]) == (1536, 1024)
    assert _dimensions(result.png_bytes) == (1100, 1000)
    assert result.metadata["source_downsampled_before_provider"] is False


def test_oversized_crop_skips_provider_and_preserves_raw_normalized_rendition() -> None:
    provider_calls = 0

    def post(*_args):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("provider must not be called for a downsampled source")

    enhancer = OpenAIPdfVisualAssetEnhancer(
        api_key="secret",
        model_id="gpt-image-test",
        http_post=post,
        sleep=lambda _seconds: None,
    )
    storage = _MemoryStorage()
    node = SimpleNamespace(text="Dense 2000px table", evidence_ids=())
    anchor = SpatialAnchor("pdf-page:000002", 0.1, 0.2, 0.9, 0.8)
    source = _png(2000, 2000)

    asset, renditions = _persist_visual_asset_renditions(
        asset_id="asset-oversized",
        role=AssetRoleV2.TABLE_RENDERING,
        node=node,
        anchor=anchor,
        png=source,
        storage=storage,
        source_kind="retained_source_pdf",
        enhancer=enhancer,
    )

    assert provider_calls == 0
    assert storage.put_calls == 1
    assert len(renditions) == 1
    assert renditions[0].role is AssetRenditionRoleV2.NORMALIZED
    assert storage.get(renditions[0].artifact_ref) == source
    assert asset.rendition_ids == (renditions[0].rendition_id,)
    assert asset.metadata["post_crop_enhancement"] == "failed"
    assert asset.metadata["visual_enhancement"] == {
        "status": "failed",
        "error_type": "PdfVisualAssetEnhancementError",
    }


def test_unexpected_provider_canvas_is_rejected_before_crop_restore() -> None:
    wrong_canvas = _png(1024, 1024)
    enhancer = OpenAIPdfVisualAssetEnhancer(
        api_key="secret",
        model_id="gpt-image-test",
        http_post=lambda *_args: {
            "data": [{"b64_json": base64.b64encode(wrong_canvas).decode("ascii")}]
        },
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PdfVisualAssetEnhancementError, match="unexpected canvas dimensions"):
        enhancer.enhance(
            png_bytes=_png(800, 200),
            asset_role=AssetRoleV2.FIGURE,
        )


def test_cover_render_failure_persists_local_crop_without_calling_enhancer() -> None:
    storage = _FailFirstPutStorage()
    enhancer = _CountingEnhancer()

    enriched = enrich_candidate_with_pdf_visual_assets(
        _cover_candidate(),
        pdf_bytes=_pdf(),
        storage=storage,
        enhancer=enhancer,
    )

    assert enhancer.calls == 0
    assert storage.put_calls == 2
    assert len(enriched.assets) == 1
    assert len(enriched.renditions) == 1
    asset = enriched.assets[0]
    assert asset.role is AssetRoleV2.FIGURE
    assert asset.recovery_state is AssetRecoveryStateV2.AVAILABLE
    assert asset.metadata["visual_enhancement"] == {
        "status": "skipped",
        "reason": "cover_source_rendering_failed",
    }
    assert enriched.nodes[1].asset_ids == (asset.asset_id,)
    assert storage.get(enriched.renditions[0].artifact_ref).startswith(b"\x89PNG\r\n\x1a\n")
