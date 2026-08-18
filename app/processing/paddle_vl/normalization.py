"""Pure Paddle PDF result -> provider-independent source-unit observation adapter.

This module deliberately stops before document-structure recovery. It converts
retained Paddle page/block payloads into physical-page SourceUnits plus the
observation/evidence primitives later consumed by the recovery layer.
"""
from __future__ import annotations

import re
from math import isfinite
from typing import Any, Mapping, Sequence

from app.processing.normalized_observations import NormalizedPdfObservationBundle
from app.processing.structured_result_v2.model import ProcessingEvidence, ProcessingObservation
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind, SpatialAnchor


class PaddlePdfNormalizationError(ValueError):
    """Raised when retained Paddle PDF output cannot be normalized safely."""


def normalize_paddle_pdf_raw_result(
    raw_result: Sequence[Mapping[str, Any]],
    *,
    document_ref: str,
    source_ref: str,
    processing_run_ref: str,
    raw_result_ref: str | None = None,
    provider_ref: str = "paddle-vl",
) -> NormalizedPdfObservationBundle:
    """Normalize one document's Paddle ``raw_result`` page list.

    The adapter preserves original PDF page identity and provider observations,
    but does not infer headings, paragraphs, parentage, or any other semantic
    document structure.
    """
    _require_nonempty(document_ref, "document_ref")
    _require_nonempty(source_ref, "source_ref")
    _require_nonempty(processing_run_ref, "processing_run_ref")
    _require_nonempty(provider_ref, "provider_ref")
    if raw_result_ref is not None:
        _require_nonempty(raw_result_ref, "raw_result_ref")
    if isinstance(raw_result, (str, bytes)) or not isinstance(raw_result, Sequence):
        raise PaddlePdfNormalizationError("raw_result must be a sequence of page mappings")

    prepared_pages: list[tuple[int, Mapping[str, Any]]] = []
    seen_pages: set[int] = set()
    for page in raw_result:
        if not isinstance(page, Mapping):
            raise PaddlePdfNormalizationError("each raw_result page must be a mapping")
        page_number = _positive_int(page.get("page_number"), "page_number")
        if page_number in seen_pages:
            raise PaddlePdfNormalizationError(f"duplicate source page: {page_number}")
        seen_pages.add(page_number)
        _validate_page_identity(page, page_number)
        prepared_pages.append((page_number, page))

    prepared_pages.sort(key=lambda item: item[0])
    units: list[SourceUnit] = []
    observations: list[ProcessingObservation] = []
    evidence: list[ProcessingEvidence] = []

    for page_number, page in prepared_pages:
        width = _positive_number(page.get("width"), f"page {page_number} width")
        height = _positive_number(page.get("height"), f"page {page_number} height")
        source_unit_id = _page_source_unit_id(page_number)
        units.append(
            SourceUnit(
                source_unit_id=source_unit_id,
                kind=SourceUnitKind.PHYSICAL_PAGE,
                source_order=page_number - 1,
                source_ref=source_ref,
                dimensions=SourceUnitDimensions(width=width, height=height),
            )
        )

        blocks = _page_blocks(page, page_number)
        ordered_blocks = sorted(
            enumerate(blocks),
            key=lambda pair: (_block_order(pair[1], pair[0]), pair[0]),
        )
        for normalized_index, (input_index, block) in enumerate(ordered_blocks):
            observed_kind = _observed_kind(block)
            text = _block_text(block)
            confidence = _confidence(block)
            anchor = _spatial_anchor(block, source_unit_id, width, height, page_number)
            observation_id = f"pdf-observation:p{page_number:06d}:b{normalized_index:06d}"
            evidence_id = f"pdf-evidence:p{page_number:06d}:b{normalized_index:06d}"
            metadata = {
                "provider_page_index": page.get("page_index"),
                "provider_local_page_index": page.get("local_page_index"),
                "provider_block_input_index": input_index,
                "provider_block_order": block.get("order"),
            }
            observations.append(
                ProcessingObservation(
                    observation_id=observation_id,
                    source_unit_id=source_unit_id,
                    order=normalized_index,
                    observed_kind=observed_kind,
                    text=text,
                    anchors=(anchor,),
                    confidence=confidence,
                    evidence_ids=(evidence_id,),
                    metadata=metadata,
                )
            )
            evidence.append(
                ProcessingEvidence(
                    evidence_id=evidence_id,
                    source_unit_id=source_unit_id,
                    anchors=(anchor,),
                    observation_id=observation_id,
                    processing_run_ref=processing_run_ref,
                    raw_result_ref=raw_result_ref,
                    provider_ref=provider_ref,
                    metadata={"page_number": page_number, "provider_observed_kind": observed_kind},
                )
            )

    return NormalizedPdfObservationBundle(
        document_ref=document_ref,
        source_ref=source_ref,
        processing_run_ref=processing_run_ref,
        raw_result_ref=raw_result_ref,
        source_units=tuple(units),
        observations=tuple(observations),
        evidence=tuple(evidence),
    )


def _page_source_unit_id(page_number: int) -> str:
    return f"pdf-page:{page_number:06d}"


def _page_blocks(page: Mapping[str, Any], page_number: int) -> list[Mapping[str, Any]]:
    candidate = page.get("blocks")
    if candidate is not None:
        if not isinstance(candidate, list):
            raise PaddlePdfNormalizationError(f"page {page_number} blocks must be a list")
        result: list[Mapping[str, Any]] = []
        for block in candidate:
            if not isinstance(block, Mapping):
                raise PaddlePdfNormalizationError(f"page {page_number} block must be a mapping")
            result.append(block)
        return result

    parsing = page.get("parsing_res_list", [])
    if not isinstance(parsing, list):
        raise PaddlePdfNormalizationError(f"page {page_number} blocks must be a list")
    return [_coerce_parsing_entry(block, index, page_number) for index, block in enumerate(parsing)]


def _coerce_parsing_entry(block: Any, order: int, page_number: int) -> Mapping[str, Any]:
    """Adapt PaddleOCR-VL ``parsing_res_list`` entries to the stable block mapping shape.

    PaddleOCR-VL can emit parsing entries as multiline strings rather than JSON
    objects. Modal already accepts that provider shape. The backend adapter must
    therefore parse only that provider-specific fallback while keeping the public
    ``blocks`` path strict.
    """
    if isinstance(block, Mapping):
        return block
    if block is None:
        raise PaddlePdfNormalizationError(f"page {page_number} parsing block must not be null")

    text = str(block)
    parsed: dict[str, Any] = {"order": order}
    content_lines: list[str] = []
    current_key: str | None = None
    recognized_structured_key = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line and set(line) == {"#"}:
            continue
        match = re.match(r"^([A-Za-z_][\w -]*):\s*(.*)$", raw_line)
        if match:
            key = match.group(1).strip().lower().replace(" ", "_")
            value = match.group(2)
            current_key = key
            if key in {"label", "type", "block_label", "category"}:
                recognized_structured_key = True
                parsed["type"] = value.strip() or None
            elif key in {"bbox", "box", "coordinate"}:
                recognized_structured_key = True
                parsed["bbox"] = _parse_bbox_text(value, page_number)
            elif key in {"content", "text", "markdown"}:
                recognized_structured_key = True
                content_lines.append(value)
            elif key in {"confidence", "score"}:
                recognized_structured_key = True
                try:
                    parsed["confidence"] = float(value.strip())
                except ValueError as exc:
                    raise PaddlePdfNormalizationError(
                        f"page {page_number} parsing block confidence must be numeric"
                    ) from exc
            continue
        if current_key in {"content", "text", "markdown"}:
            content_lines.append(raw_line)
        elif line and not recognized_structured_key:
            content_lines.append(raw_line)

    content = "\n".join(content_lines).strip("\n")
    if content:
        parsed["text"] = content
    elif not recognized_structured_key and text.strip():
        cleaned = "\n".join(
            line for line in text.splitlines() if not (line.strip() and set(line.strip()) == {"#"})
        ).strip()
        if cleaned:
            parsed["text"] = cleaned
    return parsed


def _parse_bbox_text(value: str, page_number: int) -> list[float]:
    text = value.strip().strip("[]()")
    parts = [part for part in re.split(r"[,\s]+", text) if part]
    if len(parts) != 4:
        raise PaddlePdfNormalizationError(f"page {page_number} parsing block bbox must contain four coordinates")
    coords: list[float] = []
    for part in parts:
        try:
            number = float(part)
        except ValueError as exc:
            raise PaddlePdfNormalizationError(
                f"page {page_number} parsing block bbox coordinates must be finite numbers"
            ) from exc
        if not isfinite(number):
            raise PaddlePdfNormalizationError(
                f"page {page_number} parsing block bbox coordinates must be finite numbers"
            )
        coords.append(number)
    return coords


def _block_order(block: Mapping[str, Any], fallback: int) -> int:
    value = block.get("order")
    if value is None:
        return fallback
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PaddlePdfNormalizationError("block order must be a nonnegative integer when supplied")
    return value


def _observed_kind(block: Mapping[str, Any]) -> str:
    metadata = block.get("metadata")
    label = metadata.get("label") if isinstance(metadata, Mapping) else None
    value = label or block.get("type") or block.get("block_label") or "unknown"
    text = str(value).strip().lower()
    return text or "unknown"


def _block_text(block: Mapping[str, Any]) -> str | None:
    value = block.get("text")
    if value is None:
        value = block.get("block_content")
    if value is None:
        return None
    if not isinstance(value, str):
        raise PaddlePdfNormalizationError("block text must be a string when supplied")
    return value


def _confidence(block: Mapping[str, Any]) -> float | None:
    value = block.get("confidence")
    if value is None:
        value = block.get("score")
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value) or not 0 <= value <= 1:
        raise PaddlePdfNormalizationError("block confidence must be between 0 and 1")
    return float(value)


def _spatial_anchor(
    block: Mapping[str, Any],
    source_unit_id: str,
    width: float,
    height: float,
    page_number: int,
) -> SpatialAnchor:
    bbox = block.get("bbox")
    if bbox is None:
        bbox = block.get("block_bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise PaddlePdfNormalizationError(f"page {page_number} block bbox must contain four coordinates")
    coords = []
    for value in bbox:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
            raise PaddlePdfNormalizationError(f"page {page_number} block bbox coordinates must be finite numbers")
        coords.append(float(value))
    left, top, right, bottom = coords
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise PaddlePdfNormalizationError(f"page {page_number} block bbox lies outside page dimensions")
    return SpatialAnchor(
        source_unit_id,
        left / width,
        top / height,
        right / width,
        bottom / height,
    )


def _validate_page_identity(page: Mapping[str, Any], page_number: int) -> None:
    page_index = page.get("page_index")
    if page_index is not None and page_index != page_number - 1:
        raise PaddlePdfNormalizationError(f"page {page_number} has inconsistent page_index")

    source_range = page.get("source_page_range")
    if source_range is None:
        return
    if isinstance(source_range, Mapping):
        start = source_range.get("page_start")
        end = source_range.get("page_end")
    elif isinstance(source_range, (list, tuple)) and len(source_range) == 2:
        start, end = source_range
    else:
        raise PaddlePdfNormalizationError(f"page {page_number} has malformed source_page_range")
    start = _positive_int(start, "source page range start")
    end = _positive_int(end, "source page range end")
    if start > end or not start <= page_number <= end:
        raise PaddlePdfNormalizationError(f"page {page_number} is outside source_page_range")
    local_page_index = page.get("local_page_index")
    if local_page_index is not None:
        if not isinstance(local_page_index, int) or isinstance(local_page_index, bool) or local_page_index < 0:
            raise PaddlePdfNormalizationError("local_page_index must be a nonnegative integer")
        if local_page_index != page_number - start:
            raise PaddlePdfNormalizationError(f"page {page_number} has inconsistent local_page_index")


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PaddlePdfNormalizationError(f"{name} must be a positive integer")
    return value


def _positive_number(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value) or value <= 0:
        raise PaddlePdfNormalizationError(f"{name} must be a finite positive number")
    return float(value)


def _require_nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PaddlePdfNormalizationError(f"{name} must be a non-empty string")
