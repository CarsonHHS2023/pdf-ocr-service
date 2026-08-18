"""Explicit selection record for Structured Content v2 candidates."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text

from app.models import Base


class StructuredContentSelectionV2Record(Base):
    __tablename__ = "structured_content_v2_selection"
    __table_args__ = (
        CheckConstraint("selection_version >= 0", name="ck_scv2_selection_version_nonnegative"),
        ForeignKeyConstraint(
            ["candidate_record_id", "document_id"],
            ["structured_content_v2_candidates.id", "structured_content_v2_candidates.document_id"],
            name="fk_scv2_selection_candidate_document",
            ondelete="RESTRICT",
        ),
    )

    document_id = Column(String, ForeignKey("documents.id", ondelete="RESTRICT"), primary_key=True)
    candidate_record_id = Column(String, nullable=False)
    selection_version = Column(Integer, nullable=False, default=0)
    selected_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    selection_actor_ref = Column(String(255), nullable=True)
    reason = Column(Text, nullable=True)
