"""Cheap geometry signals for the S0 v5 Phase 0 shadow planner.

The current v4 deskew detector intentionally uses a fine Hough angle grid because
it is part of an authoritative high-resolution quality path. Reusing that detector
for every shadow-analysis page added hundreds of milliseconds per page on the
locked benchmark. Phase 0 instead uses a small projection-profile deskew probe
plus a bounded low-resolution page-quad detector. These signals can only cause a
shadow escalation; current v4 remains authoritative.
"""
from __future__ import annotations

import math
import threading

import cv2
import numpy as np


_POLICY_VERSION = "atlas_s0_v5_cheap_geometry_v1"
_SKEW_MAX_SIDE = 360
_PERSPECTIVE_MAX_SIDE = 640
_SKEW_MAX_DEGREES = 3.0
_SKEW_STEP_DEGREES = 0.25
_MIN_SKEW_GAIN = 0.01
_MIN_SKEW_DEGREES = 0.25
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _resize_max_side(image: np.ndarray, max_side: int) -> np.ndarray:
    height, width = image.shape[:2]
    scale = min(1.0, float(max_side) / max(height, width))
    if scale >= 1.0:
        return np.ascontiguousarray(image)
    return np.ascontiguousarray(
        cv2.resize(
            image,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA,
        )
    )


def _projection_skew(image: np.ndarray) -> tuple[float, float, float]:
    """Return best angle, normalized confidence, and score gain over zero angle."""
    small = _resize_max_side(image, _SKEW_MAX_SIDE)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    roi = gray[
        int(round(height * 0.08)) : int(round(height * 0.92)),
        int(round(width * 0.10)) : int(round(width * 0.90)),
    ]
    if roi.size == 0:
        return 0.0, 0.0, 0.0

    binary = cv2.threshold(
        roi,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )[1]
    horizontal_rules = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (max(20, roi.shape[1] // 4), 1),
        ),
    )
    vertical_rules = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (1, max(20, roi.shape[0] // 6)),
        ),
    )
    text_only = cv2.subtract(
        binary,
        cv2.bitwise_or(horizontal_rules, vertical_rules),
    )
    if int(np.count_nonzero(text_only)) < 32:
        return 0.0, 0.0, 0.0

    angles = np.arange(
        -_SKEW_MAX_DEGREES,
        _SKEW_MAX_DEGREES + _SKEW_STEP_DEGREES / 2.0,
        _SKEW_STEP_DEGREES,
        dtype=np.float32,
    )
    center = (text_only.shape[1] / 2.0, text_only.shape[0] / 2.0)
    scores: list[float] = []
    for angle in angles:
        matrix = cv2.getRotationMatrix2D(center, float(angle), 1.0)
        rotated = cv2.warpAffine(
            text_only,
            matrix,
            (text_only.shape[1], text_only.shape[0]),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        row_counts = np.count_nonzero(rotated, axis=1).astype(np.float32)
        scores.append(float(np.var(row_counts)))

    if not scores:
        return 0.0, 0.0, 0.0
    best_index = int(np.argmax(np.asarray(scores)))
    zero_index = int(np.argmin(np.abs(angles)))
    best_score = float(scores[best_index])
    zero_score = float(scores[zero_index])
    gain = max(0.0, (best_score - zero_score) / max(1e-9, zero_score))
    confidence = min(1.0, gain * 5.0)
    best_angle = float(angles[best_index])
    if gain < _MIN_SKEW_GAIN:
        # A tiny projection-score change is not evidence of skew; snapping it to
        # zero prevents quantization noise from escalating clean pages.
        best_angle = 0.0
        confidence = 0.0
    return best_angle, confidence, gain


def _order_quad(points: np.ndarray) -> np.ndarray:
    quad = np.asarray(points, dtype=np.float32).reshape(4, 2)
    sums = quad.sum(axis=1)
    differences = np.diff(quad, axis=1).reshape(-1)
    return np.array(
        [
            quad[np.argmin(sums)],
            quad[np.argmin(differences)],
            quad[np.argmax(sums)],
            quad[np.argmax(differences)],
        ],
        dtype=np.float32,
    )


def _page_quad(image: np.ndarray) -> tuple[np.ndarray | None, float]:
    small = _resize_max_side(image, _PERSPECTIVE_MAX_SIDE)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    mask = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )[1]
    kernel_size = max(3, int(round(min(gray.shape) / 80)))
    if kernel_size % 2 == 0:
        kernel_size += 1
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (kernel_size, kernel_size),
        ),
        iterations=1,
    )
    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    image_area = float(max(1, gray.shape[0] * gray.shape[1]))
    candidates: list[tuple[float, np.ndarray]] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < image_area * 0.40:
            continue
        perimeter = float(cv2.arcLength(contour, True))
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            candidates.append((area, _order_quad(approx[:, 0, :])))
    if not candidates:
        return None, 0.0
    area, quad = max(candidates, key=lambda item: item[0])
    return quad, min(1.0, area / image_area)


def cheap_geometry_observation(image: np.ndarray) -> dict[str, float | bool | str]:
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("cheap geometry observation requires a BGR image")
    angle, confidence, gain = _projection_skew(image)
    quad, coverage = _page_quad(image)

    perspective_distortion = 0.0
    if quad is not None:
        # Quad coordinates belong to the bounded perspective image. Distortion is
        # normalized by its diagonal, so no upscaling back to source pixels is
        # necessary for the shadow decision.
        perspective = _resize_max_side(image, _PERSPECTIVE_MAX_SIDE)
        height, width = perspective.shape[:2]
        corners = np.array(
            [
                [0, 0],
                [width - 1, 0],
                [width - 1, height - 1],
                [0, height - 1],
            ],
            dtype=np.float32,
        )
        diagonal = max(1.0, math.hypot(width, height))
        perspective_distortion = float(
            np.mean(np.linalg.norm(quad - corners, axis=1)) / diagonal
        )

    geometry_suspect = bool(
        (
            abs(angle) >= _MIN_SKEW_DEGREES
            and gain >= _MIN_SKEW_GAIN
            and confidence > 0.0
        )
        or (
            0.40 <= coverage <= 0.995
            and perspective_distortion >= 0.005
        )
    )
    return {
        "policy_version": _POLICY_VERSION,
        "estimated_skew_degrees": round(float(angle), 4),
        "estimated_skew_confidence": round(float(confidence), 4),
        "estimated_skew_score_gain": round(float(gain), 6),
        "perspective_coverage": round(float(coverage), 4),
        "perspective_distortion": round(float(perspective_distortion), 6),
        "geometry_suspect": geometry_suspect,
    }


def install_s0_v5_cheap_shadow_geometry() -> None:
    """Replace only the shadow geometry observer; never touch current v4."""
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        from app.processing import s0_v5_shadow_planner as planner

        current = planner._geometry_observation
        if not getattr(current, "__atlas_s0_v5_cheap_geometry__", False):
            setattr(
                cheap_geometry_observation,
                "__atlas_s0_v5_cheap_geometry__",
                True,
            )
            setattr(
                cheap_geometry_observation,
                "__atlas_s0_v5_phase0_delegate__",
                current,
            )
            planner._geometry_observation = cheap_geometry_observation
        _INSTALLED = True


__all__ = [
    "cheap_geometry_observation",
    "install_s0_v5_cheap_shadow_geometry",
]
