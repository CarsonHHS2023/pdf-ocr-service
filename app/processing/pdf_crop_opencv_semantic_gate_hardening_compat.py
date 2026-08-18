"""Hardening for the test-only OpenCV semantic crop gate.

This layer keeps the new OpenCV -> GPT-5.6 decision architecture but tightens the
review boundary:

* difference/ROI evidence is bounded by pixel dimensions and encoded bytes;
* tiny foreground/structural changes are prioritized over page-wide background
  changes when selecting ROI panels;
* the Judge sees raw legacy measurements, not the legacy gate's accept/reject
  verdict or reason;
* the difference-map legend is explicit; and
* provider credentials are never sent to a non-HTTPS base URL.

The layer does not import or install the retired GPT Image / Foreground Lock path.
"""
from __future__ import annotations

import math
import os
import threading
from typing import Any, Mapping
from urllib.parse import urlparse

import cv2
import numpy as np

from app.processing import pdf_crop_opencv_semantic_gate_compat as gate
from app.processing import pdf_opencv_modal_bridge as opencv_bridge

_MAX_DIFFERENCE_SIDE = 1280
_MAX_DIFFERENCE_BYTES = 768 * 1024
_MAX_PANEL_WIDTH = 1536
_MAX_PANEL_HEIGHT = 768
_MAX_PANEL_BYTES = 512 * 1024
_MAX_TOTAL_PANEL_BYTES = 2 * 1024 * 1024
_MAX_ROI_UPSCALE = 8.0
_SEPARATOR_WIDTH = 6
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _fit_dimensions(
    width: int,
    height: int,
    max_width: int,
    max_height: int,
) -> tuple[int, int]:
    if width <= max_width and height <= max_height:
        return width, height
    scale = min(max_width / max(1, width), max_height / max(1, height))
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def _resize(image: np.ndarray, width: int, height: int) -> np.ndarray:
    if image.shape[1] == width and image.shape[0] == height:
        return np.ascontiguousarray(image)
    interpolation = (
        cv2.INTER_AREA
        if width < image.shape[1] or height < image.shape[0]
        else cv2.INTER_NEAREST
    )
    return np.ascontiguousarray(
        cv2.resize(image, (width, height), interpolation=interpolation)
    )


def _encode_png_bounded(
    image: np.ndarray,
    *,
    max_width: int,
    max_height: int,
    max_bytes: int,
) -> tuple[bytes, tuple[int, int]]:
    width, height = _fit_dimensions(
        image.shape[1], image.shape[0], max_width, max_height
    )
    current = _resize(image, width, height)
    while True:
        ok, encoded = cv2.imencode(
            ".png",
            current,
            [cv2.IMWRITE_PNG_COMPRESSION, 6],
        )
        if not ok:
            raise ValueError("failed to encode bounded PNG evidence")
        data = encoded.tobytes()
        if len(data) <= max_bytes or min(current.shape[:2]) <= 48:
            return data, (current.shape[1], current.shape[0])
        next_width = max(1, int(math.floor(current.shape[1] * 0.82)))
        next_height = max(1, int(math.floor(current.shape[0] * 0.82)))
        if next_width == current.shape[1] and next_height == current.shape[0]:
            return data, (current.shape[1], current.shape[0])
        current = _resize(current, next_width, next_height)


def _foreground_change_masks(
    before: np.ndarray,
    after: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return review-priority foreground and broader structural change masks.

    These masks are evidence-selection hints only. They never protect, composite,
    or alter output pixels and are deliberately independent of Foreground Lock.
    """
    before_gray = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY).astype(np.float32)
    after_gray = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY).astype(np.float32)
    height, width = before_gray.shape
    sigma = max(4.0, min(height, width) / 35.0)
    before_local = cv2.GaussianBlur(
        before_gray,
        (0, 0),
        sigmaX=sigma,
        sigmaY=sigma,
        borderType=cv2.BORDER_REPLICATE,
    )
    after_local = cv2.GaussianBlur(
        after_gray,
        (0, 0),
        sigmaX=sigma,
        sigmaY=sigma,
        borderType=cv2.BORDER_REPLICATE,
    )

    before_residual = before_local - before_gray
    after_residual = after_local - after_gray
    before_structure = (before_residual >= 14.0) | (before_gray <= 120.0)
    after_structure = (after_residual >= 14.0) | (after_gray <= 120.0)
    structure_union = before_structure | after_structure
    structure_xor = before_structure ^ after_structure

    before_lab = cv2.cvtColor(before, cv2.COLOR_BGR2LAB).astype(np.float32)
    after_lab = cv2.cvtColor(after, cv2.COLOR_BGR2LAB).astype(np.float32)
    ab_delta = np.sqrt(
        (before_lab[:, :, 1] - after_lab[:, :, 1]) ** 2
        + (before_lab[:, :, 2] - after_lab[:, :, 2]) ** 2
    )
    structure_color_changed = (ab_delta >= 8.0) & structure_union
    residual_changed = (
        np.abs(before_residual - after_residual) >= 10.0
    ) & structure_union

    priority = structure_xor | structure_color_changed
    structural = priority | residual_changed
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    priority = cv2.morphologyEx(
        priority.astype(np.uint8), cv2.MORPH_OPEN, kernel
    ) > 0
    structural = cv2.morphologyEx(
        structural.astype(np.uint8), cv2.MORPH_OPEN, kernel
    ) > 0
    return priority, structural


def _component_boxes(
    mask: np.ndarray,
    *,
    minimum_area: int,
) -> list[tuple[int, int, int, int, int]]:
    clustered = cv2.dilate(
        mask.astype(np.uint8),
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        iterations=1,
    )
    count, _, stats, _ = cv2.connectedComponentsWithStats(clustered, 8)
    boxes: list[tuple[int, int, int, int, int]] = []
    for label in range(1, count):
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        width = int(stats[label, cv2.CC_STAT_WIDTH])
        height = int(stats[label, cv2.CC_STAT_HEIGHT])
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area >= minimum_area:
            boxes.append((area, x, y, width, height))
    boxes.sort(reverse=True)
    return boxes


def _overlap_fraction(
    a: tuple[int, int, int, int, int],
    b: tuple[int, int, int, int, int],
) -> float:
    _, ax, ay, aw, ah = a
    _, bx, by, bw, bh = b
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    intersection = float((x1 - x0) * (y1 - y0))
    smaller = float(max(1, min(aw * ah, bw * bh)))
    return intersection / smaller


def _prioritized_boxes(
    priority: np.ndarray,
    structural: np.ndarray,
    *,
    maximum: int,
) -> list[tuple[str, tuple[int, int, int, int, int]]]:
    image_area = priority.size
    priority_boxes = _component_boxes(
        priority,
        minimum_area=max(4, int(round(image_area * 0.000002))),
    )
    structural_boxes = _component_boxes(
        structural,
        minimum_area=max(6, int(round(image_area * 0.000004))),
    )
    selected: list[tuple[str, tuple[int, int, int, int, int]]] = []
    for box in priority_boxes:
        if len(selected) >= maximum:
            break
        selected.append(("foreground_priority", box))
    for box in structural_boxes:
        if len(selected) >= maximum:
            break
        if any(_overlap_fraction(box, chosen) >= 0.50 for _, chosen in selected):
            continue
        selected.append(("structural_residual", box))
    return selected


def _bounded_change_evidence(
    baseline_png: bytes,
    candidate_png: bytes,
    *,
    max_rois: int = gate._DEFAULT_MAX_CHANGE_ROIS,
) -> tuple[bytes, tuple[bytes, ...], dict[str, object]]:
    before = gate._decode_png(baseline_png)
    after = gate._decode_png(candidate_png)
    if before.shape != after.shape:
        raise ValueError("difference evidence requires aligned equal-size images")

    delta = np.max(cv2.absdiff(before, after), axis=2).astype(np.uint8)
    changed = delta >= 8
    changed_ratio = float(np.mean(changed))
    changed_count = int(np.count_nonzero(changed))

    # White means unchanged; increasingly dark means larger absolute difference.
    visual = 255 - np.minimum(delta.astype(np.uint16) * 4, 255).astype(np.uint8)
    difference_png, difference_dimensions = _encode_png_bounded(
        cv2.cvtColor(visual, cv2.COLOR_GRAY2BGR),
        max_width=_MAX_DIFFERENCE_SIDE,
        max_height=_MAX_DIFFERENCE_SIDE,
        max_bytes=_MAX_DIFFERENCE_BYTES,
    )

    priority, structural = _foreground_change_masks(before, after)
    priority &= changed
    structural &= changed
    maximum = max(0, min(int(max_rois), gate._DEFAULT_MAX_CHANGE_ROIS))
    boxes = _prioritized_boxes(priority, structural, maximum=maximum)

    image_height, image_width = changed.shape
    maximum_cell_width = max(
        1, (_MAX_PANEL_WIDTH - 2 * _SEPARATOR_WIDTH) // 3
    )
    panels: list[bytes] = []
    summaries: list[dict[str, object]] = []
    total_panel_bytes = 0
    truncated_by_payload = False

    for kind, (area, x, y, width, height) in boxes:
        pad = max(4, min(24, max(width, height) // 4))
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1 = min(image_width, x + width + pad)
        y1 = min(image_height, y + height + pad)
        before_roi = before[y0:y1, x0:x1]
        after_roi = after[y0:y1, x0:x1]
        diff_roi = cv2.cvtColor(
            visual[y0:y1, x0:x1], cv2.COLOR_GRAY2BGR
        )
        roi_height, roi_width = before_roi.shape[:2]
        if roi_height <= 0 or roi_width <= 0:
            continue

        desired_scale = max(
            1.0, min(_MAX_ROI_UPSCALE, 128.0 / max(1, roi_height))
        )
        fit_scale = min(
            maximum_cell_width / max(1, roi_width),
            _MAX_PANEL_HEIGHT / max(1, roi_height),
        )
        scale = min(desired_scale, fit_scale)
        target_width = max(1, int(round(roi_width * scale)))
        target_height = max(1, int(round(roi_height * scale)))
        before_big = _resize(before_roi, target_width, target_height)
        after_big = _resize(after_roi, target_width, target_height)
        diff_big = _resize(diff_roi, target_width, target_height)
        separator = np.full(
            (target_height, _SEPARATOR_WIDTH, 3), 255, dtype=np.uint8
        )
        panel = np.concatenate(
            (before_big, separator, after_big, separator, diff_big), axis=1
        )
        panel_png, panel_dimensions = _encode_png_bounded(
            panel,
            max_width=_MAX_PANEL_WIDTH,
            max_height=_MAX_PANEL_HEIGHT,
            max_bytes=_MAX_PANEL_BYTES,
        )
        if total_panel_bytes + len(panel_png) > _MAX_TOTAL_PANEL_BYTES:
            truncated_by_payload = True
            break
        panels.append(panel_png)
        total_panel_bytes += len(panel_png)
        summaries.append(
            {
                "kind": kind,
                "bbox": [x0, y0, x1, y1],
                "cluster_area": area,
                "changed_pixels": int(
                    np.count_nonzero(changed[y0:y1, x0:x1])
                ),
                "priority_changed_pixels": int(
                    np.count_nonzero(priority[y0:y1, x0:x1])
                ),
                "structural_changed_pixels": int(
                    np.count_nonzero(structural[y0:y1, x0:x1])
                ),
                "panel_dimensions": list(panel_dimensions),
                "panel_bytes": len(panel_png),
                "source_roi_dimensions": [roi_width, roi_height],
            }
        )

    return difference_png, tuple(panels), {
        "changed_pixel_ratio": round(changed_ratio, 6),
        "changed_pixel_count": changed_count,
        "priority_changed_pixel_count": int(np.count_nonzero(priority)),
        "priority_changed_pixel_ratio": round(float(np.mean(priority)), 6),
        "structural_changed_pixel_count": int(np.count_nonzero(structural)),
        "structural_changed_pixel_ratio": round(float(np.mean(structural)), 6),
        "roi_count": len(panels),
        "rois": summaries,
        "difference_dimensions": list(difference_dimensions),
        "difference_bytes": len(difference_png),
        "roi_payload_bytes": total_panel_bytes,
        "roi_payload_limit_bytes": _MAX_TOTAL_PANEL_BYTES,
        "roi_payload_truncated": truncated_by_payload,
        "evidence_limits": {
            "max_difference_side": _MAX_DIFFERENCE_SIDE,
            "max_difference_bytes": _MAX_DIFFERENCE_BYTES,
            "max_panel_width": _MAX_PANEL_WIDTH,
            "max_panel_height": _MAX_PANEL_HEIGHT,
            "max_panel_bytes": _MAX_PANEL_BYTES,
            "max_total_panel_bytes": _MAX_TOTAL_PANEL_BYTES,
        },
    }


def _sanitize_judge_metrics(metrics: Mapping[str, object]) -> dict[str, object]:
    sanitized = dict(metrics)
    legacy = sanitized.pop("legacy_quality_gate", None)
    if isinstance(legacy, Mapping):
        legacy_gate = legacy.get("gate")
        if isinstance(legacy_gate, Mapping):
            allowed = (
                "before",
                "after",
                "edge_retention",
                "edge_density_ratio",
            )
            sanitized["legacy_quality_measurements"] = {
                key: legacy_gate[key] for key in allowed if key in legacy_gate
            }
    sanitized["difference_map_legend"] = (
        "white means unchanged; darker pixels mean larger absolute RGB difference"
    )
    return sanitized


def _https_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError("PDF crop semantic gate base URL must use HTTPS")
    return base_url


def _hardened_judge_from_env() -> gate.OpenAIOpenCVCropJudge:
    api_key, base_url = gate._visual_asset_credentials_from_env()
    base_url = _https_base_url(base_url)
    model_id = os.getenv(
        "PDF_CROP_OPENCV_SEMANTIC_GATE_MODEL",
        gate._DEFAULT_MODEL,
    ).strip()
    if not model_id:
        raise ValueError("PDF_CROP_OPENCV_SEMANTIC_GATE_MODEL must not be empty")
    return gate.OpenAIOpenCVCropJudge(
        api_key=api_key,
        model_id=model_id,
        base_url=base_url,
        timeout_seconds=gate._env_float(
            "PDF_CROP_OPENCV_SEMANTIC_GATE_TIMEOUT_SECONDS",
            gate._DEFAULT_TIMEOUT_SECONDS,
            minimum=1.0,
            maximum=180.0,
        ),
        max_attempts=gate._env_int(
            "PDF_CROP_OPENCV_SEMANTIC_GATE_MAX_ATTEMPTS",
            2,
            minimum=1,
            maximum=3,
        ),
    )


def _install_judge_metric_sanitizer() -> None:
    original = gate.OpenAIOpenCVCropJudge.judge
    if getattr(original, "_opencv_semantic_gate_hardened", False):
        return

    def judge_with_sanitized_metrics(self, **kwargs):
        kwargs["metrics"] = _sanitize_judge_metrics(kwargs.get("metrics") or {})
        return original(self, **kwargs)

    judge_with_sanitized_metrics._opencv_semantic_gate_hardened = True  # type: ignore[attr-defined]
    gate.OpenAIOpenCVCropJudge.judge = judge_with_sanitized_metrics


def _install_active_process_wrapper() -> None:
    original = gate.process_visual_crop_opencv_semantic_gate
    if getattr(opencv_bridge.process_visual_crop_v4, "_opencv_semantic_gate_hardened", False):
        return

    def process_with_hardening(png_bytes: bytes, *, page_manifest):
        return original(
            png_bytes,
            page_manifest=page_manifest,
            reviewer_factory=_hardened_judge_from_env,
        )

    process_with_hardening._opencv_semantic_gate_hardened = True  # type: ignore[attr-defined]
    opencv_bridge.process_visual_crop_v4 = process_with_hardening


def install_pdf_crop_opencv_semantic_gate_hardening_compat() -> None:
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        gate._change_evidence = _bounded_change_evidence
        gate._judge_from_env = _hardened_judge_from_env
        if "white means unchanged" not in gate._GATE_SYSTEM_PROMPT:
            gate._GATE_SYSTEM_PROMPT += (
                "\n\nDifference-map legend: white means unchanged; increasingly dark pixels "
                "mean larger absolute RGB difference. ROI panels are ordered "
                "A | B | DIFF."
            )
        _install_judge_metric_sanitizer()
        _install_active_process_wrapper()
        _INSTALLED = True


__all__ = [
    "install_pdf_crop_opencv_semantic_gate_hardening_compat",
]
