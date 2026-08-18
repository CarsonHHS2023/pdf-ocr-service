"""add source-unit-centric Structured Content v2 persistence schema

Revision ID: 0004_structured_content_v2
Revises: 0003_processing_runs
Create Date: 2026-07-26 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_structured_content_v2"
down_revision = "0003_processing_runs"
branch_labels = None
depends_on = None


def _id_column():
    return sa.Column("id", sa.String(), nullable=False)


def _association(table: str, left_table: str, right_table: str, left_col: str, right_col: str) -> None:
    op.create_table(
        table,
        _id_column(),
        sa.Column(left_col, sa.String(), nullable=False),
        sa.Column(right_col, sa.String(), nullable=False),
        sa.Column("association_order", sa.Integer(), nullable=False),
        sa.CheckConstraint("association_order >= 0", name=f"ck_{table}_order_nonnegative"),
        sa.ForeignKeyConstraint([left_col], [f"{left_table}.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint([right_col], [f"{right_table}.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(left_col, right_col, name=f"uq_{table}_pair"),
        sa.UniqueConstraint(left_col, "association_order", name=f"uq_{table}_order"),
    )


def upgrade() -> None:
    op.create_table(
        "structured_content_v2_candidates",
        _id_column(),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("lineage_key", sa.String(length=255), nullable=False),
        sa.Column("schema_id", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("transformer_ref", sa.String(length=255)),
        sa.Column("transformation_policy_ref", sa.String(length=255)),
        sa.Column("processing_run_ref", sa.String(length=1024)),
        sa.Column("raw_result_ref", sa.String(length=1024)),
        sa.Column("structured_processing_result_ref", sa.String(length=1024)),
        sa.Column("recovery_state", sa.String(length=50), nullable=False),
        sa.Column("total_source_unit_count", sa.Integer(), nullable=False),
        sa.Column("complete_source_unit_count", sa.Integer(), nullable=False),
        sa.Column("degraded_source_unit_count", sa.Integer(), nullable=False),
        sa.Column("no_usable_source_unit_count", sa.Integer(), nullable=False),
        sa.Column("unavailable_source_unit_count", sa.Integer(), nullable=False),
        sa.Column("recovery_warning_ids_json", sa.Text()),
        sa.Column("recovery_policy_ref", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("candidate_id <> ''", name="ck_scv2_candidates_candidate_id_nonempty"),
        sa.CheckConstraint("lineage_key <> ''", name="ck_scv2_candidates_lineage_key_nonempty"),
        sa.CheckConstraint("schema_version = 2", name="ck_scv2_candidates_schema_version"),
        sa.CheckConstraint("total_source_unit_count >= 0", name="ck_scv2_candidates_total_nonnegative"),
        sa.CheckConstraint("complete_source_unit_count >= 0", name="ck_scv2_candidates_complete_nonnegative"),
        sa.CheckConstraint("degraded_source_unit_count >= 0", name="ck_scv2_candidates_degraded_nonnegative"),
        sa.CheckConstraint("no_usable_source_unit_count >= 0", name="ck_scv2_candidates_no_usable_nonnegative"),
        sa.CheckConstraint("unavailable_source_unit_count >= 0", name="ck_scv2_candidates_unavailable_nonnegative"),
        sa.CheckConstraint("total_source_unit_count = complete_source_unit_count + degraded_source_unit_count + no_usable_source_unit_count + unavailable_source_unit_count", name="ck_scv2_candidates_recovery_counts_balance"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", name="uq_scv2_candidates_candidate_id"),
        sa.UniqueConstraint("id", "document_id", name="uq_scv2_candidates_id_document"),
    )
    op.create_index("ix_scv2_candidates_document", "structured_content_v2_candidates", ["document_id", "candidate_id"])

    op.create_table(
        "structured_content_v2_source_units",
        _id_column(),
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("source_unit_id", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column("source_ref", sa.String(length=1024), nullable=False),
        sa.Column("recovery_state", sa.String(length=50), nullable=False),
        sa.Column("width", sa.Float()), sa.Column("height", sa.Float()), sa.Column("dimension_unit", sa.String(length=50)),
        sa.Column("rotation_degrees", sa.Float()),
        sa.Column("source_span_start", sa.Integer()), sa.Column("source_span_end", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()),
        sa.CheckConstraint("source_unit_id <> ''", name="ck_scv2_units_id_nonempty"),
        sa.CheckConstraint("kind IN ('physical_page','text_flow','html_section','ebook_spine_item','document_part','image_canvas','audio_segment','video_segment')", name="ck_scv2_units_kind_supported"),
        sa.CheckConstraint("source_order >= 0", name="ck_scv2_units_order_nonnegative"),
        sa.CheckConstraint("source_ref <> ''", name="ck_scv2_units_source_ref_nonempty"),
        sa.CheckConstraint("recovery_state IN ('complete','degraded','no_usable_semantic_content','unavailable')", name="ck_scv2_units_recovery_supported"),
        sa.CheckConstraint("width IS NULL OR width > 0", name="ck_scv2_units_width_positive"),
        sa.CheckConstraint("height IS NULL OR height > 0", name="ck_scv2_units_height_positive"),
        sa.CheckConstraint("rotation_degrees IS NULL OR (rotation_degrees >= 0 AND rotation_degrees < 360)", name="ck_scv2_units_rotation_range"),
        sa.CheckConstraint("source_span_start IS NULL OR source_span_start >= 0", name="ck_scv2_units_span_start_nonnegative"),
        sa.CheckConstraint("source_span_end IS NULL OR source_span_end >= source_span_start", name="ck_scv2_units_span_order"),
        sa.CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_scv2_units_duration_nonnegative"),
        sa.CheckConstraint("(kind IN ('physical_page','image_canvas') AND width IS NOT NULL AND height IS NOT NULL) OR kind NOT IN ('physical_page','image_canvas')", name="ck_scv2_units_spatial_dimensions"),
        sa.CheckConstraint("rotation_degrees IS NULL OR kind IN ('physical_page','image_canvas')", name="ck_scv2_units_rotation_spatial_only"),
        sa.CheckConstraint("(kind = 'text_flow' AND source_span_start IS NOT NULL AND source_span_end IS NOT NULL) OR kind <> 'text_flow'", name="ck_scv2_units_text_flow_span"),
        sa.CheckConstraint("(kind IN ('audio_segment','video_segment') AND duration_ms IS NOT NULL) OR (kind NOT IN ('audio_segment','video_segment') AND duration_ms IS NULL)", name="ck_scv2_units_temporal_duration"),
        sa.ForeignKeyConstraint(["candidate_id"], ["structured_content_v2_candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", "source_unit_id", name="uq_scv2_units_candidate_unit"),
        sa.UniqueConstraint("candidate_id", "source_order", name="uq_scv2_units_candidate_order"),
        sa.UniqueConstraint("id", "candidate_id", name="uq_scv2_units_id_candidate"),
    )
    op.create_index("ix_scv2_units_candidate_order", "structured_content_v2_source_units", ["candidate_id", "source_order", "source_unit_id"])

    op.create_table(
        "structured_content_v2_nodes",
        _id_column(), sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False), sa.Column("lineage_key", sa.String(length=255), nullable=False),
        sa.Column("node_type", sa.String(length=50), nullable=False), sa.Column("parent_node_record_id", sa.String()),
        sa.Column("sibling_order", sa.Integer(), nullable=False), sa.Column("recovery_state", sa.String(length=50), nullable=False),
        sa.Column("text", sa.Text()), sa.Column("heading_level", sa.Integer()), sa.Column("metadata_json", sa.Text()),
        sa.CheckConstraint("node_id <> ''", name="ck_scv2_nodes_id_nonempty"),
        sa.CheckConstraint("lineage_key <> ''", name="ck_scv2_nodes_lineage_nonempty"),
        sa.CheckConstraint("sibling_order >= 0", name="ck_scv2_nodes_sibling_order_nonnegative"),
        sa.CheckConstraint("heading_level IS NULL OR heading_level > 0", name="ck_scv2_nodes_heading_level_positive"),
        sa.ForeignKeyConstraint(["candidate_id"], ["structured_content_v2_candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_node_record_id", "candidate_id"], ["structured_content_v2_nodes.id", "structured_content_v2_nodes.candidate_id"], name="fk_scv2_nodes_parent_candidate", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("candidate_id", "node_id", name="uq_scv2_nodes_candidate_node"),
        sa.UniqueConstraint("id", "candidate_id", name="uq_scv2_nodes_id_candidate"),
    )
    op.create_index("ix_scv2_nodes_candidate_parent_order", "structured_content_v2_nodes", ["candidate_id", "parent_node_record_id", "sibling_order", "node_id"])

    op.create_table(
        "structured_content_v2_node_source_units", _id_column(),
        sa.Column("node_record_id", sa.String(), nullable=False), sa.Column("source_unit_record_id", sa.String(), nullable=False), sa.Column("association_order", sa.Integer(), nullable=False),
        sa.CheckConstraint("association_order >= 0", name="ck_scv2_node_units_order_nonnegative"),
        sa.ForeignKeyConstraint(["node_record_id"], ["structured_content_v2_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_unit_record_id"], ["structured_content_v2_source_units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("node_record_id", "source_unit_record_id", name="uq_scv2_node_units_pair"),
        sa.UniqueConstraint("node_record_id", "association_order", name="uq_scv2_node_units_order"),
    )

    op.create_table(
        "structured_content_v2_evidence", _id_column(), sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("evidence_id", sa.String(length=255), nullable=False), sa.Column("source_unit_record_id", sa.String()),
        sa.Column("processing_run_ref", sa.String(length=1024)), sa.Column("raw_result_ref", sa.String(length=1024)), sa.Column("structured_processing_result_ref", sa.String(length=1024)),
        sa.Column("spr_node_ref", sa.String(length=1024)), sa.Column("spr_observation_ref", sa.String(length=1024)), sa.Column("warning_ref", sa.String(length=1024)), sa.Column("metadata_json", sa.Text()),
        sa.ForeignKeyConstraint(["candidate_id"], ["structured_content_v2_candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_unit_record_id", "candidate_id"], ["structured_content_v2_source_units.id", "structured_content_v2_source_units.candidate_id"], name="fk_scv2_evidence_source_unit_candidate", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("candidate_id", "evidence_id", name="uq_scv2_evidence_candidate_evidence"), sa.UniqueConstraint("id", "candidate_id", name="uq_scv2_evidence_id_candidate"),
    )

    op.create_table(
        "structured_content_v2_warnings", _id_column(), sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("warning_id", sa.String(length=255), nullable=False), sa.Column("code", sa.String(length=255), nullable=False), sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("scope_ref", sa.String(length=1024), nullable=False), sa.Column("safe_summary", sa.Text(), nullable=False), sa.Column("recoverable", sa.Boolean(), nullable=False), sa.Column("details_json", sa.Text()),
        sa.ForeignKeyConstraint(["candidate_id"], ["structured_content_v2_candidates.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", "warning_id", name="uq_scv2_warnings_candidate_warning"),
    )

    op.create_table(
        "structured_content_v2_assets", _id_column(), sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("asset_id", sa.String(length=255), nullable=False), sa.Column("role", sa.String(length=50), nullable=False), sa.Column("recovery_state", sa.String(length=50), nullable=False),
        sa.Column("caption", sa.Text()), sa.Column("alt_text", sa.Text()), sa.Column("metadata_json", sa.Text()),
        sa.ForeignKeyConstraint(["candidate_id"], ["structured_content_v2_candidates.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", "asset_id", name="uq_scv2_assets_candidate_asset"),
    )

    op.create_table(
        "structured_content_v2_asset_source_units", _id_column(), sa.Column("asset_record_id", sa.String(), nullable=False), sa.Column("source_unit_record_id", sa.String(), nullable=False), sa.Column("association_order", sa.Integer(), nullable=False),
        sa.CheckConstraint("association_order >= 0", name="ck_scv2_asset_units_order_nonnegative"),
        sa.ForeignKeyConstraint(["asset_record_id"], ["structured_content_v2_assets.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["source_unit_record_id"], ["structured_content_v2_source_units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("asset_record_id", "source_unit_record_id", name="uq_scv2_asset_units_pair"), sa.UniqueConstraint("asset_record_id", "association_order", name="uq_scv2_asset_units_order"),
    )

    op.create_table(
        "structured_content_v2_asset_renditions", _id_column(), sa.Column("candidate_id", sa.String(), nullable=False), sa.Column("rendition_id", sa.String(length=255), nullable=False),
        sa.Column("asset_record_id", sa.String(), nullable=False), sa.Column("role", sa.String(length=50), nullable=False), sa.Column("artifact_ref", sa.String(length=1024), nullable=False),
        sa.Column("media_type", sa.String(length=255)), sa.Column("checksum", sa.String(length=255)), sa.Column("recovery_state", sa.String(length=50), nullable=False), sa.Column("rebuildable", sa.Boolean(), nullable=False),
        sa.CheckConstraint("artifact_ref NOT LIKE 'http://%' AND artifact_ref NOT LIKE 'https://%' AND artifact_ref NOT LIKE 'file://%'", name="ck_scv2_renditions_artifact_ref_durable"),
        sa.ForeignKeyConstraint(["candidate_id"], ["structured_content_v2_candidates.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["asset_record_id"], ["structured_content_v2_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("candidate_id", "rendition_id", name="uq_scv2_renditions_candidate_rendition"),
    )

    op.create_table(
        "structured_content_v2_anchors", _id_column(), sa.Column("candidate_id", sa.String(), nullable=False), sa.Column("source_unit_record_id", sa.String(), nullable=False),
        sa.Column("owner_type", sa.String(length=20), nullable=False), sa.Column("owner_record_id", sa.String(), nullable=False), sa.Column("anchor_order", sa.Integer(), nullable=False), sa.Column("anchor_kind", sa.String(length=20), nullable=False),
        sa.Column("bbox_left", sa.Float()), sa.Column("bbox_top", sa.Float()), sa.Column("bbox_right", sa.Float()), sa.Column("bbox_bottom", sa.Float()),
        sa.Column("text_start", sa.Integer()), sa.Column("text_end", sa.Integer()), sa.Column("start_ms", sa.Integer()), sa.Column("end_ms", sa.Integer()),
        sa.Column("dom_path", sa.String(length=2048)), sa.Column("dom_text_start", sa.Integer()), sa.Column("dom_text_end", sa.Integer()),
        sa.CheckConstraint("owner_type IN ('node','evidence','asset')", name="ck_scv2_anchors_owner_type_supported"),
        sa.CheckConstraint("anchor_kind IN ('spatial','text_span','temporal','dom')", name="ck_scv2_anchors_kind_supported"),
        sa.CheckConstraint("anchor_order >= 0", name="ck_scv2_anchors_order_nonnegative"),
        sa.CheckConstraint("(anchor_kind='spatial' AND bbox_left IS NOT NULL AND bbox_top IS NOT NULL AND bbox_right IS NOT NULL AND bbox_bottom IS NOT NULL AND bbox_left>=0 AND bbox_top>=0 AND bbox_right<=1 AND bbox_bottom<=1 AND bbox_left<bbox_right AND bbox_top<bbox_bottom AND text_start IS NULL AND text_end IS NULL AND start_ms IS NULL AND end_ms IS NULL AND dom_path IS NULL AND dom_text_start IS NULL AND dom_text_end IS NULL) OR (anchor_kind='text_span' AND text_start IS NOT NULL AND text_end IS NOT NULL AND text_start>=0 AND text_end>=text_start AND bbox_left IS NULL AND bbox_top IS NULL AND bbox_right IS NULL AND bbox_bottom IS NULL AND start_ms IS NULL AND end_ms IS NULL AND dom_path IS NULL AND dom_text_start IS NULL AND dom_text_end IS NULL) OR (anchor_kind='temporal' AND start_ms IS NOT NULL AND end_ms IS NOT NULL AND start_ms>=0 AND end_ms>=start_ms AND bbox_left IS NULL AND bbox_top IS NULL AND bbox_right IS NULL AND bbox_bottom IS NULL AND text_start IS NULL AND text_end IS NULL AND dom_path IS NULL AND dom_text_start IS NULL AND dom_text_end IS NULL) OR (anchor_kind='dom' AND dom_path IS NOT NULL AND dom_path<>'' AND bbox_left IS NULL AND bbox_top IS NULL AND bbox_right IS NULL AND bbox_bottom IS NULL AND text_start IS NULL AND text_end IS NULL AND start_ms IS NULL AND end_ms IS NULL AND ((dom_text_start IS NULL AND dom_text_end IS NULL) OR (dom_text_start IS NOT NULL AND dom_text_end IS NOT NULL AND dom_text_start>=0 AND dom_text_end>=dom_text_start)))", name="ck_scv2_anchors_typed_payload"),
        sa.ForeignKeyConstraint(["candidate_id"], ["structured_content_v2_candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_unit_record_id", "candidate_id"], ["structured_content_v2_source_units.id", "structured_content_v2_source_units.candidate_id"], name="fk_scv2_anchors_source_unit_candidate", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("candidate_id", "owner_type", "owner_record_id", "anchor_order", name="uq_scv2_anchors_owner_order"),
    )
    op.create_index("ix_scv2_anchors_owner", "structured_content_v2_anchors", ["candidate_id", "owner_type", "owner_record_id", "anchor_order"])

    _association("structured_content_v2_source_unit_evidence", "structured_content_v2_source_units", "structured_content_v2_evidence", "source_unit_record_id", "evidence_record_id")
    _association("structured_content_v2_source_unit_warnings", "structured_content_v2_source_units", "structured_content_v2_warnings", "source_unit_record_id", "warning_record_id")
    _association("structured_content_v2_node_evidence", "structured_content_v2_nodes", "structured_content_v2_evidence", "node_record_id", "evidence_record_id")
    _association("structured_content_v2_node_assets", "structured_content_v2_nodes", "structured_content_v2_assets", "node_record_id", "asset_record_id")
    _association("structured_content_v2_node_warnings", "structured_content_v2_nodes", "structured_content_v2_warnings", "node_record_id", "warning_record_id")
    _association("structured_content_v2_asset_evidence", "structured_content_v2_assets", "structured_content_v2_evidence", "asset_record_id", "evidence_record_id")
    _association("structured_content_v2_warning_evidence", "structured_content_v2_warnings", "structured_content_v2_evidence", "warning_record_id", "evidence_record_id")


def downgrade() -> None:
    for table in (
        "structured_content_v2_warning_evidence", "structured_content_v2_asset_evidence", "structured_content_v2_node_warnings", "structured_content_v2_node_assets", "structured_content_v2_node_evidence", "structured_content_v2_source_unit_warnings", "structured_content_v2_source_unit_evidence",
    ):
        op.drop_table(table)
    op.drop_index("ix_scv2_anchors_owner", table_name="structured_content_v2_anchors")
    op.drop_table("structured_content_v2_anchors")
    op.drop_table("structured_content_v2_asset_renditions")
    op.drop_table("structured_content_v2_asset_source_units")
    op.drop_table("structured_content_v2_assets")
    op.drop_table("structured_content_v2_warnings")
    op.drop_table("structured_content_v2_evidence")
    op.drop_table("structured_content_v2_node_source_units")
    op.drop_index("ix_scv2_nodes_candidate_parent_order", table_name="structured_content_v2_nodes")
    op.drop_table("structured_content_v2_nodes")
    op.drop_index("ix_scv2_units_candidate_order", table_name="structured_content_v2_source_units")
    op.drop_table("structured_content_v2_source_units")
    op.drop_index("ix_scv2_candidates_document", table_name="structured_content_v2_candidates")
    op.drop_table("structured_content_v2_candidates")
