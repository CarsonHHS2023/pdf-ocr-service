"""Pydantic schemas for API responses."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class HealthCheckResponse(BaseModel):
    status: str
    service: str


class StructureRefinementImagePolicyResponse(BaseModel):
    max_pages_per_batch: int
    max_dimension_pixels: int
    jpeg_quality: int
    max_image_bytes: int


class StructureRefinementConfigResponse(BaseModel):
    enabled: bool
    provider: Optional[str] = None
    model: Optional[str] = None
    timeout_seconds: float
    max_attempts: int
    initial_backoff_seconds: float
    max_backoff_seconds: float
    max_concurrent_batches_per_document: int
    global_max_concurrent_batches: int
    image_policy: StructureRefinementImagePolicyResponse


class TaskMetadata(BaseModel):
    task_id: str
    filename: str
    status: str
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None


class TextBlockSchema(BaseModel):
    """Schema for a detected text block."""
    text: str
    confidence: float
    box: list  # Coordinates [[x1,y1], [x2,y2], ...]
    block_type: str = "text"  # "text", "title", "table", "figure", etc.


class OCRProcessResponse(BaseModel):
    task: TaskMetadata
    extracted_text: Optional[str] = None
    confidence_score: Optional[float] = None
    text_blocks: list[TextBlockSchema] = []
    structure: Optional[dict] = None


class OCRResultResponse(TaskMetadata):
    extracted_text: Optional[str] = None
    confidence_score: Optional[float] = None
    text_blocks: list[TextBlockSchema] = []
    structure: Optional[dict] = None


class DocumentBlockSchema(BaseModel):
    """Document block after layout analysis."""
    block_type: str  # "text", "title", "paragraph", "table", "image", "figure", etc.
    text: Optional[str] = None  # For text blocks
    bbox: list  # [x1, y1, x2, y2]
    confidence: float
    region_image_path: Optional[str] = None  # For table/image blocks - path to cropped region


class LayoutAnalysisResponse(BaseModel):
    """Response for layout analysis endpoint."""
    task: TaskMetadata
    blocks: list[DocumentBlockSchema] = []
    total_blocks: int = 0


class StructureAnalysisResponse(BaseModel):
    """Response for structure analysis endpoint."""
    task: TaskMetadata
    extracted_text: Optional[str] = None
    confidence_score: Optional[float] = None
    text_blocks: list[TextBlockSchema] = []
    structure: Optional[dict[str, Any]] = None


class BookSchema(BaseModel):
    """Book metadata for bookshelf list."""
    book_id: str
    book_title: str
    author: Optional[str] = None
    publication_date: Optional[str] = None
    pages_count: Optional[int] = None
    file_type: str = ""
    status: str = "completed"
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None


class BooksListSchema(BaseModel):
    """Response for books list endpoint."""
    books: list[BookSchema]
    total: int


class BookDetailSchema(BaseModel):
    """Response for book detail endpoint."""
    book_id: str
    book_title: str
    author: Optional[str] = None
    publication_date: Optional[str] = None
    pages_count: Optional[int] = None
    file_type: str = ""
    status: str = "completed"
    processed_file_path: Optional[str] = None
    original_file_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime


class BookContentSchema(BaseModel):
    """Response for book content endpoint."""
    book_id: str
    book_title: str
    content: str


class PDFUploadResponse(BaseModel):
    """Response for PDF upload."""
    book_id: str
    book_title: str
    message: str


class UploadBookResponse(BaseModel):
    """Response for the unified PDF/TXT upload endpoint."""
    book_id: str
    book_title: str
    file_type: str
    status: str
    processed_file_path: Optional[str] = None
    original_file_path: Optional[str] = None
    error_message: Optional[str] = None
    message: str
