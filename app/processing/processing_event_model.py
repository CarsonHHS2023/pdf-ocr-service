"""Append-only durable processing diagnostic events.

ProcessingEvent is deliberately observability state, not workflow/queue truth.
Events may be emitted before the corresponding ProcessingRun row is initialized,
so processing_run_id is a stable correlation key rather than a foreign key.
"""
from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text

from app.models import Base


class ProcessingEvent(Base):
    """One bounded, sanitized diagnostic event for a processing attempt."""

    __tablename__ = "processing_events"
    __table_args__ = (
        CheckConstraint("processing_run_id <> ''", name="ck_processing_events_run_id_nonempty"),
        CheckConstraint("event_name <> ''", name="ck_processing_events_event_name_nonempty"),
        CheckConstraint(
            "severity IN ('info', 'warning', 'error')",
            name="ck_processing_events_severity_supported",
        ),
        CheckConstraint(
            "page_number IS NULL OR page_number > 0",
            name="ck_processing_events_page_number_positive",
        ),
        Index(
            "ix_processing_events_run_created",
            "processing_run_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_processing_events_document_created",
            "document_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_processing_events_name_created",
            "event_name",
            "created_at",
            "id",
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    processing_run_id = Column(String(255), nullable=False)
    document_id = Column(
        String,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    schema_version = Column(String(64), nullable=False)
    event_name = Column(String(128), nullable=False)
    severity = Column(String(16), nullable=False, default="info")
    page_number = Column(Integer, nullable=True)
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


__all__ = ["ProcessingEvent"]
