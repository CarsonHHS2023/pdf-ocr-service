from __future__ import annotations

import fitz
import numpy as np
import pytest

from app.processing import pdf_page_analysis_fail_open_compat as analysis_fail_open
from app.processing import pdf_page_orientation_compat as orientation
from app.processing import pdf_page_orientation_dimensions_compat as dimensions
from app.processing import pdf_page_presentation_bridge as presentation
from app.processing import pdf_page_presentation_preprocess_compat as preprocess


def _page_with_rotated_text(degrees: int):
    document = fitz.open()
    page = document.new_page(width=300, height=400)
    points = {
        0: (40, 80),
        90: (80, 300),
        180: (260, 320),
        270: (220, 80),
    }
    page.insert_text(
        points[degrees],
        "ORIENTATION TEST TEXT",
        rotate=degrees,
    )
    return document, page


@pytest.mark.parametrize(
    ("text_rotation", "expected_correction"),
    [(0, 0), (90, 90), (180, 180), (270, 270)],
)
def test_native_pdf_text_detects_all_discrete_orientations(
    text_rotation,
    expected_correction,
):
    document, page = _page_with_rotated_text(text_rotation)
    try:
        result = orientation.detect_discrete_orientation(
            page,
            np.full((400, 300, 3), 255, dtype=np.uint8),
        )
    finally:
        document.close()

    assert result.correction_degrees == expected_correction
    assert result.source == "native_text_direction"
    assert result.confidence == 1.0


def test_page_rotation_metadata_is_combined_with_native_text_direction():
    document, page = _page_with_rotated_text(270)
    page.set_rotation(90)
    try:
        result = orientation.detect_discrete_orientation(
            page,
            np.full((300, 400, 3), 255, dtype=np.uint8),
        )
    finally:
        document.close()

    assert result.correction_degrees == 180
    assert result.source == "native_text_direction"


def test_discrete_rotation_is_applied_before_v4_geometry(monkeypatch):
    from app.processing import pdf_opencv_quality_pipeline as v4

    source = np.zeros((2, 3, 3), dtype=np.uint8)
    source[0, 0] = (1, 2, 3)
    observed_shapes = []

    monkeypatch.setattr(v4, "_render_page_bgr", lambda *_args, **_kwargs: source.copy())

    class Diagnostic:
        perspective_applied = False
        perspective_confidence = 0.0
        perspective_distortion = 0.0
        deskew_applied = False
        deskew_angle_degrees = 0.0
        deskew_confidence = 0.0
        residual_angle_degrees = 0.0
        residual_confidence = 0.0

    def candidate(image):
        observed_shapes.append(image.shape)
        return image.copy(), Diagnostic()

    monkeypatch.setattr(v4, "_build_geometry_candidate", candidate)
    monkeypatch.setattr(
        v4,
        "_gate_geometry_candidate",
        lambda *_args: (False, "geometry_not_required", {}),
    )

    document = fitz.open()
    page = document.new_page(width=300, height=400)
    try:
        selected, metadata, oriented_source = orientation._oriented_geometry(
            page,
            orientation.DiscreteOrientation(
                correction_degrees=90,
                confidence=0.99,
                source="test",
                native_text_chars=20,
                image_score=0.0,
            ),
        )
    finally:
        document.close()

    assert observed_shapes == [(3, 2, 3)]
    assert selected is not None
    assert oriented_source is not None
    assert selected.shape == (3, 2, 3)
    assert metadata["accepted"] is True
    assert metadata["v4_geometry_accepted"] is False
    assert metadata["applied_steps"] == ["discrete_orientation_90"]
    assert metadata["orientation"]["applied"] is True


def test_uncertain_image_orientation_fails_safe_to_zero():
    blank = np.full((600, 400, 3), 255, dtype=np.uint8)
    result = orientation._image_orientation(blank)
    assert result.correction_degrees == 0
    assert result.source == "opencv_layout_uncertain"


def test_install_places_orientation_before_preprocess_helpers():
    orientation.install_discrete_orientation_compat()
    dimensions.install_orientation_dimensions_compat()
    analysis_fail_open.install_analysis_render_fail_open_compat()
    assert preprocess._classify_source_pages is (
        analysis_fail_open._classify_source_pages_analysis_fail_open
    )
    assert orientation._classify_source_pages_oriented is (
        analysis_fail_open._classify_source_pages_analysis_fail_open
    )
    assert preprocess._build_ordinary_source is (
        analysis_fail_open._build_ordinary_source_analysis_fail_open
    )
    assert orientation._build_ordinary_source_oriented is (
        analysis_fail_open._build_ordinary_source_analysis_fail_open
    )


@pytest.mark.parametrize(
    ("raster_shape", "expected_size"),
    [
        ((300, 400, 3), (400.0, 300.0)),
        ((400, 300, 3), (300.0, 400.0)),
    ],
)
def test_raster_page_rect_preserves_or_swaps_source_dimensions(
    raster_shape,
    expected_size,
):
    rect = dimensions._page_rect_for_raster(
        fitz.Rect(0, 0, 300, 400),
        np.full(raster_shape, 255, dtype=np.uint8),
    )

    assert (rect.width, rect.height) == expected_size


def test_rotated_ordinary_provider_page_uses_swapped_canvas_dimensions():
    source = fitz.open()
    source.new_page(width=300, height=400)
    rotated = np.full((300, 400, 3), 255, dtype=np.uint8)
    decisions = [
        {
            "skip_ocr": False,
            "page_index": 0,
            "page_number": 1,
            "source_unit_id": "pdf-page:000001",
            "orientation_image": rotated,
        }
    ]

    provider = None
    try:
        provider_bytes, provider_map = (
            dimensions._build_ordinary_source_preserving_dimensions(
                source,
                decisions,
            )
        )
        assert provider_bytes is not None
        provider = fitz.open(stream=provider_bytes, filetype="pdf")
        assert provider.page_count == 1
        assert provider[0].rect.width == pytest.approx(400.0)
        assert provider[0].rect.height == pytest.approx(300.0)
        assert provider_map == [
            {
                "provider_page_index": 0,
                "original_page_index": 0,
                "original_page_number": 1,
                "source_unit_id": "pdf-page:000001",
            }
        ]
    finally:
        if provider is not None:
            provider.close()
        source.close()


def test_rotated_presentation_render_uses_swapped_canvas_dimensions():
    source = fitz.open()
    source.new_page(width=300, height=400)
    output = fitz.open()
    rotated = np.full((300, 400, 3), 255, dtype=np.uint8)
    try:
        dimensions._insert_geometry_or_original_preserving_dimensions(
            output,
            source,
            0,
            rotated,
        )

        assert output.page_count == 1
        assert output[0].rect.width == pytest.approx(400.0)
        assert output[0].rect.height == pytest.approx(300.0)
    finally:
        output.close()
        source.close()


def test_rotated_presentation_manifest_reports_render_canvas_dimensions():
    rotated = np.full((300, 400, 3), 255, dtype=np.uint8)
    decision = {
        "page_number": 1,
        "source_unit_id": "pdf-page:000001",
        "features": {
            "native_text_chars": 12,
            "maximum_embedded_image_coverage": 0.95,
        },
        "classification": {
            "page_role": "cover",
            "confidence": 0.99,
        },
        "geometry": {
            "accepted": True,
            "orientation": {
                "detected_degrees": 90,
                "applied": True,
            },
        },
        "geometry_image": rotated,
        "page_width_points": 300.0,
        "page_height_points": 400.0,
    }

    manifest = dimensions._presentation_manifest_page_preserving_dimensions(
        decision
    )
    synthetic = presentation._synthetic_page(manifest)

    assert manifest["source_page_width_points"] == pytest.approx(300.0)
    assert manifest["source_page_height_points"] == pytest.approx(400.0)
    assert manifest["page_width_points"] == pytest.approx(400.0)
    assert manifest["page_height_points"] == pytest.approx(300.0)
    assert synthetic["width"] == pytest.approx(400.0)
    assert synthetic["height"] == pytest.approx(300.0)


def test_candidate_geometry_render_limit_fails_open_to_ordinary_ocr(monkeypatch):
    orientation.install_discrete_orientation_compat()
    dimensions.install_orientation_dimensions_compat()
    analysis_fail_open.install_analysis_render_fail_open_compat()
    classifier_calls = []

    def render_limit(*_args, **_kwargs):
        raise ValueError("OpenCV experiment page render exceeds pixel limit")

    def classifier(*_args, **_kwargs):
        classifier_calls.append(True)
        raise AssertionError("classifier must not run after geometry render failure")

    monkeypatch.setattr(dimensions, "_OriginalOrientedGeometry", render_limit)
    monkeypatch.setattr(dimensions, "_OriginalPageClassifier", classifier)
    monkeypatch.setattr(
        presentation,
        "_analysis_image",
        lambda _page: np.full((120, 90, 3), 255, dtype=np.uint8),
    )

    source = fitz.open()
    source.new_page(width=300, height=400)
    provider = None
    try:
        decisions = dimensions._classify_source_pages_fail_open(source)
        assert len(decisions) == 1
        decision = decisions[0]
        assert decision["candidate"] is True
        assert decision["skip_ocr"] is False
        assert decision["decision_reason"] == "pre_ocr_geometry_failed"
        assert decision["geometry_image"] is None
        assert decision["orientation_image"] is None
        assert decision["geometry"]["accepted"] is False
        assert decision["geometry"]["reason"] == "pre_ocr_geometry_failed"
        assert decision["geometry"]["error_type"] == "ValueError"
        assert decision["classification"]["page_role"] == "unknown"
        assert decision["classification"]["provider"] == "none"
        assert decision["classification"]["reason_codes"] == [
            "pre_ocr_geometry_failed:ValueError"
        ]
        assert classifier_calls == []

        provider_bytes, provider_map = (
            dimensions._build_ordinary_source_preserving_dimensions(
                source,
                decisions,
            )
        )
        assert provider_bytes is not None
        provider = fitz.open(stream=provider_bytes, filetype="pdf")
        assert provider.page_count == 1
        assert provider_map[0]["source_unit_id"] == "pdf-page:000001"

        def v4_must_not_render(*_args, **_kwargs):
            raise AssertionError("failed page must bypass V4 rasterization")

        monkeypatch.setattr(
            dimensions,
            "_OriginalV4Preprocess",
            v4_must_not_render,
        )
        processed = dimensions._preprocess_pdf_geometry_fail_open(
            provider_bytes,
            expected_page_count=1,
        )
        assert processed.page_count == 1
        assert processed.changed_page_count == 0
        assert processed.pages[0].route == "quality_gate_original"
        assert processed.pages[0].fallback_used is True
        assert processed.pages[0].safe_reason == (
            "pre_ocr_geometry_failed:ValueError"
        )
        manifest = presentation._v4_manifest(processed)
        assert manifest["pages"][0]["selected"] == "original"
        assert manifest["pages"][0]["geometry"]["reason"] == (
            "pre_ocr_geometry_failed"
        )
        assert manifest["pages"][0]["background"]["attempted"] is False
        assert dimensions._ORDINARY_FAIL_OPEN_PAGES.get() == {}
        assert preprocess._classify_source_pages is (
            analysis_fail_open._classify_source_pages_analysis_fail_open
        )
    finally:
        if provider is not None:
            provider.close()
        source.close()


def test_analysis_render_limit_fails_open_before_geometry_and_v4(monkeypatch):
    orientation.install_discrete_orientation_compat()
    dimensions.install_orientation_dimensions_compat()
    analysis_fail_open.install_analysis_render_fail_open_compat()
    geometry_calls = []
    classifier_calls = []

    def analysis_render_limit(*_args, **_kwargs):
        raise ValueError("OpenCV experiment page render exceeds pixel limit")

    def geometry_must_not_run(*_args, **_kwargs):
        geometry_calls.append(True)
        raise AssertionError("geometry must not run after analysis render failure")

    def classifier_must_not_run(*_args, **_kwargs):
        classifier_calls.append(True)
        raise AssertionError("classifier must not run after analysis render failure")

    monkeypatch.setattr(
        analysis_fail_open,
        "_OriginalAnalysisImage",
        analysis_render_limit,
    )
    monkeypatch.setattr(
        analysis_fail_open,
        "_OriginalOrientedGeometry",
        geometry_must_not_run,
    )
    monkeypatch.setattr(
        analysis_fail_open,
        "_OriginalClassifier",
        classifier_must_not_run,
    )

    source = fitz.open()
    page = source.new_page(width=300, height=400)
    page.insert_textbox(
        fitz.Rect(20, 20, 280, 380),
        "BORN DIGITAL BODY TEXT " * 40,
        fontsize=8,
    )
    provider = None
    try:
        decisions = analysis_fail_open._classify_source_pages_analysis_fail_open(
            source
        )
        assert len(decisions) == 1
        decision = decisions[0]
        assert decision["candidate"] is True
        assert decision["skip_ocr"] is False
        assert decision["decision_reason"] == "pre_ocr_analysis_failed"
        assert decision["geometry_image"] is None
        assert decision["orientation_image"] is None
        assert decision["geometry"]["accepted"] is False
        assert decision["geometry"]["reason"] == "pre_ocr_analysis_failed"
        assert decision["geometry"]["error_type"] == "ValueError"
        assert decision["features"]["analysis_render_failed"] is True
        assert decision["features"]["analysis_render_error_type"] == "ValueError"
        assert decision["classification"]["page_role"] == "unknown"
        assert decision["classification"]["provider"] == "none"
        assert decision["classification"]["reason_codes"] == [
            "pre_ocr_analysis_failed:ValueError"
        ]
        assert geometry_calls == []
        assert classifier_calls == []

        provider_bytes, provider_map = (
            analysis_fail_open._build_ordinary_source_analysis_fail_open(
                source,
                decisions,
            )
        )
        assert provider_bytes is not None
        provider = fitz.open(stream=provider_bytes, filetype="pdf")
        assert provider.page_count == 1
        assert provider_map[0]["source_unit_id"] == "pdf-page:000001"

        def v4_must_not_render(*_args, **_kwargs):
            raise AssertionError("analysis-failed page must bypass V4 rasterization")

        monkeypatch.setattr(
            dimensions,
            "_OriginalV4Preprocess",
            v4_must_not_render,
        )
        processed = analysis_fail_open._preprocess_pdf_geometry_analysis_fail_open(
            provider_bytes,
            expected_page_count=1,
        )
        assert processed.page_count == 1
        assert processed.changed_page_count == 0
        assert processed.pages[0].route == "quality_gate_original"
        assert processed.pages[0].fallback_used is True
        assert processed.pages[0].safe_reason == (
            "pre_ocr_analysis_failed:ValueError"
        )
        manifest = presentation._v4_manifest(processed)
        assert manifest["pages"][0]["selected"] == "original"
        assert manifest["pages"][0]["geometry"]["reason"] == (
            "pre_ocr_analysis_failed"
        )
        assert manifest["pages"][0]["background"]["attempted"] is False
        assert manifest["pages"][0]["background"]["reason"] == (
            "pre_ocr_analysis_failed_v4_bypassed"
        )
        assert manifest["pages"][0]["analysis"]["error_type"] == "ValueError"
        assert dimensions._ORDINARY_FAIL_OPEN_PAGES.get() == {}
        assert analysis_fail_open._ANALYSIS_PROVIDER_PAGES.get() == {}
    finally:
        if provider is not None:
            provider.close()
        source.close()
