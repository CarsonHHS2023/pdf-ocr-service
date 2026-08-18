"""Fail open for analysis rendering and preserve V4 manifests through retention."""
from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import replace
from typing import Any, Callable

import fitz  # type: ignore[import]
import numpy as np

from app.processing import pdf_page_orientation_compat as orientation
from app.processing import pdf_page_orientation_dimensions_compat as dimensions
from app.processing import pdf_page_presentation_bridge as bridge
from app.processing import pdf_page_presentation_preprocess_compat as preprocess

_INSTALLED = False
_OriginalAnalysisImage: Callable[..., Any] | None = None
_OriginalOrientedGeometry: Callable[..., Any] | None = None
_OriginalClassifier: Callable[..., Any] | None = None
_OriginalClassifySourcePages: Callable[..., Any] | None = None
_OriginalBuildOrdinarySource: Callable[..., Any] | None = None
_OriginalV4Preprocess: Callable[..., Any] | None = None
_OriginalRetainDiagnostics: Callable[..., Any] | None = None
_OriginalV4Manifest: Callable[..., Any] | None = None
_FAIL_OPEN_ACTIVE: ContextVar[bool] = ContextVar(
    "pre_ocr_analysis_fail_open_active",
    default=False,
)
_ANALYSIS_FAILURES: ContextVar[dict[str, str]] = ContextVar(
    "pre_ocr_analysis_render_failures",
    default={},
)
_ANALYSIS_PROVIDER_PAGES: ContextVar[dict[int, str]] = ContextVar(
    "pre_ocr_analysis_provider_pages",
    default={},
)
_CAPTURED_V4_MANIFEST: ContextVar[
    tuple[str, dict[str, object]] | None
] = ContextVar(
    "pre_ocr_captured_v4_manifest",
    default=None,
)


class _PreOcrAnalysisUnavailable(RuntimeError):
    """Stop only the optional classifier after analysis rendering failed."""


def _source_unit_id(page: fitz.Page) -> str:
    return bridge._source_unit_id(int(page.number) + 1)


def _analysis_failure_metadata(
    detected_orientation: object,
    error_type: str,
) -> dict[str, object]:
    correction = int(getattr(detected_orientation, "correction_degrees", 0) or 0)
    return {
        "accepted": False,
        "reason": "pre_ocr_analysis_failed",
        "gate": {},
        "v4_geometry_accepted": False,
        "applied_steps": [],
        "error_type": error_type,
        "analysis": {
            "attempted": True,
            "accepted": False,
            "reason": "pre_ocr_analysis_failed",
            "error_type": error_type,
        },
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


def _analysis_image_fail_open(page: fitz.Page) -> np.ndarray:
    """Return a safe feature placeholder only inside pre-OCR page routing."""

    if _OriginalAnalysisImage is None:
        raise RuntimeError("analysis rendering compatibility is not installed")
    try:
        return _OriginalAnalysisImage(page)
    except Exception as exc:
        if not _FAIL_OPEN_ACTIVE.get():
            raise
        source_unit_id = _source_unit_id(page)
        failures = dict(_ANALYSIS_FAILURES.get())
        failures[source_unit_id] = type(exc).__name__
        _ANALYSIS_FAILURES.set(failures)
        bridge._diagnostic(
            "PDF_PAGE_CLASSIFICATION_FALLBACK_TO_OCR",
            source_unit_id=source_unit_id,
            reason=f"pre_ocr_analysis_failed:{type(exc).__name__}",
        )
        # The original loop still needs a valid BGR image to finish native/local
        # feature bookkeeping and emit a page decision. This image is never
        # submitted to the classifier because the guards below see the failure.
        return np.full((32, 32, 3), 255, dtype=np.uint8)


def _oriented_geometry_after_analysis_guard(
    page: fitz.Page,
    detected_orientation: object,
):
    """Do not attempt a higher-DPI geometry render after analysis already failed."""

    failure = _ANALYSIS_FAILURES.get().get(_source_unit_id(page))
    if failure:
        return (
            None,
            _analysis_failure_metadata(detected_orientation, failure),
            None,
        )
    if _OriginalOrientedGeometry is None:
        raise RuntimeError("orientation geometry compatibility is not installed")
    return _OriginalOrientedGeometry(page, detected_orientation)


def _classify_after_analysis_guard(
    png_bytes: bytes,
    features: Mapping[str, object],
    context: Mapping[str, object],
):
    """Prevent OpenAI classification when the page preview was unavailable."""

    source_unit_id = str(context.get("source_unit_id") or "")
    failure = _ANALYSIS_FAILURES.get().get(source_unit_id)
    if failure:
        raise _PreOcrAnalysisUnavailable(failure)
    if _OriginalClassifier is None:
        raise RuntimeError("page classifier compatibility is not installed")
    return _OriginalClassifier(png_bytes, features, context)


def _classify_source_pages_analysis_fail_open(
    source: fitz.Document,
) -> list[dict[str, object]]:
    """Convert per-page analysis failures into ordinary-OCR decisions."""

    if _OriginalClassifySourcePages is None:
        raise RuntimeError("page classification compatibility is not installed")
    active_token = _FAIL_OPEN_ACTIVE.set(True)
    failures_token = _ANALYSIS_FAILURES.set({})
    try:
        decisions = _OriginalClassifySourcePages(source)
        failures = dict(_ANALYSIS_FAILURES.get())
        for decision in decisions:
            source_unit_id = str(decision.get("source_unit_id") or "")
            failure = failures.get(source_unit_id)
            if not failure:
                continue
            classification = decision.get("classification")
            classification = (
                dict(classification) if isinstance(classification, Mapping) else {}
            )
            features = decision.get("features")
            features = dict(features) if isinstance(features, Mapping) else {}
            features.update(
                {
                    "analysis_render_failed": True,
                    "analysis_render_error_type": failure,
                }
            )
            classification.update(
                {
                    "page_role": "unknown",
                    "confidence": 0.0,
                    "reason_codes": [f"pre_ocr_analysis_failed:{failure}"],
                    "provider": "none",
                    "skip_ocr": False,
                    "decision_reason": "pre_ocr_analysis_failed",
                    "candidate_features": bridge._json_clone(features),
                }
            )
            geometry = decision.get("geometry")
            geometry = dict(geometry) if isinstance(geometry, Mapping) else {}
            if geometry.get("reason") != "pre_ocr_analysis_failed":
                geometry.update(
                    {
                        "accepted": False,
                        "reason": "pre_ocr_analysis_failed",
                        "gate": {},
                        "v4_geometry_accepted": False,
                        "applied_steps": [],
                        "error_type": failure,
                        "analysis": {
                            "attempted": True,
                            "accepted": False,
                            "reason": "pre_ocr_analysis_failed",
                            "error_type": failure,
                        },
                    }
                )
            decision.update(
                {
                    "features": features,
                    "classification": classification,
                    "skip_ocr": False,
                    "decision_reason": "pre_ocr_analysis_failed",
                    "geometry_image": None,
                    "orientation_image": None,
                    "geometry": geometry,
                }
            )
        return decisions
    finally:
        _ANALYSIS_FAILURES.reset(failures_token)
        _FAIL_OPEN_ACTIVE.reset(active_token)


def _build_ordinary_source_analysis_fail_open(
    source: fitz.Document,
    decisions: list[dict[str, object]],
) -> tuple[bytes | None, list[dict[str, object]]]:
    """Carry analysis-failed provider-page indexes into the V4 bypass layer."""

    if _OriginalBuildOrdinarySource is None:
        raise RuntimeError("ordinary provider compatibility is not installed")
    provider_bytes, provider_map = _OriginalBuildOrdinarySource(source, decisions)
    source_to_provider = {
        str(item.get("source_unit_id")): int(item["provider_page_index"])
        for item in provider_map
        if isinstance(item, Mapping)
        and isinstance(item.get("provider_page_index"), int)
    }
    analysis_pages: dict[int, str] = {}
    for decision in decisions:
        if decision.get("decision_reason") != "pre_ocr_analysis_failed":
            continue
        source_unit_id = str(decision.get("source_unit_id") or "")
        provider_page_index = source_to_provider.get(source_unit_id)
        if provider_page_index is None:
            continue
        geometry = decision.get("geometry")
        geometry = geometry if isinstance(geometry, Mapping) else {}
        analysis_pages[provider_page_index] = str(
            geometry.get("error_type") or "AnalysisRenderError"
        )

    existing = dict(dimensions._ORDINARY_FAIL_OPEN_PAGES.get())
    existing.update(analysis_pages)
    dimensions._ORDINARY_FAIL_OPEN_PAGES.set(existing)
    _ANALYSIS_PROVIDER_PAGES.set(analysis_pages)
    return provider_bytes, provider_map


def _preprocess_pdf_geometry_analysis_fail_open(
    pdf_bytes: bytes,
    *,
    expected_page_count: int | None = None,
    **kwargs: object,
):
    """Relabel V4-bypassed analysis failures with accurate audit provenance."""

    if _OriginalV4Preprocess is None:
        raise RuntimeError("V4 preprocessing compatibility is not installed")
    analysis_pages = dict(_ANALYSIS_PROVIDER_PAGES.get())
    _ANALYSIS_PROVIDER_PAGES.set({})
    processed = _OriginalV4Preprocess(
        pdf_bytes,
        expected_page_count=expected_page_count,
        **kwargs,
    )
    if not analysis_pages:
        return processed

    from app.processing import pdf_opencv_quality_pipeline as v4

    results = list(processed.pages)
    for page_index, error_type in analysis_pages.items():
        if not 0 <= page_index < len(results):
            raise ValueError("analysis fail-open provider page index is out of range")
        results[page_index] = replace(
            results[page_index],
            fallback_used=True,
            safe_reason=f"pre_ocr_analysis_failed:{error_type}",
        )

    with v4._DIAGNOSTIC_LOCK:
        manifest = v4._DIAGNOSTIC_MANIFESTS.get(processed.checksum_sha256)
        if isinstance(manifest, Mapping):
            updated_manifest = dict(manifest)
            pages = updated_manifest.get("pages")
            pages = list(pages) if isinstance(pages, list) else []
            for page_index, error_type in analysis_pages.items():
                if not 0 <= page_index < len(pages):
                    continue
                entry = pages[page_index]
                entry = dict(entry) if isinstance(entry, Mapping) else {}
                geometry = entry.get("geometry")
                geometry = dict(geometry) if isinstance(geometry, Mapping) else {}
                geometry.update(
                    {
                        "accepted": False,
                        "reason": "pre_ocr_analysis_failed",
                        "error_type": error_type,
                        "gate": {},
                    }
                )
                background = entry.get("background")
                background = (
                    dict(background) if isinstance(background, Mapping) else {}
                )
                background.update(
                    {
                        "attempted": False,
                        "accepted": False,
                        "reason": "pre_ocr_analysis_failed_v4_bypassed",
                        "gate": {},
                    }
                )
                entry.update(
                    {
                        "route": "quality_gate_original",
                        "selected": "original",
                        "geometry": geometry,
                        "background": background,
                        "analysis": {
                            "attempted": True,
                            "accepted": False,
                            "reason": "pre_ocr_analysis_failed",
                            "error_type": error_type,
                        },
                        "applied_steps": [],
                    }
                )
                pages[page_index] = entry
            updated_manifest["pages"] = pages
            v4._DIAGNOSTIC_MANIFESTS[processed.checksum_sha256] = updated_manifest

    return replace(processed, pages=tuple(results))


def _retain_diagnostics_with_manifest_capture(
    *,
    source_pdf_bytes: bytes,
    processed: Any,
    processing_attempt_id: str,
):
    """Capture the page manifest before diagnostic retention consumes it."""

    if _OriginalRetainDiagnostics is None:
        raise RuntimeError("diagnostic retention compatibility is not installed")
    from app.processing import pdf_opencv_quality_pipeline as v4

    with v4._DIAGNOSTIC_LOCK:
        manifest = v4._DIAGNOSTIC_MANIFESTS.get(processed.checksum_sha256)
        captured = (
            bridge._json_clone(manifest)
            if isinstance(manifest, Mapping)
            else None
        )
    result = _OriginalRetainDiagnostics(
        source_pdf_bytes=source_pdf_bytes,
        processed=processed,
        processing_attempt_id=processing_attempt_id,
    )
    _CAPTURED_V4_MANIFEST.set(
        (processed.checksum_sha256, captured)
        if isinstance(captured, dict)
        else None
    )
    return result


def _v4_manifest_after_retention(processed: Any) -> dict[str, object]:
    """Return the one-shot manifest captured before diagnostic retention."""

    captured = _CAPTURED_V4_MANIFEST.get()
    if captured is not None and captured[0] == processed.checksum_sha256:
        _CAPTURED_V4_MANIFEST.set(None)
        return bridge._json_clone(captured[1])
    if _OriginalV4Manifest is None:
        raise RuntimeError("V4 manifest compatibility is not installed")
    return _OriginalV4Manifest(processed)


def install_analysis_render_fail_open_compat() -> None:
    """Install analysis fail-open routing and one-shot V4 manifest capture."""

    global _INSTALLED
    global _OriginalAnalysisImage, _OriginalOrientedGeometry, _OriginalClassifier
    global _OriginalClassifySourcePages, _OriginalBuildOrdinarySource
    global _OriginalV4Preprocess, _OriginalRetainDiagnostics, _OriginalV4Manifest
    if _INSTALLED:
        return

    from app.processing import pdf_geometry_integration as integration
    from app.processing import pdf_opencv_quality_pipeline as v4

    _OriginalAnalysisImage = bridge._analysis_image
    _OriginalOrientedGeometry = orientation._oriented_geometry
    _OriginalClassifier = bridge._classify
    _OriginalClassifySourcePages = preprocess._classify_source_pages
    _OriginalBuildOrdinarySource = preprocess._build_ordinary_source
    _OriginalV4Preprocess = v4.preprocess_pdf_geometry_opencv
    _OriginalRetainDiagnostics = integration.retain_opencv_diagnostics
    _OriginalV4Manifest = bridge._v4_manifest

    bridge._analysis_image = _analysis_image_fail_open
    orientation._oriented_geometry = _oriented_geometry_after_analysis_guard
    bridge._classify = _classify_after_analysis_guard
    orientation._classify_source_pages_oriented = (
        _classify_source_pages_analysis_fail_open
    )
    preprocess._classify_source_pages = _classify_source_pages_analysis_fail_open
    orientation._build_ordinary_source_oriented = (
        _build_ordinary_source_analysis_fail_open
    )
    preprocess._build_ordinary_source = _build_ordinary_source_analysis_fail_open
    v4.preprocess_pdf_geometry_opencv = (
        _preprocess_pdf_geometry_analysis_fail_open
    )
    integration.retain_opencv_diagnostics = (
        _retain_diagnostics_with_manifest_capture
    )
    bridge._v4_manifest = _v4_manifest_after_retention
    _INSTALLED = True


__all__ = [
    "install_analysis_render_fail_open_compat",
]
