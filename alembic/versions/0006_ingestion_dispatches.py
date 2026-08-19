"""Add durable ingestion dispatch envelopes.

Revision ID: 0006_ingestion_dispatches
Revises: 0005_structured_content_v2_selection
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_ingestion_dispatches"
down_revision = "0005_structured_content_v2_selection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_dispatches",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("acceptance_key", sa.String(length=255), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("source_file_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("processing_attempt_id", sa.String(length=255), nullable=True),
        sa.Column("provider_job_id", sa.String(length=255), nullable=True),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("txt_processing_run_ref", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("claim_token", sa.String(length=64), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('pdf', 'txt')",
            name="ck_ingestion_dispatch_kind",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'claimed', 'running', 'succeeded', 'failed')",
            name="ck_ingestion_dispatch_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_ingestion_dispatch_attempt_count_nonnegative",
        ),
        sa.CheckConstraint(
            "((kind = 'pdf' AND processing_attempt_id IS NOT NULL "
            "AND provider_job_id IS NOT NULL AND provider_request_id IS NOT NULL "
            "AND txt_processing_run_ref IS NULL) OR "
            "(kind = 'txt' AND processing_attempt_id IS NULL "
            "AND provider_job_id IS NULL AND provider_request_id IS NULL "
            "AND txt_processing_run_ref IS NOT NULL))",
            name="ck_ingestion_dispatch_payload",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_ingestion_dispatch_document",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["source_files.id"],
            name="fk_ingestion_dispatch_source_file",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "acceptance_key",
            name="uq_ingestion_dispatch_acceptance_key",
        ),
    )
    op.create_index(
        "ix_ingestion_dispatch_document_id",
        "ingestion_dispatches",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_ingestion_dispatch_status_lease",
        "ingestion_dispatches",
        ["status", "claim_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ingestion_dispatch_status_lease",
        table_name="ingestion_dispatches",
    )
    op.drop_index(
        "ix_ingestion_dispatch_document_id",
        table_name="ingestion_dispatches",
    )
    op.drop_table("ingestion_dispatches")
