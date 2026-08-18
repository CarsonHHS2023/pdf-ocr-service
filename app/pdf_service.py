"""PDF processing service with layout-aware extraction pipeline."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass

import cv2
import numpy as np

from app.config import settings
from app.image_service import get_image_service

logger = logging.getLogger(__name__)


@dataclass
class ContentBlock:
    """Represents a content block (text, title, catalog, image)."""
    block_type: str  # "text", "title", "paragraph", "catalog", "image"
    content: str  # Text content or image_id
    page_num: Optional[int] = None


@dataclass
class ExtractedSegment:
    """Intermediate extracted unit used for final TXT reconstruction."""
    block_type: str
    content: str
    page_num: int
    bbox: tuple[int, int, int, int]
    page_width: int = 0
    page_height: int = 0
    block_index: int = 0


_BLOCK_TYPE_ALIASES = {
    "text": "text",
    "paragraph": "text",
    "body": "text",
    "body_text": "text",
    "content": "text",
    "list": "text",
    # PP-DocLayout-L: text-like OCR regions → "text"
    "abstract": "text",
    "algorithm": "text",
    "formula": "text",
    "equation": "text",
    "formula_number": "text",
    "equation_number": "text",
    "aside_text": "text",
    "sidebar": "text",
    "marginal_note": "text",
    # caption stays as caption for now (merged-in captions → visual block bbox)
    "caption": "caption",
    "reference": "text",
    "header": "header",
    "footer": "footer",
    "page_header": "header",
    "page_footer": "footer",
    # title and PP-DocLayout-L specific title variants
    "title": "title",
    "heading": "title",
    "section": "title",
    "doc_title": "title",
    "document_title": "title",
    "para_title": "title",
    "paragraph_title": "title",
    "headline": "title",
    "section_title": "title",
    # toc
    "toc": "toc",
    "catalog": "toc",
    "contents": "toc",
    "table_of_contents": "toc",
    "directory": "toc",
    # image-like (including seal/stamp per requirement 4.6)
    "image": "image",
    "figure": "image",
    "picture": "image",
    "photo": "image",
    "graphic": "image",
    "illustration": "image",
    "artwork": "image",
    "diagram": "image",
    "chart": "image",
    "graph": "image",
    "screenshot": "image",
    "seal": "image",
    "stamp": "image",
    # table-like
    "table": "table",
    "tabular": "table",
    "spreadsheet": "table",
    "grid": "table",
    # PP-DocLayout-L ignore regions: pass-through so explicit skip logic fires
    "page_number": "page_number",
    "page_num": "page_number",
    "pagenumber": "page_number",
    "references": "references",
    "bibliography": "references",
    "footnotes": "footnotes",
    "footnote": "footnotes",
    "header_image": "header_image",
    "footer_image": "footer_image",
}

# Block types that are silently skipped during extraction (requirement 4.2).
# "header" and "footer" are handled separately by the existing branch above.
_IGNORE_BLOCK_TYPES: frozenset[str] = frozenset({
    "page_number",
    "references",
    "footnotes",
    "header_image",
    "footer_image",
})

# Block types that carry readable text
_TEXT_BLOCK_TYPES = {"text", "title", "toc", "caption"}

# Block types that should be treated as visual media
_IMAGE_BLOCK_TYPES = {"image", "table"}

_FORCED_PARAGRAPH_BREAK_TYPES = {"title", "toc", "caption", "image", "table"}
_HARD_TRAILING_NEWLINE_TYPES = {"title", "toc"}
_CATALOG_CONNECTOR_CHARS = r"\.\.．。·•・‧⋯…\-—–_─━﹣－\s"
_CATALOG_LINE_RE = re.compile(
    rf"^(?P<title>.+?\S)\s*(?P<connector>[{_CATALOG_CONNECTOR_CHARS}]{{2,}})\s*(?P<page>\d+)\s*$"
)
_CATALOG_PAGE_ONLY_RE = re.compile(r"^(?P<title>.+?\S)\s{2,}(?P<page>\d+)\s*$")
_CATALOG_SINGLE_DASH_RE = re.compile(
    r"^(?P<title>.+?\S)\s+(?P<connector>[\-—–﹣－])\s+(?P<page>\d+)\s*$"
)
_PARAGRAPH_TERMINAL_RE = re.compile(r"[。！？!?；;：:…\.][”’\"')\]】》）]*$")
_RIGHT_PUNCTUATION_RE = re.compile(r"^[,.;:!?%)\]】》、，。！？；：]")
_HEADING_LIKE_RE = re.compile(r"^(第[一二三四五六七八九十百千万0-9]+[章节篇部卷]|[0-9]+[\.、)]|[（(]?[一二三四五六七八九十0-9]+[）)])")
_CAPTION_PREFIX_RE = re.compile(
    r"^\s*(?:图|表)\s*[0-9一二三四五六七八九十百千IVXivx]+(?:\s|[：:.\-、，,]|$)"
)
_CAPTION_PREFIX_EN_RE = re.compile(
    r"^\s*(?:Figure|Table)\s*\d+(?:\s|[：:.\-、，,]|$)",
    re.IGNORECASE,
)
# Note/annotation lines immediately below a figure or table caption should also
# be kept atomic and not merged into unrelated body paragraphs.
_NOTE_PREFIX_RE = re.compile(
    r"^\s*(?:注[：:﹕]?|注意[：:﹕]|备注[：:﹕]|说明[：:﹕]|注\s*\d+[\.）)：:﹕]|Note[：:﹕]|Remark[：:﹕])",
    re.IGNORECASE,
)
_TOC_HEADING_RE = re.compile(r"^\s*目\s*录\s*$")
_TOC_TITLE_LIKE_RE = re.compile(
    r"^(?:目录|前言|序言?|后记|附录|[一二三四五六七八九十百千万0-9]+[篇章节部卷]|[\u4e00-\u9fff]{2,12}(?:篇|章|节|部))$"
)
_TOC_PAGE_TOKEN_RE = re.compile(r"(?P<page>(?:[（(][0-9０-９]+[）)])|(?:[0-9０-９]+))\s*$")
_TOC_PAREN_PAGE_RE = re.compile(r"^(?P<title>.*[\u4e00-\u9fff].*?\S)\s*(?P<page>[（(][0-9０-９]+[）)])\s*$")
_BBOX_OVERFLOW_RATIO = 1.2
_BBOX_NEGATIVE_TOLERANCE = -5
_NORMALIZATION_MIN_GAIN_RATIO = 0.75
_MIN_SHORT_TERMINAL_LINE_LEN = 10
_MIDDLE_ZONE_TOP = 0.18
_MIDDLE_ZONE_BOTTOM = 0.82
_MAX_TOC_NOISE_CJK_LENGTH = 3
_MAX_TOC_INLINE_NOISE_CJK_LENGTH = 4


def _count_cjk_chars(text: str) -> int:
    """Return the number of CJK unified ideograph characters in *text*."""
    return sum(1 for c in text if "\u4e00" <= c <= "\u9fff")


class PDFService:
    """Service for PDF processing with layout-aware extraction.

    Primary engine: PaddleX layout_parsing pipeline (via EnhancedPDFService).
    Canonical block types: title, toc, text, image, table
    (plus header/footer for explicit skip handling).

    Pipeline (per page):
        1. Render page to a 3-channel BGR image via PyMuPDF (EnhancedPDFService).
        2. Run layout analysis on the original BGR image via PaddleX
           (or fallback: whole-page text block).  Pre-processing is NOT applied
           before layout so that PaddleX sees the full colour signal.
        3. Sort blocks top-to-bottom / left-to-right (reading order).
        4. Apply header/footer filtering: text/title blocks whose bbox falls in
           the top ``HEADER_RATIO`` or bottom ``FOOTER_RATIO`` fraction of the
           page height are discarded (configurable via settings / env vars).
        5. Per block:
           - Cover page (page_index == 0, when ``COVER_PAGE_AS_IMAGE=true``):
             entire page saved as image; OCR skipped.
           - text/title/toc  → crop ROI from original image, apply per-ROI
             OpenCV preprocessing (grayscale → denoise → skew-correct → CLAHE),
             then OCR the preprocessed crop, append plain text.
           - header/footer   → skip at step-6 OCR block processing.
             * title blocks always end with ``\\n``.
             * toc blocks are normalised to ``目录标题...页码\\n``.
           - image/table     → encode PNG, persist to DB (when book_id+db
                               are supplied), append marker
                               ``$%$%$%{image_id}$%$%$%``.
        6. Return the joined output as a single TXT string.

    Configuration knobs (all settable via environment variables):
        HEADER_RATIO          float  default 0.08  – header band fraction
        FOOTER_RATIO          float  default 0.08  – footer band fraction
        COVER_PAGE_AS_IMAGE   bool   default False  – treat page 0 as cover
    """

    def __init__(self):
        """Initialise PDF service."""
        self._ocr_service = None
        self._enhanced_pdf_service = None
        self._last_processing_summary: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Lazy service accessors
    # ------------------------------------------------------------------

    def _get_ocr_service(self):
        """Get OCR service lazily."""
        if self._ocr_service is None:
            from app.ocr_service import get_ocr_service
            self._ocr_service = get_ocr_service()
        return self._ocr_service

    def _get_enhanced_pdf_service(self):
        """Get enhanced PDF service (PyMuPDF + PaddleX layout) lazily."""
        if self._enhanced_pdf_service is None:
            from app.enhanced_pdf_service import get_enhanced_pdf_service
            self._enhanced_pdf_service = get_enhanced_pdf_service()
        return self._enhanced_pdf_service

    def get_last_processing_summary(self) -> dict[str, Any]:
        """Return the most recent extraction diagnostics summary."""
        return dict(self._last_processing_summary)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_pdf_content(
        self,
        pdf_path: str | Path,
        book_id: Optional[str] = None,
        db: Any = None,
    ) -> str:
        """Extract content from a PDF using a layout-first pipeline.

        For each page the method:
        - Renders the page to a 3-channel BGR image (PyMuPDF, 300 DPI default).
        - Runs PaddleX layout analysis on the **original BGR image** so that the
          model receives the full colour signal it was trained on.
        - Filters header/footer text blocks by position (see HEADER_RATIO /
          FOOTER_RATIO settings).
        - For cover page (page_index == 0 when ``COVER_PAGE_AS_IMAGE=true``):
          stores entire page as an image block, skips OCR.
        - For text-like blocks: crops the ROI from the raw image, applies
          per-ROI OpenCV preprocessing (grayscale → denoise → skew → CLAHE),
          then runs OCR on the preprocessed crop.
        - For visual blocks (image/table): encodes as PNG, optionally persists
          to the DB, appends ``$%$%$%{image_id}$%$%$%`` marker.

        Per-block failures are logged and skipped; processing continues.

        Args:
            pdf_path:  Path to the PDF file.
            book_id:   Optional book ID used when persisting image blocks.  When
                       *both* ``book_id`` and ``db`` are supplied the cropped
                       images are stored in the database so the frontend can
                       later retrieve them via ``GET /api/v1/images/{image_id}``.
            db:        Optional SQLAlchemy ``Session`` used together with
                       ``book_id`` for image persistence.

        Returns:
            Formatted TXT content.  Text blocks are separated by newlines.
            Image / table blocks appear as ``$%$%$%{image_id}$%$%$%`` markers.
        """
        pdf_path = str(pdf_path)
        logger.info("Starting layout-aware PDF extraction: %s", pdf_path)

        # ── Primary path: PaddleOCR-VL 1.6 ─────────────────────────────────
        try:
            from app.paddleocr_vl_service import get_paddleocr_vl_service

            vl_svc = get_paddleocr_vl_service()
            if vl_svc.is_available():
                logger.info("Using PaddleOCR-VL 1.6 for extraction")
                return vl_svc.extract_pdf_content(
                    pdf_path, book_id=book_id, db=db
                )
            else:
                logger.info(
                    "PaddleOCR-VL not available – falling back to PP-StructureV3 pipeline"
                )
        except (ImportError, RuntimeError) as exc:
            logger.info(
                "PaddleOCR-VL skipped (%s) – using legacy pipeline", exc
            )
        except Exception as exc:
            logger.warning(
                "PaddleOCR-VL raised unexpected error – falling back: %s",
                exc,
                exc_info=True,
            )
        # ── Fallback: legacy PP-StructureV3 pipeline ────────────────────────

        try:
            enhanced_svc = self._get_enhanced_pdf_service()
            ocr_service = self._get_ocr_service()

            # Process all pages → list[PageLayout]
            page_layouts = enhanced_svc.process_pdf(pdf_path)
            processing_summary: dict[str, Any] = {
                "pdf_path": pdf_path,
                "pages_total": len(page_layouts),
                "pages_processed": 0,
                "selected_engines": [],
                "fallback_pages": [],
                "extracted_images": 0,
                "extracted_tables": 0,
                "markers_written": 0,
                "page_summaries": [],
            }

            segments: list[ExtractedSegment] = []

            # Retrieve header/footer ratios once; default to settings values.
            hf_header_ratio = float(getattr(settings, "header_ratio", 0.08))
            hf_footer_ratio = float(getattr(settings, "footer_ratio", 0.08))
            cover_page_as_image = bool(getattr(settings, "cover_page_as_image", False))

            for page_layout in page_layouts:
                page_num = page_layout.page_num  # 0-indexed
                page_width, page_height = self._get_page_dimensions(page_layout)
                processing_summary["pages_processed"] += 1
                page_stats = {
                    "title_detected": 0, "title_output": 0, "title_db_saved": 0,
                    "toc_detected": 0, "toc_output": 0, "toc_db_saved": 0,
                    "text_detected": 0, "text_output": 0, "text_db_saved": 0,
                    "header_detected": 0, "header_output": 0,
                    "footer_detected": 0, "footer_output": 0,
                    "image_detected": 0, "image_output": 0, "image_db_saved": 0,
                    "table_detected": 0, "table_output": 0, "table_db_saved": 0,
                    "ignored_detected": 0,
                    "markers_written": 0,
                }
                selected_engine = getattr(page_layout, "selected_engine", "fallback_ocr_only")
                fallback_reason = getattr(page_layout, "fallback_reason", None)
                processing_summary["selected_engines"].append(selected_engine)
                logger.info(
                    "Page %d: selected_engine=%s fallback_reason=%s",
                    page_num + 1, selected_engine, fallback_reason,
                )
                if fallback_reason:
                    processing_summary["fallback_pages"].append(
                        {
                            "page_index": page_num,
                            "reason": fallback_reason,
                        }
                    )

                # ----------------------------------------------------------------
                # Cover page handling: page_index == 0 is treated as a cover image
                # when cover_page_as_image is enabled.  OCR text extraction is
                # skipped entirely; the full page is stored as an image block.
                # ----------------------------------------------------------------
                is_cover = (page_num == 0) and cover_page_as_image
                if is_cover:
                    logger.info(
                        "Page 1 treated as cover page (cover_page_as_image=True): "
                        "skipping OCR text extraction"
                    )
                    page_img = page_layout.raw_image
                    if page_img is not None and page_img.size > 0:
                        h, w = page_img.shape[:2]
                        cover_bbox = (0, 0, w, h)
                        image_id, image_saved = self._persist_image_block(
                            block_img=page_img,
                            block_type="image",
                            page_num=page_num + 1,
                            bbox=cover_bbox,
                            block_index=0,
                            confidence=1.0,
                            book_id=book_id,
                            db=db,
                        )
                        marker = f"$%$%$%{image_id}$%$%$%"
                        segments.append(
                            ExtractedSegment(
                                block_type="image",
                                content=marker,
                                page_num=page_num,
                                bbox=cover_bbox,
                                page_width=w,
                                page_height=h,
                                block_index=0,
                            )
                        )
                        page_stats["image_output"] += 1
                        page_stats["markers_written"] += 1
                        processing_summary["markers_written"] += 1
                        processing_summary["extracted_images"] += 1
                    processing_summary["page_summaries"].append(
                        {
                            "page_index": page_num,
                            "selected_engine": selected_engine,
                            "fallback_reason": fallback_reason,
                            "cover_page": True,
                            "total_blocks": 0,
                        }
                    )
                    continue

                before_filter_counts = (
                    dict(getattr(page_layout, "raw_block_type_counts", {}) or {})
                    or self._count_block_types(page_layout.blocks)
                )
                total_blocks_before_filter = sum(before_filter_counts.values())

                # Sort blocks into reading order: top → bottom, left → right
                blocks = sorted(
                    page_layout.blocks,
                    key=lambda b: (
                        self._sort_key_bbox(b.bbox)[1],
                        self._sort_key_bbox(b.bbox)[0],
                    ),
                )

                page_toc_mode = any(
                    self._normalize_block_type(getattr(_b, "block_type", "")) == "toc"
                    for _b in blocks
                )

                for block_index, block in enumerate(blocks):
                    try:
                        raw_block_type = getattr(block, "block_type", "")
                        block_type = self._normalize_block_type(raw_block_type)
                        if self._bbox_looks_suspicious(
                            getattr(block, "bbox", None), page_width=page_width, page_height=page_height
                        ):
                            logger.warning(
                                "Suspicious bbox on page %d idx=%d type=%s bbox=%r (possible coordinate misuse)",
                                page_num + 1,
                                block_index,
                                raw_block_type,
                                getattr(block, "bbox", None),
                            )
                        bbox = self._normalize_bbox(
                            getattr(block, "bbox", None),
                            page_width=page_width,
                            page_height=page_height,
                        )
                        if bbox is None:
                            # Some callers/tests only provide block-local crops, so the
                            # mocked page image can be smaller than the block coordinates.
                            bbox = self._normalize_bbox(getattr(block, "bbox", None))
                        if bbox is None:
                            logger.warning(
                                "Skipping block with invalid bbox: page=%d idx=%d raw_type=%s bbox=%r",
                                page_num + 1, block_index, raw_block_type, getattr(block, "bbox", None),
                            )
                            continue

                        if block_type in {"header", "footer"}:
                            page_stats[f"{block_type}_detected"] += 1
                            continue
                        # PP-DocLayout-L: skip explicit ignore regions (4.2)
                        if block_type in _IGNORE_BLOCK_TYPES:
                            page_stats["ignored_detected"] += 1
                            logger.debug(
                                "Skipping ignored block: page=%d idx=%d type=%s",
                                page_num + 1, block_index, block_type,
                            )
                            continue
                        page_stats[f"{self._stats_key_for_block_type(block_type)}_detected"] += 1
                        block_img = self._get_block_image(page_layout, block, block_type, bbox)

                        if not self._passes_block_filters(
                            block_img=block_img,
                            confidence=getattr(block, "confidence", None),
                            block_type=block_type,
                        ):
                            logger.debug(
                                "Skipping undersized block: page=%d idx=%d type=%s bbox=%s",
                                page_num + 1, block_index, block_type, bbox,
                            )
                            continue

                        if block_type in _IMAGE_BLOCK_TYPES:
                            image_id, image_saved = self._persist_image_block(
                                block_img=block_img,
                                block_type=block_type,
                                page_num=page_num + 1,  # 1-indexed for storage
                                bbox=bbox,
                                block_index=block_index,
                                confidence=getattr(block, "confidence", None),
                                book_id=book_id,
                                db=db,
                            )
                            marker = f"$%$%$%{image_id}$%$%$%"
                            content_saved = self._persist_content_block(
                                block_type=block_type,
                                content=image_id,
                                page_num=page_num + 1,
                                block_index=block_index,
                                bbox=bbox,
                                confidence=getattr(block, "confidence", 1.0),
                                book_id=book_id,
                                db=db,
                            )
                            if image_saved or content_saved:
                                page_stats[f"{block_type}_db_saved"] += 1
                            segments.append(
                                ExtractedSegment(
                                    block_type=block_type,
                                    content=marker,
                                    page_num=page_num,
                                    bbox=bbox,
                                    page_width=page_width,
                                    page_height=page_height,
                                    block_index=block_index,
                                )
                            )
                            page_stats[f"{block_type}_output"] += 1
                            page_stats["markers_written"] += 1
                            processing_summary["markers_written"] += 1
                            processing_summary[f"extracted_{block_type}s"] += 1
                            continue

                        if block_img is None or block_img.size == 0:
                            logger.debug(
                                "Skipping empty text block image: page=%d idx=%d type=%s",
                                page_num + 1, block_index, block_type,
                            )
                            continue

                        # For text-like blocks, apply per-ROI preprocessing
                        # (grayscale → denoise → skew correction → CLAHE) before
                        # OCR.  Layout has already run on the original BGR image,
                        # so this preprocessing is scoped to the individual block.
                        block_img = self._preprocess_text_roi(block_img)

                        text = ocr_service.extract_text_from_image(block_img).strip()
                        if not text:
                            continue

                        if self._is_caption_block(text, block_type):
                            processed_text = self._normalize_caption_text(text)
                            segment_type = "caption"
                        elif page_toc_mode or self._looks_like_catalog_block(text, block_type):
                            processed_text = self.process_catalog_block(text)
                            segment_type = "toc"
                            page_toc_mode = True
                        else:
                            normalized_text = self._normalize_block_text(text)
                            segment_type = block_type if block_type in _TEXT_BLOCK_TYPES else "text"
                            processed_text = self._select_safe_normalized_text(
                                raw_text=text,
                                normalized_text=normalized_text,
                                segment_type=segment_type,
                            )

                        if not processed_text.strip():
                            continue

                        if processed_text != text:
                            logger.debug(
                                "Text normalization changed content: page=%d idx=%d type=%s raw=%r normalized=%r",
                                page_num + 1,
                                block_index,
                                segment_type,
                                text,
                                processed_text,
                            )

                        # Compute stats key once; used for both _db_saved and _output counters.
                        stats_key = self._stats_key_for_block_type(segment_type)
                        if self._persist_content_block(
                            block_type=segment_type,
                            content=processed_text.rstrip("\n"),
                            page_num=page_num + 1,
                            block_index=block_index,
                            bbox=bbox,
                            confidence=getattr(block, "confidence", 1.0),
                            book_id=book_id,
                            db=db,
                        ):
                            page_stats[f"{stats_key}_db_saved"] += 1

                        segments.append(
                            ExtractedSegment(
                                block_type=segment_type,
                                content=processed_text,
                                page_num=page_num,
                                bbox=bbox,
                                page_width=page_width,
                                page_height=page_height,
                                block_index=block_index,
                            )
                        )
                        page_stats[f"{stats_key}_output"] += 1

                    except Exception as block_err:
                        logger.error(
                            "Error processing block page=%d idx=%d type=%s: %s",
                            page_num + 1, block_index, getattr(block, "block_type", ""), block_err,
                            exc_info=True,
                        )
                        continue  # Robust: continue with the next block

                logger.info(
                    "Page %d extraction diagnostics: selected_engine=%s fallback_reason=%s total_blocks=%d "
                    "before_filter=%s "
                    "after_filter title=%d toc=%d text=%d image=%d table=%d "
                    "extracted_images=%d extracted_tables=%d markers_written=%d diagnostics_path=%s "
                    "db_saved(title=%d,toc=%d,text=%d,image=%d,table=%d)",
                    page_num + 1,
                    selected_engine,
                    fallback_reason,
                    total_blocks_before_filter,
                    before_filter_counts,
                    page_stats["title_output"],
                    page_stats["toc_output"],
                    page_stats["text_output"],
                    page_stats["image_output"],
                    page_stats["table_output"],
                    page_stats["image_output"],
                    page_stats["table_output"],
                    page_stats["markers_written"],
                    getattr(page_layout, "diagnostics_path", None),
                    page_stats["title_db_saved"],
                    page_stats["toc_db_saved"],
                    page_stats["text_db_saved"],
                    page_stats["image_db_saved"],
                    page_stats["table_db_saved"],
                )
                processing_summary["page_summaries"].append(
                    {
                        "page_index": page_num,
                        "selected_engine": selected_engine,
                        "fallback_reason": fallback_reason,
                        "total_blocks": total_blocks_before_filter,
                        "before_filter_counts": before_filter_counts,
                        "after_filter_counts": {
                            "title": page_stats["title_output"],
                            "toc": page_stats["toc_output"],
                            "text": page_stats["text_output"],
                            "image": page_stats["image_output"],
                            "table": page_stats["table_output"],
                        },
                        "extracted_images": page_stats["image_output"],
                        "extracted_tables": page_stats["table_output"],
                        "markers_written": page_stats["markers_written"],
                        "diagnostics_path": getattr(page_layout, "diagnostics_path", None),
                    }
                )

            segments = self._apply_safe_header_footer_filter(
                segments,
                header_ratio=hf_header_ratio,
                footer_ratio=hf_footer_ratio,
            )
            result = self._assemble_output(segments)
            self._last_processing_summary = processing_summary
            logger.info(
                "PDF extraction completed: %d segments, %d total chars, extracted_images=%d, extracted_tables=%d, markers_written=%d",
                len(segments), len(result),
                processing_summary["extracted_images"],
                processing_summary["extracted_tables"],
                processing_summary["markers_written"],
            )
            return result

        except Exception as e:
            self._last_processing_summary = {
                "pdf_path": pdf_path,
                "error": str(e),
            }
            logger.error("Failed to extract PDF content: %s", e, exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _persist_image_block(
        self,
        block_img: np.ndarray,
        block_type: str,
        page_num: int,
        bbox: tuple,
        block_index: int,
        confidence: Optional[float] = None,
        book_id: Optional[str] = None,
        db: Any = None,
    ) -> tuple[str, bool]:
        """Encode a cropped block image to PNG, optionally save it, and return its ID.

        When *both* ``book_id`` and ``db`` are provided the image is stored in
        the database via ``ImageService`` so the frontend can retrieve it.  If
        either is absent the image is not persisted, but a stable hash-based
        ``image_id`` is still returned so the TXT marker is consistent.

        Args:
            block_img:  Cropped BGR/grayscale image for this layout block.
            block_type: Layout block type string (e.g. ``"image"``, ``"table"``).
            page_num:   1-indexed page number for metadata.
            bbox:       Bounding box ``(x1, y1, x2, y2)`` for metadata.
            book_id:    Optional book ID for DB persistence.
            db:         Optional SQLAlchemy session for DB persistence.

        Returns:
            Tuple of ``(image_id, persisted_to_db)``.
        """
        ok, enc = cv2.imencode(".png", block_img)
        if not ok:
            raise ValueError("cv2.imencode failed for layout block image")
        png_bytes = enc.tobytes()

        if book_id and db is not None:
            try:
                bbox_str = (
                    f"{int(bbox[0])},{int(bbox[1])},{int(bbox[2])},{int(bbox[3])}"
                )
                image_id = get_image_service().save_image(
                    db=db,
                    book_id=book_id,
                    image_data=png_bytes,
                    image_format="png",
                    page_num=page_num,
                    bbox=bbox_str,
                    block_type=block_type,
                )
                logger.info(
                    "Persisted %s block image: image_id=%s page=%d idx=%d bbox=%s confidence=%s",
                    block_type,
                    image_id,
                    page_num,
                    block_index,
                    bbox_str,
                    confidence,
                )
                return image_id, True
            except Exception as save_err:
                logger.warning(
                    "Could not persist %s block to DB (page=%d idx=%d bbox=%s confidence=%s): %s",
                    block_type,
                    page_num,
                    block_index,
                    bbox,
                    confidence,
                    save_err,
                )

        # Fallback: derive a stable ID from the PNG content hash (not persisted)
        fallback_id = "img_" + hashlib.sha256(png_bytes).hexdigest()[:16]
        logger.debug("Using hash-based image ID (not persisted): %s", fallback_id)
        return fallback_id, False

    def _persist_content_block(
        self,
        block_type: str,
        content: str,
        page_num: int,
        block_index: int,
        bbox: tuple[int, int, int, int],
        confidence: float,
        book_id: Optional[str] = None,
        db: Any = None,
    ) -> bool:
        """Persist a content block row when a DB session is available."""
        if not (book_id and db is not None):
            return False

        try:
            from app.models import ContentBlock as ContentBlockModel

            db.add(
                ContentBlockModel(
                    book_id=book_id,
                    page_num=page_num,
                    block_index=block_index,
                    block_type=block_type,
                    content=content,
                    bbox=f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
                    confidence=confidence if confidence is not None else 1.0,
                )
            )
            db.commit()
            logger.debug(
                "Persisted content block: page=%d idx=%d type=%s",
                page_num,
                block_index,
                block_type,
            )
            return True
        except Exception as save_err:
            db.rollback()
            logger.warning(
                "Could not persist content block (page=%d idx=%d type=%s bbox=%s): %s",
                page_num,
                block_index,
                block_type,
                bbox,
                save_err,
            )
            return False

    def _normalize_block_type(self, raw_block_type: Any) -> str:
        """Map layout analyzer block aliases to canonical block types."""
        normalized = str(raw_block_type or "text").strip().lower()
        normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
        return _BLOCK_TYPE_ALIASES.get(normalized, normalized or "text")

    def _sort_key_bbox(self, bbox: Any) -> tuple[int, int, int, int]:
        """Return a best-effort bbox for ordering when the true bbox is malformed."""
        normalized = self._normalize_bbox(bbox)
        return normalized or (0, 0, 0, 0)

    def _normalize_bbox(
        self,
        bbox: Any,
        page_width: Optional[int] = None,
        page_height: Optional[int] = None,
    ) -> Optional[tuple[int, int, int, int]]:
        """Normalize various bbox shapes to a clipped ``(x1, y1, x2, y2)`` tuple."""
        if bbox is None:
            return None

        x1 = y1 = x2 = y2 = None
        if isinstance(bbox, dict):
            if {"x1", "y1", "x2", "y2"} <= set(bbox.keys()):
                x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]
            elif {"left", "top", "right", "bottom"} <= set(bbox.keys()):
                x1, y1, x2, y2 = bbox["left"], bbox["top"], bbox["right"], bbox["bottom"]
        elif isinstance(bbox, (list, tuple)):
            if len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox):
                x1, y1, x2, y2 = bbox
            elif len(bbox) >= 4 and all(
                isinstance(v, (list, tuple)) and len(v) >= 2 for v in bbox[:4]
            ):
                xs = [point[0] for point in bbox[:4]]
                ys = [point[1] for point in bbox[:4]]
                x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)

        if None in {x1, y1, x2, y2}:
            return None

        x1, y1, x2, y2 = [int(round(v)) for v in (x1, y1, x2, y2)]
        if page_width is not None:
            x1 = max(0, min(x1, page_width))
            x2 = max(0, min(x2, page_width))
        if page_height is not None:
            y1 = max(0, min(y1, page_height))
            y2 = max(0, min(y2, page_height))

        if x2 <= x1 or y2 <= y1:
            return None
        return (x1, y1, x2, y2)

    def _get_page_dimensions(self, page_layout: Any) -> tuple[int, int]:
        """Return page width/height from raw or preprocessed page image."""
        for image in (page_layout.raw_image, page_layout.preprocessed_image):
            if image is not None and hasattr(image, "shape") and len(image.shape) >= 2:
                height, width = image.shape[:2]
                return width, height
        return (0, 0)

    def _bbox_looks_suspicious(self, bbox: Any, page_width: int, page_height: int) -> bool:
        """Detect likely coordinate misuse (e.g. block-local values used as page coords)."""
        if page_width <= 0 or page_height <= 0:
            return False
        normalized = self._normalize_bbox(bbox)
        if normalized is None:
            return False
        x1, y1, x2, y2 = normalized
        return (
            x2 > int(page_width * _BBOX_OVERFLOW_RATIO)
            or y2 > int(page_height * _BBOX_OVERFLOW_RATIO)
            or x1 < _BBOX_NEGATIVE_TOLERANCE
            or y1 < _BBOX_NEGATIVE_TOLERANCE
        )

    def _crop_image(self, image: Optional[np.ndarray], bbox: tuple[int, int, int, int]) -> Optional[np.ndarray]:
        """Crop an image safely, returning ``None`` when the crop is unavailable."""
        if image is None or not hasattr(image, "shape"):
            return None
        normalized_bbox = self._normalize_bbox(
            bbox,
            page_width=image.shape[1],
            page_height=image.shape[0],
        )
        if normalized_bbox is None:
            logger.debug(
                "Unable to crop image because bbox %s is invalid for shape %s",
                bbox,
                image.shape,
            )
            return None
        x1, y1, x2, y2 = normalized_bbox
        cropped = image[y1:y2, x1:x2]
        return cropped if cropped.size else None

    def _get_block_image(
        self,
        page_layout: Any,
        block: Any,
        block_type: str,
        bbox: tuple[int, int, int, int],
    ) -> Optional[np.ndarray]:
        """Get the preferred crop source for a block and fall back to embedded data.

        Visual blocks (image/table) are always cropped from the raw colour image.
        Text-like blocks are also cropped from the raw image so that
        per-block OCR preprocessing can be applied on the ROI before OCR.
        """
        if block_type in _IMAGE_BLOCK_TYPES:
            for source in (page_layout.raw_image, page_layout.preprocessed_image):
                cropped = self._crop_image(source, bbox)
                if cropped is not None:
                    return cropped
        else:
            # Prefer raw_image so that per-ROI preprocessing is applied downstream.
            # Fall back to preprocessed_image if raw_image is unavailable.
            for source in (page_layout.raw_image, page_layout.preprocessed_image):
                cropped = self._crop_image(source, bbox)
                if cropped is not None:
                    return cropped

        block_img = getattr(block, "image_data", None)
        if block_img is None or not hasattr(block_img, "size") or block_img.size == 0:
            return None
        return block_img

    def _passes_block_filters(
        self,
        block_img: Optional[np.ndarray],
        confidence: Optional[float],
        block_type: str,
    ) -> bool:
        """Apply conservative size validation without suppressing normal visual blocks."""
        if block_img is None or not hasattr(block_img, "shape") or block_img.size == 0:
            return False

        height, width = block_img.shape[:2]
        min_size = (
            int(getattr(settings, "layout_min_visual_block_size", 12))
            if block_type in _IMAGE_BLOCK_TYPES
            else int(getattr(settings, "layout_min_text_block_size", 8))
        )
        if width < min_size or height < min_size:
            return False

        min_confidence = float(getattr(settings, "layout_min_confidence", 0.0))
        if confidence is not None and confidence < min_confidence:
            return False
        return True

    def _is_header_or_footer(
        self,
        bbox: tuple[int, int, int, int],
        page_height: int,
        header_ratio: float = 0.08,
        footer_ratio: float = 0.08,
    ) -> bool:
        """Return True if *bbox* falls entirely within a header or footer band.

        The header band is the top ``header_ratio`` fraction of the page height;
        the footer band is the bottom ``footer_ratio`` fraction.  Only text-like
        blocks should be passed here; visual blocks are never filtered this way.

        Args:
            bbox:          Normalised ``(x1, y1, x2, y2)`` bounding box.
            page_height:   Full page height in pixels.
            header_ratio:  Fraction of page height reserved for the header.
            footer_ratio:  Fraction of page height reserved for the footer.
        """
        if page_height <= 0:
            return False
        _, y1, _, y2 = bbox
        header_threshold = int(page_height * header_ratio)
        footer_threshold = int(page_height * (1.0 - footer_ratio))
        return y2 <= header_threshold or y1 >= footer_threshold

    def _preprocess_text_roi(self, img: np.ndarray) -> np.ndarray:
        """Apply OCR preprocessing (grayscale → denoise → skew correction → CLAHE)
        to a text block ROI crop.

        This allows preprocessing to be scoped to individual text regions after
        layout detection rather than applied to the whole page up front.  The
        caller is responsible for ensuring that *img* is a crop from a text-like
        block (``text`` or ``title``); non-text blocks do not need this step.

        Returns the original image unchanged if preprocessing fails.
        """
        try:
            from app.image_preprocessing import ImagePreprocessor
            return ImagePreprocessor.preprocess(img)
        except Exception as exc:
            logger.debug("Per-ROI preprocessing skipped: %s", exc)
            return img

    def _count_block_types(self, blocks: list[Any]) -> dict[str, int]:
        """Count canonical block types for diagnostics when page metadata is absent."""
        counts: dict[str, int] = {}
        for block in blocks:
            block_type = self._normalize_block_type(getattr(block, "block_type", "text"))
            counts[block_type] = counts.get(block_type, 0) + 1
        return counts

    def _stats_key_for_block_type(self, block_type: str) -> str:
        """Map block types to page summary stat keys."""
        if block_type in _IMAGE_BLOCK_TYPES:  # {"image", "table"}
            return block_type
        if block_type in {"title", "toc"}:
            return block_type
        return "text"

    def _looks_like_catalog_block(self, text: str, block_type: str) -> bool:
        """Detect TOC/catalog content using either layout labels or line patterns.

        **Single-line blocks**: Only treated as TOC when the line is the "目录"
        heading or has an explicit page-number structure (dots + digit, parenthesised
        page token, etc.).  Title-like words such as "前言" or "第一章" on their own
        are intentionally *not* classified here; they could be chapter headings on a
        non-TOC page, and incorrectly setting ``page_toc_mode`` would cause the entire
        page's body text to be processed as TOC entries.

        **Multi-line blocks**: the existing majority-vote heuristic is retained.
        """
        if block_type == "toc":
            return True

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) == 1:
            line = lines[0]
            # "目录" heading is an unambiguous TOC signal.
            if _TOC_HEADING_RE.match(line):
                return True
            # Title-like words without a page number are ambiguous — they may be
            # chapter headings rather than TOC entries.  Require an explicit
            # page-number structure before declaring a single-line block as TOC.
            return bool(
                _CATALOG_LINE_RE.match(line)
                or _CATALOG_PAGE_ONLY_RE.match(line)
                or _CATALOG_SINGLE_DASH_RE.match(line)
                or _TOC_PAREN_PAGE_RE.match(line)
            )
        if len(lines) < 2:
            return False

        matches = sum(1 for line in lines if self._match_catalog_line(line))
        return matches >= max(2, len(lines) // 2)

    def _match_catalog_line(self, line: str) -> bool:
        """Return whether a line looks like a catalog/TOC entry."""
        stripped = line.strip()
        if not stripped:
            return False
        if _TOC_HEADING_RE.match(stripped) or _TOC_TITLE_LIKE_RE.match(stripped):
            return True
        return bool(
            _CATALOG_LINE_RE.match(stripped)
            or _CATALOG_PAGE_ONLY_RE.match(stripped)
            or _CATALOG_SINGLE_DASH_RE.match(stripped)
            or _TOC_PAREN_PAGE_RE.match(stripped)
        )

    def _is_caption_block(self, text: str, block_type: str) -> bool:
        """Detect figure/table captions and associated notes; keep them as protected atomic units."""
        if block_type == "caption":
            return True
        stripped = self._normalize_inline_whitespace(text)
        return bool(
            _CAPTION_PREFIX_RE.match(stripped)
            or _CAPTION_PREFIX_EN_RE.match(stripped)
            or _NOTE_PREFIX_RE.match(stripped)
        )

    def _normalize_caption_text(self, text: str) -> str:
        """Keep caption text atomic (no forced cross-line merge / rewrite)."""
        lines = [self._normalize_inline_whitespace(line) for line in text.splitlines() if line.strip()]
        return " ".join(lines).strip()

    def _select_safe_normalized_text(self, raw_text: str, normalized_text: str, segment_type: str) -> str:
        """Prefer raw OCR when normalization does not provide clear structural gain.

        Two independent safety checks guard against destructive rewriting:
        1. **Length check**: if the normalized form is shorter than
           ``_NORMALIZATION_MIN_GAIN_RATIO`` times the raw length, prefer raw.
        2. **CJK character count check**: if the number of CJK characters drops
           significantly (same ratio) after normalization, prefer raw.  This
           catches cases where line-merging inadvertently conceals OCR noise that
           reduced "投资" to a single character.

        Both decisions are logged at DEBUG level so the before/after state and
        the reason for the choice can be traced.
        """
        if segment_type in {"toc", "caption"}:
            return normalized_text
        raw_lines = [self._normalize_inline_whitespace(line) for line in raw_text.splitlines() if line.strip()]
        raw_joined = "\n".join(raw_lines)
        if not raw_joined:
            return normalized_text

        # Length-based safety gate
        if len(normalized_text) < (len(raw_joined) * _NORMALIZATION_MIN_GAIN_RATIO):
            logger.debug(
                "Normalization rejected (length gate): raw=%r normalized=%r "
                "raw_len=%d norm_len=%d threshold_ratio=%.2f",
                raw_joined, normalized_text, len(raw_joined), len(normalized_text),
                _NORMALIZATION_MIN_GAIN_RATIO,
            )
            return raw_joined

        # CJK character-count safety gate — catches substitutions that reduce
        # character count without shrinking total byte length proportionally
        raw_cjk = _count_cjk_chars(raw_joined)
        norm_cjk = _count_cjk_chars(normalized_text)
        if raw_cjk > 2 and norm_cjk < raw_cjk * _NORMALIZATION_MIN_GAIN_RATIO:
            logger.debug(
                "Normalization rejected (CJK count gate): raw=%r normalized=%r "
                "raw_cjk=%d norm_cjk=%d threshold_ratio=%.2f",
                raw_joined, normalized_text, raw_cjk, norm_cjk,
                _NORMALIZATION_MIN_GAIN_RATIO,
            )
            return raw_joined

        return normalized_text

    def _normalize_inline_whitespace(self, text: str) -> str:
        """Collapse internal whitespace while keeping CJK text compact."""
        text = text.replace("\u3000", " ")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _join_wrapped_text(self, left: str, right: str) -> str:
        """Join wrapped text fragments without introducing paragraph breaks."""
        left = left.rstrip()
        right = right.lstrip()
        if not left:
            return right
        if not right:
            return left
        if left.endswith("-"):
            return left[:-1] + right
        if _RIGHT_PUNCTUATION_RE.match(right):
            return left + right
        if re.search(r"[\u4e00-\u9fff]$", left) or re.match(r"^[\u4e00-\u9fff]", right):
            return left + right
        return f"{left} {right}"

    def _normalize_block_text(self, text: str) -> str:
        """Merge wrapped lines conservatively while preserving clear paragraph endings."""
        paragraphs: list[str] = []
        current = ""
        previous_line = ""

        for raw_line in text.splitlines():
            line = self._normalize_inline_whitespace(raw_line)
            if not line:
                if current:
                    paragraphs.append(current.strip())
                    current = ""
                    previous_line = ""
                continue
            if not current:
                current = line
                previous_line = line
                continue

            if self._is_paragraph_terminal(previous_line):
                paragraphs.append(current.strip())
                current = line
            else:
                current = self._join_wrapped_text(current, line)
            previous_line = line

        if current:
            paragraphs.append(current.strip())
        return "\n".join(paragraphs)

    def _looks_like_heading(self, segment: ExtractedSegment) -> bool:
        """Heuristic heading detector used for paragraph-boundary decisions."""
        text = segment.content.strip()
        if segment.block_type in {"title", "header"}:
            return True
        if not text:
            return False
        return bool(_HEADING_LIKE_RE.match(text))

    def _is_paragraph_terminal(self, text: str) -> bool:
        """Check whether a text fragment clearly ends a paragraph."""
        return bool(_PARAGRAPH_TERMINAL_RE.search(text.strip()))

    def _vertical_gap(self, current: ExtractedSegment, nxt: ExtractedSegment) -> int:
        """Return the vertical gap between two same-page blocks."""
        return max(0, nxt.bbox[1] - current.bbox[3])

    def _likely_page_continuation(self, current: ExtractedSegment, nxt: ExtractedSegment) -> bool:
        """Detect likely cross-page paragraph continuation at natural page breaks."""
        if current.page_num == nxt.page_num:
            return False
        if current.block_type in _FORCED_PARAGRAPH_BREAK_TYPES or nxt.block_type in _FORCED_PARAGRAPH_BREAK_TYPES:
            return False
        if self._is_paragraph_terminal(current.content):
            return False
        if self._looks_like_heading(current) or self._looks_like_heading(nxt):
            return False
        if not current.page_height or not nxt.page_height:
            return False

        current_bottom_ratio = current.bbox[3] / current.page_height
        next_top_ratio = nxt.bbox[1] / nxt.page_height
        return current_bottom_ratio >= 0.88 and next_top_ratio <= 0.18

    def _should_break_before(self, current: ExtractedSegment, nxt: ExtractedSegment) -> bool:
        """Decide whether the next segment starts a new paragraph/output line.

        The decision intentionally combines geometry (page break, vertical gap,
        indent changes, page-bottom/page-top continuation) and textual signals
        (terminal punctuation, heading/title cues) so natural wraps stay merged
        while true paragraph boundaries still emit ``\n``.
        """
        if current.block_type in _FORCED_PARAGRAPH_BREAK_TYPES:
            return True
        if nxt.block_type in _FORCED_PARAGRAPH_BREAK_TYPES:
            return True
        if current.page_num != nxt.page_num:
            return not self._likely_page_continuation(current, nxt)
        if self._is_paragraph_terminal(current.content):
            return True
        if self._looks_like_heading(current) or self._looks_like_heading(nxt):
            return True

        vertical_gap = self._vertical_gap(current, nxt)
        current_height = max(1, current.bbox[3] - current.bbox[1])
        next_height = max(1, nxt.bbox[3] - nxt.bbox[1])
        gap_threshold = max(4, int(max(current_height, next_height) * 0.08))
        continuation_indent_threshold = max(
            18,
            int(current.page_width * 0.025) if current.page_width else 18,
        )
        if current.page_width:
            indent_delta = abs(nxt.bbox[0] - current.bbox[0])
            if indent_delta > continuation_indent_threshold:
                return True
        else:
            indent_delta = 0

        current_is_paragraph_block = current.block_type in {"text", "paragraph"}
        next_is_paragraph_block = nxt.block_type in {"text", "paragraph"}
        likely_same_paragraph = (
            current_is_paragraph_block
            and next_is_paragraph_block
            and vertical_gap <= gap_threshold
            and indent_delta <= continuation_indent_threshold
            and len(current.content.strip()) >= 12
        )
        if likely_same_paragraph and self._is_paragraph_terminal(current.content):
            return True
        if current_is_paragraph_block and next_is_paragraph_block:
            if len(current.content.strip()) <= _MIN_SHORT_TERMINAL_LINE_LEN and self._is_paragraph_terminal(current.content):
                return True
        return not likely_same_paragraph

    def _apply_safe_header_footer_filter(
        self,
        segments: list[ExtractedSegment],
        header_ratio: float,
        footer_ratio: float,
    ) -> list[ExtractedSegment]:
        """Filter header/footer using repeated-text + position safeguards.

        All coordinate comparisons operate on **page-level** bounding boxes stored
        in each :class:`ExtractedSegment`.  ``segment.page_height`` is the full
        rendered page height (in pixels) that was set during extraction; it must
        never be confused with a block-local height.

        Two tiers of protection prevent false positives:
        1. *Middle-zone guard*: segments whose vertical centre falls inside the
           body region (``_MIDDLE_ZONE_TOP``–``_MIDDLE_ZONE_BOTTOM``) are always
           kept regardless of position.
        2. *Title-following guard*: on each page the bottom y-coordinate of the
           lowest title block is tracked.  Any segment whose top edge is **at or
           below** that coordinate is protected from removal (``>=`` rather than
           strict ``>`` ensures lines that start exactly at the title bottom are
           also guarded).
        """
        repeated_candidates: dict[str, int] = {}
        title_bottom_by_page: dict[int, int] = {}

        for segment in segments:
            if segment.block_type == "title":
                title_bottom_by_page[segment.page_num] = max(
                    title_bottom_by_page.get(segment.page_num, 0),
                    segment.bbox[3],
                )
            if segment.block_type not in {"text", "title"}:
                continue
            if segment.page_height <= 0:
                continue
            if segment.bbox[3] > segment.page_height:
                continue
            if not self._is_header_or_footer(segment.bbox, segment.page_height, header_ratio, footer_ratio):
                continue
            key = self._normalize_inline_whitespace(segment.content)
            if key:
                repeated_candidates[key] = repeated_candidates.get(key, 0) + 1

        filtered: list[ExtractedSegment] = []
        removed_count = 0
        for segment in segments:
            if segment.block_type not in {"text", "title"} or segment.page_height <= 0:
                filtered.append(segment)
                continue
            if segment.bbox[3] > segment.page_height:
                filtered.append(segment)
                continue
            if not self._is_header_or_footer(segment.bbox, segment.page_height, header_ratio, footer_ratio):
                filtered.append(segment)
                continue

            y_center_ratio = ((segment.bbox[1] + segment.bbox[3]) / 2) / segment.page_height
            if _MIDDLE_ZONE_TOP <= y_center_ratio <= _MIDDLE_ZONE_BOTTOM:
                filtered.append(segment)
                continue

            # Title-following guard: protect lines whose top edge is at or below
            # the bottom of the page's title block (page-level coordinates).
            title_bottom = title_bottom_by_page.get(segment.page_num, 0)
            if title_bottom > 0 and segment.bbox[1] >= title_bottom:
                logger.debug(
                    "Header/footer filter: protecting title-following segment "
                    "page=%d bbox=%r page_height=%d title_bottom=%d",
                    segment.page_num, segment.bbox, segment.page_height, title_bottom,
                )
                filtered.append(segment)
                continue

            key = self._normalize_inline_whitespace(segment.content)
            if repeated_candidates.get(key, 0) >= 2:
                logger.debug(
                    "Header/footer filter: removing repeated candidate "
                    "page=%d bbox=%r page_height=%d content=%r",
                    segment.page_num, segment.bbox, segment.page_height, key,
                )
                removed_count += 1
                continue
            filtered.append(segment)

        logger.info(
            "Safe header/footer filter applied on segments: before=%d after=%d removed=%d",
            len(segments),
            len(filtered),
            removed_count,
        )
        return filtered

    def _assemble_output(self, segments: list[ExtractedSegment]) -> str:
        """Assemble final TXT with catalog lines and paragraph-only newlines."""
        output_lines: list[str] = []
        pending_text: Optional[str] = None
        pending_segment: Optional[ExtractedSegment] = None
        last_output_type: Optional[str] = None

        for segment in segments:
            if segment.block_type in _IMAGE_BLOCK_TYPES:
                if pending_text:
                    output_lines.append(pending_text.strip())
                    last_output_type = pending_segment.block_type if pending_segment else None
                    pending_text = None
                    pending_segment = None
                output_lines.append(segment.content.strip())
                last_output_type = segment.block_type
                continue

            if segment.block_type == "toc":
                if pending_text:
                    output_lines.append(pending_text.strip())
                    last_output_type = pending_segment.block_type if pending_segment else None
                    pending_text = None
                    pending_segment = None
                for line in segment.content.splitlines():
                    if line.strip():
                        output_lines.append(line.strip())
                        last_output_type = segment.block_type
                continue

            paragraphs = [part for part in segment.content.split("\n") if part.strip()]
            for paragraph_index, paragraph in enumerate(paragraphs):
                paragraph_segment = ExtractedSegment(
                    block_type=segment.block_type,
                    content=paragraph,
                    page_num=segment.page_num,
                    bbox=segment.bbox,
                    page_width=segment.page_width,
                    page_height=segment.page_height,
                    block_index=segment.block_index,
                )
                if pending_text is None:
                    pending_text = paragraph
                    pending_segment = paragraph_segment
                    continue

                if paragraph_index > 0 or pending_segment is None or self._should_break_before(pending_segment, paragraph_segment):
                    output_lines.append(pending_text.strip())
                    last_output_type = pending_segment.block_type if pending_segment else None
                    pending_text = paragraph
                else:
                    pending_text = self._join_wrapped_text(pending_text, paragraph)
                pending_segment = paragraph_segment

        if pending_text:
            output_lines.append(pending_text.strip())
            last_output_type = pending_segment.block_type if pending_segment else last_output_type
        result = "\n".join(line for line in output_lines if line).strip()
        if result and last_output_type in _HARD_TRAILING_NEWLINE_TYPES and not result.endswith("\n"):
            result += "\n"
        return result

    # ------------------------------------------------------------------
    # Legacy helpers (kept for backward compatibility)
    # ------------------------------------------------------------------

    def clean_catalog_line(self, line: str) -> str:
        """Normalize a TOC line while preserving title-like units and page tokens."""
        stripped = line.strip()
        if not stripped:
            return ""

        if _TOC_HEADING_RE.match(stripped):
            return "目录"
        if _TOC_TITLE_LIKE_RE.match(stripped):
            return stripped
        if self._is_likely_toc_noise_line(stripped):
            return ""

        match = _TOC_PAREN_PAGE_RE.match(stripped)
        if match:
            title = self._normalize_inline_whitespace(match.group("title"))
            title = re.sub(rf"[{_CATALOG_CONNECTOR_CHARS}]+$", "", title).strip()
            page_token = match.group("page").replace(" ", "")
            if not title or self._is_likely_toc_noise_line(title):
                return ""
            return f"{title}...{page_token}"

        match = (
            _CATALOG_PAGE_ONLY_RE.match(stripped)
            or _CATALOG_SINGLE_DASH_RE.match(stripped)
            or _CATALOG_LINE_RE.match(stripped)
        )
        if not match:
            return stripped

        title = self._normalize_inline_whitespace(match.group("title"))
        title = re.sub(rf"[{_CATALOG_CONNECTOR_CHARS}]+$", "", title).strip()
        page_num_str = match.group("page")
        if not title or not page_num_str:
            return stripped
        return f"{title}...{page_num_str}"

    def _is_likely_toc_noise_line(self, line: str) -> bool:
        """Conservative TOC noise detector for short OCR garbage tokens."""
        stripped = self._normalize_inline_whitespace(line)
        if not stripped:
            return True
        if _TOC_HEADING_RE.match(stripped) or _TOC_TITLE_LIKE_RE.match(stripped):
            return False
        if _TOC_PAGE_TOKEN_RE.search(stripped):
            return False
        if re.search(r"[A-Za-z0-9]", stripped):
            return False
        if re.fullmatch(rf"[\u4e00-\u9fff]{{1,{_MAX_TOC_NOISE_CJK_LENGTH}}}", stripped):
            return True
        return False

    def process_catalog_block(self, text: str) -> str:
        """Process a catalog block and emit one normalized entry per line."""
        lines = [line for line in text.split("\n") if line.strip()]
        cleaned_lines: list[str] = []
        for idx, line in enumerate(lines):
            cleaned = self.clean_catalog_line(line)
            if not cleaned:
                continue
            prev_structured = any(self._match_catalog_line(item) or _TOC_TITLE_LIKE_RE.match(item) for item in cleaned_lines[-2:])
            next_raw = lines[idx + 1] if idx + 1 < len(lines) else ""
            next_structured = bool(self._match_catalog_line(next_raw.strip()) or _TOC_TITLE_LIKE_RE.match(next_raw.strip()))
            is_short_cjk = bool(
                re.fullmatch(rf"[\u4e00-\u9fff]{{1,{_MAX_TOC_INLINE_NOISE_CJK_LENGTH}}}", cleaned)
            ) and not bool(
                _TOC_TITLE_LIKE_RE.match(cleaned)
            )
            if prev_structured and next_structured and (self._is_likely_toc_noise_line(cleaned) or is_short_cjk):
                continue
            cleaned_lines.append(cleaned)
        if not cleaned_lines:
            return ""
        return "".join(f"{line}\n" for line in cleaned_lines if line)


_pdf_service: PDFService | None = None


def get_pdf_service() -> PDFService:
    global _pdf_service
    if _pdf_service is None:
        _pdf_service = PDFService()
    return _pdf_service
