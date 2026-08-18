"""API endpoints for PDF processing."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
import tempfile

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from pydantic import BaseModel

from app.services.pdf_processing_service import get_pdf_processing_service
from app.services.database_service import get_database_service

logger = logging.getLogger(__name__)

# Router for PDF processing endpoints
router = APIRouter(prefix="/api/pdf", tags=["PDF Processing"])


class ProcessingResult(BaseModel):
    """PDF processing result response."""
    status: str
    message: str
    book_id: Optional[str] = None
    total_pages: int = 0
    pages_processed: int = 0
    pages_failed: int = 0
    total_text_blocks: int = 0
    total_image_blocks: int = 0
    total_text_characters: int = 0
    total_image_bytes: int = 0
    error: Optional[str] = None


class BookInfo(BaseModel):
    """Book information response."""
    book_id: str
    title: str
    author: Optional[str] = None
    total_pages: int
    text_blocks: int
    image_blocks: int
    total_text_characters: int
    total_image_bytes: int


@router.post("/upload-and-process")
async def upload_and_process_pdf(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks()
) -> ProcessingResult:
    """
    Upload and process PDF file.

    Args:
        file: PDF file to process
        background_tasks: FastAPI background tasks

    Returns:
        Processing result
    """
    try:
        # Validate file
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="File must be a PDF")
        
        # Save uploaded file to temp location
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            temp_pdf_path = tmp_file.name
        
        logger.info(f"PDF uploaded: {file.filename} (temp path: {temp_pdf_path})")
        
        # Process PDF in background
        background_tasks.add_task(
            _process_pdf_background,
            temp_pdf_path,
            file.filename
        )
        
        return ProcessingResult(
            status="processing",
            message=f"PDF processing started for {file.filename}",
            total_pages=0,
            pages_processed=0
        )
        
    except HTTPException as e:
        logger.error(f"Validation error: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Error uploading PDF: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/process-status/{book_id}")
async def get_processing_status(book_id: str) -> BookInfo:
    """
    Get processing status and book information.

    Args:
        book_id: Book ID

    Returns:
        Book information
    """
    try:
        db_service = get_database_service()
        book = db_service.get_book(book_id)
        
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        
        # Get statistics
        content_blocks = db_service.get_book_content_blocks(book_id)
        images = db_service.get_book_images(book_id)
        
        text_blocks = len([b for b in content_blocks if b.block_type == "text"])
        image_blocks = len([b for b in content_blocks if b.block_type in ["image", "table"]])
        total_text = sum(len(b.content or "") for b in content_blocks if b.block_type == "text")
        total_image_bytes = sum(img.image_size or 0 for img in images)
        
        return BookInfo(
            book_id=book_id,
            title=book.book_title,
            author=book.author,
            total_pages=book.pages_count or 0,
            text_blocks=text_blocks,
            image_blocks=image_blocks,
            total_text_characters=total_text,
            total_image_bytes=total_image_bytes
        )
        
    except HTTPException as e:
        raise
    except Exception as e:
        logger.error(f"Error getting book info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/book-text/{book_id}")
async def get_book_text(book_id: str, page_num: Optional[int] = None) -> dict:
    """
    Get extracted text from a book.

    Args:
        book_id: Book ID
        page_num: Optional page number to filter

    Returns:
        Dictionary with extracted text
    """
    try:
        db_service = get_database_service()
        
        # Verify book exists
        book = db_service.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        
        # Get content blocks
        content_blocks = db_service.get_book_content_blocks(book_id, page_num)
        
        # Extract text
        result = {
            "book_id": book_id,
            "title": book.book_title,
            "pages": {}
        }
        
        for block in content_blocks:
            if block.block_type == "text":
                page = block.page_num
                if page not in result["pages"]:
                    result["pages"][page] = []
                
                result["pages"][page].append({
                    "block_index": block.block_index,
                    "content": block.content,
                    "confidence": block.confidence,
                    "bbox": block.bbox
                })
        
        return result
        
    except HTTPException as e:
        raise
    except Exception as e:
        logger.error(f"Error getting book text: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/book-images/{book_id}")
async def get_book_images_list(book_id: str, page_num: Optional[int] = None) -> dict:
    """
    Get list of extracted images from a book.

    Args:
        book_id: Book ID
        page_num: Optional page number to filter

    Returns:
        Dictionary with image metadata
    """
    try:
        db_service = get_database_service()
        
        # Verify book exists
        book = db_service.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        
        # Get images
        images = db_service.get_book_images(book_id, page_num)
        
        result = {
            "book_id": book_id,
            "title": book.book_title,
            "images": [
                {
                    "image_id": img.image_id,
                    "page_num": img.page_num,
                    "block_type": img.block_type,
                    "size": img.image_size,
                    "format": img.image_format,
                    "bbox": img.bbox
                }
                for img in images
            ]
        }
        
        return result
        
    except HTTPException as e:
        raise
    except Exception as e:
        logger.error(f"Error getting book images: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/image/{image_id}")
async def get_image(image_id: str):
    """
    Download extracted image.

    Args:
        image_id: Image ID

    Returns:
        Image file
    """
    try:
        db_service = get_database_service()
        image = db_service.get_image_by_id(image_id)
        
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
        
        return {
            "image_id": image_id,
            "format": image.image_format,
            "size": image.image_size,
            "page_num": image.page_num
        }
        
    except HTTPException as e:
        raise
    except Exception as e:
        logger.error(f"Error getting image: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _process_pdf_background(temp_pdf_path: str, original_filename: str):
    """
    Background task to process PDF.

    Runs the full layout-aware pipeline:
    1. Processes the PDF with PDFProcessingService (page-by-page blocks).
    2. Assembles a TXT file from the block results, with image markers
       ``$%$%$%{image_id}$%$%$%`` for image/table blocks.
    3. Creates a Bookshelf record (status=completed) pointing at the TXT file.
    4. Saves all ContentBlock and BookImage rows to the database.

    Args:
        temp_pdf_path:     Path to temporary uploaded PDF file.
        original_filename: Original file name (used for the book title).
    """
    try:
        logger.info(f"Starting background PDF processing: {original_filename}")

        # Initialise services
        pdf_service = get_pdf_processing_service()
        db_service = get_database_service()

        # Run the PDF processing pipeline (layout analysis + block extraction)
        processing_result = pdf_service.process_pdf_file(temp_pdf_path)

        if processing_result["status"] != "success":
            logger.error(f"PDF processing failed: {processing_result.get('error')}")
            return

        # ----------------------------------------------------------------
        # Build TXT content from block results
        # ----------------------------------------------------------------
        output_lines: list[str] = []
        for page_result in processing_result["page_results"]:
            # Keep blocks in their natural layout order (already sorted by the
            # pipeline); within a page sort by bbox y then x for reading order.
            sorted_blocks = sorted(
                page_result["blocks"],
                key=lambda b: (
                    b.get("bbox", [0, 0, 0, 0])[1],
                    b.get("bbox", [0, 0, 0, 0])[0],
                ),
            )
            for block_result in sorted_blocks:
                content_type = block_result.get("content_type")
                if content_type == "text":
                    text = (block_result.get("content") or "").strip()
                    if text:
                        output_lines.append(text)
                elif content_type == "image":
                    image_id = block_result.get("image_id", "")
                    if image_id:
                        output_lines.append(f"$%$%$%{image_id}$%$%$%")

        txt_content = "\n".join(output_lines)

        # ----------------------------------------------------------------
        # Save TXT file
        # ----------------------------------------------------------------
        import re as _re
        import uuid as _uuid
        from app.config import settings

        output_dir = Path(settings.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        book_title = original_filename.replace(".pdf", "").replace(".PDF", "")
        # Sanitise title: keep only safe characters (letters, digits, CJK, dash, underscore, space)
        safe_title = _re.sub(
            r"[^\w\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\-_. ]", "_", book_title
        ).strip()[:100]
        txt_filename = f"{_uuid.uuid4().hex[:8]}_{safe_title}.txt"
        txt_file_path = str(output_dir / txt_filename)
        with open(txt_file_path, "w", encoding="utf-8") as f:
            f.write(txt_content)
        logger.info(f"TXT file written: {txt_file_path}")

        # ----------------------------------------------------------------
        # Create Bookshelf record – use the correct parameter name
        # ----------------------------------------------------------------
        book_id = db_service.create_book(
            title=book_title,
            total_pages=processing_result["total_pages"],
            processed_file_path=txt_file_path,
        )

        # ----------------------------------------------------------------
        # Save ContentBlock and BookImage rows
        # ----------------------------------------------------------------
        for page_result in processing_result["page_results"]:
            page_num = page_result["page_num"]

            for block_result in page_result["blocks"]:
                try:
                    block_index = block_result["block_index"]
                    block_type = block_result["block_type"]
                    bbox = block_result["bbox"]
                    confidence = block_result["confidence"]

                    if block_result["content_type"] == "text":
                        content = block_result.get("content", "")
                        db_service.save_content_block(
                            book_id=book_id,
                            page_num=page_num,
                            block_index=block_index,
                            block_type=block_type,
                            content=content,
                            bbox=bbox,
                            confidence=confidence,
                        )

                    elif block_result["content_type"] == "image":
                        image_id = block_result["image_id"]
                        png_data = block_result["image_data"]

                        db_service.save_book_image(
                            book_id=book_id,
                            image_id=image_id,
                            image_data=png_data,
                            image_format="png",
                            page_num=page_num,
                            bbox=bbox,
                            block_type=block_type,
                        )

                        # Save reference in content_blocks for ordering
                        db_service.save_content_block(
                            book_id=book_id,
                            page_num=page_num,
                            block_index=block_index,
                            block_type=block_type,
                            content=image_id,
                            bbox=bbox,
                            confidence=confidence,
                        )

                except Exception as e:
                    logger.error(f"Error saving block result: {e}")
                    continue

        logger.info(
            f"Background PDF processing completed: book_id={book_id}, "
            f"pages={processing_result['pages_processed']}"
        )

        # Clean up temp file
        try:
            Path(temp_pdf_path).unlink()
        except Exception as e:
            logger.warning(f"Failed to delete temp file: {e}")

    except Exception as e:
        logger.error(f"Background PDF processing failed: {e}", exc_info=True)
