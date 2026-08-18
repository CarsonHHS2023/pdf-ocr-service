from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from app.processing import pdf_crop_opencv_semantic_gate_compat as gate
from app.processing import pdf_crop_opencv_semantic_gate_hardening_compat as hardening
from app.processing import pdf_crop_opencv_semantic_gate_request_compat as request_hardening


def _png(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _judgment() -> dict[str, object]:
    return {
        "decision": "accept",
        "confidence": 0.99,
        "background_improved": True,
        "content_preserved": True,
        "unexpected_added_content": False,
        "unexpected_removed_content": False,
        "geometry_changed": False,
        "color_or_fill_changed": False,
        "expected_cleanup_changes": ["paper background normalized"],
        "suspected_content_changes": [],
        "reason": "test",
    }


def _accepted_response() -> dict[str, object]:
    return {"choices": [{"message": {"content": json.dumps(_judgment())}}]}


def test_outbound_judge_uses_high_detail_for_every_image_input() -> None:
    captured = {}

    def fake_post(url, headers, payload, timeout_seconds):
        captured["url"] = url
        captured["payload"] = payload
        return _accepted_response()

    request_hardening.install_pdf_crop_opencv_semantic_gate_request_compat()
    reviewer = gate.OpenAIOpenCVCropJudge(
        api_key="test-key",
        base_url="https://api.openai.com/v1",
        max_attempts=1,
        json_post=fake_post,
    )
    image = _png(np.full((64, 96, 3), 220, dtype=np.uint8))

    result = reviewer.judge(
        baseline_png=image,
        candidate_png=image,
        difference_png=image,
        roi_panels=(image, image),
        metrics={},
    )

    assert result["decision"] == "accept"
    assert captured["url"].startswith("https://")
    user_message = captured["payload"]["messages"][1]
    image_parts = [
        part
        for part in user_message["content"]
        if isinstance(part, dict) and part.get("type") == "image_url"
    ]
    assert len(image_parts) == 5
    assert {part["image_url"]["detail"] for part in image_parts} == {"high"}
    assert all(part["image_url"]["url"].startswith("data:image/png;base64,") for part in image_parts)


def test_outbound_judge_rejects_http_before_bearer_request() -> None:
    called = False

    def fake_post(url, headers, payload, timeout_seconds):
        nonlocal called
        called = True
        return _accepted_response()

    request_hardening.install_pdf_crop_opencv_semantic_gate_request_compat()
    reviewer = gate.OpenAIOpenCVCropJudge(
        api_key="must-not-be-sent",
        base_url="http://example.invalid/v1",
        max_attempts=1,
        json_post=fake_post,
    )
    image = _png(np.full((32, 32, 3), 220, dtype=np.uint8))

    with pytest.raises(ValueError, match="must use HTTPS"):
        reviewer.judge(
            baseline_png=image,
            candidate_png=image,
            difference_png=image,
            roi_panels=(),
            metrics={},
        )
    assert called is False


def test_faint_one_pixel_rule_loss_gets_structural_roi_without_foreground_lock() -> None:
    baseline = np.full((400, 800, 3), 205, dtype=np.uint8)
    # Only 11 gray levels darker than the surrounding paper. This deliberately
    # stays far above the old dark-foreground threshold.
    cv2.line(baseline, (120, 210), (680, 210), (194, 194, 194), 1)
    candidate = np.full_like(baseline, 205)

    request_hardening.install_pdf_crop_opencv_semantic_gate_request_compat()
    _, panels, metrics = hardening._bounded_change_evidence(
        _png(baseline),
        _png(candidate),
    )

    assert metrics["changed_pixel_count"] > 0
    assert metrics["structural_changed_pixel_count"] > 0
    assert metrics["roi_count"] > 0
    assert len(panels) == metrics["roi_count"]
    assert any(roi["kind"] == "structural_residual" for roi in metrics["rois"])
    # Ensure at least one selected ROI actually spans the faint rule's y-position.
    assert any(roi["bbox"][1] <= 210 <= roi["bbox"][3] for roi in metrics["rois"])


def test_accept_with_suspected_content_change_fails_open() -> None:
    request_hardening.install_pdf_crop_opencv_semantic_gate_request_compat()
    judgment = _judgment()
    judgment["suspected_content_changes"] = ["faint rule may have been weakened"]

    accepted, reason = gate._semantic_accepts(judgment)

    assert accepted is False
    assert reason == "semantic_gate_suspected_content_changes"


def test_prompt_defines_intentional_color_fill_semantics() -> None:
    request_hardening.install_pdf_crop_opencv_semantic_gate_request_compat()
    assert "Field semantics: color_or_fill_changed" in gate._GATE_SYSTEM_PROMPT
    assert "Do not set it merely because gray/aged paper background was normalized" in gate._GATE_SYSTEM_PROMPT
