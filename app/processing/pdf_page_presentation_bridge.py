"""Pre-OCR presentation-page routing for the stable OpenCV v4 test pipeline.

The bridge is intentionally separate from ``pdf_opencv_quality_pipeline``.  It
reuses the existing v4 geometry builders and quality gate without changing any
v4 threshold.  Candidate selection happens locally, only candidates are sent to
the multimodal classifier, and every failure falls back to the ordinary v4 +
Paddle/Modal route.
"""
from __future__ import annotations

import base64
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
import gzip
import hashlib
import json
import logging
import os
from pathlib import Path
import threading
from time import monotonic
from typing import Any, Callable, Mapping, Sequence

import cv2
import fitz  # type: ignore[import]
import httpx
import numpy as np

from app.storage.models import StorageReference

_logger = logging.getLogger("uvicorn.error")

PRESENTATION_PAGE_ROLES = frozenset(
    {
        "cover",
        "back_cover",
        "title_page",
        "chapter_divider",
        "full_page_figure",
        "full_page_chart",
    }
)
ALL_PAGE_ROLES = frozenset((*PRESENTATION_PAGE_ROLES, "body", "unknown"))
PROMPT_VERSION = "pdf_page_presentation_classifier_v1"
DEFAULT_MIN_CONFIDENCE = 0.90
_CONTINUOUS_PROSE_CONFLICT_THRESHOLD = 0.55
_CLASSIFICATION_CACHE_MAX = 512
_CLASSIFICATION_CACHE: dict[str, dict[str, object]] = {}
_CLASSIFICATION_CACHE_LOCK = threading.Lock()
_CURRENT_PRESENTATION_MANIFEST: ContextVar[dict[str, object] | None] = ContextVar(
    "pre_ocr_presentation_manifest", default=None
)
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False

ClassifierOverride = Callable[
    [bytes, Mapping[str, object], Mapping[str, object]],
    Mapping[str, object],
]
_CLASSIFIER_OVERRIDE: ClassifierOverride | None = None


@dataclass(frozen=True, slots=True)
class PresentationProviderInput:
    """Full rendering PDF plus an optional ordinary-page-only provider PDF."""

    processing_attempt_id: str
    storage_reference: StorageReference
    checksum_sha256: str
    byte_size: int
    media_type: str
    filename: str
    preprocessing: Any
    provider_storage_reference: StorageReference
    provider_checksum_sha256: str
    provider_byte_size: int
    provider_filename: str
    provider_page_count: int
    provider_page_map: tuple[dict[str, object], ...]
    presentation_manifest: dict[str, object]


def _diagnostic(event: str, **fields: object) -> None:
    payload = " ".join(f"{name}={value}" for name, value in sorted(fields.items()))
    _logger.info("%s %s", event, payload)


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _source_unit_id(page_number: int) -> str:
    return f"pdf-page:{page_number:06d}"


def _page_number(source_unit_id: str) -> int | None:
    prefix = "pdf-page:"
    if not isinstance(source_unit_id, str) or not source_unit_id.startswith(prefix):
        return None
    try:
        value = int(source_unit_id[len(prefix) :])
    except ValueError:
        return None
    return value if value > 0 else None


def _validated_min_confidence() -> float:
    raw = os.getenv(
        "PDF_PAGE_CLASSIFICATION_MIN_CONFIDENCE",
        str(DEFAULT_MIN_CONFIDENCE),
    )
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_MIN_CONFIDENCE
    if not 0 <= value <= 1:
        return DEFAULT_MIN_CONFIDENCE
    return value


def _page_rect_area(rect: fitz.Rect) -> float:
    return max(1.0, float(rect.width) * float(rect.height))


def _coverage(rect: fitz.Rect, page_rect: fitz.Rect) -> float:
    clipped = rect & page_rect
    if clipped.is_empty:
        return 0.0
    return min(1.0, max(0.0, float(clipped.width * clipped.height) / _page_rect_area(page_rect)))


def _native_page_features(page: fitz.Page) -> dict[str, object]:
    text_dict = page.get_text("dict") or {}
    blocks = text_dict.get("blocks") if isinstance(text_dict, Mapping) else []
    blocks = blocks if isinstance(blocks, list) else []
    text_blocks = []
    font_sizes: list[float] = []
    line_count = 0
    native_text_parts: list[str] = []
    for block in blocks:
        if not isinstance(block, Mapping) or int(block.get("type", 0) or 0) != 0:
            continue
        text_blocks.append(block)
        lines = block.get("lines")
        if not isinstance(lines, list):
            continue
        line_count += len(lines)
        for line in lines:
            if not isinstance(line, Mapping):
                continue
            spans = line.get("spans")
            if not isinstance(spans, list):
                continue
            for span in spans:
                if not isinstance(span, Mapping):
                    continue
                text = span.get("text")
                if isinstance(text, str):
                    native_text_parts.append(text)
                size = span.get("size")
                if isinstance(size, (int, float)) and not isinstance(size, bool) and size > 0:
                    font_sizes.append(float(size))

    embedded_image_count = 0
    maximum_embedded_image_coverage = 0.0
    try:
        images = page.get_images(full=True)
    except Exception:
        images = []
    for image in images:
        if not image:
            continue
        embedded_image_count += 1
        xref = image[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            rects = []
        for rect in rects:
            maximum_embedded_image_coverage = max(
                maximum_embedded_image_coverage,
                _coverage(rect, page.rect),
            )

    vector_coverage = 0.0
    try:
        drawings = page.get_drawings()
    except Exception:
        drawings = []
    for drawing in drawings:
        if not isinstance(drawing, Mapping):
            continue
        rect = drawing.get("rect")
        if isinstance(rect, fitz.Rect):
            vector_coverage += _coverage(rect, page.rect)
    vector_coverage = min(1.0, vector_coverage)

    ordered_sizes = sorted(font_sizes)
    median_font_size = (
        ordered_sizes[len(ordered_sizes) // 2] if ordered_sizes else 0.0
    )
    largest_font_size = max(ordered_sizes, default=0.0)
    ratio = (
        largest_font_size / median_font_size
        if median_font_size > 0
        else (1.0 if largest_font_size > 0 else 0.0)
    )
    native_text = "".join(native_text_parts)
    return {
        "native_text_chars": len(native_text.strip()),
        "native_text_block_count": len(text_blocks),
        "native_text_line_count": line_count,
        "largest_font_size": round(largest_font_size, 4),
        "median_font_size": round(median_font_size, 4),
        "largest_font_to_median_ratio": round(ratio, 4),
        "embedded_image_count": embedded_image_count,
        "maximum_embedded_image_coverage": round(
            maximum_embedded_image_coverage, 6
        ),
        "vector_drawing_coverage": round(vector_coverage, 6),
        "pdf_rotation_metadata": int(page.rotation or 0) % 360,
    }


def _analysis_image(page: fitz.Page) -> np.ndarray:
    from app.processing import pdf_opencv_quality_pipeline as v4

    return v4._render_page_bgr(page, dpi=v4._ANALYSIS_DPI)


def _image_features(image: np.ndarray) -> dict[str, object]:
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("page analysis image must be BGR")
    height, width = image.shape[:2]
    scale = min(1.0, 1400.0 / max(height, width))
    if scale < 1:
        image = cv2.resize(
            image,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, inverse = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    foreground_coverage = float(np.count_nonzero(inverse)) / float(inverse.size)
    whitespace_ratio = 1.0 - foreground_coverage

    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        (inverse > 0).astype(np.uint8), 8
    )
    areas = stats[1:, cv2.CC_STAT_AREA] if component_count > 1 else np.array([])
    page_pixels = float(inverse.size)
    relevant = areas[areas >= max(4, page_pixels * 0.000002)] if areas.size else areas
    largest_component_ratio = (
        float(relevant.max()) / page_pixels if relevant.size else 0.0
    )

    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(8, image.shape[1] // 60), 1)
    )
    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (1, max(8, image.shape[0] // 60))
    )
    horizontal = cv2.morphologyEx(inverse, cv2.MORPH_OPEN, horizontal_kernel)
    vertical = cv2.morphologyEx(inverse, cv2.MORPH_OPEN, vertical_kernel)
    horizontal_ratio = float(np.count_nonzero(horizontal)) / page_pixels
    vertical_ratio = float(np.count_nonzero(vertical)) / page_pixels

    text_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(12, image.shape[1] // 45), max(2, image.shape[0] // 500))
    )
    text_regions = cv2.morphologyEx(inverse, cv2.MORPH_CLOSE, text_kernel)
    contours, _ = cv2.findContours(
        text_regions, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    text_boxes = [
        cv2.boundingRect(contour)
        for contour in contours
        if cv2.contourArea(contour) >= page_pixels * 0.00005
    ]
    text_region_count = len(text_boxes)
    centers = [
        ((x + w / 2) / image.shape[1], (y + h / 2) / image.shape[0])
        for x, y, w, h in text_boxes
    ]
    if len(centers) > 1:
        xs = np.array([item[0] for item in centers], dtype=float)
        ys = np.array([item[1] for item in centers], dtype=float)
        dispersion = float(np.sqrt(np.var(xs) + np.var(ys)))
    else:
        dispersion = 0.0

    dominant_visual_region_ratio = max(
        largest_component_ratio,
        float(maximum_contour_area(contours)) / page_pixels,
    )
    body_like_boxes = [
        (x, y, w, h)
        for x, y, w, h in text_boxes
        if w >= image.shape[1] * 0.42
        and h <= image.shape[0] * 0.12
    ]
    body_prose_ratio = min(
        1.0,
        sum(w * h for x, y, w, h in body_like_boxes) / max(1.0, page_pixels * 0.45),
    )
    structure = (
        "horizontal"
        if horizontal_ratio > vertical_ratio * 1.15
        else "vertical"
        if vertical_ratio > horizontal_ratio * 1.15
        else "mixed"
    )
    return {
        "foreground_coverage": round(foreground_coverage, 6),
        "whitespace_ratio": round(whitespace_ratio, 6),
        "connected_component_count": int(len(relevant)),
        "largest_component_ratio": round(largest_component_ratio, 6),
        "text_region_count": text_region_count,
        "text_region_dispersion": round(dispersion, 6),
        "dominant_visual_region_ratio": round(dominant_visual_region_ratio, 6),
        "estimated_continuous_body_prose_ratio": round(body_prose_ratio, 6),
        "horizontal_vs_vertical_structure": structure,
        "likely_discrete_orientation": 0,
    }


def maximum_contour_area(contours: Sequence[np.ndarray]) -> float:
    return max((float(cv2.contourArea(item)) for item in contours), default=0.0)


def _combined_features(page: fitz.Page, image: np.ndarray) -> dict[str, object]:
    native = _native_page_features(page)
    visual = _image_features(image)
    rotation = int(native["pdf_rotation_metadata"])
    if rotation in {90, 180, 270}:
        visual["likely_discrete_orientation"] = rotation
    return {**native, **visual}


def _candidate_reasons(
    features: Mapping[str, object],
    *,
    first_page: bool,
    last_page: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if first_page:
        reasons.append("first_physical_page")
    if last_page:
        reasons.append("last_physical_page")
    text_chars = int(features.get("native_text_chars") or 0)
    text_blocks = int(features.get("native_text_block_count") or 0)
    whitespace = float(features.get("whitespace_ratio") or 0)
    image_coverage = float(features.get("maximum_embedded_image_coverage") or 0)
    dominant = float(features.get("dominant_visual_region_ratio") or 0)
    prose = float(features.get("estimated_continuous_body_prose_ratio") or 0)
    font_ratio = float(features.get("largest_font_to_median_ratio") or 0)
    dispersion = float(features.get("text_region_dispersion") or 0)
    orientation = int(features.get("likely_discrete_orientation") or 0)

    if text_chars <= 240 and text_blocks <= 8 and whitespace >= 0.45:
        reasons.append("sparse_text_high_whitespace")
    if image_coverage >= 0.55 or dominant >= 0.48:
        reasons.append("dominant_visual_region")
    if font_ratio >= 2.0 and prose <= 0.35:
        reasons.append("large_title_low_prose")
    if dispersion >= 0.25 and prose <= 0.35:
        reasons.append("dispersed_non_body_layout")
    if orientation in {90, 180, 270}:
        reasons.append("discrete_orientation")
    return tuple(dict.fromkeys(reasons))


def _is_candidate(
    features: Mapping[str, object],
    *,
    first_page: bool,
    last_page: bool,
) -> tuple[bool, tuple[str, ...]]:
    reasons = _candidate_reasons(
        features, first_page=first_page, last_page=last_page
    )
    return bool(first_page or last_page or len(reasons) > 0), reasons


def _encode_png(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("page classification image could not be encoded")
    return encoded.tobytes()


def _response_output_text(response: Mapping[str, object]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    output = response.get("output")
    if not isinstance(output, list):
        raise ValueError("classification response has no output")
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if (
                isinstance(part, Mapping)
                and part.get("type") in {"output_text", "text"}
                and isinstance(part.get("text"), str)
            ):
                return str(part["text"])
    raise ValueError("classification response has no output text")


def _strict_classification(
    value: Mapping[str, object],
    *,
    expected_source_unit_id: str,
) -> dict[str, object]:
    if set(value) != {"source_unit_id", "page_role", "confidence", "reason_codes"}:
        raise ValueError("classification JSON fields are invalid")
    source_unit_id = value.get("source_unit_id")
    role = value.get("page_role")
    confidence = value.get("confidence")
    reason_codes = value.get("reason_codes")
    if source_unit_id != expected_source_unit_id:
        raise ValueError("classification source_unit_id mismatch")
    if role not in ALL_PAGE_ROLES:
        raise ValueError("classification page_role is invalid")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= float(confidence) <= 1
    ):
        raise ValueError("classification confidence is invalid")
    if (
        not isinstance(reason_codes, list)
        or not reason_codes
        or any(not isinstance(code, str) or not code.strip() for code in reason_codes)
    ):
        raise ValueError("classification reason_codes are invalid")
    return {
        "source_unit_id": source_unit_id,
        "page_role": role,
        "confidence": float(confidence),
        "reason_codes": list(dict.fromkeys(code.strip() for code in reason_codes)),
    }


def _classification_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "source_unit_id",
            "page_role",
            "confidence",
            "reason_codes",
        ],
        "properties": {
            "source_unit_id": {"type": "string", "minLength": 1},
            "page_role": {
                "type": "string",
                "enum": sorted(ALL_PAGE_ROLES),
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason_codes": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
        },
    }


def _openai_classification(
    png_bytes: bytes,
    features: Mapping[str, object],
    context: Mapping[str, object],
) -> dict[str, object]:
    api_key = os.getenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "").strip()
    model_id = (
        os.getenv("PDF_PAGE_CLASSIFICATION_OPENAI_MODEL", "").strip()
        or os.getenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", "").strip()
    )
    if not api_key or not model_id:
        raise RuntimeError("page classification provider is not configured")
    endpoint = os.getenv(
        "PDF_STRUCTURE_REFINEMENT_OPENAI_ENDPOINT",
        "https://api.openai.com/v1/responses",
    ).strip()
    timeout = float(os.getenv("PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS", "60"))
    source_unit_id = str(context["source_unit_id"])
    image_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    minimum = _validated_min_confidence()
    details = ("low", "high")
    last: dict[str, object] | None = None
    for attempt, detail in enumerate(details, start=1):
        _diagnostic(
            "PDF_PAGE_CLASSIFICATION_REQUEST_STARTED",
            source_unit_id=source_unit_id,
            attempt=attempt,
            image_detail=detail,
            model_id=model_id,
        )
        content = [
            {
                "type": "input_text",
                "text": json.dumps(
                    {
                        "source_unit_id": source_unit_id,
                        "page_position": dict(context),
                        "candidate_features": dict(features),
                        "instruction": (
                            "Classify visual page presentation before OCR. "
                            "Do not infer from OCR text. Continuous body prose "
                            "must be body, not a presentation page."
                        ),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
            },
            {"type": "input_image", "image_url": image_url, "detail": detail},
        ]
        payload = {
            "model": model_id,
            "instructions": (
                "Return exactly one strict JSON page classification. Allowed "
                "roles: cover, back_cover, title_page, chapter_divider, "
                "full_page_figure, full_page_chart, body, unknown."
            ),
            "input": [{"role": "user", "content": content}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "pdf_page_presentation_classification",
                    "strict": True,
                    "schema": _classification_schema(),
                }
            },
        }
        response = httpx.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        decoded = response.json()
        if not isinstance(decoded, Mapping):
            raise ValueError("classification provider response must be an object")
        parsed = json.loads(_response_output_text(decoded))
        if not isinstance(parsed, Mapping):
            raise ValueError("classification output must be an object")
        last = _strict_classification(
            parsed, expected_source_unit_id=source_unit_id
        )
        usage = decoded.get("usage")
        usage = usage if isinstance(usage, Mapping) else {}
        last.update(
            {
                "provider": "openai",
                "model_id": str(decoded.get("model") or model_id),
                "prompt_version": PROMPT_VERSION,
                "image_detail": detail,
                "input_tokens": int(usage.get("input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
                "cache_hit": False,
            }
        )
        role = last["page_role"]
        confidence = float(last["confidence"])
        if role != "unknown" and confidence >= minimum + 0.05:
            break
    assert last is not None
    return last


def _classify(
    png_bytes: bytes,
    features: Mapping[str, object],
    context: Mapping[str, object],
) -> dict[str, object]:
    checksum = hashlib.sha256(png_bytes).hexdigest()
    with _CLASSIFICATION_CACHE_LOCK:
        cached = _CLASSIFICATION_CACHE.get(checksum)
    if cached is not None:
        result = _json_clone(cached)
        result["source_unit_id"] = str(context["source_unit_id"])
        result["cache_hit"] = True
        return result

    classifier = _CLASSIFIER_OVERRIDE or _openai_classification
    result = classifier(png_bytes, features, context)
    if not isinstance(result, Mapping):
        raise ValueError("page classifier must return a mapping")
    parsed = _strict_classification(
        result,
        expected_source_unit_id=str(context["source_unit_id"]),
    )
    parsed.update(
        {
            "provider": str(result.get("provider") or "test_override"),
            "model_id": str(result.get("model_id") or "test"),
            "prompt_version": str(
                result.get("prompt_version") or PROMPT_VERSION
            ),
            "image_detail": str(result.get("image_detail") or "low"),
            "input_tokens": int(result.get("input_tokens") or 0),
            "output_tokens": int(result.get("output_tokens") or 0),
            "cache_hit": bool(result.get("cache_hit", False)),
        }
    )
    with _CLASSIFICATION_CACHE_LOCK:
        if len(_CLASSIFICATION_CACHE) >= _CLASSIFICATION_CACHE_MAX:
            _CLASSIFICATION_CACHE.pop(next(iter(_CLASSIFICATION_CACHE)))
        _CLASSIFICATION_CACHE[checksum] = _json_clone(parsed)
    return parsed


def _fallback_classification(
    source_unit_id: str,
    reason: str,
) -> dict[str, object]:
    return {
        "source_unit_id": source_unit_id,
        "page_role": "unknown",
        "confidence": 0.0,
        "reason_codes": [reason],
        "provider": "none",
        "model_id": "",
        "prompt_version": PROMPT_VERSION,
        "image_detail": "none",
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_hit": False,
    }


def _skip_ocr_decision(
    classification: Mapping[str, object],
    features: Mapping[str, object],
) -> tuple[bool, str]:
    role = classification.get("page_role")
    confidence = classification.get("confidence")
    if role not in PRESENTATION_PAGE_ROLES:
        return False, "role_not_presentation"
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or float(confidence) < _validated_min_confidence()
    ):
        return False, "classification_below_confidence_threshold"
    prose = float(features.get("estimated_continuous_body_prose_ratio") or 0)
    native_chars = int(features.get("native_text_chars") or 0)
    native_lines = int(features.get("native_text_line_count") or 0)
    if prose >= _CONTINUOUS_PROSE_CONFLICT_THRESHOLD or (
        native_chars >= 1200 and native_lines >= 18
    ):
        return False, "local_continuous_prose_conflict"
    return True, "presentation_page_confirmed"


def _geometry_only_page(
    page: fitz.Page,
) -> tuple[np.ndarray | None, dict[str, object]]:
    from app.processing import pdf_opencv_quality_pipeline as v4

    source_bgr = v4._render_page_bgr(page, dpi=v4._RENDER_DPI)
    geometry_candidate, geometry_diag = v4._build_geometry_candidate(source_bgr)
    accepted, reason, gate = v4._gate_geometry_candidate(
        source_bgr, geometry_candidate, geometry_diag
    )
    selected = geometry_candidate if accepted else None
    applied_steps: list[str] = []
    if accepted and geometry_diag.perspective_applied:
        applied_steps.append("opencv_perspective")
    if accepted and geometry_diag.deskew_applied:
        applied_steps.append("opencv_deskew")
    rotation = int(page.rotation or 0) % 360
    orientation = {
        "detected_degrees": rotation,
        "applied": rotation in {90, 180, 270},
        "source": "pdf_rotation_metadata" if rotation else "none",
    }
    return selected, {
        "accepted": accepted,
        "reason": reason,
        "gate": gate,
        **asdict(geometry_diag),
        "applied_steps": applied_steps,
        "orientation": orientation,
    }


def _insert_geometry_or_original(
    output: fitz.Document,
    source: fitz.Document,
    page_index: int,
    geometry_bgr: np.ndarray | None,
) -> None:
    from app.processing import pdf_opencv_quality_pipeline as v4

    if geometry_bgr is None:
        output.insert_pdf(source, from_page=page_index, to_page=page_index)
        return
    v4._insert_raster_page(output, source[page_index].rect, geometry_bgr)


def _provider_reference(
    processing_attempt_id: str,
    checksum: str,
) -> StorageReference:
    digest = hashlib.sha256(
        f"atlas-pdf-presentation-provider-v1\x1f{processing_attempt_id}\x1f{checksum}".encode()
    ).hexdigest()[:32]
    return StorageReference.parse(f"src_{digest}")


def _render_reference(
    processing_attempt_id: str,
    checksum: str,
) -> StorageReference:
    digest = hashlib.sha256(
        f"atlas-pdf-presentation-render-v1\x1f{processing_attempt_id}\x1f{checksum}".encode()
    ).hexdigest()[:32]
    return StorageReference.parse(f"src_{digest}")


def _v4_manifest(processed: Any) -> dict[str, object]:
    from app.processing import pdf_opencv_quality_pipeline as v4

    with v4._DIAGNOSTIC_LOCK:
        value = v4._DIAGNOSTIC_MANIFESTS.get(processed.checksum_sha256)
    if isinstance(value, dict):
        return _json_clone(value)
    return {
        "version": processed.version,
        "output_sha256": processed.checksum_sha256,
        "output_size_bytes": processed.byte_size,
        "changed_page_count": processed.changed_page_count,
        "pages": [],
    }


def _v4_page_map(manifest: Mapping[str, object]) -> dict[int, dict[str, object]]:
    pages = manifest.get("pages")
    if not isinstance(pages, list):
        return {}
    result: dict[int, dict[str, object]] = {}
    for item in pages:
        if not isinstance(item, Mapping):
            continue
        page_number = item.get("page_number")
        if isinstance(page_number, int) and page_number > 0:
            result[page_number] = _json_clone(item)
    return result


def _register_manifest(
    processing_attempt_id: str,
    checksum: str,
    manifest: Mapping[str, object],
) -> None:
    try:
        from app.processing import pdf_opencv_modal_bridge as v4_bridge
    except Exception:
        return
    with v4_bridge._MANIFEST_LOCK:
        v4_bridge._MANIFESTS_BY_ATTEMPT[
            (processing_attempt_id, checksum)
        ] = _json_clone(manifest)


def prepare_presentation_provider_input(
    *,
    storage: Any,
    source_pdf_bytes: bytes,
    original_filename: str | None,
    processing_attempt_id: str,
    expected_page_count: int | None = None,
) -> PresentationProviderInput:
    """Create a full render PDF and an ordinary-page-only provider PDF."""

    from app.processing import pdf_geometry_integration as integration
    from app.processing import pdf_opencv_quality_pipeline as v4

    _diagnostic(
        "PDF_PAGE_CLASSIFICATION_PLANNED",
        processing_attempt_id=processing_attempt_id,
    )
    processed = v4.preprocess_pdf_geometry_opencv(
        source_pdf_bytes,
        expected_page_count=expected_page_count,
    )
    integration.retain_opencv_diagnostics(
        source_pdf_bytes=source_pdf_bytes,
        processed=processed,
        processing_attempt_id=processing_attempt_id,
    )
    base_manifest = _v4_manifest(processed)
    base_pages = _v4_page_map(base_manifest)

    source = fitz.open(stream=source_pdf_bytes, filetype="pdf")
    v4_document = fitz.open(stream=processed.pdf_bytes, filetype="pdf")
    render_document = fitz.open()
    provider_document = fitz.open()
    page_entries: list[dict[str, object]] = []
    provider_map: list[dict[str, object]] = []
    presentation_count = 0

    try:
        page_count = source.page_count
        for page_index in range(page_count):
            page_number = page_index + 1
            source_unit_id = _source_unit_id(page_number)
            page = source[page_index]
            analysis_image = _analysis_image(page)
            features = _combined_features(page, analysis_image)
            candidate, reasons = _is_candidate(
                features,
                first_page=page_index == 0,
                last_page=page_index == page_count - 1,
            )
            _diagnostic(
                "PDF_PAGE_CLASSIFICATION_CANDIDATE",
                source_unit_id=source_unit_id,
                candidate=candidate,
                reason_count=len(reasons),
            )
            classification = _fallback_classification(
                source_unit_id,
                "not_selected_for_multimodal_review",
            )
            if candidate:
                geometry_image, geometry = _geometry_only_page(page)
                classification_image = (
                    geometry_image
                    if geometry_image is not None
                    else v4._render_page_bgr(page, dpi=v4._ANALYSIS_DPI)
                )
                try:
                    classification = _classify(
                        _encode_png(classification_image),
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
                            "candidate_reasons": list(reasons),
                        },
                    )
                except Exception as exc:
                    classification = _fallback_classification(
                        source_unit_id,
                        f"classification_failed:{type(exc).__name__}",
                    )
                    _diagnostic(
                        "PDF_PAGE_CLASSIFICATION_FALLBACK_TO_OCR",
                        source_unit_id=source_unit_id,
                        reason=type(exc).__name__,
                    )
                skip_ocr, decision_reason = _skip_ocr_decision(
                    classification, features
                )
            else:
                geometry_image = None
                geometry = {}
                skip_ocr = False
                decision_reason = "not_a_local_candidate"

            classification = {
                **classification,
                "candidate_features": _json_clone(features),
                "candidate_reasons": list(reasons),
                "skip_ocr": skip_ocr,
                "decision_reason": decision_reason,
            }
            _diagnostic(
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

            if skip_ocr:
                presentation_count += 1
                _insert_geometry_or_original(
                    render_document,
                    source,
                    page_index,
                    geometry_image,
                )
                geometry_selected = bool(geometry.get("accepted"))
                page_manifest = {
                    "page_number": page_number,
                    "source_unit_id": source_unit_id,
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
                    "page_width_points": float(page.rect.width),
                    "page_height_points": float(page.rect.height),
                }
                _diagnostic(
                    "PDF_PAGE_PRESENTATION_GEOMETRY_SELECTED",
                    source_unit_id=source_unit_id,
                    selected=page_manifest["selected"],
                )
                _diagnostic(
                    "PDF_PAGE_BACKGROUND_SKIPPED",
                    source_unit_id=source_unit_id,
                    reason="presentation_page_background_skipped",
                )
                _diagnostic(
                    "PDF_PAGE_OCR_SKIPPED",
                    source_unit_id=source_unit_id,
                    page_kind=classification["page_role"],
                )
            else:
                render_document.insert_pdf(
                    v4_document, from_page=page_index, to_page=page_index
                )
                provider_index = provider_document.page_count
                provider_document.insert_pdf(
                    v4_document, from_page=page_index, to_page=page_index
                )
                provider_map.append(
                    {
                        "provider_page_index": provider_index,
                        "original_page_index": page_index,
                        "original_page_number": page_number,
                        "source_unit_id": source_unit_id,
                    }
                )
                page_manifest = base_pages.get(
                    page_number,
                    {
                        "page_number": page_number,
                        "route": "v4_manifest_unavailable",
                        "selected": "original",
                    },
                )
                page_manifest = {
                    **page_manifest,
                    "source_unit_id": source_unit_id,
                    "ocr_route": "modal_paddle_ocr",
                    "page_classification": classification,
                    "page_width_points": float(page.rect.width),
                    "page_height_points": float(page.rect.height),
                }
                if candidate and classification["page_role"] in PRESENTATION_PAGE_ROLES:
                    _diagnostic(
                        "PDF_PAGE_CLASSIFICATION_FALLBACK_TO_OCR",
                        source_unit_id=source_unit_id,
                        reason=decision_reason,
                    )
            page_entries.append(_json_clone(page_manifest))

        if presentation_count == 0:
            render_bytes = processed.pdf_bytes
        else:
            render_bytes = render_document.tobytes(garbage=4, deflate=True)
        render_checksum = hashlib.sha256(render_bytes).hexdigest()
        render_put = storage.put(
            render_bytes,
            _render_reference(processing_attempt_id, render_checksum),
            expected_size=len(render_bytes),
            expected_sha256=render_checksum,
        )

        provider_page_count = provider_document.page_count
        if presentation_count == 0:
            provider_put = render_put
            provider_bytes = render_bytes
        elif provider_page_count:
            provider_bytes = provider_document.tobytes(garbage=4, deflate=True)
            provider_checksum = hashlib.sha256(provider_bytes).hexdigest()
            provider_put = storage.put(
                provider_bytes,
                _provider_reference(processing_attempt_id, provider_checksum),
                expected_size=len(provider_bytes),
                expected_sha256=provider_checksum,
            )
        else:
            # No external provider call is made.  Reuse the render object only
            # so the grant wrapper still has a valid retained object.
            provider_bytes = render_bytes
            provider_put = render_put

        manifest = {
            **base_manifest,
            "version": "pre_ocr_presentation_route_v1",
            "render_pdf_sha256": render_put.checksum_sha256,
            "provider_input_sha256": provider_put.checksum_sha256,
            "page_count": source.page_count,
            "provider_page_count": provider_page_count,
            "presentation_page_count": presentation_count,
            "pages": page_entries,
            "provider_page_map": provider_map,
        }
        _register_manifest(
            processing_attempt_id,
            render_put.checksum_sha256,
            manifest,
        )
        _diagnostic(
            "PDF_PROVIDER_PAGE_MAP_CREATED",
            processing_attempt_id=processing_attempt_id,
            original_page_count=source.page_count,
            provider_page_count=provider_page_count,
            presentation_page_count=presentation_count,
        )

        stem = Path(original_filename or "document.pdf").stem or "document"
        full_processed = replace(
            processed,
            pdf_bytes=render_bytes,
            checksum_sha256=render_put.checksum_sha256,
            byte_size=render_put.byte_size,
            changed_page_count=sum(
                1
                for item in page_entries
                if item.get("selected") not in {"original", None}
            ),
        )
        return PresentationProviderInput(
            processing_attempt_id=processing_attempt_id,
            storage_reference=render_put.reference,
            checksum_sha256=render_put.checksum_sha256,
            byte_size=render_put.byte_size,
            media_type="application/pdf",
            filename=f"{stem}.presentation-render.pdf",
            preprocessing=full_processed,
            provider_storage_reference=provider_put.reference,
            provider_checksum_sha256=provider_put.checksum_sha256,
            provider_byte_size=provider_put.byte_size,
            provider_filename=f"{stem}.ordinary-pages.pdf",
            provider_page_count=provider_page_count,
            provider_page_map=tuple(provider_map),
            presentation_manifest=_json_clone(manifest),
        )
    finally:
        provider_document.close()
        render_document.close()
        v4_document.close()
        source.close()


def _manifest_pages(
    provider_input: PresentationProviderInput,
) -> dict[int, dict[str, object]]:
    pages = provider_input.presentation_manifest.get("pages")
    if not isinstance(pages, list):
        return {}
    result: dict[int, dict[str, object]] = {}
    for item in pages:
        if isinstance(item, Mapping) and isinstance(item.get("page_number"), int):
            result[int(item["page_number"])] = _json_clone(item)
    return result


def _synthetic_page(page: Mapping[str, object]) -> dict[str, object]:
    page_number = int(page["page_number"])
    return {
        "page_number": page_number,
        "page_index": page_number - 1,
        "local_page_index": 0,
        "source_page_range": {
            "page_start": page_number,
            "page_end": page_number,
        },
        "width": float(page.get("page_width_points") or 1),
        "height": float(page.get("page_height_points") or 1),
        "blocks": [],
        "parsing_res_list": [],
        "metadata": {
            "pre_ocr_page_classification": _json_clone(
                page.get("page_classification") or {}
            ),
            "opencv_preprocessing": _json_clone(page),
        },
    }


def _remap_raw_pages(
    raw_pages: Sequence[Mapping[str, object]],
    provider_input: PresentationProviderInput,
) -> list[dict[str, object]]:
    mapping = {
        int(item["provider_page_index"]): item
        for item in provider_input.provider_page_map
    }
    remapped: dict[int, dict[str, object]] = {}
    for provider_position, page in enumerate(raw_pages):
        item = mapping.get(provider_position)
        if item is None:
            raise ValueError("provider returned an unmapped page")
        copied = dict(page)
        original_number = int(item["original_page_number"])
        copied["page_number"] = original_number
        copied["page_index"] = int(item["original_page_index"])
        copied["local_page_index"] = 0
        copied["source_page_range"] = {
            "page_start": original_number,
            "page_end": original_number,
        }
        metadata = copied.get("metadata")
        copied["metadata"] = {
            **(dict(metadata) if isinstance(metadata, Mapping) else {}),
            "provider_page_index": provider_position,
            "original_page_index": int(item["original_page_index"]),
            "original_page_number": original_number,
            "source_unit_id": str(item["source_unit_id"]),
        }
        remapped[original_number] = copied
        _diagnostic(
            "PDF_PROVIDER_PAGE_RESULT_REMAPPED",
            provider_page_index=provider_position,
            original_page_number=original_number,
            source_unit_id=item["source_unit_id"],
        )

    for page_number, page in _manifest_pages(provider_input).items():
        if page.get("ocr_route") == "skipped_presentation_image":
            remapped[page_number] = _synthetic_page(page)
    expected = set(range(1, len(_manifest_pages(provider_input)) + 1))
    if set(remapped) != expected:
        raise ValueError("remapped provider result does not cover every original page")
    return [remapped[number] for number in sorted(remapped)]


def _remap_documents(
    documents: Sequence[Mapping[str, object]],
    provider_input: PresentationProviderInput,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for document in documents:
        copied = dict(document)
        raw = copied.get("raw_result")
        if isinstance(raw, list):
            copied["raw_result"] = _remap_raw_pages(raw, provider_input)
        result.append(copied)
    return result


def _remap_payload(
    payload: Mapping[str, object],
    provider_input: PresentationProviderInput,
) -> dict[str, object]:
    copied = dict(payload)
    documents = copied.get("documents")
    if isinstance(documents, list):
        copied["documents"] = _remap_documents(documents, provider_input)
    return copied


def _decode_artifact(content: bytes, compression: str | None) -> tuple[dict[str, object], bool]:
    compressed = str(compression or "").lower() in {"gzip", "gz"}
    raw = gzip.decompress(content) if compressed else content
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, Mapping):
        raise ValueError("provider artifact JSON must be an object")
    return dict(decoded), compressed


def _encode_artifact(payload: Mapping[str, object], compressed: bool) -> bytes:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return gzip.compress(raw) if compressed else raw


def _all_special_documents(
    request: Any,
    provider_input: PresentationProviderInput,
) -> list[dict[str, object]]:
    pages = [
        _synthetic_page(page)
        for _, page in sorted(_manifest_pages(provider_input).items())
    ]
    return [{"document_id": request.document_id, "raw_result": pages}]


def _add_presentation_carriers(spr: Any, manifest: Mapping[str, object] | None) -> Any:
    if not isinstance(manifest, Mapping):
        return spr
    pages = manifest.get("pages")
    if not isinstance(pages, list):
        return spr
    special = {
        str(item.get("source_unit_id")): item
        for item in pages
        if isinstance(item, Mapping)
        and item.get("ocr_route") == "skipped_presentation_image"
    }
    if not special:
        return spr

    from app.processing.structured_result_v2.model import (
        ProcessingNode,
        ProcessingNodeKind,
        ProcessingNodeRecoveryState,
    )
    from app.processing.structured_result_v2.validation import validate_spr_v2
    from app.source_units import SpatialAnchor

    retained = [
        node
        for node in spr.nodes
        if not any(source_unit_id in special for source_unit_id in node.source_unit_ids)
    ]
    unit_order = {
        unit.source_unit_id: unit.source_order for unit in spr.source_units
    }
    carriers = []
    for source_unit_id, page in special.items():
        classification = page.get("page_classification")
        classification = (
            dict(classification) if isinstance(classification, Mapping) else {}
        )
        carriers.append(
            ProcessingNode(
                node_id=f"pre-ocr-presentation:{source_unit_id}",
                kind=ProcessingNodeKind.FIGURE,
                order=0,
                source_unit_ids=(source_unit_id,),
                parent_id=None,
                text=None,
                heading_level=None,
                anchors=(SpatialAnchor(source_unit_id, 0.0, 0.0, 1.0, 1.0),),
                observation_ids=(),
                evidence_ids=(),
                recovery_state=ProcessingNodeRecoveryState.COMPLETE,
                metadata={
                    "recovery_engine": "pre_ocr_page_presentation_v1",
                    "recovery_rule": "pre_ocr_presentation_carrier",
                    "page_kind": page.get("page_kind"),
                    "presentation_mode": "source_rendering",
                    "ocr_route": "skipped_presentation_image",
                    "page_classification": classification,
                    "geometry": _json_clone(page.get("geometry") or {}),
                    "background": _json_clone(page.get("background") or {}),
                    "opencv_page_preprocessing": _json_clone(page),
                },
            )
        )
    combined = retained + carriers
    combined.sort(
        key=lambda node: (
            min(
                (unit_order.get(value, 2**31) for value in node.source_unit_ids),
                default=2**31,
            ),
            node.order,
            node.node_id,
        )
    )
    combined = [replace(node, order=index) for index, node in enumerate(combined)]
    updated = replace(spr, nodes=tuple(combined))
    validate_spr_v2(updated)
    return updated


def _pre_reviewed_source_units(
    manifest: Mapping[str, object] | None,
) -> frozenset[str]:
    if not isinstance(manifest, Mapping):
        return frozenset()
    pages = manifest.get("pages")
    if not isinstance(pages, list):
        return frozenset()
    return frozenset(
        str(item.get("source_unit_id"))
        for item in pages
        if isinstance(item, Mapping)
        and isinstance(item.get("page_classification"), Mapping)
        and item.get("page_classification", {}).get("provider") not in {None, "none"}
    )


def _presentation_asset_id(candidate_id: str, source_unit_id: str) -> str:
    digest = hashlib.sha256(
        f"{candidate_id}\x1f{source_unit_id}\x1fpresentation".encode()
    ).hexdigest()[:24]
    return f"pdf-source-rendering:{digest}"


def _enrich_presentation_assets(
    original_enrich: Callable[..., Any],
    candidate: Any,
    *,
    pdf_bytes: bytes,
    storage: Any,
    source_kind: str,
    enhancer: Any = None,
) -> Any:
    from app.source_units import SpatialAnchor
    from app.structured_content_v2.model import (
        AssetRecoveryStateV2,
        AssetReferenceV2,
        AssetRenditionReferenceV2,
        AssetRenditionRoleV2,
        AssetRoleV2,
        ContentNodeTypeV2,
        NodeRecoveryStateV2,
    )
    from app.processing import pdf_visual_assets as visual_assets

    presentation_nodes = [
        node
        for node in candidate.nodes
        if (node.metadata or {}).get("presentation_mode") == "source_rendering"
        and (node.metadata or {}).get("ocr_route")
        == "skipped_presentation_image"
    ]
    if not presentation_nodes:
        return original_enrich(
            candidate,
            pdf_bytes=pdf_bytes,
            storage=storage,
            source_kind=source_kind,
            enhancer=enhancer,
        )

    presentation_ids = frozenset(node.node_id for node in presentation_nodes)
    ordinary = replace(
        candidate,
        nodes=tuple(
            node for node in candidate.nodes if node.node_id not in presentation_ids
        ),
    )
    enriched = original_enrich(
        ordinary,
        pdf_bytes=pdf_bytes,
        storage=storage,
        source_kind=source_kind,
        enhancer=enhancer,
    )
    source_order = {
        item.source_unit.source_unit_id: item.source_unit.source_order
        for item in candidate.source_units
    }
    assets = list(enriched.assets)
    renditions = list(enriched.renditions)
    carriers = []
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for node in presentation_nodes:
            source_unit_id = node.source_unit_ids[0]
            page_index = source_order.get(source_unit_id)
            if page_index is None or not 0 <= page_index < document.page_count:
                raise ValueError("presentation page does not map to render PDF")
            anchor = SpatialAnchor(source_unit_id, 0.0, 0.0, 1.0, 1.0)
            png = document[page_index].get_pixmap(
                matrix=visual_assets._fitz_matrix(),
                alpha=False,
            ).tobytes("png")
            checksum = hashlib.sha256(png).hexdigest()
            asset_id = _presentation_asset_id(
                candidate.candidate_id, source_unit_id
            )
            rendition_id = f"rendition:{asset_id}:original"
            put = storage.put(
                png,
                visual_assets._rendition_reference(
                    "presentation", checksum
                ),
                expected_size=len(png),
                expected_sha256=checksum,
            )
            metadata = dict(node.metadata or {})
            metadata.update(
                {
                    "source_rendering_asset_id": asset_id,
                    "source_pdf_kind": source_kind,
                }
            )
            page_kind = str(metadata.get("page_kind") or "unknown")
            asset = AssetReferenceV2(
                asset_id=asset_id,
                role=AssetRoleV2.SOURCE_RENDERING,
                recovery_state=AssetRecoveryStateV2.AVAILABLE,
                source_unit_ids=(source_unit_id,),
                source_anchors=(anchor,),
                rendition_ids=(rendition_id,),
                evidence_ids=node.evidence_ids,
                alt_text=f"Full-page source rendering: {page_kind}",
                metadata={
                    "generation": "pdf_full_page_render_v3_presentation",
                    "page_kind": page_kind,
                    "source_pdf_kind": source_kind,
                    "ocr_route": "skipped_presentation_image",
                    "page_classification": _json_clone(
                        metadata.get("page_classification") or {}
                    ),
                    "geometry": _json_clone(metadata.get("geometry") or {}),
                    "background": _json_clone(
                        metadata.get("background") or {}
                    ),
                },
            )
            rendition = AssetRenditionReferenceV2(
                rendition_id=rendition_id,
                asset_id=asset_id,
                role=AssetRenditionRoleV2.ORIGINAL,
                artifact_ref=str(put.reference),
                media_type="image/png",
                checksum=put.checksum_sha256,
                recovery_state=AssetRecoveryStateV2.AVAILABLE,
                rebuildable=True,
            )
            assets.append(asset)
            renditions.append(rendition)
            carriers.append(
                replace(
                    node,
                    node_type=ContentNodeTypeV2.FIGURE,
                    recovery_state=NodeRecoveryStateV2.RECOVERED,
                    source_anchors=(anchor,),
                    metadata=metadata,
                    asset_ids=tuple(
                        dict.fromkeys((*node.asset_ids, asset_id))
                    ),
                )
            )
            _diagnostic(
                "PDF_PRESENTATION_ASSET_CREATED",
                source_unit_id=source_unit_id,
                page_kind=page_kind,
                asset_id=asset_id,
            )
    finally:
        document.close()

    nodes = list(enriched.nodes) + carriers
    nodes.sort(key=lambda node: (node.sibling_order, node.node_id))
    return replace(
        enriched,
        nodes=tuple(nodes),
        assets=tuple(assets),
        renditions=tuple(renditions),
    )


def _install_geometry_bridge() -> None:
    from app.processing import pdf_geometry_integration as integration
    from app.processing.models import (
        ArtifactMetadata,
        ProviderArtifact,
        ProviderLifecycleStatus,
        ProviderResult,
    )
    from app.processing.orchestration import (
        OrchestrationOutcome,
        OrchestrationPhase,
    )

    integration.GeometryProviderInput = PresentationProviderInput
    integration.prepare_geometry_provider_input = prepare_presentation_provider_input

    BaseGrant = integration.ProviderInputGrantService
    BaseProvider = integration.ProviderInputChecksumProvider
    BaseOrchestrator = integration.ProviderInputAwareProcessingOrchestrator

    class PresentationGrantService(BaseGrant):
        def create_grant(self, **kwargs):
            kwargs = dict(kwargs)
            kwargs.update(
                {
                    "storage_reference": self._provider_input.provider_storage_reference,
                    "source_sha256": self._provider_input.provider_checksum_sha256,
                    "source_byte_size": self._provider_input.provider_byte_size,
                    "media_type": self._provider_input.media_type,
                    "source_etag": None,
                    "filename": self._provider_input.provider_filename,
                }
            )
            return self._delegate.create_grant(**kwargs)

        def revoke(self, grant_id):
            descriptor = self._delegate.revoke(grant_id)
            if (
                self._provider_input.provider_storage_reference
                != self._provider_input.storage_reference
            ):
                try:
                    from app.storage.dependencies import get_storage_provider

                    get_storage_provider().delete(
                        self._provider_input.provider_storage_reference
                    )
                except Exception:
                    _logger.exception(
                        "Could not delete presentation provider subset"
                    )
            return descriptor

    class PresentationChecksumProvider(BaseProvider):
        async def submit_job(self, request):
            documents = [
                replace(
                    document,
                    pdf_source_etag=None,
                    pdf_source_sha256=(
                        self._provider_input.provider_checksum_sha256
                    ),
                )
                for document in request.documents
            ]
            return await self._delegate.submit_job(
                replace(request, documents=documents)
            )

        async def get_job_result(self, job_id: str, profile: str | None = None):
            result = await self._delegate.get_job_result(job_id, profile)
            documents = _remap_documents(
                result.documents or [],
                self._provider_input,
            )
            raw_payload = result.raw_provider_payload
            if isinstance(raw_payload, Mapping):
                raw_payload = _remap_payload(
                    raw_payload,
                    self._provider_input,
                )
            return replace(
                result,
                documents=documents,
                raw_provider_payload=raw_payload,
            )

        async def get_job_artifact(
            self,
            job_id: str,
            metadata: ArtifactMetadata | None = None,
        ):
            artifact = await self._delegate.get_job_artifact(job_id, metadata)
            payload, compressed = _decode_artifact(
                artifact.content,
                artifact.metadata.compression,
            )
            remapped = _remap_payload(payload, self._provider_input)
            content = _encode_artifact(remapped, compressed)
            checksum = hashlib.sha256(content).hexdigest()
            updated_metadata = replace(
                artifact.metadata,
                size_bytes=len(content),
                sha256=checksum,
            )
            return ProviderArtifact(job_id, content, updated_metadata)

    class PresentationOrchestrator(BaseOrchestrator):
        async def run_once(self, request, policy=None):
            if self.provider_input.provider_page_count:
                return await super().run_once(request, policy)
            started = monotonic()
            documents = _all_special_documents(
                request, self.provider_input
            )
            result = ProviderResult(
                job_id=request.provider_job_id,
                request_id=request.provider_request_id,
                status=ProviderLifecycleStatus.PROVIDER_COMPLETED,
                profile=request.result_profile,
                result_artifact=None,
                documents=documents,
                raw_provider_payload={
                    "job_id": request.provider_job_id,
                    "request_id": request.provider_request_id,
                    "status": "provider_completed",
                    "profile": request.result_profile,
                    "documents": documents,
                    "build_tag": "pre-ocr-presentation-local",
                },
            )
            from app.processing import orchestration

            summary = orchestration._page_summary(request, result)
            raw = await self._ingest(request, result, summary)
            _diagnostic(
                "PDF_PROVIDER_SKIPPED_ALL_PRESENTATION",
                processing_attempt_id=request.processing_attempt_id,
                page_count=len(documents[0]["raw_result"]),
            )
            return OrchestrationOutcome(
                processing_attempt_id=request.processing_attempt_id,
                correlation_id=request.correlation_id,
                document_id=request.document_id,
                source_file_id=request.source_file_id,
                provider_name=request.provider_name,
                provider_job_id=request.provider_job_id,
                provider_request_id=request.provider_request_id,
                final_phase=OrchestrationPhase.RAW_RESULT_RETAINED,
                provider_terminal_status=ProviderLifecycleStatus.PROVIDER_COMPLETED,
                elapsed_seconds=max(0.0, monotonic() - started),
                poll_count=0,
                provider_status_snapshot=None,
                raw_result=raw,
                page_summary=summary,
            )

    integration.ProviderInputGrantService = PresentationGrantService
    integration.ProviderInputChecksumProvider = PresentationChecksumProvider
    integration.ProviderInputAwareProcessingOrchestrator = PresentationOrchestrator


def _install_canonicalization_bridge() -> None:
    from app.processing import batched_structure_refinement as batched
    from app.processing import pdf_canonicalization as canonicalization

    original_boundaries = batched._document_boundary_positions
    original_recover = canonicalization.recover_pdf_observations_to_spr_v2
    original_canonicalize = canonicalization.PdfCanonicalizationService.canonicalize
    original_enrich = canonicalization.enrich_candidate_with_pdf_visual_assets

    def boundaries_without_pre_reviewed(spr):
        positions = original_boundaries(spr)
        reviewed = _pre_reviewed_source_units(
            _CURRENT_PRESENTATION_MANIFEST.get()
        )
        return {
            source_unit_id: position
            for source_unit_id, position in positions.items()
            if source_unit_id not in reviewed
        }

    def recover_with_presentations(*args, **kwargs):
        recovered = original_recover(*args, **kwargs)
        return _add_presentation_carriers(
            recovered,
            _CURRENT_PRESENTATION_MANIFEST.get(),
        )

    def enrich_with_presentations(candidate, **kwargs):
        return _enrich_presentation_assets(
            original_enrich,
            candidate,
            **kwargs,
        )

    def canonicalize_with_presentations(self, envelope):
        checksum = getattr(self, "render_pdf_checksum_sha256", None)
        manifest = None
        if checksum:
            try:
                from app.processing import pdf_opencv_modal_bridge as v4_bridge

                manifest = v4_bridge._manifest_for_attempt(
                    envelope.identity.atlas_attempt_id,
                    checksum,
                )
            except Exception:
                manifest = None
        token = _CURRENT_PRESENTATION_MANIFEST.set(manifest)
        try:
            return original_canonicalize(self, envelope)
        finally:
            _CURRENT_PRESENTATION_MANIFEST.reset(token)

    batched._document_boundary_positions = boundaries_without_pre_reviewed
    canonicalization.recover_pdf_observations_to_spr_v2 = (
        recover_with_presentations
    )
    canonicalization.enrich_candidate_with_pdf_visual_assets = (
        enrich_with_presentations
    )
    canonicalization.PdfCanonicalizationService.canonicalize = (
        canonicalize_with_presentations
    )


def install_pre_ocr_presentation_bridge() -> None:
    """Install the pre-OCR presentation route once per backend process."""

    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _install_geometry_bridge()
        _install_canonicalization_bridge()
        _INSTALLED = True


__all__ = [
    "ALL_PAGE_ROLES",
    "PRESENTATION_PAGE_ROLES",
    "PresentationProviderInput",
    "install_pre_ocr_presentation_bridge",
    "prepare_presentation_provider_input",
]
