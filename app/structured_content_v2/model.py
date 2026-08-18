from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Any

from app.source_units import SourceAnchor, SourceUnit, anchor_to_dict, source_unit_to_dict


SC_V2_SCHEMA_ID = "atlas.structured-content-candidate"
SC_V2_SCHEMA_VERSION = 2


class ContentNodeTypeV2(str, Enum):
    SECTION = "section"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    LIST_ITEM = "list_item"
    TABLE = "table"
    FIGURE = "figure"
    CAPTION = "caption"
    FORMULA = "formula"
    HEADER = "header"
    FOOTER = "footer"
    FOOTNOTE = "footnote"
    QUOTE = "quote"
    CODE = "code"
    REFERENCE = "reference"
    UNKNOWN = "unknown"


class ContentRecoveryStateV2(str, Enum):
    COMPLETE = "complete"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class NodeRecoveryStateV2(str, Enum):
    COMPLETE = "complete"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    RECOVERED = "recovered"


class AssetRecoveryStateV2(str, Enum):
    AVAILABLE = "available"
    MISSING = "missing"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    REBUILDABLE = "rebuildable"


class WarningSeverityV2(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class AssetRoleV2(str, Enum):
    FIGURE = "figure"
    TABLE_RENDERING = "table_rendering"
    SOURCE_RENDERING = "source_rendering"
    FORMULA_RENDERING = "formula_rendering"


class AssetRenditionRoleV2(str, Enum):
    ORIGINAL = "original"
    NORMALIZED = "normalized"
    THUMBNAIL = "thumbnail"
    OCR_SOURCE = "ocr_source"


def _nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _nonnegative_int(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def _json(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("metadata requires finite JSON numbers")
        return value
    if isinstance(value, tuple):
        return tuple(_json(item) for item in value)
    if isinstance(value, list):
        return tuple(_json(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    raise ValueError("metadata must be JSON-compatible")


@dataclass(frozen=True, slots=True)
class StructuredSourceUnit:
    source_unit: SourceUnit
    evidence_ids: tuple[str, ...] = ()
    warning_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContentNodeV2:
    node_id: str
    lineage_key: str
    node_type: ContentNodeTypeV2
    source_unit_ids: tuple[str, ...]
    sibling_order: int
    recovery_state: NodeRecoveryStateV2 = NodeRecoveryStateV2.COMPLETE
    parent_id: str | None = None
    text: str | None = None
    heading_level: int | None = None
    source_anchors: tuple[SourceAnchor, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    asset_ids: tuple[str, ...] = ()
    warning_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        _nonempty(self.node_id, "node_id")
        _nonempty(self.lineage_key, "lineage_key")
        if not isinstance(self.node_type, ContentNodeTypeV2):
            raise ValueError("node_type must be a ContentNodeTypeV2")
        if not self.source_unit_ids:
            raise ValueError("source_unit_ids must not be empty")
        if any(not isinstance(item, str) or not item.strip() for item in self.source_unit_ids):
            raise ValueError("source_unit_ids must contain non-empty strings")
        if len(set(self.source_unit_ids)) != len(self.source_unit_ids):
            raise ValueError("source_unit_ids must not contain duplicates")
        _nonnegative_int(self.sibling_order, "sibling_order")
        if self.parent_id is not None:
            _nonempty(self.parent_id, "parent_id")
        if self.heading_level is not None:
            if self.node_type is not ContentNodeTypeV2.HEADING:
                raise ValueError("heading_level is only valid for heading nodes")
            if not isinstance(self.heading_level, int) or isinstance(self.heading_level, bool) or self.heading_level < 1:
                raise ValueError("heading_level must be a positive integer")
        if self.node_type is ContentNodeTypeV2.HEADING and self.heading_level is None:
            raise ValueError("heading nodes require heading_level")
        if self.recovery_state is NodeRecoveryStateV2.UNAVAILABLE and self.text not in (None, ""):
            raise ValueError("unavailable nodes must not carry text")
        if self.metadata is not None:
            object.__setattr__(self, "metadata", _json(self.metadata))


@dataclass(frozen=True, slots=True)
class EvidenceReferenceV2:
    evidence_id: str
    source_unit_id: str | None = None
    source_anchors: tuple[SourceAnchor, ...] = ()
    processing_run_ref: str | None = None
    raw_result_ref: str | None = None
    structured_processing_result_ref: str | None = None
    spr_node_ref: str | None = None
    spr_observation_ref: str | None = None
    warning_ref: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        _nonempty(self.evidence_id, "evidence_id")
        for value, name in (
            (self.source_unit_id, "source_unit_id"),
            (self.processing_run_ref, "processing_run_ref"),
            (self.raw_result_ref, "raw_result_ref"),
            (self.structured_processing_result_ref, "structured_processing_result_ref"),
            (self.spr_node_ref, "spr_node_ref"),
            (self.spr_observation_ref, "spr_observation_ref"),
            (self.warning_ref, "warning_ref"),
        ):
            if value is not None:
                _nonempty(value, name)
        if self.metadata is not None:
            object.__setattr__(self, "metadata", _json(self.metadata))


@dataclass(frozen=True, slots=True)
class ContentWarningV2:
    warning_id: str
    code: str
    severity: WarningSeverityV2
    scope_ref: str
    safe_summary: str
    evidence_ids: tuple[str, ...] = ()
    recoverable: bool = True
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        _nonempty(self.warning_id, "warning_id")
        _nonempty(self.code, "code")
        _nonempty(self.scope_ref, "scope_ref")
        _nonempty(self.safe_summary, "safe_summary")
        if self.details is not None:
            object.__setattr__(self, "details", _json(self.details))


@dataclass(frozen=True, slots=True)
class AssetRenditionReferenceV2:
    rendition_id: str
    asset_id: str
    role: AssetRenditionRoleV2
    artifact_ref: str
    media_type: str | None = None
    checksum: str | None = None
    recovery_state: AssetRecoveryStateV2 = AssetRecoveryStateV2.AVAILABLE
    rebuildable: bool = False

    def __post_init__(self) -> None:
        _nonempty(self.rendition_id, "rendition_id")
        _nonempty(self.asset_id, "asset_id")
        _nonempty(self.artifact_ref, "artifact_ref")
        if self.media_type is not None:
            _nonempty(self.media_type, "media_type")
        if self.checksum is not None:
            _nonempty(self.checksum, "checksum")


@dataclass(frozen=True, slots=True)
class AssetReferenceV2:
    asset_id: str
    role: AssetRoleV2
    recovery_state: AssetRecoveryStateV2
    source_unit_ids: tuple[str, ...]
    source_anchors: tuple[SourceAnchor, ...] = ()
    rendition_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    caption: str | None = None
    alt_text: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        _nonempty(self.asset_id, "asset_id")
        if not self.source_unit_ids:
            raise ValueError("asset source_unit_ids must not be empty")
        if len(set(self.source_unit_ids)) != len(self.source_unit_ids):
            raise ValueError("asset source_unit_ids must not contain duplicates")
        if self.metadata is not None:
            object.__setattr__(self, "metadata", _json(self.metadata))


@dataclass(frozen=True, slots=True)
class ContentRecoverySummaryV2:
    state: ContentRecoveryStateV2
    total_source_units: int
    complete_source_units: int = 0
    degraded_source_units: int = 0
    no_usable_semantic_content_source_units: int = 0
    unavailable_source_units: int = 0
    warning_ids: tuple[str, ...] = ()
    recovery_policy_ref: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "total_source_units",
            "complete_source_units",
            "degraded_source_units",
            "no_usable_semantic_content_source_units",
            "unavailable_source_units",
        ):
            _nonnegative_int(getattr(self, name), name)
        if self.recovery_policy_ref is not None:
            _nonempty(self.recovery_policy_ref, "recovery_policy_ref")


@dataclass(frozen=True, slots=True)
class StructuredContentCandidateV2:
    document_ref: str
    candidate_id: str
    lineage_key: str
    recovery_summary: ContentRecoverySummaryV2
    source_units: tuple[StructuredSourceUnit, ...]
    nodes: tuple[ContentNodeV2, ...]
    evidence: tuple[EvidenceReferenceV2, ...] = ()
    assets: tuple[AssetReferenceV2, ...] = ()
    warnings: tuple[ContentWarningV2, ...] = ()
    renditions: tuple[AssetRenditionReferenceV2, ...] = ()
    transformer_ref: str | None = None
    transformation_policy_ref: str | None = None
    processing_run_ref: str | None = None
    raw_result_ref: str | None = None
    structured_processing_result_ref: str | None = None
    schema_id: str = SC_V2_SCHEMA_ID
    schema_version: int = SC_V2_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _nonempty(self.document_ref, "document_ref")
        _nonempty(self.candidate_id, "candidate_id")
        _nonempty(self.lineage_key, "lineage_key")
        for value, name in (
            (self.transformer_ref, "transformer_ref"),
            (self.transformation_policy_ref, "transformation_policy_ref"),
            (self.processing_run_ref, "processing_run_ref"),
            (self.raw_result_ref, "raw_result_ref"),
            (self.structured_processing_result_ref, "structured_processing_result_ref"),
        ):
            if value is not None:
                _nonempty(value, name)
        if self.schema_id != SC_V2_SCHEMA_ID:
            raise ValueError(f"schema_id must be {SC_V2_SCHEMA_ID}")
        if self.schema_version != SC_V2_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SC_V2_SCHEMA_VERSION}")


def _anchor_sort_key(anchor: SourceAnchor) -> tuple[object, ...]:
    payload = anchor_to_dict(anchor)
    return (payload["source_unit_id"], payload["kind"], repr(payload))


def normalize_candidate_v2(candidate: StructuredContentCandidateV2) -> dict[str, object]:
    source_order = {item.source_unit.source_unit_id: item.source_unit.source_order for item in candidate.source_units}
    source_units = sorted(candidate.source_units, key=lambda item: (item.source_unit.source_order, item.source_unit.source_unit_id))
    nodes = sorted(candidate.nodes, key=lambda item: (item.parent_id or "", item.sibling_order, item.node_id))
    evidence = sorted(candidate.evidence, key=lambda item: item.evidence_id)
    assets = sorted(candidate.assets, key=lambda item: item.asset_id)
    warnings = sorted(candidate.warnings, key=lambda item: item.warning_id)
    renditions = sorted(candidate.renditions, key=lambda item: item.rendition_id)

    return {
        "schema_id": candidate.schema_id,
        "schema_version": candidate.schema_version,
        "document_ref": candidate.document_ref,
        "candidate_id": candidate.candidate_id,
        "lineage_key": candidate.lineage_key,
        "transformer_ref": candidate.transformer_ref,
        "transformation_policy_ref": candidate.transformation_policy_ref,
        "processing_run_ref": candidate.processing_run_ref,
        "raw_result_ref": candidate.raw_result_ref,
        "structured_processing_result_ref": candidate.structured_processing_result_ref,
        "recovery_summary": {
            "state": candidate.recovery_summary.state.value,
            "total_source_units": candidate.recovery_summary.total_source_units,
            "complete_source_units": candidate.recovery_summary.complete_source_units,
            "degraded_source_units": candidate.recovery_summary.degraded_source_units,
            "no_usable_semantic_content_source_units": candidate.recovery_summary.no_usable_semantic_content_source_units,
            "unavailable_source_units": candidate.recovery_summary.unavailable_source_units,
            "warning_ids": sorted(candidate.recovery_summary.warning_ids),
            "recovery_policy_ref": candidate.recovery_summary.recovery_policy_ref,
        },
        "source_units": [
            {
                **source_unit_to_dict(item.source_unit),
                "evidence_ids": sorted(item.evidence_ids),
                "warning_ids": sorted(item.warning_ids),
            }
            for item in source_units
        ],
        "nodes": [
            {
                "node_id": item.node_id,
                "lineage_key": item.lineage_key,
                "node_type": item.node_type.value,
                "source_unit_ids": sorted(item.source_unit_ids, key=lambda unit_id: (source_order.get(unit_id, 2**31), unit_id)),
                "sibling_order": item.sibling_order,
                "recovery_state": item.recovery_state.value,
                "parent_id": item.parent_id,
                "text": item.text,
                "heading_level": item.heading_level,
                "source_anchors": [anchor_to_dict(anchor) for anchor in sorted(item.source_anchors, key=_anchor_sort_key)],
                "evidence_ids": sorted(item.evidence_ids),
                "asset_ids": sorted(item.asset_ids),
                "warning_ids": sorted(item.warning_ids),
                "metadata": item.metadata,
            }
            for item in nodes
        ],
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "source_unit_id": item.source_unit_id,
                "source_anchors": [anchor_to_dict(anchor) for anchor in sorted(item.source_anchors, key=_anchor_sort_key)],
                "processing_run_ref": item.processing_run_ref,
                "raw_result_ref": item.raw_result_ref,
                "structured_processing_result_ref": item.structured_processing_result_ref,
                "spr_node_ref": item.spr_node_ref,
                "spr_observation_ref": item.spr_observation_ref,
                "warning_ref": item.warning_ref,
                "metadata": item.metadata,
            }
            for item in evidence
        ],
        "assets": [
            {
                "asset_id": item.asset_id,
                "role": item.role.value,
                "recovery_state": item.recovery_state.value,
                "source_unit_ids": sorted(item.source_unit_ids, key=lambda unit_id: (source_order.get(unit_id, 2**31), unit_id)),
                "source_anchors": [anchor_to_dict(anchor) for anchor in sorted(item.source_anchors, key=_anchor_sort_key)],
                "rendition_ids": sorted(item.rendition_ids),
                "evidence_ids": sorted(item.evidence_ids),
                "caption": item.caption,
                "alt_text": item.alt_text,
                "metadata": item.metadata,
            }
            for item in assets
        ],
        "warnings": [
            {
                "warning_id": item.warning_id,
                "code": item.code,
                "severity": item.severity.value,
                "scope_ref": item.scope_ref,
                "safe_summary": item.safe_summary,
                "evidence_ids": sorted(item.evidence_ids),
                "recoverable": item.recoverable,
                "details": item.details,
            }
            for item in warnings
        ],
        "renditions": [
            {
                "rendition_id": item.rendition_id,
                "asset_id": item.asset_id,
                "role": item.role.value,
                "artifact_ref": item.artifact_ref,
                "media_type": item.media_type,
                "checksum": item.checksum,
                "recovery_state": item.recovery_state.value,
                "rebuildable": item.rebuildable,
            }
            for item in renditions
        ],
    }
