"""Books management routes."""

from __future__ import annotations

import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.storage.base import StorageProvider
from app.storage.dependencies import get_storage_provider
from app.book_service import BookDeletionConflict, get_book_service
from app.schemas import BookSchema, BooksListSchema, BookDetailSchema, BookContentSchema

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/books", tags=["books"])


@router.get("", response_model=BooksListSchema)
async def list_books(db: Session = Depends(get_db)) -> BooksListSchema:
    """
    Get all books from bookshelf.

    Returns:
        List of books with metadata (title, author, publication_date, pages_count)
    """
    try:
        book_service = get_book_service()
        books = book_service.get_all_books(db)

        book_list = [
            BookSchema(
                book_id=book.id,
                book_title=book.book_title,
                author=book.author,
                publication_date=str(book.publication_date) if book.publication_date else None,
                pages_count=book.pages_count,
                file_type=book.file_type or "",
                status=book.status or "completed",
                error_message=book.error_message,
                created_at=book.created_at,
            )
            for book in books
        ]

        logger.info(f"Retrieved {len(book_list)} books")
        return BooksListSchema(books=book_list, total=len(book_list))

    except Exception as e:
        logger.error(f"Failed to list books: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list books: {e}")


@router.get("/{book_id}", response_model=BookDetailSchema)
async def get_book_detail(
    book_id: str, db: Session = Depends(get_db)
) -> BookDetailSchema:
    """
    Get book metadata by ID.

    Args:
        book_id: Book ID

    Returns:
        Book metadata
    """
    try:
        book_service = get_book_service()
        book = book_service.get_book(db, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        logger.info(f"Retrieved book: {book_id}")
        return BookDetailSchema(
            book_id=book.id,
            book_title=book.book_title,
            author=book.author,
            publication_date=str(book.publication_date) if book.publication_date else None,
            pages_count=book.pages_count,
            file_type=book.file_type or "",
            status=book.status or "completed",
            processed_file_path=book.processed_file_path,
            original_file_path=book.original_file_path,
            error_message=book.error_message,
            created_at=book.created_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get book: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get book: {e}")


def _assemble_txt_from_mineru(result_json_str: str) -> str:
    """Convert MineruResult.result_json to plain-text with image markers.

    Text content is emitted verbatim.  Visual blocks are represented as
    ``$%$%$%{image_id}$%$%$%`` markers (the format consumed by the frontend).
    Headings are preceded by the appropriate Markdown-style ``#`` prefix so
    levels are preserved.
    """
    try:
        blocks: list[dict] = json.loads(result_json_str)
    except Exception:
        return result_json_str  # fall back to raw string

    parts: list[str] = []
    for blk in blocks:
        btype = blk.get("type", "text")
        if btype == "title":
            level = blk.get("level", 2)
            prefix = "#" * max(1, min(level, 6)) + " "
            content = blk.get("content", "").strip()
            if content:
                parts.append(prefix + content + "\n")
        elif btype == "text":
            content = blk.get("content", "").strip()
            if content:
                parts.append(content + "\n")
        elif btype == "toc":
            content = blk.get("content", "").strip()
            if content:
                parts.append(content + "\n")
        elif btype in ("image", "table"):
            image_id = blk.get("image_id", "")
            caption = blk.get("caption", "").strip()
            # Continuation table image (cross-page split)
            continuation = blk.get("continuation_image_id")
            if image_id:
                parts.append(f"$%$%$%{image_id}$%$%$%\n")
            if continuation:
                parts.append(f"$%$%$%{continuation}$%$%$%\n")
            if caption:
                parts.append(caption + "\n")
    return "".join(parts).strip()


@router.get("/{book_id}/content", response_model=BookContentSchema)
async def get_book_content(
    book_id: str, db: Session = Depends(get_db)
) -> BookContentSchema:
    """
    Get book content (text) assembled from the post-processed database records.

    For PDF books the content is assembled from ``MineruResult.result_json``
    using the block list produced by the MinerU-Popo post-processing step.
    For TXT books the content is read directly from the processed file.

    Returns:
        Book content as plain text with ``$%$%$%{image_id}$%$%$%`` markers
        for visual blocks.
    """
    try:
        book_service = get_book_service()
        book = book_service.get_book(db, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        if book.status != "completed":
            raise HTTPException(
                status_code=404,
                detail=f"Book content not available (status: {book.status})",
            )

        # ── PDF books: read from MineruResult ──────────────────────────────
        if book.file_type == "pdf":
            from app.models import MineruResult
            mineru = db.query(MineruResult).filter(MineruResult.book_id == book_id).first()
            if mineru is None or not mineru.result_json:
                raise HTTPException(status_code=404, detail="Book content not found")
            content = _assemble_txt_from_mineru(mineru.result_json)
        else:
            # ── TXT books: read from processed file ─────────────────────────
            content = book_service.get_book_content(db, book_id)
            if content is None:
                raise HTTPException(status_code=404, detail="Book content not found")

        logger.info(f"Retrieved book content: {book_id}")
        return BookContentSchema(
            book_id=book.id,
            book_title=book.book_title,
            content=content,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get book content: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get book content: {e}")


@router.delete("/{book_id}")
async def delete_book(book_id: str, db: Session = Depends(get_db), storage: StorageProvider = Depends(get_storage_provider)) -> dict:
    """
    Delete book from bookshelf (and associated files).

    Args:
        book_id: Book ID

    Returns:
        Success message
    """
    try:
        book_service = get_book_service()
        success = book_service.delete_book(db, book_id, storage)

        if not success:
            raise HTTPException(status_code=404, detail="Book not found")

        logger.info(f"Deleted book: {book_id}")
        return {"message": f"Book {book_id} deleted successfully"}

    except HTTPException:
        raise
    except BookDeletionConflict as e:
        logger.warning("Book delete conflict book_id=%s: %s", book_id, e)
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete book: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete book: {e}")
