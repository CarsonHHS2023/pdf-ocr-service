"""Crop-only dark-foreground anchor restoration for OpenCV background cleanup.

This test-only layer is deliberately much narrower than the retired Foreground
Lock pipeline. It does not classify edges, connected components, table lines, or
uncertain foreground. While the crop semantic path is active it locates the
*darkest statistically meaningful local histogram peak* in the aligned
pre-cleanup baseline, restores that mode and darker pixels only where OpenCV
materially lightened them, and softly blends a small band above the mode for
antialiased stroke edges.

Foreground selection is intentionally independent of the paper/background peak.
A candidate local peak must have enough raw-pixel support and enough local
prominence to avoid treating tiny histogram ripples as foreground. Background
peak and foreground/background valley measurements remain diagnostic-only.

The layer is crop-only through a ContextVar. Page-level OpenCV normalization is
unchanged. It is installed outside the existing candidate-retention wrapper, so
the retained downloadable diagnostic remains the raw OpenCV result while the
semantic Judge receives the anchor-restored candidate. Clean-white crops never
invoke background normalization, so no anchor restoration runs for them. Any
analysis/restoration failure is fail-open to the raw OpenCV candidate.
"""
from __future__ import annotations

from contextvars import ContextVar
import hashlib
import threading
from typing import Mapping

import cv2
import numpy as np

from app.processing import pdf_crop_dark_foreground_anchor_diagnostics_compat as histogram_diagnostics
from app.processing import pdf_opencv_modal_bridge as opencv_bridge
from app.processing import pdf_opencv_quality_pipeline as v4

_POLICY_VERSION = "dark_foreground_anchor_lock_v2_local_peak"
_ANALYSIS_MAX_SIDE = 1200
_HISTOGRAM_SMOOTH_SIGMA = 2.0
_BACKGROUND_SEARCH_MIN_GRAY = 128
# Saturated white margins/captions can be a larger histogram mode than the gray
# paper region. Background selection is diagnostic-only, and true clean-white
# crops are already owned by clean-white routing, so 248..255 remains excluded.
_BACKGROUND_SEARCH_MAX_GRAY = 247

# Local-peak foreground selection. These values are intentionally conservative:
# support is measured on *raw* histogram mass around a candidate, while
# prominence is measured on the smoothed histogram against nearby saddles.
_LOCAL_PEAK_NEIGHBORHOOD_RADIUS = 3
_LOCAL_PEAK_SUPPORT_RADIUS = 4
_LOCAL_PEAK_PROMINENCE_RADIUS = 16
_MIN_LOCAL_PEAK_SUPPORT_RATIO = 0.0010
_MIN_LOCAL_PEAK_PROMINENCE_RATIO = 0.08
_MAX_LOCAL_PEAK_DIAGNOSTIC_COUNT = 16

# Kept only as diagnostic references for historical comparison. Neither value
# participates in foreground-peak selection or eligibility in v2.
_MIN_PEAK_SEPARATION = 24
_VALLEY_MARGIN = 4
_MAX_VALLEY_TO_FOREGROUND_PEAK = 0.80

_MIN_FOREGROUND_PEAK_DENSITY = 0.00010
_MIN_HARD_ANCHOR_RATIO = 0.00020
_MAX_HARD_ANCHOR_RATIO = 0.18
_MAX_SOFT_ANCHOR_RATIO = 0.25
_SOFT_BAND_WIDTH = 12
_MIN_LIGHTENING_DELTA = 3

_CURRENT_ANCHOR_STATE: ContextVar[dict[str, object] | None] = ContextVar(
    "pdf_crop_dark_foreground_anchor_state", default=None
)
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _analysis_gray(image: np.ndarray) -> np.ndarray:
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("dark foreground anchor requires a BGR image")
    height, width = image.shape[:2]
    if height <= 0 or width <= 0:
        raise ValueError("dark foreground anchor requires a non-empty image")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scale = min(1.0, _ANALYSIS_MAX_SIDE / float(max(height, width)))
    if scale >= 1.0:
        return np.ascontiguousarray(gray)
    return np.ascontiguousarray(
        cv2.resize(
            gray,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA,
        )
    )


def _base_diagnostics(analysis: np.ndarray) -> dict[str, object]:
    return {
        "policy_version": _POLICY_VERSION,
        "analysis_dimensions": [int(analysis.shape[1]), int(analysis.shape[0])],
        "diagnostic_candidate_stage": "raw_opencv_before_dark_anchor",
        "histogram_source_stage": "baseline_before_opencv_background_cleanup",
        "foreground_selection": "darkest_qualified_local_peak",
        "valley_gate_role": "diagnostic_only",
        "thresholds": {
            "background_search_min_gray": _BACKGROUND_SEARCH_MIN_GRAY,
            "background_search_max_gray": _BACKGROUND_SEARCH_MAX_GRAY,
            "minimum_peak_separation_gray_diagnostic_only": _MIN_PEAK_SEPARATION,
            "maximum_valley_to_foreground_peak_ratio_diagnostic_only": _MAX_VALLEY_TO_FOREGROUND_PEAK,
            # Keep the legacy key for plot/backward-compatible readers while
            # explicitly marking its role above as diagnostic-only.
            "maximum_valley_to_foreground_peak_ratio": _MAX_VALLEY_TO_FOREGROUND_PEAK,
            "local_peak_neighborhood_radius_gray": _LOCAL_PEAK_NEIGHBORHOOD_RADIUS,
            "local_peak_support_radius_gray": _LOCAL_PEAK_SUPPORT_RADIUS,
            "local_peak_prominence_radius_gray": _LOCAL_PEAK_PROMINENCE_RADIUS,
            "minimum_local_peak_support_ratio": _MIN_LOCAL_PEAK_SUPPORT_RATIO,
            "minimum_local_peak_prominence_ratio": _MIN_LOCAL_PEAK_PROMINENCE_RATIO,
            "minimum_foreground_peak_density": _MIN_FOREGROUND_PEAK_DENSITY,
            "minimum_hard_anchor_ratio": _MIN_HARD_ANCHOR_RATIO,
            "maximum_hard_anchor_ratio": _MAX_HARD_ANCHOR_RATIO,
            "maximum_soft_anchor_ratio": _MAX_SOFT_ANCHOR_RATIO,
            "soft_band_width_gray": _SOFT_BAND_WIDTH,
            "minimum_lightening_delta": _MIN_LIGHTENING_DELTA,
        },
    }


def _local_peak_candidates(
    histogram: np.ndarray,
    smoothed: np.ndarray,
    *,
    pixel_count: int,
) -> list[dict[str, object]]:
    """Return local maxima from dark to bright with support/prominence evidence."""
    candidates: list[dict[str, object]] = []
    radius = _LOCAL_PEAK_NEIGHBORHOOD_RADIUS
    for gray in range(radius, 256 - radius):
        center = float(smoothed[gray])
        if center <= 0.0:
            continue
        left = smoothed[gray - radius : gray]
        right = smoothed[gray + 1 : gray + radius + 1]
        if left.size == 0 or right.size == 0:
            continue
        if center < float(np.max(left)) or center < float(np.max(right)):
            continue
        # Reject a perfectly flat plateau; one side must genuinely fall away.
        if center <= float(np.min(left)) and center <= float(np.min(right)):
            continue

        support_start = max(0, gray - _LOCAL_PEAK_SUPPORT_RADIUS)
        support_end = min(255, gray + _LOCAL_PEAK_SUPPORT_RADIUS)
        support_ratio = float(
            np.sum(histogram[support_start : support_end + 1]) / max(1, pixel_count)
        )

        prominence_start = max(0, gray - _LOCAL_PEAK_PROMINENCE_RADIUS)
        prominence_end = min(255, gray + _LOCAL_PEAK_PROMINENCE_RADIUS)
        left_prominence_window = smoothed[prominence_start:gray]
        right_prominence_window = smoothed[gray + 1 : prominence_end + 1]
        if left_prominence_window.size == 0 or right_prominence_window.size == 0:
            continue
        saddle = max(
            float(np.min(left_prominence_window)),
            float(np.min(right_prominence_window)),
        )
        prominence = max(0.0, center - saddle)
        prominence_ratio = float(prominence / max(center, 1e-12))
        peak_density = float(center / max(1, pixel_count))
        qualified = bool(
            support_ratio >= _MIN_LOCAL_PEAK_SUPPORT_RATIO
            and prominence_ratio >= _MIN_LOCAL_PEAK_PROMINENCE_RATIO
            and peak_density >= _MIN_FOREGROUND_PEAK_DENSITY
        )
        candidates.append(
            {
                "gray": int(gray),
                "qualified": qualified,
                "support_ratio": round(support_ratio, 8),
                "prominence_ratio": round(prominence_ratio, 6),
                "peak_density": round(peak_density, 8),
            }
        )
    return candidates


def _histogram_anchor_thresholds(image: np.ndarray) -> dict[str, object]:
    """Select the darkest supported/prominent local histogram peak as foreground."""
    analysis = _analysis_gray(image)
    base = _base_diagnostics(analysis)
    histogram = np.bincount(analysis.ravel(), minlength=256).astype(np.float64)
    smoothed = cv2.GaussianBlur(
        histogram.reshape(-1, 1),
        (0, 0),
        sigmaX=_HISTOGRAM_SMOOTH_SIGMA,
        sigmaY=0,
        borderType=cv2.BORDER_REPLICATE,
    ).reshape(-1)
    pixel_count = int(analysis.size)

    def finalize(extra: Mapping[str, object]) -> dict[str, object]:
        result = {**base, **dict(extra)}
        try:
            result["histogram_diagnostic"] = histogram_diagnostics.capture_histogram_diagnostic(
                histogram,
                smoothed,
                result,
            )
        except Exception as exc:
            # Diagnostic code must never change the anchor decision.
            result["histogram_diagnostic"] = {
                "status": "generation_failed",
                "source_stage": "baseline_before_opencv_background_cleanup",
                "error_type": type(exc).__name__,
            }
        return result

    # Background peak is retained solely to make the diagnostic plot easier to
    # understand. It is never used to define the FG search range or eligibility.
    background_start = max(0, min(255, _BACKGROUND_SEARCH_MIN_GRAY))
    background_end = max(background_start, min(255, _BACKGROUND_SEARCH_MAX_GRAY))
    background_window = smoothed[background_start : background_end + 1]
    background_peak: int | None = None
    if background_window.size and float(np.max(background_window)) > 0.0:
        background_peak = background_start + int(np.argmax(background_window))

    candidates = _local_peak_candidates(
        histogram,
        smoothed,
        pixel_count=pixel_count,
    )
    qualified = [item for item in candidates if item.get("qualified") is True]
    diagnostic_candidates = candidates[:_MAX_LOCAL_PEAK_DIAGNOSTIC_COUNT]
    if not qualified:
        return finalize(
            {
                "eligible": False,
                "reason": "no_supported_prominent_dark_local_peak",
                "background_peak_gray": background_peak,
                "foreground_peak_candidate_count": len(candidates),
                "qualified_foreground_peak_candidate_count": 0,
                "foreground_peak_candidates": diagnostic_candidates,
            }
        )

    selected = qualified[0]
    foreground_peak = int(selected["gray"])
    peak_density = float(selected["peak_density"])
    support_ratio = float(selected["support_ratio"])
    prominence_ratio = float(selected["prominence_ratio"])

    valley_gray: int | None = None
    valley_ratio: float | None = None
    separation: int | None = None
    if background_peak is not None:
        separation = int(background_peak - foreground_peak)
        valley_start = foreground_peak + _VALLEY_MARGIN
        valley_end = background_peak - _VALLEY_MARGIN
        if valley_end > valley_start:
            valley_window = smoothed[valley_start:valley_end]
            if valley_window.size:
                valley_offset = int(np.argmin(valley_window))
                valley_gray = int(valley_start + valley_offset)
                valley_height = float(valley_window[valley_offset])
                foreground_height = float(smoothed[foreground_peak])
                valley_ratio = float(
                    valley_height / max(foreground_height, 1e-12)
                )

    hard_threshold = foreground_peak
    soft_threshold = int(min(255, hard_threshold + _SOFT_BAND_WIDTH))
    hard_ratio = float(np.mean(analysis <= hard_threshold))
    soft_ratio = float(np.mean(analysis <= soft_threshold))

    reason = "eligible"
    eligible = True
    if hard_ratio < _MIN_HARD_ANCHOR_RATIO:
        eligible = False
        reason = "hard_anchor_too_sparse"
    elif hard_ratio > _MAX_HARD_ANCHOR_RATIO:
        eligible = False
        reason = "hard_anchor_ratio_too_large"
    elif soft_ratio > _MAX_SOFT_ANCHOR_RATIO:
        eligible = False
        reason = "soft_anchor_ratio_too_large"
    elif soft_threshold <= hard_threshold:
        eligible = False
        reason = "soft_anchor_band_unavailable"

    return finalize(
        {
            "eligible": bool(eligible),
            "reason": reason,
            "background_peak_gray": background_peak,
            "foreground_peak_gray": foreground_peak,
            "foreground_peak_candidate_count": len(candidates),
            "qualified_foreground_peak_candidate_count": len(qualified),
            "foreground_peak_candidates": diagnostic_candidates,
            "selected_foreground_peak_support_ratio": round(support_ratio, 8),
            "selected_foreground_peak_prominence_ratio": round(prominence_ratio, 6),
            "valley_gray": valley_gray,
            "peak_separation_gray": separation,
            "foreground_peak_density": round(peak_density, 8),
            "valley_to_foreground_peak_ratio": (
                round(valley_ratio, 6) if valley_ratio is not None else None
            ),
            "hard_threshold_gray": hard_threshold,
            "soft_threshold_gray": soft_threshold,
            "analysis_hard_anchor_ratio": round(hard_ratio, 6),
            "analysis_soft_anchor_ratio": round(soft_ratio, 6),
            "hard_anchor_ratio": round(hard_ratio, 6),
            "soft_anchor_ratio": round(soft_ratio, 6),
        }
    )


def _restore_dark_foreground(
    baseline: np.ndarray,
    candidate: np.ndarray,
) -> tuple[np.ndarray, dict[str, object]]:
    """Restore dark baseline anchors only where cleanup materially lightened them."""
    if baseline.shape != candidate.shape:
        raise ValueError("dark foreground anchor requires aligned equal-size images")
    thresholds = _histogram_anchor_thresholds(baseline)
    if thresholds.get("eligible") is not True:
        return np.ascontiguousarray(candidate), {
            **thresholds,
            "applied": False,
            "status": "not_applied",
        }

    hard_threshold = int(thresholds["hard_threshold_gray"])
    soft_threshold = int(thresholds["soft_threshold_gray"])
    baseline_gray = cv2.cvtColor(baseline, cv2.COLOR_BGR2GRAY).astype(np.int16)
    candidate_gray = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY).astype(np.int16)
    pixel_count = int(baseline_gray.size)

    # Re-check actual full-resolution population. Downsampling can under-count
    # dense 1px structures; the real masks are never allowed to exceed these caps.
    full_hard_anchor = baseline_gray <= hard_threshold
    full_soft_anchor = baseline_gray <= soft_threshold
    full_hard_ratio = float(np.mean(full_hard_anchor))
    full_soft_ratio = float(np.mean(full_soft_anchor))
    full_ratio_metrics = {
        "full_resolution_hard_anchor_ratio": round(full_hard_ratio, 6),
        "full_resolution_soft_anchor_ratio": round(full_soft_ratio, 6),
    }
    if (
        full_hard_ratio < _MIN_HARD_ANCHOR_RATIO
        or full_hard_ratio > _MAX_HARD_ANCHOR_RATIO
        or full_soft_ratio > _MAX_SOFT_ANCHOR_RATIO
    ):
        return np.ascontiguousarray(candidate), {
            **thresholds,
            **full_ratio_metrics,
            "applied": False,
            "status": "not_applied",
            "reason": "full_resolution_anchor_ratio_out_of_bounds",
        }

    lightening = candidate_gray - baseline_gray
    material_lightening = lightening >= _MIN_LIGHTENING_DELTA
    hard_mask = full_hard_anchor & material_lightening
    soft_mask = (
        (baseline_gray > hard_threshold)
        & full_soft_anchor
        & material_lightening
    )
    hard_count = int(np.count_nonzero(hard_mask))
    soft_count = int(np.count_nonzero(soft_mask))
    if hard_count == 0 and soft_count == 0:
        return np.ascontiguousarray(candidate), {
            **thresholds,
            **full_ratio_metrics,
            "applied": False,
            "status": "not_applied",
            "reason": "no_material_anchor_lightening",
            "hard_restored_pixel_count": 0,
            "hard_restored_pixel_ratio": 0.0,
            "soft_blended_pixel_count": 0,
            "soft_blended_pixel_ratio": 0.0,
        }

    output = candidate.astype(np.float32).copy()
    if hard_count:
        output[hard_mask] = baseline[hard_mask].astype(np.float32)
    if soft_count:
        baseline_soft_gray = baseline_gray[soft_mask].astype(np.float32)
        weight = (
            (float(soft_threshold) - baseline_soft_gray)
            / max(1.0, float(soft_threshold - hard_threshold))
        )
        weight = np.clip(weight, 0.0, 1.0).reshape(-1, 1)
        original_values = baseline[soft_mask].astype(np.float32)
        candidate_values = candidate[soft_mask].astype(np.float32)
        output[soft_mask] = weight * original_values + (1.0 - weight) * candidate_values

    output = np.clip(np.rint(output), 0, 255).astype(np.uint8)
    raw_candidate_png = opencv_bridge._encode_png(candidate)
    anchored_candidate_png = opencv_bridge._encode_png(output)
    return np.ascontiguousarray(output), {
        **thresholds,
        **full_ratio_metrics,
        "applied": True,
        "status": "applied",
        "reason": "dark_foreground_anchor_restored",
        "semantic_candidate_stage": "dark_foreground_anchor_restored",
        "hard_restored_pixel_count": hard_count,
        "hard_restored_pixel_ratio": round(hard_count / max(1, pixel_count), 6),
        "soft_blended_pixel_count": soft_count,
        "soft_blended_pixel_ratio": round(soft_count / max(1, pixel_count), 6),
        "raw_candidate_sha256": hashlib.sha256(raw_candidate_png).hexdigest(),
        "anchored_candidate_sha256": hashlib.sha256(anchored_candidate_png).hexdigest(),
    }


def _public_state(state: Mapping[str, object]) -> dict[str, object]:
    return dict(state)


def _install_crop_context() -> None:
    original = opencv_bridge.process_visual_crop_v4
    if getattr(original, "_pdf_crop_dark_foreground_anchor", False):
        return

    def process_with_dark_foreground_anchor(
        png_bytes: bytes,
        *,
        page_manifest: Mapping[str, object] | None,
        **kwargs,
    ):
        state: dict[str, object] = {
            "policy_version": _POLICY_VERSION,
            "applied": False,
            "status": "not_attempted",
            "reason": "background_normalization_not_invoked",
        }
        token = _CURRENT_ANCHOR_STATE.set(state)
        try:
            output, metadata = original(
                png_bytes,
                page_manifest=page_manifest,
                **kwargs,
            )
        finally:
            _CURRENT_ANCHOR_STATE.reset(token)

        if isinstance(metadata, dict) and state.get("status") != "not_attempted":
            metadata = dict(metadata)
            background = metadata.get("background")
            if isinstance(background, Mapping):
                updated_background = dict(background)
                updated_background["dark_foreground_anchor_lock"] = _public_state(state)
                metadata["background"] = updated_background
            if state.get("applied") is True:
                raw_sha = state.get("raw_candidate_sha256")
                anchored_sha = state.get("anchored_candidate_sha256")
                if isinstance(raw_sha, str):
                    metadata["opencv_raw_candidate_sha256"] = raw_sha
                if isinstance(anchored_sha, str):
                    metadata["opencv_candidate_stage"] = "dark_foreground_anchor_restored"
        return output, metadata

    process_with_dark_foreground_anchor._pdf_crop_dark_foreground_anchor = True  # type: ignore[attr-defined]
    opencv_bridge.process_visual_crop_v4 = process_with_dark_foreground_anchor


def _install_normalizer_wrapper() -> None:
    original = v4._normalize_background
    if getattr(original, "_pdf_crop_dark_foreground_anchor", False):
        return

    def normalize_with_dark_foreground_anchor(image: np.ndarray) -> np.ndarray:
        candidate = original(image)
        state = _CURRENT_ANCHOR_STATE.get()
        if state is None:
            return candidate
        try:
            restored, diagnostics = _restore_dark_foreground(image, candidate)
        except Exception as exc:
            state.clear()
            state.update(
                {
                    "policy_version": _POLICY_VERSION,
                    "applied": False,
                    "status": "analysis_failed",
                    "reason": "dark_foreground_anchor_failed_open",
                    "error_type": type(exc).__name__,
                    "diagnostic_candidate_stage": "raw_opencv_before_dark_anchor",
                }
            )
            return candidate
        state.clear()
        state.update(diagnostics)
        return restored

    normalize_with_dark_foreground_anchor._pdf_crop_dark_foreground_anchor = True  # type: ignore[attr-defined]
    v4._normalize_background = normalize_with_dark_foreground_anchor


def _install_histogram_diagnostics_without_routes() -> None:
    """Install only diagnostic context/persistence; HTTP routing is static."""
    with histogram_diagnostics._INSTALL_LOCK:
        if histogram_diagnostics._INSTALLED:
            return
        histogram_diagnostics._install_context()
        histogram_diagnostics._install_persistence()
        histogram_diagnostics._INSTALLED = True


def install_pdf_crop_dark_foreground_anchor_compat() -> None:
    """Install crop-only dark foreground restoration before semantic review."""
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _install_crop_context()
        _install_normalizer_wrapper()
        try:
            _install_histogram_diagnostics_without_routes()
        except Exception:
            # Histogram diagnostics are optional and must not prevent anchor install.
            pass
        _INSTALLED = True


__all__ = ["install_pdf_crop_dark_foreground_anchor_compat"]
