from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from app.paddleocr_vl_service import PaddleOCRVLPDFService
from app.services.mineru_popo_service import MineruPopoService
from app.services.page_ocr_service import (
    PageOCRService,
    _serialize_parsing_res_list,
)


def _install_fake_cv2(monkeypatch):
    fake_cv2 = SimpleNamespace(
        IMREAD_COLOR=1,
        imdecode=lambda *_args, **_kwargs: np.ones((8, 8, 3), dtype=np.uint8),
    )
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)


class TestPageOCRService:
    def test_process_page_bytes_reads_dict_result(self, monkeypatch):
        _install_fake_cv2(monkeypatch)
        service = PageOCRService()
        service._pipeline = SimpleNamespace(
            predict=lambda _imgs: iter(
                [{"parsing_res_list": [{"block_label": "text"}]}]
            )
        )
        service._initialized = True

        result = service.process_page_bytes(b"fake-png")

        assert result["parsing_res_list"][0]["block_label"] == "text"

    def test_process_page_bytes_warns_when_result_not_convertible_to_dict(
        self, monkeypatch, caplog
    ):
        _install_fake_cv2(monkeypatch)
        service = PageOCRService()
        service._pipeline = SimpleNamespace(
            predict=lambda _imgs: iter([SimpleNamespace(not_res={})])
        )
        service._initialized = True

        result = service.process_page_bytes(b"fake-png")

        assert result == {}
        assert "Failed to convert predict output to dict" in caplog.text

    def test_process_page_bytes_warns_when_parsing_result_empty(
        self, monkeypatch, caplog
    ):
        _install_fake_cv2(monkeypatch)
        service = PageOCRService()
        service._pipeline = SimpleNamespace(
            predict=lambda _imgs: iter([{"parsing_res_list": []}])
        )
        service._initialized = True

        result = service.process_page_bytes(b"fake-png")

        assert result == {"parsing_res_list": []}
        assert "parsing_res_list is empty" in caplog.text


class TestParsingResultSerialization:
    def test_serializes_paddleocr_block_objects_for_json_storage(self):
        block_obj = SimpleNamespace(
            label="text",
            bbox=np.array([[10, 20], [110, 20], [110, 220], [10, 220]], dtype=np.int16),
            content="hello",
            global_block_id=7,
            global_group_id=3,
            image=None,
            polygon_points=None,
        )

        serialized = _serialize_parsing_res_list([block_obj])

        assert serialized == [
            {
                "block_label": "text",
                "block_bbox": [[10, 20], [110, 20], [110, 220], [10, 220]],
                "block_content": "hello",
                "block_id": 7,
                "block_order": 3,
            }
        ]
        assert isinstance(json.dumps({"parsing_res_list": serialized}), str)

    def test_serializes_ndarray_bbox_for_json_storage(self):
        blocks = [
            {
                "block_label": "text",
                "block_bbox": np.array(
                    [[10, 20], [110, 20], [110, 220], [10, 220]], dtype=np.int16
                ),
            }
        ]

        serialized = _serialize_parsing_res_list(blocks)

        assert serialized == [
            {
                "block_label": "text",
                "block_bbox": [[10, 20], [110, 20], [110, 220], [10, 220]],
            }
        ]
        assert isinstance(json.dumps({"parsing_res_list": serialized}), str)

    def test_keeps_flat_bbox_json_serializable_without_changes(self):
        blocks = [{"block_label": "text", "block_bbox": [10, 20, 110, 220]}]

        serialized = _serialize_parsing_res_list(blocks)

        assert serialized == blocks
        assert isinstance(json.dumps({"parsing_res_list": serialized}), str)

    def test_serializes_tuple_quad_bbox_to_nested_lists(self):
        blocks = [
            {
                "block_label": "text",
                "block_bbox": ((10, 20), (110, 20), (110, 220), (10, 220)),
            }
        ]

        serialized = _serialize_parsing_res_list(blocks)

        assert serialized == [
            {
                "block_label": "text",
                "block_bbox": [[10, 20], [110, 20], [110, 220], [10, 220]],
            }
        ]


class TestQuadBboxParsing:
    def test_mineru_popo_service_parses_quad_bbox_lists(self):
        bbox = MineruPopoService._parse_bbox(
            [[10, 20], [110, 20], [110, 220], [10, 220]]
        )

        assert bbox == [10, 20, 110, 220]

    @pytest.mark.parametrize(
        "raw",
        [
            [[10], [110, 20], [110, 220], [10, 220]],
            [[10, 20], [110, 20]],
            [[10, "bad"], [110, 20], [110, 220], [10, 220]],
            [],
        ],
    )
    def test_mineru_popo_service_rejects_malformed_quad_bbox_lists(self, raw):
        bbox = MineruPopoService._parse_bbox(raw)

        assert bbox == [0, 0, 0, 0]

    def test_paddleocr_vl_service_parses_quad_bbox_arrays(self):
        service = PaddleOCRVLPDFService()

        bbox = service._parse_bbox(
            np.array([[10, 20], [110, 20], [110, 220], [10, 220]], dtype=np.int16)
        )

        assert bbox == (10, 20, 110, 220)

    @pytest.mark.parametrize(
        "raw",
        [
            np.array(
                [
                    [10, 20, 30],
                    [110, 20, 30],
                    [110, 220, 30],
                    [10, 220, 30],
                ],
                dtype=np.int16,
            ),
            np.array([[10, 20], [110, 20]], dtype=np.int16),
            np.array([], dtype=np.int16),
            [["10", "bad"], ["110", "20"], ["110", "220"], ["10", "220"]],
        ],
    )
    def test_paddleocr_vl_service_rejects_malformed_quad_bbox_arrays(self, raw):
        service = PaddleOCRVLPDFService()

        bbox = service._parse_bbox(raw)

        assert bbox is None


class TestPaddleOCRVLPDFService:
    def test_extract_pdf_content_reads_dict_result(self, monkeypatch):
        fake_doc = SimpleNamespace(page_count=1, close=lambda: None)
        fake_pipeline = SimpleNamespace(
            predict=lambda _imgs: [SimpleNamespace(raw=True)],
            restructure_pages=lambda _raw: [
                {
                    "parsing_res_list": [
                        {
                            "block_label": "text",
                            "block_content": "Hello from PaddleOCR-VL",
                            "block_bbox": [0, 0, 20, 20],
                        }
                    ]
                }
            ],
        )
        monkeypatch.setitem(sys.modules, "fitz", SimpleNamespace(open=lambda _path: fake_doc))
        monkeypatch.setattr(
            "app.paddleocr_vl_service._render_page_as_bgr",
            lambda _doc, _idx: np.ones((8, 8, 3), dtype=np.uint8),
        )

        service = PaddleOCRVLPDFService()
        service._pipeline = fake_pipeline
        service._pipeline_initialized = True

        result = service.extract_pdf_content("/fake.pdf")

        assert "Hello from PaddleOCR-VL" in result
