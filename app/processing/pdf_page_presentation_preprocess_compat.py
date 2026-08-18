"""Correct pre-OCR preprocessing order for presentation-page routing.

This compatibility layer replaces the first implementation's whole-document V4
pass.  Page classification and geometry-only review now happen first.  Only
ordinary pages are assembled into the PDF that enters OpenCV v4, so a confirmed
presentation page never reaches the v4 background candidate builder.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
from typing import Any, Mapping

import fitz  # type: ignore[import]

from app.processing import pdf_page_presentation_bridge as bridge
from app.processing.pdf_geometry_preprocessing import (
    GeometryPageResult,
    GeometryPreprocessedPdf,
)

_INSTALLED = False
_VERSION = "pre_ocr_presentation_route_v2"


def _classify_source_pages(source: fitz.Document) -> list[dict[str, object]]:
    from app.processing import pdf_opencv_quality_pipeline as v4

    decisions: list[dict[str, object]] = []
    page_count = source.page_count
    for page_index in range(page_count):
        page_number = page_index + 1
        source_unit_id = bridge._source_unit_id(page_number)
        page = source[page_index]
        analysis_image = bridge._analysis_image(page)
        features = bridge._combined_features(page, analysis_image)
        candidate, candidate_reasons = bridge._is_candidate(
            features,
            first_page=page_index == 0,
            last_page=page_index == page_count - 1,
        )
        bridge._diagnostic(
            "PDF_PAGE_CLASSIFICATION_CANDIDATE",
            source_unit_id=source_unit_id,
            candidate=candidate,
            reason_count=len(candidate_reasons),
        )

        classification = bridge._fallback_classification(
            source_unit_id,
            "not_selected_for_multimodal_review",
        )
        geometry_image = None
        geometry: dict[str, object] = {}
        if candidate:
            # This route calls only the existing V4 geometry candidate and gate.
            # It never invokes the V4 background candidate builder.
            geometry_image, geometry = bridge._geometry_only_page(page)
            classification_image = (
                geometry_image
                if geometry_image is not None
                else v4._render_page_bgr(page, dpi=v4._ANALYSIS_DPI)
            )
            try:
                classification = bridge._classify(
                    bridge._encode_png(classification_image),
                    features,
                    {
                        "source_unit_id": source_unit_id,
                        "page_number": page_number,
                        "page_index": page_index,
                        "page_count": page_count,
                        "is_first_physical_page": page_index == 0,
                        "is_last_physical_page": page_index == page_count - 1,
                        "page_width_points": float(page.rect.width),
                        "page_height_points": float(page.rect.height),
                        "candidate_reasons": list(candidate_reasons),
                    },
                )
            except Exception as exc:
                classification = bridge._fallback_classification(
                    source_unit_id,
                    f"classification_failed:{type(exc).__name__}",
                )
                bridge._diagnostic(
                    "PDF_PAGE_CLASSIFICATION_FALLBACK_TO_OCR",
                    source_unit_id=source_unit_id,
                    reason=type(exc).__name__,
                )
            skip_ocr, decision_reason = bridge._skip_ocr_decision(
                classification,
                features,
            )
        else:
            skip_ocr = False
            decision_reason = "not_a_local_candidate"

        classification = {
            **classification,
            "candidate_features": bridge._json_clone(features),
            "candidate_reasons": list(candidate_reasons),
            "skip_ocr": skip_ocr,
            "decision_reason": decision_reason,
        }
        bridge._diagnostic(
            "PDF_PAGE_CLASSIFICATION_RESULT",
            source_unit_id=source_unit_id,
            page_role=classification["page_role"],
            confidence=classification["confidence"],
            skip_ocr=skip_ocr,
            image_detail=classification["image_detail"],
            cache_hit=classification["cache_hit"],
            input_tokens=classification["input_tokens"],
            output_tokens=classification["output_tokens"],
        )
        if candidate and not skip_ocr and classification["page_role"] in bridge.PRESENTATION_PAGE_ROLES:
            bridge._diagnostic(
                "PDF_PAGE_CLASSIFICATION_FALLBACK_TO_OCR",
                source_unit_id=source_unit_id,
                reason=decision_reason,
            )
        decisions.append(
            {
                "page_index": page_index,
                "page_number": page_number,
                "source_unit_id": source_unit_id,
                "features": features,
                "candidate": candidate,
                "candidate_reasons": candidate_reasons,
                "classification": classification,
                "skip_ocr": skip_ocr,
                "decision_reason": decision_reason,
                "geometry_image": geometry_image,
                "geometry": geometry,
                "page_width_points": float(page.rect.width),
                "page_height_points": float(page.rect.height),
            }
        )
    return decisions


def _build_ordinary_source(
    source: fitz.Document,
    decisions: list[dict[str, object]],
) -> tuple[bytes | None, list[dict[str, object]]]:
    ordinary = fitz.open()
    provider_map: list[dict[str, object]] = []
    try:
        if source.metadata:
            ordinary.set_metadata(source.metadata)
        for decision in decisions:
            if decision["skip_ocr"]:
                continue
            page_index = int(decision["page_index"])
            provider_page_index = ordinary.page_count
            ordinary.insert_pdf(source, from_page=page_index, to_page=page_index)
            provider_map.append(
                {
                    "provider_page_index": provider_page_index,
                    "original_page_index": page_index,
                    "original_page_number": int(decision["page_number"]),
                    "source_unit_id": str(decision["source_unit_id"]),
                }
            )
        if ordinary.page_count == 0:
            return None, provider_map
        return ordinary.tobytes(garbage=4, deflate=True), provider_map
    finally:
        ordinary.close()


def _presentation_manifest_page(decision: Mapping[str, object]) -> dict[str, object]:
    geometry = bridge._json_clone(decision.get("geometry") or {})
    classification = bridge._json_clone(decision["classification"])
    features = bridge._json_clone(decision["features"])
    geometry_selected = bool(geometry.get("accepted"))
    page_manifest = {
        "page_number": int(decision["page_number"]),
        "source_unit_id": str(decision["source_unit_id"]),
        "route": (
            "presentation_geometry_only"
            if geometry_selected
            else "presentation_original"
        ),
        "selected": "geometry" if geometry_selected else "original",
        "structure": {
            "native_text_chars": features["native_text_chars"],
            "maximum_embedded_image_coverage": features[
                "maximum_embedded_image_coverage"
            ],
        },
        "geometry": geometry,
        "background": {
            "attempted": False,
            "accepted": False,
            "reason": "presentation_page_background_skipped",
            "gate": {},
        },
        "page_kind": classification["page_role"],
        "presentation_mode": "source_rendering",
        "ocr_route": "skipped_presentation_image",
        "page_classification": classification,
        "page_width_points": float(decision["page_width_points"]),
        "page_height_points": float(decision["page_height_points"]),
    }
    bridge._diagnostic(
        "PDF_PAGE_PRESENTATION_GEOMETRY_SELECTED",
        source_unit_id=page_manifest["source_unit_id"],
        selected=page_manifest["selected"],
    )
    bridge._diagnostic(
        "PDF_PAGE_BACKGROUND_SKIPPED",
        source_unit_id=page_manifest["source_unit_id"],
        reason="presentation_page_background_skipped",
    )
    bridge._diagnostic(
        "PDF_PAGE_OCR_SKIPPED",
        source_unit_id=page_manifest["source_unit_id"],
        page_kind=page_manifest["page_kind"],
    )
    return page_manifest


def _ordinary_manifest_page(
    decision: Mapping[str, object],
    subset_page_manifest: Mapping[str, object] | None,
) -> dict[str, object]:
    page_number = int(decision["page_number"])
    result = bridge._json_clone(
        subset_page_manifest
        or {
            "page_number": page_number,
            "route": "v4_manifest_unavailable",
            "selected": "original",
        }
    )
    result.update(
        {
            "page_number": page_number,
            "source_unit_id": str(decision["source_unit_id"]),
            "ocr_route": "modal_paddle_ocr",
            "page_classification": bridge._json_clone(
                decision["classification"]
            ),
            "page_width_points": float(decision["page_width_points"]),
            "page_height_points": float(decision["page_height_points"]),
        }
    )
    return result


def _presentation_geometry_result(
    decision: Mapping[str, object],
) -> GeometryPageResult:
    geometry = decision.get("geometry")
    geometry = geometry if isinstance(geometry, Mapping) else {}
    width = max(1, int(round(float(decision["page_width_points"]))))
    height = max(1, int(round(float(decision["page_height_points"]))))
    accepted = bool(geometry.get("accepted"))
    return GeometryPageResult(
        page_index=int(decision["page_index"]),
        applied_steps=tuple(
            str(value) for value in geometry.get("applied_steps", [])
        ),
        deskew_angle_degrees=float(
            geometry.get("deskew_angle_degrees") or 0.0
        ),
        deskew_confidence=float(geometry.get("deskew_confidence") or 0.0),
        perspective_confidence=float(
            geometry.get("perspective_confidence") or 0.0
        ),
        perspective_distortion=float(
            geometry.get("perspective_distortion") or 0.0
        ),
        input_size=(width, height),
        output_size=(width, height),
        fallback_used=not accepted,
        safe_reason=str(
            geometry.get("reason")
            or ("presentation_geometry_selected" if accepted else "presentation_original_selected")
        ),
        route=(
            "presentation_geometry_only"
            if accepted
            else "presentation_original"
        ),
        source_kind="pdf_page",
        residual_angle_degrees=float(
            geometry.get("residual_angle_degrees") or 0.0
        ),
        residual_confidence=float(
            geometry.get("residual_confidence") or 0.0
        ),
    )


def _build_full_render(
    source: fitz.Document,
    decisions: list[dict[str, object]],
    processed_ordinary: GeometryPreprocessedPdf | None,
) -> bytes:
    if not any(bool(item["skip_ocr"]) for item in decisions):
        if processed_ordinary is None:
            raise RuntimeError("ordinary V4 output is unavailable")
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
            if decision["skip_ocr"]:
                bridge._insert_geometry_or_original(
                    output,
                    source,
                    int(decision["page_index"]),
                    decision.get("geometry_image"),
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
        return output.tobytes(garbage=4, deflate=True)
    finally:
        output.close()
        if ordinary_document is not None:
            ordinary_document.close()


def _full_preprocessing_result(
    decisions: list[dict[str, object]],
    processed_ordinary: GeometryPreprocessedPdf | None,
    render_bytes: bytes,
    render_checksum: str,
) -> GeometryPreprocessedPdf:
    ordinary_results = list(processed_ordinary.pages) if processed_ordinary else []
    ordinary_position = 0
    results: list[GeometryPageResult] = []
    for decision in decisions:
        if decision["skip_ocr"]:
            results.append(_presentation_geometry_result(decision))
            continue
        if ordinary_position >= len(ordinary_results):
            raise RuntimeError("ordinary V4 page result is missing")
        result = ordinary_results[ordinary_position]
        ordinary_position += 1
        results.append(
            replace(result, page_index=int(decision["page_index"]))
        )
    return GeometryPreprocessedPdf(
        pdf_bytes=render_bytes,
        checksum_sha256=render_checksum,
        byte_size=len(render_bytes),
        page_count=len(decisions),
        changed_page_count=sum(
            1
            for result in results
            if result.route
            not in {
                "born_digital_no_op",
                "color_critical_no_op",
                "quality_gate_original",
                "presentation_original",
            }
        ),
        pages=tuple(results),
        version=_VERSION,
    )


def prepare_presentation_provider_input_v2(
    *,
    storage: Any,
    source_pdf_bytes: bytes,
    original_filename: str | None,
    processing_attempt_id: str,
    expected_page_count: int | None = None,
) -> bridge.PresentationProviderInput:
    """Classify first, then run V4 on ordinary pages only."""

    from app.processing import pdf_geometry_integration as integration
    from app.processing import pdf_opencv_quality_pipeline as v4

    if not isinstance(source_pdf_bytes, bytes) or not source_pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("source_pdf_bytes must contain a PDF")
    bridge._diagnostic(
        "PDF_PAGE_CLASSIFICATION_PLANNED",
        processing_attempt_id=processing_attempt_id,
    )
    source = fitz.open(stream=source_pdf_bytes, filetype="pdf")
    try:
        page_count = source.page_count
        if page_count <= 0:
            raise ValueError("PDF must contain at least one page")
        if expected_page_count is not None and page_count != int(expected_page_count):
            raise ValueError("PDF page count does not match upload metadata")

        decisions = _classify_source_pages(source)
        ordinary_source_bytes, provider_map = _build_ordinary_source(
            source,
            decisions,
        )
        provider_page_count = len(provider_map)
        presentation_count = page_count - provider_page_count

        processed_ordinary: GeometryPreprocessedPdf | None = None
        subset_manifest: dict[str, object] = {
            "version": v4.GEOMETRY_PREPROCESSING_VERSION,
            "pages": [],
        }
        subset_pages: dict[int, dict[str, object]] = {}
        if ordinary_source_bytes is not None:
            processed_ordinary = v4.preprocess_pdf_geometry_opencv(
                ordinary_source_bytes,
                expected_page_count=provider_page_count,
            )
            integration.retain_opencv_diagnostics(
                source_pdf_bytes=ordinary_source_bytes,
                processed=processed_ordinary,
                processing_attempt_id=processing_attempt_id,
            )
            subset_manifest = bridge._v4_manifest(processed_ordinary)
            subset_pages = bridge._v4_page_map(subset_manifest)

        page_entries: list[dict[str, object]] = []
        ordinary_position = 0
        for decision in decisions:
            if decision["skip_ocr"]:
                page_entries.append(_presentation_manifest_page(decision))
            else:
                ordinary_position += 1
                page_entries.append(
                    _ordinary_manifest_page(
                        decision,
                        subset_pages.get(ordinary_position),
                    )
                )

        render_bytes = _build_full_render(
            source,
            decisions,
            processed_ordinary,
        )
        render_checksum = hashlib.sha256(render_bytes).hexdigest()
        render_put = storage.put(
            render_bytes,
            bridge._render_reference(processing_attempt_id, render_checksum),
            expected_size=len(render_bytes),
            expected_sha256=render_checksum,
        )

        if processed_ordinary is None:
            # No provider request is issued. Reuse the retained rendering object
            # only to keep the grant wrapper's storage contract valid.
            provider_put = render_put
        elif presentation_count == 0:
            provider_put = render_put
        else:
            provider_put = storage.put(
                processed_ordinary.pdf_bytes,
                bridge._provider_reference(
                    processing_attempt_id,
                    processed_ordinary.checksum_sha256,
                ),
                expected_size=processed_ordinary.byte_size,
                expected_sha256=processed_ordinary.checksum_sha256,
            )

        manifest = {
            "version": _VERSION,
            "ordinary_v4_version": v4.GEOMETRY_PREPROCESSING_VERSION,
            "ordinary_v4_manifest": subset_manifest,
            "render_pdf_sha256": render_put.checksum_sha256,
            "provider_input_sha256": provider_put.checksum_sha256,
            "page_count": page_count,
            "provider_page_count": provider_page_count,
            "presentation_page_count": presentation_count,
            "pages": page_entries,
            "provider_page_map": provider_map,
        }
        bridge._register_manifest(
            processing_attempt_id,
            render_put.checksum_sha256,
            manifest,
        )
        bridge._diagnostic(
            "PDF_PROVIDER_PAGE_MAP_CREATED",
            processing_attempt_id=processing_attempt_id,
            original_page_count=page_count,
            provider_page_count=provider_page_count,
            presentation_page_count=presentation_count,
        )

        preprocessing = _full_preprocessing_result(
            decisions,
            processed_ordinary,
            render_bytes,
            render_put.checksum_sha256,
        )
        stem = Path(original_filename or "document.pdf").stem or "document"
        return bridge.PresentationProviderInput(
            processing_attempt_id=processing_attempt_id,
            storage_reference=render_put.reference,
            checksum_sha256=render_put.checksum_sha256,
            byte_size=render_put.byte_size,
            media_type="application/pdf",
            filename=f"{stem}.presentation-render.pdf",
            preprocessing=preprocessing,
            provider_storage_reference=provider_put.reference,
            provider_checksum_sha256=provider_put.checksum_sha256,
            provider_byte_size=provider_put.byte_size,
            provider_filename=f"{stem}.ordinary-pages.pdf",
            provider_page_count=provider_page_count,
            provider_page_map=tuple(provider_map),
            presentation_manifest=bridge._json_clone(manifest),
        )
    finally:
        source.close()


def install_preprocess_order_compat() -> None:
    """Install the classify-first ordinary-page-only V4 preprocessing route."""

    global _INSTALLED
    if _INSTALLED:
        return
    from app.processing import pdf_geometry_integration as integration

    bridge.prepare_presentation_provider_input = (
        prepare_presentation_provider_input_v2
    )
    integration.prepare_geometry_provider_input = (
        prepare_presentation_provider_input_v2
    )
    _INSTALLED = True


__all__ = [
    "install_preprocess_order_compat",
    "prepare_presentation_provider_input_v2",
]
