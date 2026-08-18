"""Preserve confirmed orientation and page dimensions after native-PDF routing.

The native-text compatibility layer owns the final provider-subset builder so it
can omit accepted native pages and rasterize rejected text layers. This shim
recombines that behavior with the earlier orientation and fail-open contracts:
confirmed ``orientation_image`` rasters remain the provider input, quarter-turn
pages use swapped PDF canvas dimensions so those rasters are never stretched,
and optional pre-OCR geometry or analysis failures retain their page-scoped V4
fail-open state.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import fitz  # type: ignore[import]
import numpy as np

from app.processing import pdf_native_text_compat as native
from app.processing import pdf_page_analysis_fail_open_compat as analysis_fail_open
from app.processing import pdf_page_orientation_dimensions_compat as dimensions
from app.processing import pdf_page_presentation_preprocess_compat as preprocess


_INSTALLED = False


def _build_ordinary_source_preserving_orientation(
    source: fitz.Document,
    decisions: list[dict[str, Any]],
) -> tuple[bytes | None, list[dict[str, Any]]]:
    from app.processing import pdf_opencv_quality_pipeline as v4

    ordinary = fitz.open()
    provider_map: list[dict[str, Any]] = []
    fail_open_pages: dict[int, str] = {}
    analysis_pages: dict[int, str] = {}
    dimensions._ORDINARY_FAIL_OPEN_PAGES.set({})
    analysis_fail_open._ANALYSIS_PROVIDER_PAGES.set({})
    try:
        if source.metadata:
            ordinary.set_metadata(source.metadata)
        for decision in decisions:
            if decision["skip_ocr"]:
                continue

            page_index = int(decision["page_index"])
            page = source[page_index]
            provider_page_index = ordinary.page_count
            orientation_image = decision.get("orientation_image")
            fallback_raster = bool(decision.get("native_text_fallback_raster"))

            if isinstance(orientation_image, np.ndarray):
                provider_rect = dimensions._page_rect_for_raster(
                    page.rect,
                    orientation_image,
                )
                v4._insert_raster_page(
                    ordinary,
                    provider_rect,
                    orientation_image,
                )
                input_mode = (
                    "native_text_fallback_oriented_raster"
                    if fallback_raster
                    else "orientation_corrected_raster"
                )
            elif fallback_raster:
                raster = v4._render_page_bgr(page, dpi=v4._RENDER_DPI)
                provider_rect = page.rect
                v4._insert_raster_page(ordinary, provider_rect, raster)
                input_mode = "native_text_fallback_raster"
            else:
                ordinary.insert_pdf(
                    source,
                    from_page=page_index,
                    to_page=page_index,
                )
                provider_rect = page.rect
                input_mode = "pdf_page"

            decision_reason = decision.get("decision_reason")
            if decision_reason in {
                "pre_ocr_geometry_failed",
                "pre_ocr_analysis_failed",
            }:
                geometry = decision.get("geometry")
                geometry = geometry if isinstance(geometry, Mapping) else {}
                default_error_type = (
                    "AnalysisRenderError"
                    if decision_reason == "pre_ocr_analysis_failed"
                    else "GeometryError"
                )
                error_type = str(
                    geometry.get("error_type") or default_error_type
                )
                fail_open_pages[provider_page_index] = error_type
                if decision_reason == "pre_ocr_analysis_failed":
                    analysis_pages[provider_page_index] = error_type

            provider_map.append(
                {
                    "provider_page_index": provider_page_index,
                    "original_page_index": page_index,
                    "original_page_number": int(decision["page_number"]),
                    "source_unit_id": str(decision["source_unit_id"]),
                    "provider_input_mode": input_mode,
                    "provider_page_width_points": float(provider_rect.width),
                    "provider_page_height_points": float(provider_rect.height),
                }
            )

        if ordinary.page_count == 0:
            dimensions._ORDINARY_FAIL_OPEN_PAGES.set({})
            analysis_fail_open._ANALYSIS_PROVIDER_PAGES.set({})
            return None, provider_map
        ordinary_bytes = ordinary.tobytes(garbage=4, deflate=True)
        dimensions._ORDINARY_FAIL_OPEN_PAGES.set(fail_open_pages)
        analysis_fail_open._ANALYSIS_PROVIDER_PAGES.set(analysis_pages)
        return ordinary_bytes, provider_map
    finally:
        ordinary.close()


def install_native_orientation_preservation_compat() -> None:
    """Install the combined native-text and orientation-safe subset builder."""

    global _INSTALLED
    if _INSTALLED:
        return
    preprocess._build_ordinary_source = (
        _build_ordinary_source_preserving_orientation
    )
    native._build_ordinary_source_with_native = (
        _build_ordinary_source_preserving_orientation
    )
    _INSTALLED = True


__all__ = [
    "install_native_orientation_preservation_compat",
]
