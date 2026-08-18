"""Preserve rotated-page dimensions and fail open on pre-OCR render errors."""
from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import replace
import hashlib
from typing import Any, Callable

import fitz  # type: ignore[import]
import numpy as np

from app.processing import pdf_page_orientation_compat as orientation
from app.processing import pdf_page_presentation_bridge as bridge
from app.processing import pdf_page_presentation_preprocess_compat as preprocess

_INSTALLED = False
_OriginalPresentationManifestPage = preprocess._presentation_manifest_page
_OriginalClassifySourcePages = orientation._classify_source_pages_oriented
_OriginalOrientedGeometry: Callable[..., Any] | None = None
_OriginalPageClassifier: Callable[..., Any] | None = None
_OriginalV4Preprocess: Callable[..., Any] | None = None
_GEOMETRY_FAILURES: ContextVar[dict[str, str]] = ContextVar(
    "pre_ocr_orientation_geometry_failures",
    default={},
)
_ORDINARY_FAIL_OPEN_PAGES: ContextVar[dict[int, str]] = ContextVar(
    "pre_ocr_ordinary_fail_open_pages",
    default={},
)


class _PreOcrGeometryUnavailable(RuntimeError):
    """Stop only the optional presentation classifier after geometry failure."""


def _page_rect_for_raster(
    source_rect: fitz.Rect,
    raster: np.ndarray,
) -> fitz.Rect:
    """Return the source page dimensions, swapped for a quarter-turn raster."""

    if raster.ndim < 2:
        raise ValueError("raster must have height and width dimensions")
    raster_height, raster_width = raster.shape[:2]
    if raster_width <= 0 or raster_height <= 0:
        raise ValueError("raster dimensions must be positive")

    source_width = float(source_rect.width)
    source_height = float(source_rect.height)
    if source_width <= 0 or source_height <= 0:
        raise ValueError("source page dimensions must be positive")

    source_is_landscape = source_width > source_height
    source_is_portrait = source_height > source_width
    raster_is_landscape = raster_width > raster_height
    raster_is_portrait = raster_height > raster_width
    quarter_turn = bool(
        (source_is_landscape and raster_is_portrait)
        or (source_is_portrait and raster_is_landscape)
    )
    if quarter_turn:
        return fitz.Rect(0.0, 0.0, source_height, source_width)
    return fitz.Rect(0.0, 0.0, source_width, source_height)


def _presentation_render_rect(
    decision: Mapping[str, object],
) -> fitz.Rect:
    """Return the exact canvas used for a skipped presentation-page rendering."""

    source_rect = fitz.Rect(
        0.0,
        0.0,
        float(decision["page_width_points"]),
        float(decision["page_height_points"]),
    )
    geometry_image = decision.get("geometry_image")
    if isinstance(geometry_image, np.ndarray):
        return _page_rect_for_raster(source_rect, geometry_image)
    return source_rect


def _presentation_manifest_page_preserving_dimensions(
    decision: Mapping[str, object],
) -> dict[str, object]:
    """Report the orientation-adjusted render dimensions in synthetic raw pages."""

    result = _OriginalPresentationManifestPage(decision)
    source_width = float(decision["page_width_points"])
    source_height = float(decision["page_height_points"])
    render_rect = _presentation_render_rect(decision)
    result.update(
        {
            "source_page_width_points": source_width,
            "source_page_height_points": source_height,
            "page_width_points": float(render_rect.width),
            "page_height_points": float(render_rect.height),
        }
    )
    return result


def _geometry_failure_metadata(
    detected_orientation: object,
    exc: BaseException,
) -> dict[str, object]:
    correction = int(getattr(detected_orientation, "correction_degrees", 0) or 0)
    return {
        "accepted": False,
        "reason": "pre_ocr_geometry_failed",
        "gate": {},
        "v4_geometry_accepted": False,
        "applied_steps": [],
        "error_type": type(exc).__name__,
        "orientation": {
            "detected_degrees": correction,
            "correction_degrees": correction,
            "applied": False,
            "confidence": float(
                getattr(detected_orientation, "confidence", 0.0) or 0.0
            ),
            "source": str(getattr(detected_orientation, "source", "unknown")),
            "native_text_chars": int(
                getattr(detected_orientation, "native_text_chars", 0) or 0
            ),
            "image_score": float(
                getattr(detected_orientation, "image_score", 0.0) or 0.0
            ),
        },
    }


def _oriented_geometry_fail_open(
    page: fitz.Page,
    detected_orientation: object,
):
    """Convert optional geometry failures into an ordinary-OCR decision."""

    if _OriginalOrientedGeometry is None:
        raise RuntimeError("orientation geometry compatibility is not installed")
    try:
        return _OriginalOrientedGeometry(page, detected_orientation)
    except Exception as exc:
        source_unit_id = bridge._source_unit_id(int(page.number) + 1)
        failures = dict(_GEOMETRY_FAILURES.get())
        failures[source_unit_id] = type(exc).__name__
        _GEOMETRY_FAILURES.set(failures)
        bridge._diagnostic(
            "PDF_PAGE_CLASSIFICATION_FALLBACK_TO_OCR",
            source_unit_id=source_unit_id,
            reason=f"pre_ocr_geometry_failed:{type(exc).__name__}",
        )
        return None, _geometry_failure_metadata(detected_orientation, exc), None


def _classify_after_geometry_guard(
    png_bytes: bytes,
    features: Mapping[str, object],
    context: Mapping[str, object],
):
    """Do not call the optional classifier when its geometry render failed."""

    source_unit_id = str(context.get("source_unit_id") or "")
    failure = _GEOMETRY_FAILURES.get().get(source_unit_id)
    if failure:
        raise _PreOcrGeometryUnavailable(failure)
    if _OriginalPageClassifier is None:
        raise RuntimeError("page classifier compatibility is not installed")
    return _OriginalPageClassifier(png_bytes, features, context)


def _classify_source_pages_fail_open(
    source: fitz.Document,
) -> list[dict[str, object]]:
    """Keep render-limit and geometry errors inside the optional pre-OCR route."""

    token = _GEOMETRY_FAILURES.set({})
    try:
        decisions = _OriginalClassifySourcePages(source)
        failures = dict(_GEOMETRY_FAILURES.get())
        for decision in decisions:
            source_unit_id = str(decision.get("source_unit_id") or "")
            failure = failures.get(source_unit_id)
            if not failure:
                continue
            classification = decision.get("classification")
            classification = (
                dict(classification) if isinstance(classification, Mapping) else {}
            )
            classification.update(
                {
                    "page_role": "unknown",
                    "confidence": 0.0,
                    "reason_codes": [f"pre_ocr_geometry_failed:{failure}"],
                    "provider": "none",
                    "skip_ocr": False,
                    "decision_reason": "pre_ocr_geometry_failed",
                }
            )
            decision.update(
                {
                    "classification": classification,
                    "skip_ocr": False,
                    "decision_reason": "pre_ocr_geometry_failed",
                    "geometry_image": None,
                    "orientation_image": None,
                }
            )
        return decisions
    finally:
        _GEOMETRY_FAILURES.reset(token)


def _build_ordinary_source_preserving_dimensions(
    source: fitz.Document,
    decisions: list[dict[str, object]],
) -> tuple[bytes | None, list[dict[str, object]]]:
    """Build the ordinary-page PDF without stretching rotated body pages."""

    from app.processing import pdf_opencv_quality_pipeline as v4

    ordinary = fitz.open()
    provider_map: list[dict[str, object]] = []
    fail_open_pages: dict[int, str] = {}
    try:
        if source.metadata:
            ordinary.set_metadata(source.metadata)
        for decision in decisions:
            if decision["skip_ocr"]:
                continue
            page_index = int(decision["page_index"])
            provider_page_index = ordinary.page_count
            orientation_image = decision.get("orientation_image")
            if isinstance(orientation_image, np.ndarray):
                v4._insert_raster_page(
                    ordinary,
                    _page_rect_for_raster(
                        source[page_index].rect,
                        orientation_image,
                    ),
                    orientation_image,
                )
            else:
                ordinary.insert_pdf(
                    source,
                    from_page=page_index,
                    to_page=page_index,
                )
            if decision.get("decision_reason") == "pre_ocr_geometry_failed":
                geometry = decision.get("geometry")
                geometry = geometry if isinstance(geometry, Mapping) else {}
                fail_open_pages[provider_page_index] = str(
                    geometry.get("error_type") or "GeometryError"
                )
            provider_map.append(
                {
                    "provider_page_index": provider_page_index,
                    "original_page_index": page_index,
                    "original_page_number": int(decision["page_number"]),
                    "source_unit_id": str(decision["source_unit_id"]),
                }
            )
        if ordinary.page_count == 0:
            _ORDINARY_FAIL_OPEN_PAGES.set({})
            return None, provider_map
        ordinary_bytes = ordinary.tobytes(garbage=4, deflate=True)
        _ORDINARY_FAIL_OPEN_PAGES.set(fail_open_pages)
        return ordinary_bytes, provider_map
    finally:
        ordinary.close()


def _single_page_pdf_bytes(source: fitz.Document, page_index: int) -> bytes:
    single = fitz.open()
    try:
        single.insert_pdf(source, from_page=page_index, to_page=page_index)
        return single.tobytes(garbage=4, deflate=True)
    finally:
        single.close()


def _preprocess_pdf_geometry_fail_open(
    pdf_bytes: bytes,
    *,
    expected_page_count: int | None = None,
    **kwargs: object,
):
    """Bypass V4 rasterization only for pages whose pre-OCR render already failed."""

    from app.processing.pdf_geometry_preprocessing import (
        GeometryPageResult,
        GeometryPreprocessedPdf,
    )
    from app.processing import pdf_opencv_quality_pipeline as v4

    fail_open_pages = dict(_ORDINARY_FAIL_OPEN_PAGES.get())
    _ORDINARY_FAIL_OPEN_PAGES.set({})
    if not fail_open_pages:
        if _OriginalV4Preprocess is None:
            raise RuntimeError("V4 preprocessing compatibility is not installed")
        return _OriginalV4Preprocess(
            pdf_bytes,
            expected_page_count=expected_page_count,
            **kwargs,
        )

    if not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("pdf_bytes must contain a PDF")
    if _OriginalV4Preprocess is None:
        raise RuntimeError("V4 preprocessing compatibility is not installed")

    source = fitz.open(stream=pdf_bytes, filetype="pdf")
    output = fitz.open()
    results: list[GeometryPageResult] = []
    manifest_pages: list[dict[str, object]] = []
    changed_page_count = 0
    try:
        page_count = int(source.page_count)
        if page_count <= 0:
            raise ValueError("PDF must contain at least one page")
        if expected_page_count is not None and page_count != int(expected_page_count):
            raise ValueError("PDF page count does not match upload metadata")
        if any(index < 0 or index >= page_count for index in fail_open_pages):
            raise ValueError("fail-open provider page index is out of range")
        if source.metadata:
            output.set_metadata(source.metadata)

        for page_index in range(page_count):
            page_number = page_index + 1
            failure_type = fail_open_pages.get(page_index)
            if failure_type:
                page = source[page_index]
                output.insert_pdf(source, from_page=page_index, to_page=page_index)
                width = max(1, int(round(float(page.rect.width))))
                height = max(1, int(round(float(page.rect.height))))
                results.append(
                    GeometryPageResult(
                        page_index=page_index,
                        applied_steps=(),
                        deskew_angle_degrees=0.0,
                        deskew_confidence=0.0,
                        perspective_confidence=0.0,
                        perspective_distortion=0.0,
                        input_size=(width, height),
                        output_size=(width, height),
                        fallback_used=True,
                        safe_reason=f"pre_ocr_geometry_failed:{failure_type}",
                        route="quality_gate_original",
                        source_kind="pdf_page",
                    )
                )
                manifest_pages.append(
                    {
                        "page_number": page_number,
                        "route": "quality_gate_original",
                        "selected": "original",
                        "structure": {},
                        "geometry": {
                            "accepted": False,
                            "reason": "pre_ocr_geometry_failed",
                            "error_type": failure_type,
                            "gate": {},
                        },
                        "background": {
                            "attempted": False,
                            "accepted": False,
                            "reason": "pre_ocr_geometry_failed_v4_bypassed",
                            "gate": {},
                        },
                        "applied_steps": [],
                    }
                )
                bridge._diagnostic(
                    "PDF_OPENCV_PAGE_FAIL_OPEN",
                    page_number=page_number,
                    reason=f"pre_ocr_geometry_failed:{failure_type}",
                )
                continue

            single_bytes = _single_page_pdf_bytes(source, page_index)
            processed = _OriginalV4Preprocess(
                single_bytes,
                expected_page_count=1,
                **kwargs,
            )
            processed_document = fitz.open(
                stream=processed.pdf_bytes,
                filetype="pdf",
            )
            try:
                output.insert_pdf(processed_document, from_page=0, to_page=0)
            finally:
                processed_document.close()
            if len(processed.pages) != 1:
                raise RuntimeError("single-page V4 result is invalid")
            results.append(replace(processed.pages[0], page_index=page_index))
            changed_page_count += int(processed.changed_page_count)
            with v4._DIAGNOSTIC_LOCK:
                single_manifest = v4._DIAGNOSTIC_MANIFESTS.pop(
                    processed.checksum_sha256,
                    None,
                )
            pages = (
                single_manifest.get("pages")
                if isinstance(single_manifest, Mapping)
                else None
            )
            entry = (
                dict(pages[0])
                if isinstance(pages, list)
                and pages
                and isinstance(pages[0], Mapping)
                else {
                    "route": processed.pages[0].route,
                    "selected": "original",
                }
            )
            entry["page_number"] = page_number
            manifest_pages.append(entry)

        processed_bytes = output.tobytes(garbage=4, deflate=True)
    finally:
        output.close()
        source.close()

    checksum = hashlib.sha256(processed_bytes).hexdigest()
    manifest = {
        "version": v4.GEOMETRY_PREPROCESSING_VERSION,
        "source_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "output_sha256": checksum,
        "source_size_bytes": len(pdf_bytes),
        "output_size_bytes": len(processed_bytes),
        "changed_page_count": changed_page_count,
        "pages": manifest_pages,
        "paddle_vl_skipped": True,
    }
    with v4._DIAGNOSTIC_LOCK:
        v4._DIAGNOSTIC_MANIFESTS[checksum] = manifest
    return GeometryPreprocessedPdf(
        pdf_bytes=processed_bytes,
        checksum_sha256=checksum,
        byte_size=len(processed_bytes),
        page_count=len(results),
        changed_page_count=changed_page_count,
        pages=tuple(results),
        version=v4.GEOMETRY_PREPROCESSING_VERSION,
    )


def _insert_geometry_or_original_preserving_dimensions(
    output: fitz.Document,
    source: fitz.Document,
    page_index: int,
    geometry_bgr: np.ndarray | None,
) -> None:
    """Insert a presentation rendering on a canvas matching its orientation."""

    from app.processing import pdf_opencv_quality_pipeline as v4

    if geometry_bgr is None:
        output.insert_pdf(source, from_page=page_index, to_page=page_index)
        return
    v4._insert_raster_page(
        output,
        _page_rect_for_raster(source[page_index].rect, geometry_bgr),
        geometry_bgr,
    )


def install_orientation_dimensions_compat() -> None:
    """Install dimension-safe insertion, metadata, and geometry fail-open routing."""

    global _INSTALLED
    global _OriginalOrientedGeometry, _OriginalPageClassifier, _OriginalV4Preprocess
    if _INSTALLED:
        return
    from app.processing import pdf_opencv_quality_pipeline as v4

    _OriginalOrientedGeometry = orientation._oriented_geometry
    _OriginalPageClassifier = bridge._classify
    _OriginalV4Preprocess = v4.preprocess_pdf_geometry_opencv
    orientation._oriented_geometry = _oriented_geometry_fail_open
    bridge._classify = _classify_after_geometry_guard
    orientation._classify_source_pages_oriented = _classify_source_pages_fail_open
    orientation._build_ordinary_source_oriented = (
        _build_ordinary_source_preserving_dimensions
    )
    preprocess._classify_source_pages = _classify_source_pages_fail_open
    preprocess._build_ordinary_source = (
        _build_ordinary_source_preserving_dimensions
    )
    preprocess._presentation_manifest_page = (
        _presentation_manifest_page_preserving_dimensions
    )
    bridge._insert_geometry_or_original = (
        _insert_geometry_or_original_preserving_dimensions
    )
    v4.preprocess_pdf_geometry_opencv = _preprocess_pdf_geometry_fail_open
    _INSTALLED = True


__all__ = [
    "install_orientation_dimensions_compat",
]
