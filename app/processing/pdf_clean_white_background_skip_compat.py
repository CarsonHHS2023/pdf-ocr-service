"""Skip unnecessary OpenCV background cleanup on already-white pages and crops.

This test-only compatibility layer preserves the current geometry and semantic-gate
architecture while adding a conservative *need-to-clean* precheck.

Policy:
* Page-level background normalization is a true no-op when the rendered page has
  a large connected near-white background that also occupies the outer border
  band. Geometry remains eligible and unchanged.
* A visual crop is skipped only when its parent page was skipped for that exact
  clean-white reason and the crop itself independently satisfies the same test.
* A gray local crop inside a white page still follows the existing OpenCV ->
  catastrophic precheck -> GPT-5.6 semantic quality-gate path.
* Any failure inside this experimental precheck fails open to the pre-existing
  OpenCV path; it must never fail PDF processing.

The precheck only decides whether background cleanup should run. It never edits
content pixels, never replaces the existing semantic Judge, and never reintroduces
GPT Image or Foreground Lock.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict
import hashlib
import threading
from typing import Callable, Mapping

import cv2
import numpy as np

from app.processing import pdf_opencv_modal_bridge as opencv_bridge
from app.processing import pdf_opencv_quality_pipeline as v4

_POLICY_VERSION = "clean_white_connected_background_v1"
_PAGE_SKIP_REASON = "clean_white_background_skipped"
_CROP_SKIP_REASON = "clean_white_crop_background_skipped"
_PRECHECK_FAILURE_REASON = "clean_white_precheck_failed"
_NEAR_WHITE_THRESHOLD = 245
_MIN_NEAR_WHITE_RATIO = 0.50
_MIN_BORDER_CONNECTED_COMPONENT_RATIO = 0.45
_MIN_BORDER_NEAR_WHITE_RATIO = 0.80
_ANALYSIS_MAX_SIDE = 1000
_BORDER_FRACTION = 0.05

_PAGE_PREPROCESS_ACTIVE: ContextVar[bool] = ContextVar(
    "pdf_clean_white_page_preprocess_active", default=False
)
_PAGE_LAST_PRECHECK: ContextVar[dict[str, object] | None] = ContextVar(
    "pdf_clean_white_page_last_precheck", default=None
)
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _analysis_image(image: np.ndarray) -> np.ndarray:
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("clean-white precheck requires a BGR image")
    height, width = image.shape[:2]
    if height <= 0 or width <= 0:
        raise ValueError("clean-white precheck requires a non-empty image")
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


def _clean_white_precheck(image: np.ndarray) -> dict[str, object]:
    """Return a bounded, conservative white-background decision for one BGR image."""
    height, width = image.shape[:2] if isinstance(image, np.ndarray) and image.ndim >= 2 else (0, 0)
    analysis = _analysis_image(image)
    near_white = analysis >= _NEAR_WHITE_THRESHOLD
    pixel_count = int(near_white.size)
    near_white_count = int(np.count_nonzero(near_white))
    near_white_ratio = near_white_count / max(1, pixel_count)

    analysis_height, analysis_width = analysis.shape
    border_width = max(
        2,
        min(
            64,
            int(round(min(analysis_height, analysis_width) * _BORDER_FRACTION)),
        ),
    )
    border = np.zeros_like(near_white, dtype=bool)
    border[:border_width, :] = True
    border[-border_width:, :] = True
    border[:, :border_width] = True
    border[:, -border_width:] = True
    border_near_white_ratio = float(np.mean(near_white[border]))

    largest_component_ratio = 0.0
    largest_border_connected_component_ratio = 0.0
    if near_white_count:
        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
            near_white.astype(np.uint8),
            connectivity=8,
        )
        if component_count > 1:
            areas = stats[1:, cv2.CC_STAT_AREA]
            largest_component_ratio = float(np.max(areas) / max(1, pixel_count))
            border_labels = {
                int(label)
                for label in np.unique(labels[border])
                if int(label) > 0
            }
            if border_labels:
                largest_border_connected_component_ratio = float(
                    max(int(stats[label, cv2.CC_STAT_AREA]) for label in border_labels)
                    / max(1, pixel_count)
                )

    skip = bool(
        near_white_ratio >= _MIN_NEAR_WHITE_RATIO
        and largest_border_connected_component_ratio
        >= _MIN_BORDER_CONNECTED_COMPONENT_RATIO
        and border_near_white_ratio >= _MIN_BORDER_NEAR_WHITE_RATIO
    )
    return {
        "policy_version": _POLICY_VERSION,
        "status": "available",
        "skip_background_cleanup": skip,
        "reason": _PAGE_SKIP_REASON if skip else "background_cleanup_may_be_useful",
        "near_white_threshold": _NEAR_WHITE_THRESHOLD,
        "near_white_ratio": round(float(near_white_ratio), 6),
        "largest_near_white_component_ratio": round(
            float(largest_component_ratio), 6
        ),
        "largest_border_connected_near_white_component_ratio": round(
            float(largest_border_connected_component_ratio), 6
        ),
        "border_near_white_ratio": round(float(border_near_white_ratio), 6),
        "thresholds": {
            "min_near_white_ratio": _MIN_NEAR_WHITE_RATIO,
            "min_border_connected_near_white_component_ratio": (
                _MIN_BORDER_CONNECTED_COMPONENT_RATIO
            ),
            "min_border_near_white_ratio": _MIN_BORDER_NEAR_WHITE_RATIO,
        },
        "analysis_dimensions": [int(analysis_width), int(analysis_height)],
        "source_dimensions": [int(width), int(height)],
    }


def _failed_precheck(image: object, exc: BaseException) -> dict[str, object]:
    width = 0
    height = 0
    if isinstance(image, np.ndarray) and image.ndim >= 2:
        height, width = image.shape[:2]
    return {
        "policy_version": _POLICY_VERSION,
        "status": "failed",
        "skip_background_cleanup": False,
        "reason": _PRECHECK_FAILURE_REASON,
        "error_type": type(exc).__name__,
        "source_dimensions": [int(width), int(height)],
    }


def _safe_clean_white_precheck(image: np.ndarray) -> dict[str, object]:
    try:
        return _clean_white_precheck(image)
    except Exception as exc:
        # Failure means "do not skip". The pre-existing OpenCV path remains the
        # authority and the exception is reduced to bounded diagnostic metadata.
        return _failed_precheck(image, exc)


def _page_clean_white_skipped(page_manifest: Mapping[str, object] | None) -> bool:
    if not isinstance(page_manifest, Mapping):
        return False
    background = page_manifest.get("background")
    if not isinstance(background, Mapping):
        return False
    if background.get("accepted") is not False:
        return False
    if background.get("reason") != _PAGE_SKIP_REASON:
        return False
    precheck = background.get("precheck")
    if not isinstance(precheck, Mapping):
        gate = background.get("gate")
        if isinstance(gate, Mapping):
            precheck = gate.get("clean_white_precheck")
    return bool(
        isinstance(precheck, Mapping)
        and precheck.get("policy_version") == _POLICY_VERSION
        and precheck.get("status") == "available"
        and precheck.get("skip_background_cleanup") is True
    )


def _page_state_consistent_for_crop_retry(
    page_manifest: Mapping[str, object] | None,
) -> bool:
    if not _page_clean_white_skipped(page_manifest):
        return False
    assert isinstance(page_manifest, Mapping)
    geometry = page_manifest.get("geometry")
    if not isinstance(geometry, Mapping):
        return False
    if geometry.get("accepted") is True:
        return bool(
            page_manifest.get("route") == "geometry_only"
            and page_manifest.get("selected") == "geometry"
        )
    if geometry.get("accepted") is False:
        return bool(
            page_manifest.get("route") == "quality_gate_original"
            and page_manifest.get("selected") == "original"
        )
    return False


def _rewrite_clean_white_manifest(checksum_sha256: str) -> None:
    """Make page metadata describe a skip, not a failed cleanup attempt."""
    with v4._DIAGNOSTIC_LOCK:
        manifest = v4._DIAGNOSTIC_MANIFESTS.get(checksum_sha256)
        if not isinstance(manifest, dict):
            return
        pages = manifest.get("pages")
        if not isinstance(pages, list):
            return
        for page in pages:
            if not isinstance(page, dict):
                continue
            background = page.get("background")
            if not isinstance(background, dict):
                continue
            gate = background.get("gate")
            precheck = (
                gate.get("clean_white_precheck")
                if isinstance(gate, Mapping)
                else None
            )
            if isinstance(precheck, Mapping):
                background["precheck"] = dict(precheck)
            if background.get("reason") != _PAGE_SKIP_REASON:
                continue
            if not isinstance(precheck, Mapping):
                continue
            background["attempted"] = False
            background["accepted"] = False
            # The precheck is retained separately; no legacy quality-gate metrics
            # were computed for a true skip.
            background["gate"] = {}


def _crop_geometry_analysis(png_bytes: bytes):
    source_bgr = opencv_bridge._decode_png(png_bytes)
    color = v4._color_features(source_bgr)
    geometry_candidate, geometry_diag = v4._build_geometry_candidate(source_bgr)
    geometry_accepted, geometry_reason, geometry_gate = v4._gate_geometry_candidate(
        source_bgr,
        geometry_candidate,
        geometry_diag,
    )
    baseline = geometry_candidate if geometry_accepted else source_bgr
    return (
        source_bgr,
        color,
        geometry_candidate,
        geometry_diag,
        geometry_accepted,
        geometry_reason,
        geometry_gate,
        baseline,
    )


def _build_clean_white_crop_result(
    png_bytes: bytes,
    *,
    page_manifest: Mapping[str, object],
    precheck: Mapping[str, object],
    geometry_analysis=None,
) -> tuple[bytes, dict[str, object]]:
    """Keep crop geometry eligible while skipping only background normalization."""
    source_checksum = hashlib.sha256(png_bytes).hexdigest()
    analysis = geometry_analysis or _crop_geometry_analysis(png_bytes)
    (
        source_bgr,
        color,
        geometry_candidate,
        geometry_diag,
        geometry_accepted,
        geometry_reason,
        geometry_gate,
        _,
    ) = analysis
    selected_bgr = geometry_candidate if geometry_accepted else source_bgr
    output = opencv_bridge._encode_png(selected_bgr) if geometry_accepted else png_bytes
    selected = "geometry" if geometry_accepted else "original"
    semantic_gate = {
        "required": False,
        "invoked": False,
        "status": "clean_white_background_skipped",
        "safe_reason": _CROP_SKIP_REASON,
    }
    return output, {
        "version": "opencv_unified_quality_gate_experiment_v4",
        "scope": "modal_bbox_visual_crop",
        "source_sha256": source_checksum,
        "page_retry_eligible": True,
        "whole_page_route": page_manifest.get("route"),
        "whole_page_selected": page_manifest.get("selected"),
        "selection_policy": "opencv_candidate_semantic_gate_v1",
        "background_skip_policy": _POLICY_VERSION,
        "foreground_lock_used": False,
        "gpt_image_used": False,
        "status": "accepted" if geometry_accepted else "not_required",
        "selected": selected,
        "changed": bool(geometry_accepted),
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "opencv_candidate_sha256": None,
        "color": asdict(color),
        "geometry": {
            **asdict(geometry_diag),
            "accepted": geometry_accepted,
            "reason": geometry_reason,
            "gate": geometry_gate,
        },
        "background": {
            "attempted": False,
            "accepted": False,
            "reason": _CROP_SKIP_REASON,
            "precheck": dict(precheck),
            "gate": {},
            "catastrophic_gate": {},
            "semantic_gate": semantic_gate,
        },
        "semantic_gate": semantic_gate,
        "legacy_generated_image_path": "retired_not_installed",
    }


def _process_crop_with_policy(
    delegate: Callable,
    png_bytes: bytes,
    *,
    page_manifest: Mapping[str, object] | None,
    **kwargs,
):
    if not _page_clean_white_skipped(page_manifest):
        return delegate(png_bytes, page_manifest=page_manifest, **kwargs)
    try:
        analysis = _crop_geometry_analysis(png_bytes)
    except Exception:
        # Geometry analysis belongs to the existing path. If our look-ahead cannot
        # reproduce it, delegate immediately instead of changing failure behavior.
        return delegate(png_bytes, page_manifest=page_manifest, **kwargs)

    precheck = _safe_clean_white_precheck(analysis[-1])
    if precheck["skip_background_cleanup"] is True:
        assert isinstance(page_manifest, Mapping)
        return _build_clean_white_crop_result(
            png_bytes,
            page_manifest=page_manifest,
            precheck=precheck,
            geometry_analysis=analysis,
        )

    output, metadata = delegate(png_bytes, page_manifest=page_manifest, **kwargs)
    # Record why a gray local crop inside a white page was still eligible, or why
    # the experimental precheck itself failed open.
    if isinstance(metadata, dict):
        metadata = dict(metadata)
        metadata["background_skip_policy"] = _POLICY_VERSION
        background = metadata.get("background")
        if isinstance(background, dict):
            background = dict(background)
            background["precheck"] = dict(precheck)
            metadata["background"] = background
    return output, metadata


def _install_page_skip() -> None:
    from app.processing import pdf_geometry_integration as integration

    original_preprocess = integration.preprocess_pdf_geometry
    original_normalize = v4._normalize_background
    original_gate = v4._gate_background_candidate

    if getattr(original_preprocess, "_clean_white_background_skip", False):
        return

    def normalize_with_page_skip(image):
        if not _PAGE_PREPROCESS_ACTIVE.get():
            return original_normalize(image)
        precheck = _safe_clean_white_precheck(image)
        _PAGE_LAST_PRECHECK.set(precheck)
        if precheck["skip_background_cleanup"] is True:
            return np.ascontiguousarray(image.copy())
        return original_normalize(image)

    def gate_with_page_skip(baseline, candidate):
        if not _PAGE_PREPROCESS_ACTIVE.get():
            return original_gate(baseline, candidate)
        precheck = _PAGE_LAST_PRECHECK.get()
        _PAGE_LAST_PRECHECK.set(None)
        if not isinstance(precheck, Mapping):
            precheck = _safe_clean_white_precheck(baseline)
        if precheck.get("skip_background_cleanup") is True:
            return (
                False,
                _PAGE_SKIP_REASON,
                {"clean_white_precheck": dict(precheck)},
            )
        accepted, reason, gate = original_gate(baseline, candidate)
        gate = dict(gate)
        gate["clean_white_precheck"] = dict(precheck)
        return accepted, reason, gate

    def preprocess_with_page_skip(pdf_bytes: bytes, **kwargs):
        active_token = _PAGE_PREPROCESS_ACTIVE.set(True)
        last_token = _PAGE_LAST_PRECHECK.set(None)
        try:
            processed = original_preprocess(pdf_bytes, **kwargs)
        finally:
            _PAGE_LAST_PRECHECK.reset(last_token)
            _PAGE_PREPROCESS_ACTIVE.reset(active_token)
        try:
            _rewrite_clean_white_manifest(processed.checksum_sha256)
        except Exception:
            # Metadata enrichment is diagnostic only. Never turn a successfully
            # preprocessed PDF into a failure because the experimental rewrite failed.
            pass
        return processed

    normalize_with_page_skip._clean_white_background_skip = True  # type: ignore[attr-defined]
    gate_with_page_skip._clean_white_background_skip = True  # type: ignore[attr-defined]
    preprocess_with_page_skip._clean_white_background_skip = True  # type: ignore[attr-defined]
    v4._normalize_background = normalize_with_page_skip
    v4._gate_background_candidate = gate_with_page_skip
    v4.preprocess_pdf_geometry_opencv = preprocess_with_page_skip
    integration.preprocess_pdf_geometry = preprocess_with_page_skip


def _install_crop_retry_and_skip() -> None:
    original_retry = opencv_bridge._whole_page_rejected
    original_process = opencv_bridge.process_visual_crop_v4
    if getattr(original_process, "_clean_white_background_skip", False):
        return

    def retry_with_clean_white_page(page_manifest):
        return bool(
            original_retry(page_manifest)
            or _page_state_consistent_for_crop_retry(page_manifest)
        )

    def process_with_clean_white_crop(png_bytes: bytes, *, page_manifest, **kwargs):
        return _process_crop_with_policy(
            original_process,
            png_bytes,
            page_manifest=page_manifest,
            **kwargs,
        )

    retry_with_clean_white_page._clean_white_background_skip = True  # type: ignore[attr-defined]
    process_with_clean_white_crop._clean_white_background_skip = True  # type: ignore[attr-defined]
    opencv_bridge._whole_page_rejected = retry_with_clean_white_page
    opencv_bridge.process_visual_crop_v4 = process_with_clean_white_crop


def install_pdf_clean_white_background_skip_compat() -> None:
    """Install conservative page/crop clean-white background skipping."""
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _install_page_skip()
        _install_crop_retry_and_skip()
        _INSTALLED = True


__all__ = ["install_pdf_clean_white_background_skip_compat"]
