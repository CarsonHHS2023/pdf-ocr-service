"""Unified OpenCV preprocessing experiment with staged quality gates.

This test-only module keeps born-digital pages unchanged, protects color-critical
pages from grayscale normalization, and generates geometry/background candidates
for other raster-dominated pages. Geometry and background candidates are accepted
independently so a rejected cleanup candidate does not discard a useful deskew or
perspective correction. No OCR is performed here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import threading
from typing import Iterable

import cv2
import fitz  # type: ignore[import]
import numpy as np

from app.processing.pdf_geometry_preprocessing import (
    GeometryPageResult,
    GeometryPreprocessedPdf,
)

GEOMETRY_PREPROCESSING_VERSION = "opencv_unified_quality_gate_experiment_v4"
_ANALYSIS_DPI = 120
_RENDER_DPI = 300
_DIAGNOSTIC_DPI = 150
_MAX_RENDER_PIXELS = 60_000_000
_MAX_DIAGNOSTIC_PAGES = 20
_DIAGNOSTIC_LOCK = threading.Lock()
_DIAGNOSTIC_MANIFESTS: dict[str, dict[str, object]] = {}


@dataclass(frozen=True, slots=True)
class _PageStructure:
    text_chars: int
    max_image_coverage: float
    born_digital: bool


@dataclass(frozen=True, slots=True)
class _ColorFeatures:
    high_saturation_ratio: float
    largest_saturated_component_ratio: float
    saturation_p90: float
    color_critical: bool


@dataclass(frozen=True, slots=True)
class _ImageMetrics:
    background_std: float
    background_range: float
    white_ratio: float
    dark_ratio: float
    edge_density: float
    long_line_count: int


@dataclass(frozen=True, slots=True)
class _GeometryDiagnostic:
    perspective_applied: bool
    perspective_confidence: float
    perspective_distortion: float
    deskew_applied: bool
    deskew_angle_degrees: float
    deskew_confidence: float
    residual_angle_degrees: float
    residual_confidence: float


def preprocess_pdf_geometry_opencv(
    pdf_bytes: bytes,
    *,
    expected_page_count: int | None = None,
    **_: object,
) -> GeometryPreprocessedPdf:
    """Build one complete PDF using only candidates accepted by quality gates."""
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("pdf_bytes must contain a PDF")

    source = fitz.open(stream=pdf_bytes, filetype="pdf")
    output = fitz.open()
    page_results: list[GeometryPageResult] = []
    manifest_pages: list[dict[str, object]] = []
    changed_page_count = 0

    try:
        page_count = int(source.page_count)
        if expected_page_count is not None and page_count != int(expected_page_count):
            raise ValueError("PDF page count does not match upload metadata")
        if page_count <= 0:
            raise ValueError("PDF must contain at least one page")

        metadata = source.metadata
        if metadata:
            output.set_metadata(metadata)

        for page_index in range(page_count):
            page = source.load_page(page_index)
            page_number = page_index + 1
            page_size = (
                max(1, int(round(float(page.rect.width)))),
                max(1, int(round(float(page.rect.height)))),
            )
            structure = _inspect_page_structure(page)

            if structure.born_digital:
                output.insert_pdf(source, from_page=page_index, to_page=page_index)
                result = GeometryPageResult(
                    page_index=page_index,
                    applied_steps=(),
                    deskew_angle_degrees=0.0,
                    deskew_confidence=0.0,
                    perspective_confidence=0.0,
                    perspective_distortion=0.0,
                    input_size=page_size,
                    output_size=page_size,
                    fallback_used=False,
                    safe_reason="born_digital_preserved",
                    route="born_digital_no_op",
                    source_kind="pdf_page",
                )
                page_results.append(result)
                decision = {
                    "page_number": page_number,
                    "route": result.route,
                    "selected": "original",
                    "structure": asdict(structure),
                    "reasons": ["born_digital"],
                }
                manifest_pages.append(decision)
                _log_page_decision(decision)
                continue

            preview = _render_page_bgr(page, dpi=_ANALYSIS_DPI)
            color = _color_features(preview)
            source_bgr = _render_page_bgr(page, dpi=_RENDER_DPI)
            source_height, source_width = source_bgr.shape[:2]

            geometry_candidate, geometry_diag = _build_geometry_candidate(source_bgr)
            geometry_accepted, geometry_reason, geometry_gate = _gate_geometry_candidate(
                source_bgr,
                geometry_candidate,
                geometry_diag,
            )
            geometry_selected = geometry_candidate if geometry_accepted else source_bgr

            applied_steps: list[str] = []
            if geometry_accepted:
                if geometry_diag.perspective_applied:
                    applied_steps.append("opencv_perspective")
                if geometry_diag.deskew_applied:
                    applied_steps.append("opencv_deskew")

            background_attempted = not color.color_critical
            background_accepted = False
            background_reason = "color_critical_background_skipped"
            background_gate: dict[str, object] = {}
            selected_bgr = geometry_selected

            if background_attempted:
                background_candidate = _normalize_background(geometry_selected)
                (
                    background_accepted,
                    background_reason,
                    background_gate,
                ) = _gate_background_candidate(
                    geometry_selected,
                    background_candidate,
                )
                if background_accepted:
                    selected_bgr = background_candidate
                    applied_steps.extend(
                        (
                            "opencv_background_estimate_downsampled",
                            "opencv_background_divide",
                            "opencv_texture_median",
                            "opencv_bilateral_denoise",
                            "opencv_background_whiten",
                        )
                    )

            changed = geometry_accepted or background_accepted
            if changed:
                _insert_raster_page(output, page.rect, selected_bgr)
                changed_page_count += 1
            else:
                output.insert_pdf(source, from_page=page_index, to_page=page_index)

            selected_height, selected_width = selected_bgr.shape[:2]
            if color.color_critical:
                route = (
                    "color_critical_geometry"
                    if geometry_accepted
                    else "color_critical_no_op"
                )
            elif background_accepted:
                route = "normalized_scan"
            elif geometry_accepted:
                route = "geometry_only"
            else:
                route = "quality_gate_original"

            safe_reasons = []
            if not geometry_accepted:
                safe_reasons.append(f"geometry:{geometry_reason}")
            if background_attempted and not background_accepted:
                safe_reasons.append(f"background:{background_reason}")
            if color.color_critical:
                safe_reasons.append("background:color_critical_skipped")
            safe_reason = ";".join(safe_reasons) or None

            result = GeometryPageResult(
                page_index=page_index,
                applied_steps=tuple(applied_steps),
                deskew_angle_degrees=geometry_diag.deskew_angle_degrees,
                deskew_confidence=geometry_diag.deskew_confidence,
                perspective_confidence=geometry_diag.perspective_confidence,
                perspective_distortion=geometry_diag.perspective_distortion,
                input_size=(source_width, source_height),
                output_size=(selected_width, selected_height),
                fallback_used=False,
                safe_reason=safe_reason,
                route=route,
                source_kind="pdf_page",
                residual_angle_degrees=geometry_diag.residual_angle_degrees,
                residual_confidence=geometry_diag.residual_confidence,
                source_xres=_RENDER_DPI,
                source_yres=_RENDER_DPI,
                effective_xdpi=float(_RENDER_DPI),
                effective_ydpi=float(_RENDER_DPI),
            )
            page_results.append(result)

            decision = {
                "page_number": page_number,
                "route": route,
                "selected": (
                    "geometry_and_background"
                    if background_accepted and geometry_accepted
                    else "background"
                    if background_accepted
                    else "geometry"
                    if geometry_accepted
                    else "original"
                ),
                "structure": asdict(structure),
                "color": asdict(color),
                "geometry": {
                    **asdict(geometry_diag),
                    "accepted": geometry_accepted,
                    "reason": geometry_reason,
                    "gate": geometry_gate,
                },
                "background": {
                    "attempted": background_attempted,
                    "accepted": background_accepted,
                    "reason": background_reason,
                    "gate": background_gate,
                },
                "applied_steps": list(applied_steps),
            }
            manifest_pages.append(decision)
            _log_page_decision(decision)

        processed_bytes = output.tobytes(garbage=4, deflate=True)
    finally:
        output.close()
        source.close()

    if changed_page_count == 0:
        processed_bytes = pdf_bytes

    checksum = hashlib.sha256(processed_bytes).hexdigest()
    manifest = {
        "version": GEOMETRY_PREPROCESSING_VERSION,
        "source_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "output_sha256": checksum,
        "source_size_bytes": len(pdf_bytes),
        "output_size_bytes": len(processed_bytes),
        "changed_page_count": changed_page_count,
        "pages": manifest_pages,
        "paddle_vl_skipped": True,
    }
    with _DIAGNOSTIC_LOCK:
        _DIAGNOSTIC_MANIFESTS[checksum] = manifest

    return GeometryPreprocessedPdf(
        pdf_bytes=processed_bytes,
        checksum_sha256=checksum,
        byte_size=len(processed_bytes),
        page_count=len(page_results),
        changed_page_count=changed_page_count,
        pages=tuple(page_results),
        version=GEOMETRY_PREPROCESSING_VERSION,
    )


def retain_opencv_diagnostics(
    *,
    source_pdf_bytes: bytes,
    processed: GeometryPreprocessedPdf,
    processing_attempt_id: str,
) -> Path:
    """Retain the selected PDF and bounded before/after test diagnostics."""
    root = Path("/data/output/opencv-diagnostics") / processing_attempt_id
    root.mkdir(parents=True, exist_ok=True)
    _atomic_write(root / "processed.pdf", processed.pdf_bytes)

    with _DIAGNOSTIC_LOCK:
        manifest = _DIAGNOSTIC_MANIFESTS.pop(
            processed.checksum_sha256,
            {
                "version": processed.version,
                "source_sha256": hashlib.sha256(source_pdf_bytes).hexdigest(),
                "output_sha256": processed.checksum_sha256,
                "source_size_bytes": len(source_pdf_bytes),
                "output_size_bytes": processed.byte_size,
                "changed_page_count": processed.changed_page_count,
                "pages": [],
                "paddle_vl_skipped": True,
            },
        )

    source = fitz.open(stream=source_pdf_bytes, filetype="pdf")
    result = fitz.open(stream=processed.pdf_bytes, filetype="pdf")
    try:
        diagnostic_pages = min(
            source.page_count,
            result.page_count,
            _MAX_DIAGNOSTIC_PAGES,
        )
        for page_index in range(diagnostic_pages):
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

    _atomic_write(
        root / "manifest.json",
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8"),
    )
    print(
        "PDF_OPENCV_DIAGNOSTIC_RETAINED "
        f"processing_attempt_id={processing_attempt_id} path={root} "
        f"output_pdf={root / 'processed.pdf'} "
        f"output_size_bytes={processed.byte_size} "
        f"output_sha256={processed.checksum_sha256} "
        f"changed_page_count={processed.changed_page_count}",
        flush=True,
    )
    return root


def _inspect_page_structure(page: fitz.Page) -> _PageStructure:
    try:
        text_chars = len(page.get_text("text").strip())
    except Exception:
        text_chars = 0

    page_area = max(1.0, float(page.rect.width * page.rect.height))
    max_image_coverage = 0.0
    try:
        for image in page.get_images(full=True):
            xref = int(image[0])
            for rect in page.get_image_rects(xref):
                coverage = max(0.0, float(rect.width * rect.height)) / page_area
                max_image_coverage = max(max_image_coverage, coverage)
    except Exception:
        max_image_coverage = 0.0

    born_digital = text_chars >= 80 and max_image_coverage < 0.55
    return _PageStructure(
        text_chars=text_chars,
        max_image_coverage=max_image_coverage,
        born_digital=born_digital,
    )


def _color_features(image: np.ndarray) -> _ColorFeatures:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    high_saturation = (saturation >= 70) & (value >= 35) & (value <= 250)
    high_saturation_ratio = float(np.mean(high_saturation))

    largest_component_ratio = 0.0
    if np.any(high_saturation):
        count, _, stats, _ = cv2.connectedComponentsWithStats(
            high_saturation.astype(np.uint8),
            connectivity=8,
        )
        if count > 1:
            largest_component_ratio = float(
                np.max(stats[1:, cv2.CC_STAT_AREA]) / high_saturation.size
            )

    saturation_p90 = float(np.percentile(saturation, 90))
    color_critical = bool(
        high_saturation_ratio >= 0.12
        or (
            high_saturation_ratio >= 0.05
            and largest_component_ratio >= 0.025
            and saturation_p90 >= 85.0
        )
    )
    return _ColorFeatures(
        high_saturation_ratio=high_saturation_ratio,
        largest_saturated_component_ratio=largest_component_ratio,
        saturation_p90=saturation_p90,
        color_critical=color_critical,
    )


def _build_geometry_candidate(
    image: np.ndarray,
) -> tuple[np.ndarray, _GeometryDiagnostic]:
    height, width = image.shape[:2]
    quad, coverage = _detect_page_quad(image)
    canvas_corners = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    candidate = image
    perspective_distortion = 0.0
    perspective_applied = False

    if quad is not None:
        diagonal = max(1.0, math.hypot(width, height))
        perspective_distortion = float(
            np.mean(np.linalg.norm(quad - canvas_corners, axis=1)) / diagonal
        )
        if 0.40 <= coverage <= 0.995 and perspective_distortion >= 0.006:
            transform = cv2.getPerspectiveTransform(quad, canvas_corners)
            candidate = cv2.warpPerspective(
                image,
                transform,
                (width, height),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(255, 255, 255),
            )
            perspective_applied = True

    angle, confidence = _estimate_text_angle(candidate)
    deskew_applied = bool(confidence >= 0.35 and 0.08 <= abs(angle) <= 5.0)
    if deskew_applied:
        candidate = _rotate_same_canvas(candidate, angle)

    residual_angle, residual_confidence = _estimate_text_angle(candidate)
    return candidate, _GeometryDiagnostic(
        perspective_applied=perspective_applied,
        perspective_confidence=float(coverage),
        perspective_distortion=perspective_distortion,
        deskew_applied=deskew_applied,
        deskew_angle_degrees=float(angle if deskew_applied else 0.0),
        deskew_confidence=float(confidence),
        residual_angle_degrees=float(residual_angle),
        residual_confidence=float(residual_confidence),
    )


def _gate_geometry_candidate(
    original: np.ndarray,
    candidate: np.ndarray,
    diagnostic: _GeometryDiagnostic,
) -> tuple[bool, str, dict[str, object]]:
    if not diagnostic.perspective_applied and not diagnostic.deskew_applied:
        return False, "geometry_not_required", {}

    before = _image_metrics(original)
    after = _image_metrics(candidate)
    edge_ratio = _safe_ratio(after.edge_density, before.edge_density)
    dark_safe = after.dark_ratio <= max(
        before.dark_ratio * 1.70,
        before.dark_ratio + 0.025,
    )
    lines_safe = (
        before.long_line_count < 5
        or after.long_line_count >= math.floor(before.long_line_count * 0.50)
    )
    content_safe = 0.55 <= edge_ratio <= 1.65 and dark_safe and lines_safe

    deskew_improved = True
    if diagnostic.deskew_applied:
        before_abs = abs(diagnostic.deskew_angle_degrees)
        after_abs = abs(diagnostic.residual_angle_degrees)
        deskew_improved = (
            after_abs <= 0.12
            or after_abs + 0.05 < before_abs
            or diagnostic.residual_confidence < 0.20
        )

    perspective_useful = (
        diagnostic.perspective_applied
        and diagnostic.perspective_distortion >= 0.006
    )
    accepted = bool(
        content_safe
        and (
            perspective_useful
            or (diagnostic.deskew_applied and deskew_improved)
        )
    )
    reason = (
        "accepted"
        if accepted
        else "content_guard_rejected"
        if not content_safe
        else "deskew_not_improved"
        if diagnostic.deskew_applied and not deskew_improved
        else "geometry_not_material"
    )
    gate = {
        "before": asdict(before),
        "after": asdict(after),
        "edge_density_ratio": edge_ratio,
        "dark_safe": dark_safe,
        "long_lines_safe": lines_safe,
        "deskew_improved": deskew_improved,
        "perspective_useful": perspective_useful,
    }
    return accepted, reason, gate


def _normalize_background(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    max_side = max(height, width)
    scale = min(1.0, 900.0 / max_side)
    small = cv2.resize(
        gray,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_AREA,
    )
    sigma = max(10.0, min(small.shape) / 18.0)
    small_background = cv2.GaussianBlur(
        small,
        (0, 0),
        sigmaX=sigma,
        sigmaY=sigma,
        borderType=cv2.BORDER_REPLICATE,
    )
    background = cv2.resize(
        small_background,
        (width, height),
        interpolation=cv2.INTER_CUBIC,
    )
    normalized = cv2.divide(gray, np.maximum(background, 1), scale=255)
    normalized = cv2.addWeighted(gray, 0.25, normalized, 0.75, 0)
    texture_reduced = cv2.medianBlur(normalized, 3)
    cleaned = cv2.bilateralFilter(
        texture_reduced,
        d=5,
        sigmaColor=12,
        sigmaSpace=5,
    )
    softly_blurred = cv2.GaussianBlur(cleaned, (0, 0), sigmaX=0.8)
    cleaned = cv2.addWeighted(cleaned, 1.12, softly_blurred, -0.12, 0)

    tone = cleaned.astype(np.float32)
    lift = np.clip((tone - 200.0) / 55.0, 0.0, 1.0)
    tone += (255.0 - tone) * np.power(lift, 1.7) * 0.40
    cleaned = np.clip(tone, 0.0, 255.0).astype(np.uint8)
    cleaned[cleaned >= 250] = 255
    return cv2.cvtColor(cleaned, cv2.COLOR_GRAY2BGR)


def _gate_background_candidate(
    baseline: np.ndarray,
    candidate: np.ndarray,
) -> tuple[bool, str, dict[str, object]]:
    before = _image_metrics(baseline)
    after = _image_metrics(candidate)
    edge_retention = _edge_retention(baseline, candidate)
    edge_ratio = _safe_ratio(after.edge_density, before.edge_density)
    dark_safe = after.dark_ratio <= max(
        before.dark_ratio * 1.70,
        before.dark_ratio + 0.025,
    )
    lines_safe = (
        before.long_line_count < 5
        or after.long_line_count >= math.floor(before.long_line_count * 0.60)
    )
    not_overwhitened = not (
        after.white_ratio > 0.985 and before.white_ratio < 0.80
    )
    content_safe = bool(
        edge_retention >= 0.70
        and 0.60 <= edge_ratio <= 1.45
        and dark_safe
        and lines_safe
        and not_overwhitened
    )

    std_improved = (
        after.background_std <= before.background_std * 0.92
        and before.background_std - after.background_std >= 0.40
    )
    range_improved = (
        after.background_range <= before.background_range * 0.90
        and before.background_range - after.background_range >= 2.0
    )
    white_improved = after.white_ratio >= before.white_ratio + 0.02
    material_improvement = std_improved or range_improved or white_improved

    accepted = bool(content_safe and material_improvement)
    reason = (
        "accepted"
        if accepted
        else "content_guard_rejected"
        if not content_safe
        else "no_material_background_improvement"
    )
    gate = {
        "before": asdict(before),
        "after": asdict(after),
        "edge_retention": edge_retention,
        "edge_density_ratio": edge_ratio,
        "dark_safe": dark_safe,
        "long_lines_safe": lines_safe,
        "not_overwhitened": not_overwhitened,
        "background_std_improved": std_improved,
        "background_range_improved": range_improved,
        "white_ratio_improved": white_improved,
    }
    return accepted, reason, gate


def _image_metrics(image: np.ndarray) -> _ImageMetrics:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    low_frequency = _low_frequency_background(gray)
    background_std = float(np.std(low_frequency))
    p05, p95 = np.percentile(low_frequency, (5, 95))
    background_range = float(p95 - p05)
    white_ratio = float(np.mean(gray >= 248))
    dark_ratio = float(np.mean(gray <= 48))
    edges = cv2.Canny(gray, 60, 160)
    edge_density = float(np.mean(edges > 0))
    long_line_count = _long_line_count(edges)
    return _ImageMetrics(
        background_std=background_std,
        background_range=background_range,
        white_ratio=white_ratio,
        dark_ratio=dark_ratio,
        edge_density=edge_density,
        long_line_count=long_line_count,
    )


def _low_frequency_background(gray: np.ndarray) -> np.ndarray:
    height, width = gray.shape
    scale = min(1.0, 480.0 / max(height, width))
    small = cv2.resize(
        gray,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_AREA,
    )
    sigma = max(8.0, min(small.shape) / 16.0)
    return cv2.GaussianBlur(
        small,
        (0, 0),
        sigmaX=sigma,
        sigmaY=sigma,
        borderType=cv2.BORDER_REPLICATE,
    )


def _edge_retention(before: np.ndarray, after: np.ndarray) -> float:
    before_gray = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    after_gray = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
    before_edges = cv2.Canny(before_gray, 60, 160) > 0
    after_edges = cv2.Canny(after_gray, 60, 160)
    after_dilated = cv2.dilate(
        after_edges,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
    ) > 0
    edge_count = int(np.count_nonzero(before_edges))
    if edge_count == 0:
        return 1.0
    return float(np.count_nonzero(before_edges & after_dilated) / edge_count)


def _long_line_count(edges: np.ndarray) -> int:
    height, width = edges.shape
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 360.0,
        threshold=max(30, min(width, height) // 12),
        minLineLength=max(40, min(width, height) // 7),
        maxLineGap=max(8, min(width, height) // 80),
    )
    return 0 if lines is None else int(len(lines))


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 1e-9:
        return 1.0 if numerator <= 1e-9 else 10.0
    return float(numerator / denominator)


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


def _estimate_text_angle(image: np.ndarray) -> tuple[float, float]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    x0, x1 = int(round(width * 0.10)), int(round(width * 0.90))
    y0, y1 = int(round(height * 0.06)), int(round(height * 0.92))
    roi = gray[y0:y1, x0:x1]
    if roi.size == 0:
        return 0.0, 0.0

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
            (max(30, roi.shape[1] // 5), 1),
        ),
    )
    vertical_rules = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (1, max(30, roi.shape[0] // 8)),
        ),
    )
    text_only = cv2.subtract(
        binary,
        cv2.bitwise_or(horizontal_rules, vertical_rules),
    )
    connected = cv2.morphologyEx(
        text_only,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (max(12, roi.shape[1] // 18), 1),
        ),
    )
    lines = cv2.HoughLinesP(
        connected,
        1,
        np.pi / 1440.0,
        threshold=max(24, roi.shape[1] // 12),
        minLineLength=max(40, roi.shape[1] // 8),
        maxLineGap=max(10, roi.shape[1] // 40),
    )
    if lines is None:
        return 0.0, 0.0

    angles: list[float] = []
    weights: list[float] = []
    for x_start, y_start, x_end, y_end in lines[:, 0, :]:
        angle = math.degrees(
            math.atan2(float(y_end - y_start), float(x_end - x_start))
        )
        while angle <= -90.0:
            angle += 180.0
        while angle > 90.0:
            angle -= 180.0
        length = math.hypot(float(x_end - x_start), float(y_end - y_start))
        if abs(angle) <= 5.0:
            angles.append(angle)
            weights.append(length)
    if not angles:
        return 0.0, 0.0

    angle = _weighted_median(angles, weights)
    total_weight = max(1.0, sum(weights))
    inlier_weight = sum(
        weight
        for candidate, weight in zip(angles, weights, strict=True)
        if abs(candidate - angle) <= 0.75
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


def _insert_raster_page(
    document: fitz.Document,
    source_rect: fitz.Rect,
    image: np.ndarray,
) -> None:
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError("Could not encode OpenCV page output")
    page = document.new_page(
        width=float(source_rect.width),
        height=float(source_rect.height),
    )
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


def _log_page_decision(decision: dict[str, object]) -> None:
    geometry = decision.get("geometry")
    background = decision.get("background")
    color = decision.get("color")
    print(
        "PDF_OPENCV_PAGE_DECISION "
        f"page_number={decision.get('page_number')} "
        f"route={decision.get('route')} "
        f"selected={decision.get('selected')} "
        f"color_critical={color.get('color_critical') if isinstance(color, dict) else None} "
        f"geometry_accepted={geometry.get('accepted') if isinstance(geometry, dict) else None} "
        f"geometry_reason={geometry.get('reason') if isinstance(geometry, dict) else None} "
        f"background_accepted={background.get('accepted') if isinstance(background, dict) else None} "
        f"background_reason={background.get('reason') if isinstance(background, dict) else None}",
        flush=True,
    )


__all__ = [
    "GEOMETRY_PREPROCESSING_VERSION",
    "preprocess_pdf_geometry_opencv",
    "retain_opencv_diagnostics",
]
