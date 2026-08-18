"""Schema-only ORM records for source-unit-centric Structured Content v2."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint

from app.models import Base


def _id() -> str:
    return str(uuid.uuid4())


SOURCE_UNIT_KINDS = "'physical_page','text_flow','html_section','ebook_spine_item','document_part','image_canvas','audio_segment','video_segment'"
SOURCE_UNIT_RECOVERY = "'complete','degraded','no_usable_semantic_content','unavailable'"


class StructuredContentCandidateV2Record(Base):
    __tablename__ = "structured_content_v2_candidates"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_scv2_candidates_candidate_id"),
        UniqueConstraint("id", "document_id", name="uq_scv2_candidates_id_document"),
        CheckConstraint("candidate_id <> ''", name="ck_scv2_candidates_candidate_id_nonempty"),
        CheckConstraint("lineage_key <> ''", name="ck_scv2_candidates_lineage_key_nonempty"),
        CheckConstraint("schema_version = 2", name="ck_scv2_candidates_schema_version"),
        CheckConstraint("total_source_unit_count >= 0", name="ck_scv2_candidates_total_nonnegative"),
        CheckConstraint("complete_source_unit_count >= 0", name="ck_scv2_candidates_complete_nonnegative"),
        CheckConstraint("degraded_source_unit_count >= 0", name="ck_scv2_candidates_degraded_nonnegative"),
        CheckConstraint("no_usable_source_unit_count >= 0", name="ck_scv2_candidates_no_usable_nonnegative"),
        CheckConstraint("unavailable_source_unit_count >= 0", name="ck_scv2_candidates_unavailable_nonnegative"),
        CheckConstraint(
            "total_source_unit_count = complete_source_unit_count + degraded_source_unit_count + no_usable_source_unit_count + unavailable_source_unit_count",
            name="ck_scv2_candidates_recovery_counts_balance",
        ),
        Index("ix_scv2_candidates_document", "document_id", "candidate_id"),
    )
    id = Column(String, primary_key=True, default=_id)
    candidate_id = Column(String(255), nullable=False)
    document_id = Column(String, ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    lineage_key = Column(String(255), nullable=False)
    schema_id = Column(String(255), nullable=False)
    schema_version = Column(Integer, nullable=False, default=2)
    transformer_ref = Column(String(255))
    transformation_policy_ref = Column(String(255))
    processing_run_ref = Column(String(1024))
    raw_result_ref = Column(String(1024))
    structured_processing_result_ref = Column(String(1024))
    recovery_state = Column(String(50), nullable=False)
    total_source_unit_count = Column(Integer, nullable=False, default=0)
    complete_source_unit_count = Column(Integer, nullable=False, default=0)
    degraded_source_unit_count = Column(Integer, nullable=False, default=0)
    no_usable_source_unit_count = Column(Integer, nullable=False, default=0)
    unavailable_source_unit_count = Column(Integer, nullable=False, default=0)
    recovery_warning_ids_json = Column(Text)
    recovery_policy_ref = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class StructuredContentSourceUnitV2Record(Base):
    __tablename__ = "structured_content_v2_source_units"
    __table_args__ = (
        UniqueConstraint("candidate_id", "source_unit_id", name="uq_scv2_units_candidate_unit"),
        UniqueConstraint("candidate_id", "source_order", name="uq_scv2_units_candidate_order"),
        UniqueConstraint("id", "candidate_id", name="uq_scv2_units_id_candidate"),
        CheckConstraint("source_unit_id <> ''", name="ck_scv2_units_id_nonempty"),
        CheckConstraint(f"kind IN ({SOURCE_UNIT_KINDS})", name="ck_scv2_units_kind_supported"),
        CheckConstraint("source_order >= 0", name="ck_scv2_units_order_nonnegative"),
        CheckConstraint("source_ref <> ''", name="ck_scv2_units_source_ref_nonempty"),
        CheckConstraint(f"recovery_state IN ({SOURCE_UNIT_RECOVERY})", name="ck_scv2_units_recovery_supported"),
        CheckConstraint("width IS NULL OR width > 0", name="ck_scv2_units_width_positive"),
        CheckConstraint("height IS NULL OR height > 0", name="ck_scv2_units_height_positive"),
        CheckConstraint("rotation_degrees IS NULL OR (rotation_degrees >= 0 AND rotation_degrees < 360)", name="ck_scv2_units_rotation_range"),
        CheckConstraint("source_span_start IS NULL OR source_span_start >= 0", name="ck_scv2_units_span_start_nonnegative"),
        CheckConstraint("source_span_end IS NULL OR source_span_end >= source_span_start", name="ck_scv2_units_span_order"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_scv2_units_duration_nonnegative"),
        CheckConstraint("(kind IN ('physical_page','image_canvas') AND width IS NOT NULL AND height IS NOT NULL) OR kind NOT IN ('physical_page','image_canvas')", name="ck_scv2_units_spatial_dimensions"),
        CheckConstraint("rotation_degrees IS NULL OR kind IN ('physical_page','image_canvas')", name="ck_scv2_units_rotation_spatial_only"),
        CheckConstraint("(kind = 'text_flow' AND source_span_start IS NOT NULL AND source_span_end IS NOT NULL) OR kind <> 'text_flow'", name="ck_scv2_units_text_flow_span"),
        CheckConstraint("(kind IN ('audio_segment','video_segment') AND duration_ms IS NOT NULL) OR (kind NOT IN ('audio_segment','video_segment') AND duration_ms IS NULL)", name="ck_scv2_units_temporal_duration"),
        Index("ix_scv2_units_candidate_order", "candidate_id", "source_order", "source_unit_id"),
    )
    id = Column(String, primary_key=True, default=_id)
    candidate_id = Column(String, ForeignKey("structured_content_v2_candidates.id", ondelete="CASCADE"), nullable=False)
    source_unit_id = Column(String(255), nullable=False)
    kind = Column(String(50), nullable=False)
    source_order = Column(Integer, nullable=False)
    source_ref = Column(String(1024), nullable=False)
    recovery_state = Column(String(50), nullable=False)
    width = Column(Float)
    height = Column(Float)
    dimension_unit = Column(String(50))
    rotation_degrees = Column(Float)
    source_span_start = Column(Integer)
    source_span_end = Column(Integer)
    duration_ms = Column(Integer)


class StructuredContentNodeV2Record(Base):
    __tablename__ = "structured_content_v2_nodes"
    __table_args__ = (
        UniqueConstraint("candidate_id", "node_id", name="uq_scv2_nodes_candidate_node"),
        UniqueConstraint("id", "candidate_id", name="uq_scv2_nodes_id_candidate"),
        CheckConstraint("node_id <> ''", name="ck_scv2_nodes_id_nonempty"),
        CheckConstraint("lineage_key <> ''", name="ck_scv2_nodes_lineage_nonempty"),
        CheckConstraint("sibling_order >= 0", name="ck_scv2_nodes_sibling_order_nonnegative"),
        CheckConstraint("heading_level IS NULL OR heading_level > 0", name="ck_scv2_nodes_heading_level_positive"),
        ForeignKeyConstraint(["parent_node_record_id", "candidate_id"], ["structured_content_v2_nodes.id", "structured_content_v2_nodes.candidate_id"], name="fk_scv2_nodes_parent_candidate", ondelete="RESTRICT"),
        Index("ix_scv2_nodes_candidate_parent_order", "candidate_id", "parent_node_record_id", "sibling_order", "node_id"),
    )
    id = Column(String, primary_key=True, default=_id)
    candidate_id = Column(String, ForeignKey("structured_content_v2_candidates.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(String(255), nullable=False)
    lineage_key = Column(String(255), nullable=False)
    node_type = Column(String(50), nullable=False)
    parent_node_record_id = Column(String)
    sibling_order = Column(Integer, nullable=False)
    recovery_state = Column(String(50), nullable=False)
    text = Column(Text)
    heading_level = Column(Integer)
    metadata_json = Column(Text)


class StructuredContentNodeSourceUnitV2Record(Base):
    __tablename__ = "structured_content_v2_node_source_units"
    __table_args__ = (
        UniqueConstraint("node_record_id", "source_unit_record_id", name="uq_scv2_node_units_pair"),
        UniqueConstraint("node_record_id", "association_order", name="uq_scv2_node_units_order"),
        CheckConstraint("association_order >= 0", name="ck_scv2_node_units_order_nonnegative"),
    )
    id = Column(String, primary_key=True, default=_id)
    node_record_id = Column(String, ForeignKey("structured_content_v2_nodes.id", ondelete="CASCADE"), nullable=False)
    source_unit_record_id = Column(String, ForeignKey("structured_content_v2_source_units.id", ondelete="CASCADE"), nullable=False)
    association_order = Column(Integer, nullable=False)


class StructuredContentEvidenceV2Record(Base):
    __tablename__ = "structured_content_v2_evidence"
    __table_args__ = (
        UniqueConstraint("candidate_id", "evidence_id", name="uq_scv2_evidence_candidate_evidence"),
        UniqueConstraint("id", "candidate_id", name="uq_scv2_evidence_id_candidate"),
        ForeignKeyConstraint(["source_unit_record_id", "candidate_id"], ["structured_content_v2_source_units.id", "structured_content_v2_source_units.candidate_id"], name="fk_scv2_evidence_source_unit_candidate", ondelete="RESTRICT"),
    )
    id = Column(String, primary_key=True, default=_id)
    candidate_id = Column(String, ForeignKey("structured_content_v2_candidates.id", ondelete="CASCADE"), nullable=False)
    evidence_id = Column(String(255), nullable=False)
    source_unit_record_id = Column(String)
    processing_run_ref = Column(String(1024))
    raw_result_ref = Column(String(1024))
    structured_processing_result_ref = Column(String(1024))
    spr_node_ref = Column(String(1024))
    spr_observation_ref = Column(String(1024))
    warning_ref = Column(String(1024))
    metadata_json = Column(Text)


class StructuredContentWarningV2Record(Base):
    __tablename__ = "structured_content_v2_warnings"
    __table_args__ = (UniqueConstraint("candidate_id", "warning_id", name="uq_scv2_warnings_candidate_warning"),)
    id = Column(String, primary_key=True, default=_id)
    candidate_id = Column(String, ForeignKey("structured_content_v2_candidates.id", ondelete="CASCADE"), nullable=False)
    warning_id = Column(String(255), nullable=False)
    code = Column(String(255), nullable=False)
    severity = Column(String(50), nullable=False)
    scope_ref = Column(String(1024), nullable=False)
    safe_summary = Column(Text, nullable=False)
    recoverable = Column(Boolean, nullable=False, default=True)
    details_json = Column(Text)


class StructuredContentAssetV2Record(Base):
    __tablename__ = "structured_content_v2_assets"
    __table_args__ = (UniqueConstraint("candidate_id", "asset_id", name="uq_scv2_assets_candidate_asset"),)
    id = Column(String, primary_key=True, default=_id)
    candidate_id = Column(String, ForeignKey("structured_content_v2_candidates.id", ondelete="CASCADE"), nullable=False)
    asset_id = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)
    recovery_state = Column(String(50), nullable=False)
    caption = Column(Text)
    alt_text = Column(Text)
    metadata_json = Column(Text)


class StructuredContentAssetSourceUnitV2Record(Base):
    __tablename__ = "structured_content_v2_asset_source_units"
    __table_args__ = (
        UniqueConstraint("asset_record_id", "source_unit_record_id", name="uq_scv2_asset_units_pair"),
        UniqueConstraint("asset_record_id", "association_order", name="uq_scv2_asset_units_order"),
        CheckConstraint("association_order >= 0", name="ck_scv2_asset_units_order_nonnegative"),
    )
    id = Column(String, primary_key=True, default=_id)
    asset_record_id = Column(String, ForeignKey("structured_content_v2_assets.id", ondelete="CASCADE"), nullable=False)
    source_unit_record_id = Column(String, ForeignKey("structured_content_v2_source_units.id", ondelete="CASCADE"), nullable=False)
    association_order = Column(Integer, nullable=False)


class StructuredContentAssetRenditionV2Record(Base):
    __tablename__ = "structured_content_v2_asset_renditions"
    __table_args__ = (
        UniqueConstraint("candidate_id", "rendition_id", name="uq_scv2_renditions_candidate_rendition"),
        CheckConstraint("artifact_ref NOT LIKE 'http://%' AND artifact_ref NOT LIKE 'https://%' AND artifact_ref NOT LIKE 'file://%'", name="ck_scv2_renditions_artifact_ref_durable"),
    )
    id = Column(String, primary_key=True, default=_id)
    candidate_id = Column(String, ForeignKey("structured_content_v2_candidates.id", ondelete="CASCADE"), nullable=False)
    rendition_id = Column(String(255), nullable=False)
    asset_record_id = Column(String, ForeignKey("structured_content_v2_assets.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(50), nullable=False)
    artifact_ref = Column(String(1024), nullable=False)
    media_type = Column(String(255))
    checksum = Column(String(255))
    recovery_state = Column(String(50), nullable=False)
    rebuildable = Column(Boolean, nullable=False, default=False)


class StructuredContentAnchorV2Record(Base):
    __tablename__ = "structured_content_v2_anchors"
    __table_args__ = (
        UniqueConstraint("candidate_id", "owner_type", "owner_record_id", "anchor_order", name="uq_scv2_anchors_owner_order"),
        CheckConstraint("owner_type IN ('node','evidence','asset')", name="ck_scv2_anchors_owner_type_supported"),
        CheckConstraint("anchor_kind IN ('spatial','text_span','temporal','dom')", name="ck_scv2_anchors_kind_supported"),
        CheckConstraint("anchor_order >= 0", name="ck_scv2_anchors_order_nonnegative"),
        CheckConstraint(
            "(anchor_kind='spatial' AND bbox_left IS NOT NULL AND bbox_top IS NOT NULL AND bbox_right IS NOT NULL AND bbox_bottom IS NOT NULL AND bbox_left>=0 AND bbox_top>=0 AND bbox_right<=1 AND bbox_bottom<=1 AND bbox_left<bbox_right AND bbox_top<bbox_bottom AND text_start IS NULL AND text_end IS NULL AND start_ms IS NULL AND end_ms IS NULL AND dom_path IS NULL AND dom_text_start IS NULL AND dom_text_end IS NULL) OR "
            "(anchor_kind='text_span' AND text_start IS NOT NULL AND text_end IS NOT NULL AND text_start>=0 AND text_end>=text_start AND bbox_left IS NULL AND bbox_top IS NULL AND bbox_right IS NULL AND bbox_bottom IS NULL AND start_ms IS NULL AND end_ms IS NULL AND dom_path IS NULL AND dom_text_start IS NULL AND dom_text_end IS NULL) OR "
            "(anchor_kind='temporal' AND start_ms IS NOT NULL AND end_ms IS NOT NULL AND start_ms>=0 AND end_ms>=start_ms AND bbox_left IS NULL AND bbox_top IS NULL AND bbox_right IS NULL AND bbox_bottom IS NULL AND text_start IS NULL AND text_end IS NULL AND dom_path IS NULL AND dom_text_start IS NULL AND dom_text_end IS NULL) OR "
            "(anchor_kind='dom' AND dom_path IS NOT NULL AND dom_path<>'' AND bbox_left IS NULL AND bbox_top IS NULL AND bbox_right IS NULL AND bbox_bottom IS NULL AND text_start IS NULL AND text_end IS NULL AND start_ms IS NULL AND end_ms IS NULL AND ((dom_text_start IS NULL AND dom_text_end IS NULL) OR (dom_text_start IS NOT NULL AND dom_text_end IS NOT NULL AND dom_text_start>=0 AND dom_text_end>=dom_text_start)))",
            name="ck_scv2_anchors_typed_payload",
        ),
        ForeignKeyConstraint(["source_unit_record_id", "candidate_id"], ["structured_content_v2_source_units.id", "structured_content_v2_source_units.candidate_id"], name="fk_scv2_anchors_source_unit_candidate", ondelete="RESTRICT"),
        Index("ix_scv2_anchors_owner", "candidate_id", "owner_type", "owner_record_id", "anchor_order"),
    )
    id = Column(String, primary_key=True, default=_id)
    candidate_id = Column(String, ForeignKey("structured_content_v2_candidates.id", ondelete="CASCADE"), nullable=False)
    source_unit_record_id = Column(String, nullable=False)
    owner_type = Column(String(20), nullable=False)
    owner_record_id = Column(String, nullable=False)
    anchor_order = Column(Integer, nullable=False)
    anchor_kind = Column(String(20), nullable=False)
    bbox_left = Column(Float); bbox_top = Column(Float); bbox_right = Column(Float); bbox_bottom = Column(Float)
    text_start = Column(Integer); text_end = Column(Integer)
    start_ms = Column(Integer); end_ms = Column(Integer)
    dom_path = Column(String(2048)); dom_text_start = Column(Integer); dom_text_end = Column(Integer)


def _association(name: str, table: str, left_table: str, right_table: str, left_col: str, right_col: str):
    return type(name, (Base,), {
        "__tablename__": table,
        "__table_args__": (
            UniqueConstraint(left_col, right_col, name=f"uq_{table}_pair"),
            UniqueConstraint(left_col, "association_order", name=f"uq_{table}_order"),
            CheckConstraint("association_order >= 0", name=f"ck_{table}_order_nonnegative"),
        ),
        "id": Column(String, primary_key=True, default=_id),
        left_col: Column(String, ForeignKey(f"{left_table}.id", ondelete="CASCADE"), nullable=False),
        right_col: Column(String, ForeignKey(f"{right_table}.id", ondelete="CASCADE"), nullable=False),
        "association_order": Column(Integer, nullable=False),
    })


StructuredContentSourceUnitEvidenceV2Record = _association("StructuredContentSourceUnitEvidenceV2Record", "structured_content_v2_source_unit_evidence", "structured_content_v2_source_units", "structured_content_v2_evidence", "source_unit_record_id", "evidence_record_id")
StructuredContentSourceUnitWarningV2Record = _association("StructuredContentSourceUnitWarningV2Record", "structured_content_v2_source_unit_warnings", "structured_content_v2_source_units", "structured_content_v2_warnings", "source_unit_record_id", "warning_record_id")
StructuredContentNodeEvidenceV2Record = _association("StructuredContentNodeEvidenceV2Record", "structured_content_v2_node_evidence", "structured_content_v2_nodes", "structured_content_v2_evidence", "node_record_id", "evidence_record_id")
StructuredContentNodeAssetV2Record = _association("StructuredContentNodeAssetV2Record", "structured_content_v2_node_assets", "structured_content_v2_nodes", "structured_content_v2_assets", "node_record_id", "asset_record_id")
StructuredContentNodeWarningV2Record = _association("StructuredContentNodeWarningV2Record", "structured_content_v2_node_warnings", "structured_content_v2_nodes", "structured_content_v2_warnings", "node_record_id", "warning_record_id")
StructuredContentAssetEvidenceV2Record = _association("StructuredContentAssetEvidenceV2Record", "structured_content_v2_asset_evidence", "structured_content_v2_assets", "structured_content_v2_evidence", "asset_record_id", "evidence_record_id")
StructuredContentWarningEvidenceV2Record = _association("StructuredContentWarningEvidenceV2Record", "structured_content_v2_warning_evidence", "structured_content_v2_warnings", "structured_content_v2_evidence", "warning_record_id", "evidence_record_id")
