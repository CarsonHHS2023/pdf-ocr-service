"""Deterministic retained-TXT decoding and source observation normalization.

This module is intentionally pre-semantic. It preserves exact decoded text and
stable source-line/span identity for a later structure-recovery model without
letting that model own or rewrite source text.
"""
from __future__ import annotations

from dataclasses import dataclass
import codecs

from app.processing.normalized_observations import NormalizedObservationBundle
from app.processing.structured_result_v2.model import ProcessingEvidence, ProcessingObservation
from app.source_units import SourceUnit, SourceUnitKind, TextSpanAnchor


DEFAULT_MAX_LINES_PER_SOURCE_UNIT = 200
DEFAULT_MAX_CHARS_PER_SOURCE_UNIT = 12_000


class TxtNormalizationError(ValueError):
    """Raised when retained TXT bytes cannot be normalized safely."""


@dataclass(frozen=True, slots=True)
class DecodedTxt:
    text: str
    encoding: str


@dataclass(frozen=True, slots=True)
class TxtSourceLine:
    line_id: str
    line_number: int
    body_start: int
    body_end: int
    separator_start: int
    separator_end: int
    text: str
    separator: str

    @property
    def is_empty(self) -> bool:
        return self.text == ""


@dataclass(frozen=True, slots=True)
class NormalizedTxtSource:
    decoded: DecodedTxt
    lines: tuple[TxtSourceLine, ...]
    bundle: NormalizedObservationBundle


def decode_txt_bytes(raw_data: bytes) -> DecodedTxt:
    if not isinstance(raw_data, bytes):
        raise TypeError("raw_data must be bytes")

    bom_encodings: tuple[tuple[bytes, str], ...] = (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    )
    candidates: list[str] = []
    for bom, encoding in bom_encodings:
        if raw_data.startswith(bom):
            candidates.append(encoding)
            break
    for encoding in ("utf-8", "gb18030", "gbk"):
        if encoding not in candidates:
            candidates.append(encoding)

    for encoding in candidates:
        try:
            text = raw_data.decode(encoding, errors="strict")
        except UnicodeDecodeError:
            continue
        if "\x00" in text:
            raise TxtNormalizationError("decoded TXT must not contain NUL")
        return DecodedTxt(text=text, encoding=encoding)

    raise TxtNormalizationError("TXT source could not be decoded with supported encodings")


def index_txt_lines(text: str) -> tuple[TxtSourceLine, ...]:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if "\x00" in text:
        raise TxtNormalizationError("decoded TXT must not contain NUL")

    lines: list[TxtSourceLine] = []
    line_start = 0
    line_number = 1
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        if char not in {"\r", "\n"}:
            index += 1
            continue
        separator_start = index
        if char == "\r" and index + 1 < length and text[index + 1] == "\n":
            index += 2
        else:
            index += 1
        lines.append(
            TxtSourceLine(
                line_id=f"L{line_number:06d}",
                line_number=line_number,
                body_start=line_start,
                body_end=separator_start,
                separator_start=separator_start,
                separator_end=index,
                text=text[line_start:separator_start],
                separator=text[separator_start:index],
            )
        )
        line_number += 1
        line_start = index

    # Every source has at least one stable line identity. A terminal newline also
    # creates the trailing empty source line so later line IDs remain literal.
    lines.append(
        TxtSourceLine(
            line_id=f"L{line_number:06d}",
            line_number=line_number,
            body_start=line_start,
            body_end=length,
            separator_start=length,
            separator_end=length,
            text=text[line_start:length],
            separator="",
        )
    )
    return tuple(lines)


def normalize_txt_bytes(
    raw_data: bytes,
    *,
    document_ref: str,
    source_ref: str,
    processing_run_ref: str,
    raw_result_ref: str | None = None,
    max_lines_per_source_unit: int = DEFAULT_MAX_LINES_PER_SOURCE_UNIT,
    max_chars_per_source_unit: int = DEFAULT_MAX_CHARS_PER_SOURCE_UNIT,
) -> NormalizedTxtSource:
    for value, name in (
        (document_ref, "document_ref"),
        (source_ref, "source_ref"),
        (processing_run_ref, "processing_run_ref"),
    ):
        if not isinstance(value, str) or not value.strip():
            raise TxtNormalizationError(f"{name} must be a non-empty string")
    if raw_result_ref is not None and (not isinstance(raw_result_ref, str) or not raw_result_ref.strip()):
        raise TxtNormalizationError("raw_result_ref must be a non-empty string when supplied")
    for value, name in (
        (max_lines_per_source_unit, "max_lines_per_source_unit"),
        (max_chars_per_source_unit, "max_chars_per_source_unit"),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise TxtNormalizationError(f"{name} must be a positive integer")

    decoded = decode_txt_bytes(raw_data)
    lines = index_txt_lines(decoded.text)
    groups = _partition_lines(
        lines,
        max_lines=max_lines_per_source_unit,
        max_chars=max_chars_per_source_unit,
    )

    source_units: list[SourceUnit] = []
    observations: list[ProcessingObservation] = []
    evidence: list[ProcessingEvidence] = []

    for source_order, group in enumerate(groups):
        source_unit_id = f"txt-flow:{source_order + 1:06d}"
        unit_start = group[0].body_start
        unit_end = group[-1].separator_end
        source_units.append(
            SourceUnit(
                source_unit_id=source_unit_id,
                kind=SourceUnitKind.TEXT_FLOW,
                source_order=source_order,
                source_ref=source_ref,
                source_span=TextSpanAnchor(source_unit_id, unit_start, unit_end),
            )
        )
        observation_order = 0
        for line in group:
            if line.is_empty:
                continue
            anchor = TextSpanAnchor(source_unit_id, line.body_start, line.body_end)
            observation_id = f"txt-observation:{line.line_id}"
            evidence_id = f"txt-evidence:{line.line_id}"
            metadata = {
                "line_id": line.line_id,
                "line_number": line.line_number,
                "encoding": decoded.encoding,
                "separator_start": line.separator_start,
                "separator_end": line.separator_end,
            }
            observations.append(
                ProcessingObservation(
                    observation_id=observation_id,
                    source_unit_id=source_unit_id,
                    order=observation_order,
                    observed_kind="text_line",
                    text=line.text,
                    anchors=(anchor,),
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
                    metadata={"line_id": line.line_id, "source_format": "txt"},
                )
            )
            observation_order += 1

    bundle = NormalizedObservationBundle(
        document_ref=document_ref,
        source_ref=source_ref,
        processing_run_ref=processing_run_ref,
        raw_result_ref=raw_result_ref,
        source_units=tuple(source_units),
        observations=tuple(observations),
        evidence=tuple(evidence),
    )
    return NormalizedTxtSource(decoded=decoded, lines=lines, bundle=bundle)


def _partition_lines(
    lines: tuple[TxtSourceLine, ...],
    *,
    max_lines: int,
    max_chars: int,
) -> tuple[tuple[TxtSourceLine, ...], ...]:
    groups: list[tuple[TxtSourceLine, ...]] = []
    current: list[TxtSourceLine] = []
    current_start = 0

    for line in lines:
        if current:
            projected_chars = line.separator_end - current_start
            if len(current) >= max_lines or projected_chars > max_chars:
                groups.append(tuple(current))
                current = []
        if not current:
            current_start = line.body_start
        current.append(line)

    if current:
        groups.append(tuple(current))
    return tuple(groups)


__all__ = [
    "DEFAULT_MAX_CHARS_PER_SOURCE_UNIT",
    "DEFAULT_MAX_LINES_PER_SOURCE_UNIT",
    "DecodedTxt",
    "NormalizedTxtSource",
    "TxtNormalizationError",
    "TxtSourceLine",
    "decode_txt_bytes",
    "index_txt_lines",
    "normalize_txt_bytes",
]
