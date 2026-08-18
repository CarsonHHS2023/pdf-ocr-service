from __future__ import annotations

import asyncio
import json

import pytest

from app.processing.openai_structure_refinement_provider import (
    OpenAIResponsesStructureRefiner,
    StructureRefinementProviderError,
    openai_structure_refiner_from_env,
)
from app.processing.structured_result_v2.model import (
    ProcessingNode,
    ProcessingNodeKind,
    StructuredProcessingResultV2,
)
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind


def _spr() -> StructuredProcessingResultV2:
    unit = SourceUnit(
        "pdf-page:000001",
        SourceUnitKind.PHYSICAL_PAGE,
        0,
        "pdf-source",
        dimensions=SourceUnitDimensions(888, 1226),
    )
    heading = ProcessingNode(
        "node-stop",
        ProcessingNodeKind.HEADING,
        0,
        (unit.source_unit_id,),
        text="STOP",
        heading_level=2,
        metadata={"recovery_rule": "mineru_popo_heading"},
    )
    return StructuredProcessingResultV2(
        document_ref="doc-1",
        processing_run_ref="run-1",
        source_units=(unit,),
        observations=(),
        nodes=(heading,),
    )


def test_multimodal_request_uses_strict_schema_and_page_data_url() -> None:
    captured = {}

    def http_post(url, headers, payload, timeout):
        captured.update(url=url, headers=headers, payload=payload, timeout=timeout)
        return {
            "output_text": json.dumps({
                "operations": [{
                    "op": "reclassify_node",
                    "node_id": "node-stop",
                    "confidence": 0.98,
                    "reason_codes": ["embedded_visual_text"],
                    "target_kind": "figure",
                    "heading_level": None,
                    "toc_level": None,
                    "parent_id": None,
                    "warning": None,
                }]
            })
        }

    refiner = OpenAIResponsesStructureRefiner(
        api_key="secret",
        model_id="vision-model",
        page_image_resolver=lambda spr: {
            "pdf-page:000001": "data:image/png;base64,AAAA"
        },
        http_post=http_post,
    )
    patch = refiner.propose(_spr())

    assert patch.operations[0].target_kind is ProcessingNodeKind.FIGURE
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["payload"]["text"]["format"]["type"] == "json_schema"
    assert captured["payload"]["text"]["format"]["strict"] is True
    content = captured["payload"]["input"][0]["content"]
    assert any(item.get("type") == "input_image" for item in content)
    assert any(item.get("image_url") == "data:image/png;base64,AAAA" for item in content)


def test_async_http_adapter_is_awaited_without_blocking_adapter_thread() -> None:
    called_on_task = False

    async def async_http_post(url, headers, payload, timeout):
        nonlocal called_on_task
        called_on_task = asyncio.current_task() is not None
        await asyncio.sleep(0)
        return {"output_text": '{"operations": []}'}

    refiner = OpenAIResponsesStructureRefiner(
        api_key="secret",
        model_id="vision-model",
        async_http_post=async_http_post,
    )

    patch = asyncio.run(refiner.propose_async(_spr()))

    assert patch.operations == ()
    assert called_on_task is True


def test_extracts_output_text_from_response_message_content() -> None:
    def http_post(url, headers, payload, timeout):
        return {
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": '{"operations": []}',
                }],
            }]
        }

    patch = OpenAIResponsesStructureRefiner(
        api_key="secret",
        model_id="vision-model",
        http_post=http_post,
    ).propose(_spr())
    assert patch.operations == ()


def test_rejects_non_data_url_page_images() -> None:
    refiner = OpenAIResponsesStructureRefiner(
        api_key="secret",
        model_id="vision-model",
        page_image_resolver=lambda spr: {"pdf-page:000001": "https://example.com/page.png"},
        http_post=lambda *args: {"output_text": '{"operations": []}'},
    )
    with pytest.raises(ValueError, match="data URLs"):
        refiner.propose(_spr())


def test_env_factory_is_disabled_without_configuration(monkeypatch) -> None:
    monkeypatch.delenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", raising=False)
    assert openai_structure_refiner_from_env() is None


def test_env_factory_requires_key_and_model_together(monkeypatch) -> None:
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "secret")
    monkeypatch.delenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", raising=False)
    with pytest.raises(ValueError, match="both PDF_STRUCTURE_REFINEMENT"):
        openai_structure_refiner_from_env()


def test_endpoint_must_use_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        OpenAIResponsesStructureRefiner(
            api_key="secret",
            model_id="vision-model",
            endpoint="http://localhost/v1/responses",
        )


def test_retryable_provider_failure_retries_then_succeeds_without_sensitive_events() -> None:
    attempts = 0
    delays: list[float] = []
    events: list[tuple[str, dict[str, object]]] = []

    async def async_http_post(url, headers, payload, timeout):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise StructureRefinementProviderError(
                "secret provider body and STOP text",
                retryable=True,
                status_code=429,
            )
        return {"output_text": '{"operations": []}'}

    async def sleep(delay: float) -> None:
        delays.append(delay)

    refiner = OpenAIResponsesStructureRefiner(
        api_key="secret",
        model_id="vision-model",
        async_http_post=async_http_post,
        max_attempts=3,
        initial_backoff_seconds=0.25,
        max_backoff_seconds=2.0,
        sleep=sleep,
        event_sink=lambda event, fields: events.append((event, dict(fields))),
    )

    patch = asyncio.run(refiner.propose_async(_spr()))

    assert patch.operations == ()
    assert attempts == 3
    assert delays == [0.25, 0.5]
    assert [event for event, _ in events].count(
        "PDF_STRUCTURE_REFINEMENT_PROVIDER_RETRY_SCHEDULED"
    ) == 2
    assert "secret provider body" not in str(events)
    assert "STOP" not in str(events)


def test_non_retryable_provider_failure_fails_immediately() -> None:
    attempts = 0
    delays: list[float] = []

    async def async_http_post(url, headers, payload, timeout):
        nonlocal attempts
        attempts += 1
        raise StructureRefinementProviderError(
            "invalid request",
            retryable=False,
            status_code=400,
        )

    async def sleep(delay: float) -> None:
        delays.append(delay)

    refiner = OpenAIResponsesStructureRefiner(
        api_key="secret",
        model_id="vision-model",
        async_http_post=async_http_post,
        sleep=sleep,
    )

    with pytest.raises(StructureRefinementProviderError):
        asyncio.run(refiner.propose_async(_spr()))

    assert attempts == 1
    assert delays == []


def test_retry_after_is_honored_and_capped_by_max_backoff() -> None:
    attempts = 0
    delays: list[float] = []

    async def async_http_post(url, headers, payload, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise StructureRefinementProviderError(
                "rate limited",
                retryable=True,
                status_code=429,
                retry_after_seconds=30.0,
            )
        return {"output_text": '{"operations": []}'}

    async def sleep(delay: float) -> None:
        delays.append(delay)

    refiner = OpenAIResponsesStructureRefiner(
        api_key="secret",
        model_id="vision-model",
        async_http_post=async_http_post,
        max_attempts=2,
        initial_backoff_seconds=0.5,
        max_backoff_seconds=4.0,
        sleep=sleep,
    )

    asyncio.run(refiner.propose_async(_spr()))

    assert attempts == 2
    assert delays == [4.0]


def test_retry_configuration_is_loaded_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "secret")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", "vision-model")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_INITIAL_BACKOFF_SECONDS", "0.75")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_BACKOFF_SECONDS", "6")

    refiner = openai_structure_refiner_from_env()

    assert refiner is not None
    assert refiner.max_attempts == 5
    assert refiner.initial_backoff_seconds == 0.75
    assert refiner.max_backoff_seconds == 6.0
