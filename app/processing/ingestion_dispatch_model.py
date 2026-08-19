"""Durable acceptance-to-processing dispatch state.

This table is deliberately separate from ProcessingRun. ProcessingRun remains
processing provenance/observability state; IngestionDispatch is the durable
business-acceptance envelope that makes post-commit processing dispatch
recoverable.
"""
from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from app.models import Base


class IngestionDispatch(Base):
    """One durable initial-ingestion dispatch for one accepted book source."""

    __tablename__ = "ingestion_dispatches"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('pdf', 'txt')",
            name="ck_ingestion_dispatch_kind",
        ),
        CheckConstraint(
            "status IN ('queued', 'claimed', 'running', 'succeeded', 'failed')",
            name="ck_ingestion_dispatch_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_ingestion_dispatch_attempt_count_nonnegative",
        ),
        CheckConstraint(
            "((kind = 'pdf' AND processing_attempt_id IS NOT NULL "
            "AND provider_job_id IS NOT NULL AND provider_request_id IS NOT NULL "
            "AND txt_processing_run_ref IS NULL) OR "
            "(kind = 'txt' AND processing_attempt_id IS NULL "
            "AND provider_job_id IS NULL AND provider_request_id IS NULL "
            "AND txt_processing_run_ref IS NOT NULL))",
            name="ck_ingestion_dispatch_payload",
        ),
        UniqueConstraint("acceptance_key", name="uq_ingestion_dispatch_acceptance_key"),
        Index("ix_ingestion_dispatch_document_id", "document_id"),
        Index("ix_ingestion_dispatch_status_lease", "status", "claim_expires_at"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    acceptance_key = Column(String(255), nullable=False)
    document_id = Column(
        String,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_file_id = Column(
        String,
        ForeignKey("source_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind = Column(String(16), nullable=False)

    processing_attempt_id = Column(String(255), nullable=True)
    provider_job_id = Column(String(255), nullable=True)
    provider_request_id = Column(String(255), nullable=True)
    txt_processing_run_ref = Column(String(255), nullable=True)

    status = Column(String(16), nullable=False, default="queued")
    claim_token = Column(String(64), nullable=True)
    claim_expires_at = Column(DateTime, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


__all__ = ["IngestionDispatch"]
