"""PaddleOCR wrapper service."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import chardet
import numpy as np

logger = logging.getLogger(__name__)

# Suppress PaddleOCR verbose logging for version 3.7.0+
logging.getLogger("ppocr").setLevel(logging.WARNING)


@dataclass
class TextBlock:
    """Represents a detected text block with its properties."""
    text: str
    confidence: float
    box: list  # Coordinates [[x1,y1], [x2,y2], ...]
    block_type: str = "text"  # "text", "title", "table", "figure", etc.


@dataclass
class OCRExtractionResult:
    """Result of OCR extraction."""
    extracted_text: str
    confidence_score: float
    text_blocks: list[TextBlock] = field(default_factory=list)
    structure: Optional[dict] = None  # PP-Structure analysis result


class OCRService:
    def __init__(self) -> None:
        self._ocr_engine = None
        # Set PaddleOCR home directory
        os.environ['PADDLEOCR_HOME'] = '/tmp/paddleocr'

    def _build_engine(self) -> Any:
        try:
            from paddleocr import PaddleOCR
            logger.info("PaddleOCR imported successfully")
        except ImportError as e:
            logger.error(f"Failed to import PaddleOCR: {e}")
            raise RuntimeError("PaddleOCR is not installed") from e
        except Exception as e:
            logger.error(f"Error importing PaddleOCR: {e}")
            raise RuntimeError(f"PaddleOCR import failed: {e}") from e

        try:
            logger.info("Initializing PaddleOCR engine with lang='ch'...")
            # PaddleOCR 3.7.0 initialization
            # Note: show_log and use_gpu parameters were removed in 3.7.0
            # Logging is controlled via Python's logging module (see top of file)
            engine = PaddleOCR(lang="ch", use_angle_cls=True)
            logger.info("PaddleOCR engine initialized successfully")
            return engine
        except TypeError as e:
            # Try with minimal params for compatibility
            logger.warning(f"Initialization with use_angle_cls failed: {e}, trying lang only...")
            try:
                engine = PaddleOCR(lang="ch")
                logger.info("PaddleOCR engine initialized with lang='ch' only")
                return engine
            except Exception as e2:
                logger.error(f"Failed with lang='ch' only: {e2}")
                raise RuntimeError(f"Failed to initialize PaddleOCR: {e2}") from e2
        except Exception as e:
            logger.error(f"Unexpected error initializing PaddleOCR: {e}")
            raise RuntimeError(f"PaddleOCR initialization failed: {e}") from e

    def _ensure_engine(self) -> Any:
        if self._ocr_engine is None:
            logger.info("Building OCR engine...")
            self._ocr_engine = self._build_engine()
            logger.info("OCR engine ready")
        return self._ocr_engine

    def extract_text(self, file_path: str | Path) -> OCRExtractionResult:
        try:
            file_path = str(file_path)
            logger.info(f"Starting OCR extraction for: {file_path}")
            
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")
            
            engine = self._ensure_engine()
            logger.info("Calling PaddleOCR engine.ocr()...")
            
            # PaddleOCR 3.7.0 no longer supports 'cls' parameter
            ocr_result = engine.ocr(file_path)
            
            logger.info(f"Raw OCR result type: {type(ocr_result)}, length: {len(ocr_result) if ocr_result else 0}")

            texts: list[str] = []
            confidences: list[float] = []
            text_blocks: list[TextBlock] = []
            
            # PaddleOCR 3.7.0 returns a new format with 'rec_texts' and 'rec_scores'
            if isinstance(ocr_result, list) and len(ocr_result) > 0:
                item = ocr_result[0]
                if isinstance(item, dict):
                    texts = item.get('rec_texts', [])
                    confidences = item.get('rec_scores', [])
                    rec_boxes = item.get('rec_boxes', [])
                    logger.info(f"Extracted {len(texts)} text blocks from new format")
                    
                    # Create TextBlock objects with coordinate information
                    for i, text in enumerate(texts):
                        confidence = confidences[i] if i < len(confidences) else 0.0
                        box = rec_boxes[i].tolist() if i < len(rec_boxes) else []
                        text_blocks.append(
                            TextBlock(
                                text=text,
                                confidence=confidence,
                                box=box,
                                block_type="text"
                            )
                        )

            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            result = OCRExtractionResult(
                extracted_text="\n".join(texts).strip(),
                confidence_score=round(avg_confidence, 4),
                text_blocks=text_blocks,
            )
            logger.info(f"OCR completed: {len(texts)} text blocks, confidence: {avg_confidence:.4f}")
            return result
        except FileNotFoundError as e:
            logger.error(f"File error: {e}")
            raise RuntimeError(f"File error: {e}") from e
        except Exception as e:
            logger.error(f"Error during OCR extraction: {type(e).__name__}: {e}", exc_info=True)
            raise RuntimeError(f"OCR extraction failed: {e}") from e

    def extract_text_from_image(self, image: np.ndarray) -> str:
        """
        Extract text from a numpy image array using the OCR engine.

        This method accepts a pre-loaded image (e.g. a cropped layout block) as a
        numpy array rather than a file path, making it suitable for per-block OCR
        in the layout-aware PDF pipeline.

        Args:
            image: BGR or grayscale image as a numpy ndarray.

        Returns:
            Extracted text joined by newlines, or empty string on failure.
        """
        try:
            import cv2

            shape_info = image.shape if (image is not None and hasattr(image, "shape")) else "unknown"
            logger.info("Starting OCR on image array (%s)", shape_info)
            engine = self._ensure_engine()

            # Normalise to BGR (PaddleOCR expects BGR)
            if image.ndim == 2:
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            elif image.ndim == 3 and image.shape[2] == 4:
                image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

            ocr_result = engine.ocr(image)

            texts: list[str] = []
            if isinstance(ocr_result, list) and len(ocr_result) > 0:
                item = ocr_result[0]
                if isinstance(item, dict):
                    # PaddleOCR ≥ 3.7.0 new format
                    texts = item.get("rec_texts", [])
                elif isinstance(item, list):
                    # Legacy format: [[box, (text, conf)], ...]
                    for line in item:
                        if line and len(line) >= 2:
                            text_info = line[1]
                            if isinstance(text_info, (tuple, list)) and len(text_info) >= 1:
                                texts.append(str(text_info[0]))

            result = "\n".join(t for t in texts if t).strip()
            logger.info("Image OCR completed: %d text lines extracted", len(texts))
            return result

        except Exception as e:
            logger.error("Error during image OCR: %s: %s", type(e).__name__, e, exc_info=True)
            return ""

    def process_txt(self, file_path: str | Path) -> OCRExtractionResult:
        """Process a TXT file by reading its content directly with confidence 1.0.

        Args:
            file_path: Path to the TXT file

        Returns:
            OCRExtractionResult with the file content and confidence_score=1.0
        """
        try:
            file_path = str(file_path)
            logger.info(f"Processing TXT file: {file_path}")

            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")

            with open(file_path, "rb") as f:
                raw_data = f.read()

            detection = chardet.detect(raw_data[:10000])
            detected_encoding = detection.get("encoding") or "utf-8"
            logger.info(
                "Detected TXT encoding %s (confidence=%s)",
                detected_encoding,
                detection.get("confidence"),
            )

            candidate_encodings: list[str] = []
            for encoding in (
                detected_encoding,
                "utf-8-sig",
                "utf-8",
                "gb18030",
                "gbk",
                "gb2312",
                "latin-1",
            ):
                normalized = encoding.lower()
                if normalized not in candidate_encodings:
                    candidate_encodings.append(normalized)

            content = ""
            used_encoding = detected_encoding
            for encoding in candidate_encodings:
                try:
                    content = raw_data.decode(encoding)
                    used_encoding = encoding
                    break
                except UnicodeDecodeError:
                    continue
            else:
                used_encoding = candidate_encodings[0]
                logger.warning(
                    "Strict TXT decoding failed for all candidate encodings; "
                    "falling back to %s with errors='ignore'",
                    used_encoding,
                )
                content = raw_data.decode(used_encoding, errors="ignore")

            logger.info("Read TXT file using encoding: %s", used_encoding)

            lines = [line for line in content.split("\n") if line.strip()]
            text_blocks = [
                TextBlock(text=line, confidence=1.0, box=[], block_type="text")
                for line in lines
            ]

            result = OCRExtractionResult(
                extracted_text=content,
                confidence_score=1.0,
                text_blocks=text_blocks,
            )
            logger.info(f"TXT processing completed: {len(lines)} lines")
            return result
        except FileNotFoundError as e:
            logger.error(f"File error: {e}")
            raise RuntimeError(f"File error: {e}") from e
        except Exception as e:
            logger.error(f"Error during TXT processing: {type(e).__name__}: {e}", exc_info=True)
            raise RuntimeError(f"TXT processing failed: {e}") from e

    def structure_analysis(self, file_path: str | Path) -> OCRExtractionResult:
        """Perform document structure analysis by processing OCR results.
        
        Returns OCR results with structure metadata. Will be enhanced with
        create_pipeline once it becomes available in future PaddleOCR versions.
        """
        try:
            file_path = str(file_path)
            logger.info(f"Starting structure analysis for: {file_path}")
            
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")
            
            # First, get OCR results with text blocks and coordinates
            ocr_result = self.extract_text(file_path)
            
            # Add simple structure analysis: categorize blocks by position
            # Could be enhanced later with create_pipeline for more sophisticated layout analysis
            structure_info = {
                "total_blocks": len(ocr_result.text_blocks),
                "blocks_by_type": {},
                "analysis_method": "coordinate-based"
            }
            
            logger.info(f"Structure analysis completed: {len(ocr_result.text_blocks)} blocks")
            
            return OCRExtractionResult(
                extracted_text=ocr_result.extracted_text,
                confidence_score=ocr_result.confidence_score,
                text_blocks=ocr_result.text_blocks,
                structure=structure_info,
            )
        except FileNotFoundError as e:
            logger.error(f"File error: {e}")
            raise RuntimeError(f"File error: {e}") from e
        except Exception as e:
            logger.error(f"Error during structure analysis: {type(e).__name__}: {e}", exc_info=True)
            raise RuntimeError(f"Structure analysis failed: {e}") from e


_ocr_service: OCRService | None = None


def get_ocr_service() -> OCRService:
    global _ocr_service
    if _ocr_service is None:
        _ocr_service = OCRService()
    return _ocr_service
