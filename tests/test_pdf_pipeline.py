"""Tests for the layout-aware PDF processing pipeline.

These tests verify the end-to-end PDF→TXT pipeline using mocks so they run
quickly without GPU/model dependencies.

Covered requirements
--------------------
- Mixed-content PDF (text blocks + image/table blocks) produces a TXT that
  contains both plain text and ``$%$%$%{image_id}$%$%$%`` markers.
- Marker format is exactly ``$%$%$%{image_id}$%$%$%`` (no extra delimiters).
- Processing a multi-block document does *not* collapse output to a single line.
- Per-block failures are logged and skipped; remaining blocks are still output.
- Image blocks are persisted to the DB when ``book_id`` and ``db`` are supplied.
- The ``/api/v1/upload`` endpoint writes a TXT consumed by
  ``/api/v1/books/{book_id}/content``.
"""

from __future__ import annotations

import io
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.config import settings
from app.enhanced_pdf_service import (
    EnhancedPDFService,
    LayoutBlock,
    PageLayout,
    _make_paddlex_layout_analyzer,
)
from app.main import app
from app.models import Base, BookImage, Bookshelf, ContentBlock
from app.pdf_service import PDFService

# ---------------------------------------------------------------------------
# Marker regular expression
# ---------------------------------------------------------------------------

MARKER_RE = re.compile(r"\$%\$%\$%([a-zA-Z0-9_\-]+)\$%\$%\$%")


# ---------------------------------------------------------------------------
# DB fixture (fast in-memory SQLite)
# ---------------------------------------------------------------------------


def _make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture()
def client():
    """FastAPI TestClient with a fresh in-memory SQLite database."""
    SessionLocal = _make_db()

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers to build fake PageLayout objects
# ---------------------------------------------------------------------------


def _fake_image() -> np.ndarray:
    """Return a tiny valid BGR image."""
    return np.ones((50, 50, 3), dtype=np.uint8) * 128


def _text_block(y: int = 0) -> LayoutBlock:
    block = LayoutBlock(block_type="text", bbox=(0, y, 400, y + 40))
    block.image_data = _fake_image()
    return block


def _title_block(y: int = 0) -> LayoutBlock:
    block = LayoutBlock(block_type="title", bbox=(0, y, 400, y + 50))
    block.image_data = _fake_image()
    return block


def _toc_block(y: int = 0) -> LayoutBlock:
    block = LayoutBlock(block_type="toc", bbox=(0, y, 400, y + 80))
    block.image_data = _fake_image()
    return block


def _image_block(y: int = 50) -> LayoutBlock:
    block = LayoutBlock(block_type="image", bbox=(0, y, 400, y + 100))
    block.image_data = _fake_image()
    return block


def _table_block(y: int = 160) -> LayoutBlock:
    block = LayoutBlock(block_type="table", bbox=(0, y, 400, y + 80))
    block.image_data = _fake_image()
    return block


def _make_page_layout(blocks: list[LayoutBlock], page_num: int = 0) -> PageLayout:
    img = _fake_image()
    pl = PageLayout(page_num=page_num, total_pages=1, blocks=blocks)
    pl.raw_image = img
    pl.preprocessed_image = img
    return pl


def _page_image(height: int = 400, width: int = 400, value: int = 180) -> np.ndarray:
    return np.ones((height, width, 3), dtype=np.uint8) * value


# ---------------------------------------------------------------------------
# PDFService unit tests (no HTTP, no DB)
# ---------------------------------------------------------------------------


class TestPDFServiceMarkerFormat:
    """Verify the exact marker format produced by PDFService."""

    def _run_extraction(self, blocks: list[LayoutBlock]) -> str:
        """Run extract_pdf_content with a single mocked page."""
        page_layout = _make_page_layout(blocks)

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:

            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.return_value = "some text"
            mock_ocr.return_value = mock_ocr_svc

            svc = PDFService()
            return svc.extract_pdf_content("/fake/path.pdf")

    def test_image_block_produces_marker(self):
        """An image block must produce exactly one $%$%$%....$%$%$% marker."""
        result = self._run_extraction([_image_block()])
        markers = MARKER_RE.findall(result)
        assert len(markers) == 1, f"Expected 1 marker, got {markers!r} in {result!r}"

    def test_table_block_produces_marker(self):
        """A table block must also produce a marker."""
        result = self._run_extraction([_table_block()])
        markers = MARKER_RE.findall(result)
        assert len(markers) == 1

    def test_marker_format_exactly(self):
        """Marker must start and end with the literal delimiters $%$%$%."""
        result = self._run_extraction([_image_block()])
        assert "$%$%$%" in result
        # The full pattern must match with no extra characters around the delimiters
        full_match = MARKER_RE.search(result)
        assert full_match is not None
        image_id = full_match.group(1)
        reconstructed = f"$%$%$%{image_id}$%$%$%"
        assert reconstructed in result

    def test_text_block_no_marker(self):
        """A text block must NOT produce a marker."""
        result = self._run_extraction([_text_block()])
        assert "$%$%$%" not in result

    def test_marker_image_id_not_empty(self):
        """The image_id inside the marker must be non-empty."""
        result = self._run_extraction([_image_block()])
        markers = MARKER_RE.findall(result)
        assert all(m.strip() for m in markers), "image_id inside marker must not be empty"


class TestPDFServiceMixedContent:
    """Mixed text + image documents produce both text and markers."""

    def _run_multi_block(self, blocks: list[LayoutBlock], text_per_block: str = "OCR text line") -> str:
        page_layout = _make_page_layout(blocks)

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:

            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.return_value = text_per_block
            mock_ocr.return_value = mock_ocr_svc

            svc = PDFService()
            return svc.extract_pdf_content("/fake/path.pdf")

    def test_mixed_page_has_text_and_markers(self):
        """A page with text + image blocks yields both text lines and markers."""
        blocks = [_text_block(y=0), _image_block(y=50), _text_block(y=160)]
        result = self._run_multi_block(blocks, text_per_block="paragraph text")

        assert "paragraph text" in result, "Text content missing from output"
        assert "$%$%$%" in result, "Image marker missing from output"
        markers = MARKER_RE.findall(result)
        assert len(markers) == 1, f"Expected 1 image marker, found {markers!r}"

    def test_output_has_multiple_lines(self):
        """Three blocks must produce output with more than one line (not collapsed)."""
        blocks = [_text_block(y=0), _text_block(y=50), _text_block(y=100)]
        result = self._run_multi_block(blocks, text_per_block="distinct line")
        lines = [l for l in result.split("\n") if l.strip()]
        assert len(lines) >= 2, (
            f"Expected multiple output lines, got {len(lines)}: {result!r}"
        )

    def test_reading_order_preserved(self):
        """Blocks sorted top-to-bottom produce output in that order."""
        # Block at y=100 comes after block at y=0 in the layout
        b_top = LayoutBlock(block_type="text", bbox=(0, 0, 400, 40))
        b_top.image_data = _fake_image()
        b_bot = LayoutBlock(block_type="text", bbox=(0, 100, 400, 140))
        b_bot.image_data = _fake_image()

        page_layout = _make_page_layout([b_bot, b_top])  # intentionally reversed

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:

            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            call_count = [0]
            def _ocr_side_effect(img):
                call_count[0] += 1
                return f"text_{call_count[0]}"

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.side_effect = _ocr_side_effect
            mock_ocr.return_value = mock_ocr_svc

            svc = PDFService()
            result = svc.extract_pdf_content("/fake/path.pdf")

        lines = [l for l in result.split("\n") if l.strip()]
        assert lines[0] == "text_1", f"First OCR call should be top block: {lines}"
        assert lines[1] == "text_2", f"Second OCR call should be bottom block: {lines}"

    def test_multiple_image_blocks_multiple_markers(self):
        """Two image blocks → two separate markers."""
        blocks = [_image_block(y=0), _image_block(y=110)]
        result = self._run_multi_block(blocks)
        markers = MARKER_RE.findall(result)
        assert len(markers) == 2, f"Expected 2 markers, got {markers!r}"

    def test_visual_alias_uses_page_crop_and_persists_records(self):
        """Figure/picture aliases should still emit markers and persist DB rows."""
        blocks = [
            LayoutBlock(block_type="figure", bbox=(-10, 40, 120, 180)),
            LayoutBlock(block_type="table", bbox=(150, 60, 380, 210)),
        ]
        for block in blocks:
            block.image_data = np.zeros((0, 0, 3), dtype=np.uint8)  # force page-image recrop

        page_layout = PageLayout(page_num=0, total_pages=1, blocks=blocks)
        page_layout.raw_image = _page_image()
        page_layout.preprocessed_image = _page_image(value=240)

        session = _make_db()()
        book_id = str(uuid.uuid4())
        try:
            session.add(
                Bookshelf(
                    id=book_id,
                    book_title="Visual Alias Test",
                    file_type="pdf",
                    status="processing",
                )
            )
            session.commit()
            with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
                 patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:
                mock_enhanced = MagicMock()
                mock_enhanced.process_pdf.return_value = [page_layout]
                mock_eps.return_value = mock_enhanced
                mock_ocr.return_value = MagicMock()

                result = PDFService().extract_pdf_content("/fake/path.pdf", book_id=book_id, db=session)

            assert len(MARKER_RE.findall(result)) == 2

            images = session.query(BookImage).order_by(BookImage.block_type).all()
            assert [image.block_type for image in images] == ["image", "table"]

            content_blocks = session.query(ContentBlock).order_by(ContentBlock.block_type).all()
            assert len(content_blocks) == 2
            assert {block.block_type for block in content_blocks} == {"image", "table"}
        finally:
            session.close()

    def test_empty_text_block_skipped(self):
        """Empty OCR output from a text block must not add blank lines."""
        blocks = [_text_block(y=0)]
        page_layout = _make_page_layout(blocks)

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:

            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.return_value = ""  # empty OCR
            mock_ocr.return_value = mock_ocr_svc

            svc = PDFService()
            result = svc.extract_pdf_content("/fake/path.pdf")

        assert result.strip() == ""


class TestPDFServiceErrorHandling:
    """Per-block failures are isolated; processing continues."""

    def test_failing_block_does_not_abort_pipeline(self):
        """When one block fails, subsequent blocks are still processed."""
        blocks = [_text_block(y=0), _image_block(y=50), _text_block(y=160)]
        page_layout = _make_page_layout(blocks)

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:

            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            call_count = [0]
            def _ocr_side_effect(img):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise RuntimeError("Simulated OCR failure")
                return "recovered text"

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.side_effect = _ocr_side_effect
            mock_ocr.return_value = mock_ocr_svc

            svc = PDFService()
            result = svc.extract_pdf_content("/fake/path.pdf")

        # The image block marker and the third block's text should still appear
        assert "recovered text" in result, "Later blocks should still produce output"
        assert "$%$%$%" in result, "Image marker should still be present"


class TestPDFServiceImagePersistence:
    """Image blocks are persisted to the DB when book_id + db are supplied."""

    def test_image_saved_to_db_when_credentials_provided(self):
        """save_image must be called once when book_id and db are given."""
        blocks = [_image_block()]
        page_layout = _make_page_layout(blocks)

        mock_db_session = MagicMock()
        book_id = str(uuid.uuid4())

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service"), \
             patch("app.pdf_service.get_image_service") as mock_img_svc_factory:

            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            mock_img_svc = MagicMock()
            mock_img_svc.save_image.return_value = "img_saved001"
            mock_img_svc_factory.return_value = mock_img_svc

            svc = PDFService()
            result = svc.extract_pdf_content("/fake/path.pdf", book_id=book_id, db=mock_db_session)

        mock_img_svc.save_image.assert_called_once()
        call_kwargs = mock_img_svc.save_image.call_args[1]
        assert call_kwargs["book_id"] == book_id
        assert "$%$%$%img_saved001$%$%$%" in result

    def test_image_not_persisted_without_book_id(self):
        """save_image must NOT be called when book_id is absent."""
        blocks = [_image_block()]
        page_layout = _make_page_layout(blocks)

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service"), \
             patch("app.pdf_service.get_image_service") as mock_img_svc_factory:

            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            mock_img_svc = MagicMock()
            mock_img_svc_factory.return_value = mock_img_svc

            svc = PDFService()
            result = svc.extract_pdf_content("/fake/path.pdf")  # no book_id, no db

        mock_img_svc.save_image.assert_not_called()
        # A fallback hash-based marker should still be produced
        assert "$%$%$%" in result

    def test_mixed_visual_blocks_update_summary_and_write_markers(self):
        """Image/table extraction should persist both visual blocks and count markers."""
        blocks = [_text_block(y=0), LayoutBlock(block_type="graphic", bbox=(0, 60, 180, 180)), LayoutBlock(block_type="spreadsheet", bbox=(0, 200, 220, 320))]
        page_layout = _make_page_layout(blocks)
        page_layout.raw_image = _page_image(height=360, width=260)
        page_layout.preprocessed_image = _page_image(height=360, width=260, value=220)
        for block in page_layout.blocks:
            block.image_data = _fake_image()

        mock_db_session = MagicMock()
        book_id = str(uuid.uuid4())

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr, \
             patch("app.pdf_service.get_image_service") as mock_img_svc_factory:
            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.return_value = "正文段落"
            mock_ocr.return_value = mock_ocr_svc

            mock_img_svc = MagicMock()
            mock_img_svc.save_image.side_effect = ["img_visual_1", "img_visual_2"]
            mock_img_svc_factory.return_value = mock_img_svc

            svc = PDFService()
            result = svc.extract_pdf_content("/fake/path.pdf", book_id=book_id, db=mock_db_session)
            summary = svc.get_last_processing_summary()

        assert len(MARKER_RE.findall(result)) >= 2
        assert "$%$%$%img_visual_1$%$%$%" in result
        assert "$%$%$%img_visual_2$%$%$%" in result
        assert mock_img_svc.save_image.call_count == 2
        assert summary["extracted_images"] == 1
        assert summary["extracted_tables"] == 1
        assert summary["markers_written"] == 2


class TestCatalogNormalization:
    """Catalog connector normalization rules."""

    def test_catalog_lines_normalize_to_three_dots(self):
        svc = PDFService()
        raw = "第一章 绪论.......................5\n第二章 原理 —— 12\n第三章 图表目录 ─── 18\n第四章 附录    28\n第五章 单破折号 - 30"
        assert svc.process_catalog_block(raw) == (
            "第一章 绪论...5\n"
            "第二章 原理...12\n"
            "第三章 图表目录...18\n"
            "第四章 附录...28\n"
            "第五章 单破折号...30\n"
        )

    def test_catalog_fallback_preserves_unmatched_line(self):
        svc = PDFService()
        raw = "普通文本没有可靠页码"
        assert svc.process_catalog_block(raw) == "普通文本没有可靠页码\n"


class TestParagraphReconstruction:
    """Paragraph reconstruction removes internal wraps but keeps paragraph breaks."""

    def test_title_block_always_ends_with_newline(self):
        page_layout = _make_page_layout([_title_block(y=0)])
        page_layout.blocks[0].image_data = _fake_image()

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:
            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.return_value = "第一章 总论"
            mock_ocr.return_value = mock_ocr_svc

            result = PDFService().extract_pdf_content("/fake/path.pdf")

        assert result == "第一章 总论\n"

    def test_internal_wraps_are_merged_and_paragraphs_keep_newlines(self):
        page_layout = _make_page_layout([
            LayoutBlock(block_type="text", bbox=(0, 0, 380, 60)),
            LayoutBlock(block_type="text", bbox=(0, 140, 380, 200)),
        ])
        for block in page_layout.blocks:
            block.image_data = _fake_image()

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:
            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.side_effect = [
                "这是第一段第一行\n这是第一段第二行。",
                "这是第二段第一行\n这是第二段第二行。",
            ]
            mock_ocr.return_value = mock_ocr_svc

            result = PDFService().extract_pdf_content("/fake/path.pdf")

        assert result == "这是第一段第一行这是第一段第二行。\n这是第二段第一行这是第二段第二行。"

    def test_terminal_punctuation_inside_block_creates_paragraph_break(self):
        page_layout = _make_page_layout([LayoutBlock(block_type="text", bbox=(0, 0, 380, 120))])
        page_layout.blocks[0].image_data = _fake_image()

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:
            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.return_value = "感受。\n巨大损失。"
            mock_ocr.return_value = mock_ocr_svc

            result = PDFService().extract_pdf_content("/fake/path.pdf")

        assert result == "感受。\n巨大损失。"

    def test_page_end_wrap_does_not_create_false_paragraph_break(self):
        page1 = PageLayout(page_num=0, total_pages=2, blocks=[LayoutBlock(block_type="text", bbox=(0, 330, 380, 390))])
        page1.raw_image = _page_image(height=400)
        page1.preprocessed_image = _page_image(height=400, value=220)
        page1.blocks[0].image_data = _fake_image()

        page2 = PageLayout(page_num=1, total_pages=2, blocks=[LayoutBlock(block_type="text", bbox=(0, 10, 380, 70))])
        page2.raw_image = _page_image(height=400)
        page2.preprocessed_image = _page_image(height=400, value=220)
        page2.blocks[0].image_data = _fake_image()

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:
            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page1, page2]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.side_effect = [
                "这是跨页段落的前半部分",
                "接着说完这一段。",
            ]
            mock_ocr.return_value = mock_ocr_svc

            result = PDFService().extract_pdf_content("/fake/path.pdf")

        assert result == "这是跨页段落的前半部分接着说完这一段。"


class TestCaptionAndNormalizationSafety:
    def test_figure_and_table_captions_kept_atomic(self):
        page_layout = _make_page_layout([
            LayoutBlock(block_type="text", bbox=(0, 0, 380, 80)),
            LayoutBlock(block_type="text", bbox=(0, 90, 380, 160)),
        ])
        for block in page_layout.blocks:
            block.image_data = _fake_image()

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:
            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.side_effect = [
                "图2 富人的现金流",
                "表3 资产负债",
            ]
            mock_ocr.return_value = mock_ocr_svc

            result = PDFService().extract_pdf_content("/fake/path.pdf")

        assert result == "图2 富人的现金流\n表3 资产负债"

    def test_low_gain_normalization_prefers_raw(self):
        svc = PDFService()
        raw = "进行投资"
        normalized = "进行"
        assert svc._select_safe_normalized_text(raw, normalized, "text") == raw

    def test_normalization_threshold_boundary_keeps_normalized(self):
        svc = PDFService()
        raw = "abcdef"
        normalized = "abcde"  # length ratio is 5/6 ~= 0.833 > 0.75 → keep normalized
        assert svc._select_safe_normalized_text(raw, normalized, "text") == normalized


# ---------------------------------------------------------------------------
# HTTP endpoint integration tests (via TestClient)
# ---------------------------------------------------------------------------


class TestPDFUploadEndpointIntegration:
    """Verify the /api/v1/upload → /api/v1/books/{id}/content round-trip."""

    def test_pdf_upload_content_not_single_line(self, client: TestClient):
        """Content returned from /content endpoint must not be a single collapsed line
        when the PDF has multiple text blocks."""
        multi_block_text = "Line 1 text\nLine 2 text\nLine 3 text"

        with patch("app.routers.ocr.get_pdf_service") as mock_pdf_svc_factory:
            mock_svc = MagicMock()
            mock_svc.extract_pdf_content.return_value = multi_block_text
            mock_pdf_svc_factory.return_value = mock_svc

            resp = client.post(
                "/api/v1/upload",
                files=[("file", ("book.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf"))],
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "completed"
        book_id = data["book_id"]

        content_resp = client.get(f"/api/v1/books/{book_id}/content")
        assert content_resp.status_code == 200
        content = content_resp.json()["content"]
        lines = [ln for ln in content.split("\n") if ln.strip()]
        assert len(lines) >= 2, (
            f"Expected multi-line output, got {len(lines)} line(s): {content!r}"
        )

    def test_pdf_upload_content_includes_image_markers(self, client: TestClient):
        """Content returned from /content must preserve $%$%$% markers."""
        txt_with_markers = "Introduction text\n$%$%$%img_abc123$%$%$%\nConclusion text"

        with patch("app.routers.ocr.get_pdf_service") as mock_pdf_svc_factory:
            mock_svc = MagicMock()
            mock_svc.extract_pdf_content.return_value = txt_with_markers
            mock_pdf_svc_factory.return_value = mock_svc

            resp = client.post(
                "/api/v1/upload",
                files=[("file", ("book.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf"))],
            )

        assert resp.status_code == 200
        book_id = resp.json()["book_id"]

        content_resp = client.get(f"/api/v1/books/{book_id}/content")
        assert content_resp.status_code == 200
        content = content_resp.json()["content"]
        assert "$%$%$%img_abc123$%$%$%" in content, (
            f"Image marker not preserved in stored TXT: {content!r}"
        )

    def test_pdf_upload_passes_book_id_and_db_to_extraction(self, client: TestClient):
        """extract_pdf_content must be called with book_id and db kwargs."""
        with patch("app.routers.ocr.get_pdf_service") as mock_pdf_svc_factory:
            mock_svc = MagicMock()
            mock_svc.extract_pdf_content.return_value = "some text"
            mock_pdf_svc_factory.return_value = mock_svc

            resp = client.post(
                "/api/v1/upload",
                files=[("file", ("book.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf"))],
            )

        assert resp.status_code == 200
        call_kwargs = mock_svc.extract_pdf_content.call_args[1]
        assert "book_id" in call_kwargs, "book_id must be passed to extract_pdf_content"
        assert "db" in call_kwargs, "db must be passed to extract_pdf_content"
        assert call_kwargs["book_id"] is not None

    def test_legacy_pdf_upload_endpoint_removed(self, client: TestClient):
        """Legacy /api/v1/pdf/upload must be removed."""
        resp = client.post(
            "/api/v1/pdf/upload",
            files=[("file", ("legacy.pdf", io.BytesIO(b"%PDF-1.4 legacy"), "application/pdf"))],
        )
        assert resp.status_code == 404, resp.text


class TestEnhancedPDFServiceDiagnostics:
    """Layout-engine diagnostics should prove whether PaddleX pipeline ran or fell back."""

    def test_fallback_engine_logs_reason(self, caplog: pytest.LogCaptureFixture):
        svc = EnhancedPDFService()
        svc._layout_engine_initialized = True
        svc._layout_analyzer = None
        svc._set_layout_engine_status("fallback_ocr_only", "paddlex_unavailable: mock import error")

        with caplog.at_level(logging.INFO):
            page_layout = svc.analyze_layout(_page_image(), page_num=0)

        assert page_layout.selected_engine == "fallback_ocr_only"
        assert page_layout.fallback_reason == "paddlex_unavailable: mock import error"
        assert "selected_engine=fallback_ocr_only" in caplog.text
        assert "paddlex_unavailable: mock import error" in caplog.text

    def test_paddlex_pipeline_engine_logs_selection_and_writes_debug_artifact(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        svc = EnhancedPDFService()
        svc._layout_engine_initialized = True
        svc._layout_analyzer = MagicMock(return_value=[
            {"type": "graphic", "bbox": [0, 0, 80, 80], "score": 0.91},
            {"type": "table", "bbox": [90, 10, 180, 120], "score": 0.88},
        ])
        svc._set_layout_engine_status("paddlex_pipeline", pipeline_name="PP-StructureV3", engine_name="PP-DocLayout_plus-L")
        monkeypatch.setattr(settings, "layout_debug_enabled", True)
        monkeypatch.setattr(settings, "layout_debug_dir", tmp_path)

        with caplog.at_level(logging.INFO):
            page_layout = svc.analyze_layout(_page_image(height=200, width=200), page_num=1)

        assert page_layout.selected_engine == "paddlex_pipeline"
        assert [block.block_type for block in page_layout.blocks] == ["image", "table"]
        assert "selected_engine=paddlex_pipeline" in caplog.text
        assert page_layout.diagnostics_path is not None
        artifact_path = Path(page_layout.diagnostics_path)
        assert artifact_path.exists()
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        assert artifact["selected_engine"] == "paddlex_pipeline"
        assert artifact["blocks"][0]["type"] == "image"


# ---------------------------------------------------------------------------
# New tests: PaddleX pipeline engine selection
# ---------------------------------------------------------------------------


class TestPaddleXPipelineEngineSelection:
    """PaddleX pipeline must be selected as the primary engine."""

    def test_paddlex_selected_when_import_succeeds(
        self, caplog: pytest.LogCaptureFixture
    ):
        """When paddlex is importable, engine status must be paddlex_pipeline."""
        import sys

        mock_pipeline = MagicMock()
        mock_pipeline.predict.return_value = iter([])  # no detections

        mock_paddlex = MagicMock()
        mock_paddlex.__version__ = "3.0.0"
        mock_paddlex.create_pipeline.return_value = mock_pipeline

        svc = EnhancedPDFService()

        with patch.dict(sys.modules, {"paddlex": mock_paddlex}):
            with caplog.at_level(logging.INFO):
                analyzer = svc._get_layout_analyzer()

        assert analyzer is not None, "Analyzer must not be None when PaddleX is available"
        status = svc._get_layout_engine_status()
        assert status["selected_engine"] == "paddlex_pipeline"
        assert status["pipeline_name"] == "PP-StructureV3"
        assert status["engine_name"] == "PP-DocLayout_plus-L"
        assert "selected_engine=paddlex_pipeline" in caplog.text
        mock_paddlex.create_pipeline.assert_called_once_with(
            pipeline="PP-StructureV3",
            layout_detection_model_name="PP-DocLayout_plus-L",
        )

    def test_paddlex_failure_surfaces_error_and_warning(
        self, caplog: pytest.LogCaptureFixture
    ):
        """When paddlex import fails, an ERROR and DEGRADED MODE WARNING must be logged."""
        import sys

        svc = EnhancedPDFService()

        with patch.dict(sys.modules, {"paddlex": None}):
            with caplog.at_level(logging.WARNING):
                analyzer = svc._get_layout_analyzer()

        assert analyzer is None
        status = svc._get_layout_engine_status()
        assert status["selected_engine"] == "fallback_ocr_only"
        assert "paddlex" in (status["reason"] or "").lower()

        # Both ERROR and DEGRADED MODE warning must appear in logs
        log_text = caplog.text
        assert "DEGRADED MODE" in log_text, "Degraded-mode warning must be surfaced to caller"

    def test_paddlex_init_error_surfaces_loudly(
        self, caplog: pytest.LogCaptureFixture
    ):
        """When create_pipeline raises, error must be logged and fallback activated."""
        import sys

        mock_paddlex = MagicMock()
        mock_paddlex.__version__ = "3.0.0"
        mock_paddlex.create_pipeline.side_effect = RuntimeError("model not found")

        svc = EnhancedPDFService()

        with patch.dict(sys.modules, {"paddlex": mock_paddlex}):
            with caplog.at_level(logging.WARNING):
                analyzer = svc._get_layout_analyzer()

        assert analyzer is None
        status = svc._get_layout_engine_status()
        assert status["selected_engine"] == "fallback_ocr_only"
        log_text = caplog.text
        assert "DEGRADED MODE" in log_text


# ---------------------------------------------------------------------------
# New tests: PaddleX predict fallback strategies
# ---------------------------------------------------------------------------


class TestPaddleXPredictFallbackStrategies:
    def test_predict_stops_after_first_non_empty_attempt(
        self, caplog: pytest.LogCaptureFixture
    ):
        class Pipeline:
            def __init__(self):
                self.calls = []

            def predict(self, payload):
                self.calls.append(payload)
                if isinstance(payload, list):
                    return iter([{
                        "boxes": [{"label": "text", "score": 0.9, "coordinate": [1, 2, 3, 4]}]
                    }])
                return iter([])

        pipeline = Pipeline()
        analyzer = _make_paddlex_layout_analyzer(pipeline)

        with caplog.at_level(logging.INFO):
            blocks = analyzer(_page_image())

        assert len(blocks) == 1
        assert len(pipeline.calls) == 1
        assert "attempt=list_img" in caplog.text
        assert "raw_results=1" in caplog.text
        assert "attempt=ndarray_img" not in caplog.text

    def test_predict_falls_back_to_tmp_path_and_cleans_file(
        self, caplog: pytest.LogCaptureFixture
    ):
        class Pipeline:
            def __init__(self):
                self.calls = []
                self.tmp_path: str | None = None

            def predict(self, payload):
                self.calls.append(payload)
                if isinstance(payload, list):
                    return iter([])
                if isinstance(payload, np.ndarray):
                    return iter([])
                if isinstance(payload, dict):
                    return iter([])
                if isinstance(payload, str):
                    self.tmp_path = payload
                    assert Path(payload).exists()
                    return iter([{
                        "boxes": [{"label": "text", "score": 0.8, "coordinate": [0, 0, 10, 10]}]
                    }])
                return iter([])

        pipeline = Pipeline()
        analyzer = _make_paddlex_layout_analyzer(pipeline)

        with caplog.at_level(logging.INFO):
            blocks = analyzer(_page_image())

        assert len(blocks) == 1
        assert len(pipeline.calls) == 4
        assert pipeline.tmp_path is not None
        assert not Path(pipeline.tmp_path).exists()
        assert "attempt=tmp_path" in caplog.text
        assert "raw_results=1" in caplog.text

    def test_parse_boxes_from_nested_res_layout_result(self):
        class Pipeline:
            def predict(self, payload):
                if isinstance(payload, list):
                    return iter([{
                        "res": {
                            "layout_result": [
                                {"class_name": "title", "score": 0.77, "bbox": [10, 20, 40, 80]}
                            ]
                        }
                    }])
                return iter([])

        analyzer = _make_paddlex_layout_analyzer(Pipeline())
        blocks = analyzer(_page_image())
        assert len(blocks) == 1
        assert blocks[0]["type"] == "title"
        assert blocks[0]["bbox"] == [10.0, 20.0, 40.0, 80.0]
        assert blocks[0]["score"] == pytest.approx(0.77)

    def test_parse_object_det_boxes_with_polygon_points(self):
        class Box:
            def __init__(self):
                self.category = "table"
                self.score = 0.5
                self.points = [[50, 80], [10, 20], [10, 80], [50, 20]]

        class Result:
            def __init__(self):
                self.det_boxes = [Box()]

        class Pipeline:
            def predict(self, payload):
                if isinstance(payload, list):
                    return iter([Result()])
                return iter([])

        analyzer = _make_paddlex_layout_analyzer(Pipeline())
        blocks = analyzer(_page_image())
        assert len(blocks) == 1
        assert blocks[0]["type"] == "table"
        assert blocks[0]["bbox"] == [10.0, 20.0, 50.0, 80.0]
        assert blocks[0]["score"] == pytest.approx(0.5)

    def test_logs_diagnostics_when_raw_results_non_empty_but_no_blocks(
        self, caplog: pytest.LogCaptureFixture
    ):
        class Pipeline:
            def predict(self, payload):
                if isinstance(payload, list):
                    return iter([{"foo": "bar", "res": {"abc": [1]}}])
                return iter([])

        analyzer = _make_paddlex_layout_analyzer(Pipeline())
        with caplog.at_level(logging.WARNING):
            blocks = analyzer(_page_image())
        assert blocks == []
        assert "PaddleX parsing produced zero blocks" in caplog.text
        assert "diagnostics=" in caplog.text


# ---------------------------------------------------------------------------
# New tests: canonical label normalization
# ---------------------------------------------------------------------------


class TestLabelNormalization:
    """Raw PaddleX labels must be normalised to the five canonical types."""

    def _svc(self) -> "EnhancedPDFService":
        from app.enhanced_pdf_service import EnhancedPDFService as EPS
        return EPS()

    @pytest.mark.parametrize("raw,expected", [
        # title aliases
        ("title", "title"),
        ("heading", "title"),
        ("headline", "title"),
        ("section_title", "title"),
        # toc aliases
        ("toc", "toc"),
        ("catalog", "toc"),
        ("contents", "toc"),
        ("table_of_contents", "toc"),
        ("directory", "toc"),
        # text aliases
        ("text", "text"),
        ("paragraph", "text"),
        ("body", "text"),
        # image aliases
        ("image", "image"),
        ("figure", "image"),
        ("graphic", "image"),
        ("diagram", "image"),
        ("chart", "image"),
        # table aliases
        ("table", "table"),
        ("tabular", "table"),
        ("grid", "table"),
    ])
    def test_enhanced_label_normalization(self, raw: str, expected: str):
        svc = self._svc()
        assert svc._normalize_block_type(raw) == expected, (
            f"Raw label {raw!r} should map to {expected!r}"
        )

    @pytest.mark.parametrize("raw,expected", [
        ("title", "title"),
        ("heading", "title"),
        ("toc", "toc"),
        ("catalog", "toc"),
        ("contents", "toc"),
        ("table_of_contents", "toc"),
        ("text", "text"),
        ("paragraph", "text"),
        ("graphic", "image"),
        ("figure", "image"),
        ("image", "image"),
        ("table", "table"),
        ("tabular", "table"),
    ])
    def test_pdf_service_label_normalization(self, raw: str, expected: str):
        from app.pdf_service import PDFService
        svc = PDFService()
        assert svc._normalize_block_type(raw) == expected, (
            f"PDFService raw label {raw!r} should map to {expected!r}"
        )


# ---------------------------------------------------------------------------
# New tests: TOC / catalog normalization (canonical type is now "toc")
# ---------------------------------------------------------------------------


class TestTOCNormalization:
    """TOC connector normalization and toc block type recognition."""

    def test_toc_lines_normalize_to_three_dots(self):
        svc = PDFService()
        raw = (
            "第一章 绪论.......................5\n"
            "第二章 原理 —— 12\n"
            "第三章 图表目录 ─── 18\n"
            "第四章 附录    28\n"
            "第五章 单破折号 - 30"
        )
        assert svc.process_catalog_block(raw) == (
            "第一章 绪论...5\n"
            "第二章 原理...12\n"
            "第三章 图表目录...18\n"
            "第四章 附录...28\n"
            "第五章 单破折号...30\n"
        )

    def test_toc_fallback_preserves_unmatched_line(self):
        svc = PDFService()
        raw = "普通文本没有可靠页码"
        assert svc.process_catalog_block(raw) == "普通文本没有可靠页码\n"

    def test_toc_block_type_routes_to_toc_processing(self):
        """A block with block_type='toc' must be processed via process_catalog_block."""
        toc_block = LayoutBlock(block_type="toc", bbox=(0, 0, 400, 100))
        toc_block.image_data = _fake_image()
        page_layout = _make_page_layout([toc_block])

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:

            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.return_value = "第一章 引言.........1"
            mock_ocr.return_value = mock_ocr_svc

            result = PDFService().extract_pdf_content("/fake/path.pdf")

        assert "第一章 引言...1" in result, f"TOC entry not normalised: {result!r}"

    def test_catalog_alias_also_routes_to_toc(self):
        """Block type 'catalog' (legacy alias) must normalise to 'toc' and be processed."""
        catalog_block = LayoutBlock(block_type="catalog", bbox=(0, 0, 400, 100))
        catalog_block.image_data = _fake_image()
        page_layout = _make_page_layout([catalog_block])

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:

            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.return_value = "第二章 方法论.........8"
            mock_ocr.return_value = mock_ocr_svc

            result = PDFService().extract_pdf_content("/fake/path.pdf")

        assert "第二章 方法论...8" in result, f"Legacy 'catalog' block not normalised: {result!r}"

    def test_toc_block_helper_properties(self):
        """_toc_block() helper creates a LayoutBlock with block_type='toc'."""
        block = _toc_block(y=10)
        assert block.block_type == "toc"
        assert block.bbox == (0, 10, 400, 90)
        assert block.image_data is not None

    def test_toc_block_helper_used_in_pipeline(self):
        """_toc_block() helper integrates correctly with the extraction pipeline."""
        page_layout = _make_page_layout([_toc_block(y=0)])

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:

            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.return_value = "第三章 结论...15"
            mock_ocr.return_value = mock_ocr_svc

            result = PDFService().extract_pdf_content("/fake/path.pdf")

        # Already-normalised TOC entry passes through process_catalog_block unchanged
        assert "第三章 结论...15" in result
        # toc block type always ends with \n (hard rule)
        assert result.endswith("\n")

    def test_toc_titles_noise_and_parenthesized_pages(self):
        svc = PDFService()
        raw = (
            "目录\n"
            "仓码行\n"
            "前言\n"
            "成长之路 (3)\n"
            "科究图利\n"
            "理念篇.....(4)\n"
        )
        assert svc.process_catalog_block(raw) == (
            "目录\n"
            "前言\n"
            "成长之路...(3)\n"
            "理念篇...(4)\n"
        )


# ---------------------------------------------------------------------------
# New tests: per-page diagnostics include all five canonical type counts
# ---------------------------------------------------------------------------


class TestPerPageDiagnosticsFiveTypes:
    """block_type_counts must always contain all five canonical types (with zeros)."""

    def test_fallback_page_has_all_five_types_with_zeros(self):
        svc = EnhancedPDFService()
        svc._layout_engine_initialized = True
        svc._layout_analyzer = None
        svc._set_layout_engine_status("fallback_ocr_only", "paddlex_unavailable: test")

        page_layout = svc.analyze_layout(_page_image(), page_num=0)

        for canonical_type in ("title", "toc", "text", "image", "table"):
            assert canonical_type in page_layout.block_type_counts, (
                f"canonical type {canonical_type!r} missing from block_type_counts"
            )
        assert page_layout.block_type_counts["text"] == 1
        assert page_layout.block_type_counts["image"] == 0
        assert page_layout.block_type_counts["table"] == 0
        assert page_layout.block_type_counts["title"] == 0
        assert page_layout.block_type_counts["toc"] == 0

    def test_active_engine_page_has_all_five_types(self):
        svc = EnhancedPDFService()
        svc._layout_engine_initialized = True
        svc._layout_analyzer = MagicMock(return_value=[
            {"type": "title", "bbox": [0, 0, 400, 40], "score": 0.95},
            {"type": "text", "bbox": [0, 50, 400, 120], "score": 0.90},
            {"type": "image", "bbox": [0, 130, 200, 250], "score": 0.88},
        ])
        svc._set_layout_engine_status("paddlex_pipeline", pipeline_name="PP-StructureV3", engine_name="PP-DocLayout_plus-L")

        page_layout = svc.analyze_layout(_page_image(height=300, width=400), page_num=0)

        for canonical_type in ("title", "toc", "text", "image", "table"):
            assert canonical_type in page_layout.block_type_counts, (
                f"canonical type {canonical_type!r} missing from block_type_counts"
            )
        assert page_layout.block_type_counts["title"] == 1
        assert page_layout.block_type_counts["text"] == 1
        assert page_layout.block_type_counts["image"] == 1
        assert page_layout.block_type_counts["toc"] == 0
        assert page_layout.block_type_counts["table"] == 0

    def test_diagnostics_log_contains_all_five_type_counts(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Log output must include canonical title/toc/text/image/table counts."""
        svc = EnhancedPDFService()
        svc._layout_engine_initialized = True
        svc._layout_analyzer = MagicMock(return_value=[
            {"type": "toc", "bbox": [0, 0, 400, 80], "score": 0.92},
            {"type": "table", "bbox": [0, 90, 400, 200], "score": 0.87},
        ])
        svc._set_layout_engine_status("paddlex_pipeline", pipeline_name="PP-StructureV3", engine_name="PP-DocLayout_plus-L")

        with caplog.at_level(logging.INFO):
            svc.analyze_layout(_page_image(height=250, width=400), page_num=2)

        log_text = caplog.text
        # The log line must mention all five canonical labels explicitly
        assert "title=" in log_text
        assert "toc=" in log_text
        assert "text=" in log_text
        assert "image=" in log_text
        assert "table=" in log_text


class TestOCRServiceExtractTextFromImage:
    """extract_text_from_image accepts numpy arrays and returns text."""

    def test_returns_string_on_engine_success(self):
        """When the engine returns recognised text it must be joined and returned."""
        from app.ocr_service import OCRService

        svc = OCRService()
        fake_engine = MagicMock()
        fake_engine.ocr.return_value = [{"rec_texts": ["Hello", "World"]}]
        svc._ocr_engine = fake_engine

        result = svc.extract_text_from_image(np.ones((100, 100, 3), dtype=np.uint8))
        assert result == "Hello\nWorld"

    def test_returns_empty_string_on_engine_failure(self):
        """A crashing engine must return empty string, not raise."""
        from app.ocr_service import OCRService

        svc = OCRService()
        fake_engine = MagicMock()
        fake_engine.ocr.side_effect = RuntimeError("engine crash")
        svc._ocr_engine = fake_engine

        result = svc.extract_text_from_image(np.ones((100, 100, 3), dtype=np.uint8))
        assert result == ""

    def test_grayscale_input_accepted(self):
        """Grayscale (2-D) images must be accepted without error."""
        from app.ocr_service import OCRService

        svc = OCRService()
        fake_engine = MagicMock()
        fake_engine.ocr.return_value = [{"rec_texts": ["Text"]}]
        svc._ocr_engine = fake_engine

        result = svc.extract_text_from_image(np.ones((100, 100), dtype=np.uint8))
        assert result == "Text"

    def test_legacy_format_supported(self):
        """Legacy PaddleOCR list-of-list output format is handled."""
        from app.ocr_service import OCRService

        svc = OCRService()
        fake_engine = MagicMock()
        # Real legacy format: ocr_result = [ list_of_lines ]
        # where each line is [box, (text, confidence)]
        fake_engine.ocr.return_value = [
            [  # list of lines for this image
                [  # single line: [box, (text, conf)]
                    [[0, 0], [100, 0], [100, 20], [0, 20]],  # bounding box
                    ("Legacy text", 0.95),                    # recognition result
                ]
            ]
        ]
        svc._ocr_engine = fake_engine

        result = svc.extract_text_from_image(np.ones((100, 100, 3), dtype=np.uint8))
        assert result == "Legacy text"


# ---------------------------------------------------------------------------
# New tests: _ensure_bgr_uint8 channel normalisation helper
# ---------------------------------------------------------------------------


class TestEnsureBgrUint8:
    """_ensure_bgr_uint8 converts any supported shape/dtype to 3-channel uint8 BGR."""

    def _fn(self):
        from app.enhanced_pdf_service import _ensure_bgr_uint8
        return _ensure_bgr_uint8

    def test_passthrough_bgr_uint8(self):
        """A (H, W, 3) uint8 array is returned unchanged (no copy needed)."""
        fn = self._fn()
        img = np.ones((100, 80, 3), dtype=np.uint8) * 128
        result = fn(img)
        assert result.shape == (100, 80, 3)
        assert result.dtype == np.uint8

    def test_grayscale_2d_to_bgr(self):
        """A (H, W) grayscale array must be expanded to (H, W, 3)."""
        fn = self._fn()
        img = np.ones((60, 40), dtype=np.uint8) * 200
        result = fn(img)
        assert result.shape == (60, 40, 3)
        assert result.dtype == np.uint8

    def test_single_channel_3d_to_bgr(self):
        """A (H, W, 1) single-channel array must be expanded to (H, W, 3)."""
        fn = self._fn()
        img = np.ones((60, 40, 1), dtype=np.uint8) * 100
        result = fn(img)
        assert result.shape == (60, 40, 3)
        assert result.dtype == np.uint8

    def test_bgra_to_bgr(self):
        """A (H, W, 4) BGRA array must have the alpha channel dropped."""
        fn = self._fn()
        img = np.ones((50, 50, 4), dtype=np.uint8) * 150
        result = fn(img)
        assert result.shape == (50, 50, 3)
        assert result.dtype == np.uint8

    def test_float_dtype_cast_to_uint8(self):
        """Float32 images (values 0–255) must be clipped and cast to uint8."""
        fn = self._fn()
        img = np.ones((30, 30, 3), dtype=np.float32) * 180.5
        result = fn(img)
        assert result.dtype == np.uint8
        assert result.shape == (30, 30, 3)

    def test_float_out_of_range_clipped(self):
        """Values outside [0, 255] in float images are clipped before casting."""
        fn = self._fn()
        img = np.array([[[300.0, -10.0, 128.0]]], dtype=np.float32)
        result = fn(img)
        assert result[0, 0, 0] == 255  # 300 clipped to 255
        assert result[0, 0, 1] == 0    # -10 clipped to 0
        assert result[0, 0, 2] == 128


# ---------------------------------------------------------------------------
# New tests: cover page handling
# ---------------------------------------------------------------------------


class TestCoverPageHandling:
    """When cover_page_as_image=True, page 0 is stored as image; OCR is skipped."""

    def _run_cover_page(self, monkeypatch, blocks, page_num=0):
        """Run extraction with cover_page_as_image enabled."""
        from app.config import settings

        page_layout = _make_page_layout(blocks, page_num=page_num)
        # Use a realistically-sized page image so the cover can be saved
        page_img = _page_image(height=400, width=300)
        page_layout.raw_image = page_img
        page_layout.preprocessed_image = page_img

        monkeypatch.setattr(settings, "cover_page_as_image", True)

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:

            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.return_value = "text that should be skipped"
            mock_ocr.return_value = mock_ocr_svc

            svc = PDFService()
            result = svc.extract_pdf_content("/fake/path.pdf")

        return result, mock_ocr_svc

    def test_cover_page_produces_image_marker(self, monkeypatch):
        """When cover handling is on, page 0 must produce an image marker."""
        blocks = [_text_block(y=0), _text_block(y=50)]
        result, _ = self._run_cover_page(monkeypatch, blocks)
        assert "$%$%$%" in result, "Cover page must produce an image marker"
        assert MARKER_RE.search(result) is not None

    def test_cover_page_skips_ocr(self, monkeypatch):
        """OCR must NOT be called for a cover page."""
        blocks = [_text_block(y=0), _image_block(y=60)]
        _, mock_ocr_svc = self._run_cover_page(monkeypatch, blocks)
        mock_ocr_svc.extract_text_from_image.assert_not_called()

    def test_cover_page_text_not_in_output(self, monkeypatch):
        """Text that would normally come from text blocks must not appear for cover."""
        blocks = [_text_block(y=0)]
        result, _ = self._run_cover_page(monkeypatch, blocks)
        assert "text that should be skipped" not in result

    def test_non_cover_page_still_extracts_text(self, monkeypatch):
        """Pages with index > 0 must still extract OCR text even when cover mode is on."""
        from app.config import settings

        monkeypatch.setattr(settings, "cover_page_as_image", True)

        page0 = _make_page_layout([_image_block()], page_num=0)
        page0.raw_image = _page_image(height=400, width=300)
        page0.preprocessed_image = page0.raw_image

        page1 = _make_page_layout([_text_block(y=0)], page_num=1)
        page1.raw_image = _page_image(height=400, width=300)
        page1.preprocessed_image = page1.raw_image

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:

            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page0, page1]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.return_value = "body text"
            mock_ocr.return_value = mock_ocr_svc

            result = PDFService().extract_pdf_content("/fake/path.pdf")

        assert "body text" in result, "Body text from page 1 must appear in output"

    def test_cover_page_disabled_by_default(self, monkeypatch):
        """With default settings (cover_page_as_image=False) page 0 is NOT skipped."""
        from app.config import settings

        monkeypatch.setattr(settings, "cover_page_as_image", False)
        blocks = [_text_block(y=0)]
        page_layout = _make_page_layout(blocks, page_num=0)

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:

            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page_layout]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.return_value = "normal text"
            mock_ocr.return_value = mock_ocr_svc

            result = PDFService().extract_pdf_content("/fake/path.pdf")

        assert "normal text" in result


# ---------------------------------------------------------------------------
# New tests: header/footer filtering
# ---------------------------------------------------------------------------


class TestHeaderFooterFiltering:
    """Header/footer filtering is page-level and requires repeated text evidence."""

    def _make_full_page_layout(self, blocks, height=1000, width=800, page_num=0):
        """Build a PageLayout with a realistically-sized page image."""
        pl = PageLayout(page_num=page_num, total_pages=1, blocks=blocks)
        img = np.ones((height, width, 3), dtype=np.uint8) * 200
        pl.raw_image = img
        pl.preprocessed_image = img
        return pl

    def _run_extraction_with_hf(self, page_layouts, monkeypatch, header_ratio=0.08, footer_ratio=0.08):
        from app.config import settings

        monkeypatch.setattr(settings, "header_ratio", header_ratio)
        monkeypatch.setattr(settings, "footer_ratio", footer_ratio)

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:

            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = page_layouts
            mock_eps.return_value = mock_enhanced

            call_log = []
            def _side_effect(img):
                call_log.append(img)
                return f"text_{len(call_log)}"

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.side_effect = _side_effect
            mock_ocr.return_value = mock_ocr_svc

            svc = PDFService()
            result = svc.extract_pdf_content("/fake/path.pdf")

        return result, call_log

    def test_repeated_header_block_filtered(self, monkeypatch):
        """Top-band repeated text across pages should be filtered safely."""
        page_height = 1000
        page1 = self._make_full_page_layout(
            [LayoutBlock(block_type="text", bbox=(0, 10, 800, 70)), LayoutBlock(block_type="text", bbox=(0, 200, 800, 350))],
            height=page_height,
            page_num=0,
        )
        page2 = self._make_full_page_layout(
            [LayoutBlock(block_type="text", bbox=(0, 10, 800, 70)), LayoutBlock(block_type="text", bbox=(0, 250, 800, 420))],
            height=page_height,
            page_num=1,
        )
        for page in (page1, page2):
            for block in page.blocks:
                block.image_data = _fake_image()

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:
            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page1, page2]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.side_effect = ["重复页眉", "正文段落一", "重复页眉", "正文段落二"]
            mock_ocr.return_value = mock_ocr_svc

            result = PDFService().extract_pdf_content("/fake/path.pdf")

        assert "重复页眉" not in result
        assert "正文段落一" in result
        assert "正文段落二" in result

    def test_single_page_top_block_not_filtered_without_repetition(self, monkeypatch):
        """Position-only top text should not be dropped when it is not repeated."""
        page_height = 1000
        top_block = LayoutBlock(block_type="text", bbox=(0, 10, 800, 70))
        top_block.image_data = _fake_image()
        body_block = LayoutBlock(block_type="text", bbox=(0, 300, 800, 500))
        body_block.image_data = _fake_image()

        pl = self._make_full_page_layout([top_block, body_block], height=page_height)
        result, call_log = self._run_extraction_with_hf([pl], monkeypatch)

        assert len(call_log) == 2
        assert "text_1" in result and "text_2" in result

    def test_body_block_not_filtered(self, monkeypatch):
        """Text block in the middle of the page must NOT be filtered."""
        page_height = 1000
        body_block = LayoutBlock(block_type="text", bbox=(0, 400, 800, 600))
        body_block.image_data = _fake_image()

        pl = self._make_full_page_layout([body_block], height=page_height)

        result, call_log = self._run_extraction_with_hf([pl], monkeypatch)

        assert len(call_log) == 1, "Body block must not be filtered"
        assert "text_1" in result

    def test_visual_blocks_not_filtered(self, monkeypatch):
        """Image/table blocks inside header/footer bands must NOT be filtered."""
        page_height = 1000
        # Image block placed in the header band
        image_in_header = LayoutBlock(block_type="image", bbox=(0, 5, 800, 70))
        image_in_header.image_data = _fake_image()

        pl = self._make_full_page_layout([image_in_header], height=page_height)

        result, call_log = self._run_extraction_with_hf([pl], monkeypatch)

        # Image block is never OCR'd but should produce a marker
        assert "$%$%$%" in result, "Image block must produce a marker even in header band"
        assert len(call_log) == 0, "No OCR call for an image block"

    def test_title_followed_by_first_line_is_preserved(self, monkeypatch):
        """Text after a top title should not be mistaken for header noise."""
        page_height = 1000
        title_in_header = LayoutBlock(block_type="title", bbox=(0, 5, 800, 60))
        title_in_header.image_data = _fake_image()
        body_block = LayoutBlock(block_type="text", bbox=(0, 65, 800, 150))
        body_block.image_data = _fake_image()

        pl = self._make_full_page_layout([title_in_header, body_block], height=page_height)

        result, call_log = self._run_extraction_with_hf([pl], monkeypatch)

        assert len(call_log) == 2
        assert "text_1" in result and "text_2" in result

    def test_configurable_ratios(self, monkeypatch):
        """Wider header/footer ratios remove more blocks."""
        page_height = 1000
        # y=150 is in 15% header band but not 8% header band
        near_top_block = LayoutBlock(block_type="text", bbox=(0, 100, 800, 150))
        near_top_block.image_data = _fake_image()
        body_block = LayoutBlock(block_type="text", bbox=(0, 500, 800, 700))
        body_block.image_data = _fake_image()

        pl = self._make_full_page_layout([near_top_block, body_block], height=page_height)

        # With 8% ratio: header threshold = 80px. Block y2=150 > 80 → NOT filtered.
        result_8pct, calls_8pct = self._run_extraction_with_hf(
            [pl], monkeypatch, header_ratio=0.08, footer_ratio=0.08
        )
        assert len(calls_8pct) == 2, "With 8% ratio, near-top block should pass"
        assert "text_1" in result_8pct and "text_2" in result_8pct

        # Re-create the page layout for the second run (mock state resets)
        pl2 = self._make_full_page_layout([near_top_block, body_block], height=page_height)

        result_20pct, calls_20pct = self._run_extraction_with_hf(
            [pl2], monkeypatch, header_ratio=0.20, footer_ratio=0.08
        )
        assert len(calls_20pct) == 2, "Ratio widening alone should not remove non-repeated content"
        assert "text_1" in result_20pct and "text_2" in result_20pct

    def test_repeated_middle_zone_text_is_not_filtered(self, monkeypatch):
        """Repeated body-band text should be protected from header/footer filtering."""
        page1 = self._make_full_page_layout(
            [LayoutBlock(block_type="text", bbox=(0, 300, 800, 380))],
            height=1000,
            page_num=0,
        )
        page2 = self._make_full_page_layout(
            [LayoutBlock(block_type="text", bbox=(0, 320, 800, 400))],
            height=1000,
            page_num=1,
        )
        for page in (page1, page2):
            for block in page.blocks:
                block.image_data = _fake_image()

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:
            mock_enhanced = MagicMock()
            mock_enhanced.process_pdf.return_value = [page1, page2]
            mock_eps.return_value = mock_enhanced

            mock_ocr_svc = MagicMock()
            mock_ocr_svc.extract_text_from_image.side_effect = ["重复正文", "重复正文"]
            mock_ocr.return_value = mock_ocr_svc

            result = PDFService().extract_pdf_content("/fake/path.pdf")

        assert result.count("重复正文") == 2


# ---------------------------------------------------------------------------
# Patch regression tests (must-fix issues)
# ---------------------------------------------------------------------------


def _full_page_layout(blocks, height=1000, width=800, page_num=0):
    """Convenience: PageLayout with a realistically-sized raw image."""
    pl = PageLayout(page_num=page_num, total_pages=1, blocks=blocks)
    img = np.ones((height, width, 3), dtype=np.uint8) * 200
    pl.raw_image = img
    pl.preprocessed_image = img
    return pl


class TestPageLevelFilteringSafety:
    """A. Page-level coordinate semantics must be enforced end-to-end."""

    def _run(self, page_layouts, monkeypatch, ocr_texts, header_ratio=0.08, footer_ratio=0.08):
        from app.config import settings
        monkeypatch.setattr(settings, "header_ratio", header_ratio)
        monkeypatch.setattr(settings, "footer_ratio", footer_ratio)

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:
            mock_eps.return_value.process_pdf.return_value = page_layouts
            mock_ocr.return_value.extract_text_from_image.side_effect = list(ocr_texts)
            return PDFService().extract_pdf_content("/fake/path.pdf")

    def test_first_body_line_after_title_preserved_exact_boundary(self, monkeypatch):
        """A body line whose top y equals the title bottom must be retained.

        Before fix: the strict `>` comparison dropped lines starting exactly at
        title_bottom.  After fix: `>=` protects them.
        """
        page_height = 1000
        # Title occupies y=5..60 → title_bottom = 60
        title = LayoutBlock(block_type="title", bbox=(0, 5, 800, 60))
        title.image_data = _fake_image()
        # First body line starts exactly at y=60 (title_bottom), ends at y=78 (in header band)
        first_body = LayoutBlock(block_type="text", bbox=(0, 60, 800, 78))
        first_body.image_data = _fake_image()

        pl = _full_page_layout([title, first_body], height=page_height)
        result = self._run([pl], monkeypatch, ["前言", "第一段正文行"])

        assert "第一段正文行" in result, (
            "First body line starting at title_bottom must not be dropped by header filter"
        )

    def test_first_body_line_after_preface_title_preserved(self, monkeypatch):
        """Body text after a chapter title (e.g., '前言') must appear in output.

        Before fix: '前言' alone triggered page_toc_mode, causing subsequent body
        text to be processed as TOC entries (and potentially stripped as noise).
        After fix: a single title-like word without a page number must NOT trigger
        page_toc_mode.
        """
        page_height = 1000
        title = LayoutBlock(block_type="title", bbox=(0, 10, 800, 60))
        title.image_data = _fake_image()
        body = LayoutBlock(block_type="text", bbox=(0, 80, 800, 200))
        body.image_data = _fake_image()

        pl = _full_page_layout([title, body], height=page_height)
        result = self._run([pl], monkeypatch, ["前言", "本书主要讲述如何通过投资实现财务自由。"])

        assert "本书主要讲述如何通过投资实现财务自由。" in result, (
            "Body text after '前言' title must not be lost when title triggers no TOC mode"
        )

    def test_body_text_after_preface_not_classified_as_toc(self, monkeypatch):
        """Blocks following a lone '前言' title must remain 'text', not 'toc'."""
        svc = PDFService()
        # Single-line "前言" without a page number should NOT look like a catalog block
        assert not svc._looks_like_catalog_block("前言", "text"), (
            "'前言' alone (no page number) must not be classified as a catalog block"
        )
        assert not svc._looks_like_catalog_block("序言", "text"), (
            "'序言' alone must not be classified as a catalog block"
        )
        assert not svc._looks_like_catalog_block("第一章", "text"), (
            "'第一章' alone must not be classified as a catalog block"
        )
        assert not svc._looks_like_catalog_block("理念篇", "text"), (
            "'理念篇' alone must not be classified as a catalog block"
        )

    def test_no_block_level_coordinate_trimming(self, monkeypatch):
        """Blocks with y coordinates near the top of a LARGE page must not be
        filtered when page_height is correct and no repetition exists."""
        page_height = 2000  # unusually tall page
        # Block near the very top (y=5..50) — within 8% header band of 2000px = 160px
        top_block = LayoutBlock(block_type="text", bbox=(0, 5, 800, 50))
        top_block.image_data = _fake_image()
        body_block = LayoutBlock(block_type="text", bbox=(0, 400, 800, 600))
        body_block.image_data = _fake_image()

        pl = _full_page_layout([top_block, body_block], height=page_height)
        result = self._run([pl], monkeypatch, ["正文顶部行", "正文中部行"])

        # Both blocks appear only once (no repetition) so neither should be filtered
        assert "正文顶部行" in result
        assert "正文中部行" in result


class TestTOCReconstructionRobust:
    """B. TOC page reconstruction — headings, leaders and page numbers preserved."""

    def test_toc_heading_目录_triggers_toc_mode(self):
        """'目录' alone on a single-line block must still trigger TOC mode."""
        svc = PDFService()
        assert svc._looks_like_catalog_block("目录", "text"), (
            "'目录' heading must be classified as a catalog block"
        )

    def test_toc_entry_with_page_number_triggers_toc_mode(self):
        """A single-line TOC entry that has a page number must be recognised."""
        svc = PDFService()
        assert svc._looks_like_catalog_block("成长之路 (3)", "text")
        assert svc._looks_like_catalog_block("理念篇.....(4)", "text")
        assert svc._looks_like_catalog_block("第一章 引言.........1", "text")

    def test_toc_block_type_always_detected(self):
        """An explicit 'toc' block type always counts as catalog regardless of content."""
        svc = PDFService()
        assert svc._looks_like_catalog_block("任意文本", "toc")

    def test_toc_entries_without_page_numbers_preserved_in_multiline_block(self):
        """In a multi-line TOC block, heading-only entries like '前言' are kept."""
        svc = PDFService()
        raw = "目录\n前言\n成长之路 (3)\n理念篇.....(4)\n"
        out = svc.process_catalog_block(raw)
        assert "目录" in out
        assert "前言" in out
        assert "成长之路...(3)" in out
        assert "理念篇...(4)" in out

    def test_toc_entries_each_on_own_line(self, monkeypatch):
        """When TOC entries are individual blocks each must appear on its own line."""
        from app.config import settings
        monkeypatch.setattr(settings, "header_ratio", 0.08)
        monkeypatch.setattr(settings, "footer_ratio", 0.08)

        page_height = 1000
        # Simulate a TOC page where each entry is a separate text block
        # The first block is the "目录" heading → triggers toc mode
        # Subsequent blocks are individual entries
        blocks = []
        ocr_texts = []
        entries = [
            ("目录", 0),
            ("前言", 80),
            ("成长之路 (3)", 150),
            ("理念篇.....(4)", 220),
        ]
        for text_val, y in entries:
            b = LayoutBlock(block_type="text", bbox=(0, y, 800, y + 60))
            b.image_data = _fake_image()
            blocks.append(b)
            ocr_texts.append(text_val)

        pl = _full_page_layout(blocks, height=page_height)

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:
            mock_eps.return_value.process_pdf.return_value = [pl]
            mock_ocr.return_value.extract_text_from_image.side_effect = ocr_texts
            result = PDFService().extract_pdf_content("/fake/path.pdf")

        lines = [ln for ln in result.splitlines() if ln.strip()]
        assert "目录" in lines, f"'目录' missing from TOC output: {result!r}"
        # "前言" appears on the TOC page as the first entry after 目录 which triggered
        # toc mode, so it should be kept as a toc line
        assert "前言" in lines, f"'前言' TOC entry missing from output: {result!r}"
        assert "成长之路...(3)" in lines, f"Leader-dot entry missing: {result!r}"
        assert "理念篇...(4)" in lines, f"Parenthesised page entry missing: {result!r}"
        # Each entry must be on its own line (not merged into one long line)
        merged = " ".join(lines)
        for entry in ("成长之路...(3)", "理念篇...(4)"):
            assert entry in merged


class TestCaptionNoteAtomicGrouping:
    """C. Figure/table caption and note association — atomic handling."""

    def test_caption_type_block_kept_atomic(self):
        """A block explicitly labeled 'caption' by the layout analyser must be
        handled as a protected atomic unit, not treated as plain 'text'."""
        caption_block = LayoutBlock(block_type="caption", bbox=(0, 0, 400, 50))
        caption_block.image_data = _fake_image()
        page_layout = _make_page_layout([caption_block])

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:
            mock_eps.return_value.process_pdf.return_value = [page_layout]
            mock_ocr.return_value.extract_text_from_image.return_value = "图3 资产负债表示意图"
            result = PDFService().extract_pdf_content("/fake/path.pdf")

        assert "图3 资产负债表示意图" in result

    def test_figure_caption_not_merged_with_body_text(self):
        """A figure caption must appear on its own line, never merged into the
        preceding or following body paragraph."""
        blocks = [
            LayoutBlock(block_type="text", bbox=(0, 0, 400, 80)),
            LayoutBlock(block_type="text", bbox=(0, 90, 400, 130)),  # caption content
            LayoutBlock(block_type="text", bbox=(0, 140, 400, 220)),
        ]
        for b in blocks:
            b.image_data = _fake_image()
        page_layout = _make_page_layout(blocks)

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:
            mock_eps.return_value.process_pdf.return_value = [page_layout]
            mock_ocr.return_value.extract_text_from_image.side_effect = [
                "这是正文段落，描述了富人的现金流模型。",
                "图2 富人的现金流",
                "通过上图可以看出资产带来的收入远大于支出。",
            ]
            result = PDFService().extract_pdf_content("/fake/path.pdf")

        lines = [ln for ln in result.splitlines() if ln.strip()]
        # The caption must appear as a standalone line
        assert "图2 富人的现金流" in lines, f"Caption missing from output: {result!r}"
        # Body text must not be merged with the caption
        for line in lines:
            assert "图2 富人的现金流" not in line or line.strip() == "图2 富人的现金流", (
                f"Caption was merged with other content: {line!r}"
            )

    def test_note_line_detected_as_caption_atomic(self):
        """A note line (注：…) following a caption must be kept atomic."""
        svc = PDFService()
        assert svc._is_caption_block("注：该图数据来自富爸爸穷爸爸。", "text"), (
            "Note line starting with '注：' must be classified as caption"
        )
        assert svc._is_caption_block("注1：各项数值均为估算。", "text"), (
            "Numbered note '注1：' must be classified as caption"
        )

    def test_note_line_not_merged_into_body_paragraph(self):
        """A note block after a figure must not be merged with subsequent body text."""
        blocks = [
            LayoutBlock(block_type="image", bbox=(0, 0, 400, 200)),
            LayoutBlock(block_type="text", bbox=(0, 210, 400, 240)),  # caption
            LayoutBlock(block_type="text", bbox=(0, 245, 400, 265)),  # note
            LayoutBlock(block_type="text", bbox=(0, 280, 400, 360)),  # body
        ]
        for b in blocks:
            b.image_data = _fake_image()
        page_layout = _make_page_layout(blocks)

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:
            mock_eps.return_value.process_pdf.return_value = [page_layout]
            mock_ocr.return_value.extract_text_from_image.side_effect = [
                "图5 现金流象限",
                "注：图中数据仅供参考。",
                "上图清晰地说明了四个象限的定义。",
            ]
            result = PDFService().extract_pdf_content("/fake/path.pdf")

        lines = [ln.strip() for ln in result.splitlines() if ln.strip()]
        # The note must appear on its own line (not merged with body)
        assert "注：图中数据仅供参考。" in lines, f"Note line missing: {result!r}"
        # Body text must also appear
        assert "上图清晰地说明了四个象限的定义。" in lines, f"Body text missing: {result!r}"


class TestNormalizationSafety:
    """D. Conservative normalization — prevent destructive rewrite/truncation."""

    def test_low_confidence_cjk_substitution_rejected(self):
        """When normalization reduces CJK count significantly, prefer raw OCR.

        Scenario: OCR produces '进行\\n货' (OCR misread of '投资' → '货').
        After line-merge normalization we'd get '进行货'.  The CJK-count safety gate
        must detect the count *did not actually decrease here* (both have 3 CJK chars)
        but the LENGTH safety gate must reject if normalized is shorter than 75% of raw.
        """
        svc = PDFService()
        raw = "进行\n投资"           # 4 CJK chars (进行投资) + 1 newline = 5 chars total
        normalized = "进行"         # only 2 chars → 2 < 5 * 0.75 = 3.75 → reject
        result = svc._select_safe_normalized_text(raw, normalized, "text")
        assert result == "进行\n投资", (
            f"Conservative normalization must prefer raw when shortened by > 25%; got {result!r}"
        )

    def test_cjk_character_count_gate(self):
        """CJK count gate: if CJK chars drop by more than 25%, prefer raw."""
        svc = PDFService()
        # raw has 4 CJK chars; normalized has only 1 → 1 < 4 * 0.75 = 3 → reject
        raw = "投资理财"     # 4 CJK chars
        normalized = "投"   # 1 CJK char
        result = svc._select_safe_normalized_text(raw, normalized, "text")
        assert result == "投资理财", (
            f"CJK count gate must prefer raw when CJK chars reduced by > 25%; got {result!r}"
        )

    def test_safe_normalization_accepted(self):
        """When normalized length is >= 75% of raw, normalization is accepted."""
        svc = PDFService()
        raw = "abcdefgh"
        normalized = "abcdef"  # 6/8 = 0.75 → NOT less than threshold → accept
        result = svc._select_safe_normalized_text(raw, normalized, "text")
        assert result == normalized, (
            f"Normalization should be accepted when ratio is at threshold; got {result!r}"
        )

    def test_normalization_debug_logging_on_rejection(self, caplog):
        """Rejected normalizations must produce a DEBUG log for traceability."""
        import logging
        svc = PDFService()
        raw = "进行投资活动"
        normalized = "进"  # far too short
        with caplog.at_level(logging.DEBUG, logger="app.pdf_service"):
            svc._select_safe_normalized_text(raw, normalized, "text")
        assert any("Normalization rejected" in r.message for r in caplog.records), (
            "Normalization rejection must be logged at DEBUG level"
        )

    def test_toc_and_caption_bypass_safety_gate(self):
        """TOC and caption segments must bypass the length/CJK safety gates."""
        svc = PDFService()
        raw = "非常非常非常长的原始文本"
        normalized = "短"
        # For toc/caption types the normalized form is always returned as-is
        assert svc._select_safe_normalized_text(raw, normalized, "toc") == normalized
        assert svc._select_safe_normalized_text(raw, normalized, "caption") == normalized


class TestNewPipelineRequirements:
    def test_header_footer_blocks_skipped_in_text_ocr(self):
        header = LayoutBlock(block_type="header", bbox=(0, 0, 400, 40))
        header.image_data = _fake_image()
        body = LayoutBlock(block_type="text", bbox=(0, 80, 400, 140))
        body.image_data = _fake_image()
        page_layout = _make_page_layout([header, body])

        with patch("app.pdf_service.PDFService._get_enhanced_pdf_service") as mock_eps, \
             patch("app.pdf_service.PDFService._get_ocr_service") as mock_ocr:
            mock_eps.return_value.process_pdf.return_value = [page_layout]
            mock_ocr.return_value.extract_text_from_image.return_value = "body content"
            result = PDFService().extract_pdf_content("/fake/path.pdf")

        assert "body content" in result
        assert mock_ocr.return_value.extract_text_from_image.call_count == 1

    def test_visual_caption_note_blocks_are_merged(self):
        svc = EnhancedPDFService()
        visual = LayoutBlock(block_type="image", bbox=(20, 40, 220, 180), confidence=0.95)
        caption = LayoutBlock(block_type="caption", bbox=(20, 186, 220, 220), confidence=0.8)
        caption_note = LayoutBlock(block_type="caption", bbox=(20, 224, 220, 250), confidence=0.7)

        merged = svc._merge_visual_with_caption_blocks(
            [visual, caption, caption_note],
            _page_image(height=800, width=400),
        )

        assert len(merged) == 1
        assert merged[0].block_type == "image"
        assert merged[0].bbox == (20, 40, 220, 250)
