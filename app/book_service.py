"""Book service for managing bookshelf."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from datetime import date
from sqlalchemy.orm import Session

from app.models import Document, DocumentType
from app.storage.base import StorageProvider
from app.storage.errors import ObjectNotFound
from app.config import settings

logger = logging.getLogger(__name__)

_TERMINAL_PROCESSING_RUN_STATUSES = {"succeeded", "failed", "cancelled"}


class BookDeletionConflict(RuntimeError):
    """Raised when a book cannot be safely deleted while processing is active."""


class BookService:
    """Service for managing books on bookshelf."""

    @staticmethod
    def create_book(
        db: Session,
        book_title: str,
        txt_content: str,
        file_type: str = "pdf",
        author: str | None = None,
        publication_date: date | None = None,
        pages_count: int | None = None,
    ) -> tuple[str, str]:
        """
        Create a new book entry and save TXT file.

        Args:
            db: Database session
            book_title: Book title
            txt_content: Processed TXT content
            file_type: File type ("pdf" or "txt")
            author: Book author (optional)
            publication_date: Publication date (optional)
            pages_count: Number of pages (optional)

        Returns:
            Tuple of (book_id, processed_file_path)
        """
        try:
            # Ensure output directory exists
            output_dir = Path(settings.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            # Create filepath with sanitized title to ensure filesystem safety
            safe_title = re.sub(r'[^\w\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\-_. ]', '_', book_title)
            safe_title = safe_title.strip()[:100]  # limit length
            filename = f"{uuid.uuid4().hex[:8]}_{safe_title}.txt"
            processed_file_path = str(output_dir / filename)

            # Save TXT file
            with open(processed_file_path, "w", encoding="utf-8") as f:
                f.write(txt_content)

            # Create database record
            book = Document(
                document_type=DocumentType.BOOK,
                title=book_title,
                file_type=file_type,
                processed_file_path=processed_file_path,
                status="completed",
                author=author,
                publication_date=publication_date,
                pages_count=pages_count,
            )
            db.add(book)
            db.commit()
            db.refresh(book)

            logger.info(
                f"Created book: {book.id}, title: {book_title}, author: {author}, pages: {pages_count}"
            )
            return book.id, processed_file_path

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create book: {e}")
            raise

    @staticmethod
    def get_book(db: Session, book_id: str) -> Document | None:
        """
        Get book by ID.

        Args:
            db: Database session
            book_id: Book ID

        Returns:
            Document object or None
        """
        return (
            db.query(Document)
            .filter(Document.id == book_id, Document.document_type == DocumentType.BOOK.value)
            .first()
        )

    @staticmethod
    def get_all_books(db: Session) -> list[Document]:
        """
        Get all books from bookshelf.

        Args:
            db: Database session

        Returns:
            List of Document objects
        """
        return (
            db.query(Document)
            .filter(Document.document_type == DocumentType.BOOK.value)
            .order_by(Document.created_at.desc())
            .all()
        )

    @staticmethod
    def get_book_content(db: Session, book_id: str) -> str | None:
        """
        Get book content from processed file.

        Args:
            db: Database session
            book_id: Book ID

        Returns:
            Book content or None
        """
        try:
            book = BookService.get_book(db, book_id)
            if not book:
                logger.warning(f"Book not found: {book_id}")
                return None

            filepath = book.processed_file_path
            if not filepath:
                logger.warning(f"No processed file for book: {book_id}")
                return None

            filepath_obj = Path(filepath)
            if not filepath_obj.exists():
                logger.warning(f"Book file not found: {filepath}")
                return None

            with open(filepath_obj, "r", encoding="utf-8") as f:
                content = f.read()

            logger.info(f"Retrieved book content: {book_id}, size: {len(content)}")
            return content

        except Exception as e:
            logger.error(f"Failed to get book content: {e}")
            raise

    @staticmethod
    def delete_book(db: Session, book_id: str, storage: StorageProvider | None = None) -> bool:
        """
        Delete book and associated files.

        ProcessingRun is durable provenance and therefore remains protected by
        RESTRICT at the schema boundary. A user-initiated delete explicitly
        purges only terminal runs; any active/non-terminal run blocks deletion.

        Args:
            db: Database session
            book_id: Book ID

        Returns:
            True if deleted, False otherwise
        """
        try:
            book = BookService.get_book(db, book_id)
            if not book:
                logger.warning(f"Book not found: {book_id}")
                return False

            processing_runs = list(book.processing_runs)
            nonterminal_runs = [
                run
                for run in processing_runs
                if run.status not in _TERMINAL_PROCESSING_RUN_STATUSES
            ]
            if nonterminal_runs:
                logger.warning(
                    "Refusing to delete book with active processing runs: book_id=%s active_run_count=%s",
                    book_id,
                    len(nonterminal_runs),
                )
                raise BookDeletionConflict(
                    "Book is still being processed and cannot be deleted yet"
                )

            # Delete associated compatibility files only. Opaque retained-source
            # storage references are deleted explicitly through Storage below,
            # never parsed as filesystem paths.
            for filepath in [book.processed_file_path, book.original_file_path]:
                if filepath:
                    p = Path(filepath)
                    if p.exists():
                        p.unlink()
                        logger.info(f"Deleted file: {filepath}")

            deleted_sources: list[tuple[str, bytes]] = []

            def restore_deleted_sources(reason: str) -> None:
                if storage is None:
                    return
                for storage_reference, retained_bytes in deleted_sources:
                    try:
                        storage.put(retained_bytes, storage_reference)
                        logger.info("Restored retained source after %s: %s", reason, book_id)
                    except Exception as restore_exc:
                        logger.error(
                            "Failed to restore retained source after %s: %s",
                            reason,
                            restore_exc,
                        )

            if storage is not None:
                try:
                    for source in list(book.source_files):
                        if source.retained and source.storage_reference:
                            try:
                                retained_bytes = storage.get(source.storage_reference)
                                storage.delete(source.storage_reference)
                                deleted_sources.append((source.storage_reference, retained_bytes))
                                logger.info("Deleted retained source for book %s", book_id)
                            except ObjectNotFound:
                                logger.warning("Retained source already missing for book %s", book_id)
                except Exception:
                    db.rollback()
                    restore_deleted_sources("retained source delete failure")
                    raise

            try:
                # ProcessingRun intentionally uses ON DELETE RESTRICT so provenance
                # cannot disappear implicitly. A user-initiated purge removes only
                # terminal runs explicitly, in the same DB transaction, before the
                # Document/SourceFile aggregate is deleted.
                for run in processing_runs:
                    db.delete(run)
                if processing_runs:
                    db.flush()
                    logger.info(
                        "Purged %s terminal processing run(s) before deleting book %s",
                        len(processing_runs),
                        book_id,
                    )

                # Delete database record (cascades to source files, images, pages,
                # content blocks, and other aggregate-owned compatibility rows).
                db.delete(book)
                db.commit()
            except Exception:
                db.rollback()
                restore_deleted_sources("failed book metadata delete")
                raise

            logger.info(f"Deleted book: {book_id}")
            return True

        except BookDeletionConflict:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to delete book: {e}")
            raise


_book_service: BookService | None = None


def get_book_service() -> BookService:
    global _book_service
    if _book_service is None:
        _book_service = BookService()
    return _book_service
