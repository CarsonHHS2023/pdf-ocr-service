from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document, ProcessingRun, SourceFile
import app.models_v2  # noqa: F401
import app.models_v2_selection  # noqa: F401
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
    TxtLineStructureAssignment,
    TxtStructureKind,
    TxtStructureWindowResult,
)
from app.storage.local import LocalStorageProvider
from app.storage.models import StorageReference
from app.structured_content_v2.repository import StructuredContentCandidateV2Repository
from app.structured_content_v2.selection import StructuredContentV2SelectionRepository


def _db(raw: bytes):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    digest = hashlib.sha256(raw).hexdigest()
    with factory.begin() as session:
        session.add(Document(id="doc-txt", title="TXT", file_type="txt", status="processing"))
        session.add(
            SourceFile(
                id="source-txt",
                document_id="doc-txt",
                original_filename="fixture.txt",
                file_type="txt",
                mime_type="text/plain",
                byte_size=len(raw),
                checksum_sha256=digest,
                storage_reference="src_" + "2" * 32,
                retained=1,
            )
        )
    return engine, factory


class _DeterministicAnalyzer:
    def analyze(self, window):
        assignments = []
        for line in window.lines:
            if line.is_empty:
                continue
            if line.line_id == "L000001":
                kind, starts, level = TxtStructureKind.TITLE, True, None
            elif line.text.startswith("1 "):
                kind, starts, level = TxtStructureKind.HEADING, True, 1
            else:
                kind, starts, level = TxtStructureKind.PARAGRAPH, line.text.startswith("Body"), None
            assignments.append(TxtLineStructureAssignment(line.line_id, kind, starts, level))
        return TxtStructureWindowResult(window.window_id, tuple(assignments))


def _put_source(storage, raw: bytes):
    ref = StorageReference.parse("src_" + "2" * 32)
    storage.put(raw, ref, expected_size=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest())


def test_retained_txt_becomes_spr_candidate_and_initial_explicit_selection(tmp_path) -> None:
    raw = "Book\r\n1 Intro\r\nBody first\r\ncontinued\n".encode("utf-8")
    engine, factory = _db(raw)
    storage = LocalStorageProvider(tmp_path)
    _put_source(storage, raw)
    service = TxtCanonicalizationService(storage=storage, session_factory=factory, analyzer=_DeterministicAnalyzer())
    request = RetainedTxtCanonicalizationRequest("doc-txt", "source-txt", "txt-run-001")
    try:
        outcome = service.canonicalize(request)
        assert outcome.initial_selection_created is True
        assert outcome.selected_candidate_id == outcome.candidate_id
        assert outcome.selection_version == 1
        assert outcome.candidate_id.startswith("scv2_txt_")
        assert storage.exists(outcome.structured_processing_result_ref)

        spr_payload = json.loads(storage.get(outcome.structured_processing_result_ref).decode("utf-8"))
        assert all(unit["kind"] == "text_flow" for unit in spr_payload["source_units"])
        assert spr_payload["nodes"][2]["text"] == "Body first\r\ncontinued"

        with factory() as session:
            run = session.execute(select(ProcessingRun).where(ProcessingRun.processing_run_id == "txt-run-001")).scalar_one()
            assert run.status == "succeeded"
            assert run.structured_processing_result_ref == outcome.structured_processing_result_ref
            candidate = StructuredContentCandidateV2Repository().get_candidate(session, outcome.candidate_id)
            assert candidate.document_ref == "doc-txt"
            assert all(unit.source_unit.kind.value == "text_flow" for unit in candidate.source_units)
            selection = StructuredContentV2SelectionRepository().get_selection(session, "doc-txt")
            assert selection.candidate_id == outcome.candidate_id
    finally:
        engine.dispose()


def test_txt_canonicalization_retry_is_idempotent_and_later_run_does_not_replace_selection(tmp_path) -> None:
    raw = b"Book\nBody\n"
    engine, factory = _db(raw)
    storage = LocalStorageProvider(tmp_path)
    _put_source(storage, raw)
    service = TxtCanonicalizationService(storage=storage, session_factory=factory, analyzer=_DeterministicAnalyzer())
    try:
        request = RetainedTxtCanonicalizationRequest("doc-txt", "source-txt", "txt-run-001")
        first = service.canonicalize(request)
        retry = service.canonicalize(request)
        later = service.canonicalize(RetainedTxtCanonicalizationRequest("doc-txt", "source-txt", "txt-run-002"))

        assert retry.candidate_id == first.candidate_id
        assert retry.structured_processing_result_ref == first.structured_processing_result_ref
        assert retry.initial_selection_created is False
        assert later.candidate_id != first.candidate_id
        assert later.selected_candidate_id == first.candidate_id
        assert later.selection_version == 1
    finally:
        engine.dispose()


def test_retained_txt_checksum_mismatch_fails_closed_before_analysis(tmp_path) -> None:
    raw = b"Book\nBody\n"
    engine, factory = _db(raw)
    storage = LocalStorageProvider(tmp_path)
    _put_source(storage, b"Book\nOther\n")
    service = TxtCanonicalizationService(storage=storage, session_factory=factory, analyzer=_DeterministicAnalyzer())
    try:
        with pytest.raises(TxtCanonicalizationError, match="byte size|checksum"):
            service.canonicalize(RetainedTxtCanonicalizationRequest("doc-txt", "source-txt", "txt-run-001"))
    finally:
        engine.dispose()


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http failure")

    def json(self):
        return self._payload


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
        "id": "resp_txt_test",
        "status": "completed",
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
        ],
    }


def test_openai_compatible_analyzer_uses_responses_strict_schema_and_parses_structure_only() -> None:
    from app.processing.txt.structure_recovery import TxtStructureAnalysisWindow, TxtStructureWindowLine

    capture = {}
    response = _Response(
        _responses_payload(
            {
                "L000001": {"kind": "heading", "starts_new_node": True, "heading_level": 1},
                "L000002": {"kind": "paragraph", "starts_new_node": True, "heading_level": None},
            }
        )
    )
    factory = lambda **kwargs: _Client(response, capture, **kwargs)
    analyzer = OpenAICompatibleTxtStructureAnalyzer(
        OpenAICompatibleTxtAnalyzerConfig("https://llm.example/v1", "secret", "model-1"),
        client_factory=factory,
    )
    window = TxtStructureAnalysisWindow(
        "txt-structure-window:000001",
        0,
        (
            TxtStructureWindowLine("L000001", "1 Intro", False),
            TxtStructureWindowLine("L000002", "Body", False),
        ),
    )

    result = analyzer.analyze(window)
    assert [item.kind for item in result.assignments] == [TxtStructureKind.HEADING, TxtStructureKind.PARAGRAPH]
    assert capture["url"] == "https://llm.example/v1/responses"
    assert capture["json"]["model"] == "model-1"
    assert capture["json"]["text"]["format"]["type"] == "json_schema"
    assert capture["json"]["text"]["format"]["strict"] is True
    schema = capture["json"]["text"]["format"]["schema"]
    assignment_schema = schema["properties"]["assignments"]
    assert assignment_schema["required"] == ["L000001", "L000002"]
    assert list(assignment_schema["properties"]) == ["L000001", "L000002"]
    assert "line_id" not in schema["$defs"]["structure_assignment"]["properties"]
    assert "temperature" not in capture["json"]
    assert "response_format" not in capture["json"]
    assert "messages" not in capture["json"]
    request_text = json.dumps(capture["json"], ensure_ascii=False)
    assert "L000001" in request_text and "1 Intro" in request_text
    assert "replacement_text" not in request_text
    assert "secret" not in request_text


def test_openai_compatible_analyzer_accepts_responses_output_text_shortcut() -> None:
    from app.processing.txt.structure_recovery import TxtStructureAnalysisWindow, TxtStructureWindowLine

    response = _Response(
        {
            "output_text": json.dumps(
                {
                    "assignments": {
                        "L000001": {"kind": "paragraph", "starts_new_node": True, "heading_level": None}
                    }
                }
            )
        }
    )
    analyzer = OpenAICompatibleTxtStructureAnalyzer(
        OpenAICompatibleTxtAnalyzerConfig("https://llm.example/v1", "secret", "model-1"),
        client_factory=lambda **kwargs: _Client(response, {}, **kwargs),
    )
    window = TxtStructureAnalysisWindow(
        "txt-structure-window:000001",
        0,
        (TxtStructureWindowLine("L000001", "Body", False),),
    )
    assert analyzer.analyze(window).assignments[0].kind is TxtStructureKind.PARAGRAPH


def test_openai_compatible_analyzer_rejects_model_generated_text_field() -> None:
    from app.processing.txt.structure_recovery import TxtStructureAnalysisWindow, TxtStructureWindowLine

    response = _Response(
        _responses_payload(
            {
                "L000001": {
                    "kind": "paragraph",
                    "starts_new_node": True,
                    "heading_level": None,
                    "text": "rewritten",
                }
            }
        )
    )
    analyzer = OpenAICompatibleTxtStructureAnalyzer(
        OpenAICompatibleTxtAnalyzerConfig("https://llm.example/v1", "secret", "model-1"),
        client_factory=lambda **kwargs: _Client(response, {}, **kwargs),
    )
    window = TxtStructureAnalysisWindow(
        "txt-structure-window:000001",
        0,
        (TxtStructureWindowLine("L000001", "Body", False),),
    )
    with pytest.raises(TxtStructureAnalyzerClientError, match="malformed"):
        analyzer.analyze(window)


def test_txt_canonicalization_has_no_ocr_mineru_modal_or_legacy_content_dependency() -> None:
    source = Path("app/processing/txt/canonicalization.py").read_text(encoding="utf-8")
    for forbidden in ("PdfPage", "MineruResult", "PageOCRService", "MineruPopo", "modal", "app.routers.books"):
        assert forbidden not in source
