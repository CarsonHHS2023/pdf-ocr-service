"""OCR processing routes."""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Document, DocumentType, SourceFile
from app.ocr_service import OCRExtractionResult, TextBlock, get_ocr_service
from app.pdf_service import get_pdf_service
from app.schemas import (
    OCRProcessResponse,
    OCRResultResponse,
    StructureAnalysisResponse,
    TaskMetadata,
    TextBlockSchema,
    UploadBookResponse,
)
from app.processing.pdf_ingestion import new_pdf_ingestion_ids, process_pdf_document_background
from app.processing.txt.ingestion import new_txt_ingestion_ids, process_txt_document_background
from app.storage.base import StorageProvider
from app.storage.dependencies import get_storage_provider
from app.storage.errors import StorageError
from app.storage.models import StorageReference

# HF Spaces reliably surfaces Uvicorn's configured error logger. The stderr
# fallback is intentionally flushed so diagnostics survive abrupt restarts.
logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/v1", tags=["ocr"])

# Legacy image OCR task storage (in-memory). PDF/TXT uploads use the database.
TASKS: dict[str, dict[str, Any]] = {}


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _upload_diagnostic(event: str, **fields: object) -> None:
    payload = " ".join(f"{name}={value}" for name, value in fields.items())
    message = f"{event} {payload}".rstrip()
    logger.info(message)
    print(message, file=sys.stderr, flush=True)


def _to_task_metadata(task: dict[str, Any]) -> TaskMetadata:
    return TaskMetadata(
        task_id=task["task_id"],
        filename=task["filename"],
        status=task["status"],
        created_at=task["created_at"],
        updated_at=task["updated_at"],
        error_message=task.get("error_message"),
    )


def _convert_text_blocks_to_schema(text_blocks: list[TextBlock]) -> list[TextBlockSchema]:
    """Convert TextBlock objects to TextBlockSchema for API response."""
    return [
        TextBlockSchema(
            text=block.text,
            confidence=block.confidence,
            box=block.box,
            block_type=block.block_type,
        )
        for block in text_blocks
    ]


def _retain_source_bytes(storage: StorageProvider, content: bytes) -> tuple[str, int, str]:
    """Write original upload bytes through Storage and return actual metadata."""
    expected_checksum = hashlib.sha256(content).hexdigest()
    result = storage.put(
        content,
        StorageReference.generate(),
        expected_size=len(content),
        expected_sha256=expected_checksum,
    )
    return str(result.reference), result.byte_size, result.checksum_sha256


def _cleanup_retained_source(storage: StorageProvider, storage_reference: str | None) -> None:
    """Best-effort compensation for DB failures after source retention."""
    if not storage_reference:
        return
    try:
        storage.delete(storage_reference)
    except Exception as exc:  # pragma: no cover - log-only compensation path
        logger.error("Failed to clean retained source after DB error: %s", exc)


@router.post("/upload", response_model=UploadBookResponse)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    storage: StorageProvider = Depends(get_storage_provider),
) -> UploadBookResponse:
    """Upload a PDF or TXT file and start canonical processing.

    TXT files retain the original bytes and are processed asynchronously through
    bounded LLM structure analysis, deterministic SPR v2 reconciliation, the
    shared Structured Content v2 transformer, and explicit Reader v2 selection.

    PDF files are processed asynchronously through the retained-source Modal
    PaddleOCR-VL integration. The server counts pages without rasterizing them,
    then marks the document completed only after Structured Content v2 is
    persisted and explicitly selected for Reader v2.
    """
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename is required")

    filename = file.filename
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    ext = Path(filename).suffix.lower()
    if ext not in {".pdf", ".txt"}:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Only PDF and TXT files are accepted.",
        )

    file_type = "pdf" if ext == ".pdf" else "txt"
    book_title = Path(filename).stem
    book_id = str(uuid.uuid4())

    content = await file.read()
    _upload_diagnostic(
        "PDF_UPLOAD_ACCEPTED" if file_type == "pdf" else "TXT_UPLOAD_ACCEPTED",
        document_id=book_id,
        filename=filename,
        byte_size=len(content),
    )

    try:
        storage_reference, retained_size, retained_checksum = _retain_source_bytes(storage, content)
    except StorageError as exc:
        logger.exception("Source retention failed document_id=%s", book_id)
        raise HTTPException(status_code=500, detail=f"Failed to retain uploaded source: {exc}") from exc

    if file_type == "txt":
        source_file_id = str(uuid.uuid4())
        book = Document(
            id=book_id,
            document_type=DocumentType.BOOK,
            title=book_title,
            file_type=file_type,
            status="processing",
        )
        source_file = SourceFile(
            id=source_file_id,
            document=book,
            original_filename=filename,
            file_type=file_type,
            mime_type=file.content_type or "text/plain",
            byte_size=retained_size,
            checksum_sha256=retained_checksum,
            storage_reference=storage_reference,
            retained=1,
            is_primary=1,
        )
        db.add(book)
        db.add(source_file)
        try:
            db.commit()
        except Exception:
            db.rollback()
            _cleanup_retained_source(storage, storage_reference)
            raise

        ingestion_ids = new_txt_ingestion_ids()
        _upload_diagnostic(
            "TXT_SOURCE_RETAINED",
            document_id=book_id,
            source_file_id=source_file_id,
            processing_run_ref=ingestion_ids.processing_run_ref,
            storage_reference=storage_reference,
            byte_size=retained_size,
        )
        background_tasks.add_task(
            process_txt_document_background,
            book_id,
            source_file_id,
            ingestion_ids,
        )
        _upload_diagnostic(
            "TXT_BACKGROUND_TASK_QUEUED",
            document_id=book_id,
            source_file_id=source_file_id,
            processing_run_ref=ingestion_ids.processing_run_ref,
        )

        return UploadBookResponse(
            book_id=book_id,
            book_title=book_title,
            file_type=file_type,
            status="processing",
            processed_file_path=None,
            original_file_path=None,
            message=(
                f"File '{filename}' uploaded; TXT structure analysis and Reader v2 "
                "canonicalization queued."
            ),
        )

    _upload_diagnostic(
        "PDF_SOURCE_RETAINED",
        document_id=book_id,
        storage_reference=storage_reference,
        byte_size=retained_size,
    )

    # ── PDF: retain original source -> Modal -> canonical Reader v2 ──────────
    try:
        import fitz  # type: ignore[import]

        pdf = fitz.open(stream=content, filetype="pdf")
        try:
            page_count = pdf.page_count
        finally:
            pdf.close()
        if page_count <= 0:
            raise ValueError("Uploaded PDF contains no pages")
    except Exception:
        logger.exception("Uploaded PDF could not be opened document_id=%s", book_id)
        _cleanup_retained_source(storage, storage_reference)
        return UploadBookResponse(
            book_id=book_id,
            book_title=book_title,
            file_type=file_type,
            status="failed",
            error_message="Uploaded PDF could not be opened",
            message=f"Failed to accept PDF '{filename}'.",
        )

    source_file_id = str(uuid.uuid4())
    book = Document(
        id=book_id,
        document_type=DocumentType.BOOK,
        title=book_title,
        file_type=file_type,
        pages_count=page_count,
        status="processing",
    )
    source_file = SourceFile(
        id=source_file_id,
        document=book,
        original_filename=filename,
        file_type=file_type,
        mime_type="application/pdf",
        byte_size=retained_size,
        checksum_sha256=retained_checksum,
        storage_reference=storage_reference,
        retained=1,
        is_primary=1,
    )
    db.add(book)
    db.add(source_file)
    try:
        db.commit()
    except Exception:
        db.rollback()
        _cleanup_retained_source(storage, storage_reference)
        logger.exception("PDF database commit failed document_id=%s source_file_id=%s", book_id, source_file_id)
        raise

    ingestion_ids = new_pdf_ingestion_ids()
    _upload_diagnostic(
        "PDF_DATABASE_COMMITTED",
        document_id=book_id,
        source_file_id=source_file_id,
        processing_attempt_id=ingestion_ids.processing_attempt_id,
        page_count=page_count,
    )
    background_tasks.add_task(
        process_pdf_document_background,
        book_id,
        source_file_id,
        ingestion_ids,
    )
    _upload_diagnostic(
        "PDF_BACKGROUND_TASK_QUEUED",
        document_id=book_id,
        source_file_id=source_file_id,
        processing_attempt_id=ingestion_ids.processing_attempt_id,
        provider_job_id=ingestion_ids.provider_job_id,
    )

    return UploadBookResponse(
        book_id=book_id,
        book_title=book_title,
        file_type=file_type,
        status="processing",
        processed_file_path=None,
        message=(
            f"File '{filename}' uploaded; {page_count} page(s) queued for Modal "
            "processing and Reader v2 canonicalization."
        ),
    )


@router.post("/ocr/{task_id}", response_model=OCRProcessResponse)
async def process_ocr(task_id: str) -> OCRProcessResponse:
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not os.path.exists(task["file_path"]):
        task["status"] = TaskStatus.FAILED.value
        task["error_message"] = "Uploaded file not found"
        task["updated_at"] = _now()
        raise HTTPException(status_code=500, detail="Uploaded file not found")

    task["status"] = TaskStatus.PROCESSING.value
    task["updated_at"] = _now()

    try:
        result: OCRExtractionResult = get_ocr_service().extract_text(task["file_path"])
        task["status"] = TaskStatus.COMPLETED.value
        task["extracted_text"] = result.extracted_text
        task["confidence_score"] = result.confidence_score
        task["text_blocks"] = result.text_blocks
        task["structure"] = result.structure
        task["updated_at"] = _now()
    except Exception as exc:
        task["status"] = TaskStatus.FAILED.value
        task["error_message"] = str(exc)
        task["updated_at"] = _now()
        raise HTTPException(status_code=500, detail=f"OCR processing failed: {exc}") from exc

    return OCRProcessResponse(
        task=_to_task_metadata(task),
        extracted_text=task["extracted_text"],
        confidence_score=task["confidence_score"],
        text_blocks=_convert_text_blocks_to_schema(task["text_blocks"]),
        structure=task["structure"],
    )


@router.post("/structure/{task_id}", response_model=StructureAnalysisResponse)
async def process_structure_analysis(task_id: str) -> StructureAnalysisResponse:
    """Perform document structure analysis using PP-Structure."""
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not os.path.exists(task["file_path"]):
        task["status"] = TaskStatus.FAILED.value
        task["error_message"] = "Uploaded file not found"
        task["updated_at"] = _now()
        raise HTTPException(status_code=500, detail="Uploaded file not found")

    task["status"] = TaskStatus.PROCESSING.value
    task["updated_at"] = _now()

    try:
        result: OCRExtractionResult = get_ocr_service().structure_analysis(task["file_path"])
        task["status"] = TaskStatus.COMPLETED.value
        task["extracted_text"] = result.extracted_text
        task["confidence_score"] = result.confidence_score
        task["text_blocks"] = result.text_blocks
        task["structure"] = result.structure
        task["updated_at"] = _now()
    except Exception as exc:
        task["status"] = TaskStatus.FAILED.value
        task["error_message"] = str(exc)
        task["updated_at"] = _now()
        raise HTTPException(status_code=500, detail=f"Structure analysis failed: {exc}") from exc

    return StructureAnalysisResponse(
        task=_to_task_metadata(task),
        extracted_text=task["extracted_text"],
        confidence_score=task["confidence_score"],
        text_blocks=_convert_text_blocks_to_schema(task["text_blocks"]),
        structure=task["structure"],
    )


@router.get("/result/{task_id}", response_model=OCRResultResponse)
async def get_result(task_id: str) -> OCRResultResponse:
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return OCRResultResponse(
        **_to_task_metadata(task).model_dump(),
        extracted_text=task.get("extracted_text"),
        confidence_score=task.get("confidence_score"),
        text_blocks=_convert_text_blocks_to_schema(task.get("text_blocks", [])),
        structure=task.get("structure"),
    )
