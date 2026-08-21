"""Safe, bounded diagnostics for the pre-OCR page-classification pipeline.

This compatibility layer is installed after presentation, high-resolution, and
native-text overlays have composed their final ``_classify_source_pages``
function. It does not alter any classification decision or threshold; it only
records configuration and decision summaries that distinguish model decisions,
fail-open OCR, presentation skips, and native-text skips.
"""
from __future__ import annotations

import os
from typing import Any, Mapping

from app.processing import pdf_page_presentation_bridge as bridge
from app.processing import pdf_page_presentation_preprocess_compat as preprocess

_INSTALLED = False


def _configured_model() -> str:
    return (
        os.getenv("PDF_PAGE_CLASSIFICATION_OPENAI_MODEL", "").strip()
        or os.getenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", "").strip()
    )


def _timeout_seconds() -> float:
    raw = os.getenv("PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS", "60")
    try:
        value = float(raw)
    except ValueError:
        return 60.0
    return max(0.1, value)


def _classification(decision: Mapping[str, Any]) -> Mapping[str, Any]:
    value = decision.get("classification")
    return value if isinstance(value, Mapping) else {}


def _safe_reason_codes(classification: Mapping[str, Any]) -> str:
    values = classification.get("reason_codes")
    if not isinstance(values, list):
        return ""
    safe = [str(value).strip().replace(" ", "_")[:80] for value in values[:8]]
    return ",".join(value for value in safe if value)


def _emit_decision(decision: Mapping[str, Any]) -> None:
    classification = _classification(decision)
    candidate = bool(decision.get("candidate"))
    skip_ocr = bool(decision.get("skip_ocr"))
    native_text = bool(decision.get("native_text_accepted"))
    if not candidate and not skip_ocr and not native_text:
        return
    bridge._diagnostic(
        "PDF_PAGE_CLASSIFICATION_DECISION",
        page_number=decision.get("page_number"),
        source_unit_id=decision.get("source_unit_id"),
        candidate=candidate,
        page_role=classification.get("page_role"),
        confidence=classification.get("confidence"),
        provider=classification.get("provider"),
        model_id=classification.get("model_id"),
        cache_hit=classification.get("cache_hit"),
        skip_ocr=skip_ocr,
        decision_reason=decision.get("decision_reason"),
        native_text_accepted=native_text,
        reason_codes=_safe_reason_codes(classification),
    )


def _emit_summary(decisions: list[dict[str, Any]]) -> None:
    candidate_count = 0
    classifier_success_count = 0
    classifier_fallback_count = 0
    cache_hit_count = 0
    presentation_page_count = 0
    native_text_page_count = 0
    provider_page_count = 0
    fallback_to_ocr_count = 0
    below_confidence_count = 0
    prose_conflict_count = 0
    role_not_presentation_count = 0

    for decision in decisions:
        classification = _classification(decision)
        candidate = bool(decision.get("candidate"))
        skip_ocr = bool(decision.get("skip_ocr"))
        native_text = bool(decision.get("native_text_accepted"))
        decision_reason = str(decision.get("decision_reason") or "")
        provider = str(classification.get("provider") or "")

        candidate_count += int(candidate)
        if candidate:
            if provider and provider != "none":
                classifier_success_count += 1
            else:
                classifier_fallback_count += 1
            cache_hit_count += int(bool(classification.get("cache_hit")))

        if native_text:
            native_text_page_count += 1
        elif skip_ocr and decision_reason == "presentation_page_confirmed":
            presentation_page_count += 1

        if not skip_ocr:
            provider_page_count += 1
            if candidate:
                fallback_to_ocr_count += 1

        below_confidence_count += int(
            decision_reason == "classification_below_confidence_threshold"
        )
        prose_conflict_count += int(
            decision_reason == "local_continuous_prose_conflict"
        )
        role_not_presentation_count += int(
            candidate and decision_reason == "role_not_presentation"
        )
        _emit_decision(decision)

    bridge._diagnostic(
        "PDF_PAGE_CLASSIFICATION_SUMMARY",
        document_page_count=len(decisions),
        candidate_count=candidate_count,
        classifier_success_count=classifier_success_count,
        classifier_fallback_count=classifier_fallback_count,
        cache_hit_count=cache_hit_count,
        presentation_page_count=presentation_page_count,
        native_text_page_count=native_text_page_count,
        provider_page_count=provider_page_count,
        excluded_from_provider_count=(
            presentation_page_count + native_text_page_count
        ),
        fallback_to_ocr_count=fallback_to_ocr_count,
        below_confidence_count=below_confidence_count,
        prose_conflict_count=prose_conflict_count,
        role_not_presentation_count=role_not_presentation_count,
    )


def install_page_classification_observability_compat() -> None:
    """Wrap the fully composed page classifier without changing decisions."""
    global _INSTALLED
    if _INSTALLED:
        return

    original = preprocess._classify_source_pages
    if getattr(original, "__atlas_page_classification_observability__", False):
        _INSTALLED = True
        return

    def classify_with_observability(source):
        api_key_configured = bool(
            os.getenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "").strip()
        )
        model_id = _configured_model()
        bridge._diagnostic(
            "PDF_PAGE_CLASSIFICATION_CONFIG",
            enabled=bool(api_key_configured and model_id),
            provider=("openai" if api_key_configured and model_id else "none"),
            api_key_configured=api_key_configured,
            model_configured=bool(model_id),
            model_id=(model_id or None),
            min_confidence=bridge._validated_min_confidence(),
            timeout_seconds=_timeout_seconds(),
        )
        decisions = original(source)
        _emit_summary(decisions)
        return decisions

    setattr(classify_with_observability, "__atlas_page_classification_observability__", True)
    preprocess._classify_source_pages = classify_with_observability
    _INSTALLED = True


__all__ = ["install_page_classification_observability_compat"]
