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


def _source(text: str):
    return normalize_txt_bytes(
        text.encode("utf-8"),
        document_ref="doc-repeat-header",
        source_ref="source-repeat-header",
        processing_run_ref="run-repeat-header",
        raw_result_ref="raw-repeat-header",
        max_lines_per_source_unit=200,
        max_chars_per_source_unit=100_000,
    )


def _results(source, overrides):
    windows = build_txt_structure_windows(source)
    results = []
    for window in windows:
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


def test_repeated_serial_book_title_keeps_first_title_and_demotes_later_occurrences_to_headers() -> None:
    repeated = "伍稻洋《市委书记的两规日子》"
    source = _source(
        "\n".join(
            [
                repeated,
                "目录",
                "第一章",
                "正文 A",
                repeated,
                "第二章",
                "正文 B",
                repeated,
                "第三章",
                "正文 C",
                repeated,
                "第四章",
            ]
        )
    )
    results = _results(
        source,
        {
            "L000001": (TxtStructureKind.TITLE, True, None),
            "L000003": (TxtStructureKind.HEADING, True, 1),
            "L000005": (TxtStructureKind.PARAGRAPH, True, None),
            "L000006": (TxtStructureKind.HEADING, True, 1),
            "L000008": (TxtStructureKind.HEADING, True, 2),
            "L000009": (TxtStructureKind.HEADING, True, 1),
            "L000011": (TxtStructureKind.TITLE, True, 1),
            "L000012": (TxtStructureKind.HEADING, True, 1),
        },
    )

    spr = recover_txt_structure_to_spr_v2(source, results)
    repeated_nodes = [node for node in spr.nodes if node.text == repeated]

    assert len(repeated_nodes) == 4
    assert repeated_nodes[0].kind is ProcessingNodeKind.TITLE
    assert repeated_nodes[0].heading_level == 1
    assert [node.kind for node in repeated_nodes[1:]] == [
        ProcessingNodeKind.HEADER,
        ProcessingNodeKind.HEADER,
        ProcessingNodeKind.HEADER,
    ]
    assert all(node.heading_level is None for node in repeated_nodes[1:])
    assert all(node.metadata["txt_structure_kind"] == "header" for node in repeated_nodes[1:])


def test_two_matching_body_lines_are_not_reclassified_as_running_headers() -> None:
    repeated = "This sentence intentionally occurs twice."
    source = _source(f"{repeated}\nbody\n{repeated}\nend")
    spr = recover_txt_structure_to_spr_v2(source, _results(source, {}))

    repeated_nodes = [node for node in spr.nodes if node.text == repeated]
    assert len(repeated_nodes) == 2
    assert all(node.kind is ProcessingNodeKind.PARAGRAPH for node in repeated_nodes)
