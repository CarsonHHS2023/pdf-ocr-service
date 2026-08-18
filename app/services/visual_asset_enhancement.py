"""Conservative post-OCR enhancement for cropped visual assets.

The OCR page image and its coordinates remain unchanged. This module only
creates a presentation rendition after a visual block has already been cropped.
Every operation is fail-open: an unsafe or unsuccessful enhancement returns the
original bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Iterable

import cv2  # type: ignore[import]
import numpy as np

ENHANCEMENT_VERSION = "visual_asset_enhancement_v1"
_MIN_DIMENSION = 24
_DESKEW_MIN_DEGREES = 0.35
_DESKEW_MAX_DEGREES = 5.0
_MIN_LINE_LENGTH_RATIO = 0.22
_MIN_PERSPECTIVE_AREA_RATIO = 0.68
_MIN_PERSPECTIVE_DISTORTION = 0.045

_DOCUMENT_LIKE_TYPES = frozenset(
    {
        "table",
        "tabular",
        "chart",
        "diagram",
        "graphic",
        "screenshot",
        "formula",
        "equation",
    }
)
_COLOR_SENSITIVE_TYPES = frozenset({"seal", "stamp"})


@dataclass(frozen=True)
class VisualAssetEnhancementResult:
    """Enhanced BGR image and bounded, JSON-safe provenance metadata."""

    image: np.ndarray
    metadata: dict[str, Any]


def visual_asset_enhancement_enabled() -> bool:
    """Return whether local visual-asset enhancement is enabled.

    The feature defaults on, but can be disabled without a code deployment by
    setting ``VISUAL_ASSET_ENHANCEMENT_ENABLED=0``.
    """

    value = os.getenv("VISUAL_ASSET_ENHANCEMENT_ENABLED", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def enhance_visual_asset_bytes(
    image_data: bytes,
    *,
    block_type: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Decode, conservatively enhance, and PNG-encode one cropped asset.

    On any failure the original bytes are returned with ``fallback_used=true``.
    """

    normalized_type = _normalize_block_type(block_type)
    base_metadata = _metadata_base(normalized_type)
    if not image_data:
        return image_data, {**base_metadata, "fallback_used": True, "reason": "empty_input"}

    try:
        encoded = np.frombuffer(image_data, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if image is None:
            return image_data, {
                **base_metadata,
                "fallback_used": True,
                "reason": "decode_failed",
            }

        result = enhance_visual_asset(image, block_type=normalized_type)
        ok, output = cv2.imencode(".png", result.image)
        if not ok:
            return image_data, {
                **result.metadata,
                "fallback_used": True,
                "reason": "encode_failed",
            }
        return output.tobytes(), {**result.metadata, "output_format": "png"}
    except Exception as exc:  # fail-open boundary
        return image_data, {
            **base_metadata,
            "fallback_used": True,
            "reason": "unexpected_error",
            "safe_error_type": type(exc).__name__,
        }


def enhance_visual_asset(
    image_bgr: np.ndarray,
    *,
    block_type: str | None = None,
) -> VisualAssetEnhancementResult:
    """Create a conservative enhanced rendition of one cropped visual block."""

    normalized_type = _normalize_block_type(block_type)
    metadata = _metadata_base(normalized_type)

    if not _is_valid_bgr_image(image_bgr):
        return VisualAssetEnhancementResult(
            image=np.array(image_bgr, copy=True),
            metadata={**metadata, "fallback_used": True, "reason": "invalid_image"},
        )

    original = np.ascontiguousarray(image_bgr.copy())
    height, width = original.shape[:2]
    metadata["input_size"] = [int(width), int(height)]
    if min(height, width) < _MIN_DIMENSION:
        return VisualAssetEnhancementResult(
            image=original,
            metadata={**metadata, "fallback_used": True, "reason": "image_too_small"},
        )

    working = original
    applied_steps: list[str] = []

    try:
        quad, quad_confidence, distortion = _detect_perspective_quad(working)
        metadata["perspective_confidence"] = round(float(quad_confidence), 4)
        metadata["perspective_distortion"] = round(float(distortion), 4)
        if quad is not None and normalized_type in _DOCUMENT_LIKE_TYPES:
            rectified = _warp_quad_to_rectangle(working, quad)
            if _geometry_output_is_safe(working, rectified):
                working = rectified
                applied_steps.append("perspective_rectification")
                metadata["source_quad"] = [
                    [round(float(x), 2), round(float(y), 2)] for x, y in quad
                ]

        angle, angle_confidence = _estimate_skew_angle(working)
        metadata["deskew_angle_degrees"] = round(float(angle), 4)
        metadata["deskew_confidence"] = round(float(angle_confidence), 4)
        if (
            _DESKEW_MIN_DEGREES < abs(angle) <= _DESKEW_MAX_DEGREES
            and angle_confidence >= 0.60
        ):
            rotated = _rotate_bound(working, -angle)
            if _geometry_output_is_safe(working, rotated):
                working = rotated
                applied_steps.append("deskew")

        working, tonal_steps = _apply_content_aware_tonal_enhancement(
            working,
            normalized_type,
        )
        applied_steps.extend(tonal_steps)

        if not _quality_gate(original, working):
            return VisualAssetEnhancementResult(
                image=original,
                metadata={
                    **metadata,
                    "applied_steps": applied_steps,
                    "fallback_used": True,
                    "reason": "quality_gate_rejected",
                    "output_size": [int(width), int(height)],
                },
            )

        output_height, output_width = working.shape[:2]
        return VisualAssetEnhancementResult(
            image=np.ascontiguousarray(working),
            metadata={
                **metadata,
                "applied_steps": applied_steps,
                "fallback_used": False,
                "output_size": [int(output_width), int(output_height)],
            },
        )
    except Exception as exc:  # fail-open boundary
        return VisualAssetEnhancementResult(
            image=original,
            metadata={
                **metadata,
                "applied_steps": applied_steps,
                "fallback_used": True,
                "reason": "unexpected_error",
                "safe_error_type": type(exc).__name__,
                "output_size": [int(width), int(height)],
            },
        )


def _metadata_base(block_type: str) -> dict[str, Any]:
    return {
        "enhancement_version": ENHANCEMENT_VERSION,
        "rendition_kind": "enhanced",
        "block_type": block_type,
        "applied_steps": [],
        "fallback_used": False,
    }


def _normalize_block_type(block_type: str | None) -> str:
    return str(block_type or "image").strip().lower() or "image"


def _is_valid_bgr_image(image: Any) -> bool:
    return (
        isinstance(image, np.ndarray)
        and image.dtype == np.uint8
        and image.ndim == 3
        and image.shape[2] == 3
        and image.size > 0
    )


def _order_quad(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    return np.array(
        [
            points[np.argmin(sums)],
            points[np.argmin(differences)],
            points[np.argmax(sums)],
            points[np.argmax(differences)],
        ],
        dtype=np.float32,
    )


def _detect_perspective_quad(image: np.ndarray) -> tuple[np.ndarray | None, float, float]:
    height, width = image.shape[:2]
    image_area = float(height * width)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    edges = cv2.morphologyEx(
        edges,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
        iterations=2,
    )
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    best_quad: np.ndarray | None = None
    best_score = 0.0
    best_distortion = 0.0
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:20]:
        area = float(cv2.contourArea(contour))
        area_ratio = area / image_area if image_area else 0.0
        if area_ratio < _MIN_PERSPECTIVE_AREA_RATIO:
            continue
        perimeter = cv2.arcLength(contour, True)
        approximation = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approximation) != 4 or not cv2.isContourConvex(approximation):
            continue

        quad = _order_quad(approximation.reshape(4, 2))
        top = float(np.linalg.norm(quad[1] - quad[0]))
        bottom = float(np.linalg.norm(quad[2] - quad[3]))
        left = float(np.linalg.norm(quad[3] - quad[0]))
        right = float(np.linalg.norm(quad[2] - quad[1]))
        if min(top, bottom, left, right) < _MIN_DIMENSION:
            continue
        width_distortion = abs(top - bottom) / max(top, bottom)
        height_distortion = abs(left - right) / max(left, right)
        distortion = max(width_distortion, height_distortion)
        if distortion < _MIN_PERSPECTIVE_DISTORTION:
            continue

        score = min(1.0, area_ratio) * min(1.0, distortion / 0.20)
        if score > best_score:
            best_quad = quad
            best_score = score
            best_distortion = distortion

    return best_quad, best_score, best_distortion


def _warp_quad_to_rectangle(image: np.ndarray, quad: np.ndarray) -> np.ndarray:
    ordered = _order_quad(quad)
    top_left, top_right, bottom_right, bottom_left = ordered
    target_width = max(
        int(round(np.linalg.norm(top_right - top_left))),
        int(round(np.linalg.norm(bottom_right - bottom_left))),
    )
    target_height = max(
        int(round(np.linalg.norm(bottom_left - top_left))),
        int(round(np.linalg.norm(bottom_right - top_right))),
    )
    if target_width < _MIN_DIMENSION or target_height < _MIN_DIMENSION:
        return image

    destination = np.array(
        [
            [0, 0],
            [target_width - 1, 0],
            [target_width - 1, target_height - 1],
            [0, target_height - 1],
        ],
        dtype=np.float32,
    )
    transform = cv2.getPerspectiveTransform(ordered, destination)
    return cv2.warpPerspective(
        image,
        transform,
        (target_width, target_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _estimate_skew_angle(image: np.ndarray) -> tuple[float, float]:
    _, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        15,
    )
    minimum_length = max(20, int(width * _MIN_LINE_LENGTH_RATIO))
    lines = cv2.HoughLinesP(
        binary,
        1,
        np.pi / 1800,
        threshold=max(25, int(width * 0.08)),
        minLineLength=minimum_length,
        maxLineGap=max(8, int(width * 0.03)),
    )
    if lines is None:
        return 0.0, 0.0

    weighted_angles: list[tuple[float, float]] = []
    for line in lines[:, 0]:
        x1, y1, x2, y2 = [float(value) for value in line]
        length = float(np.hypot(x2 - x1, y2 - y1))
        if length < minimum_length:
            continue
        angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        while angle <= -90:
            angle += 180
        while angle > 90:
            angle -= 180
        if abs(angle) <= 12:
            weighted_angles.append((angle, length))

    if len(weighted_angles) < 2:
        return 0.0, 0.0

    median = _weighted_median(weighted_angles)
    agreeing_weight = sum(
        weight for angle, weight in weighted_angles if abs(angle - median) <= 1.2
    )
    total_weight = sum(weight for _, weight in weighted_angles)
    confidence = min(1.0, agreeing_weight / max(total_weight, 1.0))
    confidence *= min(1.0, len(weighted_angles) / 6.0)
    return median, confidence


def _weighted_median(values: Iterable[tuple[float, float]]) -> float:
    ordered = sorted(values, key=lambda item: item[0])
    total = sum(weight for _, weight in ordered)
    midpoint = total / 2.0
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= midpoint:
            return float(value)
    return float(ordered[-1][0]) if ordered else 0.0


def _rotate_bound(image: np.ndarray, angle: float) -> np.ndarray:
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    cos_value = abs(matrix[0, 0])
    sin_value = abs(matrix[0, 1])
    output_width = int((height * sin_value) + (width * cos_value))
    output_height = int((height * cos_value) + (width * sin_value))
    matrix[0, 2] += (output_width / 2.0) - center[0]
    matrix[1, 2] += (output_height / 2.0) - center[1]
    border = _estimated_border_color(image)
    return cv2.warpAffine(
        image,
        matrix,
        (output_width, output_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border,
    )


def _estimated_border_color(image: np.ndarray) -> tuple[int, int, int]:
    top = image[0, :, :]
    bottom = image[-1, :, :]
    left = image[:, 0, :]
    right = image[:, -1, :]
    pixels = np.concatenate([top, bottom, left, right], axis=0)
    medians = np.median(pixels, axis=0)
    return tuple(int(value) for value in medians)


def _apply_content_aware_tonal_enhancement(
    image: np.ndarray,
    block_type: str,
) -> tuple[np.ndarray, list[str]]:
    if block_type in _DOCUMENT_LIKE_TYPES:
        denoised = cv2.bilateralFilter(image, 5, 20, 20)
        normalized = _clahe_luminance(denoised, clip_limit=1.8)
        sharpened = _unsharp_mask(normalized, amount=0.28)
        return sharpened, [
            "edge_preserving_denoise",
            "local_contrast",
            "mild_sharpen",
        ]

    if block_type in _COLOR_SENSITIVE_TYPES:
        denoised = cv2.bilateralFilter(image, 3, 12, 12)
        normalized = _clahe_luminance(denoised, clip_limit=1.25)
        return normalized, ["mild_color_denoise", "mild_local_contrast"]

    denoised = cv2.bilateralFilter(image, 3, 10, 10)
    normalized = _clahe_luminance(denoised, clip_limit=1.20)
    return normalized, ["mild_color_denoise", "mild_local_contrast"]


def _clahe_luminance(image: np.ndarray, *, clip_limit: float) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lightness, channel_a, channel_b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    enhanced_lightness = clahe.apply(lightness)
    merged = cv2.merge((enhanced_lightness, channel_a, channel_b))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def _unsharp_mask(image: np.ndarray, *, amount: float) -> np.ndarray:
    blurred = cv2.GaussianBlur(image, (0, 0), 1.0)
    return cv2.addWeighted(image, 1.0 + amount, blurred, -amount, 0)


def _geometry_output_is_safe(source: np.ndarray, output: np.ndarray) -> bool:
    if not _is_valid_bgr_image(output):
        return False
    source_area = float(source.shape[0] * source.shape[1])
    output_area = float(output.shape[0] * output.shape[1])
    return (
        min(output.shape[:2]) >= _MIN_DIMENSION
        and output_area >= source_area * 0.35
        and output_area <= source_area * 4.0
    )


def _quality_gate(source: np.ndarray, output: np.ndarray) -> bool:
    if not _geometry_output_is_safe(source, output):
        return False
    source_gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    output_gray = cv2.cvtColor(output, cv2.COLOR_BGR2GRAY)
    source_contrast = float(np.std(source_gray))
    output_contrast = float(np.std(output_gray))
    if source_contrast >= 4.0 and output_contrast < source_contrast * 0.45:
        return False

    source_edges = float(np.mean(cv2.Canny(source_gray, 80, 180) > 0))
    output_edges = float(np.mean(cv2.Canny(output_gray, 80, 180) > 0))
    if source_edges > 0.002 and output_edges > source_edges * 4.0:
        return False
    return True
