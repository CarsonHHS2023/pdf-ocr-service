from __future__ import annotations

import json

import httpx
import pytest

from app.processing.txt.analyzer_client import (
    OpenAICompatibleTxtAnalyzerConfig,
    OpenAICompatibleTxtStructureAnalyzer,
    TxtStructureAnalyzerClientError,
)
from app.processing.txt.structure_recovery import (
    TxtStructureAnalysisWindow,
    TxtStructureKind,
    TxtStructureWindowLine,
)


def _window() -> TxtStructureAnalysisWindow:
    return TxtStructureAnalysisWindow(
        "txt-structure-window:000001",
        0,
        (TxtStructureWindowLine("L000001", "Body", False),),
    )


def _success_response() -> httpx.Response:
    request = httpx.Request("POST", "https://llm.example/v1/responses")
    return httpx.Response(
        200,
        request=request,
        json={
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "assignments": {
                                        "L000001": {
                                            "kind": "paragraph",
                                            "starts_new_node": True,
                                            "heading_level": None,
                                        }
                                    }
                                }
                            ),
                        }
                    ],
                }
            ]
        },
    )


class _SequenceClient:
    def __init__(self, factory, **kwargs):
        self.factory = factory

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, *, headers, json):
        self.factory.calls += 1
        self.factory.urls.append(url)
        outcome = self.factory.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _SequenceFactory:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.urls = []

    def __call__(self, **kwargs):
        return _SequenceClient(self, **kwargs)


def _status_response(status_code: int) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request("POST", "https://llm.example/v1/responses"),
        json={"error": "temporary"},
    )


def _analyzer(factory, sleeps, *, max_attempts=3, backoff=0.25):
    return OpenAICompatibleTxtStructureAnalyzer(
        OpenAICompatibleTxtAnalyzerConfig(
            "https://llm.example/v1",
            "secret",
            "model-1",
            max_attempts=max_attempts,
            retry_backoff_seconds=backoff,
        ),
        client_factory=factory,
        sleep=sleeps.append,
    )


def test_retries_rate_limit_and_server_failures_with_bounded_exponential_backoff() -> None:
    factory = _SequenceFactory([_status_response(429), _status_response(503), _success_response()])
    sleeps = []
    result = _analyzer(factory, sleeps).analyze(_window())

    assert factory.calls == 3
    assert set(factory.urls) == {"https://llm.example/v1/responses"}
    assert sleeps == [0.25, 0.5]
    assert result.assignments[0].kind is TxtStructureKind.PARAGRAPH


def test_retries_known_transport_timeout_then_succeeds() -> None:
    request = httpx.Request("POST", "https://llm.example/v1/responses")
    factory = _SequenceFactory([httpx.ReadTimeout("timeout", request=request), _success_response()])
    sleeps = []
    result = _analyzer(factory, sleeps).analyze(_window())

    assert factory.calls == 2
    assert sleeps == [0.25]
    assert result.assignments[0].line_id == "L000001"


def test_non_retryable_client_error_fails_immediately_with_safe_status() -> None:
    factory = _SequenceFactory([_status_response(400), _success_response()])
    sleeps = []
    with pytest.raises(TxtStructureAnalyzerClientError) as caught:
        _analyzer(factory, sleeps).analyze(_window())

    assert factory.calls == 1
    assert sleeps == []
    assert caught.value.status_code == 400
    assert caught.value.retryable is False
    assert caught.value.stage == "provider_http"
    assert "temporary" not in str(caught.value)
    assert "secret" not in str(caught.value)


def test_transient_failure_stops_at_configured_attempt_bound() -> None:
    factory = _SequenceFactory([_status_response(503), _status_response(503), _success_response()])
    sleeps = []
    with pytest.raises(TxtStructureAnalyzerClientError) as caught:
        _analyzer(factory, sleeps, max_attempts=2).analyze(_window())

    assert factory.calls == 2
    assert sleeps == [0.25]
    assert caught.value.status_code == 503
    assert caught.value.retryable is True


def test_malformed_success_payload_is_not_retried() -> None:
    malformed = httpx.Response(
        200,
        request=httpx.Request("POST", "https://llm.example/v1/responses"),
        content=b"{not-json",
    )
    factory = _SequenceFactory([malformed, _success_response()])
    sleeps = []
    with pytest.raises(TxtStructureAnalyzerClientError, match="response was malformed") as caught:
        _analyzer(factory, sleeps).analyze(_window())

    assert factory.calls == 1
    assert sleeps == []
    assert caught.value.stage == "provider_json"


def test_retry_configuration_is_bounded_and_validated() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        OpenAICompatibleTxtAnalyzerConfig("https://llm.example/v1", "secret", "model-1", max_attempts=0)
    with pytest.raises(ValueError, match="retry_backoff_seconds"):
        OpenAICompatibleTxtAnalyzerConfig(
            "https://llm.example/v1",
            "secret",
            "model-1",
            retry_backoff_seconds=-0.1,
        )
