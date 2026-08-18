from __future__ import annotations

import asyncio

import httpx
import pytest

import app.processing.openai_provider_error_diagnostics as diagnostics
from app.processing.openai_provider_error_diagnostics import (
    _emit_http_error_response,
    _safe_openai_error_fields,
    diagnostic_openai_client_factory,
)
from app.processing.openai_structure_refinement_provider import (
    StructureRefinementProviderError,
)
from app.processing.pdf_structure_refinement_images import (
    openai_pdf_structure_refiner_from_env,
)


def _response(payload: object, *, status_code: int = 400) -> httpx.Response:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    return httpx.Response(status_code, json=payload, request=request)


def test_safe_error_fields_exclude_free_form_message_and_secrets() -> None:
    secret = "sk-test-secret"
    response = _response(
        {
            "error": {
                "type": " invalid_request_error ",
                "code": "invalid_json_schema",
                "param": "text.format.schema",
                "message": f"rejected submitted value {secret}",
                "request_body": secret,
                "authorization": f"Bearer {secret}",
            },
            "unrelated": secret,
        }
    )

    fields = _safe_openai_error_fields(response)

    assert fields == {
        "status_code": 400,
        "provider_error_type": "invalid_request_error",
        "provider_error_code": "invalid_json_schema",
        "provider_error_param": "text.format.schema",
    }
    rendered = repr(fields)
    assert secret not in rendered
    assert "message" not in rendered
    assert "request_body" not in rendered
    assert "authorization" not in rendered


def test_malformed_or_unexpected_error_body_logs_status_only() -> None:
    assert _safe_openai_error_fields(_response(["not", "an", "object"])) == {
        "status_code": 400
    }
    assert _safe_openai_error_fields(_response({"error": "not-an-object"})) == {
        "status_code": 400
    }


def test_response_hook_emits_only_safe_fields(monkeypatch) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        diagnostics,
        "emit_refinement_provider_event",
        lambda event, fields: events.append((event, dict(fields))),
    )

    asyncio.run(
        _emit_http_error_response(
            _response(
                {
                    "error": {
                        "type": "invalid_request_error",
                        "code": "invalid_json_schema",
                        "param": "text.format.schema",
                        "message": "must never be logged",
                    }
                }
            )
        )
    )

    assert events == [
        (
            "PDF_STRUCTURE_REFINEMENT_PROVIDER_HTTP_ERROR",
            {
                "status_code": 400,
                "provider_error_type": "invalid_request_error",
                "provider_error_code": "invalid_json_schema",
                "provider_error_param": "text.format.schema",
            },
        )
    ]


def test_credit_balance_exhausted_raises_non_retryable_provider_error(
    monkeypatch,
) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        diagnostics,
        "emit_refinement_provider_event",
        lambda event, fields: events.append((event, dict(fields))),
    )
    response = _response(
        {
            "error": {
                "type": "insufficient_quota",
                "code": "credit_balance_exhausted",
                "message": "must never be logged",
            }
        },
        status_code=429,
    )

    with pytest.raises(StructureRefinementProviderError) as captured:
        asyncio.run(_emit_http_error_response(response))

    assert captured.value.status_code == 429
    assert captured.value.retryable is False
    assert events == [
        (
            "PDF_STRUCTURE_REFINEMENT_PROVIDER_HTTP_ERROR",
            {
                "status_code": 429,
                "provider_error_type": "insufficient_quota",
                "provider_error_code": "credit_balance_exhausted",
            },
        )
    ]


def test_ordinary_rate_limit_remains_retryable_in_existing_http_flow(
    monkeypatch,
) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        diagnostics,
        "emit_refinement_provider_event",
        lambda event, fields: events.append((event, dict(fields))),
    )

    asyncio.run(
        _emit_http_error_response(
            _response(
                {
                    "error": {
                        "type": "rate_limit_error",
                        "code": "rate_limit_exceeded",
                    }
                },
                status_code=429,
            )
        )
    )

    assert events == [
        (
            "PDF_STRUCTURE_REFINEMENT_PROVIDER_HTTP_ERROR",
            {
                "status_code": 429,
                "provider_error_type": "rate_limit_error",
                "provider_error_code": "rate_limit_exceeded",
            },
        )
    ]


def test_pdf_factory_uses_diagnostic_shared_client(monkeypatch) -> None:
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", "test-model")

    refiner = openai_pdf_structure_refiner_from_env(b"%PDF-test")

    assert refiner is not None
    assert refiner.client_factory is diagnostic_openai_client_factory
