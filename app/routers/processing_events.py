"""Authenticated read-only access to bounded durable processing events."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.processing.processing_events import MAX_QUERY_LIMIT, list_processing_events
from app.routers.processing_operator import require_operator_auth


router = APIRouter(
    prefix="/internal/operator/processing-events",
    tags=["internal-processing-operator"],
    include_in_schema=False,
)


class ProcessingEventResponse(BaseModel):
    event_id: str
    processing_run_id: str
    document_id: str
    schema_version: str
    event_name: str
    severity: str
    page_number: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ProcessingEventListResponse(BaseModel):
    processing_run_id: str | None = None
    document_id: str | None = None
    event_name: str | None = None
    count: int
    events: list[ProcessingEventResponse] = Field(default_factory=list)


@router.get("", response_model=ProcessingEventListResponse)
def get_processing_events(
    processing_run_id: str | None = Query(default=None, max_length=255),
    document_id: str | None = Query(default=None, max_length=255),
    event_name: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=200, ge=1, le=MAX_QUERY_LIMIT),
    _: None = Depends(require_operator_auth),
    db: Session = Depends(get_db),
) -> ProcessingEventListResponse:
    """Return a sanitized event window for one run and/or document."""
    if not processing_run_id and not document_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="processing_run_id or document_id is required",
        )
    try:
        records = list_processing_events(
            db,
            processing_run_id=processing_run_id,
            document_id=document_id,
            event_name=event_name,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return ProcessingEventListResponse(
        processing_run_id=processing_run_id,
        document_id=document_id,
        event_name=event_name,
        count=len(records),
        events=[
            ProcessingEventResponse(
                event_id=item.event_id,
                processing_run_id=item.processing_run_id,
                document_id=item.document_id,
                schema_version=item.schema_version,
                event_name=item.event_name,
                severity=item.severity,
                page_number=item.page_number,
                payload=item.payload,
                created_at=item.created_at,
            )
            for item in records
        ],
    )


__all__ = ["router"]
