"""PDF processing service - handles the complete extraction workflow."""

from __future__ import annotations

import logging
import hashlib
import uuid
from typing import Optional, List, Tuple
from pathlib import Path
import io

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class ImageStorageService:
    """Handle image storage and ID generation."""

    @staticmethod
    def generate_image_id(image_data: np.ndarray) -> str:
        """
        Generate image ID using SHA256 hash of image data.

        Args:
            image_data: Image as numpy array

        Returns:
            Image ID as "img_<sha256_hash>"
        """
        try:
            # Convert image to bytes
            img_bytes = image_data.tobytes()
            # Compute SHA256 hash
            hash_obj = hashlib.sha256(img_bytes)
            hash_hex = hash_obj.hexdigest()[:16]  # Use first 16 chars
            image_id = f"img_{hash_hex}"
            return image_id
        except Exception as e:
            logger.error(f"Failed to generate image ID: {e}")
            # Fallback to UUID
            return f"img_{uuid.uuid4().hex[:16]}"

    @staticmethod
    def encode_image_to_png(image_data: np.ndarray) -> Tuple[bytes, int]:
        """
        Encode image to PNG format.

        Args:
            image_data: Image as numpy array (BGR or grayscale)

        Returns:
            Tuple of (PNG bytes, file size in bytes)
        """
        try:
            # If image is BGR, convert to RGB for PNG
            if len(image_data.shape) == 3 and image_data.shape[2] == 3:
                image_rgb = cv2.cvtColor(image_data, cv2.COLOR_BGR2RGB)
            else:
                image_rgb = image_data

            # Encode to PNG
            success, encoded = cv2.imencode('.png', image_rgb)
            if not success:
                raise ValueError("Failed to encode image to PNG")

            png_bytes = encoded.tobytes()
            size = len(png_bytes)

            logger.debug(f"Image encoded to PNG: {size} bytes")
            return png_bytes, size

        except Exception as e:
            logger.error(f"Failed to encode image to PNG: {e}")
            raise

    @staticmethod
    def save_image_file(image_data: np.ndarray, save_path: Path) -> None:
        """
        Save image to file system as PNG.

        Args:
            image_data: Image as numpy array
            save_path: Path to save PNG file
        """
        try:
            save_path = Path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)

            if len(image_data.shape) == 3 and image_data.shape[2] == 3:
                image_rgb = cv2.cvtColor(image_data, cv2.COLOR_BGR2RGB)
            else:
                image_rgb = image_data

            cv2.imwrite(str(save_path), image_rgb)
            logger.debug(f"Image saved to file: {save_path}")

        except Exception as e:
            logger.error(f"Failed to save image file: {e}")
            raise


class PDFProcessingService:
    """Main service for processing PDFs with layout analysis."""

    def __init__(self):
        """Initialize PDF processing service."""
        self._enhanced_pdf_service = None
        self._ocr_service = None
        self._image_storage = ImageStorageService()

    def _get_enhanced_pdf_service(self):
        """Get enhanced PDF service."""
        if self._enhanced_pdf_service is None:
            from app.enhanced_pdf_service import get_enhanced_pdf_service
            self._enhanced_pdf_service = get_enhanced_pdf_service()
        return self._enhanced_pdf_service

    def _get_ocr_service(self):
        """Get OCR service."""
        if self._ocr_service is None:
            from app.ocr_service import get_ocr_service
            self._ocr_service = get_ocr_service()
        return self._ocr_service

    def process_text_block(self, block_image: np.ndarray) -> str:
        """
        Process text block using PaddleOCR.

        Args:
            block_image: Cropped text block image

        Returns:
            Extracted text
        """
        try:
            ocr_service = self._get_ocr_service()

            # OCR expects BGR image
            if len(block_image.shape) == 2:
                # Convert grayscale to BGR
                block_image = cv2.cvtColor(block_image, cv2.COLOR_GRAY2BGR)

            # Use extract_text_from_image which accepts a numpy array
            text = ocr_service.extract_text_from_image(block_image)
            logger.debug(f"Text extracted: {len(text)} characters")
            return text

        except Exception as e:
            logger.error(f"Failed to process text block: {e}")
            return ""

    def process_image_block(self, block_image: np.ndarray, 
                           page_num: int, block_index: int,
                           bbox: tuple) -> Tuple[str, bytes, int]:
        """
        Process image/table block (save as PNG).

        Args:
            block_image: Cropped block image
            page_num: Page number
            block_index: Block index in page
            bbox: Bounding box coordinates

        Returns:
            Tuple of (image_id, PNG bytes, file size)
        """
        try:
            # Generate image ID using hash
            image_id = self._image_storage.generate_image_id(block_image)
            
            # Encode to PNG
            png_bytes, size = self._image_storage.encode_image_to_png(block_image)
            
            logger.debug(f"Image block processed: {image_id}, {size} bytes")
            return image_id, png_bytes, size

        except Exception as e:
            logger.error(f"Failed to process image block: {e}")
            raise

    def process_pdf_file(self, pdf_path: str | Path) -> dict:
        """
        Process complete PDF file.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Processing result dictionary
        """
        try:
            pdf_path = str(pdf_path)
            enhanced_pdf_service = self._get_enhanced_pdf_service()
            
            logger.info(f"Starting PDF processing: {pdf_path}")
            
            result = {
                "pdf_path": pdf_path,
                "status": "success",
                "total_pages": 0,
                "pages_processed": 0,
                "pages_failed": 0,
                "total_text_blocks": 0,
                "total_image_blocks": 0,
                "total_text_characters": 0,
                "total_image_bytes": 0,
                "failed_pages": [],
                "page_results": []
            }
            
            try:
                # Process entire PDF
                page_layouts = enhanced_pdf_service.process_pdf(
                    pdf_path,
                    dpi=300,
                )
                
                result["total_pages"] = len(page_layouts)
                
                for page_layout in page_layouts:
                    try:
                        page_result = self._process_page(page_layout)
                        result["page_results"].append(page_result)
                        result["pages_processed"] += 1
                        result["total_text_blocks"] += page_result["text_blocks"]
                        result["total_image_blocks"] += page_result["image_blocks"]
                        result["total_text_characters"] += page_result["text_characters"]
                        result["total_image_bytes"] += page_result["image_bytes"]
                        
                    except Exception as e:
                        logger.error(f"Failed to process page {page_layout.page_num}: {e}")
                        result["pages_failed"] += 1
                        result["failed_pages"].append({
                            "page_num": page_layout.page_num,
                            "error": str(e)
                        })
                        # Continue to next page
                        continue
                
                logger.info(f"PDF processing completed:")
                logger.info(f"  - Pages processed: {result['pages_processed']}/{result['total_pages']}")
                logger.info(f"  - Text blocks: {result['total_text_blocks']}")
                logger.info(f"  - Image blocks: {result['total_image_blocks']}")
                logger.info(f"  - Total text: {result['total_text_characters']} characters")
                logger.info(f"  - Total images: {result['total_image_bytes']} bytes")
                
            except Exception as e:
                logger.error(f"Error processing PDF: {e}")
                result["status"] = "error"
                result["error"] = str(e)
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to process PDF file: {e}")
            raise

    def _process_page(self, page_layout) -> dict:
        """
        Process a single page layout.

        Args:
            page_layout: PageLayout object

        Returns:
            Page processing result
        """
        page_result = {
            "page_num": page_layout.page_num,
            "total_blocks": len(page_layout.blocks),
            "text_blocks": 0,
            "image_blocks": 0,
            "text_characters": 0,
            "image_bytes": 0,
            "blocks": []
        }
        
        logger.info(f"Processing page {page_layout.page_num + 1}: {len(page_layout.blocks)} blocks")
        
        for block_index, block in enumerate(page_layout.blocks):
            try:
                block_result = {
                    "block_index": block_index,
                    "block_type": block.block_type,
                    "bbox": block.bbox,
                    "confidence": block.confidence
                }
                
                if block.block_type == "text":
                    # Process text block
                    text = self.process_text_block(block.image_data)
                    block_result["content"] = text
                    block_result["content_type"] = "text"
                    block_result["size"] = len(text)
                    
                    page_result["text_blocks"] += 1
                    page_result["text_characters"] += len(text)
                    
                    logger.debug(f"  Text block {block_index}: {len(text)} chars")
                    
                elif block.block_type in ["image", "table"]:
                    # Process image/table block
                    image_id, png_bytes, size = self.process_image_block(
                        block.image_data,
                        page_layout.page_num,
                        block_index,
                        block.bbox
                    )
                    block_result["image_id"] = image_id
                    block_result["image_data"] = png_bytes
                    block_result["image_size"] = size
                    block_result["content_type"] = "image"
                    
                    page_result["image_blocks"] += 1
                    page_result["image_bytes"] += size
                    
                    logger.debug(f"  {block.block_type.title()} block {block_index}: {image_id}, {size} bytes")
                
                page_result["blocks"].append(block_result)
                
            except Exception as e:
                logger.error(f"Error processing block {block_index} on page {page_layout.page_num}: {e}")
                # Continue to next block
                continue
        
        return page_result


# Singleton instance
_pdf_processing_service: PDFProcessingService | None = None


def get_pdf_processing_service() -> PDFProcessingService:
    """Get or create PDF processing service singleton."""
    global _pdf_processing_service
    if _pdf_processing_service is None:
        _pdf_processing_service = PDFProcessingService()
    return _pdf_processing_service
