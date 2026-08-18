from __future__ import annotations

import hashlib

import cv2
import numpy as np

from app.processing import pdf_crop_dark_foreground_anchor_compat as anchor
from app.processing import pdf_opencv_modal_bridge as bridge
from app.processing import pdf_opencv_quality_pipeline as v4


def _baseline() -> np.ndarray:
    image = np.full((360, 720, 3), 210, dtype=np.uint8)
    for y in (70, 140, 210, 280):
        cv2.line(image, (35, y), (685, y), (80, 80, 80), 2)
    for x in range(80, 650, 75):
        cv2.rectangle(image, (x, 100), (x + 20, 108), (80, 80, 80), -1)
        cv2.rectangle(image, (x + 25, 100), (x + 32, 108), (88, 88, 88), -1)
    return image


def _raw_candidate(baseline: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(baseline, cv2.COLOR_BGR2GRAY)
    candidate = baseline.astype(np.int16).copy()
    candidate[gray <= 82] += 55
    candidate[(gray > 82) & (gray <= 94)] += 36
    candidate[gray > 180] += 25
    return np.clip(candidate, 0, 255).astype(np.uint8)


def test_outer_anchor_keeps_inner_capture_as_raw_opencv_bytes() -> None:
    saved_normalize = v4._normalize_background
    saved_process = bridge.process_visual_crop_v4
    saved_installed = anchor._INSTALLED
    baseline = _baseline()
    raw = _raw_candidate(baseline)
    captured: list[bytes] = []

    def inner_raw_capture(image):
        candidate = raw.copy()
        captured.append(bridge._encode_png(candidate))
        return candidate

    def semantic_delegate(png_bytes: bytes, *, page_manifest, **kwargs):
        source = bridge._decode_png(png_bytes)
        candidate = v4._normalize_background(source)
        return bridge._encode_png(candidate), {
            "background": {"attempted": True, "accepted": True},
        }

    v4._normalize_background = inner_raw_capture
    bridge.process_visual_crop_v4 = semantic_delegate
    anchor._INSTALLED = False
    try:
        anchor.install_pdf_crop_dark_foreground_anchor_compat()
        output, metadata = bridge.process_visual_crop_v4(
            bridge._encode_png(baseline),
            page_manifest={"route": "quality_gate_original"},
        )
        assert len(captured) == 1
        assert np.array_equal(bridge._decode_png(captured[0]), raw)
        diagnostics = metadata["background"]["dark_foreground_anchor_lock"]
        assert diagnostics["applied"] is True
        assert diagnostics["diagnostic_candidate_stage"] == "raw_opencv_before_dark_anchor"
        assert diagnostics["semantic_candidate_stage"] == "dark_foreground_anchor_restored"
        raw_sha = hashlib.sha256(captured[0]).hexdigest()
        anchored_sha = hashlib.sha256(output).hexdigest()
        assert diagnostics["raw_candidate_sha256"] == raw_sha
        assert diagnostics["anchored_candidate_sha256"] == anchored_sha
        assert raw_sha != anchored_sha
        assert metadata["opencv_raw_candidate_sha256"] == raw_sha
        assert metadata["opencv_candidate_stage"] == "dark_foreground_anchor_restored"
    finally:
        v4._normalize_background = saved_normalize
        bridge.process_visual_crop_v4 = saved_process
        anchor._INSTALLED = saved_installed


def test_crop_that_never_normalizes_background_gets_no_anchor_metadata() -> None:
    saved_normalize = v4._normalize_background
    saved_process = bridge.process_visual_crop_v4
    saved_installed = anchor._INSTALLED

    def no_background_delegate(png_bytes: bytes, *, page_manifest, **kwargs):
        return png_bytes, {
            "background": {
                "attempted": False,
                "accepted": False,
                "reason": "clean_white_crop_background_skipped",
            }
        }

    bridge.process_visual_crop_v4 = no_background_delegate
    anchor._INSTALLED = False
    try:
        anchor.install_pdf_crop_dark_foreground_anchor_compat()
        source = bridge._encode_png(_baseline())
        output, metadata = bridge.process_visual_crop_v4(
            source,
            page_manifest={"route": "geometry_only"},
        )
        assert output == source
        assert "dark_foreground_anchor_lock" not in metadata["background"]
        assert "opencv_raw_candidate_sha256" not in metadata
        assert "opencv_candidate_stage" not in metadata
    finally:
        v4._normalize_background = saved_normalize
        bridge.process_visual_crop_v4 = saved_process
        anchor._INSTALLED = saved_installed
