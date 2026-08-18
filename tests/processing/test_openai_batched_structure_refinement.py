from __future__ import annotations

import asyncio
import json

from app.processing.llm_structure_refinement import (
    DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION,
)
from app.processing.openai_batched_structure_refinement import OpenAIBatchedStructureRefiner
from app.processing.openai_structure_refinement_provider import (
    OpenAIResponsesStructureRefiner,
    StructureRefinementProviderError,
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
    node = ProcessingNode(
        "node-1",
        ProcessingNodeKind.PARAGRAPH,
        0,
        (unit.source_unit_id,),
        text="Heading",
    )
    return StructuredProcessingResultV2(
        document_ref="doc-1",
        processing_run_ref="run-1",
        source_units=(unit,),
        observations=(),
        nodes=(node,),
    )


class _Response:
    status_code = 200
    headers = {}

    def __init__(self, output_text: str) -> None:
        self._output_text = output_text

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"output_text": self._output_text}


class _Client:
    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.post_count = 0
        self.enter_count = 0
        self.exit_count = 0
        self.failures = list(failures or [])

    async def __aenter__(self):
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_count += 1

    async def post(self, *args, **kwargs):
        self.post_count += 1
        await asyncio.sleep(0)
        if self.failures:
            raise self.failures.pop(0)
        request_payload = kwargs["json"]
        serialized_request = request_payload["input"][0]["content"][0]["text"]
        request = json.loads(serialized_request)
        source_unit_ids = request["review_scope"]["page_role_review_source_unit_ids"]
        page_reviews = [
            {
                "source_unit_id": source_unit_id,
                "page_role": "unknown",
                "confidence": 0.5,
                "reason_codes": ["test_fixture"],
            }
            for source_unit_id in source_unit_ids
        ]
        return _Response(json.dumps({"page_reviews": page_reviews, "operations": []}))


def _summary(events: list[tuple[str, dict[str, object]]]) -> dict[str, object]:
    summaries = [
        fields
        for event, fields in events
        if event == "PDF_STRUCTURE_REFINEMENT_DOCUMENT_METRICS"
    ]
    assert len(summaries) == 1
    return summaries[0]


def test_one_client_is_reused_and_success_metrics_are_emitted() -> None:
    client = _Client()
    factory_calls = []
    events: list[tuple[str, dict[str, object]]] = []

    def client_factory(timeout_seconds):
        factory_calls.append(timeout_seconds)
        return client

    probe = OpenAIResponsesStructureRefiner(
        api_key="secret",
        model_id="vision-model",
    )
    refiner = OpenAIBatchedStructureRefiner(
        probe=probe,
        batch_planner=lambda _spr: (
            {"pdf-page:000001": "data:image/jpeg;base64,AAAA"},
            {"pdf-page:000002": "data:image/jpeg;base64,BBBB"},
        ),
        max_concurrent_batches=2,
        batch_timeout_seconds=60,
        client_factory=client_factory,
        event_sink=lambda event, fields: events.append((event, dict(fields))),
    )

    patch = asyncio.run(refiner.propose_async(_spr()))

    assert patch.operations == ()
    assert len(patch.page_reviews) == 1
    assert patch.prompt_version == DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION
    assert factory_calls == [60.0]
    assert client.enter_count == 1
    assert client.post_count == 2
    assert client.exit_count == 1

    summary = _summary(events)
    assert summary["provider"] == "openai"
    assert summary["model_id"] == "vision-model"
    assert summary["prompt_version"] == DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION
    assert summary["outcome"] == "succeeded"
    assert summary["batch_count"] == 2
    assert summary["page_count"] == 2
    assert summary["successful_batch_count"] == 2
    assert summary["failed_batch_count"] == 0
    assert summary["operation_count"] == 0
    assert summary["page_role_review_count"] == 1
    assert summary["provider_failure_count"] == 0
    assert summary["retry_count"] == 0
    assert summary["error_type"] is None
    assert isinstance(summary["duration_ms"], int)
    assert "doc-1" not in str(summary)
    assert "Heading" not in str(summary)


def test_explicit_custom_prompt_version_is_preserved() -> None:
    client = _Client()
    events: list[tuple[str, dict[str, object]]] = []
    probe = OpenAIResponsesStructureRefiner(
        api_key="secret",
        model_id="vision-model",
        prompt_version="custom-refinement-experiment",
    )
    refiner = OpenAIBatchedStructureRefiner(
        probe=probe,
        batch_planner=lambda _spr: (
            {"pdf-page:000001": "data:image/jpeg;base64,AAAA"},
        ),
        max_concurrent_batches=1,
        batch_timeout_seconds=60,
        client_factory=lambda _timeout: client,
        event_sink=lambda event, fields: events.append((event, dict(fields))),
    )

    patch = asyncio.run(refiner.propose_async(_spr()))

    assert patch.prompt_version == "custom-refinement-experiment"
    assert _summary(events)["prompt_version"] == "custom-refinement-experiment"


def test_retry_and_rate_limit_metrics_are_aggregated_without_sensitive_content() -> None:
    client = _Client([
        StructureRefinementProviderError(
            "secret response body and Heading text",
            retryable=True,
            status_code=429,
        )
    ])
    batch_events: list[tuple[str, dict[str, object]]] = []
    provider_events: list[tuple[str, dict[str, object]]] = []
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    probe = OpenAIResponsesStructureRefiner(
        api_key="secret",
        model_id="vision-model",
        max_attempts=2,
        initial_backoff_seconds=0.25,
        sleep=sleep,
        event_sink=lambda event, fields: provider_events.append((event, dict(fields))),
    )
    refiner = OpenAIBatchedStructureRefiner(
        probe=probe,
        batch_planner=lambda _spr: (
            {"pdf-page:000001": "data:image/jpeg;base64,AAAA"},
        ),
        max_concurrent_batches=1,
        batch_timeout_seconds=60,
        client_factory=lambda _timeout: client,
        event_sink=lambda event, fields: batch_events.append((event, dict(fields))),
    )

    patch = asyncio.run(refiner.propose_async(_spr()))

    assert patch.operations == ()
    assert len(patch.page_reviews) == 1
    assert client.post_count == 2
    assert delays == [0.25]
    assert [event for event, _ in provider_events].count(
        "PDF_STRUCTURE_REFINEMENT_PROVIDER_FAILURE"
    ) == 1

    summary = _summary(batch_events)
    assert summary["outcome"] == "succeeded"
    assert summary["provider_failure_count"] == 1
    assert summary["retry_count"] == 1
    assert summary["rate_limit_count"] == 1
    assert summary["server_error_count"] == 0
    assert summary["provider_unavailable_count"] == 0
    assert "secret response body" not in str(batch_events)
    assert "Heading" not in str(batch_events)
