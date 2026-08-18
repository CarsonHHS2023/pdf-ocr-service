"""PDF processing service using PaddleOCR-VL 1.6.

Processing rules applied to each block in ``parsing_res_list``:

1. **TOC** (toc / catalog / table_of_contents / directory)
   Each line is normalised to ``title...page_number\\n``.

2. **Title** (doc_title / paragraph_title / title / heading / …)
   Emitted verbatim followed by a single ``\\n``.

3. **Paragraph text** (text / paragraph / body / abstract / …)
   Natural soft-wraps inside the block are collapsed; a single ``\\n``
   is appended at the end of the paragraph.

4. **Visual blocks** (image / figure / table / seal / figure_caption /
   figure_title / table_caption / vision_footnote / …)
   Treated as images: the region (plus any immediately-following caption
   blocks) is cropped from the PyMuPDF-rendered page, persisted to the
   database (when ``book_id`` and ``db`` are both supplied) and replaced
   by a ``$%$%$%{image_id}$%$%$%`` marker.

5. **Everything else** – silently ignored.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Optional

import numpy as np

from app.image_service import get_image_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Block-label classification sets
# ---------------------------------------------------------------------------

# Block types that are rendered as image crops and emitted as $%$%$% markers.
_VISUAL_LABELS: frozenset[str] = frozenset(
    {
        "image",
        "figure",
        "picture",
        "photo",
        "chart",
        "diagram",
        "graphic",
        "illustration",
        "artwork",
        "screenshot",
        "table",
        "seal",
        "stamp",
    }
)

# Caption / annotation types that are grouped with the preceding visual block.
_CAPTION_LABELS: frozenset[str] = frozenset(
    {
        "figure_caption",
        "figure_title",
        "figure_note",
        "table_caption",
        "vision_footnote",
        "caption",
    }
)

# Table-of-contents labels.
_TOC_LABELS: frozenset[str] = frozenset(
    {
        "toc",
        "catalog",
        "table_of_contents",
        "contents",
        "directory",
    }
)

# Title / heading labels (doc-level or paragraph-level).
_TITLE_LABELS: frozenset[str] = frozenset(
    {
        "doc_title",
        "document_title",
        "paragraph_title",
        "para_title",
        "title",
        "heading",
        "section_title",
        "headline",
    }
)

# Body-text labels.
_TEXT_LABELS: frozenset[str] = frozenset(
    {
        "text",
        "paragraph",
        "body",
        "body_text",
        "content",
        "abstract",
        "formula",
        "equation",
        "formula_number",
        "equation_number",
        "algorithm",
    }
)

# ---------------------------------------------------------------------------
# TOC-line normalisation helpers (mirrors logic in pdf_service.py)
# ---------------------------------------------------------------------------

_CATALOG_CONNECTOR_CHARS = r"\.\.．。·•・‧⋯…\-—–_─━﹣－\s"
_CATALOG_LINE_RE = re.compile(
    rf"^(?P<title>.+?\S)\s*(?P<connector>[{_CATALOG_CONNECTOR_CHARS}]{{2,}})\s*(?P<page>\d+)\s*$"
)
_CATALOG_PAGE_ONLY_RE = re.compile(r"^(?P<title>.+?\S)\s{2,}(?P<page>\d+)\s*$")
_CATALOG_SINGLE_DASH_RE = re.compile(
    r"^(?P<title>.+?\S)\s+(?P<connector>[\-—–﹣－])\s+(?P<page>\d+)\s*$"
)
_TOC_PAREN_PAGE_RE = re.compile(
    r"^(?P<title>.*[\u4e00-\u9fff].*?\S)\s*(?P<page>[（(][0-9０-９]+[）)])\s*$"
)
_TOC_HEADING_RE = re.compile(r"^\s*目\s*录\s*$")
_TOC_TITLE_LIKE_RE = re.compile(
    r"^(?:目录|前言|序言?|后记|附录"
    r"|[一二三四五六七八九十百千万0-9]+[篇章节部卷]"
    r"|[\u4e00-\u9fff]{2,12}(?:篇|章|节|部))$"
)
_TOC_PAGE_TOKEN_RE = re.compile(
    r"(?P<page>(?:[（(][0-9０-９]+[）)])|(?:[0-9０-９]+))\s*$"
)

_MAX_TOC_NOISE_CJK_LENGTH = 3

# ---------------------------------------------------------------------------
# PyMuPDF rendering DPI (must match whatever PaddleOCR-VL uses internally
# when receiving numpy arrays so bboxes are in the same pixel-space).
# ---------------------------------------------------------------------------
_RENDER_DPI = 300


def _render_page_as_bgr(doc: Any, page_num: int, dpi: int = _RENDER_DPI) -> np.ndarray:
    """Render a PDF page to a 3-channel uint8 BGR numpy array."""
    page = doc.load_page(page_num)
    scale = dpi / 72.0
    import fitz  # type: ignore[import]

    matrix = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    img_data = np.frombuffer(pix.samples, dtype=np.uint8)
    img = img_data.reshape(pix.height, pix.width, pix.n)
    if pix.n == 3:
        img = np.ascontiguousarray(img[:, :, [2, 1, 0]])  # RGB → BGR
    return img


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PaddleOCRVLPDFService:
    """Extracts and formats PDF content using PaddleOCR-VL 1.6.

    Workflow per PDF:
    1. Render every page to a BGR numpy array with PyMuPDF at ``_RENDER_DPI``.
    2. Pass the list of page images to ``PaddleOCRVL.predict()``.
    3. Call ``restructure_pages()`` for cross-page structural refinement.
    4. For each page result, iterate ``parsing_res_list`` in reading order
       and apply the formatting rules described in the module docstring.

    When *both* ``book_id`` and ``db`` are supplied visual-block crops are
    persisted via ``ImageService``; otherwise a hash-based ID is used.
    """

    def __init__(self) -> None:
        self._pipeline: Any = None
        self._pipeline_initialized = False

    # ------------------------------------------------------------------
    # Lazy pipeline accessor
    # ------------------------------------------------------------------

    def _get_pipeline(self) -> Any:
        if not self._pipeline_initialized:
            try:
                from paddleocr import PaddleOCRVL  # type: ignore[import]

                self._pipeline = PaddleOCRVL(pipeline_version="v1.6")
                logger.info("PaddleOCR-VL 1.6 pipeline initialised successfully")
            except ImportError as exc:
                logger.warning(
                    "PaddleOCR-VL unavailable (ImportError): %s – "
                    "install 'paddleocr[doc-parser]' to enable",
                    exc,
                )
                self._pipeline = None
            except Exception as exc:
                logger.error(
                    "PaddleOCR-VL pipeline init error: %s",
                    exc,
                    exc_info=True,
                )
                self._pipeline = None
            self._pipeline_initialized = True
        return self._pipeline

    def is_available(self) -> bool:
        """Return True when ``PaddleOCRVL`` can be imported."""
        try:
            from paddleocr import PaddleOCRVL  # type: ignore[import]  # noqa: F401

            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_pdf_content(
        self,
        pdf_path: str | Path,
        book_id: Optional[str] = None,
        db: Any = None,
    ) -> str:
        """Process *pdf_path* with PaddleOCR-VL 1.6 and return formatted TXT.

        Args:
            pdf_path: Path to the PDF file.
            book_id:  Optional book identifier used when persisting image crops.
            db:       Optional SQLAlchemy session used together with *book_id*.

        Returns:
            A single string with formatted text and ``$%$%$%{id}$%$%$%`` markers
            for visual blocks.

        Raises:
            RuntimeError: when PaddleOCR-VL is not importable.
        """
        pipeline = self._get_pipeline()
        if pipeline is None:
            raise RuntimeError(
                "PaddleOCR-VL is not available. "
                "Install 'paddleocr[doc-parser]' to enable."
            )

        import fitz  # type: ignore[import]

        pdf_path = str(pdf_path)
        logger.info("PaddleOCR-VL 1.6 extraction started: %s", pdf_path)

        doc = fitz.open(pdf_path)
        try:
            # ── 1. Render all pages to BGR images ──────────────────────────
            page_images: list[np.ndarray] = [
                _render_page_as_bgr(doc, i) for i in range(doc.page_count)
            ]
            logger.info(
                "Rendered %d page(s) at %d DPI for PaddleOCR-VL",
                len(page_images),
                _RENDER_DPI,
            )

            # ── 2. Run PaddleOCR-VL on all pages ───────────────────────────
            raw_output = list(pipeline.predict(page_images))
            output = pipeline.restructure_pages(raw_output)

            # ── 3. Collect formatted output ────────────────────────────────
            result_parts: list[str] = []

            for page_idx, res in enumerate(output):
                try:
                    res_data: dict = dict(res)
                except Exception as exc:
                    logger.warning(
                        "Failed to convert PaddleOCR-VL output to dict for page %d (type=%s): %s",
                        page_idx + 1,
                        type(res),
                        exc,
                    )
                    res_data = {}

                parsing_res_list: list[dict] = res_data.get("parsing_res_list", [])
                if not parsing_res_list:
                    logger.warning(
                        "parsing_res_list is empty for page %d. res_data keys: %s",
                        page_idx + 1,
                        list(res_data.keys()),
                    )
                page_img = page_images[page_idx] if page_idx < len(page_images) else None

                logger.info(
                    "Processing page %d: %d block(s)",
                    page_idx + 1,
                    len(parsing_res_list),
                )

                result_parts.extend(
                    self._process_page_blocks(
                        parsing_res_list,
                        page_img=page_img,
                        page_num=page_idx + 1,
                        book_id=book_id,
                        db=db,
                    )
                )

            content = "".join(result_parts).strip()
            logger.info(
                "PaddleOCR-VL extraction completed: %d chars",
                len(content),
            )
            return content

        finally:
            doc.close()

    # ------------------------------------------------------------------
    # Per-page block processing
    # ------------------------------------------------------------------

    def _process_page_blocks(
        self,
        parsing_res_list: list[dict],
        page_img: Optional[np.ndarray],
        page_num: int,
        book_id: Optional[str],
        db: Any,
    ) -> list[str]:
        """Convert one page's ``parsing_res_list`` to formatted text parts."""
        parts: list[str] = []
        i = 0
        while i < len(parsing_res_list):
            block = parsing_res_list[i]
            label = str(block.get("block_label", "")).strip().lower()
            content = str(block.get("block_content", "")).strip()
            bbox = self._parse_bbox(block.get("block_bbox"))

            # ── Visual / caption blocks ────────────────────────────────────
            if label in _VISUAL_LABELS or label in _CAPTION_LABELS:
                combined_bbox = bbox
                j = i + 1
                # Absorb immediately-following caption-only blocks.
                while j < len(parsing_res_list):
                    next_label = (
                        str(parsing_res_list[j].get("block_label", ""))
                        .strip()
                        .lower()
                    )
                    if next_label not in _CAPTION_LABELS:
                        break
                    cap_bbox = self._parse_bbox(
                        parsing_res_list[j].get("block_bbox")
                    )
                    combined_bbox = self._merge_bboxes(combined_bbox, cap_bbox)
                    j += 1

                if page_img is not None and combined_bbox:
                    image_id = self._persist_block_image(
                        page_img=page_img,
                        bbox=combined_bbox,
                        block_type=label,
                        page_num=page_num,
                        block_index=i,
                        book_id=book_id,
                        db=db,
                    )
                    parts.append(f"$%$%$%{image_id}$%$%$%\n")
                    logger.debug(
                        "Page %d: visual block label=%s bbox=%s → %s",
                        page_num,
                        label,
                        combined_bbox,
                        image_id,
                    )

                i = j

            # ── Title blocks ───────────────────────────────────────────────
            elif label in _TITLE_LABELS:
                text = self._normalize_inline(content)
                if text:
                    parts.append(text + "\n")
                i += 1

            # ── Table of contents blocks ───────────────────────────────────
            elif label in _TOC_LABELS:
                toc_text = self._process_toc_block(content)
                if toc_text:
                    parts.append(toc_text)
                i += 1

            # ── Body-text paragraphs ───────────────────────────────────────
            elif label in _TEXT_LABELS:
                para = self._normalize_paragraph(content)
                if para:
                    parts.append(para + "\n")
                i += 1

            # ── Everything else is ignored ─────────────────────────────────
            else:
                logger.debug(
                    "Page %d: ignoring block label=%s", page_num, label
                )
                i += 1

        return parts

    # ------------------------------------------------------------------
    # Bounding-box helpers
    # ------------------------------------------------------------------

    def _parse_bbox(
        self, raw: Any
    ) -> Optional[tuple[int, int, int, int]]:
        """Normalise various bbox representations to ``(x1, y1, x2, y2)`` ints."""
        if raw is None:
            return None
        try:
            if isinstance(raw, np.ndarray):
                raw = raw.tolist()
            if isinstance(raw, (list, tuple)):
                if len(raw) == 4 and not isinstance(raw[0], (list, tuple)):
                    vals = [float(v) for v in raw]
                    x1 = int(round(vals[0]))
                    y1 = int(round(vals[1]))
                    x2 = int(round(vals[2]))
                    y2 = int(round(vals[3]))
                    return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
                if (
                    len(raw) == 4
                    and isinstance(raw[0], (list, tuple))
                    and all(
                        isinstance(pt, (list, tuple)) and len(pt) == 2
                        for pt in raw
                    )
                ):
                    xs = [float(pt[0]) for pt in raw]
                    ys = [float(pt[1]) for pt in raw]
                    return (
                        int(min(xs)),
                        int(min(ys)),
                        int(max(xs)),
                        int(max(ys)),
                    )
        except Exception:
            pass
        return None

    def _merge_bboxes(
        self,
        a: Optional[tuple[int, int, int, int]],
        b: Optional[tuple[int, int, int, int]],
    ) -> Optional[tuple[int, int, int, int]]:
        """Return the smallest rectangle containing both *a* and *b*."""
        if a is None:
            return b
        if b is None:
            return a
        return (
            min(a[0], b[0]),
            min(a[1], b[1]),
            max(a[2], b[2]),
            max(a[3], b[3]),
        )

    # ------------------------------------------------------------------
    # Image persistence
    # ------------------------------------------------------------------

    def _persist_block_image(
        self,
        page_img: np.ndarray,
        bbox: tuple[int, int, int, int],
        block_type: str,
        page_num: int,
        block_index: int,
        book_id: Optional[str],
        db: Any,
    ) -> str:
        """Crop *bbox* from *page_img*, persist if possible, and return an ID."""
        import cv2  # type: ignore[import]

        x1, y1, x2, y2 = bbox
        h, w = page_img.shape[:2]
        x1, x2 = max(0, x1), min(w, x2)
        y1, y2 = max(0, y1), min(h, y2)

        crop = page_img[y1:y2, x1:x2]
        if crop.size == 0:
            logger.warning(
                "Empty crop for block type=%s page=%d bbox=%r – skipping",
                block_type,
                page_num,
                bbox,
            )
            return "img_empty"

        ok, enc = cv2.imencode(".png", crop)
        if not ok:
            logger.warning("cv2.imencode failed for block type=%s page=%d", block_type, page_num)
            return "img_encode_fail"
        png_bytes = enc.tobytes()

        if book_id and db is not None:
            try:
                bbox_str = f"{x1},{y1},{x2},{y2}"
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
                    "Persisted visual block: image_id=%s page=%d idx=%d type=%s bbox=%s",
                    image_id,
                    page_num,
                    block_index,
                    block_type,
                    bbox_str,
                )
                return image_id
            except Exception as exc:
                logger.warning(
                    "Could not persist visual block (page=%d idx=%d type=%s): %s",
                    page_num,
                    block_index,
                    block_type,
                    exc,
                )

        # Fallback: deterministic hash-based ID (not stored in DB)
        fallback_id = "img_" + hashlib.sha256(png_bytes).hexdigest()[:16]
        logger.debug("Using hash-based image ID (not persisted): %s", fallback_id)
        return fallback_id

    # ------------------------------------------------------------------
    # Text normalisation helpers
    # ------------------------------------------------------------------

    def _normalize_inline(self, text: str) -> str:
        """Collapse all whitespace variants to single ASCII spaces."""
        text = text.replace("\u3000", " ")
        return re.sub(r"\s+", " ", text).strip()

    def _normalize_paragraph(self, text: str) -> str:
        """Merge wrapped lines into a single paragraph string.

        - CJK-to-CJK boundaries: concatenate directly (no space).
        - Hyphen-split words: remove hyphen and join.
        - Punctuation continuation: attach without space.
        - All other boundaries: insert a single space.
        """
        lines = [
            self._normalize_inline(line)
            for line in text.splitlines()
            if line.strip()
        ]
        if not lines:
            return ""

        result = lines[0]
        for line in lines[1:]:
            if not line:
                continue
            if result.endswith("-"):
                result = result[:-1] + line
            elif re.match(r"^[,\.;:!?\)\]%）】》、，。！？；：]", line):
                result += line
            elif re.search(r"[\u4e00-\u9fff]$", result) or re.match(
                r"^[\u4e00-\u9fff]", line
            ):
                result += line
            else:
                result += " " + line
        return result

    # ------------------------------------------------------------------
    # TOC line normalisation
    # ------------------------------------------------------------------

    def _process_toc_block(self, text: str) -> str:
        """Normalise a TOC block to one ``title...page_number\\n`` per entry."""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        out: list[str] = []
        for line in lines:
            cleaned = self._clean_toc_line(line)
            if cleaned:
                out.append(cleaned + "\n")
        return "".join(out)

    def _clean_toc_line(self, line: str) -> str:
        """Rewrite one raw TOC line to ``title...page_number`` format."""
        stripped = line.strip()
        if not stripped:
            return ""

        if _TOC_HEADING_RE.match(stripped):
            return "目录"
        if _TOC_TITLE_LIKE_RE.match(stripped):
            return stripped
        if self._is_toc_noise(stripped):
            return ""

        # Parenthesised page token: e.g. "第一章 概述（5）"
        match = _TOC_PAREN_PAGE_RE.match(stripped)
        if match:
            title = self._normalize_inline(match.group("title"))
            title = re.sub(
                rf"[{_CATALOG_CONNECTOR_CHARS}]+$", "", title
            ).strip()
            page_token = match.group("page").replace(" ", "")
            if not title or self._is_toc_noise(title):
                return ""
            return f"{title}...{page_token}"

        match = (
            _CATALOG_PAGE_ONLY_RE.match(stripped)
            or _CATALOG_SINGLE_DASH_RE.match(stripped)
            or _CATALOG_LINE_RE.match(stripped)
        )
        if not match:
            return stripped

        title = self._normalize_inline(match.group("title"))
        title = re.sub(
            rf"[{_CATALOG_CONNECTOR_CHARS}]+$", "", title
        ).strip()
        page_num_str = match.group("page")
        if not title or not page_num_str:
            return stripped
        return f"{title}...{page_num_str}"

    def _is_toc_noise(self, line: str) -> bool:
        """Return True for very short CJK-only fragments that are OCR noise."""
        stripped = self._normalize_inline(line)
        if not stripped:
            return True
        if _TOC_HEADING_RE.match(stripped) or _TOC_TITLE_LIKE_RE.match(stripped):
            return False
        if _TOC_PAGE_TOKEN_RE.search(stripped):
            return False
        if re.search(r"[A-Za-z0-9]", stripped):
            return False
        return bool(
            re.fullmatch(
                rf"[\u4e00-\u9fff]{{1,{_MAX_TOC_NOISE_CJK_LENGTH}}}",
                stripped,
            )
        )


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------

_vl_service: PaddleOCRVLPDFService | None = None


def get_paddleocr_vl_service() -> PaddleOCRVLPDFService:
    """Return the module-level ``PaddleOCRVLPDFService`` singleton."""
    global _vl_service
    if _vl_service is None:
        _vl_service = PaddleOCRVLPDFService()
    return _vl_service
