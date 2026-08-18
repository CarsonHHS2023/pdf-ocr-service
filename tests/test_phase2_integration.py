"""Heavy integration tests for Phase 2 - slow, manual run, real libraries.

These tests require actual PDF files and use real libraries (PyMuPDF, PaddleOCR, etc.).
Run manually for acceptance testing: pytest tests/test_phase2_integration.py -v -s -m slow
"""

import pytest
from pathlib import Path
from typing import Optional
import numpy as np

from app.services.pdf_processing_service import get_pdf_processing_service
from app.services.database_service import get_database_service, DatabaseService


pytestmark = pytest.mark.slow  # Mark all tests as slow/integration


class TestPDFProcessingServiceIntegration:
    """Test PDF processing with real libraries."""

    def test_service_initialization(self):
        """Test PDF processing service initialization."""
        service = get_pdf_processing_service()
        assert service is not None
        print(f"✓ PDF processing service initialized")

    def test_process_text_block_real(self):
        """Test processing a text block with real OCR."""
        service = get_pdf_processing_service()
        
        # Create a simple text-like image
        img = np.ones((100, 200, 3), dtype=np.uint8) * 255
        # Add some dark pixels to simulate text
        img[40:60, 50:150] = 50
        
        text = service.process_text_block(img)
        
        # Should return a string (even if empty due to no real text)
        assert isinstance(text, str)
        print(f"✓ Text block processed (text length: {len(text)})")

    def test_process_image_block_real(self):
        """Test processing an image block with real PNG encoding."""
        service = get_pdf_processing_service()
        
        # Create test image
        img = np.ones((100, 100, 3), dtype=np.uint8) * 200
        
        image_id, png_bytes, size = service.process_image_block(
            img, page_num=0, block_index=0, bbox=(0, 0, 100, 100)
        )
        
        assert image_id is not None
        assert image_id.startswith("img_")
        assert isinstance(png_bytes, bytes)
        assert size > 0
        # Verify PNG format
        assert png_bytes[:4] == b'\x89PNG'
        print(f"✓ Image block processed: {image_id}, {size} bytes")

    def test_process_pdf_file_with_valid_pdf(self, test_pdf_path: Optional[str]):
        """Test processing a complete PDF file."""
        if test_pdf_path is None:
            pytest.skip("No test PDF available")
        
        service = get_pdf_processing_service()
        
        result = service.process_pdf_file(test_pdf_path)
        
        assert result is not None
        assert result["status"] in ["success", "error"]
        assert result["total_pages"] > 0
        assert result["pages_processed"] >= 0
        assert isinstance(result["page_results"], list)
        
        print(f"✓ PDF processed:")
        print(f"  - Total pages: {result['total_pages']}")
        print(f"  - Pages processed: {result['pages_processed']}")
        print(f"  - Text blocks: {result['total_text_blocks']}")
        print(f"  - Image blocks: {result['total_image_blocks']}")


class TestCompleteWorkflowIntegration:
    """Test complete end-to-end workflow with real PDF."""

    def test_pdf_to_database_complete_workflow(self, test_db_service: DatabaseService, 
                                               test_pdf_path: Optional[str]):
        """Test complete workflow from PDF processing to database storage."""
        if test_pdf_path is None:
            pytest.skip("No test PDF available")
        
        print(f"\n{'='*80}")
        print(f"🔄 Complete Workflow Integration Test")
        print(f"{'='*80}")
        
        # Step 1: Process PDF
        print(f"\n1️⃣ Processing PDF...")
        pdf_service = get_pdf_processing_service()
        processing_result = pdf_service.process_pdf_file(test_pdf_path)
        
        assert processing_result["status"] == "success"
        assert processing_result["pages_processed"] > 0
        print(f"   ✓ PDF processed: {processing_result['pages_processed']} pages")
        
        # Step 2: Create book record
        print(f"\n2️⃣ Creating book record...")
        book_id = test_db_service.create_book(
            title="Integration Test PDF",
            total_pages=processing_result["total_pages"]
        )
        assert book_id is not None
        print(f"   ✓ Book created: {book_id}")
        
        # Step 3: Save blocks to database
        print(f"\n3️⃣ Saving blocks to database...")
        text_blocks_count = 0
        image_blocks_count = 0
        
        for page_result in processing_result["page_results"]:
            for block_result in page_result["blocks"]:
                if block_result["content_type"] == "text":
                    test_db_service.save_content_block(
                        book_id=book_id,
                        page_num=page_result["page_num"],
                        block_index=block_result["block_index"],
                        block_type=block_result["block_type"],
                        content=block_result.get("content", ""),
                        bbox=block_result["bbox"],
                        confidence=block_result["confidence"]
                    )
                    text_blocks_count += 1
                
                elif block_result["content_type"] == "image":
                    image_id = block_result["image_id"]
                    png_data = block_result["image_data"]
                    
                    test_db_service.save_book_image(
                        book_id=book_id,
                        image_id=image_id,
                        image_data=png_data,
                        image_format="png",
                        page_num=page_result["page_num"],
                        bbox=block_result["bbox"],
                        block_type=block_result["block_type"]
                    )
                    image_blocks_count += 1
        
        print(f"   ✓ Saved {text_blocks_count} text blocks")
        print(f"   ✓ Saved {image_blocks_count} image blocks")
        
        # Step 4: Verify data retrieval
        print(f"\n4️⃣ Verifying data retrieval...")
        
        # Check book
        book = test_db_service.get_book(book_id)
        assert book is not None
        print(f"   ✓ Book retrieved: {book.book_title}")
        
        # Check content blocks
        content_blocks = test_db_service.get_book_content_blocks(book_id)
        assert len(content_blocks) == text_blocks_count + image_blocks_count
        print(f"   ✓ All {len(content_blocks)} blocks retrieved")
        
        # Check images
        images = test_db_service.get_book_images(book_id)
        assert len(images) == image_blocks_count
        print(f"   ✓ All {len(images)} images retrieved")
        
        print(f"\n{'='*80}")
        print(f"✅ Complete workflow integration test verified!")
        print(f"{'='*80}\n")


class TestPDFProcessingErrorRecoveryIntegration:
    """Test error recovery in PDF processing."""

    def test_page_error_recovery(self, test_pdf_path: Optional[str]):
        """Test that PDF processing continues despite page errors."""
        if test_pdf_path is None:
            pytest.skip("No test PDF available")
        
        service = get_pdf_processing_service()
        result = service.process_pdf_file(test_pdf_path)
        
        # Verify processing continued despite any errors
        assert result["pages_processed"] > 0
        assert result["total_pages"] > 0
        assert result["pages_processed"] + result["pages_failed"] == result["total_pages"]
        
        if result["pages_failed"] > 0:
            print(f"✓ PDF processing recovered from {result['pages_failed']} failed pages")
            print(f"  Failed pages: {result['failed_pages']}")
        else:
            print(f"✓ All pages processed successfully")

    def test_image_hash_uniqueness_real(self):
        """Test that hash-based image IDs are unique for different images."""
        service = get_pdf_processing_service()
        
        # Create different images
        img1 = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        img2 = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        
        id1, _, _ = service.process_image_block(img1, 0, 0, (0, 0, 100, 100))
        id2, _, _ = service.process_image_block(img2, 0, 1, (0, 0, 100, 100))
        
        # Different images should have different IDs
        assert id1 != id2
        print(f"✓ Different images have unique IDs")
        print(f"  ID1: {id1}")
        print(f"  ID2: {id2}")
