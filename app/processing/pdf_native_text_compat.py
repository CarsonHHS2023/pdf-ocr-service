"""Test-only native PDF text recovery before the Modal OCR provider boundary.

Reliable born-digital pages are converted to the same page/block envelope used by
Paddle normalization and are omitted from the provider subset. Pages that expose
a text layer but fail the conservative quality gate are rasterized only in the
derived provider input; the retained source and Reader rendering remain the
original PDF page.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
import math
import re
import statistics
from typing import Any

import fitz  # type: ignore[import]

from app.processing import pdf_page_presentation_bridge as bridge
from app.processing import pdf_page_presentation_preprocess_compat as preprocess


_VERSION = "native_pdf_text_v1"
_MIN_RAW_TEXT_CHARS_FOR_FALLBACK = 80
_MIN_ACCEPTED_TEXT_CHARS = 120
_MIN_ACCEPTED_LINE_COUNT = 4
_MAX_FULL_PAGE_IMAGE_COVERAGE = 0.80
_MIN_PRINTABLE_RATIO = 0.98
_MAX_CONTROL_RATIO = 0.01
_MAX_DUPLICATE_LINE_RATIO = 0.25
_IMAGE_TEXT_OVERLAP_RATIO = 0.65
_INSTALLED = False

_PAGE_NUMBER_RE = re.compile(r"^(?:\d{1,4}|[IVXLCDMivxlcdm]{1,8})$")
_SENTENCE_END_RE = re.compile(r"[。！？!?；;：:]\s*$")
_CJK_RE = re.compile(r"[\u3000-\u303f\u3400-\u9fff]")


def _rect(value: Any) -> fitz.Rect | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        rect = fitz.Rect(*(float(item) for item in value))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in (rect.x0, rect.y0, rect.x1, rect.y1)):
        return None
    if rect.is_empty or rect.width <= 0 or rect.height <= 0:
        return None
    return rect


def _intersection_ratio(left: fitz.Rect, right: fitz.Rect) -> float:
    intersection = left & right
    if intersection.is_empty:
        return 0.0
    area = max(1.0, float(left.width * left.height))
    return max(0.0, float(intersection.width * intersection.height) / area)


def _image_rectangles(page: fitz.Page) -> list[fitz.Rect]:
    result: list[fitz.Rect] = []
    seen: set[tuple[float, float, float, float]] = set()
    try:
        images = page.get_images(full=True)
    except Exception:
        images = []
    for image in images:
        if not image:
            continue
        try:
            rectangles = page.get_image_rects(int(image[0]))
        except Exception:
            rectangles = []
        for rectangle in rectangles:
            clipped = rectangle & page.rect
            if clipped.is_empty or clipped.width <= 0 or clipped.height <= 0:
                continue
            key = tuple(round(float(value), 4) for value in clipped)
            if key in seen:
                continue
            seen.add(key)
            result.append(clipped)
    return result


def _line_records(page: fitz.Page) -> tuple[list[dict[str, Any]], list[fitz.Rect], int]:
    image_rects = _image_rectangles(page)
    try:
        payload = page.get_text("dict") or {}
    except Exception:
        payload = {}
    blocks = payload.get("blocks") if isinstance(payload, Mapping) else []
    blocks = blocks if isinstance(blocks, list) else []

    records: list[dict[str, Any]] = []
    raw_chars = 0
    for block in blocks:
        if not isinstance(block, Mapping) or int(block.get("type", 0) or 0) != 0:
            continue
        lines = block.get("lines")
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, Mapping):
                continue
            spans = line.get("spans")
            if not isinstance(spans, list):
                continue
            visible: list[tuple[str, fitz.Rect, float, int]] = []
            for span in spans:
                if not isinstance(span, Mapping):
                    continue
                text = span.get("text")
                if not isinstance(text, str) or not text.strip():
                    continue
                raw_chars += len(text.strip())
                alpha = span.get("alpha", 255)
                if isinstance(alpha, (int, float)) and not isinstance(alpha, bool) and alpha <= 8:
                    continue
                bbox = _rect(span.get("bbox"))
                if bbox is None:
                    continue
                bbox &= page.rect
                if bbox.is_empty or bbox.width <= 0 or bbox.height <= 0:
                    continue
                size = span.get("size")
                font_size = (
                    float(size)
                    if isinstance(size, (int, float))
                    and not isinstance(size, bool)
                    and math.isfinite(float(size))
                    and float(size) > 0
                    else float(bbox.height)
                )
                flags = span.get("flags")
                visible.append(
                    (
                        text,
                        bbox,
                        font_size,
                        int(flags) if isinstance(flags, int) and not isinstance(flags, bool) else 0,
                    )
                )
            if not visible:
                continue
            text = "".join(item[0] for item in visible).strip()
            if not text:
                continue
            bbox = fitz.Rect(
                min(item[1].x0 for item in visible),
                min(item[1].y0 for item in visible),
                max(item[1].x1 for item in visible),
                max(item[1].y1 for item in visible),
            )
            image_overlap = max(
                (_intersection_ratio(bbox, image_rect) for image_rect in image_rects),
                default=0.0,
            )
            center_inside_image = any(
                image_rect.contains(fitz.Point((bbox.x0 + bbox.x1) / 2, (bbox.y0 + bbox.y1) / 2))
                for image_rect in image_rects
            )
            records.append(
                {
                    "text": text,
                    "bbox": bbox,
                    "font_size": statistics.median(item[2] for item in visible),
                    "flags": max(item[3] for item in visible),
                    "inside_image": bool(
                        center_inside_image and image_overlap >= _IMAGE_TEXT_OVERLAP_RATIO
                    ),
                }
            )
    records.sort(
        key=lambda item: (
            round(float(item["bbox"].y0), 3),
            round(float(item["bbox"].x0), 3),
        )
    )
    return records, image_rects, raw_chars


def _text_health(text: str, lines: Sequence[dict[str, Any]]) -> dict[str, float | int]:
    if not text:
        return {
            "printable_ratio": 0.0,
            "control_ratio": 1.0,
            "replacement_count": 0,
            "duplicate_line_ratio": 0.0,
        }
    printable = sum(character.isprintable() or character in "\n\t" for character in text)
    controls = sum(
        ord(character) < 32 and character not in "\n\t\r" for character in text
    )
    normalized_lines = [
        re.sub(r"\s+", "", str(item.get("text") or ""))
        for item in lines
        if str(item.get("text") or "").strip()
    ]
    duplicate_count = len(normalized_lines) - len(set(normalized_lines))
    return {
        "printable_ratio": round(printable / max(1, len(text)), 6),
        "control_ratio": round(controls / max(1, len(text)), 6),
        "replacement_count": text.count("\ufffd"),
        "duplicate_line_ratio": round(
            duplicate_count / max(1, len(normalized_lines)), 6
        ),
    }


def _validate_native_text_layer(page: fitz.Page) -> tuple[dict[str, Any], list[dict[str, Any]], list[fitz.Rect]]:
    records, image_rects, raw_chars = _line_records(page)
    usable = [item for item in records if not item["inside_image"]]
    text = "\n".join(str(item["text"]) for item in usable)
    usable_chars = len(re.sub(r"\s+", "", text))
    page_area = max(1.0, float(page.rect.width * page.rect.height))
    max_image_coverage = max(
        (
            float(rect.width * rect.height) / page_area
            for rect in image_rects
        ),
        default=0.0,
    )
    health = _text_health(text, usable)

    reason = "native_text_layer_accepted"
    accepted = True
    if usable_chars < _MIN_ACCEPTED_TEXT_CHARS:
        accepted = False
        reason = "native_text_too_sparse"
    elif len(usable) < _MIN_ACCEPTED_LINE_COUNT:
        accepted = False
        reason = "native_text_line_count_too_low"
    elif max_image_coverage > _MAX_FULL_PAGE_IMAGE_COVERAGE:
        accepted = False
        reason = "full_page_image_dominates_native_text"
    elif float(health["printable_ratio"]) < _MIN_PRINTABLE_RATIO:
        accepted = False
        reason = "native_text_printability_failed"
    elif float(health["control_ratio"]) > _MAX_CONTROL_RATIO:
        accepted = False
        reason = "native_text_control_characters_failed"
    elif int(health["replacement_count"]) > 0:
        accepted = False
        reason = "native_text_replacement_characters_failed"
    elif float(health["duplicate_line_ratio"]) > _MAX_DUPLICATE_LINE_RATIO:
        accepted = False
        reason = "native_text_duplicate_lines_failed"

    validation = {
        "accepted": accepted,
        "reason": reason,
        "version": _VERSION,
        "native_text_chars": raw_chars,
        "usable_native_text_chars": usable_chars,
        "native_text_line_count": len(records),
        "usable_native_text_line_count": len(usable),
        "image_internal_text_line_count": len(records) - len(usable),
        "embedded_image_count": len(image_rects),
        "maximum_embedded_image_coverage": round(max_image_coverage, 6),
        "raster_fallback_required": bool(
            not accepted and raw_chars >= _MIN_RAW_TEXT_CHARS_FOR_FALLBACK
        ),
        **health,
    }
    return validation, usable, image_rects


def _body_font_size(lines: Sequence[dict[str, Any]]) -> float:
    values = [
        float(item["font_size"])
        for item in lines
        if isinstance(item.get("font_size"), (int, float))
        and not isinstance(item.get("font_size"), bool)
        and float(item["font_size"]) > 0
    ]
    return statistics.median(values) if values else 1.0


def _line_kind(
    line: Mapping[str, Any],
    *,
    page: fitz.Page,
    body_font_size: float,
) -> str:
    text = str(line.get("text") or "").strip()
    bbox = line["bbox"]
    if bbox.y0 >= page.rect.height * 0.88 and _PAGE_NUMBER_RE.fullmatch(text):
        return "number"
    size = float(line.get("font_size") or 0)
    centered = abs(((bbox.x0 + bbox.x1) / 2) - page.rect.width / 2) <= page.rect.width * 0.18
    if len(text) <= 80 and (
        size >= body_font_size * 1.10
        or (centered and size >= body_font_size * 1.03)
    ):
        return "paragraph_title"
    return "text"


def _join_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    if _CJK_RE.search(left[-1:]) or _CJK_RE.match(right[:1]):
        return left.rstrip() + right.lstrip()
    return left.rstrip() + " " + right.lstrip()


def _paragraph_blocks(page: fitz.Page, lines: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    body_size = _body_font_size(lines)
    prepared = [
        {**item, "kind": _line_kind(item, page=page, body_font_size=body_size)}
        for item in lines
    ]
    body_left = min(
        (float(item["bbox"].x0) for item in prepared if item["kind"] == "text"),
        default=0.0,
    )
    result: list[dict[str, Any]] = []
    for item in prepared:
        bbox: fitz.Rect = item["bbox"]
        kind = str(item["kind"])
        text = str(item["text"]).strip()
        if not text:
            continue
        can_merge = False
        if result and kind == "text" and result[-1]["type"] == "text":
            previous = result[-1]
            previous_bbox = fitz.Rect(previous["bbox"])
            vertical_gap = float(bbox.y0 - previous_bbox.y1)
            line_height = max(1.0, float(bbox.height), float(previous_bbox.height))
            starts_indented = float(bbox.x0) >= body_left + max(8.0, page.rect.width * 0.025)
            previous_terminal = bool(_SENTENCE_END_RE.search(str(previous["text"])))
            can_merge = bool(
                vertical_gap <= line_height * 1.15
                and not (starts_indented and previous_terminal)
            )
        if can_merge:
            previous = result[-1]
            previous["text"] = _join_text(str(previous["text"]), text)
            previous_bbox = fitz.Rect(previous["bbox"])
            previous["bbox"] = [
                min(previous_bbox.x0, bbox.x0),
                min(previous_bbox.y0, bbox.y0),
                max(previous_bbox.x1, bbox.x1),
                max(previous_bbox.y1, bbox.y1),
            ]
            previous["metadata"]["native_line_count"] += 1
            continue
        result.append(
            {
                "type": kind,
                "text": text,
                "bbox": [bbox.x0, bbox.y0, bbox.x1, bbox.y1],
                "metadata": {
                    "label": kind,
                    "native_pdf_source": True,
                    "native_text_version": _VERSION,
                    "native_line_count": 1,
                },
            }
        )
    return result


def _figure_blocks(page: fitz.Page, image_rects: Sequence[fitz.Rect]) -> list[dict[str, Any]]:
    page_area = max(1.0, float(page.rect.width * page.rect.height))
    result: list[dict[str, Any]] = []
    for rectangle in image_rects:
        coverage = float(rectangle.width * rectangle.height) / page_area
        if coverage < 0.01 or coverage > _MAX_FULL_PAGE_IMAGE_COVERAGE:
            continue
        result.append(
            {
                "type": "image",
                "text": None,
                "bbox": [rectangle.x0, rectangle.y0, rectangle.x1, rectangle.y1],
                "metadata": {
                    "label": "image",
                    "native_pdf_source": True,
                    "native_text_version": _VERSION,
                    "embedded_image_coverage": round(coverage, 6),
                },
            }
        )
    return result


def build_native_raw_page(
    page: fitz.Page,
    *,
    page_number: int,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    validation, usable_lines, image_rects = _validate_native_text_layer(page)
    if not validation["accepted"]:
        return None, validation
    blocks = [
        *_paragraph_blocks(page, usable_lines),
        *_figure_blocks(page, image_rects),
    ]
    blocks.sort(
        key=lambda item: (
            round(float(item["bbox"][1]), 4),
            round(float(item["bbox"][0]), 4),
            0 if item["type"] != "image" else 1,
        )
    )
    for order, block in enumerate(blocks):
        block["order"] = order
    return (
        {
            "page_number": page_number,
            "page_index": page_number - 1,
            "local_page_index": 0,
            "source_page_range": {
                "page_start": page_number,
                "page_end": page_number,
            },
            "width": float(page.rect.width),
            "height": float(page.rect.height),
            "blocks": blocks,
            "parsing_res_list": [],
            "metadata": {
                "native_pdf_text": dict(validation),
                "source_unit_id": bridge._source_unit_id(page_number),
            },
        },
        validation,
    )


def _native_manifest_page(decision: Mapping[str, Any]) -> dict[str, Any]:
    classification = bridge._json_clone(decision.get("classification") or {})
    validation = bridge._json_clone(decision.get("native_text_validation") or {})
    return {
        "page_number": int(decision["page_number"]),
        "source_unit_id": str(decision["source_unit_id"]),
        "route": "native_pdf_text",
        "selected": "original",
        "structure": {
            "native_text_chars": validation.get("native_text_chars", 0),
            "usable_native_text_chars": validation.get("usable_native_text_chars", 0),
            "maximum_embedded_image_coverage": validation.get(
                "maximum_embedded_image_coverage", 0
            ),
        },
        "geometry": {
            "accepted": False,
            "reason": "native_pdf_original_preserved",
            "applied_steps": [],
        },
        "background": {
            "attempted": False,
            "accepted": False,
            "reason": "native_pdf_text_page_background_skipped",
            "gate": {},
        },
        "page_kind": "body",
        "presentation_mode": "structured_native_text",
        "ocr_route": "native_pdf_text",
        "page_classification": classification,
        "native_text_validation": validation,
        "native_raw_page": bridge._json_clone(decision["native_raw_page"]),
        "page_width_points": float(decision["page_width_points"]),
        "page_height_points": float(decision["page_height_points"]),
    }


def _native_result_page(page: Mapping[str, Any]) -> dict[str, Any]:
    raw = page.get("native_raw_page")
    if not isinstance(raw, Mapping):
        raise ValueError("native PDF manifest page is missing native_raw_page")
    copied = bridge._json_clone(raw)
    metadata = copied.get("metadata")
    copied["metadata"] = {
        **(dict(metadata) if isinstance(metadata, Mapping) else {}),
        "pre_ocr_page_classification": bridge._json_clone(
            page.get("page_classification") or {}
        ),
        "opencv_preprocessing": bridge._json_clone(page),
        "native_pdf_text": bridge._json_clone(
            page.get("native_text_validation") or {}
        ),
    }
    return copied


def _remap_raw_pages_with_native(
    raw_pages: Sequence[Mapping[str, Any]],
    provider_input: bridge.PresentationProviderInput,
) -> list[dict[str, Any]]:
    mapping = {
        int(item["provider_page_index"]): item
        for item in provider_input.provider_page_map
    }
    remapped: dict[int, dict[str, Any]] = {}
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
            "provider_input_mode": str(item.get("provider_input_mode") or "pdf_page"),
        }
        remapped[original_number] = copied
        bridge._diagnostic(
            "PDF_PROVIDER_PAGE_RESULT_REMAPPED",
            provider_page_index=provider_position,
            original_page_number=original_number,
            source_unit_id=item["source_unit_id"],
        )

    manifest_pages = bridge._manifest_pages(provider_input)
    for page_number, page in manifest_pages.items():
        route = page.get("ocr_route")
        if route == "skipped_presentation_image":
            remapped[page_number] = bridge._synthetic_page(page)
        elif route == "native_pdf_text":
            remapped[page_number] = _native_result_page(page)
    expected = set(range(1, len(manifest_pages) + 1))
    if set(remapped) != expected:
        raise ValueError("remapped provider result does not cover every original page")
    return [remapped[number] for number in sorted(remapped)]


def _all_local_documents(
    request: Any,
    provider_input: bridge.PresentationProviderInput,
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for _, page in sorted(bridge._manifest_pages(provider_input).items()):
        if page.get("ocr_route") == "native_pdf_text":
            pages.append(_native_result_page(page))
        else:
            pages.append(bridge._synthetic_page(page))
    return [{"document_id": request.document_id, "raw_result": pages}]


def _build_ordinary_source_with_native(
    source: fitz.Document,
    decisions: list[dict[str, Any]],
) -> tuple[bytes | None, list[dict[str, Any]]]:
    from app.processing import pdf_opencv_quality_pipeline as v4

    ordinary = fitz.open()
    provider_map: list[dict[str, Any]] = []
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
            if fallback_raster:
                raster = v4._render_page_bgr(page, dpi=v4._RENDER_DPI)
                v4._insert_raster_page(ordinary, page.rect, raster)
                input_mode = "native_text_fallback_raster"
            else:
                ordinary.insert_pdf(source, from_page=page_index, to_page=page_index)
                input_mode = "pdf_page"
            provider_map.append(
                {
                    "provider_page_index": provider_page_index,
                    "original_page_index": page_index,
                    "original_page_number": int(decision["page_number"]),
                    "source_unit_id": str(decision["source_unit_id"]),
                    "provider_input_mode": input_mode,
                }
            )
        if ordinary.page_count == 0:
            return None, provider_map
        return ordinary.tobytes(garbage=4, deflate=True), provider_map
    finally:
        ordinary.close()


def install_native_pdf_text_compat() -> None:
    """Install native-page extraction after presentation and high-res routing."""

    global _INSTALLED
    if _INSTALLED:
        return

    original_classify = preprocess._classify_source_pages
    original_manifest_page = preprocess._presentation_manifest_page
    original_geometry_result = preprocess._presentation_geometry_result

    def classify_with_native(source: fitz.Document) -> list[dict[str, Any]]:
        decisions = original_classify(source)
        for decision in decisions:
            if bool(decision.get("skip_ocr")):
                continue
            page_index = int(decision["page_index"])
            raw_page, validation = build_native_raw_page(
                source[page_index],
                page_number=int(decision["page_number"]),
            )
            decision["native_text_validation"] = validation
            if raw_page is not None:
                decision["native_raw_page"] = raw_page
                decision["native_text_accepted"] = True
                decision["skip_ocr"] = True
                decision["decision_reason"] = "native_pdf_text_accepted"
                decision["geometry_image"] = None
                decision["geometry"] = {}
                classification = dict(decision.get("classification") or {})
                classification.update(
                    {
                        "native_text_accepted": True,
                        "native_text_version": _VERSION,
                        "skip_ocr": True,
                        "decision_reason": "native_pdf_text_accepted",
                    }
                )
                decision["classification"] = classification
                bridge._diagnostic(
                    "PDF_NATIVE_TEXT_PAGE_ACCEPTED",
                    source_unit_id=decision["source_unit_id"],
                    native_text_chars=validation["usable_native_text_chars"],
                    native_text_line_count=validation["usable_native_text_line_count"],
                    embedded_image_count=validation["embedded_image_count"],
                )
            elif validation["raster_fallback_required"]:
                decision["native_text_fallback_raster"] = True
                bridge._diagnostic(
                    "PDF_NATIVE_TEXT_PAGE_RASTER_FALLBACK",
                    source_unit_id=decision["source_unit_id"],
                    reason=validation["reason"],
                    native_text_chars=validation["native_text_chars"],
                    maximum_embedded_image_coverage=validation[
                        "maximum_embedded_image_coverage"
                    ],
                )
        return decisions

    def manifest_page_with_native(decision: Mapping[str, Any]) -> dict[str, Any]:
        if decision.get("native_text_accepted"):
            return _native_manifest_page(decision)
        return original_manifest_page(decision)

    def geometry_result_with_native(decision: Mapping[str, Any]):
        result = original_geometry_result(decision)
        if not decision.get("native_text_accepted"):
            return result
        return replace(
            result,
            applied_steps=(),
            fallback_used=False,
            safe_reason="native_text_layer_accepted",
            route="native_pdf_text_no_op",
        )

    preprocess._classify_source_pages = classify_with_native
    preprocess._build_ordinary_source = _build_ordinary_source_with_native
    preprocess._presentation_manifest_page = manifest_page_with_native
    preprocess._presentation_geometry_result = geometry_result_with_native
    bridge._remap_raw_pages = _remap_raw_pages_with_native
    bridge._all_special_documents = _all_local_documents
    _INSTALLED = True


__all__ = [
    "build_native_raw_page",
    "install_native_pdf_text_compat",
]
