import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import study_assistant
from app.routers import study


client = TestClient(app)


def payload():
    return {
        "contract": "reader-study-context",
        "version": 1,
        "document_ref": "doc-1",
        "candidate_id": "cand-1",
        "reader_contract_version": "2",
        "candidate_schema_id": "atlas.structured-content-candidate",
        "candidate_schema_version": 2,
        "question": "What matters here?",
        "items": [
            {
                "kind": "highlight",
                "item_id": "h-1",
                "node_id": "n-1",
                "source_unit_id": "su-1",
                "source_anchor": {"kind": "text_span", "source_unit_id": "su-1", "start": 4, "end": 9},
                "excerpt": "important",
                "text_start": 4,
                "text_end": 9,
                "highlight_style": "yellow",
            }
        ],
    }


def test_study_request_is_strict_and_versioned():
    bad = payload(); bad["extra"] = True
    assert client.post("/api/study/v1/ask", json=bad).status_code == 422
    bad = payload(); bad["version"] = 2
    assert client.post("/api/study/v1/ask", json=bad).status_code == 422


def test_typed_anchor_validation_fails_closed():
    bad = payload(); bad["items"][0]["source_anchor"] = {"kind": "text_span", "start": 10, "end": 2}
    assert client.post("/api/study/v1/ask", json=bad).status_code == 422


def test_endpoint_returns_safe_answer_and_source_ids(monkeypatch):
    monkeypatch.setattr(study_assistant, "ask_provider", lambda question, items: ("Grounded answer", ["h-1"]))
    response = client.post("/api/study/v1/ask", json=payload())
    assert response.status_code == 200
    assert response.json() == {
        "contract": "study-assistant-answer", "version": 1, "answer": "Grounded answer",
        "source_item_ids": ["h-1"], "model": "configured-provider"
    }


def test_endpoint_maps_configuration_error_without_secret(monkeypatch):
    def fail(*args, **kwargs):
        raise study_assistant.StudyAssistantNotConfigured("secret-key-value")
    monkeypatch.setattr(study_assistant, "ask_provider", fail)
    response = client.post("/api/study/v1/ask", json=payload())
    assert response.status_code == 503
    assert "secret-key-value" not in response.text
    assert response.json()["detail"]["code"] == "study_assistant_not_configured"


def test_provider_prompt_is_server_generated_and_source_subset_enforced():
    captured = {}
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": json.dumps({"answer": "A", "source_item_ids": ["h-1"]})}}]}
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, headers, json):
            captured.update(url=url, headers=headers, payload=json); return Response()
    cfg = study_assistant.StudyAssistantConfig("https://provider.example/v1", "TOPSECRET", "model-x")
    answer, source_ids = study_assistant.ask_provider("Q", [{"item_id": "h-1", "kind": "highlight", "excerpt": "x"}], config=cfg, client_factory=lambda **kwargs: Client())
    assert (answer, source_ids) == ("A", ["h-1"])
    assert captured["headers"]["Authorization"] == "Bearer TOPSECRET"
    assert "TOPSECRET" not in json.dumps(captured["payload"])
    assert captured["payload"]["messages"][0]["role"] == "system"

    class BadResponse(Response):
        def json(self):
            return {"choices": [{"message": {"content": json.dumps({"answer": "A", "source_item_ids": ["other"]})}}]}
    class BadClient(Client):
        def post(self, *args, **kwargs): return BadResponse()
    with pytest.raises(study_assistant.StudyAssistantMalformedResponse):
        study_assistant.ask_provider("Q", [{"item_id": "h-1"}], config=cfg, client_factory=lambda **kwargs: BadClient())


def test_context_size_and_duplicate_ids_are_bounded(monkeypatch):
    duplicate = payload(); duplicate["items"].append(dict(duplicate["items"][0]))
    assert client.post("/api/study/v1/ask", json=duplicate).status_code == 422
    huge = payload(); huge["question"] = "x" * (study.MAX_QUESTION + 1)
    assert client.post("/api/study/v1/ask", json=huge).status_code == 422


def test_source_has_no_legacy_or_storage_dependencies():
    import pathlib
    source = pathlib.Path("app/routers/study.py").read_text() + pathlib.Path("app/study_assistant.py").read_text()
    for forbidden in ["/api/reader/v1", "/api/v1/books/", "artifact_ref", "storage_ref", "signed_url", "Modal", "raw_processing_result"]:
        assert forbidden not in source
