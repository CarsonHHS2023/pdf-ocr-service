from __future__ import annotations

import fitz
import numpy as np

from app.processing import pdf_page_high_resolution_confirmation_compat as confirmation
from app.processing import pdf_page_orientation_compat as orientation
from app.processing import pdf_page_presentation_bridge as bridge


def _opencv_proposal(degrees: int = 180) -> orientation.DiscreteOrientation:
    return orientation.DiscreteOrientation(
        correction_degrees=degrees,
        confidence=0.391221,
        source="opencv_layout",
        native_text_chars=0,
        image_score=0.5,
    )


def _page():
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    return document, page


def test_opencv_only_180_proposal_rejected_by_high_resolution_confirmation(
    monkeypatch,
):
    proposal = _opencv_proposal()
    monkeypatch.setattr(
        confirmation,
        "_OriginalDetectOrientation",
        lambda *_args, **_kwargs: proposal,
    )
    monkeypatch.setattr(
        confirmation,
        "_request_high_resolution_orientation",
        lambda *_args, **_kwargs: {
            "source_unit_id": "pdf-page:000001",
            "upright_correction_degrees": 0,
            "confidence": 0.99,
            "reason_codes": ["original_text_is_upright"],
        },
    )

    document, page = _page()
    try:
        result = confirmation._detect_orientation_with_high_resolution_confirmation(
            page,
            np.full((120, 90, 3), 255, dtype=np.uint8),
        )
    finally:
        document.close()

    assert result.correction_degrees == 0
    assert result.applied is False
    assert result.source == "openai_high_resolution_rejected_opencv_layout"
    assert result.confidence == 0.99


def test_confirmed_180_proposal_remains_available_for_truly_rotated_page(
    monkeypatch,
):
    proposal = _opencv_proposal()
    monkeypatch.setattr(
        confirmation,
        "_OriginalDetectOrientation",
        lambda *_args, **_kwargs: proposal,
    )
    monkeypatch.setattr(
        confirmation,
        "_request_high_resolution_orientation",
        lambda *_args, **_kwargs: {
            "source_unit_id": "pdf-page:000001",
            "upright_correction_degrees": 180,
            "confidence": 0.97,
            "reason_codes": ["proposed_variant_text_is_upright"],
        },
    )

    document, page = _page()
    try:
        result = confirmation._detect_orientation_with_high_resolution_confirmation(
            page,
            np.full((120, 90, 3), 255, dtype=np.uint8),
        )
    finally:
        document.close()

    assert result.correction_degrees == 180
    assert result.applied is True
    assert result.source == "openai_high_resolution_confirmed_opencv_layout"
    assert result.confidence == 0.97


def test_orientation_confirmation_failure_preserves_original_page(monkeypatch):
    from app.processing import pdf_opencv_quality_pipeline as v4

    proposal = _opencv_proposal()
    monkeypatch.setattr(
        confirmation,
        "_OriginalDetectOrientation",
        lambda *_args, **_kwargs: proposal,
    )

    def unavailable(*_args, **_kwargs):
        raise TimeoutError("confirmation unavailable")

    monkeypatch.setattr(
        confirmation,
        "_request_high_resolution_orientation",
        unavailable,
    )

    source_image = np.full((8, 6, 3), 255, dtype=np.uint8)
    monkeypatch.setattr(
        v4,
        "_render_page_bgr",
        lambda *_args, **_kwargs: source_image.copy(),
    )

    class Diagnostic:
        perspective_applied = False
        perspective_confidence = 0.0
        perspective_distortion = 0.0
        deskew_applied = False
        deskew_angle_degrees = 0.0
        deskew_confidence = 0.0
        residual_angle_degrees = 0.0
        residual_confidence = 0.0

    monkeypatch.setattr(
        v4,
        "_build_geometry_candidate",
        lambda image: (image.copy(), Diagnostic()),
    )
    monkeypatch.setattr(
        v4,
        "_gate_geometry_candidate",
        lambda *_args, **_kwargs: (False, "geometry_not_required", {}),
    )

    document, page = _page()
    try:
        result = confirmation._detect_orientation_with_high_resolution_confirmation(
            page,
            np.full((120, 90, 3), 255, dtype=np.uint8),
        )
        selected, metadata, oriented_source = orientation._oriented_geometry(
            page,
            result,
        )
    finally:
        document.close()

    assert result.correction_degrees == 0
    assert result.source == "opencv_layout_unconfirmed"
    assert selected is None
    assert oriented_source is None
    assert metadata["orientation"]["applied"] is False
    assert metadata["applied_steps"] == []


def test_low_resolution_presentation_proposal_is_replaced_by_high_resolution_body(
    monkeypatch,
):
    monkeypatch.setattr(
        confirmation,
        "_OriginalOpenAIClassification",
        lambda *_args, **_kwargs: {
            "source_unit_id": "pdf-page:000012",
            "page_role": "full_page_chart",
            "confidence": 0.98,
            "reason_codes": ["dominant_chart_and_table_layout"],
            "provider": "openai",
            "model_id": "test-model",
            "prompt_version": "low-resolution",
            "image_detail": "low",
            "input_tokens": 700,
            "output_tokens": 100,
            "cache_hit": False,
        },
    )
    monkeypatch.setattr(
        confirmation,
        "_request_high_resolution_classification",
        lambda *_args, **_kwargs: {
            "source_unit_id": "pdf-page:000012",
            "page_role": "body",
            "confidence": 0.99,
            "reason_codes": [
                "mixed_chart_and_body_layout",
                "high_resolution_confirmed",
                "body_prose_present",
                "visual_coverage_partial",
            ],
            "provider": "openai",
            "model_id": "test-model",
            "prompt_version": confirmation.PROMPT_VERSION,
            "image_detail": "high",
            "input_tokens": 3000,
            "output_tokens": 200,
            "cache_hit": False,
        },
    )

    result = confirmation._openai_classification_with_high_resolution_confirmation(
        b"not-decoded-because-request-is-mocked",
        {},
        {"source_unit_id": "pdf-page:000012"},
    )

    assert result["page_role"] == "body"
    assert result["image_detail"] == "high"
    assert "high_resolution_confirmed" in result["reason_codes"]
    assert "low_resolution_role_full_page_chart" in result["reason_codes"]


def test_low_resolution_body_result_does_not_require_expensive_confirmation(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        confirmation,
        "_OriginalOpenAIClassification",
        lambda *_args, **_kwargs: {
            "source_unit_id": "pdf-page:000003",
            "page_role": "body",
            "confidence": 0.97,
            "reason_codes": ["mixed_text_and_diagram_layout"],
            "provider": "openai",
            "model_id": "test-model",
            "prompt_version": "low-resolution",
            "image_detail": "high",
            "input_tokens": 3000,
            "output_tokens": 200,
            "cache_hit": False,
        },
    )
    monkeypatch.setattr(
        confirmation,
        "_request_high_resolution_classification",
        lambda *_args, **_kwargs: calls.append(True),
    )

    result = confirmation._openai_classification_with_high_resolution_confirmation(
        b"unused",
        {},
        {"source_unit_id": "pdf-page:000003"},
    )

    assert result["page_role"] == "body"
    assert calls == []


def _confirmed_chart(*, reason_codes: list[str]) -> dict[str, object]:
    return {
        "source_unit_id": "pdf-page:000012",
        "page_role": "full_page_chart",
        "confidence": 0.99,
        "reason_codes": reason_codes,
        "provider": "openai",
        "image_detail": "high",
    }


def test_full_page_chart_with_substantial_prose_falls_back_to_ordinary_ocr(
    monkeypatch,
):
    monkeypatch.setattr(
        confirmation,
        "_OriginalSkipOcrDecision",
        lambda *_args, **_kwargs: (True, "presentation_page_confirmed"),
    )
    classification = _confirmed_chart(
        reason_codes=[
            "high_resolution_confirmed",
            "body_prose_present",
            "visual_coverage_partial",
        ]
    )

    skip, reason = confirmation._skip_ocr_with_high_resolution_confirmation(
        classification,
        {
            "text_region_count": 84,
            "dominant_visual_region_ratio": 0.028848,
        },
    )

    assert skip is False
    assert reason == "high_resolution_body_prose_conflict"


def test_dense_text_conflict_rejects_false_full_page_chart_even_if_model_says_dominant(
    monkeypatch,
):
    monkeypatch.setattr(
        confirmation,
        "_OriginalSkipOcrDecision",
        lambda *_args, **_kwargs: (True, "presentation_page_confirmed"),
    )
    classification = _confirmed_chart(
        reason_codes=[
            "high_resolution_confirmed",
            "body_prose_absent",
            "visual_coverage_dominant",
        ]
    )

    skip, reason = confirmation._skip_ocr_with_high_resolution_confirmation(
        classification,
        {
            "text_region_count": 84,
            "dominant_visual_region_ratio": 0.028848,
        },
    )

    assert skip is False
    assert reason == "local_dense_text_visual_conflict"


def test_genuine_high_resolution_full_page_chart_can_still_skip_ocr(monkeypatch):
    monkeypatch.setattr(
        confirmation,
        "_OriginalSkipOcrDecision",
        lambda *_args, **_kwargs: (True, "presentation_page_confirmed"),
    )
    classification = _confirmed_chart(
        reason_codes=[
            "high_resolution_confirmed",
            "body_prose_absent",
            "visual_coverage_full_page",
        ]
    )

    skip, reason = confirmation._skip_ocr_with_high_resolution_confirmation(
        classification,
        {
            "text_region_count": 5,
            "dominant_visual_region_ratio": 0.62,
        },
    )

    assert skip is True
    assert reason == "presentation_page_high_resolution_confirmed"


def test_test_override_behavior_is_not_changed(monkeypatch):
    monkeypatch.setattr(
        confirmation,
        "_OriginalSkipOcrDecision",
        lambda *_args, **_kwargs: (True, "presentation_page_confirmed"),
    )

    skip, reason = confirmation._skip_ocr_with_high_resolution_confirmation(
        {
            "page_role": "cover",
            "confidence": 0.99,
            "provider": "test_override",
            "image_detail": "low",
            "reason_codes": ["fixture"],
        },
        {},
    )

    assert skip is True
    assert reason == "presentation_page_confirmed"
