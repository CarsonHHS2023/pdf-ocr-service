from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Any

from app.source_units import SourceAnchor, SourceUnit, anchor_to_dict, source_unit_to_dict


SPR_V2_SCHEMA_ID = "atlas.structured-processing-result"
SPR_V2_SCHEMA_VERSION = 2


class ProcessingNodeKind(str, Enum):
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    LIST_ITEM = "list_item"
    CAPTION = "caption"
    FORMULA = "formula"
    HEADER = "header"
    FOOTER = "footer"
    FOOTNOTE = "footnote"
    TABLE = "table"
    FIGURE = "figure"
    QUOTE = "quote"
    CODE = "code"
    REFERENCE = "reference"
    UNKNOWN = "unknown"


class ProcessingNodeRecoveryState(str, Enum):
    COMPLETE = "complete"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


def _require_nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_nonnegative_int(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("metadata requires finite JSON numbers")
        return value
    if isinstance(value, tuple):
        return tuple(_json_value(item) for item in value)
    if isinstance(value, list):
        return tuple(_json_value(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    raise ValueError("metadata must be JSON-compatible")


@dataclass(frozen=True, slots=True)
class ProcessingObservation:
    observation_id: str
    source_unit_id: str
    order: int
    observed_kind: str
    text: str | None = None
    anchors: tuple[SourceAnchor, ...] = ()
    confidence: float | None = None
    evidence_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.observation_id, "observation_id")
        _require_nonempty(self.source_unit_id, "source_unit_id")
        _require_nonnegative_int(self.order, "order")
        _require_nonempty(self.observed_kind, "observed_kind")
        if self.confidence is not None:
            if (
                not isinstance(self.confidence, (int, float))
                or isinstance(self.confidence, bool)
                or not isfinite(self.confidence)
                or not 0 <= self.confidence <= 1
            ):
                raise ValueError("confidence must be between 0 and 1")
        if self.metadata is not None:
            object.__setattr__(self, "metadata", _json_value(self.metadata))


@dataclass(frozen=True, slots=True)
class ProcessingNode:
    node_id: str
    kind: ProcessingNodeKind
    order: int
    source_unit_ids: tuple[str, ...]
    parent_id: str | None = None
    text: str | None = None
    heading_level: int | None = None
    anchors: tuple[SourceAnchor, ...] = ()
    observation_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    recovery_state: ProcessingNodeRecoveryState = ProcessingNodeRecoveryState.COMPLETE
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.node_id, "node_id")
        if not isinstance(self.kind, ProcessingNodeKind):
            raise ValueError("kind must be a ProcessingNodeKind")
        _require_nonnegative_int(self.order, "order")
        if not self.source_unit_ids:
            raise ValueError("source_unit_ids must not be empty")
        if any(not isinstance(item, str) or not item.strip() for item in self.source_unit_ids):
            raise ValueError("source_unit_ids must contain non-empty strings")
        if len(set(self.source_unit_ids)) != len(self.source_unit_ids):
            raise ValueError("source_unit_ids must not contain duplicates")
        if self.parent_id is not None:
            _require_nonempty(self.parent_id, "parent_id")
        if self.heading_level is not None:
            if self.kind not in {ProcessingNodeKind.TITLE, ProcessingNodeKind.HEADING}:
                raise ValueError("heading_level is only valid for title/heading nodes")
            if not isinstance(self.heading_level, int) or isinstance(self.heading_level, bool) or self.heading_level < 1:
                raise ValueError("heading_level must be a positive integer")
        if self.kind is ProcessingNodeKind.HEADING and self.heading_level is None:
            raise ValueError("heading nodes require heading_level")
        if not isinstance(self.recovery_state, ProcessingNodeRecoveryState):
            raise ValueError("recovery_state must be a ProcessingNodeRecoveryState")
        if self.recovery_state is ProcessingNodeRecoveryState.UNAVAILABLE and self.text not in (None, ""):
            raise ValueError("unavailable nodes must not carry recovered text")
        if self.metadata is not None:
            object.__setattr__(self, "metadata", _json_value(self.metadata))


@dataclass(frozen=True, slots=True)
class ProcessingEvidence:
    evidence_id: str
    source_unit_id: str | None = None
    anchors: tuple[SourceAnchor, ...] = ()
    observation_id: str | None = None
    processing_run_ref: str | None = None
    raw_result_ref: str | None = None
    provider_ref: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.evidence_id, "evidence_id")
        for value, name in (
            (self.source_unit_id, "source_unit_id"),
            (self.observation_id, "observation_id"),
            (self.processing_run_ref, "processing_run_ref"),
            (self.raw_result_ref, "raw_result_ref"),
            (self.provider_ref, "provider_ref"),
        ):
            if value is not None:
                _require_nonempty(value, name)
        if self.metadata is not None:
            object.__setattr__(self, "metadata", _json_value(self.metadata))


@dataclass(frozen=True, slots=True)
class StructuredProcessingResultV2:
    document_ref: str
    processing_run_ref: str
    source_units: tuple[SourceUnit, ...]
    observations: tuple[ProcessingObservation, ...]
    nodes: tuple[ProcessingNode, ...]
    evidence: tuple[ProcessingEvidence, ...] = ()
    raw_result_ref: str | None = None
    schema_id: str = SPR_V2_SCHEMA_ID
    schema_version: int = SPR_V2_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.document_ref, "document_ref")
        _require_nonempty(self.processing_run_ref, "processing_run_ref")
        if self.raw_result_ref is not None:
            _require_nonempty(self.raw_result_ref, "raw_result_ref")
        if self.schema_id != SPR_V2_SCHEMA_ID:
            raise ValueError(f"schema_id must be {SPR_V2_SCHEMA_ID}")
        if self.schema_version != SPR_V2_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SPR_V2_SCHEMA_VERSION}")


def _anchor_sort_key(anchor: SourceAnchor) -> tuple[object, ...]:
    payload = anchor_to_dict(anchor)
    return (
        payload["source_unit_id"],
        payload["kind"],
        repr(payload),
    )


def normalize_spr_v2(spr: StructuredProcessingResultV2) -> dict[str, object]:
    """Return a deterministic JSON-compatible projection independent of tuple input order."""

    source_order = {unit.source_unit_id: unit.source_order for unit in spr.source_units}

    units = sorted(spr.source_units, key=lambda unit: (unit.source_order, unit.source_unit_id))
    evidence = sorted(spr.evidence, key=lambda item: item.evidence_id)
    observations = sorted(
        spr.observations,
        key=lambda item: (source_order.get(item.source_unit_id, 2**31), item.order, item.observation_id),
    )
    nodes = sorted(spr.nodes, key=lambda item: (item.order, item.node_id))

    return {
        "schema_id": spr.schema_id,
        "schema_version": spr.schema_version,
        "document_ref": spr.document_ref,
        "processing_run_ref": spr.processing_run_ref,
        "raw_result_ref": spr.raw_result_ref,
        "source_units": [source_unit_to_dict(unit) for unit in units],
        "observations": [
            {
                "observation_id": item.observation_id,
                "source_unit_id": item.source_unit_id,
                "order": item.order,
                "observed_kind": item.observed_kind,
                "text": item.text,
                "anchors": [anchor_to_dict(anchor) for anchor in sorted(item.anchors, key=_anchor_sort_key)],
                "confidence": item.confidence,
                "evidence_ids": sorted(item.evidence_ids),
                "metadata": item.metadata,
            }
            for item in observations
        ],
        "nodes": [
            {
                "node_id": item.node_id,
                "kind": item.kind.value,
                "order": item.order,
                "source_unit_ids": sorted(item.source_unit_ids, key=lambda unit_id: (source_order.get(unit_id, 2**31), unit_id)),
                "parent_id": item.parent_id,
                "text": item.text,
                "heading_level": item.heading_level,
                "anchors": [anchor_to_dict(anchor) for anchor in sorted(item.anchors, key=_anchor_sort_key)],
                "observation_ids": sorted(item.observation_ids),
                "evidence_ids": sorted(item.evidence_ids),
                "recovery_state": item.recovery_state.value,
                "metadata": item.metadata,
            }
            for item in nodes
        ],
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "source_unit_id": item.source_unit_id,
                "anchors": [anchor_to_dict(anchor) for anchor in sorted(item.anchors, key=_anchor_sort_key)],
                "observation_id": item.observation_id,
                "processing_run_ref": item.processing_run_ref,
                "raw_result_ref": item.raw_result_ref,
                "provider_ref": item.provider_ref,
                "metadata": item.metadata,
            }
            for item in evidence
        ],
    }
