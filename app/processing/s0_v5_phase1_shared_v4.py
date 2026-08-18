"""Shared-aware OpenCV v4 page coordinator for S0 v5 Phase 1.

The existing v4 helper functions and quality gates remain authoritative.  This
module only avoids recomputing evidence that the already-composed classification
path produced for an equivalent provider page.  Unsafe provider transformations
or missing cache data fall back to the installed v4 helpers.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
from typing import Callable

import fitz  # type: ignore[import]

from app.processing import s0_v5_phase1_shared_cache as shared
from app.processing.pdf_geometry_preprocessing import (
    GeometryPageResult,
    GeometryPreprocessedPdf,
)


_BASE_DELEGATE: Callable[..., GeometryPreprocessedPdf] | None = None
_SAFE_COLOR_REUSE_MODES = frozenset({"pdf_page", "orientation_corrected_raster"})
_SAFE_GEOMETRY_REUSE_MODES = _SAFE_COLOR_REUSE_MODES


def configure(*, base_delegate: Callable[..., GeometryPreprocessedPdf]) -> None:
    global _BASE_DELEGATE
    _BASE_DELEGATE = base_delegate


def preprocess_pdf_geometry_opencv_shared(
    pdf_bytes: bytes,
    *,
    expected_page_count: int | None = None,
    **kwargs: object,
) -> GeometryPreprocessedPdf:
    """Run v4 while reusing only page-equivalent Phase 1 evidence."""
    delegate = _BASE_DELEGATE
    if shared.active_state() is None:
        if delegate is None:
            raise RuntimeError("Phase 1 V4 delegate is unavailable")
        return delegate(
            pdf_bytes,
            expected_page_count=expected_page_count,
            **kwargs,
        )

    from app.processing import pdf_opencv_quality_pipeline as v4

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
            provider_item = shared.provider_item(page)
            original_page_number = (
                int(provider_item["original_page_number"])
                if provider_item is not None
                and isinstance(provider_item.get("original_page_number"), int)
                else None
            )
            provider_input_mode = (
                str(provider_item.get("provider_input_mode") or "pdf_page")
                if provider_item is not None
                else "pdf_page"
            )
            cached = (
                shared.page_cache(original_page_number)
                if original_page_number is not None
                else None
            )
            page_size = (
                max(1, int(round(float(page.rect.width)))),
                max(1, int(round(float(page.rect.height)))),
            )

            # Reuse original-PDF structure only when the provider page is still
            # that PDF page.  Orientation/native fallback rasterization can
            # change born-digital semantics and must be inspected afresh.
            structure = (
                cached.get("structure")
                if provider_input_mode == "pdf_page" and isinstance(cached, dict)
                else None
            )
            if structure is None:
                structure = v4._inspect_page_structure(page)
            else:
                shared.metric("ordinary_structure_cache_hits")

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
                    "phase1_provider_input_mode": provider_input_mode,
                }
                manifest_pages.append(decision)
                v4._log_page_decision(decision)
                continue

            # Discrete rotation preserves color-distribution evidence, while
            # native fallback raster paths are deliberately recomputed.
            color = (
                cached.get("color")
                if provider_input_mode in _SAFE_COLOR_REUSE_MODES
                and isinstance(cached, dict)
                else None
            )
            if color is None:
                preview = v4._render_page_bgr(page, dpi=v4._ANALYSIS_DPI)
                color = v4._color_features(preview)
                preview = None
            else:
                shared.metric("ordinary_color_cache_hits")

            cached_geometry = (
                shared.cached_geometry_for_ordinary(
                    original_page_number,
                    provider_input_mode=provider_input_mode,
                )
                if provider_input_mode in _SAFE_GEOMETRY_REUSE_MODES
                else None
            )
            if cached_geometry is None:
                source_bgr = v4._render_page_bgr(page, dpi=v4._RENDER_DPI)
                geometry_candidate, geometry_diag = v4._build_geometry_candidate(
                    source_bgr
                )
                (
                    geometry_accepted,
                    geometry_reason,
                    geometry_gate,
                ) = v4._gate_geometry_candidate(
                    source_bgr,
                    geometry_candidate,
                    geometry_diag,
                )
                geometry_selected = (
                    geometry_candidate if geometry_accepted else source_bgr
                )
            else:
                (
                    geometry_selected,
                    geometry_diag,
                    geometry_accepted,
                    geometry_reason,
                    geometry_gate,
                ) = cached_geometry

            source_height, source_width = geometry_selected.shape[:2]
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
                background_candidate = v4._normalize_background(geometry_selected)
                (
                    background_accepted,
                    background_reason,
                    background_gate,
                ) = v4._gate_background_candidate(
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
                v4._insert_raster_page(output, page.rect, selected_bgr)
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

            safe_reasons: list[str] = []
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
                source_xres=v4._RENDER_DPI,
                source_yres=v4._RENDER_DPI,
                effective_xdpi=float(v4._RENDER_DPI),
                effective_ydpi=float(v4._RENDER_DPI),
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
                "phase1_provider_input_mode": provider_input_mode,
            }
            manifest_pages.append(decision)
            v4._log_page_decision(decision)

        processed_bytes = output.tobytes(garbage=4, deflate=True)
    finally:
        output.close()
        source.close()

    if changed_page_count == 0:
        processed_bytes = pdf_bytes

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
        "s0_v5_phase1_shared_analysis": True,
    }
    with v4._DIAGNOSTIC_LOCK:
        v4._DIAGNOSTIC_MANIFESTS[checksum] = manifest

    return GeometryPreprocessedPdf(
        pdf_bytes=processed_bytes,
        checksum_sha256=checksum,
        byte_size=len(processed_bytes),
        page_count=len(page_results),
        changed_page_count=changed_page_count,
        pages=tuple(page_results),
        version=v4.GEOMETRY_PREPROCESSING_VERSION,
    )


__all__ = ["configure", "preprocess_pdf_geometry_opencv_shared"]
