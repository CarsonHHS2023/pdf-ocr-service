"""Enhanced PDF processing service using PyMuPDF and PaddleX layout analysis."""

from __future__ import annotations

import json
import logging
import io
import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional, List
from dataclasses import dataclass, field
import numpy as np
import fitz  # PyMuPDF

from app.config import settings

logger = logging.getLogger(__name__)

# Canonical layout block types produced by the pipeline.
# Core downstream stats keep the original five canonical classes.
_CANONICAL_TYPES: tuple[str, ...] = ("title", "toc", "text", "image", "table")

_LAYOUT_BLOCK_TYPE_ALIASES = {
    # PP-DocLayout-L: document title → "title"
    "doc_title": "title",
    "document_title": "title",
    # PP-DocLayout-L: paragraph/section title → "title"
    "para_title": "title",
    "paragraph_title": "title",
    "title": "title",
    "heading": "title",
    "headline": "title",
    "section_title": "title",
    # PP-DocLayout-L: plain text → "text"
    "text": "text",
    "paragraph": "text",
    "body": "text",
    "body_text": "text",
    "content": "text",
    # PP-DocLayout-L: text-like regions that are OCR'd like body text
    "abstract": "text",
    "algorithm": "text",
    "formula": "text",
    "equation": "text",
    "formula_number": "text",
    "equation_number": "text",
    "aside_text": "text",
    "sidebar": "text",
    "marginal_note": "text",
    # toc / catalog
    "toc": "toc",
    "catalog": "toc",
    "contents": "toc",
    "table_of_contents": "toc",
    "directory": "toc",
    # header/footer (skipped in extraction)
    "header": "header",
    "page_header": "header",
    "running_header": "header",
    "footer": "footer",
    "page_footer": "footer",
    "running_footer": "footer",
    # PP-DocLayout-L: additional ignore regions (passed through as-is so
    # pdf_service can skip them explicitly)
    "page_num": "page_number",
    "page_number": "page_number",
    "pagenumber": "page_number",
    "reference": "references",
    "references": "references",
    "bibliography": "references",
    "footnotes": "footnotes",
    "footnote": "footnotes",
    "header_image": "header_image",
    "footer_image": "footer_image",
    # PP-DocLayout-L: seal/stamp → treated as a visual image block
    "seal": "image",
    "stamp": "image",
    # caption / note-like → merged into adjacent visual block
    "caption": "caption",
    "figure_caption": "caption",
    "table_caption": "caption",
    "fig_caption": "caption",
    "figure_title": "caption",
    "note": "caption",
    "annotation": "caption",
    # image-like
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
    # table-like
    "table": "table",
    "tabular": "table",
    "spreadsheet": "table",
    "grid": "table",
}
_LAYOUT_VISUAL_BLOCK_TYPES = {"image", "table"}


def _ensure_bgr_uint8(img: np.ndarray) -> np.ndarray:
    """Ensure *img* is a 3-channel uint8 BGR array for the PaddleX layout pipeline.

    PaddleX ``PP-StructureV3`` layout detection expects a (H, W, 3) uint8 BGR
    image.  This helper applies the necessary conversions.  A new array is
    always returned when any conversion is required; for a ``(H, W, 3) uint8``
    input the same array is returned unchanged (no copy):

    * ``(H, W)``      – grayscale → replicated to 3-channel BGR.
    * ``(H, W, 1)``   – single-channel → replicated to 3-channel BGR.
    * ``(H, W, 4)``   – BGRA → alpha dropped, 3-channel BGR kept.
    * ``dtype != uint8`` – values clipped to [0, 255] and cast to uint8.
    * ``(H, W, 3) uint8`` – returned as-is (no copy).
    """
    import cv2  # import here to keep module-level imports clean

    if img.dtype != np.uint8:
        img = np.clip(img, 0, 255).astype(np.uint8)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.ndim == 3:
        if img.shape[2] == 1:
            img = cv2.cvtColor(img[:, :, 0], cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        # shape (H, W, 3) is already correct
    return img


def _make_paddlex_layout_analyzer(pipeline: Any):
    """Wrap a PaddleX layout pipeline as a callable returning normalised block dicts.

    The wrapper accepts a numpy BGR image and returns a list of dicts in the form::

        [{"type": "<raw_label>", "bbox": [x1, y1, x2, y2], "score": <float>}, ...]

    PaddleX >= 3.0 ``predict()`` yields result objects whose box information may
    arrive in several shapes:

    * **Shape 1 – dict with ``"boxes"`` key** (typical for PaddleX 3.x serialised
      output): ``{"boxes": [{"label": "text", "score": 0.9, "coordinate": [x1, y1, x2, y2]}, …]}``.
      Boxes may also be nested under a ``"res"`` sub-dict.
    * **Shape 2 – object with ``.boxes`` attribute** (PaddleX object-based API):
      each box is either a dict or an object with ``label``, ``score``, and
      ``coordinate``/``bbox`` attributes.

    Error handling:

    * If ``pipeline.predict()`` itself raises, the error is logged at ERROR level
      and an empty list is returned so that ``analyze_layout`` can fall back
      gracefully on that page rather than aborting the whole document.
    * Individual malformed boxes (missing ``coordinate``/``bbox``) are silently
      skipped; the rest of the page's detections are still returned.
    """

    def _analyze(img: np.ndarray) -> list[dict]:
        import math

        blocks: list[dict] = []
        raw_results: list[Any] = []
        attempt_summaries: list[str] = []
        candidate_keys: tuple[str, ...] = (
            "boxes",
            "layout_result",
            "det_boxes",
            "dt_polys",
            "res_list",
            "results",
        )
        coord_keys: tuple[str, ...] = (
            "coordinate",
            "bbox",
            "box",
            "poly",
            "polygon",
            "points",
        )
        label_keys: tuple[str, ...] = (
            "label",
            "type",
            "cls_name",
            "class_name",
            "category",
        )
        diagnostic_key_limit = 12

        def _to_raw_results(prediction: Any) -> list[Any]:
            if prediction is None:
                return []
            if isinstance(prediction, list):
                return prediction
            if isinstance(prediction, tuple):
                return list(prediction)
            if isinstance(prediction, dict):
                return [prediction]
            try:
                return list(prediction)
            except TypeError:
                return [prediction]

        def _get_value(obj: Any, key: str) -> Any:
            if isinstance(obj, dict):
                return obj.get(key)
            value = getattr(obj, key, None)
            if value is not None:
                return value
            try:
                return obj[key]
            except (KeyError, TypeError, IndexError):
                return None

        def _to_float(value: Any) -> Optional[float]:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(number):
                return None
            return number

        def _normalize_rect(raw_coord: Any) -> Optional[list[float]]:
            if raw_coord is None:
                return None

            coord_items: list[Any]
            if isinstance(raw_coord, np.ndarray):
                coord_items = raw_coord.tolist()
            elif isinstance(raw_coord, (list, tuple)):
                coord_items = list(raw_coord)
            else:
                try:
                    coord_items = list(raw_coord)
                except TypeError:
                    return None

            # [x1, y1, x2, y2]
            if len(coord_items) == 4:
                numeric = [_to_float(v) for v in coord_items]
                if all(v is not None for v in numeric):
                    numeric_values = [float(v) for v in numeric if v is not None]
                    x1, y1, x2, y2 = numeric_values
                    left, right = min(x1, x2), max(x1, x2)
                    top, bottom = min(y1, y2), max(y1, y2)
                    if right <= left or bottom <= top:
                        return None
                    return [left, top, right, bottom]

            # polygon/points: [[x,y], ...] or [{"x":..,"y":..}, ...] or [x1,y1,...]
            points: list[tuple[float, float]] = []
            for item in coord_items:
                if isinstance(item, dict):
                    x_val = _to_float(item.get("x"))
                    y_val = _to_float(item.get("y"))
                    if x_val is not None and y_val is not None:
                        points.append((x_val, y_val))
                    continue
                if isinstance(item, np.ndarray):
                    item = item.tolist()
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    x_val = _to_float(item[0])
                    y_val = _to_float(item[1])
                    if x_val is not None and y_val is not None:
                        points.append((x_val, y_val))

            if len(points) < 2 and len(coord_items) >= 4 and len(coord_items) % 2 == 0:
                flat_numeric = [_to_float(v) for v in coord_items]
                if all(v is not None for v in flat_numeric):
                    values = [float(v) for v in flat_numeric if v is not None]
                    points = list(zip(values[0::2], values[1::2]))

            if len(points) >= 2:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                left, right = min(xs), max(xs)
                top, bottom = min(ys), max(ys)
                if right <= left or bottom <= top:
                    return None
                return [left, top, right, bottom]

            return None

        def _extract_bbox(box: Any) -> Optional[list[float]]:
            rect = _normalize_rect(box)
            if rect is not None:
                return rect
            for key in coord_keys:
                rect = _normalize_rect(_get_value(box, key))
                if rect is not None:
                    return rect
            return None

        def _extract_label(box: Any) -> str:
            for key in label_keys:
                value = _get_value(box, key)
                if value is not None:
                    label = str(value).strip()
                    if label:
                        return label
            return "text"

        def _extract_score(box: Any) -> float:
            for key in ("score", "confidence"):
                value = _to_float(_get_value(box, key))
                if value is not None:
                    return value
            return 0.0

        attempts: list[tuple[str, Any]] = [
            ("list_img", [img]),
            ("ndarray_img", img),
            ("dict_img", {"img": img}),
        ]
        for attempt_name, attempt_input in attempts:
            try:
                prediction = pipeline.predict(attempt_input)
                candidate_results = _to_raw_results(prediction)
                logger.info(
                    "PaddleX predict attempt=%s input_type=%s raw_results=%d",
                    attempt_name,
                    type(attempt_input).__name__,
                    len(candidate_results),
                )
                attempt_summaries.append(
                    f"{attempt_name}:{len(candidate_results)}"
                )
                if candidate_results:
                    raw_results = candidate_results
                    break
            except Exception as exc:
                logger.warning(
                    "PaddleX predict attempt failed: attempt=%s input_type=%s error=%s",
                    attempt_name,
                    type(attempt_input).__name__,
                    exc,
                    exc_info=True,
                )
                attempt_summaries.append(f"{attempt_name}:error={exc}")

        if not raw_results:
            tmp_path: Optional[str] = None
            try:
                import cv2  # import here to keep module-level imports clean
                import tempfile

                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                    tmp_path = tmp.name
                cv2.imwrite(tmp_path, img)

                prediction = pipeline.predict(tmp_path)
                candidate_results = _to_raw_results(prediction)
                logger.info(
                    "PaddleX predict attempt=%s input_type=%s raw_results=%d",
                    "tmp_path",
                    "str",
                    len(candidate_results),
                )
                attempt_summaries.append(f"tmp_path:{len(candidate_results)}")
                if candidate_results:
                    raw_results = candidate_results
            except Exception as exc:
                logger.warning(
                    "PaddleX predict attempt failed: attempt=%s input_type=%s error=%s",
                    "tmp_path",
                    "str",
                    exc,
                    exc_info=True,
                )
                attempt_summaries.append(f"tmp_path:error={exc}")
            finally:
                if tmp_path:
                    try:
                        Path(tmp_path).unlink(missing_ok=True)
                    except Exception as cleanup_exc:
                        logger.warning(
                            "Failed to remove PaddleX temp image path=%s error=%s",
                            tmp_path,
                            cleanup_exc,
                        )

        if not raw_results:
            logger.warning(
                "PaddleX pipeline.predict() produced no results after attempts: %s",
                "; ".join(attempt_summaries) if attempt_summaries else "none",
            )
            return blocks

        parse_diagnostics: list[dict[str, Any]] = []
        for result_item in raw_results:
            nested_res = _get_value(result_item, "res")
            layout_det_res = _get_value(result_item, "layout_det_res")
            parsing_res_list = _get_value(result_item, "parsing_res_list")
            probe_targets: list[tuple[str, Any]] = [("item", result_item)]
            if nested_res is not None:
                probe_targets.append(("res", nested_res))
            if layout_det_res is not None:
                probe_targets.append(("layout_det_res", layout_det_res))

            def _to_iterable_items(value: Any) -> list[Any]:
                if value is None:
                    return []
                if isinstance(value, dict):
                    return list(value.values())
                if isinstance(value, (list, tuple)):
                    return list(value)
                try:
                    return list(value)
                except TypeError:
                    return [value]

            def _candidate_presence(target: Any) -> dict[str, list[str]]:
                present_keys: list[str] = []
                absent_keys: list[str] = []
                for key in candidate_keys:
                    if _get_value(target, key) is not None:
                        present_keys.append(key)
                    else:
                        absent_keys.append(key)
                return {
                    "present": present_keys,
                    "absent": absent_keys,
                }

            def _extend_blocks_from_target(target: Any) -> None:
                for key in candidate_keys:
                    box_list = _get_value(target, key)
                    if box_list is None:
                        continue
                    iterable_boxes = _to_iterable_items(box_list)
                    for box in iterable_boxes:
                        coord = _extract_bbox(box)
                        if coord is None:
                            continue
                        raw_label = _extract_label(box)
                        score = _extract_score(box)
                        blocks.append({"type": raw_label, "bbox": coord, "score": score})

            key_presence: dict[str, dict[str, list[str]]] = {}
            blocks_before_item = len(blocks)
            for target_name, target in probe_targets:
                key_presence[target_name] = _candidate_presence(target)
                _extend_blocks_from_target(target)

            parsing_key_presence: list[dict[str, list[str]]] = []
            if len(blocks) == blocks_before_item and parsing_res_list is not None:
                for parsing_item in _to_iterable_items(parsing_res_list):
                    parsing_key_presence.append(_candidate_presence(parsing_item))
                    _extend_blocks_from_target(parsing_item)

            parse_diagnostics.append(
                {
                    "item_type": type(result_item).__name__,
                    "item_keys": list(result_item.keys())[:diagnostic_key_limit] if isinstance(result_item, dict) else None,
                    "layout_det_res_present": layout_det_res is not None,
                    "layout_det_res_candidate_keys": (
                        _candidate_presence(layout_det_res) if layout_det_res is not None else None
                    ),
                    "res_type": type(nested_res).__name__ if nested_res is not None else None,
                    "res_keys": list(nested_res.keys())[:diagnostic_key_limit] if isinstance(nested_res, dict) else None,
                    "candidate_keys": key_presence,
                    "parsing_res_list_count": len(_to_iterable_items(parsing_res_list)),
                    "parsing_res_list_candidate_keys": parsing_key_presence[:2],
                }
            )

        if raw_results and not blocks:
            logger.warning(
                "PaddleX parsing produced zero blocks: raw_results=%d diagnostics=%s",
                len(raw_results),
                parse_diagnostics[:3],
            )

        return blocks

    return _analyze


@dataclass
class LayoutBlock:
    """Represents a detected layout block."""
    block_type: str  # "text", "image", "table", etc.
    bbox: tuple  # (x1, y1, x2, y2) - bounding box coordinates
    confidence: float = 1.0
    page_num: int = 0
    image_data: Optional[np.ndarray] = None  # Cropped image data


@dataclass
class PageLayout:
    """Layout analysis result for a single page."""
    page_num: int
    total_pages: int
    blocks: List[LayoutBlock] = field(default_factory=list)
    raw_image: Optional[np.ndarray] = None
    preprocessed_image: Optional[np.ndarray] = None
    selected_engine: str = "fallback_ocr_only"
    fallback_reason: Optional[str] = None
    block_type_counts: dict[str, int] = field(default_factory=dict)
    raw_block_type_counts: dict[str, int] = field(default_factory=dict)
    diagnostics_path: Optional[str] = None


class EnhancedPDFService:
    """Service for PDF processing with PyMuPDF and layout analysis."""

    def __init__(self):
        """Initialize enhanced PDF service."""
        self._ocr_service = None
        self._layout_analyzer = None
        self._layout_engine_initialized = False
        self._layout_engine_status = {
            "selected_engine": "fallback_ocr_only",
            "reason": "layout engine not initialized",
            "engine_name": None,
            "pipeline_name": None,
        }

    def _get_ocr_service(self):
        """Get OCR service lazily."""
        if self._ocr_service is None:
            from app.ocr_service import get_ocr_service
            self._ocr_service = get_ocr_service()
        return self._ocr_service

    def _get_layout_analyzer(self):
        """Get layout analyzer lazily.

        Primary engine: PaddleX PP-StructureV3 pipeline with the
        PP-DocLayout_plus-L layout detection model (via ``pdx.create_pipeline``).
        PP-DocLayout_plus-L is PaddleX 3.x's newest, highest-precision 23-class
        layout detection model; PP-StructureV3 is the recommended pipeline that
        wraps it.  If PaddleX is unavailable the service enters degraded mode and
        a clear warning is surfaced so operators know structural extraction is
        disabled.
        """
        if not self._layout_engine_initialized:
            configured_engine_value = getattr(settings, "layout_engine", None)
            configured_engine = (
                "auto"
                if configured_engine_value is None
                else str(configured_engine_value).strip().lower()
            )
            try:
                if configured_engine in {"fallback", "fallback_ocr_only", "ocr_only"}:
                    self._layout_analyzer = None
                    self._set_layout_engine_status(
                        "fallback_ocr_only",
                        f"layout engine forced by config: {configured_engine}",
                    )
                    logger.info(
                        "Layout engine selection: selected_engine=%s fallback_reason=%s",
                        self._layout_engine_status["selected_engine"],
                        self._layout_engine_status["reason"],
                    )
                    return self._layout_analyzer

                # --- Primary path: PaddleX PP-StructureV3 pipeline with PP-DocLayout_plus-L ---
                # PP-DocLayout_plus-L is a 23-class layout detection model (mAP 83.2%)
                # trained on Chinese/English papers, PPT, magazines, contracts, books,
                # exams, ancient books and research reports.  It is the default layout
                # model used by the PP-StructureV3 document understanding pipeline.
                import paddlex as pdx  # type: ignore[import]

                pipeline_name = "PP-StructureV3"
                model_name = "PP-DocLayout_plus-L"
                logger.info(
                    "Initializing PaddleX pipeline: pipeline=%s layout_model=%s",
                    pipeline_name,
                    model_name,
                )
                pipeline = pdx.create_pipeline(
                    pipeline=pipeline_name,
                    layout_detection_model_name=model_name,
                )
                self._layout_analyzer = _make_paddlex_layout_analyzer(pipeline)
                paddlex_version = getattr(pdx, "__version__", "unknown")
                try:
                    from paddleocr import __version__ as paddleocr_version  # type: ignore[import]
                except Exception:
                    paddleocr_version = "unknown"
                self._set_layout_engine_status(
                    "paddlex_pipeline",
                    pipeline_name=pipeline_name,
                    engine_name=model_name,
                )
                logger.info(
                    "Layout engine initialized: selected_engine=paddlex_pipeline "
                    "paddlex_version=%s paddleocr_version=%s pipeline=%s model=%s",
                    paddlex_version,
                    paddleocr_version,
                    pipeline_name,
                    model_name,
                )
            except ImportError as exc:
                errmsg = f"paddlex_unavailable: {exc}"
                logger.error(
                    "Layout engine init failed — PaddleX not importable. "
                    "Install paddlex[ocr]>=3.0.0 to enable title/toc/image/table extraction. "
                    "Error: %s",
                    exc,
                )
                logger.warning(
                    "DEGRADED MODE active: layout analysis unavailable. "
                    "Only plain text will be extracted until PaddleX is available. "
                    "selected_engine=fallback_ocr_only fallback_reason=%s",
                    errmsg,
                )
                self._set_layout_engine_status("fallback_ocr_only", errmsg)
                self._layout_analyzer = None
            except Exception as exc:
                errmsg = f"paddlex_init_error: {exc}"
                logger.error(
                    "Layout engine init failed — PaddleX pipeline creation error: %s",
                    exc,
                    exc_info=True,
                )
                logger.warning(
                    "DEGRADED MODE active: layout analysis unavailable. "
                    "Check PaddleX installation and model availability. "
                    "selected_engine=fallback_ocr_only fallback_reason=%s",
                    errmsg,
                )
                self._set_layout_engine_status("fallback_ocr_only", errmsg)
                self._layout_analyzer = None
            finally:
                self._layout_engine_initialized = True
                logger.info(
                    "Layout engine selection: selected_engine=%s fallback_reason=%s",
                    self._layout_engine_status["selected_engine"],
                    self._layout_engine_status["reason"],
                )
        return self._layout_analyzer

    def _set_layout_engine_status(
        self,
        selected_engine: str,
        reason: Optional[str] = None,
        engine_name: Optional[str] = None,
        pipeline_name: Optional[str] = None,
    ) -> None:
        """Persist the latest layout-engine selection for diagnostics/logging."""
        self._layout_engine_status = {
            "selected_engine": selected_engine,
            "reason": reason,
            "engine_name": engine_name,
            "pipeline_name": pipeline_name,
        }

    def _get_layout_engine_status(self) -> dict[str, Optional[str]]:
        """Return a shallow copy of the latest layout-engine selection."""
        return dict(self._layout_engine_status)

    def load_pdf(self, pdf_path: str | Path) -> fitz.Document:
        """
        Load PDF document using PyMuPDF.

        Args:
            pdf_path: Path to PDF file

        Returns:
            PyMuPDF Document object
        """
        try:
            pdf_path = str(pdf_path)
            logger.info(f"Loading PDF: {pdf_path}")
            
            doc = fitz.open(pdf_path)
            logger.info(f"PDF loaded successfully: {doc.page_count} pages")
            return doc
            
        except Exception as e:
            logger.error(f"Failed to load PDF: {e}")
            raise

    def extract_page_as_image(self, doc: fitz.Document, page_num: int,
                             dpi: int = 300) -> np.ndarray:
        """
        Extract a page from PDF and convert to image.

        Args:
            doc: PyMuPDF Document
            page_num: Page number (0-indexed)
            dpi: Rendering DPI (higher = better quality)

        Returns:
            Image as numpy array (BGR format)
        """
        try:
            page = doc.load_page(page_num)
            
            # Render page to image with specified DPI
            # 72 is default DPI, we multiply by (dpi/72)
            scale = dpi / 72.0
            matrix = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            
            # Convert pixmap to numpy array
            img_data = np.frombuffer(pix.samples, dtype=np.uint8)
            img = img_data.reshape(pix.height, pix.width, pix.n)
            
            # Convert RGB to BGR (OpenCV format)
            if pix.n == 3:
                img = np.ascontiguousarray(img[:, :, [2, 1, 0]])
            
            logger.debug(f"Extracted page {page_num} as image: {img.shape}")
            return img
            
        except Exception as e:
            logger.error(f"Failed to extract page {page_num} as image: {e}")
            raise

    def analyze_layout(self, img: np.ndarray, page_num: int = 0) -> PageLayout:
        """Analyze page layout using the PaddleX pipeline.

        Args:
            img: Image as numpy array
            page_num: Page number

        Returns:
            PageLayout with detected blocks.  ``block_type_counts`` always
            contains all five canonical types (title/toc/text/image/table),
            with zero for types that were not detected on this page.
        """
        try:
            layout_analyzer = self._get_layout_analyzer()
            engine_status = self._get_layout_engine_status()
            
            if layout_analyzer is None:
                logger.warning(
                    "Layout analyzer unavailable on page %d: selected_engine=%s fallback_reason=%s",
                    page_num + 1,
                    engine_status["selected_engine"],
                    engine_status["reason"],
                )
                return self._fallback_layout_analysis(
                    img,
                    page_num,
                    reason=engine_status["reason"],
                )
            
            logger.info(
                "Analyzing layout for page %d with selected_engine=%s",
                page_num + 1,
                engine_status["selected_engine"],
            )

            # Ensure the image is 3-channel uint8 BGR before feeding PaddleX.
            # Layout must run on the original colour image – not a grayscale
            # preprocessed version – to preserve structural cues.
            layout_img = _ensure_bgr_uint8(img)
            logger.info(
                "Layout input: page=%d input_shape=%s input_dtype=%s bgr_shape=%s",
                page_num + 1,
                img.shape,
                img.dtype,
                layout_img.shape,
            )

            # Run layout analysis
            result = layout_analyzer(layout_img)
            
            # Parse results
            blocks = []
            raw_blocks_metadata: list[dict[str, Any]] = []
            raw_type_counts: Counter[str] = Counter()
            if isinstance(result, list) and len(result) > 0:
                for item in result:
                    if isinstance(item, dict):
                        raw_type = item.get("type", "text")
                        block_type = self._normalize_block_type(raw_type)
                        raw_type_counts[block_type] += 1
                        bbox = self._normalize_bbox(item.get("bbox"), img)
                        confidence = item.get("score")
                        if confidence is None:
                            confidence = item.get("confidence")
                        if confidence is None:
                            confidence = 0.0
                        raw_blocks_metadata.append(
                            {
                                "raw_type": raw_type,
                                "type": block_type,
                                "bbox": list(bbox) if bbox else None,
                                "score": confidence,
                            }
                        )
                        
                        if bbox:
                            block = LayoutBlock(
                                block_type=block_type,
                                bbox=bbox,
                                confidence=confidence,
                                page_num=page_num
                            )
                            blocks.append(block)
            blocks = self._merge_visual_with_caption_blocks(blocks, layout_img)
            kept_type_counts = Counter(block.block_type for block in blocks)

            # Per-page 5-type diagnostics always include all canonical types (zeros for absent).
            canonical_counts = {t: kept_type_counts.get(t, 0) for t in _CANONICAL_TYPES}

            diagnostics_path = self._persist_page_debug_artifact(
                page_num=page_num,
                selected_engine=engine_status["selected_engine"] or "fallback_ocr_only",
                fallback_reason=engine_status["reason"],
                total_blocks=len(raw_blocks_metadata),
                blocks_metadata=raw_blocks_metadata,
            )
            logger.info(
                "Page %d layout diagnostics: selected_engine=%s total_blocks=%d "
                "before_filter=%s after_filter=%s "
                "canonical title=%d toc=%d text=%d image=%d table=%d",
                page_num + 1,
                engine_status["selected_engine"],
                len(raw_blocks_metadata),
                dict(raw_type_counts),
                dict(kept_type_counts),
                canonical_counts["title"],
                canonical_counts["toc"],
                canonical_counts["text"],
                canonical_counts["image"],
                canonical_counts["table"],
            )
            
            return PageLayout(
                page_num=page_num,
                total_pages=1,  # Will be set by caller
                blocks=blocks,
                raw_image=img,
                selected_engine=engine_status["selected_engine"] or "fallback_ocr_only",
                fallback_reason=engine_status["reason"],
                block_type_counts=canonical_counts,
                raw_block_type_counts=dict(raw_type_counts),
                diagnostics_path=diagnostics_path,
            )
            
        except Exception as e:
            logger.error(f"Failed to analyze layout: {e}")
            logger.warning("Using fallback layout analysis")
            return self._fallback_layout_analysis(
                img,
                page_num,
                reason=f"layout_runtime_error: {e}",
            )

    def _fallback_layout_analysis(
        self,
        img: np.ndarray,
        page_num: int = 0,
        reason: Optional[str] = None,
    ) -> PageLayout:
        """Fallback layout analysis when PaddleX pipeline is unavailable.

        Treats the entire image as a single text block.  The five-type
        canonical counts are always returned with zeros for absent types.

        Args:
            img: Image as numpy array
            page_num: Page number

        Returns:
            PageLayout with single full-page block
        """
        logger.info(f"Using fallback layout analysis for page {page_num}")
        
        h, w = img.shape[:2]
        blocks = [
            LayoutBlock(
                block_type="text",
                bbox=(0, 0, w, h),
                confidence=1.0,
                page_num=page_num
            )
        ]
        canonical_counts = {"title": 0, "toc": 0, "text": 1, "image": 0, "table": 0}
        return PageLayout(
            page_num=page_num,
            total_pages=1,
            blocks=blocks,
            raw_image=img,
            selected_engine="fallback_ocr_only",
            fallback_reason=reason,
            block_type_counts=canonical_counts,
            raw_block_type_counts={"text": 1},
        )

    def crop_block_image(self, img: np.ndarray, bbox: tuple) -> np.ndarray:
        """
        Crop image region based on bounding box.

        Args:
            img: Full image as numpy array
            bbox: Bounding box (x1, y1, x2, y2)

        Returns:
            Cropped image
        """
        try:
            x1, y1, x2, y2 = bbox
            # Convert to integers
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            
            # Ensure bounds
            h, w = img.shape[:2]
            x1 = max(0, min(x1, w))
            y1 = max(0, min(y1, h))
            x2 = max(0, min(x2, w))
            y2 = max(0, min(y2, h))
            
            cropped = img[y1:y2, x1:x2]
            logger.debug(f"Cropped image region: ({x1}, {y1}) to ({x2}, {y2})")
            return cropped
            
        except Exception as e:
            logger.error(f"Failed to crop image: {e}")
            return img

    def _normalize_block_type(self, block_type: Any) -> str:
        """Normalize layout analyzer block aliases."""
        normalized = str(block_type or "text").strip().lower()
        normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
        return _LAYOUT_BLOCK_TYPE_ALIASES.get(normalized, normalized or "text")

    def _expand_bbox_union(
        self,
        bbox_a: tuple[int, int, int, int],
        bbox_b: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int]:
        """Return union bbox of two rectangular regions."""
        return (
            min(bbox_a[0], bbox_b[0]),
            min(bbox_a[1], bbox_b[1]),
            max(bbox_a[2], bbox_b[2]),
            max(bbox_a[3], bbox_b[3]),
        )

    def _horizontal_overlap_ratio(
        self,
        bbox_a: tuple[int, int, int, int],
        bbox_b: tuple[int, int, int, int],
    ) -> float:
        """Compute horizontal overlap over the smaller width."""
        overlap = max(0, min(bbox_a[2], bbox_b[2]) - max(bbox_a[0], bbox_b[0]))
        min_width = max(1, min(bbox_a[2] - bbox_a[0], bbox_b[2] - bbox_b[0]))
        return overlap / min_width

    def _merge_visual_with_caption_blocks(self, blocks: list[LayoutBlock], img: np.ndarray) -> list[LayoutBlock]:
        """Merge nearby caption/note blocks into image/table blocks."""
        visual_indices = [idx for idx, block in enumerate(blocks) if block.block_type in _LAYOUT_VISUAL_BLOCK_TYPES]
        caption_indices = [idx for idx, block in enumerate(blocks) if block.block_type == "caption"]
        if not visual_indices or not caption_indices:
            return blocks

        page_height = img.shape[0] if hasattr(img, "shape") and img.ndim >= 2 else 0
        max_caption_gap = max(60, int(page_height * 0.08))
        consumed_captions: set[int] = set()

        for caption_idx in caption_indices:
            caption_block = blocks[caption_idx]
            c_bbox = caption_block.bbox
            best_visual_idx = -1
            best_distance = float("inf")
            for visual_idx in visual_indices:
                visual_block = blocks[visual_idx]
                v_bbox = visual_block.bbox
                overlap_ratio = self._horizontal_overlap_ratio(c_bbox, v_bbox)
                if overlap_ratio < 0.3:
                    continue
                if c_bbox[1] >= v_bbox[3]:
                    distance = c_bbox[1] - v_bbox[3]
                elif v_bbox[1] >= c_bbox[3]:
                    distance = v_bbox[1] - c_bbox[3]
                else:
                    distance = 0
                if distance > max_caption_gap:
                    continue
                if distance < best_distance:
                    best_distance = distance
                    best_visual_idx = visual_idx

            if best_visual_idx < 0:
                continue

            merged_visual = blocks[best_visual_idx]
            merged_visual.bbox = self._expand_bbox_union(merged_visual.bbox, c_bbox)
            merged_visual.confidence = max(merged_visual.confidence, caption_block.confidence)
            consumed_captions.add(caption_idx)

        if not consumed_captions:
            return blocks

        merged_blocks = [block for idx, block in enumerate(blocks) if idx not in consumed_captions]
        return merged_blocks

    def _persist_page_debug_artifact(
        self,
        page_num: int,
        selected_engine: str,
        fallback_reason: Optional[str],
        total_blocks: int,
        blocks_metadata: list[dict[str, Any]],
    ) -> Optional[str]:
        """Optionally persist page-level block metadata for troubleshooting."""
        if not getattr(settings, "layout_debug_enabled", False):
            return None

        debug_dir = Path(getattr(settings, "layout_debug_dir", Path("output/layout_debug")))
        debug_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = debug_dir / f"page_{page_num + 1:04d}.json"
        artifact = {
            "page_index": page_num,
            "selected_engine": selected_engine,
            "fallback_reason": fallback_reason,
            "total_blocks": total_blocks,
            "blocks": blocks_metadata,
        }
        artifact_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Wrote page layout debug artifact: %s", artifact_path)
        return str(artifact_path)

    def _normalize_bbox(self, bbox: Any, img: np.ndarray) -> Optional[tuple[int, int, int, int]]:
        """Normalize and clip bbox coordinates to image bounds."""
        if bbox is None:
            return None

        x1 = y1 = x2 = y2 = None
        if isinstance(bbox, dict):
            if {"x1", "y1", "x2", "y2"} <= set(bbox.keys()):
                x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]
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

        h, w = img.shape[:2]
        x1, y1, x2, y2 = [int(round(v)) for v in (x1, y1, x2, y2)]
        x1 = max(0, min(x1, w))
        x2 = max(0, min(x2, w))
        y1 = max(0, min(y1, h))
        y2 = max(0, min(y2, h))

        if x2 <= x1 or y2 <= y1:
            return None
        return (x1, y1, x2, y2)

    def process_pdf(self, pdf_path: str | Path,
                   dpi: int = 300,
                   denoise_strength: int = 10,
                   enhance_contrast: float = 2.0) -> List[PageLayout]:
        """
        Process entire PDF document.

        Args:
            pdf_path: Path to PDF file
            dpi: Rendering DPI
            denoise_strength: Deprecated (kept for backward compatibility)
            enhance_contrast: Deprecated (kept for backward compatibility)

        Returns:
            List of PageLayout for each page
        """
        try:
            _ = denoise_strength, enhance_contrast
            doc = self.load_pdf(pdf_path)
            page_layouts = []
            total_pages = doc.page_count
            
            logger.info(f"Processing PDF with {total_pages} pages")
            
            for page_num in range(total_pages):
                # Initialise per-page variables so the exception handler can
                # safely access them even when an early step fails.
                raw_img = None
                try:
                    logger.info(f"Processing page {page_num + 1}/{total_pages}")
                    
                    # 1. Extract page as image (3-channel BGR)
                    raw_img = self.extract_page_as_image(doc, page_num, dpi=dpi)

                    # 2. Analyze layout on the original colour image so that
                    # PaddleX receives the full 3-channel signal it expects.
                    page_layout = self.analyze_layout(raw_img, page_num)
                    page_layout.total_pages = total_pages
                    page_layout.raw_image = raw_img

                    # 3. Crop block images from the original image. Text
                    # preprocessing is deferred to step-6 per-block OCR.
                    for block in page_layout.blocks:
                        block.image_data = self.crop_block_image(raw_img, block.bbox)
                    
                    page_layouts.append(page_layout)
                    logger.debug(f"Page {page_num + 1} processed: {len(page_layout.blocks)} blocks")
                    
                except Exception as e:
                    logger.error(
                        "Error processing page %d: %s; attempting OCR-only fallback",
                        page_num + 1,
                        e,
                        exc_info=True,
                    )
                    if raw_img is not None:
                        # Use the OCR-only fallback so the page still contributes
                        # text content rather than being silently dropped.
                        try:
                            page_layout = self._fallback_layout_analysis(
                                raw_img,
                                page_num,
                                reason=f"page_processing_error: {e}",
                            )
                            page_layout.total_pages = total_pages
                            page_layouts.append(page_layout)
                            logger.warning(
                                "Fallback activated for page %d: "
                                "selected_engine=%s fallback_reason=%s",
                                page_num + 1,
                                page_layout.selected_engine,
                                page_layout.fallback_reason,
                            )
                        except Exception as fallback_err:
                            logger.error(
                                "Fallback also failed for page %d: %s",
                                page_num + 1,
                                fallback_err,
                            )
                    else:
                        logger.error(
                            "Cannot apply fallback for page %d: raw image unavailable",
                            page_num + 1,
                        )
            
            doc.close()
            logger.info(f"PDF processing completed: {len(page_layouts)} pages processed")
            return page_layouts
            
        except Exception as e:
            logger.error(f"Failed to process PDF: {e}")
            raise


# Singleton instance
_enhanced_pdf_service: EnhancedPDFService | None = None


def get_enhanced_pdf_service() -> EnhancedPDFService:
    """Get or create enhanced PDF service singleton."""
    global _enhanced_pdf_service
    if _enhanced_pdf_service is None:
        _enhanced_pdf_service = EnhancedPDFService()
    return _enhanced_pdf_service
