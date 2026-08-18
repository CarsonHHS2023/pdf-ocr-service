from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.processing.structured_result_v2.model import ProcessingNodeKind
from app.processing.structured_result_v2.validation import validate_spr_v2
from app.processing.txt.normalization import normalize_txt_bytes
from app.processing.txt.structure_recovery import (
    TxtLineStructureAssignment,
    TxtStructureKind,
    TxtStructureRecoveryError,
    TxtStructureWindowResult,
    build_txt_structure_windows,
    recover_txt_structure_to_spr_v2,
)
from app.source_units import SourceUnitKind, TextSpanAnchor


def _source(text: str, *, source_unit_lines: int = 200):
    return normalize_txt_bytes(
        text.encode("utf-8"),
        document_ref="doc-txt",
        source_ref="source-txt",
        processing_run_ref="run-txt",
        raw_result_ref="raw-txt",
        max_lines_per_source_unit=source_unit_lines,
        max_chars_per_source_unit=100_000,
    )


def _results(source, *, max_lines=80, overlap=12, overrides=None):
    overrides = overrides or {}
    windows = build_txt_structure_windows(source, max_lines=max_lines, overlap_lines=overlap)
    results = []
    for window in windows:
        assignments = []
        for line in window.lines:
            if line.is_empty:
                continue
            kind, starts, level = overrides.get(
                (window.window_id, line.line_id),
                overrides.get(line.line_id, (TxtStructureKind.PARAGRAPH, True, None)),
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


def test_windows_are_bounded_deterministic_and_keep_empty_line_context() -> None:
    source = _source("a\n\nb\nc\nd\ne")
    first = build_txt_structure_windows(source, max_lines=3, overlap_lines=1)
    second = build_txt_structure_windows(source, max_lines=3, overlap_lines=1)

    assert first == second
    assert [window.window_id for window in first] == [
        "txt-structure-window:000001",
        "txt-structure-window:000002",
        "txt-structure-window:000003",
    ]
    assert max(len(window.lines) for window in first) <= 3
    assert first[0].lines[1].line_id == "L000002"
    assert first[0].lines[1].is_empty is True
    assert first[0].lines[1].text == ""


def test_assignment_contract_has_no_replacement_text_field() -> None:
    assert "text" not in TxtLineStructureAssignment.__dataclass_fields__
    assignment = TxtLineStructureAssignment("L000001", TxtStructureKind.PARAGRAPH, True)
    assert assignment.line_id == "L000001"


def test_overlap_tie_break_uses_earliest_deterministic_window() -> None:
    source = _source("one\ntwo\nthree\nfour\nfive")
    windows = build_txt_structure_windows(source, max_lines=3, overlap_lines=1)
    shared_line = "L000003"
    results = _results(
        source,
        max_lines=3,
        overlap=1,
        overrides={
            (windows[0].window_id, shared_line): (TxtStructureKind.HEADING, True, 2),
            (windows[1].window_id, shared_line): (TxtStructureKind.PARAGRAPH, True, None),
        },
    )

    spr = recover_txt_structure_to_spr_v2(source, results, max_lines=3, overlap_lines=1)
    line_three_node = next(node for node in spr.nodes if node.metadata["source_line_ids"] == (shared_line,))
    assert line_three_node.kind is ProcessingNodeKind.HEADING
    assert line_three_node.heading_level == 2


def test_overlap_majority_wins_independent_of_result_tuple_order() -> None:
    source = _source("1\n2\n3\n4\n5\n6")
    windows = build_txt_structure_windows(source, max_lines=4, overlap_lines=3)
    target = "L000004"
    assert len(windows) == 3
    overrides = {
        (windows[0].window_id, target): (TxtStructureKind.HEADING, True, 2),
        (windows[1].window_id, target): (TxtStructureKind.PARAGRAPH, True, None),
        (windows[2].window_id, target): (TxtStructureKind.PARAGRAPH, True, None),
    }
    results = _results(source, max_lines=4, overlap=3, overrides=overrides)

    spr_a = recover_txt_structure_to_spr_v2(source, results, max_lines=4, overlap_lines=3)
    spr_b = recover_txt_structure_to_spr_v2(source, tuple(reversed(results)), max_lines=4, overlap_lines=3)
    assert spr_a == spr_b
    target_node = next(node for node in spr_a.nodes if node.metadata["source_line_ids"] == (target,))
    assert target_node.kind is ProcessingNodeKind.PARAGRAPH


def test_multiline_grouping_preserves_exact_source_newlines_and_blank_breaks_group() -> None:
    source = _source("first\r\nsecond\n\nthird\rfourth")
    results = _results(
        source,
        overrides={
            "L000001": (TxtStructureKind.PARAGRAPH, True, None),
            "L000002": (TxtStructureKind.PARAGRAPH, False, None),
            "L000004": (TxtStructureKind.PARAGRAPH, False, None),
            "L000005": (TxtStructureKind.PARAGRAPH, False, None),
        },
    )

    spr = recover_txt_structure_to_spr_v2(source, results)

    assert spr.nodes[0].text == "first\r\nsecond"
    assert spr.nodes[0].metadata["source_line_ids"] == ("L000001", "L000002")
    assert spr.nodes[1].metadata["source_line_ids"] == ("L000004", "L000005")
    assert spr.nodes[1].text == "third\rfourth"


def test_node_can_span_multiple_text_flow_source_units_without_fake_pages() -> None:
    source = _source("alpha\nbeta\ngamma\ndelta", source_unit_lines=2)
    results = _results(
        source,
        overrides={
            "L000001": (TxtStructureKind.PARAGRAPH, True, None),
            "L000002": (TxtStructureKind.PARAGRAPH, False, None),
            "L000003": (TxtStructureKind.PARAGRAPH, False, None),
            "L000004": (TxtStructureKind.PARAGRAPH, False, None),
        },
    )

    spr = recover_txt_structure_to_spr_v2(source, results)

    assert len(spr.nodes) == 1
    assert len(spr.nodes[0].source_unit_ids) >= 2
    assert all(unit.kind is SourceUnitKind.TEXT_FLOW for unit in spr.source_units)
    assert all(isinstance(anchor, TextSpanAnchor) for anchor in spr.nodes[0].anchors)
    assert spr.nodes[0].text == "alpha\nbeta\ngamma\ndelta"
    validate_spr_v2(spr)


def test_heading_hierarchy_and_toc_mapping_are_deterministic() -> None:
    source = _source("Book\n1 Intro\nBody\n1.1 Detail\nMore\nContents", source_unit_lines=2)
    results = _results(
        source,
        overrides={
            "L000001": (TxtStructureKind.TITLE, True, None),
            "L000002": (TxtStructureKind.HEADING, True, 1),
            "L000003": (TxtStructureKind.PARAGRAPH, True, None),
            "L000004": (TxtStructureKind.HEADING, True, 2),
            "L000005": (TxtStructureKind.PARAGRAPH, True, None),
            "L000006": (TxtStructureKind.TOC, True, None),
        },
    )

    spr = recover_txt_structure_to_spr_v2(source, results)
    title, heading1, body, heading2, more, toc = spr.nodes

    assert title.kind is ProcessingNodeKind.TITLE
    assert title.heading_level == 1
    assert heading1.parent_id is None
    assert body.parent_id == heading1.node_id
    assert heading2.parent_id == heading1.node_id
    assert more.parent_id == heading2.node_id
    assert toc.kind is ProcessingNodeKind.REFERENCE
    assert toc.metadata["txt_structure_kind"] == "toc"
    assert toc.parent_id == heading2.node_id


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("missing_window", "missing analysis window results"),
        ("unknown_line", "outside the window"),
        ("duplicate_line", "duplicate assignment"),
        ("missing_line", "missing assignments"),
        ("empty_line", "empty source lines"),
    ],
)
def test_malformed_analysis_output_fails_closed(mutation, message) -> None:
    source = _source("a\n\nb\nc")
    results = list(_results(source, max_lines=3, overlap=1))

    if mutation == "missing_window":
        results.pop()
    elif mutation == "unknown_line":
        first = results[0]
        bad = first.assignments + (
            TxtLineStructureAssignment("L999999", TxtStructureKind.PARAGRAPH, True),
        )
        results[0] = TxtStructureWindowResult(first.window_id, bad)
    elif mutation == "duplicate_line":
        first = results[0]
        results[0] = TxtStructureWindowResult(first.window_id, first.assignments + (first.assignments[0],))
    elif mutation == "missing_line":
        first = results[0]
        results[0] = TxtStructureWindowResult(first.window_id, first.assignments[1:])
    elif mutation == "empty_line":
        first = results[0]
        bad = first.assignments + (
            TxtLineStructureAssignment("L000002", TxtStructureKind.PARAGRAPH, True),
        )
        results[0] = TxtStructureWindowResult(first.window_id, bad)

    with pytest.raises(TxtStructureRecoveryError, match=message):
        recover_txt_structure_to_spr_v2(
            source,
            tuple(results),
            max_lines=3,
            overlap_lines=1,
        )


def test_heading_assignment_invariants_fail_at_contract_boundary() -> None:
    with pytest.raises(TxtStructureRecoveryError, match="positive heading_level"):
        TxtLineStructureAssignment("L000001", TxtStructureKind.HEADING, True)
    with pytest.raises(TxtStructureRecoveryError, match="must start a new node"):
        TxtLineStructureAssignment("L000001", TxtStructureKind.TITLE, False)
    with pytest.raises(TxtStructureRecoveryError, match="only valid for title/heading"):
        TxtLineStructureAssignment("L000001", TxtStructureKind.PARAGRAPH, True, 2)


def test_structure_recovery_has_no_runtime_persistence_or_network_dependencies() -> None:
    source = Path("app/processing/txt/structure_recovery.py").read_text(encoding="utf-8")
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
        "openai",
        "app.database",
        "app.models",
        "app.routers",
        "app.services",
        "app.structured_content_v2",
    )
    assert not any(name.startswith(forbidden_prefixes) for name in imported)
