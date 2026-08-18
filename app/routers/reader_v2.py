"""Source-unit-aware Reader v2 HTTP API."""
from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.reader_v2.api_models import (
    ReaderV2AssetResponse,
    ReaderV2ContentResponse,
    ReaderV2NavigationResponse,
    ReaderV2OpenResponse,
    reader_v2_asset_response,
    reader_v2_content_response,
    reader_v2_navigation_response,
    reader_v2_open_response,
)
from app.reader_v2.assets import (
    ReaderV2AssetDelivery,
    ReaderV2AssetError,
    ReaderV2AssetNotFound,
    ReaderV2SelectionChanged,
    build_selected_reader_v2_asset,
    build_selected_reader_v2_asset_deliveries,
    build_selected_reader_v2_opencv_diagnostic,
)
from app.reader_v2.contracts import ReaderContentChunkV2, ReaderDocumentViewV2
from app.reader_v2.service import (
    NoSelectedReaderV2Content,
    ReaderV2ServiceError,
    SelectedReaderV2CandidateDocumentMismatch,
    build_selected_reader_v2_document,
)
from app.storage.dependencies import get_storage_provider
from app.storage.errors import InvalidReference, ObjectNotFound, ProviderUnavailable, ReadFailure
from app.storage.models import StorageReference
from app.structured_content_v2.repository import (
    StructuredContentV2CandidateNotFound,
    StructuredContentV2PersistenceError,
)
from app.structured_content_v2.selection import (
    StructuredContentV2SelectionCandidateInvalid,
    StructuredContentV2SelectionCandidateMismatch,
    StructuredContentV2SelectionError,
    StructuredContentV2SelectionNotFound,
)


router = APIRouter(prefix="/api/reader/v2", tags=["reader-v2"])

DEFAULT_NODE_LIMIT = 100
MAX_NODE_LIMIT = 500


def _api_error(status_code: int, code: str, message: str) -> NoReturn:
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _selection_changed() -> NoReturn:
    _api_error(
        status.HTTP_409_CONFLICT,
        "reader_selection_changed",
        "The Reader location is stale because the selected content changed.",
    )


def _map_reader_error(exc: Exception) -> NoReturn:
    if isinstance(exc, (NoSelectedReaderV2Content, StructuredContentV2SelectionNotFound)):
        _api_error(
            status.HTTP_409_CONFLICT,
            "reader_not_ready",
            "Reader content is not available for this document.",
        )
    if isinstance(exc, ReaderV2SelectionChanged):
        _selection_changed()
    if isinstance(
        exc,
        (
            SelectedReaderV2CandidateDocumentMismatch,
            StructuredContentV2SelectionCandidateInvalid,
            StructuredContentV2SelectionCandidateMismatch,
            StructuredContentV2CandidateNotFound,
        ),
    ):
        _api_error(
            status.HTTP_409_CONFLICT,
            "reader_selection_invalid",
            "The selected Reader content is invalid for this document.",
        )
    if isinstance(
        exc,
        (
            ReaderV2AssetError,
            ReaderV2ServiceError,
            StructuredContentV2PersistenceError,
            StructuredContentV2SelectionError,
        ),
    ):
        _api_error(
            status.HTTP_409_CONFLICT,
            "reader_content_incompatible",
            "The selected content cannot be represented by this Reader contract.",
        )
    raise exc


def _build_view(db: Session, document_ref: str) -> ReaderDocumentViewV2:
    try:
        return build_selected_reader_v2_document(session=db, document_ref=document_ref)
    except Exception as exc:
        _map_reader_error(exc)


def _map_asset_build_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ReaderV2AssetNotFound):
        _api_error(
            status.HTTP_404_NOT_FOUND,
            "reader_asset_not_found",
            "Asset or requested diagnostic is not part of selected Reader content.",
        )
    _map_reader_error(exc)


def _build_asset(
    db: Session,
    document_ref: str,
    candidate_id: str,
    asset_id: str,
) -> ReaderV2AssetDelivery:
    try:
        return build_selected_reader_v2_asset(
            session=db,
            document_ref=document_ref,
            candidate_id=candidate_id,
            asset_id=asset_id,
        )
    except Exception as exc:
        _map_asset_build_error(exc)


def _build_asset_deliveries(
    db: Session,
    document_ref: str,
    candidate_id: str,
    asset_id: str,
) -> tuple[ReaderV2AssetDelivery, ...]:
    try:
        return build_selected_reader_v2_asset_deliveries(
            session=db,
            document_ref=document_ref,
            candidate_id=candidate_id,
            asset_id=asset_id,
        )
    except Exception as exc:
        _map_asset_build_error(exc)


def _build_opencv_diagnostic(
    db: Session,
    document_ref: str,
    candidate_id: str,
    asset_id: str,
) -> ReaderV2AssetDelivery:
    try:
        return build_selected_reader_v2_opencv_diagnostic(
            session=db,
            document_ref=document_ref,
            candidate_id=candidate_id,
            asset_id=asset_id,
        )
    except Exception as exc:
        _map_asset_build_error(exc)


def _deliver_asset_bytes(
    delivery: ReaderV2AssetDelivery,
    *,
    attachment_filename: str | None = None,
) -> Response:
    if delivery.delivery_state != "available" or delivery.storage_ref is None:
        _api_error(
            status.HTTP_409_CONFLICT,
            "reader_asset_unavailable",
            "Asset content is unavailable; Reader metadata remains usable.",
        )

    storage = get_storage_provider()
    try:
        reference = StorageReference.parse(delivery.storage_ref)
        data = storage.get(reference)
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

    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if attachment_filename is not None:
        headers["Content-Disposition"] = f'attachment; filename="{attachment_filename}"'
    return Response(
        content=data,
        media_type=delivery.rendition_media_type or "application/octet-stream",
        headers=headers,
    )


@router.get("/documents/{document_ref}", response_model=ReaderV2OpenResponse)
def open_reader_v2_document(
    document_ref: str,
    db: Session = Depends(get_db),
) -> ReaderV2OpenResponse:
    """Return selected Reader v2 identity, source units, navigation, and state."""
    return reader_v2_open_response(_build_view(db, document_ref))


@router.get("/documents/{document_ref}/navigation", response_model=ReaderV2NavigationResponse)
def get_reader_v2_navigation(
    document_ref: str,
    db: Session = Depends(get_db),
) -> ReaderV2NavigationResponse:
    """Return source-position-stable heading navigation."""
    return reader_v2_navigation_response(_build_view(db, document_ref))


@router.get("/documents/{document_ref}/content", response_model=ReaderV2ContentResponse)
def get_reader_v2_content(
    document_ref: str,
    start_node_order: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_NODE_LIMIT, ge=1, le=MAX_NODE_LIMIT),
    candidate_id: str | None = Query(default=None, min_length=1),
    db: Session = Depends(get_db),
) -> ReaderV2ContentResponse:
    """Return a bounded semantic-node chunk independent of presentation pagination."""
    view = _build_view(db, document_ref)
    if candidate_id is not None and view.candidate_id != candidate_id:
        _selection_changed()

    eligible = tuple(node for node in view.nodes if node.order >= start_node_order)
    nodes = eligible[:limit]
    next_node = eligible[limit] if len(eligible) > limit else None
    chunk = ReaderContentChunkV2(
        document_ref=view.document_ref,
        candidate_id=view.candidate_id,
        nodes=nodes,
        has_more=next_node is not None,
        next_node_order=next_node.order if next_node is not None else None,
    )
    return reader_v2_content_response(view, chunk)


@router.get("/documents/{document_ref}/assets/{asset_id}", response_model=ReaderV2AssetResponse)
def get_reader_v2_asset(
    document_ref: str,
    asset_id: str,
    candidate_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> ReaderV2AssetResponse:
    """Return selected v2 asset metadata without exposing durable storage locators."""
    return reader_v2_asset_response(_build_asset(db, document_ref, candidate_id, asset_id))


@router.get("/documents/{document_ref}/assets/{asset_id}/content")
def get_reader_v2_asset_content(
    document_ref: str,
    asset_id: str,
    candidate_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> Response:
    """Return the highest-priority non-diagnostic stored rendition with fallback."""
    deliveries = _build_asset_deliveries(db, document_ref, candidate_id, asset_id)
    available = tuple(
        delivery
        for delivery in deliveries
        if delivery.delivery_state == "available" and delivery.storage_ref is not None
    )
    if not available:
        _api_error(
            status.HTTP_409_CONFLICT,
            "reader_asset_unavailable",
            "Asset content is unavailable; Reader metadata remains usable.",
        )

    storage = get_storage_provider()
    for delivery in available:
        try:
            reference = StorageReference.parse(delivery.storage_ref)
            data = storage.get(reference)
        except (ObjectNotFound, InvalidReference):
            continue
        except (ProviderUnavailable, ReadFailure):
            _api_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "reader_asset_delivery_unavailable",
                "Asset delivery is temporarily unavailable.",
            )

        return Response(
            content=data,
            media_type=delivery.rendition_media_type or "application/octet-stream",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    _api_error(
        status.HTTP_409_CONFLICT,
        "reader_asset_unavailable",
        "Asset content is unavailable; Reader metadata remains usable.",
    )


@router.get(
    "/documents/{document_ref}/assets/{asset_id}/diagnostics/opencv-candidate/content"
)
def download_reader_v2_opencv_candidate(
    document_ref: str,
    asset_id: str,
    candidate_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> Response:
    """Download the retained OpenCV candidate without allowing it into Reader fallback."""
    delivery = _build_opencv_diagnostic(db, document_ref, candidate_id, asset_id)
    return _deliver_asset_bytes(
        delivery,
        attachment_filename="opencv-candidate.png",
    )
