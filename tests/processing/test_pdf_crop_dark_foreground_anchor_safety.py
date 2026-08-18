from __future__ import annotations

import numpy as np

from app.processing import pdf_crop_dark_foreground_anchor_compat as anchor


def test_full_resolution_anchor_cap_blocks_underestimated_dense_mask(monkeypatch) -> None:
    baseline = np.full((300, 600, 3), 210, dtype=np.uint8)
    baseline[:, :180] = 80  # 30% of full-resolution pixels are dark.
    candidate = np.full_like(baseline, 240)

    # Simulate a downsampled analysis that underestimated the real dark population.
    monkeypatch.setattr(
        anchor,
        "_histogram_anchor_thresholds",
        lambda image: {
            "policy_version": anchor._POLICY_VERSION,
            "eligible": True,
            "reason": "eligible",
            "hard_threshold_gray": 80,
            "soft_threshold_gray": 92,
            "analysis_hard_anchor_ratio": 0.10,
            "analysis_soft_anchor_ratio": 0.12,
            "diagnostic_candidate_stage": "raw_opencv_before_dark_anchor",
        },
    )

    restored, diagnostics = anchor._restore_dark_foreground(baseline, candidate)
    assert diagnostics["applied"] is False
    assert diagnostics["reason"] == "full_resolution_anchor_ratio_out_of_bounds"
    assert diagnostics["full_resolution_hard_anchor_ratio"] == 0.3
    assert diagnostics["full_resolution_soft_anchor_ratio"] == 0.3
    assert np.array_equal(restored, candidate)


def test_full_resolution_caps_bound_actual_anchor_population() -> None:
    baseline = np.full((400, 800, 3), 210, dtype=np.uint8)
    baseline[50:110, 80:720] = 80  # 12% hard foreground block.
    baseline[120:150, 80:720] = 88  # 6% soft-band content.
    candidate = baseline.copy()
    candidate[baseline <= 100] = np.clip(candidate[baseline <= 100].astype(np.int16) + 50, 0, 255)

    restored, diagnostics = anchor._restore_dark_foreground(baseline, candidate)
    assert diagnostics["eligible"] is True
    assert diagnostics["applied"] is True
    assert diagnostics["full_resolution_hard_anchor_ratio"] <= anchor._MAX_HARD_ANCHOR_RATIO
    assert diagnostics["full_resolution_soft_anchor_ratio"] <= anchor._MAX_SOFT_ANCHOR_RATIO
    assert diagnostics["hard_restored_pixel_ratio"] <= anchor._MAX_HARD_ANCHOR_RATIO
    assert diagnostics["soft_blended_pixel_ratio"] <= anchor._MAX_SOFT_ANCHOR_RATIO
