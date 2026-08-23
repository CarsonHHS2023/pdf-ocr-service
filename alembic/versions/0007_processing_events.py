"""Add append-only durable processing diagnostic events.

Revision ID: 0007_processing_events
Revises: 0006_ingestion_dispatches
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_processing_events"
down_revision = "0006_ingestion_dispatches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processing_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("processing_run_id", sa.String(length=255), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("event_name", sa.String(length=128), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "processing_run_id <> ''",
            name="ck_processing_events_run_id_nonempty",
        ),
        sa.CheckConstraint(
            "event_name <> ''",
            name="ck_processing_events_event_name_nonempty",
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'error')",
            name="ck_processing_events_severity_supported",
        ),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number > 0",
            name="ck_processing_events_page_number_positive",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_processing_events_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_processing_events_run_created",
        "processing_events",
        ["processing_run_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_processing_events_document_created",
        "processing_events",
        ["document_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_processing_events_name_created",
        "processing_events",
        ["event_name", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_processing_events_name_created", table_name="processing_events")
    op.drop_index("ix_processing_events_document_created", table_name="processing_events")
    op.drop_index("ix_processing_events_run_created", table_name="processing_events")
    op.drop_table("processing_events")
