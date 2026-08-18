from __future__ import annotations

import io

import fitz  # type: ignore[import]
import numpy as np
from PIL import Image, ImageDraw

from app.processing import pdf_native_orientation_preservation_compat as native_orientation
from app.processing import pdf_native_text_compat as native
from app.processing import pdf_page_analysis_fail_open_compat as analysis_fail_open
from app.processing import pdf_page_orientation_dimensions_compat as orientation_dimensions
from app.processing.paddle_vl.normalization import normalize_paddle_pdf_raw_result
from app.processing.pdf_page_presentation_bridge import PresentationProviderInput
from app.storage.models import StorageReference


def _chart_png(*, width: int = 500, height: int = 300) -> bytes:
    image = Image.new("RGB", (width, height), "black")
    draw = ImageDraw.Draw(image)
    draw.line((20, height - 30, width - 20, 25), fill="cyan", width=5)
    draw.rectangle((80, 40, 350, 110), outline="white", width=3)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _native_mixed_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page(width=397, height=575)
    page.insert_text((175, 60), "Upper Section  Forging Sharp Eyes", fontsize=12)
    page.insert_text(
        (79, 86),
        "The next market opening may be higher when volume confirms the move,",
        fontsize=10.5,
    )
    page.insert_text(
        (57, 103),
        "so the trader should observe whether price remains stable near the close.",
        fontsize=10.5,
    )
    page.insert_text(
        (57, 120),
        "A reliable signal must come from sustained activity rather than noise.",
        fontsize=10.5,
    )
    page.insert_text((82, 164), "Detailed Trading Review", fontsize=12)
    page.insert_text(
        (79, 190),
        "The first example stayed above its average price before the closing bell,",
        fontsize=10.5,
    )
    page.insert_text(
        (57, 207),
        "then expanded with stronger volume and a clear continuation pattern.",
        fontsize=10.5,
    )
    page.insert_text(
        (57, 224),
        "This paragraph is native PDF text and must not be OCR duplicated.",
        fontsize=10.5,
    )
    page.insert_image(fitz.Rect(57, 280, 343, 482), stream=_chart_png())
    page.insert_text(
        (82, 312),
        "TEXT INSIDE THE CHART MUST NOT BECOME BODY PROSE",
        fontsize=9,
        color=(1, 1, 1),
    )
    page.insert_text(
        (79, 497),
        "The second example appears after the chart and must remain after it,",
        fontsize=10.5,
    )
    page.insert_text(
        (57, 514),
        "preserving the original page reading order and source coordinates.",
        fontsize=10.5,
    )
    page.insert_text((318, 555), "31", fontsize=9)
    data = document.tobytes(garbage=4, deflate=True)
    document.close()
    return data


def _full_page_image_with_hidden_text_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page(width=397, height=575)
    page.insert_image(page.rect, stream=_chart_png(width=800, height=1200))
    for index in range(12):
        page.insert_text(
            (35, 50 + index * 35),
            f"Hidden OCR text line {index:02d} that should not be trusted as native content.",
            fontsize=10,
        )
    data = document.tobytes(garbage=4, deflate=True)
    document.close()
    return data


def _page(pdf_bytes: bytes) -> tuple[fitz.Document, fitz.Page]:
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    return document, document[0]


def _provider_pdf_for_single_decision(
    decision: dict[str, object],
) -> tuple[fitz.Document, list[dict[str, object]]]:
    source = fitz.open()
    source.new_page(width=397, height=575)
    try:
        provider_bytes, provider_map = (
            native_orientation._build_ordinary_source_preserving_orientation(
                source,
                [decision],
            )
        )
    finally:
        source.close()
    assert provider_bytes is not None
    return fitz.open(stream=provider_bytes, filetype="pdf"), provider_map


def test_native_mixed_page_preserves_text_figure_and_reading_order() -> None:
    document, page = _page(_native_mixed_pdf())
    try:
        raw_page, validation = native.build_native_raw_page(page, page_number=10)
    finally:
        document.close()

    assert raw_page is not None
    assert validation["accepted"] is True
    assert validation["embedded_image_count"] == 1
    assert validation["image_internal_text_line_count"] == 1
    blocks = raw_page["blocks"]
    text = "\n".join(str(block.get("text") or "") for block in blocks)
    assert "TEXT INSIDE THE CHART" not in text
    assert "The next market opening" in text
    assert "The second example appears after the chart" in text

    figure_index = next(index for index, block in enumerate(blocks) if block["type"] == "image")
    first_body_index = next(
        index
        for index, block in enumerate(blocks)
        if "The next market opening" in str(block.get("text") or "")
    )
    after_figure_index = next(
        index
        for index, block in enumerate(blocks)
        if "The second example appears after the chart" in str(block.get("text") or "")
    )
    assert first_body_index < figure_index < after_figure_index
    assert blocks[-1]["type"] == "number"
    assert blocks[-1]["text"] == "31"


def test_native_page_matches_existing_paddle_normalization_contract() -> None:
    document, page = _page(_native_mixed_pdf())
    try:
        raw_page, validation = native.build_native_raw_page(page, page_number=10)
    finally:
        document.close()
    assert raw_page is not None and validation["accepted"]

    bundle = normalize_paddle_pdf_raw_result(
        [raw_page],
        document_ref="document-1",
        source_ref="source-1",
        processing_run_ref="run-1",
        raw_result_ref="raw-1",
        provider_ref="native-pdf-text",
    )

    assert [unit.source_unit_id for unit in bundle.source_units] == ["pdf-page:000010"]
    kinds = [observation.observed_kind for observation in bundle.observations]
    assert "image" in kinds
    assert "paragraph_title" in kinds
    assert "text" in kinds
    assert "number" in kinds


def test_full_page_image_text_layer_requires_raster_fallback() -> None:
    document, page = _page(_full_page_image_with_hidden_text_pdf())
    try:
        raw_page, validation = native.build_native_raw_page(page, page_number=8)
    finally:
        document.close()

    assert raw_page is None
    assert validation["accepted"] is False
    assert validation["raster_fallback_required"] is True
    assert validation["maximum_embedded_image_coverage"] > 0.95


def test_provider_subset_omits_native_page_and_preserves_confirmed_orientation() -> None:
    source = fitz.open()
    native_source = fitz.open(stream=_native_mixed_pdf(), filetype="pdf")
    hidden_source = fitz.open(
        stream=_full_page_image_with_hidden_text_pdf(), filetype="pdf"
    )
    confirmed_orientation_image = np.zeros((397, 575, 3), dtype=np.uint8)
    confirmed_orientation_image[:, :287] = 255
    try:
        source.insert_pdf(native_source)
        source.insert_pdf(hidden_source)
        source.new_page(width=397, height=575).insert_text(
            (50, 80), "ordinary provider page", fontsize=12
        )
        decisions = [
            {
                "skip_ocr": True,
                "page_index": 0,
                "page_number": 1,
                "source_unit_id": "pdf-page:000001",
            },
            {
                "skip_ocr": False,
                "native_text_fallback_raster": True,
                "orientation_image": confirmed_orientation_image,
                "page_index": 1,
                "page_number": 2,
                "source_unit_id": "pdf-page:000002",
            },
            {
                "skip_ocr": False,
                "page_index": 2,
                "page_number": 3,
                "source_unit_id": "pdf-page:000003",
            },
        ]
        provider_bytes, provider_map = (
            native_orientation._build_ordinary_source_preserving_orientation(
                source, decisions
            )
        )
    finally:
        hidden_source.close()
        native_source.close()
        source.close()

    assert provider_bytes is not None
    provider = fitz.open(stream=provider_bytes, filetype="pdf")
    try:
        assert provider.page_count == 2
        assert provider[0].get_text("text").strip() == ""
        assert "ordinary provider page" in provider[1].get_text("text")
        images = provider[0].get_images(full=True)
        assert len(images) == 1
        assert (images[0][2], images[0][3]) == (575, 397)
        assert abs(float(provider[0].rect.width) - 575.0) < 0.01
        assert abs(float(provider[0].rect.height) - 397.0) < 0.01
        page_ratio = float(provider[0].rect.width / provider[0].rect.height)
        raster_ratio = 575.0 / 397.0
        assert abs(page_ratio - raster_ratio) < 1e-6
        assert abs(float(provider[1].rect.width) - 397.0) < 0.01
        assert abs(float(provider[1].rect.height) - 575.0) < 0.01
    finally:
        provider.close()
    assert [item["original_page_number"] for item in provider_map] == [2, 3]
    assert (
        provider_map[0]["provider_input_mode"]
        == "native_text_fallback_oriented_raster"
    )
    assert provider_map[0]["provider_page_width_points"] == 575.0
    assert provider_map[0]["provider_page_height_points"] == 397.0
    assert provider_map[1]["provider_input_mode"] == "pdf_page"


def test_half_turn_orientation_keeps_original_page_dimensions() -> None:
    provider, provider_map = _provider_pdf_for_single_decision(
        {
            "skip_ocr": False,
            "orientation_image": np.zeros((575, 397, 3), dtype=np.uint8),
            "page_index": 0,
            "page_number": 1,
            "source_unit_id": "pdf-page:000001",
        }
    )
    try:
        assert abs(float(provider[0].rect.width) - 397.0) < 0.01
        assert abs(float(provider[0].rect.height) - 575.0) < 0.01
    finally:
        provider.close()
    assert provider_map[0]["provider_input_mode"] == "orientation_corrected_raster"
    assert provider_map[0]["provider_page_width_points"] == 397.0
    assert provider_map[0]["provider_page_height_points"] == 575.0


def test_quarter_turn_ordinary_page_uses_swapped_canvas() -> None:
    provider, provider_map = _provider_pdf_for_single_decision(
        {
            "skip_ocr": False,
            "orientation_image": np.zeros((397, 575, 3), dtype=np.uint8),
            "page_index": 0,
            "page_number": 1,
            "source_unit_id": "pdf-page:000001",
        }
    )
    try:
        assert abs(float(provider[0].rect.width) - 575.0) < 0.01
        assert abs(float(provider[0].rect.height) - 397.0) < 0.01
    finally:
        provider.close()
    assert provider_map[0]["provider_input_mode"] == "orientation_corrected_raster"
    assert provider_map[0]["provider_page_width_points"] == 575.0
    assert provider_map[0]["provider_page_height_points"] == 397.0


def test_combined_builder_preserves_geometry_fail_open_state() -> None:
    orientation_dimensions._ORDINARY_FAIL_OPEN_PAGES.set({})
    provider, provider_map = _provider_pdf_for_single_decision(
        {
            "skip_ocr": False,
            "decision_reason": "pre_ocr_geometry_failed",
            "geometry": {"error_type": "RenderLimitError"},
            "page_index": 0,
            "page_number": 1,
            "source_unit_id": "pdf-page:000001",
        }
    )
    try:
        assert provider.page_count == 1
        assert orientation_dimensions._ORDINARY_FAIL_OPEN_PAGES.get() == {
            0: "RenderLimitError"
        }
    finally:
        provider.close()
        orientation_dimensions._ORDINARY_FAIL_OPEN_PAGES.set({})
    assert provider_map[0]["provider_input_mode"] == "pdf_page"


def test_combined_builder_composes_geometry_and_analysis_fail_open_state() -> None:
    orientation_dimensions._ORDINARY_FAIL_OPEN_PAGES.set({})
    analysis_fail_open._ANALYSIS_PROVIDER_PAGES.set({})
    source = fitz.open()
    source.new_page(width=397, height=575)
    source.new_page(width=397, height=575)
    try:
        provider_bytes, provider_map = (
            native_orientation._build_ordinary_source_preserving_orientation(
                source,
                [
                    {
                        "skip_ocr": False,
                        "decision_reason": "pre_ocr_geometry_failed",
                        "geometry": {"error_type": "GeometryRenderLimit"},
                        "page_index": 0,
                        "page_number": 1,
                        "source_unit_id": "pdf-page:000001",
                    },
                    {
                        "skip_ocr": False,
                        "decision_reason": "pre_ocr_analysis_failed",
                        "geometry": {"error_type": "AnalysisRenderLimit"},
                        "page_index": 1,
                        "page_number": 2,
                        "source_unit_id": "pdf-page:000002",
                    },
                ],
            )
        )
    finally:
        source.close()

    assert provider_bytes is not None
    provider = fitz.open(stream=provider_bytes, filetype="pdf")
    try:
        assert provider.page_count == 2
        assert orientation_dimensions._ORDINARY_FAIL_OPEN_PAGES.get() == {
            0: "GeometryRenderLimit",
            1: "AnalysisRenderLimit",
        }
        assert analysis_fail_open._ANALYSIS_PROVIDER_PAGES.get() == {
            1: "AnalysisRenderLimit"
        }
    finally:
        provider.close()
        orientation_dimensions._ORDINARY_FAIL_OPEN_PAGES.set({})
        analysis_fail_open._ANALYSIS_PROVIDER_PAGES.set({})

    assert [item["provider_page_index"] for item in provider_map] == [0, 1]
    assert [item["original_page_number"] for item in provider_map] == [1, 2]


def test_all_local_subset_clears_geometry_and_analysis_fail_open_state() -> None:
    orientation_dimensions._ORDINARY_FAIL_OPEN_PAGES.set({7: "stale-geometry"})
    analysis_fail_open._ANALYSIS_PROVIDER_PAGES.set({8: "stale-analysis"})
    source = fitz.open()
    source.new_page(width=397, height=575)
    try:
        provider_bytes, provider_map = (
            native_orientation._build_ordinary_source_preserving_orientation(
                source,
                [
                    {
                        "skip_ocr": True,
                        "page_index": 0,
                        "page_number": 1,
                        "source_unit_id": "pdf-page:000001",
                    }
                ],
            )
        )
    finally:
        source.close()

    assert provider_bytes is None
    assert provider_map == []
    assert orientation_dimensions._ORDINARY_FAIL_OPEN_PAGES.get() == {}
    assert analysis_fail_open._ANALYSIS_PROVIDER_PAGES.get() == {}


def test_mixed_native_provider_and_presentation_pages_restore_original_order() -> None:
    document, page = _page(_native_mixed_pdf())
    try:
        native_page, validation = native.build_native_raw_page(page, page_number=1)
    finally:
        document.close()
    assert native_page is not None and validation["accepted"]

    manifest_pages = [
        {
            "page_number": 1,
            "source_unit_id": "pdf-page:000001",
            "ocr_route": "native_pdf_text",
            "native_raw_page": native_page,
            "native_text_validation": validation,
            "page_classification": {"page_role": "body", "provider": "none"},
            "page_width_points": 397.0,
            "page_height_points": 575.0,
        },
        {
            "page_number": 2,
            "source_unit_id": "pdf-page:000002",
            "ocr_route": "modal_paddle_ocr",
            "page_width_points": 397.0,
            "page_height_points": 575.0,
        },
        {
            "page_number": 3,
            "source_unit_id": "pdf-page:000003",
            "ocr_route": "skipped_presentation_image",
            "page_kind": "chapter_divider",
            "page_classification": {
                "page_role": "chapter_divider",
                "provider": "openai",
            },
            "page_width_points": 397.0,
            "page_height_points": 575.0,
        },
    ]
    provider_input = PresentationProviderInput(
        processing_attempt_id="attempt-1",
        storage_reference=StorageReference.parse(
            "src_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        ),
        checksum_sha256="a" * 64,
        byte_size=10,
        media_type="application/pdf",
        filename="render.pdf",
        preprocessing=None,
        provider_storage_reference=StorageReference.parse(
            "src_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        ),
        provider_checksum_sha256="b" * 64,
        provider_byte_size=5,
        provider_filename="provider.pdf",
        provider_page_count=1,
        provider_page_map=(
            {
                "provider_page_index": 0,
                "original_page_index": 1,
                "original_page_number": 2,
                "source_unit_id": "pdf-page:000002",
                "provider_input_mode": "pdf_page",
            },
        ),
        presentation_manifest={
            "page_count": 3,
            "provider_page_count": 1,
            "presentation_page_count": 1,
            "native_text_page_count": 1,
            "pages": manifest_pages,
        },
    )
    provider_pages = [
        {
            "page_number": 1,
            "page_index": 0,
            "local_page_index": 0,
            "source_page_range": {"page_start": 1, "page_end": 1},
            "width": 397.0,
            "height": 575.0,
            "blocks": [
                {
                    "type": "text",
                    "text": "provider page two",
                    "bbox": [20, 20, 200, 40],
                    "order": 0,
                }
            ],
        }
    ]

    remapped = native._remap_raw_pages_with_native(
        provider_pages, provider_input
    )

    assert [page["page_number"] for page in remapped] == [1, 2, 3]
    assert any(block["type"] == "image" for block in remapped[0]["blocks"])
    assert remapped[1]["blocks"][0]["text"] == "provider page two"
    assert remapped[2]["blocks"] == []
