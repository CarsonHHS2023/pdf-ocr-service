"""add processing run provenance

Revision ID: 0003_processing_runs
Revises: 0002_structured_content
Create Date: 2026-07-22 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_processing_runs"
down_revision = "0002_structured_content_persistence_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processing_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("processing_run_id", sa.String(length=255), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("source_file_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("provider_ref", sa.String(length=255), nullable=True),
        sa.Column("provider_model_ref", sa.String(length=255), nullable=True),
        sa.Column("processing_policy_ref", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("raw_result_ref", sa.String(length=1024), nullable=True),
        sa.Column("structured_processing_result_ref", sa.String(length=1024), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.Column("safe_error_code", sa.String(length=255), nullable=True),
        sa.Column("safe_error_summary", sa.Text(), nullable=True),
        sa.Column("metrics_json", sa.Text(), nullable=True),
        sa.Column("extensions_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("processing_run_id <> ''", name="ck_processing_runs_run_id_nonempty"),
        sa.CheckConstraint("status IN ('created','running','succeeded','failed','cancelled')", name="ck_processing_runs_status_supported"),
        sa.CheckConstraint("idempotency_key IS NULL OR idempotency_key <> ''", name="ck_processing_runs_idempotency_key_nonempty"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name="fk_processing_runs_document_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], name="fk_processing_runs_source_file_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_processing_runs"),
        sa.UniqueConstraint("processing_run_id", name="uq_processing_runs_processing_run_id"),
        sa.UniqueConstraint("document_id", "idempotency_key", name="uq_processing_runs_document_idempotency_key"),
    )
    op.create_index("ix_processing_runs_document_created", "processing_runs", ["document_id", "created_at", "processing_run_id"])
    op.create_index("ix_processing_runs_source_file_id", "processing_runs", ["source_file_id"])
    op.create_index("ix_processing_runs_raw_result_ref", "processing_runs", ["raw_result_ref"])
    op.create_index("ix_processing_runs_spr_ref", "processing_runs", ["structured_processing_result_ref"])


def downgrade() -> None:
    op.drop_index("ix_processing_runs_spr_ref", table_name="processing_runs")
    op.drop_index("ix_processing_runs_raw_result_ref", table_name="processing_runs")
    op.drop_index("ix_processing_runs_source_file_id", table_name="processing_runs")
    op.drop_index("ix_processing_runs_document_created", table_name="processing_runs")
    op.drop_table("processing_runs")
