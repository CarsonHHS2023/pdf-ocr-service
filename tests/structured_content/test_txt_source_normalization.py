from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.processing.txt.normalization import (
    TxtNormalizationError,
    decode_txt_bytes,
    index_txt_lines,
    normalize_txt_bytes,
)
from app.source_units import SourceUnitKind, TextSpanAnchor


def _normalize(raw: bytes, **kwargs):
    return normalize_txt_bytes(
        raw,
        document_ref="doc-txt",
        source_ref="source-txt",
        processing_run_ref="run-txt",
        raw_result_ref="raw-txt",
        **kwargs,
    )


def test_utf8_and_utf8_bom_decode_without_replacement() -> None:
    plain = decode_txt_bytes("第一章\nHello".encode("utf-8"))
    bom = decode_txt_bytes("第一章\nHello".encode("utf-8-sig"))
    assert plain.text == bom.text == "第一章\nHello"
    assert plain.encoding == "utf-8"
    assert bom.encoding == "utf-8-sig"


def test_gb18030_gbk_compatible_source_decodes_deterministically() -> None:
    raw = "第一章\r\n中文正文".encode("gbk")
    decoded = decode_txt_bytes(raw)
    assert decoded.text == "第一章\r\n中文正文"
    assert decoded.encoding in {"gb18030", "gbk"}
    assert decode_txt_bytes(raw) == decoded


def test_line_index_preserves_crlf_lf_cr_offsets_and_empty_lines() -> None:
    text = "alpha\r\n\r\nbeta\ngamma\r"
    lines = index_txt_lines(text)

    assert [(line.line_id, line.text, line.separator) for line in lines] == [
        ("L000001", "alpha", "\r\n"),
        ("L000002", "", "\r\n"),
        ("L000003", "beta", "\n"),
        ("L000004", "gamma", "\r"),
        ("L000005", "", ""),
    ]
    for line in lines:
        assert text[line.body_start:line.body_end] == line.text
        assert text[line.separator_start:line.separator_end] == line.separator


def test_normalization_uses_text_flow_units_and_exact_line_anchors() -> None:
    raw = "Heading\r\n\r\nBody line\nFinal".encode("utf-8")
    result = _normalize(raw, max_lines_per_source_unit=2, max_chars_per_source_unit=1000)

    assert [unit.kind for unit in result.bundle.source_units] == [
        SourceUnitKind.TEXT_FLOW,
        SourceUnitKind.TEXT_FLOW,
    ]
    assert [unit.source_unit_id for unit in result.bundle.source_units] == [
        "txt-flow:000001",
        "txt-flow:000002",
    ]
    assert all(unit.dimensions is None for unit in result.bundle.source_units)
    assert [item.text for item in result.bundle.observations] == ["Heading", "Body line", "Final"]
    assert [item.metadata["line_id"] for item in result.bundle.observations] == ["L000001", "L000003", "L000004"]

    decoded = result.decoded.text
    for observation in result.bundle.observations:
        assert len(observation.anchors) == 1
        anchor = observation.anchors[0]
        assert isinstance(anchor, TextSpanAnchor)
        assert decoded[anchor.start:anchor.end] == observation.text


def test_empty_lines_keep_line_identity_but_create_no_observation() -> None:
    result = _normalize(b"first\n\nthird")
    assert [line.line_id for line in result.lines] == ["L000001", "L000002", "L000003"]
    assert result.lines[1].is_empty is True
    assert [item.metadata["line_id"] for item in result.bundle.observations] == ["L000001", "L000003"]


def test_source_unit_partition_is_deterministic_and_not_presentation_pagination() -> None:
    raw = "one\ntwo\nthree\nfour\nfive".encode()
    first = _normalize(raw, max_lines_per_source_unit=2, max_chars_per_source_unit=100)
    second = _normalize(raw, max_lines_per_source_unit=2, max_chars_per_source_unit=100)
    assert first == second
    assert [unit.source_order for unit in first.bundle.source_units] == [0, 1, 2]
    assert all(unit.kind is SourceUnitKind.TEXT_FLOW for unit in first.bundle.source_units)
    assert all("page" not in unit.source_unit_id for unit in first.bundle.source_units)


def test_nul_and_unsupported_bytes_fail_closed() -> None:
    with pytest.raises(TxtNormalizationError, match="NUL"):
        decode_txt_bytes(b"abc\x00def")
    with pytest.raises(TxtNormalizationError, match="could not be decoded"):
        decode_txt_bytes(b"\x81")


def test_txt_normalizer_has_no_ocr_llm_runtime_or_canonical_dependencies() -> None:
    source = Path("app/processing/txt/normalization.py").read_text(encoding="utf-8")
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
        "openai",
        "requests",
        "httpx",
        "app.database",
        "app.models",
        "app.routers",
        "app.services",
        "app.structured_content_v2",
    )
    assert not any(name.startswith(forbidden_prefixes) for name in imported)
    assert "physical_page" not in source
    assert "PageOCRService" not in source
    assert "Mineru" not in source
