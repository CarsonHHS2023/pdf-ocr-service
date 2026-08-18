from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.processing import pdf_crop_dark_foreground_anchor_compat as anchor
from app.processing import pdf_opencv_modal_bridge as bridge
from app.processing import pdf_opencv_quality_pipeline as v4


def _gray_table(width: int = 900, height: int = 520) -> np.ndarray:
    image = np.full((height, width, 3), 210, dtype=np.uint8)
    # A small, clearly separated dark mode representing text/grid strokes.
    for y in (70, 145, 220, 295, 370, 445):
        cv2.line(image, (45, y), (855, y), (80, 80, 80), 2, cv2.LINE_8)
    for row in range(5):
        for col in range(7):
            x0 = 90 + col * 105
            y0 = 95 + row * 72
            cv2.rectangle(image, (x0, y0), (x0 + 16, y0 + 5), (80, 80, 80), -1)
            cv2.rectangle(image, (x0 + 23, y0), (x0 + 29, y0 + 5), (88, 88, 88), -1)
    return image


def _faded_candidate(baseline: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(baseline, cv2.COLOR_BGR2GRAY)
    candidate = baseline.astype(np.int16).copy()
    candidate[gray <= 82] += 55
    candidate[(gray > 82) & (gray <= 94)] += 38
    candidate[gray > 180] += 25
    return np.clip(candidate, 0, 255).astype(np.uint8)


def _saved_runtime() -> dict[str, object]:
    return {
        "normalize": v4._normalize_background,
        "process": bridge.process_visual_crop_v4,
        "installed": anchor._INSTALLED,
    }


def _restore_runtime(saved: dict[str, object]) -> None:
    v4._normalize_background = saved["normalize"]
    bridge.process_visual_crop_v4 = saved["process"]
    anchor._INSTALLED = saved["installed"]


def test_histogram_finds_small_distinct_dark_foreground_mode() -> None:
    baseline = _gray_table()
    result = anchor._histogram_anchor_thresholds(baseline)
    assert result["eligible"] is True
    assert 76 <= result["foreground_peak_gray"] <= 90
    assert result["background_peak_gray"] == 210
    assert result["peak_separation_gray"] >= anchor._MIN_PEAK_SEPARATION
    assert result["hard_anchor_ratio"] < 0.10
    assert result["soft_anchor_ratio"] < 0.12


def test_dark_anchor_restores_hard_strokes_and_softens_edge_fade() -> None:
    baseline = _gray_table()
    candidate = _faded_candidate(baseline)
    restored, diagnostics = anchor._restore_dark_foreground(baseline, candidate)
    assert diagnostics["applied"] is True
    hard_threshold = int(diagnostics["hard_threshold_gray"])
    soft_threshold = int(diagnostics["soft_threshold_gray"])

    baseline_gray = cv2.cvtColor(baseline, cv2.COLOR_BGR2GRAY)
    candidate_gray = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY)
    restored_gray = cv2.cvtColor(restored, cv2.COLOR_BGR2GRAY)

    hard = (baseline_gray <= hard_threshold) & (
        candidate_gray - baseline_gray >= anchor._MIN_LIGHTENING_DELTA
    )
    assert np.count_nonzero(hard) > 0
    assert np.array_equal(restored[hard], baseline[hard])

    soft = (
        (baseline_gray > hard_threshold)
        & (baseline_gray <= soft_threshold)
        & (candidate_gray - baseline_gray >= anchor._MIN_LIGHTENING_DELTA)
    )
    assert np.count_nonzero(soft) > 0
    assert np.all(restored_gray[soft] <= candidate_gray[soft])
    assert np.any(restored_gray[soft] < candidate_gray[soft])
    assert np.all(restored_gray[soft] >= baseline_gray[soft])

    background = baseline_gray > 180
    assert np.array_equal(restored[background], candidate[background])


def test_anchor_never_overrides_candidate_pixels_that_became_darker() -> None:
    baseline = _gray_table()
    candidate = _faded_candidate(baseline)
    candidate[100:110, 100:110] = 30
    restored, _ = anchor._restore_dark_foreground(baseline, candidate)
    assert np.array_equal(restored[100:110, 100:110], candidate[100:110, 100:110])


def test_ambiguous_large_dark_region_is_not_locked() -> None:
    image = np.full((400, 800, 3), 210, dtype=np.uint8)
    image[:, :320] = 90
    candidate = np.full_like(image, 240)
    result = anchor._histogram_anchor_thresholds(image)
    assert result["eligible"] is False
    assert result["reason"] in {
        "hard_anchor_ratio_too_large",
        "soft_anchor_ratio_too_large",
    }
    restored, diagnostics = anchor._restore_dark_foreground(image, candidate)
    assert diagnostics["applied"] is False
    assert np.array_equal(restored, candidate)


def test_normalizer_is_crop_only_and_page_calls_are_unchanged() -> None:
    saved = _saved_runtime()
    baseline = _gray_table()
    raw_candidate = _faded_candidate(baseline)

    def fake_normalize(image):
        return raw_candidate.copy()

    v4._normalize_background = fake_normalize
    anchor._INSTALLED = False
    try:
        anchor.install_pdf_crop_dark_foreground_anchor_compat()
        page_candidate = v4._normalize_background(baseline)
        assert np.array_equal(page_candidate, raw_candidate)
    finally:
        _restore_runtime(saved)


def test_installed_crop_context_restores_candidate_and_attaches_metadata() -> None:
    saved = _saved_runtime()
    baseline = _gray_table()
    raw_candidate = _faded_candidate(baseline)

    def fake_normalize(image):
        return raw_candidate.copy()

    def semantic_delegate(png_bytes: bytes, *, page_manifest, **kwargs):
        source = bridge._decode_png(png_bytes)
        candidate = v4._normalize_background(source)
        return bridge._encode_png(candidate), {
            "background": {"attempted": True, "accepted": True},
            "semantic_gate": {"invoked": True},
        }

    v4._normalize_background = fake_normalize
    bridge.process_visual_crop_v4 = semantic_delegate
    anchor._INSTALLED = False
    try:
        anchor.install_pdf_crop_dark_foreground_anchor_compat()
        output, metadata = bridge.process_visual_crop_v4(
            bridge._encode_png(baseline),
            page_manifest={"route": "quality_gate_original"},
        )
        restored = bridge._decode_png(output)
        diagnostics = metadata["background"]["dark_foreground_anchor_lock"]
        assert diagnostics["status"] == "applied"
        assert diagnostics["applied"] is True
        assert diagnostics["hard_restored_pixel_count"] > 0
        assert diagnostics["anchored_candidate_sha256"] != diagnostics["raw_candidate_sha256"]
        assert np.mean(restored) < np.mean(raw_candidate)
    finally:
        _restore_runtime(saved)


def test_anchor_analysis_failure_fails_open_to_raw_opencv_candidate(monkeypatch) -> None:
    saved = _saved_runtime()
    baseline = _gray_table()
    raw_candidate = _faded_candidate(baseline)

    def fake_normalize(image):
        return raw_candidate.copy()

    def semantic_delegate(png_bytes: bytes, *, page_manifest, **kwargs):
        source = bridge._decode_png(png_bytes)
        candidate = v4._normalize_background(source)
        return bridge._encode_png(candidate), {
            "background": {"attempted": True, "accepted": False},
        }

    def explode(*args, **kwargs):
        raise RuntimeError("synthetic anchor failure")

    v4._normalize_background = fake_normalize
    bridge.process_visual_crop_v4 = semantic_delegate
    anchor._INSTALLED = False
    monkeypatch.setattr(anchor, "_restore_dark_foreground", explode)
    try:
        anchor.install_pdf_crop_dark_foreground_anchor_compat()
        output, metadata = bridge.process_visual_crop_v4(
            bridge._encode_png(baseline),
            page_manifest={"route": "quality_gate_original"},
        )
        assert np.array_equal(bridge._decode_png(output), raw_candidate)
        diagnostics = metadata["background"]["dark_foreground_anchor_lock"]
        assert diagnostics["status"] == "analysis_failed"
        assert diagnostics["applied"] is False
        assert diagnostics["error_type"] == "RuntimeError"
        assert "synthetic anchor failure" not in str(diagnostics)
    finally:
        _restore_runtime(saved)


def test_histogram_analysis_is_bounded_for_large_crop() -> None:
    large = cv2.resize(_gray_table(), (3600, 2400), interpolation=cv2.INTER_NEAREST)
    result = anchor._histogram_anchor_thresholds(large)
    assert max(result["analysis_dimensions"]) <= anchor._ANALYSIS_MAX_SIDE
