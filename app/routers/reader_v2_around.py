"""Bounded Reader v2 lookup for restoring legacy node-id-only locations."""
from __future__ import annotations

from fastapi import Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.reader_v2.api_models import ReaderV2ContentResponse, reader_v2_content_response
from app.reader_v2.contracts import ReaderContentChunkV2
from app.routers.reader_v2 import MAX_NODE_LIMIT, _api_error, _build_view, _selection_changed, router


@router.get("/documents/{document_ref}/content/around", response_model=ReaderV2ContentResponse)
def get_reader_v2_content_around(
    document_ref: str,
    node_id: str = Query(..., min_length=1),
    limit: int = Query(default=150, ge=1, le=MAX_NODE_LIMIT),
    candidate_id: str | None = Query(default=None, min_length=1),
    db: Session = Depends(get_db),
) -> ReaderV2ContentResponse:
    """Return exactly one bounded semantic-node window containing ``node_id``."""
    view = _build_view(db, document_ref)
    if candidate_id is not None and view.candidate_id != candidate_id:
        _selection_changed()

    anchor = next((node for node in view.nodes if node.node_id == node_id), None)
    if anchor is None:
        _api_error(
            status.HTTP_404_NOT_FOUND,
            "reader_node_not_found",
            "The Reader node does not exist in the selected content.",
        )

    window_start = (anchor.order // limit) * limit
    eligible = tuple(node for node in view.nodes if node.order >= window_start)
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
