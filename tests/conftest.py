"""Shared test fixtures and utilities for Phase 2 integration tests."""

import pytest
import tempfile
from pathlib import Path
from typing import Generator
import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.services.database_service import DatabaseService


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """Get test database URL."""
    return "sqlite:///:memory:"


@pytest.fixture
def test_db_service() -> Generator[DatabaseService, None, None]:
    """Create a fresh database service for each test."""
    # Use in-memory SQLite database
    db_service = DatabaseService("sqlite:///:memory:")
    yield db_service
    # Cleanup is automatic with in-memory database


@pytest.fixture
def test_pdf_path() -> Generator[str, None, None]:
    """Create a minimal test PDF file."""
    # This fixture assumes a test PDF exists in test_samples directory
    test_samples_dir = Path(__file__).parent.parent / "test_samples"
    pdf_files = list(test_samples_dir.glob("*.pdf")) + list(test_samples_dir.glob("*.PDF"))
    
    if pdf_files:
        yield str(pdf_files[0])
    else:
        pytest.skip("No test PDF found in test_samples directory")


@pytest.fixture
def sample_book_data() -> dict:
    """Sample book data for testing."""
    return {
        "title": "Test Book",
        "author": "Test Author",
        "total_pages": 10
    }


@pytest.fixture
def sample_text_block() -> dict:
    """Sample text block data for testing."""
    return {
        "page_num": 0,
        "block_index": 0,
        "block_type": "text",
        "content": "This is test text content",
        "bbox": (10, 10, 500, 100),
        "confidence": 0.95
    }


@pytest.fixture
def sample_image_block() -> dict:
    """Sample image block data for testing."""
    import numpy as np
    
    # Create a simple test image (100x100 pixels)
    img = np.ones((100, 100, 3), dtype=np.uint8) * 200
    img_bytes = img.tobytes()
    
    return {
        "image_id": "img_test123456789",
        "image_data": img_bytes,
        "image_format": "png",
        "page_num": 0,
        "bbox": (10, 10, 200, 200),
        "block_type": "image"
    }
