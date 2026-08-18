from __future__ import annotations

from app.processing.structured_result_v2.model import ProcessingNodeKind
from app.processing.txt.normalization import normalize_txt_bytes
from app.processing.txt.structure_recovery import (
    TxtLineStructureAssignment,
    TxtStructureKind,
    TxtStructureWindowResult,
    build_txt_structure_windows,
    recover_txt_structure_to_spr_v2,
)
from app.source_units import TextSpanAnchor


def _source(text: str):
    return normalize_txt_bytes(
        text.encode("utf-8"),
        document_ref="doc-compact-toc",
        source_ref="source-compact-toc",
        processing_run_ref="run-compact-toc",
        raw_result_ref="raw-compact-toc",
        max_lines_per_source_unit=200,
        max_chars_per_source_unit=100_000,
    )


def _results(source, overrides=None):
    overrides = overrides or {}
    results = []
    for window in build_txt_structure_windows(source):
        assignments = []
        for line in window.lines:
            if line.is_empty:
                continue
            kind, starts, level = overrides.get(
                line.line_id,
                (TxtStructureKind.PARAGRAPH, True, None),
            )
            assignments.append(
                TxtLineStructureAssignment(
                    line_id=line.line_id,
                    kind=kind,
                    starts_new_node=starts,
                    heading_level=level,
                )
            )
        results.append(TxtStructureWindowResult(window.window_id, tuple(assignments)))
    return tuple(results)


def test_compact_multi_entry_chapter_rows_are_recovered_as_individual_toc_nodes() -> None:
    chapter1 = "\u7b2c\u4e00\u7ae0  Alpha"
    chapter2 = "\u7b2c\u4e8c\u7ae0  Beta"
    chapter3 = "\u7b2c\u4e09\u7ae0  Gamma"
    chapter4 = "\u7b2c\u56db\u7ae0  Delta"
    chapter5 = "\u7b2c\u4e94\u7ae0  Epsilon"
    chapter6 = "\u7b2c\u516d\u7ae0  Zeta"
    source = _source(
        "\n".join(
            [
                "\u5e7f\u544a\u5fc3\u7406\u6218",
                "\u4f5c\u8005\u4fe1\u606f",
                f"{chapter1} {chapter2}",
                f"{chapter3} {chapter4}",
                f"{chapter5} {chapter6}",
                chapter1,
                "\u6b63\u6587\u5f00\u59cb\u3002",
            ]
        )
    )
    spr = recover_txt_structure_to_spr_v2(
        source,
        _results(
            source,
            {
                "L000001": (TxtStructureKind.TITLE, True, None),
                "L000003": (TxtStructureKind.PARAGRAPH, True, None),
                "L000004": (TxtStructureKind.HEADING, True, 2),
                "L000005": (TxtStructureKind.UNKNOWN, True, None),
                "L000006": (TxtStructureKind.HEADING, True, 1),
            },
        ),
    )

    toc_nodes = [
        node
        for node in spr.nodes
        if (node.metadata or {}).get("txt_structure_kind") == "toc"
    ]
    assert [node.text for node in toc_nodes] == [
        chapter1,
        chapter2,
        chapter3,
        chapter4,
        chapter5,
        chapter6,
    ]
    assert all(node.kind is ProcessingNodeKind.REFERENCE for node in toc_nodes)
    assert all(
        (node.metadata or {}).get("recovery_rule") == "txt_compact_toc_split"
        for node in toc_nodes
    )
    assert all(
        len(node.anchors) == 1 and isinstance(node.anchors[0], TextSpanAnchor)
        for node in toc_nodes
    )
    for node in toc_nodes:
        anchor = node.anchors[0]
        assert source.decoded.text[anchor.start:anchor.end] == node.text

    body_heading = next(
        node
        for node in spr.nodes
        if node.text == chapter1 and node.kind is ProcessingNodeKind.HEADING
    )
    assert body_heading.heading_level == 1


def test_body_sentence_with_multiple_chapter_mentions_is_not_treated_as_compact_toc() -> None:
    text = "\u6211\u4eec\u5148\u8ba8\u8bba\u7b2c\u4e00\u7ae0 \u7684\u89c2\u70b9\uff0c\u7136\u540e\u6bd4\u8f83\u7b2c\u4e8c\u7ae0 \u7684\u5185\u5bb9\uff0c\u8fd9\u4ecd\u7136\u662f\u4e00\u6bb5\u6b63\u6587\u3002"
    source = _source(text)
    spr = recover_txt_structure_to_spr_v2(source, _results(source))

    assert len(spr.nodes) == 1
    assert spr.nodes[0].kind is ProcessingNodeKind.PARAGRAPH
    assert spr.nodes[0].text == text


def test_single_chapter_heading_is_not_reclassified_as_compact_toc() -> None:
    chapter = "\u7b2c\u4e00\u7ae0  Alpha"
    source = _source(chapter)
    spr = recover_txt_structure_to_spr_v2(
        source,
        _results(source, {"L000001": (TxtStructureKind.HEADING, True, 1)}),
    )

    assert len(spr.nodes) == 1
    assert spr.nodes[0].kind is ProcessingNodeKind.HEADING
    assert spr.nodes[0].heading_level == 1
