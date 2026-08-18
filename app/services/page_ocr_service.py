"""Per-page PaddleOCR-VL processing service.

Each PDF page is processed independently so that:
- Pages can be tracked individually in the database.
- Failures are isolated to a single page.
- The pipeline can be scheduled asynchronously (one page at a time) without
  blocking the HTTP layer.

Workflow (run as a FastAPI BackgroundTask):
1. Retrieve all PdfPage records for *book_id* with status=pending.
2. For each page (in order), load the stored PNG image, run PaddleOCR-VL
   predict(), and write the raw JSON back to PdfPage.ocr_raw_json.
3. If any page fails mark the book as failed and delete the page records
   (satisfying requirements 1 & 2).
4. On full success, call MineruPopoService to post-process all page results
   and store the structured output in MineruResult.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np

from app.database import SessionLocal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Single-page OCR
# ---------------------------------------------------------------------------


def _normalize_block_bbox_for_json(bbox: Any) -> Any:
    """Normalize block bbox values for JSON serialization."""
    if bbox is None:
        return []

    if hasattr(bbox, "tolist"):
        bbox = bbox.tolist()
    elif isinstance(bbox, tuple):
        bbox = list(bbox)
    elif not isinstance(bbox, list):
        try:
            bbox = list(bbox)
        except TypeError:
            return bbox

    if (
        isinstance(bbox, list)
        and len(bbox) == 4
        and isinstance(bbox[0], (list, tuple))
        and all(isinstance(pt, (list, tuple)) and len(pt) == 2 for pt in bbox)
    ):
        return [[int(v) for v in pt] for pt in bbox]
    return bbox


def _serialize_parsing_res_list(parsing_res_list: list[Any]) -> list[dict[str, Any]]:
    """Convert PaddleOCR-VL blocks (or raw dicts) to JSON-serializable dicts."""
    result: list[dict[str, Any]] = []
    for block in parsing_res_list:
        if hasattr(block, "label"):
            bbox = _normalize_block_bbox_for_json(getattr(block, "bbox", None))

            result.append(
                {
                    "block_label": getattr(block, "label", ""),
                    "block_bbox": bbox,
                    "block_content": getattr(block, "content", None) or "",
                    "block_id": getattr(block, "global_block_id", None),
                    "block_order": getattr(block, "global_group_id", None),
                }
            )
        elif isinstance(block, dict):
            block_copy = dict(block)
            block_copy["block_bbox"] = _normalize_block_bbox_for_json(
                block_copy.get("block_bbox")
            )
            result.append(block_copy)
        else:
            logger.warning("Skipping unknown block type: %s", type(block))
    return result

class PageOCRService:
    """Wraps PaddleOCR-VL for single-page inference."""

    def __init__(self) -> None:
        self._pipeline: Any = None
        self._initialized = False

    def _get_pipeline(self) -> Any:
        if not self._initialized:
            try:
                from paddleocr import PaddleOCRVL  # type: ignore[import]
                self._pipeline = PaddleOCRVL(pipeline_version="v1.6")
                logger.info("PaddleOCR-VL 1.6 pipeline initialized (PageOCRService)")
            except ImportError as exc:
                logger.error("PaddleOCR-VL not available: %s", exc)
                self._pipeline = None
            except Exception as exc:
                logger.error("PaddleOCR-VL init error: %s", exc, exc_info=True)
                self._pipeline = None
            self._initialized = True
        return self._pipeline

    def process_page_bytes(self, page_png_bytes: bytes) -> dict:
        """Run PaddleOCR-VL on a single page and return the raw result dict.

        Args:
            page_png_bytes: PNG-encoded page image bytes.

        Returns:
            Dict with key ``parsing_res_list``.

        Raises:
            RuntimeError: if PaddleOCR-VL is unavailable.
            Exception:    if prediction fails.
        """
        import cv2  # type: ignore[import]

        pipeline = self._get_pipeline()
        if pipeline is None:
            raise RuntimeError(
                "PaddleOCR-VL is not available. "
                "Install 'paddleocr[doc-parser]' to enable."
            )

        nparr = np.frombuffer(page_png_bytes, dtype=np.uint8)
        img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise ValueError("Failed to decode page image bytes")

        raw_output = list(pipeline.predict([img_bgr]))
        try:
            res_data: dict = dict(raw_output[0])
        except Exception as exc:
            logger.warning(
                "Failed to convert predict output to dict (type=%s): %s",
                type(raw_output[0]) if raw_output else "empty",
                exc,
            )
            res_data = {}

        parsing_res_list = res_data.get("parsing_res_list", [])
        if not parsing_res_list:
            logger.warning(
                "parsing_res_list is empty for page. res_data keys: %s",
                list(res_data.keys()),
            )

        return res_data


# Module-level singleton so the pipeline is initialised only once per process.
_page_ocr_service: PageOCRService | None = None


def get_page_ocr_service() -> PageOCRService:
    global _page_ocr_service
    if _page_ocr_service is None:
        _page_ocr_service = PageOCRService()
    return _page_ocr_service


# ---------------------------------------------------------------------------
# Background book-processing function
# ---------------------------------------------------------------------------

def process_book_background(book_id: str) -> None:
    """Background task: OCR each page then run MinerU-Popo post-processing.

    This function is designed to be passed to FastAPI's BackgroundTasks.  It
    creates its own database session so it can run after the HTTP response has
    been sent.

    On any per-page failure the book is marked failed and the PdfPage records
    are deleted from the database.  The original PDF file has already been
    deleted by the upload endpoint before this function is called.
    """
    from app.models import Document, PdfPage, MineruResult  # avoid circular import

    db = SessionLocal()
    try:
        pages = (
            db.query(PdfPage)
            .filter(PdfPage.book_id == book_id, PdfPage.status == "pending")
            .order_by(PdfPage.page_num)
            .all()
        )

        if not pages:
            logger.warning("No pending pages found for book %s", book_id)
            _mark_book_failed(db, book_id, "No pages found to process")
            return

        ocr_service = get_page_ocr_service()
        failed_page_num: int | None = None
        failed_error_message = ""

        # ── Process pages one at a time ──────────────────────────────────────
        for page in pages:
            page_num = page.page_num
            try:
                page.status = "processing"
                db.commit()

                if not page.page_image_data:
                    raise ValueError(f"Page {page_num} has no image data")

                res_data = ocr_service.process_page_bytes(page.page_image_data)

                # Store raw JSON: attach page dimensions for MinerU-Popo
                payload = {
                    "page_num": page_num,
                    "page_width": page.page_width or 0,
                    "page_height": page.page_height or 0,
                    "parsing_res_list": _serialize_parsing_res_list(
                        res_data.get("parsing_res_list", [])
                    ),
                }
                page.ocr_raw_json = json.dumps(payload, ensure_ascii=False)
                page.status = "completed"
                db.commit()

                logger.info(
                    "Book %s page %d OCR completed (%d blocks)",
                    book_id,
                    page_num,
                    len(payload["parsing_res_list"]),
                )

            except Exception as exc:
                logger.error(
                    "Book %s page %d OCR failed: %s",
                    book_id,
                    page_num,
                    exc,
                    exc_info=True,
                )
                # Rollback first so the session is clean (the previous commit or
                # flush may have left it in a rolled-back / dirty state).
                try:
                    db.rollback()
                except Exception as rb_exc:
                    logger.debug("Rollback failed (ignored): %s", rb_exc)
                # Re-query the page object because rollback detaches it.
                try:
                    fresh_page = db.query(PdfPage).filter(
                        PdfPage.book_id == book_id,
                        PdfPage.page_num == page_num,
                    ).first()
                    if fresh_page:
                        fresh_page.status = "failed"
                        fresh_page.error_message = str(exc)
                        db.commit()
                except Exception as inner:
                    logger.error("Could not update page status: %s", inner)
                    try:
                        db.rollback()
                    except Exception as rb_exc:
                        logger.debug("Rollback failed (ignored): %s", rb_exc)
                failed_page_num = page_num
                failed_error_message = str(exc)
                break  # stop immediately; no fallback

        if failed_page_num is not None:
            # Ensure the session is clean before the bulk delete.
            try:
                db.rollback()
            except Exception as rb_exc:
                logger.debug("Rollback failed (ignored): %s", rb_exc)
            try:
                # Delete all PdfPage records for this book (requirement 2)
                db.query(PdfPage).filter(PdfPage.book_id == book_id).delete()
                db.commit()
            except Exception as e:
                logger.error("Could not delete pages for book %s: %s", book_id, e)
                try:
                    db.rollback()
                except Exception as rb_exc:
                    logger.debug("Rollback failed (ignored): %s", rb_exc)
            _mark_book_failed(
                db,
                book_id,
                f"Page {failed_page_num} OCR failed: {failed_error_message}",
            )
            return

        # ── All pages OCR'd successfully; run MinerU-Popo ───────────────────
        try:
            all_pages = (
                db.query(PdfPage)
                .filter(PdfPage.book_id == book_id)
                .order_by(PdfPage.page_num)
                .all()
            )

            from app.services.mineru_popo_service import get_mineru_popo_service
            mineru = get_mineru_popo_service()

            result_json_str = mineru.process(book_id=book_id, pages=all_pages, db=db)

            mineru_result = MineruResult(
                book_id=book_id,
                status="completed",
                result_json=result_json_str,
            )
            db.add(mineru_result)

            book = db.query(Document).filter(Document.id == book_id).first()
            if book:
                book.status = "completed"
            db.commit()
            logger.info("Book %s processing completed (MinerU-Popo done)", book_id)

        except Exception as exc:
            logger.error("Book %s MinerU-Popo failed: %s", book_id, exc, exc_info=True)
            _mark_book_failed(db, book_id, f"MinerU-Popo post-processing failed: {exc}")

    except Exception as exc:
        logger.error("Book %s background task error: %s", book_id, exc, exc_info=True)
        try:
            _mark_book_failed(db, book_id, str(exc))
        except Exception:
            pass
    finally:
        db.close()


def _mark_book_failed(db: Any, book_id: str, error: str) -> None:
    """Helper: set book status=failed and commit."""
    from app.models import Document
    try:
        # Rollback first to ensure the session is in a clean state before
        # querying (a previous exception may have left it rolled-back).
        try:
            db.rollback()
        except Exception as rb_exc:
            logger.debug("Rollback failed (ignored): %s", rb_exc)
        book = db.query(Document).filter(Document.id == book_id).first()
        if book:
            book.status = "failed"
            book.error_message = error
        db.commit()
    except Exception as exc:
        logger.error("Could not mark book %s failed: %s", book_id, exc)
        try:
            db.rollback()
        except Exception as rb_exc:
            logger.debug("Rollback failed (ignored): %s", rb_exc)
