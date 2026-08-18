"""High-resolution confirmation for risky pre-OCR orientation and presentation decisions."""
from __future__ import annotations

import base64
import json
import os
from typing import Any, Callable, Mapping

import cv2
import fitz  # type: ignore[import]
import httpx
import numpy as np

from app.processing import pdf_page_orientation_compat as orientation
from app.processing import pdf_page_presentation_bridge as bridge

PROMPT_VERSION = "pdf_page_presentation_classifier_v2_high_resolution_confirmation"
_ORIENTATION_MIN_CONFIDENCE = 0.90
_PRESENTATION_ROLES = frozenset(bridge.PRESENTATION_PAGE_ROLES)
_FULL_PAGE_VISUAL_ROLES = frozenset({"full_page_figure", "full_page_chart"})
_VISUAL_COVERAGE_VALUES = frozenset({"full_page", "dominant", "partial", "minimal"})

_INSTALLED = False
_OriginalDetectOrientation: Callable[..., Any] | None = None
_OriginalOpenAIClassification: Callable[..., Any] | None = None
_OriginalSkipOcrDecision: Callable[..., Any] | None = None


def _configured_provider() -> tuple[str, str, str, float]:
    api_key = os.getenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "").strip()
    model_id = (
        os.getenv("PDF_PAGE_CLASSIFICATION_OPENAI_MODEL", "").strip()
        or os.getenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", "").strip()
    )
    endpoint = os.getenv(
        "PDF_STRUCTURE_REFINEMENT_OPENAI_ENDPOINT",
        "https://api.openai.com/v1/responses",
    ).strip()
    timeout = float(os.getenv("PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS", "60"))
    if not api_key or not model_id:
        raise RuntimeError("high-resolution confirmation provider is not configured")
    return api_key, model_id, endpoint, timeout


def _resize_for_confirmation(image: np.ndarray, *, max_dimension: int) -> np.ndarray:
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("confirmation image must be BGR")
    height, width = image.shape[:2]
    scale = min(1.0, float(max_dimension) / max(height, width))
    if scale >= 1.0:
        return image
    return cv2.resize(
        image,
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        interpolation=cv2.INTER_AREA,
    )


def _jpeg_data_url(image: np.ndarray, *, max_dimension: int) -> str:
    prepared = _resize_for_confirmation(image, max_dimension=max_dimension)
    ok, encoded = cv2.imencode(
        ".jpg",
        prepared,
        [int(cv2.IMWRITE_JPEG_QUALITY), 88],
    )
    if not ok:
        raise RuntimeError("high-resolution confirmation image could not be encoded")
    return "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")


def _decode_page_image(png_bytes: bytes) -> np.ndarray:
    array = np.frombuffer(png_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("page classification image could not be decoded")
    return image


def _page_views(png_bytes: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    image = _decode_page_image(png_bytes)
    height = image.shape[0]
    split_top = max(1, int(round(height * 0.58)))
    split_bottom = min(height - 1, int(round(height * 0.42)))
    return image, image[:split_top], image[split_bottom:]


def _response_payload(
    *,
    endpoint: str,
    api_key: str,
    timeout: float,
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    response = httpx.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=dict(payload),
        timeout=timeout,
    )
    response.raise_for_status()
    decoded = response.json()
    if not isinstance(decoded, Mapping):
        raise ValueError("confirmation provider response must be an object")
    return decoded


def _classification_confirmation_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "source_unit_id",
            "page_role",
            "confidence",
            "reason_codes",
            "has_substantial_body_prose",
            "visual_coverage",
        ],
        "properties": {
            "source_unit_id": {"type": "string", "minLength": 1},
            "page_role": {
                "type": "string",
                "enum": sorted(bridge.ALL_PAGE_ROLES),
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason_codes": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "has_substantial_body_prose": {"type": "boolean"},
            "visual_coverage": {
                "type": "string",
                "enum": sorted(_VISUAL_COVERAGE_VALUES),
            },
        },
    }


def _request_high_resolution_classification(
    png_bytes: bytes,
    features: Mapping[str, object],
    context: Mapping[str, object],
) -> dict[str, object]:
    api_key, model_id, endpoint, timeout = _configured_provider()
    source_unit_id = str(context["source_unit_id"])
    full_page, top_half, bottom_half = _page_views(png_bytes)
    content = [
        {
            "type": "input_text",
            "text": json.dumps(
                {
                    "source_unit_id": source_unit_id,
                    "page_position": dict(context),
                    "candidate_features": dict(features),
                    "instruction": (
                        "Confirm the page role from high-resolution evidence. "
                        "A page containing a chart or figure plus one or more "
                        "substantial body-prose passages is body, not a full-page "
                        "chart or figure. Inspect the full page and both regional "
                        "views before deciding."
                    ),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ),
        },
        {"type": "input_text", "text": "High-resolution full-page view:"},
        {
            "type": "input_image",
            "image_url": _jpeg_data_url(full_page, max_dimension=2200),
            "detail": "high",
        },
        {"type": "input_text", "text": "High-resolution upper-page view:"},
        {
            "type": "input_image",
            "image_url": _jpeg_data_url(top_half, max_dimension=1800),
            "detail": "high",
        },
        {"type": "input_text", "text": "High-resolution lower-page view:"},
        {
            "type": "input_image",
            "image_url": _jpeg_data_url(bottom_half, max_dimension=1800),
            "detail": "high",
        },
    ]
    payload = {
        "model": model_id,
        "instructions": (
            "Return exactly one strict JSON high-resolution page classification. "
            "Allowed roles: cover, back_cover, title_page, chapter_divider, "
            "full_page_figure, full_page_chart, body, unknown. A visually prominent "
            "chart does not make the page full_page_chart when meaningful prose must "
            "also be read in sequence."
        ),
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "pdf_page_high_resolution_confirmation",
                "strict": True,
                "schema": _classification_confirmation_schema(),
            }
        },
    }
    decoded = _response_payload(
        endpoint=endpoint,
        api_key=api_key,
        timeout=timeout,
        payload=payload,
    )
    parsed = json.loads(bridge._response_output_text(decoded))
    if not isinstance(parsed, Mapping):
        raise ValueError("high-resolution classification output must be an object")
    required = {
        "source_unit_id",
        "page_role",
        "confidence",
        "reason_codes",
        "has_substantial_body_prose",
        "visual_coverage",
    }
    if set(parsed) != required:
        raise ValueError("high-resolution classification fields are invalid")
    if parsed.get("source_unit_id") != source_unit_id:
        raise ValueError("high-resolution classification source_unit_id mismatch")
    role = parsed.get("page_role")
    confidence = parsed.get("confidence")
    reasons = parsed.get("reason_codes")
    prose = parsed.get("has_substantial_body_prose")
    coverage = parsed.get("visual_coverage")
    if role not in bridge.ALL_PAGE_ROLES:
        raise ValueError("high-resolution classification role is invalid")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= float(confidence) <= 1
    ):
        raise ValueError("high-resolution classification confidence is invalid")
    if (
        not isinstance(reasons, list)
        or not reasons
        or any(not isinstance(item, str) or not item.strip() for item in reasons)
    ):
        raise ValueError("high-resolution classification reason_codes are invalid")
    if not isinstance(prose, bool):
        raise ValueError("high-resolution body-prose flag is invalid")
    if coverage not in _VISUAL_COVERAGE_VALUES:
        raise ValueError("high-resolution visual coverage is invalid")
    usage = decoded.get("usage")
    usage = usage if isinstance(usage, Mapping) else {}
    reason_codes = list(dict.fromkeys(str(item).strip() for item in reasons))
    reason_codes.extend(
        [
            "high_resolution_confirmed",
            "body_prose_present" if prose else "body_prose_absent",
            f"visual_coverage_{coverage}",
        ]
    )
    return {
        "source_unit_id": source_unit_id,
        "page_role": str(role),
        "confidence": float(confidence),
        "reason_codes": list(dict.fromkeys(reason_codes)),
        "provider": "openai",
        "model_id": str(decoded.get("model") or model_id),
        "prompt_version": PROMPT_VERSION,
        "image_detail": "high",
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cache_hit": False,
    }


def _orientation_confirmation_schema(proposed_degrees: int) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "source_unit_id",
            "upright_correction_degrees",
            "confidence",
            "reason_codes",
        ],
        "properties": {
            "source_unit_id": {"type": "string", "minLength": 1},
            "upright_correction_degrees": {
                "type": "integer",
                "enum": [0, int(proposed_degrees)],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason_codes": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
        },
    }


def _request_high_resolution_orientation(
    page: fitz.Page,
    proposal: orientation.DiscreteOrientation,
) -> dict[str, object]:
    api_key, model_id, endpoint, timeout = _configured_provider()
    from app.processing import pdf_opencv_quality_pipeline as v4

    source_unit_id = bridge._source_unit_id(int(page.number) + 1)
    raw_page = v4._render_page_bgr(page, dpi=v4._RENDER_DPI)
    proposed_page = orientation._rotate_clockwise(
        raw_page,
        proposal.correction_degrees,
    )
    content = [
        {
            "type": "input_text",
            "text": json.dumps(
                {
                    "source_unit_id": source_unit_id,
                    "opencv_proposed_correction_degrees": proposal.correction_degrees,
                    "opencv_confidence": proposal.confidence,
                    "instruction": (
                        "Choose which variant is upright. Use readable text direction, "
                        "page numbers, captions, and diagram labels. Return 0 when the "
                        "proposal is not independently convincing."
                    ),
                },
                separators=(",", ":"),
                allow_nan=False,
            ),
        },
        {"type": "input_text", "text": "Variant A: original rendered page (correction 0)."},
        {
            "type": "input_image",
            "image_url": _jpeg_data_url(raw_page, max_dimension=2200),
            "detail": "high",
        },
        {
            "type": "input_text",
            "text": (
                "Variant B: page after the OpenCV-proposed correction "
                f"({proposal.correction_degrees} degrees clockwise)."
            ),
        },
        {
            "type": "input_image",
            "image_url": _jpeg_data_url(proposed_page, max_dimension=2200),
            "detail": "high",
        },
    ]
    payload = {
        "model": model_id,
        "instructions": (
            "Return exactly one strict JSON orientation confirmation. Select the "
            "correction that makes the page upright. Do not trust geometric layout "
            "alone; when semantic orientation evidence is unclear, select 0."
        ),
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "pdf_page_orientation_confirmation",
                "strict": True,
                "schema": _orientation_confirmation_schema(
                    proposal.correction_degrees
                ),
            }
        },
    }
    decoded = _response_payload(
        endpoint=endpoint,
        api_key=api_key,
        timeout=timeout,
        payload=payload,
    )
    parsed = json.loads(bridge._response_output_text(decoded))
    if not isinstance(parsed, Mapping):
        raise ValueError("orientation confirmation output must be an object")
    required = {
        "source_unit_id",
        "upright_correction_degrees",
        "confidence",
        "reason_codes",
    }
    if set(parsed) != required:
        raise ValueError("orientation confirmation fields are invalid")
    if parsed.get("source_unit_id") != source_unit_id:
        raise ValueError("orientation confirmation source_unit_id mismatch")
    correction = parsed.get("upright_correction_degrees")
    confidence = parsed.get("confidence")
    reasons = parsed.get("reason_codes")
    if correction not in {0, proposal.correction_degrees}:
        raise ValueError("orientation confirmation correction is invalid")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= float(confidence) <= 1
    ):
        raise ValueError("orientation confirmation confidence is invalid")
    if (
        not isinstance(reasons, list)
        or not reasons
        or any(not isinstance(item, str) or not item.strip() for item in reasons)
    ):
        raise ValueError("orientation confirmation reason_codes are invalid")
    return {
        "source_unit_id": source_unit_id,
        "upright_correction_degrees": int(correction),
        "confidence": float(confidence),
        "reason_codes": list(dict.fromkeys(str(item).strip() for item in reasons)),
    }


def _detect_orientation_with_high_resolution_confirmation(
    page: fitz.Page,
    analysis_image: np.ndarray,
) -> orientation.DiscreteOrientation:
    if _OriginalDetectOrientation is None:
        raise RuntimeError("high-resolution orientation confirmation is not installed")
    proposal = _OriginalDetectOrientation(page, analysis_image)
    if not proposal.applied or proposal.source != "opencv_layout":
        return proposal
    source_unit_id = bridge._source_unit_id(int(page.number) + 1)
    bridge._diagnostic(
        "PDF_PAGE_ORIENTATION_CONFIRMATION_STARTED",
        source_unit_id=source_unit_id,
        proposed_degrees=proposal.correction_degrees,
        proposal_confidence=proposal.confidence,
        image_detail="high",
    )
    try:
        confirmation = _request_high_resolution_orientation(page, proposal)
    except Exception as exc:
        bridge._diagnostic(
            "PDF_PAGE_ORIENTATION_CONFIRMATION_FAILED",
            source_unit_id=source_unit_id,
            proposed_degrees=proposal.correction_degrees,
            error_type=type(exc).__name__,
            applied=False,
        )
        return orientation.DiscreteOrientation(
            correction_degrees=0,
            confidence=0.0,
            source="opencv_layout_unconfirmed",
            native_text_chars=proposal.native_text_chars,
            image_score=proposal.image_score,
        )
    confirmed_degrees = int(confirmation["upright_correction_degrees"])
    confidence = float(confirmation["confidence"])
    applied = bool(
        confirmed_degrees == proposal.correction_degrees
        and confidence >= _ORIENTATION_MIN_CONFIDENCE
    )
    bridge._diagnostic(
        "PDF_PAGE_ORIENTATION_CONFIRMATION_RESULT",
        source_unit_id=source_unit_id,
        proposed_degrees=proposal.correction_degrees,
        confirmed_degrees=confirmed_degrees,
        confidence=confidence,
        applied=applied,
    )
    return orientation.DiscreteOrientation(
        correction_degrees=proposal.correction_degrees if applied else 0,
        confidence=confidence,
        source=(
            "openai_high_resolution_confirmed_opencv_layout"
            if applied
            else "openai_high_resolution_rejected_opencv_layout"
        ),
        native_text_chars=proposal.native_text_chars,
        image_score=proposal.image_score,
    )


def _openai_classification_with_high_resolution_confirmation(
    png_bytes: bytes,
    features: Mapping[str, object],
    context: Mapping[str, object],
) -> dict[str, object]:
    if _OriginalOpenAIClassification is None:
        raise RuntimeError("high-resolution page confirmation is not installed")
    initial = _OriginalOpenAIClassification(png_bytes, features, context)
    if initial.get("page_role") not in _PRESENTATION_ROLES:
        return dict(initial)
    source_unit_id = str(context["source_unit_id"])
    bridge._diagnostic(
        "PDF_PAGE_CLASSIFICATION_HIGH_RES_CONFIRMATION_STARTED",
        source_unit_id=source_unit_id,
        proposed_role=initial.get("page_role"),
        proposed_confidence=initial.get("confidence"),
    )
    confirmed = _request_high_resolution_classification(
        png_bytes,
        features,
        context,
    )
    reasons = list(confirmed.get("reason_codes") or [])
    reasons.append(f"low_resolution_role_{initial.get('page_role')}")
    confirmed["reason_codes"] = list(dict.fromkeys(reasons))
    bridge._diagnostic(
        "PDF_PAGE_CLASSIFICATION_HIGH_RES_CONFIRMATION_RESULT",
        source_unit_id=source_unit_id,
        proposed_role=initial.get("page_role"),
        confirmed_role=confirmed.get("page_role"),
        confirmed_confidence=confirmed.get("confidence"),
        body_prose_present=(
            "body_prose_present" in set(confirmed.get("reason_codes") or [])
        ),
    )
    return confirmed


def _skip_ocr_with_high_resolution_confirmation(
    classification: Mapping[str, object],
    features: Mapping[str, object],
) -> tuple[bool, str]:
    if _OriginalSkipOcrDecision is None:
        raise RuntimeError("high-resolution page confirmation is not installed")
    skip_ocr, reason = _OriginalSkipOcrDecision(classification, features)
    if not skip_ocr:
        return skip_ocr, reason
    if classification.get("provider") != "openai":
        return skip_ocr, reason
    role = str(classification.get("page_role") or "")
    reason_codes = {
        str(value)
        for value in classification.get("reason_codes", [])
        if isinstance(value, str)
    }
    if (
        classification.get("image_detail") != "high"
        or "high_resolution_confirmed" not in reason_codes
    ):
        return False, "presentation_requires_high_resolution_confirmation"
    if role in _FULL_PAGE_VISUAL_ROLES:
        if "body_prose_present" in reason_codes:
            return False, "high_resolution_body_prose_conflict"
        if not (
            "visual_coverage_full_page" in reason_codes
            or "visual_coverage_dominant" in reason_codes
        ):
            return False, "high_resolution_visual_coverage_conflict"
        text_regions = int(features.get("text_region_count") or 0)
        dominant = float(features.get("dominant_visual_region_ratio") or 0.0)
        if text_regions >= 20 and dominant < 0.25:
            return False, "local_dense_text_visual_conflict"
    return True, "presentation_page_high_resolution_confirmed"


def install_high_resolution_page_confirmation_compat() -> None:
    """Install high-resolution confirmation after all existing page-routing layers."""

    global _INSTALLED
    global _OriginalDetectOrientation
    global _OriginalOpenAIClassification
    global _OriginalSkipOcrDecision
    if _INSTALLED:
        return
    _OriginalDetectOrientation = orientation.detect_discrete_orientation
    _OriginalOpenAIClassification = bridge._openai_classification
    _OriginalSkipOcrDecision = bridge._skip_ocr_decision
    orientation.detect_discrete_orientation = (
        _detect_orientation_with_high_resolution_confirmation
    )
    bridge._openai_classification = (
        _openai_classification_with_high_resolution_confirmation
    )
    bridge._skip_ocr_decision = _skip_ocr_with_high_resolution_confirmation
    bridge.PROMPT_VERSION = PROMPT_VERSION
    with bridge._CLASSIFICATION_CACHE_LOCK:
        bridge._CLASSIFICATION_CACHE.clear()
    _INSTALLED = True


__all__ = [
    "install_high_resolution_page_confirmation_compat",
]
