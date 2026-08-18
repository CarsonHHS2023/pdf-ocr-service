from __future__ import annotations

from pydantic import BaseModel, Field

from .asset_contracts import ReaderAssetDelivery, ReaderTableDelivery
from .contracts import (
    ReaderContentChunk,
    ReaderDocumentMetadata,
    ReaderDocumentView,
    ReaderLocation,
    ReaderNavigationEntry,
    ReaderNodeView,
    ReaderPageView,
    ReaderWarning,
)


class ReaderWarningDTO(BaseModel):
    code: str


class ReaderLocationDTO(BaseModel):
    document_ref: str
    candidate_id: str
    candidate_schema_id: str
    candidate_schema_version: int
    contract_version: str
    page_id: str | None = None
    node_id: str | None = None
    segment_index: int | None = None


class ReaderMetadataDTO(BaseModel):
    title: str | None = None
    page_count: int


class ReaderNodeDTO(BaseModel):
    location: ReaderLocationDTO
    node_id: str
    node_type: str
    order: int
    content_state: str
    text: str | None = None
    heading_level: int | None = None
    parent_ref: str | None = None
    child_refs: list[str] = Field(default_factory=list)
    asset_refs: list[str] = Field(default_factory=list)
    warnings: list[ReaderWarningDTO] = Field(default_factory=list)


class ReaderPageDTO(BaseModel):
    location: ReaderLocationDTO
    page_id: str
    page_order: int
    content_state: str
    nodes: list[ReaderNodeDTO] = Field(default_factory=list)
    warnings: list[ReaderWarningDTO] = Field(default_factory=list)


class ReaderNavigationDTO(BaseModel):
    location: ReaderLocationDTO
    label: str
    order: int
    heading_level: int
    kind: str


class ReaderContinuationDTO(BaseModel):
    location: ReaderLocationDTO
    page_order: int


class ReaderIdentityDTO(BaseModel):
    contract_version: str
    document_ref: str
    candidate_id: str
    candidate_schema_id: str
    candidate_schema_version: int


class ReaderOpenResponse(ReaderIdentityDTO):
    processing_state: str
    content_state: str
    metadata: ReaderMetadataDTO
    navigation: list[ReaderNavigationDTO] = Field(default_factory=list)
    warnings: list[ReaderWarningDTO] = Field(default_factory=list)


class ReaderNavigationResponse(ReaderIdentityDTO):
    navigation: list[ReaderNavigationDTO] = Field(default_factory=list)


class ReaderContentResponse(ReaderIdentityDTO):
    pages: list[ReaderPageDTO] = Field(default_factory=list)
    has_more: bool
    continuation: ReaderContinuationDTO | None = None


class ReaderAssetResponse(ReaderIdentityDTO):
    asset_id: str
    role: str
    recovery_state: str
    delivery_state: str
    media_type: str | None = None
    byte_size: int | None = None
    caption: str | None = None
    alt_text: str | None = None
    description: str | None = None
    content_href: str | None = None


class ReaderTableCellDTO(BaseModel):
    row_index: int
    column_index: int
    row_span: int
    column_span: int
    text: str | None = None


class ReaderTableResponse(ReaderIdentityDTO):
    page_id: str
    node_id: str
    content_state: str
    row_count: int
    column_count: int
    cell_offset: int
    cell_limit: int
    cells: list[ReaderTableCellDTO] = Field(default_factory=list)
    has_more: bool
    next_cell_offset: int | None = None
    rendered_asset_id: str | None = None
    rendered_asset_href: str | None = None


def _location(value: ReaderLocation) -> ReaderLocationDTO:
    return ReaderLocationDTO(
        document_ref=str(value.document_ref),
        candidate_id=str(value.candidate_id),
        candidate_schema_id=value.candidate_schema_id,
        candidate_schema_version=value.candidate_schema_version,
        contract_version=value.contract_version,
        page_id=str(value.page_id) if value.page_id is not None else None,
        node_id=str(value.node_id) if value.node_id is not None else None,
        segment_index=value.segment_index,
    )


def _warning(value: ReaderWarning) -> ReaderWarningDTO:
    return ReaderWarningDTO(code=value.code.value)


def _metadata(value: ReaderDocumentMetadata) -> ReaderMetadataDTO:
    return ReaderMetadataDTO(title=value.title, page_count=value.page_count)


def _node(value: ReaderNodeView) -> ReaderNodeDTO:
    return ReaderNodeDTO(
        location=_location(value.location),
        node_id=str(value.node_id),
        node_type=value.node_type.value,
        order=value.order,
        content_state=value.content_state.value,
        text=value.text,
        heading_level=value.heading_level,
        parent_ref=str(value.parent_ref) if value.parent_ref is not None else None,
        child_refs=[str(ref) for ref in value.child_refs],
        asset_refs=[str(ref) for ref in value.asset_refs],
        warnings=[_warning(warning) for warning in value.warnings],
    )


def _page(value: ReaderPageView) -> ReaderPageDTO:
    return ReaderPageDTO(
        location=_location(value.location),
        page_id=str(value.page_id),
        page_order=value.page_order,
        content_state=value.content_state.value,
        nodes=[_node(node) for node in value.nodes],
        warnings=[_warning(warning) for warning in value.warnings],
    )


def _navigation(value: ReaderNavigationEntry) -> ReaderNavigationDTO:
    return ReaderNavigationDTO(
        location=_location(value.location),
        label=value.label,
        order=value.order,
        heading_level=value.heading_level,
        kind=value.kind.value,
    )


def _identity(value: ReaderDocumentView | ReaderContentChunk) -> dict[str, object]:
    return {
        "contract_version": value.contract_version,
        "document_ref": str(value.document_ref),
        "candidate_id": str(value.candidate_id),
        "candidate_schema_id": value.candidate_schema_id,
        "candidate_schema_version": value.candidate_schema_version,
    }


def _delivery_identity(document_ref: str, candidate_id: str, schema_id: str, schema_version: int) -> dict[str, object]:
    return {
        "contract_version": "1",
        "document_ref": document_ref,
        "candidate_id": candidate_id,
        "candidate_schema_id": schema_id,
        "candidate_schema_version": schema_version,
    }


def reader_open_response(value: ReaderDocumentView) -> ReaderOpenResponse:
    return ReaderOpenResponse(
        **_identity(value),
        processing_state=value.processing_state.value,
        content_state=value.content_state.value,
        metadata=_metadata(value.metadata),
        navigation=[_navigation(entry) for entry in value.navigation],
        warnings=[_warning(warning) for warning in value.warnings],
    )


def reader_navigation_response(value: ReaderDocumentView) -> ReaderNavigationResponse:
    return ReaderNavigationResponse(
        **_identity(value),
        navigation=[_navigation(entry) for entry in value.navigation],
    )


def reader_content_response(value: ReaderContentChunk) -> ReaderContentResponse:
    continuation = None
    if value.continuation is not None:
        continuation = ReaderContinuationDTO(
            location=_location(value.continuation.location),
            page_order=value.continuation.page_order,
        )
    return ReaderContentResponse(
        **_identity(value),
        pages=[_page(page) for page in value.pages],
        has_more=value.has_more,
        continuation=continuation,
    )


def reader_asset_response(value: ReaderAssetDelivery) -> ReaderAssetResponse:
    asset = value.asset
    content_href = None
    if value.delivery_state == "available":
        content_href = (
            f"/api/reader/v1/documents/{value.document_ref}/assets/{asset.asset_id}/content"
            f"?candidate_id={value.candidate_id}"
        )
    return ReaderAssetResponse(
        **_delivery_identity(
            value.document_ref,
            value.candidate_id,
            value.candidate_schema_id,
            value.candidate_schema_version,
        ),
        asset_id=str(asset.asset_id),
        role=asset.role.value,
        recovery_state=asset.recovery_state.value,
        delivery_state=value.delivery_state,
        media_type=value.delivery_media_type,
        byte_size=value.delivery_byte_size,
        caption=asset.caption,
        alt_text=asset.alt_text,
        description=asset.description,
        content_href=content_href,
    )


def reader_table_response(value: ReaderTableDelivery, *, cell_offset: int, cell_limit: int) -> ReaderTableResponse:
    attrs = value.attributes
    ordered_cells = sorted(attrs.structure.cells, key=lambda cell: (cell.row_index, cell.column_index))
    cells = ordered_cells[cell_offset : cell_offset + cell_limit]
    next_offset = cell_offset + len(cells)
    has_more = next_offset < len(ordered_cells)
    rendered_asset_id = str(attrs.rendered_asset_id) if attrs.rendered_asset_id is not None else None
    return ReaderTableResponse(
        **_delivery_identity(
            value.document_ref,
            value.candidate_id,
            value.candidate_schema_id,
            value.candidate_schema_version,
        ),
        page_id=value.page_id,
        node_id=value.node_id,
        content_state=value.content_state.value,
        row_count=attrs.structure.row_count,
        column_count=attrs.structure.column_count,
        cell_offset=cell_offset,
        cell_limit=cell_limit,
        cells=[
            ReaderTableCellDTO(
                row_index=cell.row_index,
                column_index=cell.column_index,
                row_span=cell.row_span,
                column_span=cell.column_span,
                text=cell.text,
            )
            for cell in cells
        ],
        has_more=has_more,
        next_cell_offset=next_offset if has_more else None,
        rendered_asset_id=rendered_asset_id,
        rendered_asset_href=(
            f"/api/reader/v1/documents/{value.document_ref}/assets/{rendered_asset_id}"
            f"?candidate_id={value.candidate_id}"
            if rendered_asset_id is not None
            else None
        ),
    )


__all__ = [
    "ReaderAssetResponse",
    "ReaderContentResponse",
    "ReaderNavigationResponse",
    "ReaderOpenResponse",
    "ReaderTableResponse",
    "reader_asset_response",
    "reader_content_response",
    "reader_navigation_response",
    "reader_open_response",
    "reader_table_response",
]
