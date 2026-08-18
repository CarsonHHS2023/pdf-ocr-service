"""Compatibility fixes for enriched pre-OCR classifier audit responses."""
from __future__ import annotations

import hashlib
import json
import os
from typing import Mapping

from app.processing import pdf_page_presentation_bridge as bridge

_INSTALLED = False


def _classifier_identity() -> dict[str, object]:
    override = bridge._CLASSIFIER_OVERRIDE
    if override is not None:
        return {
            "kind": "override",
            "module": str(getattr(override, "__module__", "")),
            "qualname": str(
                getattr(override, "__qualname__", getattr(override, "__name__", ""))
            ),
            "process_identity": id(override),
        }
    return {
        "kind": "openai",
        "model": (
            os.getenv("PDF_PAGE_CLASSIFICATION_OPENAI_MODEL", "").strip()
            or os.getenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", "").strip()
        ),
        "endpoint": os.getenv(
            "PDF_STRUCTURE_REFINEMENT_OPENAI_ENDPOINT",
            "https://api.openai.com/v1/responses",
        ).strip(),
    }


def _classification_cache_key(
    png_bytes: bytes,
    features: Mapping[str, object],
    context: Mapping[str, object],
) -> str:
    # source_unit_id is an output identity, not a classification signal. Keep
    # the remaining prompt context, candidate features, prompt version and
    # effective classifier configuration in the process-local cache key.
    page_context = {
        str(name): value
        for name, value in context.items()
        if name != "source_unit_id"
    }
    payload = {
        "image_sha256": hashlib.sha256(png_bytes).hexdigest(),
        "features": bridge._json_clone(dict(features)),
        "page_context": bridge._json_clone(page_context),
        "prompt_version": bridge.PROMPT_VERSION,
        "classifier": _classifier_identity(),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fixed_classify(png_bytes, features, context):
    cache_key = _classification_cache_key(png_bytes, features, context)
    with bridge._CLASSIFICATION_CACHE_LOCK:
        cached = bridge._CLASSIFICATION_CACHE.get(cache_key)
    if cached is not None:
        result = bridge._json_clone(cached)
        result["source_unit_id"] = str(context["source_unit_id"])
        result["cache_hit"] = True
        return result

    classifier = bridge._CLASSIFIER_OVERRIDE or bridge._openai_classification
    result = classifier(png_bytes, features, context)
    if not isinstance(result, Mapping):
        raise ValueError("page classifier must return a mapping")
    core = {
        name: result.get(name)
        for name in (
            "source_unit_id",
            "page_role",
            "confidence",
            "reason_codes",
        )
    }
    parsed = bridge._strict_classification(
        core,
        expected_source_unit_id=str(context["source_unit_id"]),
    )
    parsed.update(
        {
            "provider": str(result.get("provider") or "test_override"),
            "model_id": str(result.get("model_id") or "test"),
            "prompt_version": str(
                result.get("prompt_version") or bridge.PROMPT_VERSION
            ),
            "image_detail": str(result.get("image_detail") or "low"),
            "input_tokens": int(result.get("input_tokens") or 0),
            "output_tokens": int(result.get("output_tokens") or 0),
            "cache_hit": bool(result.get("cache_hit", False)),
        }
    )
    with bridge._CLASSIFICATION_CACHE_LOCK:
        if len(bridge._CLASSIFICATION_CACHE) >= bridge._CLASSIFICATION_CACHE_MAX:
            bridge._CLASSIFICATION_CACHE.pop(
                next(iter(bridge._CLASSIFICATION_CACHE))
            )
        bridge._CLASSIFICATION_CACHE[cache_key] = bridge._json_clone(parsed)
    return parsed


def install_classifier_audit_compat() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    bridge._classify = _fixed_classify
    _INSTALLED = True


__all__ = [
    "install_classifier_audit_compat",
]
