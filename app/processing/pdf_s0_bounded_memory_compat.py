"""Keep production-equivalent presentation preprocessing page-bounded in memory.

The staging overlay stack composes orientation, dimension preservation, analysis
fail-open, high-resolution confirmation, and native-text routing around the
classify-first presentation pipeline. This final compatibility layer preserves
those contracts while preventing full-resolution NumPy page rasters from living
in the whole-document decision list.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import fitz  # type: ignore[import]
import numpy as np

from app.processing import pdf_native_text_compat as native
from app.processing import pdf_page_analysis_fail_open_compat as analysis_fail_open
from app.processing import pdf_page_orientation_compat as orientation
from app.processing import pdf_page_orientation_dimensions_compat as dimensions
from app.processing import pdf_page_presentation_bridge as bridge
from app.processing import pdf_page_presentation_preprocess_compat as preprocess

_INSTALLED = False


def _bounded_classify_source_pages(source: fitz.Document) -> list[dict[str, Any]]:
    if _ORIGINAL_CLASSIFY is None:
        raise RuntimeError("bounded-memory classifier compatibility is not installed")
    decisions = _ORIGINAL_CLASSIFY(source)
    # Downstream native/fail-open wrappers may still add legacy raster slots set
    # to None. Remove them at the decision boundary so the durable in-memory
    # representation is metadata-only.
    for decision in decisions:
        decision.pop("geometry_image", None)
        decision.pop("orientation_image", None)
    return decisions


def _bounded_build_ordinary_source(
    source: fitz.Document,
    decisions: list[dict[str, Any]],
) -> tuple[bytes | None, list[dict[str, Any]]]:
    """Build provider pages with at most one reconstructed orientation raster."""
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
            fallback_raster = bool(decision.get("native_text_fallback_raster"))
            orientation_image = orientation._orientation_image_from_decision(
                page,
                decision,
            )

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
                raster = None
                input_mode = "native_text_fallback_raster"
            else:
                ordinary.insert_pdf(
                    source,
                    from_page=page_index,
                    to_page=page_index,
                )
                provider_rect = page.rect
                input_mode = "pdf_page"
            orientation_image = None

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


def _bounded_build_full_render(
    source: fitz.Document,
    decisions: list[dict[str, Any]],
    processed_ordinary: Any | None,
) -> bytes:
    """Recompute only confirmed presentation geometry during final assembly."""
    page_count = len(decisions)
    preprocess._set_s0_work_phase("presentation_render_assembly", page_count)
    if not any(bool(item["skip_ocr"]) for item in decisions):
        if processed_ordinary is None:
            raise RuntimeError("ordinary V4 output is unavailable")
        preprocess._mark_s0_work_page_completed(
            page_number=page_count,
            page_count=page_count,
            route="ordinary_render_reused",
        )
        return processed_ordinary.pdf_bytes

    ordinary_document = (
        fitz.open(stream=processed_ordinary.pdf_bytes, filetype="pdf")
        if processed_ordinary is not None
        else None
    )
    output = fitz.open()
    ordinary_index = 0
    try:
        if source.metadata:
            output.set_metadata(source.metadata)
        for decision in decisions:
            page_number = int(decision["page_number"])
            page_index = int(decision["page_index"])
            if decision["skip_ocr"]:
                if decision.get("native_text_accepted"):
                    # Native-text pages retain their original PDF rendering; no
                    # presentation raster should be regenerated for them.
                    output.insert_pdf(
                        source,
                        from_page=page_index,
                        to_page=page_index,
                    )
                    route = "native_pdf_text_no_op"
                else:
                    geometry_image, geometry = (
                        orientation._presentation_geometry_from_decision(
                            source[page_index],
                            decision,
                        )
                    )
                    decision["geometry"] = geometry
                    bridge._insert_geometry_or_original(
                        output,
                        source,
                        page_index,
                        geometry_image,
                    )
                    geometry_image = None
                    route = (
                        "presentation_geometry_only"
                        if bool(geometry.get("accepted"))
                        else "presentation_original"
                    )
            else:
                if ordinary_document is None:
                    raise RuntimeError("ordinary V4 document is unavailable")
                output.insert_pdf(
                    ordinary_document,
                    from_page=ordinary_index,
                    to_page=ordinary_index,
                )
                ordinary_index += 1
                route = "ordinary_v4_render"
            preprocess._mark_s0_work_page_completed(
                page_number=page_number,
                page_count=page_count,
                route=route,
            )
        return output.tobytes(garbage=4, deflate=True)
    finally:
        output.close()
        if ordinary_document is not None:
            ordinary_document.close()


def _orientation_adjusted_manifest_page(
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    if _ORIGINAL_MANIFEST_PAGE is None:
        raise RuntimeError("bounded-memory manifest compatibility is not installed")
    result = _ORIGINAL_MANIFEST_PAGE(decision)
    if decision.get("native_text_accepted"):
        return result

    geometry = decision.get("geometry")
    geometry = geometry if isinstance(geometry, Mapping) else {}
    orientation_meta = geometry.get("orientation")
    if not isinstance(orientation_meta, Mapping):
        orientation_meta = decision.get("orientation")
    if not isinstance(orientation_meta, Mapping):
        return result
    try:
        degrees = int(
            orientation_meta.get(
                "correction_degrees",
                orientation_meta.get("detected_degrees", 0),
            )
            or 0
        ) % 360
    except (TypeError, ValueError):
        return result
    applied = bool(orientation_meta.get("applied"))
    if not applied or degrees not in {90, 270}:
        return result

    source_width = float(decision["page_width_points"])
    source_height = float(decision["page_height_points"])
    result.update(
        {
            "source_page_width_points": source_width,
            "source_page_height_points": source_height,
            "page_width_points": source_height,
            "page_height_points": source_width,
        }
    )
    return result


_ORIGINAL_CLASSIFY = None
_ORIGINAL_MANIFEST_PAGE = None


def install_s0_bounded_memory_compat() -> None:
    """Install final bounded-memory behavior after all presentation overlays."""
    global _INSTALLED, _ORIGINAL_CLASSIFY, _ORIGINAL_MANIFEST_PAGE
    if _INSTALLED:
        return
    _ORIGINAL_CLASSIFY = preprocess._classify_source_pages
    _ORIGINAL_MANIFEST_PAGE = preprocess._presentation_manifest_page

    preprocess._classify_source_pages = _bounded_classify_source_pages
    preprocess._build_ordinary_source = _bounded_build_ordinary_source
    preprocess._build_full_render = _bounded_build_full_render
    preprocess._presentation_manifest_page = _orientation_adjusted_manifest_page
    native._build_ordinary_source_with_native = _bounded_build_ordinary_source
    _INSTALLED = True


__all__ = ["install_s0_bounded_memory_compat"]
