from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import TypeAlias


class SourceUnitKind(str, Enum):
    PHYSICAL_PAGE = "physical_page"
    TEXT_FLOW = "text_flow"
    HTML_SECTION = "html_section"
    EBOOK_SPINE_ITEM = "ebook_spine_item"
    DOCUMENT_PART = "document_part"
    IMAGE_CANVAS = "image_canvas"
    AUDIO_SEGMENT = "audio_segment"
    VIDEO_SEGMENT = "video_segment"


class SourceUnitRecoveryState(str, Enum):
    COMPLETE = "complete"
    DEGRADED = "degraded"
    NO_USABLE_SEMANTIC_CONTENT = "no_usable_semantic_content"
    UNAVAILABLE = "unavailable"


def _require_nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_nonnegative_int(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def _require_finite_positive(value: float, name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")


def _require_finite_nonnegative(value: float, name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")


@dataclass(frozen=True, slots=True)
class SourceUnitDimensions:
    width: float
    height: float
    unit: str = "pixel"

    def __post_init__(self) -> None:
        _require_finite_positive(self.width, "width")
        _require_finite_positive(self.height, "height")
        _require_nonempty(self.unit, "unit")


@dataclass(frozen=True, slots=True)
class SpatialAnchor:
    source_unit_id: str
    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        _require_nonempty(self.source_unit_id, "source_unit_id")
        values = (self.left, self.top, self.right, self.bottom)
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and isfinite(v) for v in values):
            raise ValueError("spatial anchor coordinates must be finite numbers")
        if not (0 <= self.left < self.right <= 1 and 0 <= self.top < self.bottom <= 1):
            raise ValueError("spatial anchor must be a valid normalized bounding box")


@dataclass(frozen=True, slots=True)
class TextSpanAnchor:
    source_unit_id: str
    start: int
    end: int

    def __post_init__(self) -> None:
        _require_nonempty(self.source_unit_id, "source_unit_id")
        _require_nonnegative_int(self.start, "start")
        _require_nonnegative_int(self.end, "end")
        if self.start > self.end:
            raise ValueError("text span start must not exceed end")


@dataclass(frozen=True, slots=True)
class TemporalAnchor:
    source_unit_id: str
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        _require_nonempty(self.source_unit_id, "source_unit_id")
        _require_nonnegative_int(self.start_ms, "start_ms")
        _require_nonnegative_int(self.end_ms, "end_ms")
        if self.start_ms > self.end_ms:
            raise ValueError("temporal start_ms must not exceed end_ms")


@dataclass(frozen=True, slots=True)
class DomAnchor:
    source_unit_id: str
    path: str
    text_start: int | None = None
    text_end: int | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.source_unit_id, "source_unit_id")
        _require_nonempty(self.path, "path")
        if (self.text_start is None) != (self.text_end is None):
            raise ValueError("DOM text range requires both text_start and text_end")
        if self.text_start is not None and self.text_end is not None:
            _require_nonnegative_int(self.text_start, "text_start")
            _require_nonnegative_int(self.text_end, "text_end")
            if self.text_start > self.text_end:
                raise ValueError("DOM text_start must not exceed text_end")


SourceAnchor: TypeAlias = SpatialAnchor | TextSpanAnchor | TemporalAnchor | DomAnchor


@dataclass(frozen=True, slots=True)
class SourceUnit:
    source_unit_id: str
    kind: SourceUnitKind
    source_order: int
    source_ref: str
    recovery_state: SourceUnitRecoveryState = SourceUnitRecoveryState.COMPLETE
    dimensions: SourceUnitDimensions | None = None
    rotation_degrees: float | None = None
    source_span: TextSpanAnchor | None = None
    duration_ms: int | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.source_unit_id, "source_unit_id")
        if not isinstance(self.kind, SourceUnitKind):
            raise ValueError("kind must be a SourceUnitKind")
        _require_nonnegative_int(self.source_order, "source_order")
        _require_nonempty(self.source_ref, "source_ref")
        if not isinstance(self.recovery_state, SourceUnitRecoveryState):
            raise ValueError("recovery_state must be a SourceUnitRecoveryState")
        if self.rotation_degrees is not None:
            _require_finite_nonnegative(self.rotation_degrees, "rotation_degrees")
            if self.rotation_degrees >= 360:
                raise ValueError("rotation_degrees must be less than 360")
        if self.source_span is not None and self.source_span.source_unit_id != self.source_unit_id:
            raise ValueError("source_span must reference its owning source unit")
        if self.duration_ms is not None:
            _require_nonnegative_int(self.duration_ms, "duration_ms")
        self._validate_kind_specific_fields()

    def _validate_kind_specific_fields(self) -> None:
        spatial_kinds = {SourceUnitKind.PHYSICAL_PAGE, SourceUnitKind.IMAGE_CANVAS}
        temporal_kinds = {SourceUnitKind.AUDIO_SEGMENT, SourceUnitKind.VIDEO_SEGMENT}

        if self.kind in spatial_kinds and self.dimensions is None:
            raise ValueError(f"{self.kind.value} requires dimensions")
        if self.kind not in spatial_kinds and self.rotation_degrees is not None:
            raise ValueError("rotation_degrees is only valid for spatial source units")
        if self.kind in temporal_kinds and self.duration_ms is None:
            raise ValueError(f"{self.kind.value} requires duration_ms")
        if self.kind not in temporal_kinds and self.duration_ms is not None:
            raise ValueError("duration_ms is only valid for temporal source units")
        if self.kind is SourceUnitKind.TEXT_FLOW and self.source_span is None:
            raise ValueError("text_flow requires a source_span")


def anchor_to_dict(anchor: SourceAnchor) -> dict[str, object]:
    if isinstance(anchor, SpatialAnchor):
        return {
            "kind": "spatial",
            "source_unit_id": anchor.source_unit_id,
            "normalized_bbox": [anchor.left, anchor.top, anchor.right, anchor.bottom],
        }
    if isinstance(anchor, TextSpanAnchor):
        return {
            "kind": "text_span",
            "source_unit_id": anchor.source_unit_id,
            "start": anchor.start,
            "end": anchor.end,
        }
    if isinstance(anchor, TemporalAnchor):
        return {
            "kind": "temporal",
            "source_unit_id": anchor.source_unit_id,
            "start_ms": anchor.start_ms,
            "end_ms": anchor.end_ms,
        }
    if isinstance(anchor, DomAnchor):
        payload: dict[str, object] = {
            "kind": "dom",
            "source_unit_id": anchor.source_unit_id,
            "path": anchor.path,
        }
        if anchor.text_start is not None and anchor.text_end is not None:
            payload["text_start"] = anchor.text_start
            payload["text_end"] = anchor.text_end
        return payload
    raise TypeError(f"unsupported source anchor: {type(anchor)!r}")


def source_unit_to_dict(unit: SourceUnit) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_unit_id": unit.source_unit_id,
        "kind": unit.kind.value,
        "source_order": unit.source_order,
        "source_ref": unit.source_ref,
        "recovery_state": unit.recovery_state.value,
    }
    if unit.dimensions is not None:
        payload["dimensions"] = {
            "width": unit.dimensions.width,
            "height": unit.dimensions.height,
            "unit": unit.dimensions.unit,
        }
    if unit.rotation_degrees is not None:
        payload["rotation_degrees"] = unit.rotation_degrees
    if unit.source_span is not None:
        payload["source_span"] = anchor_to_dict(unit.source_span)
    if unit.duration_ms is not None:
        payload["duration_ms"] = unit.duration_ms
    return payload
