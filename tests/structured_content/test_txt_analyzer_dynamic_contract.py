from __future__ import annotations

import json

import pytest

from app.processing.txt.analyzer_client import (
    OpenAICompatibleTxtAnalyzerConfig,
    OpenAICompatibleTxtStructureAnalyzer,
    TxtStructureAnalyzerClientError,
)
from app.processing.txt.canonicalization import (
    RetainedTxtCanonicalizationRequest,
    TxtCanonicalizationError,
    TxtCanonicalizationService,
)
from app.processing.txt.structure_recovery import (
    TxtOutlineAnalysisWindow,
    TxtOutlineCandidate,
    TxtStructureAnalysisWindow,
    TxtStructureKind,
    TxtStructureWindowLine,
)


class _Response:
    status_code = 200

    def __init__(self, assignments):
        self._payload = {
            "output_text": json.dumps({"assignments": assignments}),
        }

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self, response, capture=None, **kwargs):
        self.response = response
        self.capture = capture if capture is not None else {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, *, headers, json):
        self.capture["url"] = url
        self.capture["json"] = json
        return self.response


def _analyzer(assignments, capture=None):
    response = _Response(assignments)
    return OpenAICompatibleTxtStructureAnalyzer(
        OpenAICompatibleTxtAnalyzerConfig(
            "https://llm.example/v1",
            "secret",
            "model-1",
        ),
        client_factory=lambda **kwargs: _Client(response, capture, **kwargs),
    )


def _local_window():
    return TxtStructureAnalysisWindow(
        "txt-structure-window:000001",
        0,
        (
            TxtStructureWindowLine("L000001", "Heading", False),
            TxtStructureWindowLine("L000002", "Body", False),
            TxtStructureWindowLine("L000003", "", True),
        ),
    )


def _local_assignment(kind="paragraph", starts_new_node=True, heading_level=None):
    return {
        "kind": kind,
        "starts_new_node": starts_new_node,
        "heading_level": heading_level,
    }


def test_local_response_schema_owns_exact_nonempty_source_identities() -> None:
    capture = {}
    assignments = {
        "L000001": _local_assignment("heading", True, 1),
        "L000002": _local_assignment(),
    }
    result = _analyzer(assignments, capture).analyze(_local_window())

    schema = capture["json"]["text"]["format"]["schema"]
    assignment_schema = schema["properties"]["assignments"]
    assert assignment_schema["required"] == ["L000001", "L000002"]
    assert list(assignment_schema["properties"]) == ["L000001", "L000002"]
    assert assignment_schema["additionalProperties"] is False
    assert "L000003" not in assignment_schema["properties"]
    assert schema["$defs"]["structure_assignment"]["required"] == [
        "kind", "starts_new_node", "heading_level"
    ]
    assert "line_id" not in schema["$defs"]["structure_assignment"]["properties"]
    assert [item.line_id for item in result.assignments] == ["L000001", "L000002"]


@pytest.mark.parametrize(
    "assignments",
    [
        {"L000001": _local_assignment()},
        {
            "L000001": _local_assignment(),
            "L000002": _local_assignment(),
            "L999999": _local_assignment(),
        },
        {
            "L000001": _local_assignment(),
            "L000002": _local_assignment(),
            "L000003": _local_assignment(),
        },
    ],
)
def test_local_provider_identity_mismatch_still_fails_defensively(assignments) -> None:
    with pytest.raises(TxtStructureAnalyzerClientError) as caught:
        _analyzer(assignments).analyze(_local_window())
    assert caught.value.stage == "local_structure_contract"
    assert caught.value.contract_reason == "identity_set_mismatch"


def _outline_window():
    return TxtOutlineAnalysisWindow(
        "txt-outline-window:000001",
        0,
        (
            TxtOutlineCandidate("L000001", "Book", TxtStructureKind.TITLE, 1),
            TxtOutlineCandidate("L000002", "Chapter", TxtStructureKind.HEADING, 1),
        ),
    )


def test_outline_response_schema_owns_exact_candidate_identities() -> None:
    capture = {}
    result = _analyzer(
        {
            "L000001": {"heading_level": 1},
            "L000002": {"heading_level": 2},
        },
        capture,
    ).reconcile_outline(_outline_window())

    schema = capture["json"]["text"]["format"]["schema"]
    assignment_schema = schema["properties"]["assignments"]
    assert assignment_schema["required"] == ["L000001", "L000002"]
    assert list(assignment_schema["properties"]) == ["L000001", "L000002"]
    assert assignment_schema["additionalProperties"] is False
    assert schema["$defs"]["outline_assignment"]["required"] == ["heading_level"]
    assert [item.heading_level for item in result.assignments] == [1, 2]


@pytest.mark.parametrize(
    "assignments",
    [
        {"L000001": {"heading_level": 1}},
        {
            "L000001": {"heading_level": 1},
            "L000002": {"heading_level": 2},
            "L999999": {"heading_level": 3},
        },
    ],
)
def test_outline_provider_identity_mismatch_still_fails_defensively(assignments) -> None:
    with pytest.raises(TxtStructureAnalyzerClientError) as caught:
        _analyzer(assignments).reconcile_outline(_outline_window())
    assert caught.value.stage == "outline_contract"
    assert caught.value.contract_reason == "identity_set_mismatch"


class _FailingLookupSession:
    rolled_back = False
    closed = False

    def get(self, model, identity):
        raise RuntimeError("database detail that must remain internal")

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_canonicalization_wraps_unexpected_failure_with_exact_stage() -> None:
    session = _FailingLookupSession()
    service = TxtCanonicalizationService(
        storage=object(),
        session_factory=lambda: session,
        analyzer=object(),
    )
    with pytest.raises(TxtCanonicalizationError) as caught:
        service.canonicalize(
            RetainedTxtCanonicalizationRequest(
                "doc-1",
                "source-1",
                "run-1",
            )
        )
    assert caught.value.stage == "source_lookup"
    assert isinstance(caught.value.__cause__, RuntimeError)
    # The source lookup phase is intentionally read-only and short lived. It is
    # closed immediately on failure rather than being kept open long enough to
    # require a write-transaction rollback.
    assert session.rolled_back is False
    assert session.closed is True
