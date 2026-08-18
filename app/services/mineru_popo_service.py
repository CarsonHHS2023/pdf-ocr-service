"""MinerU-Popo post-processing service.

Takes the per-page PaddleOCR-VL results stored in ``PdfPage.ocr_raw_json``
and produces a single structured document by applying:

1. **Paragraph recovery** – merge continuation lines within and across blocks.
2. **Cross-page recovery** – detect text paragraphs that span page boundaries.
3. **Heading hierarchy recovery** – assign H1/H2/H3 levels based on position
   and frequency.
4. **Image-text association** – attach figure/table captions to their visual
   blocks.
5. **Table cross-page recovery** – merge table blocks that split across pages.

MinerU intermediate JSON format stored in ``MineruResult.result_json``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A JSON array of content-block dicts, one per logical document element:

    [
        {"type": "title",  "level": 1, "content": "Book Title",   "page_num": 1},
        {"type": "title",  "level": 2, "content": "Chapter 1",    "page_num": 1},
        {"type": "text",   "content": "Paragraph text …",          "page_num": 1},
        {"type": "image",  "image_id": "img_abc123",
         "caption": "Figure 1: example",                            "page_num": 2},
        {"type": "table",  "image_id": "img_def456",
         "caption": "Table 1: results",                             "page_num": 3},
        {"type": "toc",    "content": "目录项…1\\n",               "page_num": 1},
    ]

magic-pdf (MinerU) model_list compatible per-page format
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
When an optional ``magic-pdf`` installation is detected, the service converts
the per-page blocks to magic-pdf's ``model_list`` format::

    {
        "page_info": {"page_no": 0, "height": 3508, "width": 2480},
        "layout_dets": [
            {
                "category_id": <int>,   # see _VL_LABEL_TO_CATEGORY below
                "poly": [x0,y0,x1,y1,x2,y2,x3,y3],
                "score": 1.0,
                "text": "<ocr text>"    # for text/title blocks
            }
        ]
    }

Category-ID mapping (magic-pdf convention):
    0  title            1  plain_text       2  abandon (header/footer)
    3  figure           4  figure_caption   5  table
    6  table_caption    7  table_footnote   8  isolate_formula
    9  formula_caption
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# CJK unified ideographs Unicode range (used in multiple regex patterns)
_CJK_RANGE = r"[\u4e00-\u9fff]"

# ---------------------------------------------------------------------------
# PaddleOCR-VL block_label → magic-pdf category_id
# ---------------------------------------------------------------------------

_VL_LABEL_TO_CATEGORY: dict[str, int] = {
    # title / heading → 0
    "doc_title": 0, "document_title": 0, "title": 0, "heading": 0,
    "paragraph_title": 0, "section_title": 0, "headline": 0, "para_title": 0,
    # plain text → 1
    "text": 1, "paragraph": 1, "body": 1, "body_text": 1, "content": 1,
    "abstract": 1, "algorithm": 1, "toc": 1, "catalog": 1,
    "contents": 1, "table_of_contents": 1, "directory": 1,
    "reference": 1, "aside_text": 1, "sidebar": 1, "marginal_note": 1,
    # abandon → 2
    "header": 2, "footer": 2, "page_header": 2, "page_footer": 2,
    # figure → 3
    "image": 3, "figure": 3, "picture": 3, "photo": 3, "chart": 3,
    "diagram": 3, "graphic": 3, "illustration": 3, "artwork": 3,
    "screenshot": 3, "seal": 3, "stamp": 3,
    # figure_caption → 4
    "figure_caption": 4, "figure_title": 4, "figure_note": 4, "caption": 4,
    # table → 5
    "table": 5, "tabular": 5,
    # table_caption → 6
    "table_caption": 6, "table_title": 6,
    # table_footnote → 7
    "vision_footnote": 7, "table_footnote": 7,
    # formula → 8
    "formula": 8, "equation": 8, "formula_number": 8, "equation_number": 8,
}

# Visual labels that will be cropped and stored as images
_VISUAL_CATS: frozenset[int] = frozenset({3, 5})         # figure, table
_CAPTION_CATS: frozenset[int] = frozenset({4, 6, 7})     # captions / footnotes
_TITLE_CATS: frozenset[int] = frozenset({0})
_TEXT_CATS: frozenset[int] = frozenset({1})
_ABANDON_CATS: frozenset[int] = frozenset({2})
_FORMULA_CATS: frozenset[int] = frozenset({8, 9})


# ---------------------------------------------------------------------------
# Internal block representation
# ---------------------------------------------------------------------------

class _Block:
    __slots__ = ("label", "cat", "content", "bbox", "page_num")

    def __init__(
        self,
        label: str,
        cat: int,
        content: str,
        bbox: list[int],
        page_num: int,
    ) -> None:
        self.label = label
        self.cat = cat
        self.content = content
        self.bbox = bbox          # [x1, y1, x2, y2]
        self.page_num = page_num


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class MineruPopoService:
    """Convert per-page PaddleOCR-VL JSON → structured document blocks.

    The heavy lifting (cross-page merging, heading levels, etc.) is done via
    the internal helpers.  If the optional ``magic-pdf`` package is installed
    the service delegates to it after building the ``model_list``; otherwise
    the built-in rules are applied.
    """

    # ------------------------------------------------------------------
    # Public entry-point
    # ------------------------------------------------------------------

    def process(
        self,
        book_id: str,
        pages: list[Any],  # list[PdfPage]
        db: Any,
    ) -> str:
        """Process all pages and return ``result_json`` as a JSON string.

        Args:
            book_id: Book ID used when persisting image crops.
            pages:   Ordered list of PdfPage ORM objects (must have
                     ``page_num``, ``page_width``, ``page_height``,
                     ``page_image_data``, and ``ocr_raw_json`` populated).
            db:      Active SQLAlchemy session.

        Returns:
            JSON string (list of content-block dicts).
        """
        # 1. Parse all per-page OCR JSON
        raw_pages = self._load_raw_pages(pages)

        # 2. Crop visual blocks → save to book_images → embed image_ids
        processed = self._embed_visual_blocks(raw_pages, pages, book_id, db)

        # 3. Build model_list for potential magic-pdf use
        model_list = self._build_model_list(processed)

        # 4. Try magic-pdf; fall back to built-in rules
        if self._magic_pdf_available():
            try:
                result_blocks = self._run_magic_pdf(book_id, pages, model_list, db)
                return json.dumps(result_blocks, ensure_ascii=False)
            except Exception as exc:
                logger.warning(
                    "magic-pdf processing failed (%s); using built-in rules", exc
                )

        # 5. Built-in document reconstruction
        result_blocks = self._reconstruct(processed)
        return json.dumps(result_blocks, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Step 1: Load per-page OCR JSON
    # ------------------------------------------------------------------

    def _load_raw_pages(self, pages: list[Any]) -> list[list[_Block]]:
        """Parse ``ocr_raw_json`` from each PdfPage into lists of _Block."""
        all_page_blocks: list[list[_Block]] = []
        for page in pages:
            blocks: list[_Block] = []
            try:
                payload: dict = json.loads(page.ocr_raw_json or "{}")
                page_num: int = payload.get("page_num", page.page_num)
                for raw in payload.get("parsing_res_list", []):
                    label = str(raw.get("block_label", "")).strip().lower()
                    content = str(raw.get("block_content", "")).strip()
                    bbox_raw = raw.get("block_bbox")
                    bbox = self._parse_bbox(bbox_raw)
                    cat = _VL_LABEL_TO_CATEGORY.get(label, 1)
                    blocks.append(_Block(label, cat, content, bbox, page_num))
            except Exception as exc:
                logger.warning(
                    "Failed to parse OCR JSON for page %s: %s", page.page_num, exc
                )
            all_page_blocks.append(blocks)
        return all_page_blocks

    # ------------------------------------------------------------------
    # Step 2: Crop visual blocks and persist to book_images
    # ------------------------------------------------------------------

    def _embed_visual_blocks(
        self,
        raw_pages: list[list[_Block]],
        pages: list[Any],
        book_id: str,
        db: Any,
    ) -> list[list[dict]]:
        """Crop visual blocks from page images and replace with image_ids.

        Returns a new list-of-lists of dicts suitable for reconstruction,
        where visual blocks have type "image"/"table" and an "image_id" key.
        """
        from app.image_service import get_image_service

        image_service = get_image_service()
        result: list[list[dict]] = []

        for page_idx, (blk_list, page_orm) in enumerate(zip(raw_pages, pages)):
            page_dicts: list[dict] = []
            i = 0
            while i < len(blk_list):
                blk = blk_list[i]

                if blk.cat in _VISUAL_CATS:
                    # Absorb following captions
                    combined_bbox = blk.bbox[:]
                    caption_parts: list[str] = []
                    j = i + 1
                    while j < len(blk_list):
                        nxt = blk_list[j]
                        if nxt.cat not in _CAPTION_CATS:
                            break
                        combined_bbox = self._merge_bboxes(combined_bbox, nxt.bbox)
                        if nxt.content:
                            caption_parts.append(nxt.content)
                        j += 1

                    image_id = self._crop_and_save(
                        page_orm,
                        combined_bbox,
                        blk.label,
                        blk.page_num,
                        i,
                        book_id,
                        db,
                        image_service,
                    )
                    block_type = "table" if blk.cat == 5 else "image"
                    page_dicts.append({
                        "type": block_type,
                        "image_id": image_id,
                        "caption": " ".join(caption_parts),
                        "page_num": blk.page_num,
                        "bbox": combined_bbox,
                    })
                    i = j

                elif blk.cat in _CAPTION_CATS:
                    # Orphan caption (no preceding visual block on this page)
                    page_dicts.append({
                        "type": "text",
                        "content": blk.content,
                        "page_num": blk.page_num,
                        "bbox": blk.bbox,
                    })
                    i += 1

                elif blk.cat in _TITLE_CATS:
                    page_dicts.append({
                        "type": "title",
                        "content": blk.content,
                        "page_num": blk.page_num,
                        "bbox": blk.bbox,
                    })
                    i += 1

                elif blk.cat in _TEXT_CATS:
                    page_dicts.append({
                        "type": "text",
                        "content": blk.content,
                        "page_num": blk.page_num,
                        "bbox": blk.bbox,
                    })
                    i += 1

                elif blk.cat in _FORMULA_CATS:
                    page_dicts.append({
                        "type": "text",
                        "content": blk.content,
                        "page_num": blk.page_num,
                        "bbox": blk.bbox,
                    })
                    i += 1

                else:
                    # abandon (header/footer) or unknown → skip
                    i += 1

            result.append(page_dicts)
        return result

    def _crop_and_save(
        self,
        page_orm: Any,
        bbox: list[int],
        block_type: str,
        page_num: int,
        block_index: int,
        book_id: str,
        db: Any,
        image_service: Any,
    ) -> str:
        """Crop *bbox* from page image and persist; return image_id."""
        import cv2  # type: ignore[import]
        import hashlib

        if not page_orm.page_image_data or not bbox:
            return "img_empty"

        nparr = np.frombuffer(page_orm.page_image_data, dtype=np.uint8)
        page_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if page_img is None:
            return "img_decode_fail"

        x1, y1, x2, y2 = bbox
        h, w = page_img.shape[:2]
        x1, x2 = max(0, x1), min(w, x2)
        y1, y2 = max(0, y1), min(h, y2)
        crop = page_img[y1:y2, x1:x2]
        if crop.size == 0:
            return "img_empty"

        ok, enc = cv2.imencode(".png", crop)
        if not ok:
            return "img_encode_fail"
        png_bytes = enc.tobytes()

        try:
            image_id = image_service.save_image(
                db=db,
                book_id=book_id,
                image_data=png_bytes,
                image_format="png",
                page_num=page_num,
                bbox=f"{x1},{y1},{x2},{y2}",
                block_type=block_type,
            )
            return image_id
        except Exception as exc:
            logger.warning("Could not persist image block (page=%d): %s", page_num, exc)
            return "img_" + hashlib.sha256(png_bytes).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Step 3: Build magic-pdf model_list
    # ------------------------------------------------------------------

    def _build_model_list(self, processed: list[list[dict]]) -> list[dict]:
        """Convert processed page blocks to magic-pdf model_list format."""
        model_list: list[dict] = []
        for page_idx, page_blocks in enumerate(processed):
            layout_dets = []
            for blk in page_blocks:
                bbox = blk.get("bbox") or [0, 0, 0, 0]
                x1, y1, x2, y2 = bbox
                poly = [x1, y1, x2, y1, x2, y2, x1, y2]
                blk_type = blk["type"]
                if blk_type == "title":
                    cat_id = 0
                elif blk_type in ("image",):
                    cat_id = 3
                elif blk_type == "table":
                    cat_id = 5
                else:
                    cat_id = 1  # plain_text
                det: dict = {
                    "category_id": cat_id,
                    "poly": poly,
                    "score": 1.0,
                    "latex": "",
                    "html": "",
                }
                if blk_type in ("text", "title"):
                    det["text"] = blk.get("content", "")
                elif blk_type in ("image", "table"):
                    det["image_id"] = blk.get("image_id", "")
                    det["text"] = blk.get("caption", "")
                layout_dets.append(det)

            # Infer page dimensions from blocks (fallback to 0)
            if page_blocks:
                max_x = max(
                    (b.get("bbox") or [0, 0, 0, 0])[2] for b in page_blocks
                )
                max_y = max(
                    (b.get("bbox") or [0, 0, 0, 0])[3] for b in page_blocks
                )
            else:
                max_x = max_y = 0

            model_list.append({
                "page_info": {
                    "page_no": page_idx,
                    "height": max_y or 3508,
                    "width": max_x or 2480,
                },
                "layout_dets": layout_dets,
            })
        return model_list

    # ------------------------------------------------------------------
    # Step 4a: magic-pdf (optional)
    # ------------------------------------------------------------------

    def _magic_pdf_available(self) -> bool:
        try:
            import magic_pdf  # type: ignore[import]  # noqa: F401
            return True
        except ImportError:
            return False

    def _run_magic_pdf(
        self,
        book_id: str,
        pages: list[Any],
        model_list: list[dict],
        db: Any,
    ) -> list[dict]:
        """Use magic-pdf pipeline for post-processing.

        Requires the ``magic-pdf`` package (``pip install magic-pdf``).
        The PDF bytes are reconstructed from stored page images in memory.
        """
        raise NotImplementedError(
            "magic-pdf integration not yet wired; built-in rules will be used."
        )

    # ------------------------------------------------------------------
    # Step 4b: Built-in document reconstruction
    # ------------------------------------------------------------------

    def _reconstruct(self, processed: list[list[dict]]) -> list[dict]:
        """Apply built-in post-processing rules to assembled document.

        Rules applied in order:
        1. Flatten all pages into a single block list.
        2. Paragraph cross-page recovery: merge consecutive text blocks
           where the previous block ends mid-sentence.
        3. Table cross-page recovery: merge consecutive table blocks.
        4. Heading hierarchy: assign levels 1-3 to title blocks.
        5. Image-text association: already done in _embed_visual_blocks.
        """
        # Flatten
        flat: list[dict] = []
        for page_blocks in processed:
            flat.extend(page_blocks)

        # Cross-page text merging
        flat = self._merge_cross_page_text(flat)

        # Cross-page table merging
        flat = self._merge_cross_page_tables(flat)

        # Heading levels
        flat = self._assign_heading_levels(flat)

        return flat

    def _merge_cross_page_text(self, blocks: list[dict]) -> list[dict]:
        """Merge text blocks where a sentence continues across a page boundary."""
        if not blocks:
            return blocks
        merged: list[dict] = [blocks[0]]
        for blk in blocks[1:]:
            prev = merged[-1]
            if (
                prev["type"] == "text"
                and blk["type"] == "text"
                and prev.get("page_num", 0) != blk.get("page_num", 0)
            ):
                # Check if previous block ends mid-sentence
                prev_content: str = prev.get("content", "")
                next_content: str = blk.get("content", "")
                if self._continues_across_page(prev_content, next_content):
                    sep = "" if self._cjk_join(prev_content, next_content) else " "
                    prev["content"] = prev_content.rstrip() + sep + next_content.lstrip()
                    continue
            merged.append(blk)
        return merged

    def _merge_cross_page_tables(self, blocks: list[dict]) -> list[dict]:
        """Merge consecutive table image blocks that span pages."""
        if not blocks:
            return blocks
        merged: list[dict] = [blocks[0]]
        for blk in blocks[1:]:
            prev = merged[-1]
            if (
                prev["type"] == "table"
                and blk["type"] == "table"
                and prev.get("page_num", 0) != blk.get("page_num", 0)
                and not blk.get("caption")
            ):
                # Annotate that this table continues; keep first image_id
                prev["caption"] = (
                    (prev.get("caption") or "")
                    + f" [continued from p{prev['page_num']} to p{blk['page_num']}]"
                ).strip()
                prev["continuation_image_id"] = blk.get("image_id")
                continue
            merged.append(blk)
        return merged

    def _assign_heading_levels(self, blocks: list[dict]) -> list[dict]:
        """Assign H1/H2/H3 levels to title blocks based on content patterns."""
        title_blocks = [b for b in blocks if b["type"] == "title"]
        if not title_blocks:
            return blocks

        # Simple heuristic: first title encountered is H1 (doc title),
        # numbered sections (1., 1.1, 第一章 …) are H2,
        # unnumbered short titles are H3.
        _H1_RE = re.compile(r"^\s*(?:第[一二三四五六七八九十百千万\d]+[编册篇卷]|PART\s+[IVX\d]+)", re.I)
        _H2_RE = re.compile(
            r"^\s*(?:"
            r"第[一二三四五六七八九十百千万\d]+[章节]|"
            r"[一二三四五六七八九十百千万]、|"
            r"\d+\.\s|"
            r"Chapter\s+\d+|"
            r"Section\s+\d+"
            r")",
            re.I,
        )
        _H3_RE = re.compile(
            r"^\s*(?:"
            r"[（(]?[一二三四五六七八九十\d]+[)）.、]\s|"
            r"\d+\.\d+\s"
            r")"
        )

        first_title_seen = False
        for blk in blocks:
            if blk["type"] != "title":
                continue
            content = blk.get("content", "")
            if not first_title_seen:
                blk["level"] = 1
                first_title_seen = True
            elif _H1_RE.match(content):
                blk["level"] = 1
            elif _H2_RE.match(content):
                blk["level"] = 2
            else:
                blk["level"] = 3
        return blocks

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_bbox(raw: Any) -> list[int]:
        if raw is None:
            return [0, 0, 0, 0]
        try:
            if isinstance(raw, (list, tuple)):
                if len(raw) == 4 and not isinstance(raw[0], (list, tuple)):
                    vals = [int(round(float(v))) for v in raw]
                    x1, y1, x2, y2 = vals
                    return [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
                if (
                    len(raw) == 4
                    and isinstance(raw[0], (list, tuple))
                    and all(
                        isinstance(pt, (list, tuple)) and len(pt) == 2
                        for pt in raw
                    )
                ):
                    xs = [int(round(float(pt[0]))) for pt in raw]
                    ys = [int(round(float(pt[1]))) for pt in raw]
                    return [min(xs), min(ys), max(xs), max(ys)]
        except Exception:
            pass
        return [0, 0, 0, 0]

    @staticmethod
    def _merge_bboxes(a: list[int], b: list[int]) -> list[int]:
        if not a:
            return b
        if not b:
            return a
        return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]

    @staticmethod
    def _continues_across_page(prev: str, nxt: str) -> bool:
        """Return True if *prev* likely continues into *nxt*."""
        prev = prev.rstrip()
        nxt = nxt.lstrip()
        if not prev or not nxt:
            return False
        # Ends with a sentence-terminating punctuation → new paragraph
        if re.search(r"[。！？.!?…]\s*$", prev):
            return False
        # Next block starts with a capital / CJK / digit after whitespace → might continue
        if re.match(rf"^[a-z{_CJK_RANGE[1:-1]}\d]", nxt):
            return True
        return False

    @staticmethod
    def _cjk_join(prev: str, nxt: str) -> bool:
        """Return True if both ends are CJK characters (no space needed)."""
        prev = prev.rstrip()
        nxt = nxt.lstrip()
        if not prev or not nxt:
            return False
        return bool(
            re.search(_CJK_RANGE + r"$", prev)
            and re.match(r"^" + _CJK_RANGE, nxt)
        )


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_mineru_popo_service: MineruPopoService | None = None


def get_mineru_popo_service() -> MineruPopoService:
    global _mineru_popo_service
    if _mineru_popo_service is None:
        _mineru_popo_service = MineruPopoService()
    return _mineru_popo_service
