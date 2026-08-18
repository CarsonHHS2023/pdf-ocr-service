"""add explicit Structured Content v2 selection

Revision ID: 0005_structured_content_v2_selection
Revises: 0004_structured_content_v2
Create Date: 2026-07-26 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_structured_content_v2_selection"
down_revision = "0004_structured_content_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "structured_content_v2_selection",
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("candidate_record_id", sa.String(), nullable=False),
        sa.Column("selection_version", sa.Integer(), nullable=False),
        sa.Column("selected_at", sa.DateTime(), nullable=False),
        sa.Column("selection_actor_ref", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.CheckConstraint("selection_version >= 0", name="ck_scv2_selection_version_nonnegative"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["candidate_record_id", "document_id"],
            ["structured_content_v2_candidates.id", "structured_content_v2_candidates.document_id"],
            name="fk_scv2_selection_candidate_document",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("document_id"),
    )


def downgrade() -> None:
    op.drop_table("structured_content_v2_selection")
