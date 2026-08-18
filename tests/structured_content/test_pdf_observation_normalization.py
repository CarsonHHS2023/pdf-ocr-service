from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from app.processing.paddle_vl.normalization import (
    PaddlePdfNormalizationError,
    _coerce_parsing_entry,
    normalize_paddle_pdf_raw_result,
)
from app.source_units import SourceUnitKind, SpatialAnchor


FIXTURE = Path("tests/fixtures/providers/paddle_vl_api/result_page_mapping_multi_range.json")


def _raw_pages():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return payload["documents"][0]["raw_result"]


def _normalize(raw_result):
    return normalize_paddle_pdf_raw_result(
        raw_result,
        document_ref="document_fixture_001",
        source_ref="source-file-001",
        processing_run_ref="processing-run-001",
        raw_result_ref="raw-result-001",
    )


def test_real_provider_fixture_maps_original_pdf_pages_to_physical_source_units() -> None:
    bundle = _normalize(_raw_pages())

    assert [unit.kind for unit in bundle.source_units] == [SourceUnitKind.PHYSICAL_PAGE] * 3
    assert [unit.source_unit_id for unit in bundle.source_units] == [
        "pdf-page:000001",
        "pdf-page:000002",
        "pdf-page:000003",
    ]
    assert [unit.source_order for unit in bundle.source_units] == [0, 1, 2]
    assert [(unit.dimensions.width, unit.dimensions.height) for unit in bundle.source_units] == [
        (612.0, 792.0),
        (612.0, 792.0),
        (612.0, 792.0),
    ]

    first = bundle.observations[0]
    assert first.source_unit_id == "pdf-page:000001"
    assert first.observed_kind == "text"
    assert first.text == "# Fixture page 1\n\nHello page one."
    assert first.confidence == pytest.approx(0.91)
    assert isinstance(first.anchors[0], SpatialAnchor)
    assert first.anchors[0].left == pytest.approx(72 / 612)
    assert first.anchors[0].top == pytest.approx(72 / 792)
    assert first.anchors[0].right == pytest.approx(540 / 612)
    assert first.anchors[0].bottom == pytest.approx(120 / 792)

    first_evidence = bundle.evidence[0]
    assert first_evidence.observation_id == first.observation_id
    assert first_evidence.processing_run_ref == "processing-run-001"
    assert first_evidence.raw_result_ref == "raw-result-001"
    assert first_evidence.provider_ref == "paddle-vl"


def test_page_input_order_does_not_change_normalized_output() -> None:
    pages = _raw_pages()
    forward = _normalize(pages)
    reverse = _normalize(list(reversed(copy.deepcopy(pages))))

    assert forward == reverse


def test_block_order_is_provider_order_not_list_position() -> None:
    page = copy.deepcopy(_raw_pages()[0])
    page["blocks"] = [
        {"type": "text", "text": "second", "bbox": [10, 20, 50, 40], "confidence": 0.8, "order": 2},
        {"type": "title", "text": "first", "bbox": [10, 5, 50, 15], "confidence": 0.9, "order": 1},
    ]

    bundle = _normalize([page])

    assert [item.text for item in bundle.observations] == ["first", "second"]
    assert [item.observed_kind for item in bundle.observations] == ["title", "text"]
    assert [item.order for item in bundle.observations] == [0, 1]


@pytest.mark.parametrize("page_number_text", ["12", "XIV", "十二", "第十二页"])
def test_mapping_parsing_entry_preserves_paddle_number_label_independent_of_text(
    page_number_text: str,
) -> None:
    page = copy.deepcopy(_raw_pages()[0])
    page.pop("blocks", None)
    page["parsing_res_list"] = [
        {
            "block_label": "number",
            "block_content": page_number_text,
            "block_bbox": [72, 720, 100, 750],
            "block_order": 7,
        }
    ]

    bundle = _normalize([page])

    assert len(bundle.observations) == 1
    assert bundle.observations[0].observed_kind == "number"
    assert bundle.observations[0].text == page_number_text


def test_paddle_parsing_res_string_entry_is_adapted_to_block_mapping() -> None:
    page = copy.deepcopy(_raw_pages()[0])
    page.pop("blocks", None)
    page["parsing_res_list"] = [
        "label: text\nbbox: [72, 72, 540, 120]\ncontent: Hello from Paddle string output."
    ]

    bundle = _normalize([page])

    assert len(bundle.observations) == 1
    observation = bundle.observations[0]
    assert observation.observed_kind == "text"
    assert observation.text == "Hello from Paddle string output."
    assert observation.metadata["provider_block_input_index"] == 0
    assert observation.anchors[0].left == pytest.approx(72 / 612)
    assert observation.anchors[0].bottom == pytest.approx(120 / 792)


def test_multiline_paddle_parsing_content_is_preserved() -> None:
    page = copy.deepcopy(_raw_pages()[0])
    page.pop("blocks", None)
    page["parsing_res_list"] = [
        "type: paragraph\nbbox: 20 30 300 100\ncontent: first line\nsecond line"
    ]

    bundle = _normalize([page])

    assert bundle.observations[0].observed_kind == "paragraph"
    assert bundle.observations[0].text == "first line\nsecond line"


def test_empty_structured_content_does_not_fall_back_to_provider_debug_text() -> None:
    page = copy.deepcopy(_raw_pages()[0])
    page.pop("blocks", None)
    page["parsing_res_list"] = [
        "label: chart\nbbox: [152, 237, 540, 325]\ncontent:"
    ]

    bundle = _normalize([page])

    observation = bundle.observations[0]
    assert observation.observed_kind == "chart"
    assert observation.text is None
    assert observation.anchors[0].left == pytest.approx(152 / 612)


def test_unstructured_plain_string_still_uses_text_fallback() -> None:
    parsed = _coerce_parsing_entry(
        "Plain provider text without structured fields",
        order=3,
        page_number=1,
    )

    assert parsed == {
        "order": 3,
        "text": "Plain provider text without structured fields",
    }


def test_public_blocks_path_remains_strict_for_non_mapping_entries() -> None:
    page = copy.deepcopy(_raw_pages()[0])
    page["blocks"] = ["label: text\nbbox: [1, 1, 20, 20]\ncontent: not allowed here"]

    with pytest.raises(PaddlePdfNormalizationError, match="block must be a mapping"):
        _normalize([page])


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda pages: pages.__setitem__(1, copy.deepcopy(pages[0])), "duplicate source page"),
        (lambda pages: pages[0].__setitem__("width", 0), "finite positive"),
        (lambda pages: pages[0]["blocks"][0].__setitem__("bbox", [-1, 0, 10, 10]), "outside page dimensions"),
        (lambda pages: pages[0].__setitem__("page_index", 4), "inconsistent page_index"),
        (lambda pages: pages[0].__setitem__("local_page_index", 1), "inconsistent local_page_index"),
    ],
)
def test_malformed_provider_page_data_fails_closed(mutator, message) -> None:
    pages = copy.deepcopy(_raw_pages())
    mutator(pages)
    with pytest.raises(PaddlePdfNormalizationError, match=message):
        _normalize(pages)


def test_normalizer_has_no_runtime_or_persistence_dependencies() -> None:
    source = Path("app/processing/paddle_vl/normalization.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden_prefixes = (
        "sqlalchemy",
        "fastapi",
        "modal",
        "requests",
        "httpx",
        "app.database",
        "app.models",
        "app.routers",
        "app.services",
        "app.structured_content_v2",
    )
    assert not any(name.startswith(forbidden_prefixes) for name in imported)
