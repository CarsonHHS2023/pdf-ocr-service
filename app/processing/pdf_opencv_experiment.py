"""Isolated OpenCV preprocessing experiment for PDF pages 3 and 4.

This module is intentionally test-only. It preserves unselected PDF pages, replaces
page 3 with a perspective/deskew/background-normalized raster, and replaces page 4
with a background-cleaned binary raster. No OCR is performed here.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
from typing import Iterable

import cv2
import fitz  # type: ignore[import]
import numpy as np

from app.processing.pdf_geometry_preprocessing import (
    GeometryPageResult,
    GeometryPreprocessedPdf,
)

GEOMETRY_PREPROCESSING_VERSION = "opencv_pages_3_4_experiment_v1"
_RENDER_DPI = 300
_DIAGNOSTIC_DPI = 150
_SELECTED_PAGE_INDEXES = (2, 3)
_MAX_RENDER_PIXELS = 60_000_000


def preprocess_pdf_geometry_opencv(
    pdf_bytes: bytes,
    *,
    expected_page_count: int | None = None,
    **_: object,
) -> GeometryPreprocessedPdf:
    """Process only pages 3 and 4 and preserve all other pages unchanged."""
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("pdf_bytes must contain a PDF")

    source = fitz.open(stream=pdf_bytes, filetype="pdf")
    output = fitz.open()
    page_results: list[GeometryPageResult] = []
    try:
        page_count = int(source.page_count)
        if expected_page_count is not None and page_count != int(expected_page_count):
            raise ValueError("PDF page count does not match upload metadata")
        if page_count < 4:
            raise ValueError("OpenCV experiment requires at least four pages")

        metadata = source.metadata
        if metadata:
            output.set_metadata(metadata)

        for page_index in range(page_count):
            page = source.load_page(page_index)
            page_size = (
                max(1, int(round(float(page.rect.width)))),
                max(1, int(round(float(page.rect.height)))),
            )
            if page_index not in _SELECTED_PAGE_INDEXES:
                output.insert_pdf(source, from_page=page_index, to_page=page_index)
                page_results.append(
                    GeometryPageResult(
                        page_index=page_index,
                        applied_steps=(),
                        deskew_angle_degrees=0.0,
                        deskew_confidence=0.0,
                        perspective_confidence=0.0,
                        perspective_distortion=0.0,
                        input_size=page_size,
                        output_size=page_size,
                        fallback_used=False,
                        safe_reason="opencv_experiment_unselected_page",
                        route="no_op",
                        source_kind="pdf_page",
                    )
                )
                continue

            source_bgr = _render_page_bgr(page, dpi=_RENDER_DPI)
            if page_index == 2:
                processed_bgr, diagnostic = _process_photo_page(source_bgr)
                steps = (
                    "opencv_perspective",
                    "opencv_deskew",
                    "opencv_illumination_normalize",
                )
                route = "opencv_photo_page"
            else:
                processed_bgr, diagnostic = _process_gray_scan_page(source_bgr)
                steps = (
                    "opencv_background_normalize",
                    "opencv_adaptive_binarize",
                )
                route = "opencv_gray_scan_page"

            _insert_raster_page(output, page.rect, processed_bgr)
            input_height, input_width = source_bgr.shape[:2]
            output_height, output_width = processed_bgr.shape[:2]
            page_results.append(
                GeometryPageResult(
                    page_index=page_index,
                    applied_steps=steps,
                    deskew_angle_degrees=float(diagnostic["deskew_angle_degrees"]),
                    deskew_confidence=float(diagnostic["deskew_confidence"]),
                    perspective_confidence=float(diagnostic["perspective_confidence"]),
                    perspective_distortion=float(diagnostic["perspective_distortion"]),
                    input_size=(input_width, input_height),
                    output_size=(output_width, output_height),
                    fallback_used=False,
                    safe_reason=None,
                    route=route,
                    source_kind="pdf_page",
                    source_xres=_RENDER_DPI,
                    source_yres=_RENDER_DPI,
                    effective_xdpi=float(_RENDER_DPI),
                    effective_ydpi=float(_RENDER_DPI),
                )
            )
            print(
                "PDF_OPENCV_PAGE_PROCESSED "
                f"page_number={page_index + 1} route={route} "
                f"perspective_applied={diagnostic['perspective_applied']} "
                f"perspective_confidence={diagnostic['perspective_confidence']:.4f} "
                f"perspective_distortion={diagnostic['perspective_distortion']:.6f} "
                f"deskew_angle_degrees={diagnostic['deskew_angle_degrees']:.4f} "
                f"deskew_confidence={diagnostic['deskew_confidence']:.4f} "
                f"input_size={input_width}x{input_height} "
                f"output_size={output_width}x{output_height}",
                flush=True,
            )

        processed_bytes = output.tobytes(garbage=4, deflate=True)
    finally:
        output.close()
        source.close()

    checksum = hashlib.sha256(processed_bytes).hexdigest()
    return GeometryPreprocessedPdf(
        pdf_bytes=processed_bytes,
        checksum_sha256=checksum,
        byte_size=len(processed_bytes),
        page_count=len(page_results),
        changed_page_count=len(_SELECTED_PAGE_INDEXES),
        pages=tuple(page_results),
        version=GEOMETRY_PREPROCESSING_VERSION,
    )


def retain_opencv_diagnostics(
    *,
    source_pdf_bytes: bytes,
    processed: GeometryPreprocessedPdf,
    processing_attempt_id: str,
) -> Path:
    """Retain final PDF plus before/after PNGs in the test Storage mount."""
    root = Path("/data/output/opencv-diagnostics") / processing_attempt_id
    root.mkdir(parents=True, exist_ok=True)
    _atomic_write(root / "processed.pdf", processed.pdf_bytes)

    source = fitz.open(stream=source_pdf_bytes, filetype="pdf")
    result = fitz.open(stream=processed.pdf_bytes, filetype="pdf")
    try:
        for page_index in _SELECTED_PAGE_INDEXES:
            before = _render_page_bgr(source.load_page(page_index), dpi=_DIAGNOSTIC_DPI)
            after = _render_page_bgr(result.load_page(page_index), dpi=_DIAGNOSTIC_DPI)
            page_number = page_index + 1
            _write_png(root / f"page-{page_number:02d}-before.png", before)
            _write_png(root / f"page-{page_number:02d}-after.png", after)
            _write_png(
                root / f"page-{page_number:02d}-comparison.png",
                _comparison_image(before, after),
            )
    finally:
        result.close()
        source.close()

    source_sha = hashlib.sha256(source_pdf_bytes).hexdigest()
    manifest = (
        f"version={processed.version}\n"
        f"source_sha256={source_sha}\n"
        f"output_sha256={processed.checksum_sha256}\n"
        f"source_size_bytes={len(source_pdf_bytes)}\n"
        f"output_size_bytes={processed.byte_size}\n"
        f"changed_page_count={processed.changed_page_count}\n"
        "paddle_vl_skipped=true\n"
    ).encode("utf-8")
    _atomic_write(root / "manifest.txt", manifest)
    print(
        "PDF_OPENCV_DIAGNOSTIC_RETAINED "
        f"processing_attempt_id={processing_attempt_id} path={root} "
        f"output_pdf={root / 'processed.pdf'} "
        f"output_size_bytes={processed.byte_size} "
        f"output_sha256={processed.checksum_sha256}",
        flush=True,
    )
    return root


def _render_page_bgr(page: fitz.Page, *, dpi: int) -> np.ndarray:
    scale = float(dpi) / 72.0
    width = max(1, int(math.ceil(float(page.rect.width) * scale)))
    height = max(1, int(math.ceil(float(page.rect.height) * scale)))
    if width * height > _MAX_RENDER_PIXELS:
        raise ValueError("OpenCV experiment page render exceeds pixel limit")
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(scale, scale),
        colorspace=fitz.csRGB,
        alpha=False,
        annots=True,
    )
    rgb = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height,
        pixmap.width,
        pixmap.n,
    )
    return cv2.cvtColor(rgb[:, :, :3], cv2.COLOR_RGB2BGR)


def _process_photo_page(image: np.ndarray) -> tuple[np.ndarray, dict[str, float | bool]]:
    quad, coverage = _detect_page_quad(image)
    height, width = image.shape[:2]
    canvas_corners = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    perspective_distortion = 0.0
    perspective_applied = False
    corrected = image
    if quad is not None:
        diagonal = max(1.0, math.hypot(width, height))
        perspective_distortion = float(
            np.mean(np.linalg.norm(quad - canvas_corners, axis=1)) / diagonal
        )
        if perspective_distortion >= 0.003:
            transform = cv2.getPerspectiveTransform(quad, canvas_corners)
            corrected = cv2.warpPerspective(
                image,
                transform,
                (width, height),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(255, 255, 255),
            )
            perspective_applied = True

    angle, confidence = _estimate_horizontal_angle(corrected)
    if 0.08 <= abs(angle) <= 5.0:
        corrected = _rotate_same_canvas(corrected, angle)
    else:
        angle = 0.0

    gray = cv2.cvtColor(corrected, cv2.COLOR_BGR2GRAY)
    sigma = max(15.0, min(gray.shape) / 10.0)
    background = cv2.GaussianBlur(gray, (0, 0), sigmaX=sigma, sigmaY=sigma)
    normalized = cv2.divide(gray, np.maximum(background, 1), scale=255)
    normalized = cv2.addWeighted(gray, 0.35, normalized, 0.65, 0)
    normalized[normalized >= 250] = 255
    output = cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR)
    return output, {
        "perspective_applied": perspective_applied,
        "perspective_confidence": float(coverage),
        "perspective_distortion": perspective_distortion,
        "deskew_angle_degrees": float(angle),
        "deskew_confidence": float(confidence),
    }


def _process_gray_scan_page(image: np.ndarray) -> tuple[np.ndarray, dict[str, float | bool]]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    block_size = _odd_clamped(round(min(height, width) / 8), 75, 401)
    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        block_size,
        18,
    )
    output = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    return output, {
        "perspective_applied": False,
        "perspective_confidence": 0.0,
        "perspective_distortion": 0.0,
        "deskew_angle_degrees": 0.0,
        "deskew_confidence": 0.0,
    }


def _detect_page_quad(image: np.ndarray) -> tuple[np.ndarray | None, float]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    _, mask = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )
    kernel_size = _odd_clamped(round(min(gray.shape) / 60), 5, 31)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (kernel_size, kernel_size),
    )
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    image_area = float(gray.shape[0] * gray.shape[1])
    candidates: list[tuple[float, np.ndarray]] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < image_area * 0.35:
            continue
        perimeter = float(cv2.arcLength(contour, True))
        for epsilon_ratio in (0.01, 0.02, 0.03, 0.04):
            approx = cv2.approxPolyDP(contour, epsilon_ratio * perimeter, True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                candidates.append((area, _order_quad(approx[:, 0, :])))
                break
    if not candidates:
        return None, 0.0
    area, quad = max(candidates, key=lambda candidate: candidate[0])
    return quad, min(1.0, area / image_area)


def _order_quad(points: Iterable[Iterable[float]]) -> np.ndarray:
    quad = np.asarray(tuple(points), dtype=np.float32).reshape(4, 2)
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


def _estimate_horizontal_angle(image: np.ndarray) -> tuple[float, float]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )[1]
    height, width = gray.shape
    kernel_width = max(15, width // 20)
    connected = cv2.morphologyEx(
        binary,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 1)),
    )
    lines = cv2.HoughLinesP(
        connected,
        1,
        np.pi / 720.0,
        threshold=max(30, width // 8),
        minLineLength=max(40, width // 5),
        maxLineGap=max(10, width // 30),
    )
    if lines is None:
        return 0.0, 0.0

    angles: list[float] = []
    weights: list[float] = []
    for x1, y1, x2, y2 in lines[:, 0, :]:
        angle = math.degrees(math.atan2(float(y2 - y1), float(x2 - x1)))
        while angle <= -90.0:
            angle += 180.0
        while angle > 90.0:
            angle -= 180.0
        length = math.hypot(float(x2 - x1), float(y2 - y1))
        if abs(angle) <= 7.0:
            angles.append(angle)
            weights.append(length)
    if not angles:
        return 0.0, 0.0

    angle = _weighted_median(angles, weights)
    total_weight = max(1.0, sum(weights))
    inlier_weight = sum(
        weight
        for candidate, weight in zip(angles, weights, strict=True)
        if abs(candidate - angle) <= 1.0
    )
    return angle, min(1.0, inlier_weight / total_weight)


def _weighted_median(values: list[float], weights: list[float]) -> float:
    order = np.argsort(np.asarray(values))
    sorted_values = np.asarray(values, dtype=np.float64)[order]
    sorted_weights = np.asarray(weights, dtype=np.float64)[order]
    cumulative = np.cumsum(sorted_weights)
    index = int(np.searchsorted(cumulative, cumulative[-1] / 2.0))
    return float(sorted_values[min(index, len(sorted_values) - 1)])


def _rotate_same_canvas(image: np.ndarray, angle: float) -> np.ndarray:
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), angle, 1.0)
    return cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )


def _insert_raster_page(document: fitz.Document, source_rect: fitz.Rect, image: np.ndarray) -> None:
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError("Could not encode OpenCV page output")
    page = document.new_page(width=float(source_rect.width), height=float(source_rect.height))
    page.insert_image(page.rect, stream=encoded.tobytes(), keep_proportion=False)


def _comparison_image(before: np.ndarray, after: np.ndarray) -> np.ndarray:
    target_height = min(before.shape[0], after.shape[0])
    before_resized = _resize_to_height(before, target_height)
    after_resized = _resize_to_height(after, target_height)
    separator = np.full((target_height, 12, 3), 224, dtype=np.uint8)
    return cv2.hconcat([before_resized, separator, after_resized])


def _resize_to_height(image: np.ndarray, height: int) -> np.ndarray:
    width = max(1, int(round(image.shape[1] * height / image.shape[0])))
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


def _write_png(path: Path, image: np.ndarray) -> None:
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError(f"Could not encode diagnostic image {path.name}")
    _atomic_write(path, encoded.tobytes())


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _odd_clamped(value: int, minimum: int, maximum: int) -> int:
    bounded = max(minimum, min(int(value), maximum))
    return bounded if bounded % 2 else bounded + 1


__all__ = [
    "GEOMETRY_PREPROCESSING_VERSION",
    "preprocess_pdf_geometry_opencv",
    "retain_opencv_diagnostics",
]
