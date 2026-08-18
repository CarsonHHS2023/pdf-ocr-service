from __future__ import annotations

import cv2
import numpy as np

from app.processing import pdf_crop_dark_foreground_anchor_compat as anchor


def _multi_peak_scan() -> np.ndarray:
    image = np.full((500, 900, 3), 188, dtype=np.uint8)
    # Broad dark foreground mode around 64.
    for y in range(80, 380, 50):
        cv2.line(image, (60, y), (840, y), (64, 64, 64), 3, cv2.LINE_8)
    for row in range(5):
        for col in range(8):
            x = 90 + col * 95
            y = 105 + row * 55
            cv2.rectangle(image, (x, y), (x + 20, y + 6), (64, 64, 64), -1)

    # A lighter but still meaningful local mode around 106.
    for row in range(4):
        for col in range(6):
            x = 130 + col * 110
            y = 120 + row * 70
            cv2.rectangle(image, (x, y), (x + 18, y + 5), (106, 106, 106), -1)
    return image


def test_darkest_qualified_local_peak_is_selected_without_background_backsolve() -> None:
    result = anchor._histogram_anchor_thresholds(_multi_peak_scan())
    assert result["eligible"] is True
    assert 60 <= result["foreground_peak_gray"] <= 68
    assert result["background_peak_gray"] == 188
    assert result["foreground_selection"] == "darkest_qualified_local_peak"
    assert result["valley_gate_role"] == "diagnostic_only"
    assert result["selected_foreground_peak_support_ratio"] >= anchor._MIN_LOCAL_PEAK_SUPPORT_RATIO
    assert result["selected_foreground_peak_prominence_ratio"] >= anchor._MIN_LOCAL_PEAK_PROMINENCE_RATIO
    qualified = [
        item
        for item in result["foreground_peak_candidates"]
        if item["qualified"] is True
    ]
    assert len(qualified) >= 2
    assert result["foreground_peak_gray"] == min(item["gray"] for item in qualified)


def test_search_boundary_cannot_become_fake_foreground_peak() -> None:
    # Monotonic rise toward a background mode: old argmax(0..BG-24) logic would
    # select the right edge of the search window even though it was not a peak.
    histogram = np.zeros(256, dtype=np.float64)
    for gray in range(40, 189):
        histogram[gray] = gray - 39
    histogram[188] = 1000
    smoothed = cv2.GaussianBlur(
        histogram.reshape(-1, 1),
        (0, 0),
        sigmaX=anchor._HISTOGRAM_SMOOTH_SIGMA,
        sigmaY=0,
        borderType=cv2.BORDER_REPLICATE,
    ).reshape(-1)
    candidates = anchor._local_peak_candidates(
        histogram,
        smoothed,
        pixel_count=int(max(1, histogram.sum())),
    )
    assert not any(item["gray"] == 164 for item in candidates)


def test_tiny_dark_ripple_fails_support_filter() -> None:
    image = np.full((600, 900, 3), 200, dtype=np.uint8)
    image[10, 10] = 30
    image[20, 20] = 30
    result = anchor._histogram_anchor_thresholds(image)

    # The two dark specks must never qualify as a foreground mode. The dominant
    # gray=200 background mode may itself be a mathematically valid local peak,
    # but the unchanged 18% full anchor-population cap must then reject it.
    dark_candidates = [
        item
        for item in result.get("foreground_peak_candidates", [])
        if int(item.get("gray", 256)) <= 40
    ]
    assert dark_candidates
    assert all(item["qualified"] is False for item in dark_candidates)
    assert all(
        float(item["support_ratio"]) < anchor._MIN_LOCAL_PEAK_SUPPORT_RATIO
        for item in dark_candidates
    )
    assert result["eligible"] is False
    assert result["reason"] in {
        "no_supported_prominent_dark_local_peak",
        "hard_anchor_ratio_too_large",
        "soft_anchor_ratio_too_large",
    }


def test_low_prominence_ripple_is_not_qualified() -> None:
    # Build a smooth broad distribution with only a tiny ripple at 80. The
    # support may be nonzero, but prominence should be too small.
    histogram = np.zeros(256, dtype=np.float64)
    for gray in range(50, 121):
        histogram[gray] = 1000.0 - abs(gray - 90) * 4.0
    histogram[80] += 5.0
    smoothed = cv2.GaussianBlur(
        histogram.reshape(-1, 1),
        (0, 0),
        sigmaX=anchor._HISTOGRAM_SMOOTH_SIGMA,
        sigmaY=0,
        borderType=cv2.BORDER_REPLICATE,
    ).reshape(-1)
    candidates = anchor._local_peak_candidates(
        histogram,
        smoothed,
        pixel_count=int(histogram.sum()),
    )
    assert all(
        item["prominence_ratio"] >= anchor._MIN_LOCAL_PEAK_PROMINENCE_RATIO
        for item in candidates
        if item["qualified"] is True
    )


def test_valley_ratio_above_legacy_limit_is_diagnostic_only() -> None:
    # Two modes connected by a high shoulder. Eligibility now depends on local
    # peak support/prominence and anchor population caps, not valley<=0.80.
    image = _multi_peak_scan()
    result = anchor._histogram_anchor_thresholds(image)
    assert result["eligible"] is True
    assert result["valley_gate_role"] == "diagnostic_only"
    thresholds = result["thresholds"]
    assert thresholds["maximum_valley_to_foreground_peak_ratio"] == 0.80
