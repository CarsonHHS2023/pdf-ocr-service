"""数据库模型"""
from sqlalchemy import Column, String, DateTime, Text, Integer, Enum, LargeBinary, ForeignKey, Date, Float, Boolean, CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, synonym, validates
from datetime import datetime
import enum
import uuid

Base = declarative_base()

class TaskStatus(str, enum.Enum):
    """任务状态"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class OCRTask(Base):
    """OCR任务"""
    __tablename__ = "ocr_tasks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String, nullable=False)
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    result_text = Column(Text, nullable=True)  # OCR 提取的文本
    error_message = Column(String, nullable=True)  # 错误信息
    pages_count = Column(Integer, nullable=True)  # PDF 页数


class DocumentType(str, enum.Enum):
    """Controlled document type machine values stored as lowercase strings."""

    BOOK = "book"
    RECEIPT = "receipt"
    INVOICE = "invoice"
    CONTRACT = "contract"
    NOTE = "note"
    PICTURE = "picture"
    AUDIO = "audio"
    VIDEO = "video"
    EMAIL = "email"
    WEBPAGE = "webpage"
    OTHER = "other"


def validate_document_type(value: str | DocumentType) -> str:
    """Return a valid lowercase document type or raise ValueError."""
    if isinstance(value, DocumentType):
        return value.value
    normalized = str(value).lower()
    valid_values = {item.value for item in DocumentType}
    if normalized not in valid_values:
        raise ValueError(f"Invalid document_type: {value}")
    return normalized


class Document(Base):
    """Authoritative business aggregate root for uploaded documents."""
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_type = Column(String(50), default=DocumentType.BOOK.value, nullable=False)
    title = Column(String(255), nullable=False)
    author = Column(String(255), nullable=True)
    publication_date = Column(Date, nullable=True)
    pages_count = Column(Integer, nullable=True)
    file_type = Column(String(10), nullable=False)
    processed_file_path = Column(String(1024), nullable=True)
    original_file_path = Column(String(1024), nullable=True)
    status = Column(String(50), default="processing", nullable=False)
    error_message = Column(Text, nullable=True)
    language = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    source_files = relationship("SourceFile", back_populates="document", cascade="all, delete-orphan")
    content_blocks = relationship("ContentBlock", back_populates="document", cascade="all, delete-orphan")
    images = relationship("BookImage", back_populates="document", cascade="all, delete-orphan")
    pages = relationship("PdfPage", back_populates="document", cascade="all, delete-orphan")
    mineru_result = relationship("MineruResult", back_populates="document", cascade="all, delete-orphan", uselist=False)
    processing_runs = relationship("ProcessingRun", back_populates="document", passive_deletes=True)

    @validates("document_type")
    def _validate_document_type(self, key: str, value: str | DocumentType) -> str:
        return validate_document_type(value)

    @property
    def book_title(self) -> str:
        return self.title

    @book_title.setter
    def book_title(self, value: str) -> None:
        self.title = value


class SourceFile(Base):
    """Immutable source evidence metadata for a Document."""
    __tablename__ = "source_files"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_type = Column(String(10), nullable=False)
    mime_type = Column(String(255), nullable=True)
    byte_size = Column(Integer, nullable=True)
    checksum_sha256 = Column(String(64), nullable=True)
    storage_reference = Column(String(1024), nullable=True)
    retained = Column(Integer, default=0, nullable=False)
    is_primary = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    document = relationship("Document", back_populates="source_files")


# Compatibility alias for legacy type hints only; no bookshelf table is mapped.
Bookshelf = Document


class ContentBlock(Base):
    """内容块表 - 存储提取的文本或图片引用"""
    __tablename__ = "content_blocks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    book_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_num = Column(Integer, nullable=False)  # 页码
    block_index = Column(Integer, nullable=False)  # 块索引
    block_type = Column(String(50), nullable=False)  # "text", "image", "table"
    content = Column(Text, nullable=True)  # 文本内容或图片 ID
    bbox = Column(Text, nullable=True)  # 坐标 "x1,y1,x2,y2"
    confidence = Column(Float, default=1.0, nullable=False)  # 置信度
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # 关系
    document = relationship("Document", back_populates="content_blocks")
    book = synonym("document")


class BookImage(Base):
    """书籍中的图表表"""
    __tablename__ = "book_images"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    book_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    image_id = Column(String(255), unique=True, nullable=False)  # img_hash_16chars
    image_format = Column(String(10), default='png', nullable=False)  # 图片格式
    image_data = Column(LargeBinary, nullable=False)  # 图片二进制数据
    image_size = Column(Integer, nullable=True)  # 图片大小（字节）
    page_num = Column(Integer, nullable=True)  # 原 PDF 页码
    bbox = Column(Text, nullable=True)  # 坐标 "x1,y1,x2,y2"
    block_type = Column(String(50), nullable=True)  # "image" 或 "table"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # 关系
    document = relationship("Document", back_populates="images")
    book = synonym("document")


class PdfPage(Base):
    """PDF页面表 - 每页单独存储渲染图像及OCR结果"""
    __tablename__ = "pdf_pages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    book_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_num = Column(Integer, nullable=False)          # 1-based页码
    status = Column(String(20), default="pending", nullable=False)  # pending/processing/completed/failed
    page_image_data = Column(LargeBinary, nullable=True)  # PyMuPDF渲染的PNG页面图像
    page_width = Column(Integer, nullable=True)           # 渲染后的像素宽度
    page_height = Column(Integer, nullable=True)          # 渲染后的像素高度
    # PaddleOCR-VL predict() 返回的 parsing_res_list JSON字符串
    # 格式: {"page_num": N, "page_width": W, "page_height": H, "parsing_res_list": [...]}
    ocr_raw_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    document = relationship("Document", back_populates="pages")
    book = synonym("document")


class MineruResult(Base):
    """MinerU-Popo后处理结果表 - 存储跨页恢复后的结构化文档"""
    __tablename__ = "mineru_results"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    book_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True)
    status = Column(String(20), default="pending", nullable=False)  # pending/processing/completed/failed
    # 后处理结果JSON: [{"type": "title"|"text"|"image"|"table", "content": str,
    #                   "image_id": str, "level": int, "page_num": int}, ...]
    result_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    document = relationship("Document", back_populates="mineru_result")
    book = synonym("document")



class ProcessingRun(Base):
    """Durable provider-independent processing execution provenance.

    ProcessingRun stores run identity and artifact references only; it is not
    canonical content, selection state, Reader state, or workflow queue truth.
    """
    __tablename__ = "processing_runs"
    __table_args__ = (
        UniqueConstraint("processing_run_id", name="uq_processing_runs_processing_run_id"),
        UniqueConstraint("document_id", "idempotency_key", name="uq_processing_runs_document_idempotency_key"),
        CheckConstraint("processing_run_id <> ''", name="ck_processing_runs_run_id_nonempty"),
        CheckConstraint("status IN ('created','running','succeeded','failed','cancelled')", name="ck_processing_runs_status_supported"),
        CheckConstraint("idempotency_key IS NULL OR idempotency_key <> ''", name="ck_processing_runs_idempotency_key_nonempty"),
        Index("ix_processing_runs_document_created", "document_id", "created_at", "processing_run_id"),
        Index("ix_processing_runs_source_file_id", "source_file_id"),
        Index("ix_processing_runs_raw_result_ref", "raw_result_ref"),
        Index("ix_processing_runs_spr_ref", "structured_processing_result_ref"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    processing_run_id = Column(String(255), nullable=False)
    document_id = Column(String, ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    source_file_id = Column(String, ForeignKey("source_files.id", ondelete="RESTRICT"), nullable=True)
    status = Column(String(50), default="created", nullable=False)
    provider_ref = Column(String(255), nullable=True)
    provider_model_ref = Column(String(255), nullable=True)
    processing_policy_ref = Column(String(255), nullable=True)
    idempotency_key = Column(String(255), nullable=True)
    raw_result_ref = Column(String(1024), nullable=True)
    structured_processing_result_ref = Column(String(1024), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    safe_error_code = Column(String(255), nullable=True)
    safe_error_summary = Column(Text, nullable=True)
    metrics_json = Column(Text, nullable=True)
    extensions_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    document = relationship("Document", back_populates="processing_runs")
    source_file = relationship("SourceFile")


# M4 Slice 2A Structured Content persistence records.
# These ORM rows are schema/navigation records only. Candidate graph immutability is
# an application/repository boundary for Slice 2B; Slice 2A intentionally exposes
# no update/delete/selection service and candidate insertion never auto-selects.
import json



def encode_json_text(value):
    """Encode JSON-compatible values deterministically for Text columns."""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def decode_json_text(value):
    """Decode a Text-backed JSON value, returning ordinary JSON-compatible data."""
    if value is None:
        return None
    return json.loads(value)


class StructuredContentCandidate(Base):
    __tablename__ = "structured_content_candidates"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_sc_candidates_candidate_id"),
        UniqueConstraint("document_id", "candidate_id", name="uq_sc_candidates_document_candidate"),
        UniqueConstraint("id", "document_id", name="uq_sc_candidates_id_document"),
        CheckConstraint("candidate_id <> ''", name="ck_sc_candidates_candidate_id_nonempty"),
        CheckConstraint("lineage_key <> ''", name="ck_sc_candidates_lineage_key_nonempty"),
        CheckConstraint("schema_version >= 0", name="ck_sc_candidates_schema_version_nonnegative"),
        CheckConstraint("total_page_count >= 0", name="ck_sc_candidates_total_pages_nonnegative"),
        CheckConstraint("complete_page_count >= 0", name="ck_sc_candidates_complete_pages_nonnegative"),
        CheckConstraint("degraded_page_count >= 0", name="ck_sc_candidates_degraded_pages_nonnegative"),
        CheckConstraint("no_usable_page_count >= 0", name="ck_sc_candidates_no_usable_pages_nonnegative"),
        CheckConstraint("unavailable_page_count >= 0", name="ck_sc_candidates_unavailable_pages_nonnegative"),
        CheckConstraint("unsupported_page_count >= 0", name="ck_sc_candidates_unsupported_pages_nonnegative"),
        Index("ix_sc_candidates_document_id", "document_id"),
        Index("ix_sc_candidates_lineage_key", "lineage_key"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id = Column(String(255), nullable=False)
    document_id = Column(String, ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    lineage_key = Column(String(255), nullable=False)
    schema_id = Column(String(255), nullable=False)
    schema_version = Column(Integer, nullable=False)
    source_file_ref = Column(String(1024), nullable=True)
    processing_run_ref = Column(String(1024), nullable=True)
    raw_result_ref = Column(String(1024), nullable=True)
    structured_processing_result_ref = Column(String(1024), nullable=True)
    transformer_ref = Column(String(255), nullable=True)
    transformation_policy_ref = Column(String(255), nullable=True)
    recovery_state = Column(String(50), nullable=False)
    total_page_count = Column(Integer, nullable=False, default=0)
    complete_page_count = Column(Integer, nullable=False, default=0)
    degraded_page_count = Column(Integer, nullable=False, default=0)
    no_usable_page_count = Column(Integer, nullable=False, default=0)
    unavailable_page_count = Column(Integer, nullable=False, default=0)
    unsupported_page_count = Column(Integer, nullable=False, default=0)
    extensions_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    document = relationship("Document", back_populates="structured_content_candidates")
    pages = relationship("StructuredContentPage", back_populates="candidate")
    nodes = relationship("StructuredContentNode", back_populates="candidate")
    evidence = relationship("StructuredContentEvidence", back_populates="candidate")
    warnings = relationship("StructuredContentWarning", back_populates="candidate")
    assets = relationship("StructuredContentAsset", back_populates="candidate")
    selection = relationship("StructuredContentSelection", back_populates="candidate", uselist=False)


Document.structured_content_candidates = relationship("StructuredContentCandidate", back_populates="document", passive_deletes=True)


class StructuredContentPage(Base):
    __tablename__ = "structured_content_pages"
    __table_args__ = (
        UniqueConstraint("candidate_id", "page_id", name="uq_sc_pages_candidate_page_id"),
        UniqueConstraint("candidate_id", "page_order", name="uq_sc_pages_candidate_page_order"),
        UniqueConstraint("id", "candidate_id", name="uq_sc_pages_id_candidate"),
        CheckConstraint("page_order >= 0", name="ck_sc_pages_page_order_nonnegative"),
        CheckConstraint("source_page_index >= 0", name="ck_sc_pages_source_page_index_nonnegative"),
        Index("ix_sc_pages_candidate_order", "candidate_id", "page_order"),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id = Column(String, ForeignKey("structured_content_candidates.id", ondelete="CASCADE"), nullable=False)
    page_id = Column(String(255), nullable=False)
    page_order = Column(Integer, nullable=False)
    source_page_index = Column(Integer, nullable=False)
    recovery_state = Column(String(50), nullable=False)
    page_label = Column(String(255), nullable=True)
    width = Column(Float, nullable=True); height = Column(Float, nullable=True); dimension_unit = Column(String(50), nullable=True)
    coordinate_origin = Column(String(50), nullable=True); coordinate_unit = Column(String(50), nullable=True); rotation_applied = Column(Boolean, nullable=True)
    rotation_degrees = Column(Float, nullable=True)
    extensions_json = Column(Text, nullable=True)
    candidate = relationship("StructuredContentCandidate", back_populates="pages")
    nodes = relationship("StructuredContentNode", back_populates="page")
    roots = relationship("StructuredContentPageRoot", back_populates="page", order_by="StructuredContentPageRoot.root_order")


class StructuredContentNode(Base):
    __tablename__ = "structured_content_nodes"
    __table_args__ = (
        UniqueConstraint("candidate_id", "node_id", name="uq_sc_nodes_candidate_node_id"),
        UniqueConstraint("id", "candidate_id", name="uq_sc_nodes_id_candidate"),
        CheckConstraint("sibling_order >= 0", name="ck_sc_nodes_sibling_order_nonnegative"),
        CheckConstraint("attribute_type IS NULL OR attribute_type IN ('heading','list','list_item','table','figure','caption','formula')", name="ck_sc_nodes_attribute_type_supported"),
        ForeignKeyConstraint(["page_id", "candidate_id"], ["structured_content_pages.id", "structured_content_pages.candidate_id"], name="fk_sc_nodes_page_candidate", ondelete="CASCADE"),
        ForeignKeyConstraint(["parent_node_id", "candidate_id"], ["structured_content_nodes.id", "structured_content_nodes.candidate_id"], name="fk_sc_nodes_parent_candidate", ondelete="RESTRICT"),
        Index("ix_sc_nodes_candidate_page_sibling", "candidate_id", "page_id", "sibling_order"),
        Index("ix_sc_nodes_candidate_parent_sibling", "candidate_id", "parent_node_id", "sibling_order"),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id = Column(String, ForeignKey("structured_content_candidates.id", ondelete="CASCADE"), nullable=False)
    page_id = Column(String, nullable=False)
    node_id = Column(String(255), nullable=False)
    lineage_key = Column(String(255), nullable=False)
    node_type = Column(String(50), nullable=False)
    parent_node_id = Column(String, nullable=True)
    sibling_order = Column(Integer, nullable=False)
    text = Column(Text, nullable=True)
    recovery_state = Column(String(50), nullable=False)
    source_page_index = Column(Integer, nullable=True); bbox_left = Column(Float, nullable=True); bbox_top = Column(Float, nullable=True); bbox_right = Column(Float, nullable=True); bbox_bottom = Column(Float, nullable=True); text_span_start = Column(Integer, nullable=True); text_span_end = Column(Integer, nullable=True)
    attribute_type = Column(String(50), nullable=True)
    attribute_json = Column(Text, nullable=True)
    extensions_json = Column(Text, nullable=True)
    candidate = relationship("StructuredContentCandidate", back_populates="nodes")
    page = relationship("StructuredContentPage", back_populates="nodes")
    parent = relationship("StructuredContentNode", remote_side=[id, candidate_id])
    table_cells = relationship("StructuredContentTableCell", back_populates="table_node", order_by="StructuredContentTableCell.row_index, StructuredContentTableCell.column_index")


class StructuredContentPageRoot(Base):
    __tablename__ = "structured_content_page_roots"
    __table_args__ = (
        UniqueConstraint("page_id", "root_order", name="uq_sc_page_roots_page_order"),
        UniqueConstraint("page_id", "node_id", name="uq_sc_page_roots_page_node"),
        CheckConstraint("root_order >= 0", name="ck_sc_page_roots_order_nonnegative"),
        ForeignKeyConstraint(["page_id", "candidate_id"], ["structured_content_pages.id", "structured_content_pages.candidate_id"], name="fk_sc_page_roots_page_candidate", ondelete="CASCADE"),
        ForeignKeyConstraint(["node_id", "candidate_id"], ["structured_content_nodes.id", "structured_content_nodes.candidate_id"], name="fk_sc_page_roots_node_candidate", ondelete="CASCADE"),
    )
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id = Column(String, ForeignKey("structured_content_candidates.id", ondelete="CASCADE"), nullable=False)
    page_id = Column(String, nullable=False); node_id = Column(String, nullable=False); root_order = Column(Integer, nullable=False)
    page = relationship("StructuredContentPage", back_populates="roots")
    node = relationship("StructuredContentNode")


class StructuredContentEvidence(Base):
    __tablename__ = "structured_content_evidence"
    __table_args__ = (UniqueConstraint("candidate_id", "evidence_id", name="uq_sc_evidence_candidate_evidence_id"), UniqueConstraint("id", "candidate_id", name="uq_sc_evidence_id_candidate"), CheckConstraint("source_page_index IS NULL OR source_page_index >= 0", name="ck_sc_evidence_source_page_index_nonnegative"),)
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id = Column(String, ForeignKey("structured_content_candidates.id", ondelete="CASCADE"), nullable=False)
    evidence_id = Column(String(255), nullable=False); kind = Column(String(50), nullable=False)
    source_file_ref = Column(String(1024)); source_page_index = Column(Integer); raw_result_ref = Column(String(1024)); structured_processing_result_ref = Column(String(1024)); processing_run_ref = Column(String(1024)); spr_node_ref = Column(String(1024)); spr_observation_ref = Column(String(1024)); spr_evidence_ref = Column(String(1024)); warning_ref = Column(String(1024))
    bbox_left = Column(Float); bbox_top = Column(Float); bbox_right = Column(Float); bbox_bottom = Column(Float); text_span_start = Column(Integer); text_span_end = Column(Integer)
    details_json = Column(Text); extensions_json = Column(Text)
    candidate = relationship("StructuredContentCandidate", back_populates="evidence")


class StructuredContentWarning(Base):
    __tablename__ = "structured_content_warnings"
    __table_args__ = (UniqueConstraint("candidate_id", "warning_id", name="uq_sc_warnings_candidate_warning_id"), UniqueConstraint("id", "candidate_id", name="uq_sc_warnings_id_candidate"),)
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id = Column(String, ForeignKey("structured_content_candidates.id", ondelete="CASCADE"), nullable=False)
    warning_id = Column(String(255), nullable=False); code = Column(String(255), nullable=False); severity = Column(String(50), nullable=False); scope_path = Column(String(1024), nullable=False); safe_summary = Column(Text, nullable=False); recoverable = Column(Boolean, nullable=False, default=True); blocking_hint = Column(Text)
    details_json = Column(Text); extensions_json = Column(Text)
    candidate = relationship("StructuredContentCandidate", back_populates="warnings")


class StructuredContentAsset(Base):
    __tablename__ = "structured_content_assets"
    __table_args__ = (UniqueConstraint("candidate_id", "asset_id", name="uq_sc_assets_candidate_asset_id"), UniqueConstraint("id", "candidate_id", name="uq_sc_assets_id_candidate"), CheckConstraint("byte_size IS NULL OR byte_size >= 0", name="ck_sc_assets_byte_size_nonnegative"),)
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id = Column(String, ForeignKey("structured_content_candidates.id", ondelete="CASCADE"), nullable=False)
    asset_id = Column(String(255), nullable=False); role = Column(String(50), nullable=False); recovery_state = Column(String(50), nullable=False)
    media_type = Column(String(255)); checksum = Column(String(255)); byte_size = Column(Integer); width = Column(Float); height = Column(Float); dimension_unit = Column(String(50)); source_page_index = Column(Integer); bbox_left = Column(Float); bbox_top = Column(Float); bbox_right = Column(Float); bbox_bottom = Column(Float); caption = Column(Text); alt_text = Column(Text); description = Column(Text); storage_ref = Column(String(1024)); extensions_json = Column(Text)
    candidate = relationship("StructuredContentCandidate", back_populates="assets")
    renditions = relationship("StructuredContentAssetRendition", back_populates="asset", order_by="StructuredContentAssetRendition.rendition_order")


class StructuredContentAssetRendition(Base):
    __tablename__ = "structured_content_asset_renditions"
    __table_args__ = (UniqueConstraint("asset_id", "rendition_id", name="uq_sc_asset_renditions_asset_rendition_id"), UniqueConstraint("asset_id", "rendition_order", name="uq_sc_asset_renditions_asset_order"), CheckConstraint("rendition_order >= 0", name="ck_sc_asset_renditions_order_nonnegative"),)
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    asset_id = Column(String, ForeignKey("structured_content_assets.id", ondelete="CASCADE"), nullable=False)
    rendition_id = Column(String(255), nullable=False); rendition_order = Column(Integer, nullable=False); role = Column(String(50)); media_type = Column(String(255)); storage_ref = Column(String(1024)); checksum = Column(String(255)); width = Column(Float); height = Column(Float); dimension_unit = Column(String(50)); recovery_state = Column(String(50)); rebuildable = Column(Boolean, nullable=False, default=False); extensions_json = Column(Text)
    asset = relationship("StructuredContentAsset", back_populates="renditions")


class StructuredContentTableCell(Base):
    __tablename__ = "structured_content_table_cells"
    __table_args__ = (UniqueConstraint("table_node_id", "row_index", "column_index", name="uq_sc_table_cells_node_coordinate"), CheckConstraint("row_index >= 0", name="ck_sc_table_cells_row_nonnegative"), CheckConstraint("column_index >= 0", name="ck_sc_table_cells_column_nonnegative"), CheckConstraint("row_span > 0", name="ck_sc_table_cells_row_span_positive"), CheckConstraint("column_span > 0", name="ck_sc_table_cells_column_span_positive"), Index("ix_sc_table_cells_node_order", "table_node_id", "row_index", "column_index"),)
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    table_node_id = Column(String, ForeignKey("structured_content_nodes.id", ondelete="CASCADE"), nullable=False)
    row_index = Column(Integer, nullable=False); column_index = Column(Integer, nullable=False); row_span = Column(Integer, nullable=False, default=1); column_span = Column(Integer, nullable=False, default=1); text = Column(Text); cell_role = Column(String(50)); extensions_json = Column(Text)
    table_node = relationship("StructuredContentNode", back_populates="table_cells")


class StructuredContentSelection(Base):
    __tablename__ = "structured_content_selection"
    __table_args__ = (CheckConstraint("selection_version >= 0", name="ck_sc_selection_version_nonnegative"), ForeignKeyConstraint(["candidate_id", "document_id"], ["structured_content_candidates.id", "structured_content_candidates.document_id"], name="fk_sc_selection_candidate_document", ondelete="RESTRICT"),)
    document_id = Column(String, ForeignKey("documents.id", ondelete="RESTRICT"), primary_key=True)
    candidate_id = Column(String, nullable=False)
    selection_version = Column(Integer, nullable=False, default=0)
    selected_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    selection_actor_ref = Column(String(255))
    reason = Column(Text)
    document = relationship("Document")
    candidate = relationship("StructuredContentCandidate", back_populates="selection")


# Ordered association records; ordering columns preserve tuple order from the in-memory model.
def _assoc_class(name, table, left_table, right_table, left_col, right_col):
    return type(name, (Base,), {
        "__tablename__": table,
        "__table_args__": (UniqueConstraint(left_col, right_col, name=f"uq_{table}"), CheckConstraint("association_order >= 0", name=f"ck_{table}_order_nonnegative"),),
        "id": Column(String, primary_key=True, default=lambda: str(uuid.uuid4())),
        left_col: Column(String, ForeignKey(f"{left_table}.id", ondelete="CASCADE"), nullable=False),
        right_col: Column(String, ForeignKey(f"{right_table}.id", ondelete="CASCADE"), nullable=False),
        "association_order": Column(Integer, nullable=False, default=0),
    })

StructuredContentPageEvidence = _assoc_class("StructuredContentPageEvidence", "structured_content_page_evidence", "structured_content_pages", "structured_content_evidence", "page_id", "evidence_id")
StructuredContentPageWarning = _assoc_class("StructuredContentPageWarning", "structured_content_page_warning", "structured_content_pages", "structured_content_warnings", "page_id", "warning_id")
StructuredContentNodeEvidence = _assoc_class("StructuredContentNodeEvidence", "structured_content_node_evidence", "structured_content_nodes", "structured_content_evidence", "node_id", "evidence_id")
StructuredContentNodeAsset = _assoc_class("StructuredContentNodeAsset", "structured_content_node_asset", "structured_content_nodes", "structured_content_assets", "node_id", "asset_id")
StructuredContentNodeWarning = _assoc_class("StructuredContentNodeWarning", "structured_content_node_warning", "structured_content_nodes", "structured_content_warnings", "node_id", "warning_id")
StructuredContentAssetEvidence = _assoc_class("StructuredContentAssetEvidence", "structured_content_asset_evidence", "structured_content_assets", "structured_content_evidence", "asset_id", "evidence_id")
StructuredContentWarningEvidence = _assoc_class("StructuredContentWarningEvidence", "structured_content_warning_evidence", "structured_content_warnings", "structured_content_evidence", "warning_id", "evidence_id")
