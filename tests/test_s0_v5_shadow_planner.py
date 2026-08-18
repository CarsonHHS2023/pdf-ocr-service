from __future__ import annotations

import cv2
import fitz  # type: ignore[import]
import numpy as np

from app.processing.s0_v5_shadow_geometry import cheap_geometry_observation
from app.processing.s0_v5_shadow_planner import (
    BACKGROUND_ONLY,
    PASSTHROUGH,
    CheapPageObservation,
    build_document_profile,
    compare_plan_to_actual,
    observe_page,
    plan_page,
    summarize_shadow_results,
)


def _observation(
    page_number: int = 1,
    *,
    born_digital: bool = False,
    clean_white: bool = False,
    background_suspect: bool = False,
    geometry_suspect: bool = False,
    color_critical: bool = False,
    full_page_raster: bool = True,
    xdpi: float | None = 150.0,
    ydpi: float | None = 150.0,
) -> CheapPageObservation:
    return CheapPageObservation(
        page_number=page_number,
        born_digital=born_digital,
        embedded_image_count=1 if full_page_raster else 0,
        maximum_embedded_image_coverage=1.0 if full_page_raster else 0.0,
        single_full_page_raster=full_page_raster,
        native_raster_width_pixels=701 if full_page_raster else None,
        native_raster_height_pixels=1084 if full_page_raster else None,
        native_raster_xdpi=xdpi if full_page_raster else None,
        native_raster_ydpi=ydpi if full_page_raster else None,
        near_white_ratio=0.9 if clean_white else 0.1,
        border_near_white_ratio=0.95 if clean_white else 0.2,
        largest_border_connected_near_white_ratio=0.8 if clean_white else 0.1,
        background_std=2.0 if clean_white else 14.0,
        background_range=8.0 if clean_white else 42.0,
        dark_ratio=0.02,
        high_saturation_ratio=0.0,
        color_critical=color_critical,
        estimated_skew_degrees=0.0 if not geometry_suspect else 0.7,
        estimated_skew_confidence=0.0 if not geometry_suspect else 0.8,
        perspective_coverage=0.0,
        perspective_distortion=0.0,
        clean_white=clean_white,
        background_suspect=background_suspect,
        geometry_suspect=geometry_suspect,
    )


def test_born_digital_shadow_plan_is_passthrough() -> None:
    observation = _observation(born_digital=True, full_page_raster=False)
    profile = build_document_profile([observation])

    plan = plan_page(observation, profile)

    assert plan.route == PASSTHROUGH
    assert plan.requires_high_resolution is False
    assert "born_digital" in plan.reason_codes


def test_clean_white_without_geometry_signal_is_passthrough() -> None:
    observation = _observation(clean_white=True)
    profile = build_document_profile([observation])

    plan = plan_page(observation, profile)

    assert plan.route == PASSTHROUGH
    assert plan.requires_high_resolution is False


def test_uniform_gray_full_page_raster_profile_and_native_candidate() -> None:
    observations = [
        _observation(page_number, background_suspect=True)
        for page_number in range(1, 11)
    ]
    profile = build_document_profile(observations)

    assert profile.profile_kind == "uniform_gray_scan"
    assert profile.full_page_raster_ratio == 1.0
    assert profile.background_suspect_ratio == 1.0
    assert profile.native_raster_dpi_consistent is True
    assert profile.median_native_raster_xdpi == 150.0
    assert profile.median_native_raster_ydpi == 150.0

    plan = plan_page(observations[0], profile)
    assert plan.route == BACKGROUND_ONLY
    assert plan.native_raster_candidate is True


def test_passthrough_false_negative_is_detected_against_current_v4_manifest() -> None:
    observation = _observation(clean_white=True)
    profile = build_document_profile([observation])
    plan = plan_page(observation, profile)
    actual = {
        "page_number": 1,
        "route": "normalized_scan",
        "ocr_route": "modal_paddle_ocr",
        "geometry": {"accepted": False},
        "background": {"accepted": True},
    }

    comparison = compare_plan_to_actual(plan, actual)

    assert comparison["scope"] == "ordinary_v4"
    assert comparison["actual_requires_treatment"] is True
    assert comparison["false_negative_passthrough"] is True
    assert comparison["route_miss"] is True


def test_presentation_page_is_excluded_from_v4_route_comparison() -> None:
    observation = _observation(background_suspect=True)
    profile = build_document_profile([observation])
    plan = plan_page(observation, profile)

    comparison = compare_plan_to_actual(
        plan,
        {
            "page_number": 1,
            "route": "presentation_original",
            "ocr_route": "skipped_presentation_image",
        },
    )

    assert comparison["scope"] == "presentation_excluded"
    assert comparison["false_negative_passthrough"] is None


def test_shadow_summary_counts_false_negatives_and_unnecessary_escalation() -> None:
    summary = summarize_shadow_results(
        [
            {
                "scope": "ordinary_v4",
                "false_negative_passthrough": True,
                "route_miss": True,
                "unnecessary_escalation": False,
            },
            {
                "scope": "ordinary_v4",
                "false_negative_passthrough": False,
                "route_miss": False,
                "unnecessary_escalation": True,
            },
            {"scope": "presentation_excluded"},
        ]
    )

    assert summary == {
        "page_count": 3,
        "ordinary_compared_count": 2,
        "presentation_excluded_count": 1,
        "false_negative_passthrough_count": 1,
        "route_miss_count": 1,
        "unnecessary_escalation_count": 1,
    }


def test_observe_page_detects_single_full_page_native_raster_without_rendering_it() -> None:
    document = fitz.open()
    try:
        page = document.new_page(width=360, height=540)
        bgr = np.full((1125, 750, 3), 220, dtype=np.uint8)
        success, encoded = cv2.imencode(".png", bgr)
        assert success
        page.insert_image(page.rect, stream=encoded.tobytes())
        analysis = np.full((720, 480, 3), 220, dtype=np.uint8)

        observation = observe_page(
            page=page,
            analysis_image=analysis,
            native_features={
                "native_text_chars": 0,
                "maximum_embedded_image_coverage": 1.0,
                "pdf_rotation_metadata": 0,
            },
        )
    finally:
        document.close()

    assert observation.single_full_page_raster is True
    assert observation.native_raster_width_pixels == 750
    assert observation.native_raster_height_pixels == 1125
    assert observation.native_raster_xdpi == 150.0
    assert observation.native_raster_ydpi == 150.0
    assert observation.background_suspect is True


def test_cheap_shadow_geometry_does_not_escalate_blank_page() -> None:
    image = np.full((900, 600, 3), 255, dtype=np.uint8)

    result = cheap_geometry_observation(image)

    assert result["policy_version"] == "atlas_s0_v5_cheap_geometry_v1"
    assert result["estimated_skew_degrees"] == 0.0
    assert result["geometry_suspect"] is False


def test_cheap_shadow_geometry_escalates_clear_text_skew() -> None:
    image = np.full((900, 600, 3), 255, dtype=np.uint8)
    for y in range(160, 760, 55):
        cv2.line(image, (100, y), (500, y), (0, 0, 0), thickness=5)
    matrix = cv2.getRotationMatrix2D((300, 450), 1.0, 1.0)
    skewed = cv2.warpAffine(
        image,
        matrix,
        (600, 900),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )

    result = cheap_geometry_observation(skewed)

    assert abs(float(result["estimated_skew_degrees"])) >= 0.5
    assert float(result["estimated_skew_score_gain"]) >= 0.01
    assert result["geometry_suspect"] is True
