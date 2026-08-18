"""Database service for storing PDF processing results."""

from __future__ import annotations

import logging
import uuid
from typing import Optional, List
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from app.models import Base, Document, DocumentType, ContentBlock, BookImage

logger = logging.getLogger(__name__)


class DatabaseService:
    """Handle database operations for PDF processing."""

    def __init__(self, database_url: str = "sqlite:///./test.db"):
        """
        Initialize database service.

        Args:
            database_url: SQLAlchemy database URL
        """
        self.database_url = database_url
        self.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False} if "sqlite" in database_url else {}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # This standalone service is used by isolated tests with in-memory
        # SQLite. Production application startup applies Alembic migrations via
        # app.database.init_db(); create_all is retained here only for the
        # temporary isolated test-only path.
        if database_url == "sqlite:///:memory:":
            Base.metadata.create_all(bind=self.engine)
        logger.info(f"Database session factory initialized: {database_url}")

    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()

    def create_book(self, title: str, author: Optional[str] = None,
                   total_pages: int = 0, processed_file_path: str = "") -> str:
        """
        Create a new book record.

        Args:
            title: Book title
            author: Author name
            total_pages: Total page count
            processed_file_path: Path to processed file

        Returns:
            Book ID
        """
        session = None
        try:
            session = self.get_session()
            book_id = str(uuid.uuid4())
            
            book = Document(
                id=book_id,
                document_type=DocumentType.BOOK,
                title=title,
                author=author,
                pages_count=total_pages,
                processed_file_path=processed_file_path if processed_file_path else None,
                status="completed" if processed_file_path else "processing",
                file_type="",
            )
            
            session.add(book)
            session.commit()
            
            logger.info(f"Book created: {book_id} - {title}")
            return book_id
            
        except SQLAlchemyError as e:
            if session:
                session.rollback()
            logger.error(f"Failed to create book: {e}")
            raise
        finally:
            if session:
                session.close()

    def save_content_block(self, book_id: str, page_num: int,
                          block_index: int, block_type: str,
                          content: str, bbox: tuple,
                          confidence: float = 1.0) -> str:
        """
        Save a content block (text/image reference).

        Args:
            book_id: Book ID
            page_num: Page number
            block_index: Block index in page
            block_type: Block type (text, image, table)
            content: Text content or image ID
            bbox: Bounding box (x1, y1, x2, y2)
            confidence: Confidence score

        Returns:
            Content block ID
        """
        session = None
        try:
            session = self.get_session()
            block_id = str(uuid.uuid4())
            
            # Convert bbox tuple to string
            bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
            
            content_block = ContentBlock(
                id=block_id,
                book_id=book_id,
                page_num=page_num,
                block_index=block_index,
                block_type=block_type,
                content=content,
                bbox=bbox_str,
                confidence=confidence
            )
            
            session.add(content_block)
            session.commit()
            
            logger.debug(f"Content block saved: {block_id} (type={block_type}, page={page_num})")
            return block_id
            
        except SQLAlchemyError as e:
            if session:
                session.rollback()
            logger.error(f"Failed to save content block: {e}")
            raise
        finally:
            if session:
                session.close()

    def save_book_image(self, book_id: str, image_id: str,
                       image_data: bytes, image_format: str = "png",
                       page_num: Optional[int] = None,
                       bbox: Optional[tuple] = None,
                       block_type: Optional[str] = None) -> str:
        """
        Save a book image (extracted image or table).

        Args:
            book_id: Book ID
            image_id: Image ID (hash-based)
            image_data: PNG image bytes
            image_format: Image format (default: png)
            page_num: Original page number
            bbox: Bounding box coordinates
            block_type: Block type (image or table)

        Returns:
            BookImage ID
        """
        session = None
        try:
            session = self.get_session()
            db_id = str(uuid.uuid4())
            
            # Convert bbox to string if provided
            bbox_str = None
            if bbox:
                bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
            
            book_image = BookImage(
                id=db_id,
                book_id=book_id,
                image_id=image_id,
                image_format=image_format,
                image_data=image_data,
                image_size=len(image_data),
                page_num=page_num,
                bbox=bbox_str,
                block_type=block_type
            )
            
            session.add(book_image)
            session.commit()
            
            logger.debug(f"Book image saved: {db_id} (image_id={image_id}, size={len(image_data)} bytes)")
            return db_id
            
        except SQLAlchemyError as e:
            if session:
                session.rollback()
            logger.error(f"Failed to save book image: {e}")
            raise
        finally:
            if session:
                session.close()

    def get_book(self, book_id: str) -> Optional[Document]:
        """
        Retrieve book record.

        Args:
            book_id: Book ID

        Returns:
            Document object or None
        """
        session = None
        try:
            session = self.get_session()
            book = session.query(Document).filter(Document.id == book_id).first()
            return book
        except SQLAlchemyError as e:
            logger.error(f"Failed to get book: {e}")
            return None
        finally:
            if session:
                session.close()

    def get_book_content_blocks(self, book_id: str, page_num: Optional[int] = None) -> List[ContentBlock]:
        """
        Get content blocks for a book.

        Args:
            book_id: Book ID
            page_num: Filter by page number (optional)

        Returns:
            List of ContentBlock objects
        """
        session = None
        try:
            session = self.get_session()
            query = session.query(ContentBlock).filter(ContentBlock.book_id == book_id)
            
            if page_num is not None:
                query = query.filter(ContentBlock.page_num == page_num)
            
            blocks = query.order_by(ContentBlock.page_num, ContentBlock.block_index).all()
            return blocks
            
        except SQLAlchemyError as e:
            logger.error(f"Failed to get content blocks: {e}")
            return []
        finally:
            if session:
                session.close()

    def get_book_images(self, book_id: str, page_num: Optional[int] = None) -> List[BookImage]:
        """
        Get images for a book.

        Args:
            book_id: Book ID
            page_num: Filter by page number (optional)

        Returns:
            List of BookImage objects
        """
        session = None
        try:
            session = self.get_session()
            query = session.query(BookImage).filter(BookImage.book_id == book_id)
            
            if page_num is not None:
                query = query.filter(BookImage.page_num == page_num)
            
            images = query.order_by(BookImage.page_num).all()
            return images
            
        except SQLAlchemyError as e:
            logger.error(f"Failed to get book images: {e}")
            return []
        finally:
            if session:
                session.close()

    def get_image_by_id(self, image_id: str) -> Optional[BookImage]:
        """
        Get image by image_id.

        Args:
            image_id: Image ID

        Returns:
            BookImage object or None
        """
        session = None
        try:
            session = self.get_session()
            image = session.query(BookImage).filter(BookImage.image_id == image_id).first()
            return image
            
        except SQLAlchemyError as e:
            logger.error(f"Failed to get image: {e}")
            return None
        finally:
            if session:
                session.close()


# Singleton instance
_database_service: DatabaseService | None = None


def get_database_service(database_url: str = "sqlite:///./test.db") -> DatabaseService:
    """Get or create database service singleton."""
    global _database_service
    if _database_service is None:
        _database_service = DatabaseService(database_url)
    return _database_service
