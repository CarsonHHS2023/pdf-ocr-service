from __future__ import annotations

import json

import pytest

from app.processing.structured_result_v2.model import ProcessingNodeKind
from app.processing.txt.analyzer_client import (
    OpenAICompatibleTxtAnalyzerConfig,
    OpenAICompatibleTxtStructureAnalyzer,
    TxtStructureAnalyzerClientError,
)
from app.processing.txt.normalization import normalize_txt_bytes
from app.processing.txt.structure_recovery import (
    TxtHeadingLevelAssignment,
    TxtLineStructureAssignment,
    TxtOutlineWindowResult,
    TxtStructureKind,
    TxtStructureRecoveryError,
    TxtStructureWindowResult,
    build_txt_outline_windows,
    build_txt_structure_windows,
    reconcile_txt_outline_levels,
    reconcile_txt_window_assignments,
    recover_txt_structure_to_spr_v2,
)


def _source(text: str):
    return normalize_txt_bytes(
        text.encode("utf-8"),
        document_ref="doc-outline",
        source_ref="source-outline",
        processing_run_ref="run-outline",
        raw_result_ref="raw-outline",
        max_lines_per_source_unit=3,
        max_chars_per_source_unit=100_000,
    )


def _local_results(source, assignments_by_line):
    results = []
    for window in build_txt_structure_windows(source, max_lines=80, overlap_lines=12):
        assignments = []
        for line in window.lines:
            if line.is_empty:
                continue
            kind, starts, level = assignments_by_line[line.line_id]
            assignments.append(TxtLineStructureAssignment(line.line_id, kind, starts, level))
        results.append(TxtStructureWindowResult(window.window_id, tuple(assignments)))
    return tuple(results)


def test_outline_is_compact_and_contains_only_existing_title_heading_candidates() -> None:
    source = _source("Book\nChapter 1\nBody\n1.1 Detail\nMore\nChapter 2\n")
    local = _local_results(
        source,
        {
            "L000001": (TxtStructureKind.TITLE, True, None),
            "L000002": (TxtStructureKind.HEADING, True, 1),
            "L000003": (TxtStructureKind.PARAGRAPH, True, None),
            "L000004": (TxtStructureKind.HEADING, True, 1),
            "L000005": (TxtStructureKind.PARAGRAPH, True, None),
            "L000006": (TxtStructureKind.HEADING, True, 1),
        },
    )
    consensus = reconcile_txt_window_assignments(source, local)
    outline = build_txt_outline_windows(source, consensus, max_candidates=3, overlap_candidates=1)

    assert [candidate.line_id for window in outline for candidate in window.candidates] == [
        "L000001", "L000002", "L000004", "L000004", "L000006",
    ]
    assert all(
        candidate.kind in {TxtStructureKind.TITLE, TxtStructureKind.HEADING}
        for window in outline
        for candidate in window.candidates
    )
    assert all(candidate.line_id not in {"L000003", "L000005"} for window in outline for candidate in window.candidates)


def test_outline_level_reconciliation_changes_hierarchy_without_changing_source_text() -> None:
    source = _source("Book\nChapter 1\n1.1 Detail\nBody text\nChapter 2\n")
    local = _local_results(
        source,
        {
            "L000001": (TxtStructureKind.TITLE, True, None),
            "L000002": (TxtStructureKind.HEADING, True, 1),
            "L000003": (TxtStructureKind.HEADING, True, 1),
            "L000004": (TxtStructureKind.PARAGRAPH, True, None),
            "L000005": (TxtStructureKind.HEADING, True, 1),
        },
    )
    consensus = reconcile_txt_window_assignments(source, local)
    outline = build_txt_outline_windows(source, consensus)
    assert len(outline) == 1
    global_results = (
        TxtOutlineWindowResult(
            outline[0].window_id,
            (
                TxtHeadingLevelAssignment("L000001", 1),
                TxtHeadingLevelAssignment("L000002", 1),
                TxtHeadingLevelAssignment("L000003", 2),
                TxtHeadingLevelAssignment("L000005", 1),
            ),
        ),
    )

    spr = recover_txt_structure_to_spr_v2(source, local, outline_results=global_results)
    title, chapter1, detail, body, chapter2 = spr.nodes

    assert title.kind is ProcessingNodeKind.TITLE
    assert chapter1.kind is ProcessingNodeKind.HEADING and chapter1.heading_level == 1
    assert detail.kind is ProcessingNodeKind.HEADING and detail.heading_level == 2
    assert detail.parent_id == chapter1.node_id
    assert body.parent_id == detail.node_id
    assert chapter2.kind is ProcessingNodeKind.HEADING and chapter2.heading_level == 1
    assert chapter2.parent_id is None
    assert [node.text for node in spr.nodes] == [
        "Book", "Chapter 1", "1.1 Detail", "Body text", "Chapter 2",
    ]


def test_outline_overlap_uses_majority_then_earliest_window_tie_break() -> None:
    source = _source("A\nB\nC\nD\n")
    local = _local_results(
        source,
        {
            line_id: (TxtStructureKind.HEADING, True, 1)
            for line_id in ("L000001", "L000002", "L000003", "L000004")
        },
    )
    consensus = reconcile_txt_window_assignments(source, local)
    windows = build_txt_outline_windows(source, consensus, max_candidates=3, overlap_candidates=2)
    assert len(windows) == 2
    results = (
        TxtOutlineWindowResult(
            windows[0].window_id,
            tuple(TxtHeadingLevelAssignment(candidate.line_id, 2) for candidate in windows[0].candidates),
        ),
        TxtOutlineWindowResult(
            windows[1].window_id,
            tuple(TxtHeadingLevelAssignment(candidate.line_id, 3) for candidate in windows[1].candidates),
        ),
    )
    levels = reconcile_txt_outline_levels(windows, results)
    assert levels["L000002"] == 2
    assert levels["L000003"] == 2


def test_outline_contract_fails_closed_on_missing_or_out_of_scope_assignments() -> None:
    source = _source("Chapter\nDetail\n")
    local = _local_results(
        source,
        {
            "L000001": (TxtStructureKind.HEADING, True, 1),
            "L000002": (TxtStructureKind.HEADING, True, 2),
        },
    )
    consensus = reconcile_txt_window_assignments(source, local)
    windows = build_txt_outline_windows(source, consensus)

    with pytest.raises(TxtStructureRecoveryError, match="missing assignments"):
        reconcile_txt_outline_levels(
            windows,
            (TxtOutlineWindowResult(windows[0].window_id, (TxtHeadingLevelAssignment("L000001", 1),)),),
        )
    with pytest.raises(TxtStructureRecoveryError, match="outside the window"):
        reconcile_txt_outline_levels(
            windows,
            (
                TxtOutlineWindowResult(
                    windows[0].window_id,
                    (
                        TxtHeadingLevelAssignment("L000001", 1),
                        TxtHeadingLevelAssignment("L000002", 2),
                        TxtHeadingLevelAssignment("L999999", 3),
                    ),
                ),
            ),
        )


class _Response:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Client:
    def __init__(self, response, capture, **kwargs):
        self.response = response
        self.capture = capture

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, *, headers, json):
        self.capture["url"] = url
        self.capture["headers"] = headers
        self.capture["json"] = json
        return self.response


def _responses_payload(assignments):
    return {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"assignments": assignments}),
                    }
                ],
            }
        ]
    }


def test_openai_compatible_outline_client_returns_levels_only_and_never_text() -> None:
    source = _source("Book\nChapter\nDetail\n")
    local = _local_results(
        source,
        {
            "L000001": (TxtStructureKind.TITLE, True, None),
            "L000002": (TxtStructureKind.HEADING, True, 1),
            "L000003": (TxtStructureKind.HEADING, True, 1),
        },
    )
    consensus = reconcile_txt_window_assignments(source, local)
    window = build_txt_outline_windows(source, consensus)[0]
    capture = {}
    response = _Response(
        _responses_payload(
            {
                "L000001": {"heading_level": 1},
                "L000002": {"heading_level": 1},
                "L000003": {"heading_level": 2},
            }
        )
    )
    analyzer = OpenAICompatibleTxtStructureAnalyzer(
        OpenAICompatibleTxtAnalyzerConfig("https://llm.example/v1", "secret", "model-1"),
        client_factory=lambda **kwargs: _Client(response, capture, **kwargs),
    )

    result = analyzer.reconcile_outline(window)
    assert [assignment.heading_level for assignment in result.assignments] == [1, 1, 2]
    assert capture["url"] == "https://llm.example/v1/responses"
    assert capture["json"]["text"]["format"]["type"] == "json_schema"
    assert capture["json"]["text"]["format"]["name"] == "txt_outline_heading_levels"
    assert capture["json"]["text"]["format"]["strict"] is True
    schema = capture["json"]["text"]["format"]["schema"]
    assignment_schema = schema["properties"]["assignments"]
    assert assignment_schema["required"] == ["L000001", "L000002", "L000003"]
    assert list(assignment_schema["properties"]) == ["L000001", "L000002", "L000003"]
    assert "line_id" not in schema["$defs"]["outline_assignment"]["properties"]
    assert "temperature" not in capture["json"]
    assert "response_format" not in capture["json"]
    assert "messages" not in capture["json"]
    request = json.dumps(capture["json"], ensure_ascii=False)
    assert "Chapter" in request and "Detail" in request
    assert "parent_id" not in request
    assert "replacement_text" not in request
    assert "secret" not in request


def test_openai_compatible_outline_client_rejects_model_generated_text_or_parent_fields() -> None:
    source = _source("Chapter\n")
    local = _local_results(
        source,
        {"L000001": (TxtStructureKind.HEADING, True, 1)},
    )
    consensus = reconcile_txt_window_assignments(source, local)
    window = build_txt_outline_windows(source, consensus)[0]
    response = _Response(
        _responses_payload(
            {
                "L000001": {
                    "heading_level": 1,
                    "text": "rewritten",
                    "parent_id": "made-up",
                }
            }
        )
    )
    analyzer = OpenAICompatibleTxtStructureAnalyzer(
        OpenAICompatibleTxtAnalyzerConfig("https://llm.example/v1", "secret", "model-1"),
        client_factory=lambda **kwargs: _Client(response, {}, **kwargs),
    )
    with pytest.raises(TxtStructureAnalyzerClientError):
        analyzer.reconcile_outline(window)
