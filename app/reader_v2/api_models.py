from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.source_units import anchor_to_dict, source_unit_to_dict

from .assets import ReaderV2AssetDelivery
from .contracts import (
    ReaderContentChunkV2,
    ReaderDocumentViewV2,
    ReaderLocationV2,
    ReaderNavigationEntryV2,
    ReaderNodeViewV2,
    ReaderSourceUnitViewV2,
    ReaderV2Warning,
)


class ReaderV2WarningDTO(BaseModel):
    code: str


class ReaderV2LocationDTO(BaseModel):
    document_ref: str
    candidate_id: str
    candidate_schema_id: str
    candidate_schema_version: int
    contract_version: str
    node_id: str | None = None
    source_unit_id: str | None = None
    source_anchor: dict[str, Any] | None = None


class ReaderV2SourceUnitDTO(BaseModel):
    source_unit_id: str
    kind: str
    source_order: int
    source_ref: str
    recovery_state: str
    dimensions: dict[str, Any] | None = None
    rotation_degrees: float | None = None
    source_span: dict[str, Any] | None = None
    duration_ms: int | None = None
    content_state: str
    warnings: list[ReaderV2WarningDTO] = Field(default_factory=list)


class ReaderV2NodeDTO(BaseModel):
    location: ReaderV2LocationDTO
    node_id: str
    node_type: str
    order: int
    content_state: str
    source_unit_ids: list[str] = Field(default_factory=list)
    source_anchors: list[dict[str, Any]] = Field(default_factory=list)
    text: str | None = None
    heading_level: int | None = None
    parent_ref: str | None = None
    child_refs: list[str] = Field(default_factory=list)
    asset_refs: list[str] = Field(default_factory=list)
    warnings: list[ReaderV2WarningDTO] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class ReaderV2NavigationDTO(BaseModel):
    location: ReaderV2LocationDTO
    label: str
    order: int
    heading_level: int


class ReaderV2MetadataDTO(BaseModel):
    source_unit_count: int
    physical_page_count: int
    reflowable_source_unit_count: int


class ReaderV2IdentityDTO(BaseModel):
    contract_version: str
    document_ref: str
    candidate_id: str
    candidate_schema_id: str
    candidate_schema_version: int


class ReaderV2OpenResponse(ReaderV2IdentityDTO):
    content_state: str
    metadata: ReaderV2MetadataDTO
    source_units: list[ReaderV2SourceUnitDTO] = Field(default_factory=list)
    navigation: list[ReaderV2NavigationDTO] = Field(default_factory=list)
    warnings: list[ReaderV2WarningDTO] = Field(default_factory=list)


class ReaderV2NavigationResponse(ReaderV2IdentityDTO):
    navigation: list[ReaderV2NavigationDTO] = Field(default_factory=list)


class ReaderV2ContentResponse(ReaderV2IdentityDTO):
    nodes: list[ReaderV2NodeDTO] = Field(default_factory=list)
    has_more: bool
    next_node_order: int | None = None


class ReaderV2AssetResponse(ReaderV2IdentityDTO):
    asset_id: str
    role: str
    recovery_state: str
    source_unit_ids: list[str] = Field(default_factory=list)
    source_anchors: list[dict[str, Any]] = Field(default_factory=list)
    caption: str | None = None
    alt_text: str | None = None
    delivery_state: str
    rendition_id: str | None = None
    rendition_role: str | None = None
    rendition_media_type: str | None = None
    rendition_recovery_state: str | None = None


def _warning(value: ReaderV2Warning) -> ReaderV2WarningDTO:
    return ReaderV2WarningDTO(code=value.code.value)


def _location(value: ReaderLocationV2) -> ReaderV2LocationDTO:
    return ReaderV2LocationDTO(
        document_ref=value.document_ref,
        candidate_id=value.candidate_id,
        candidate_schema_id=value.candidate_schema_id,
        candidate_schema_version=value.candidate_schema_version,
        contract_version=value.contract_version,
        node_id=value.node_id,
        source_unit_id=value.source_unit_id,
        source_anchor=anchor_to_dict(value.source_anchor) if value.source_anchor is not None else None,
    )


def _source_unit(value: ReaderSourceUnitViewV2) -> ReaderV2SourceUnitDTO:
    payload = source_unit_to_dict(value.source_unit)
    return ReaderV2SourceUnitDTO(
        **payload,
        content_state=value.content_state.value,
        warnings=[_warning(item) for item in value.warnings],
    )


def _node(value: ReaderNodeViewV2) -> ReaderV2NodeDTO:
    return ReaderV2NodeDTO(
        location=_location(value.location),
        node_id=value.node_id,
        node_type=value.node_type.value,
        order=value.order,
        content_state=value.content_state.value,
        source_unit_ids=list(value.source_unit_ids),
        source_anchors=[anchor_to_dict(item) for item in value.source_anchors],
        text=value.text,
        heading_level=value.heading_level,
        parent_ref=value.parent_ref,
        child_refs=list(value.child_refs),
        asset_refs=list(value.asset_refs),
        warnings=[_warning(item) for item in value.warnings],
        metadata=value.metadata,
    )


def _navigation(value: ReaderNavigationEntryV2) -> ReaderV2NavigationDTO:
    return ReaderV2NavigationDTO(
        location=_location(value.location),
        label=value.label,
        order=value.order,
        heading_level=value.heading_level,
    )


def _identity(value: ReaderDocumentViewV2 | ReaderContentChunkV2) -> dict[str, object]:
    if isinstance(value, ReaderDocumentViewV2):
        return {
            "contract_version": value.contract_version,
            "document_ref": value.document_ref,
            "candidate_id": value.candidate_id,
            "candidate_schema_id": value.candidate_schema_id,
            "candidate_schema_version": value.candidate_schema_version,
        }
    return {
        "contract_version": value.contract_version,
        "document_ref": value.document_ref,
        "candidate_id": value.candidate_id,
        "candidate_schema_id": "atlas.structured-content-candidate",
        "candidate_schema_version": 2,
    }


def reader_v2_open_response(value: ReaderDocumentViewV2) -> ReaderV2OpenResponse:
    return ReaderV2OpenResponse(
        **_identity(value),
        content_state=value.content_state.value,
        metadata=ReaderV2MetadataDTO(
            source_unit_count=value.metadata.source_unit_count,
            physical_page_count=value.metadata.physical_page_count,
            reflowable_source_unit_count=value.metadata.reflowable_source_unit_count,
        ),
        source_units=[_source_unit(item) for item in value.source_units],
        navigation=[_navigation(item) for item in value.navigation],
        warnings=[_warning(item) for item in value.warnings],
    )


def reader_v2_navigation_response(value: ReaderDocumentViewV2) -> ReaderV2NavigationResponse:
    return ReaderV2NavigationResponse(
        **_identity(value),
        navigation=[_navigation(item) for item in value.navigation],
    )


def reader_v2_content_response(value: ReaderDocumentViewV2, chunk: ReaderContentChunkV2) -> ReaderV2ContentResponse:
    return ReaderV2ContentResponse(
        **_identity(value),
        nodes=[_node(item) for item in chunk.nodes],
        has_more=chunk.has_more,
        next_node_order=chunk.next_node_order,
    )


def reader_v2_asset_response(value: ReaderV2AssetDelivery) -> ReaderV2AssetResponse:
    return ReaderV2AssetResponse(
        contract_version="2",
        document_ref=value.document_ref,
        candidate_id=value.candidate_id,
        candidate_schema_id=value.candidate_schema_id,
        candidate_schema_version=value.candidate_schema_version,
        asset_id=value.asset_id,
        role=value.role,
        recovery_state=value.recovery_state,
        source_unit_ids=list(value.source_unit_ids),
        source_anchors=[anchor_to_dict(item) for item in value.source_anchors],
        caption=value.caption,
        alt_text=value.alt_text,
        delivery_state=value.delivery_state,
        rendition_id=value.rendition_id,
        rendition_role=value.rendition_role,
        rendition_media_type=value.rendition_media_type,
        rendition_recovery_state=value.rendition_recovery_state,
    )


__all__ = [
    "ReaderV2AssetResponse",
    "ReaderV2ContentResponse",
    "ReaderV2NavigationResponse",
    "ReaderV2OpenResponse",
    "reader_v2_asset_response",
    "reader_v2_content_response",
    "reader_v2_navigation_response",
    "reader_v2_open_response",
]