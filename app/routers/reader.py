"""Opt-in versioned Reader API with bounded content and asset delivery."""
from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.reader import (
    NoSelectedReaderContent,
    ReaderContentChunk,
    ReaderContinuation,
    ReaderContractError,
    ReaderDocumentView,
    ReaderServiceError,
    SelectedReaderCandidateDocumentMismatch,
    build_selected_reader_document,
    validate_reader_content_chunk,
)
from app.reader.api_models import (
    ReaderAssetResponse,
    ReaderContentResponse,
    ReaderNavigationResponse,
    ReaderOpenResponse,
    ReaderTableResponse,
    reader_asset_response,
    reader_content_response,
    reader_navigation_response,
    reader_open_response,
    reader_table_response,
)
from app.reader.asset_contracts import (
    ReaderAssetDelivery,
    ReaderAssetNotFound,
    ReaderSelectionChanged,
    ReaderTableNotFound,
)
from app.reader_asset_service import build_selected_reader_asset, build_selected_reader_table
from app.storage.dependencies import get_storage_provider
from app.storage.errors import InvalidReference, ObjectNotFound, ProviderUnavailable, ReadFailure
from app.storage.models import StorageReference
from app.structured_content.errors import (
    CandidateSelectionCorrupt,
    PersistedCandidateCorrupt,
    StructuredContentCandidateNotFound,
)

router = APIRouter(prefix="/api/reader/v1", tags=["reader-v1"])

DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 50
DEFAULT_TABLE_CELL_LIMIT = 200
MAX_TABLE_CELL_LIMIT = 500


def _api_error(status_code: int, code: str, message: str) -> NoReturn:
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _selection_changed() -> NoReturn:
    _api_error(
        status.HTTP_409_CONFLICT,
        "reader_selection_changed",
        "The Reader location is stale because the selected content changed.",
    )


def _map_selected_content_error(exc: Exception) -> NoReturn:
    if isinstance(exc, NoSelectedReaderContent):
        _api_error(
            status.HTTP_409_CONFLICT,
            "reader_not_ready",
            "Reader content is not available for this document.",
        )
    if isinstance(exc, ReaderSelectionChanged):
        _selection_changed()
    if isinstance(
        exc,
        (
            SelectedReaderCandidateDocumentMismatch,
            CandidateSelectionCorrupt,
            StructuredContentCandidateNotFound,
        ),
    ):
        _api_error(
            status.HTTP_409_CONFLICT,
            "reader_selection_invalid",
            "The selected Reader content is invalid for this document.",
        )
    if isinstance(exc, (ReaderServiceError, ReaderContractError, PersistedCandidateCorrupt)):
        _api_error(
            status.HTTP_409_CONFLICT,
            "reader_content_incompatible",
            "The selected content cannot be represented by this Reader contract.",
        )
    raise exc


def _build_view(db: Session, document_ref: str) -> ReaderDocumentView:
    try:
        return build_selected_reader_document(session=db, document_ref=document_ref)
    except Exception as exc:
        _map_selected_content_error(exc)


def _build_asset(db: Session, document_ref: str, candidate_id: str, asset_id: str) -> ReaderAssetDelivery:
    try:
        return build_selected_reader_asset(
            session=db,
            document_ref=document_ref,
            candidate_id=candidate_id,
            asset_id=asset_id,
        )
    except ReaderAssetNotFound:
        _api_error(status.HTTP_404_NOT_FOUND, "reader_asset_not_found", "Asset is not part of selected Reader content.")
    except Exception as exc:
        _map_selected_content_error(exc)


@router.get("/documents/{document_ref}", response_model=ReaderOpenResponse)
def open_reader_document(document_ref: str, db: Session = Depends(get_db)) -> ReaderOpenResponse:
    """Return document state, metadata, navigation, and warnings without page bodies."""
    return reader_open_response(_build_view(db, document_ref))


@router.get("/documents/{document_ref}/navigation", response_model=ReaderNavigationResponse)
def get_reader_navigation(document_ref: str, db: Session = Depends(get_db)) -> ReaderNavigationResponse:
    """Return navigation metadata separately from Reader page content."""
    return reader_navigation_response(_build_view(db, document_ref))


@router.get("/documents/{document_ref}/content", response_model=ReaderContentResponse)
def get_reader_content(
    document_ref: str,
    start_page_order: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    candidate_id: str | None = Query(default=None, min_length=1),
    db: Session = Depends(get_db),
) -> ReaderContentResponse:
    """Return a bounded page chunk, optionally bound to a prior candidate location."""
    view = _build_view(db, document_ref)
    if candidate_id is not None and str(view.candidate_id) != candidate_id:
        _selection_changed()
    eligible = tuple(page for page in view.pages if page.page_order >= start_page_order)
    pages = eligible[:limit]
    next_page = eligible[limit] if len(eligible) > limit else None

    continuation = None
    if next_page is not None:
        continuation = ReaderContinuation(
            location=next_page.location,
            page_order=next_page.page_order,
        )

    chunk = ReaderContentChunk(
        document_ref=view.document_ref,
        candidate_id=view.candidate_id,
        candidate_schema_id=view.candidate_schema_id,
        candidate_schema_version=view.candidate_schema_version,
        pages=pages,
        has_more=next_page is not None,
        continuation=continuation,
    )
    validate_reader_content_chunk(chunk)
    return reader_content_response(chunk)


@router.get("/documents/{document_ref}/assets/{asset_id}", response_model=ReaderAssetResponse)
def get_reader_asset(
    document_ref: str,
    asset_id: str,
    candidate_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> ReaderAssetResponse:
    """Return selected-candidate asset metadata without exposing storage locators."""
    return reader_asset_response(_build_asset(db, document_ref, candidate_id, asset_id))


@router.get("/documents/{document_ref}/assets/{asset_id}/content")
def get_reader_asset_content(
    document_ref: str,
    asset_id: str,
    candidate_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> Response:
    """Return selected asset bytes only for the candidate identity carried by the Reader location."""
    delivery = _build_asset(db, document_ref, candidate_id, asset_id)
    if delivery.delivery_state != "available" or delivery.storage_ref is None:
        _api_error(
            status.HTTP_409_CONFLICT,
            "reader_asset_unavailable",
            "Asset content is unavailable; Reader metadata remains usable.",
        )
    try:
        reference = StorageReference.parse(delivery.storage_ref)
        data = get_storage_provider().get(reference)
    except (ObjectNotFound, InvalidReference):
        _api_error(
            status.HTTP_409_CONFLICT,
            "reader_asset_unavailable",
            "Asset content is unavailable; Reader metadata remains usable.",
        )
    except (ProviderUnavailable, ReadFailure):
        _api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "reader_asset_delivery_unavailable",
            "Asset delivery is temporarily unavailable.",
        )
    headers = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
    return Response(
        content=data,
        media_type=delivery.delivery_media_type or "application/octet-stream",
        headers=headers,
    )


@router.get("/documents/{document_ref}/tables/{node_id}", response_model=ReaderTableResponse)
def get_reader_table(
    document_ref: str,
    node_id: str,
    candidate_id: str = Query(..., min_length=1),
    cell_offset: int = Query(default=0, ge=0),
    cell_limit: int = Query(default=DEFAULT_TABLE_CELL_LIMIT, ge=1, le=MAX_TABLE_CELL_LIMIT),
    db: Session = Depends(get_db),
) -> ReaderTableResponse:
    """Return a bounded structured-table cell slice with optional rendered-asset identity."""
    try:
        table = build_selected_reader_table(
            session=db,
            document_ref=document_ref,
            candidate_id=candidate_id,
            node_id=node_id,
        )
    except ReaderTableNotFound:
        _api_error(status.HTTP_404_NOT_FOUND, "reader_table_not_found", "Table is not part of selected Reader content.")
    except Exception as exc:
        _map_selected_content_error(exc)
    return reader_table_response(table, cell_offset=cell_offset, cell_limit=cell_limit)
