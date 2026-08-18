from __future__ import annotations

import json

import pytest

from app.processing.batched_structure_refinement import (
    BatchedStructureRefiner,
    RequiredHeadingReviewError,
)
from app.processing.llm_structure_refinement_provider import (
    StructureRefinementResponseError,
    parse_structure_refinement_response,
)
from app.processing.openai_structure_refinement_provider import (
    OpenAIResponsesStructureRefiner,
)
from app.processing.structured_result_v2.model import (
    ProcessingNode,
    ProcessingNodeKind,
    ProcessingNodeRecoveryState,
    StructuredProcessingResultV2,
)
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind


def _spr() -> StructuredProcessingResultV2:
    unit = SourceUnit(
        "pdf-page:000001",
        SourceUnitKind.PHYSICAL_PAGE,
        0,
        "source-pdf",
        dimensions=SourceUnitDimensions(600, 800),
    )
    return StructuredProcessingResultV2(
        document_ref="private-document-ref",
        processing_run_ref="private-processing-run",
        source_units=(unit,),
        observations=(),
        nodes=(
            ProcessingNode(
                "toc-item",
                ProcessingNodeKind.LIST_ITEM,
                0,
                (unit.source_unit_id,),
                text="一、私有目录文字.....1",
                metadata={"recovery_rule": "mineru_popo_toc_item"},
            ),
            ProcessingNode(
                "unknown-node",
                ProcessingNodeKind.UNKNOWN,
                1,
                (unit.source_unit_id,),
                text="私有背透文字",
                recovery_state=ProcessingNodeRecoveryState.DEGRADED,
            ),
            ProcessingNode(
                "heading-node",
                ProcessingNodeKind.HEADING,
                2,
                (unit.source_unit_id,),
                text="私有标题文字",
                heading_level=2,
            ),
        ),
    )


def _valid_response() -> dict[str, object]:
    return {
        "id": "resp_test",
        "model": "diagnostic-model",
        "status": "completed",
        "output_text": json.dumps({"operations": []}),
        "usage": {"input_tokens": 123, "output_tokens": 7},
    }


@pytest.mark.asyncio
async def test_request_preflight_reports_spr_shape_without_document_content() -> None:
    events: list[tuple[str, dict[str, object]]] = []

    async def post(_url, _headers, _payload, _timeout):
        return _valid_response()

    refiner = OpenAIResponsesStructureRefiner(
        api_key="secret-api-key",
        model_id="diagnostic-model",
        page_image_resolver=lambda _spr: {},
        async_http_post=post,
        event_sink=lambda event, fields: events.append((event, dict(fields))),
    )

    patch = await refiner.propose_async(_spr())

    assert patch.operations == ()
    preflight = next(
        fields
        for event, fields in events
        if event == "PDF_STRUCTURE_REFINEMENT_REQUEST_PREFLIGHT"
    )
    assert preflight["json_preflight_passed"] is True
    assert preflight["source_unit_count"] == 1
    assert preflight["observation_count"] == 0
    assert preflight["node_count"] == 3
    assert preflight["unknown_node_count"] == 1
    assert preflight["degraded_node_count"] == 1
    assert preflight["toc_item_count"] == 1
    assert preflight["heading_candidate_count"] == 1
    assert preflight["selected_page_count"] == 0
    assert preflight["serialized_request_bytes"] > 0
    assert "private-document-ref" not in repr(preflight)
    assert "私有背透文字" not in repr(preflight)
    assert "secret-api-key" not in repr(events)

    response = next(
        fields
        for event, fields in events
        if event == "PDF_STRUCTURE_REFINEMENT_RESPONSE_RECEIVED"
    )
    assert response["response_status"] == "completed"
    assert response["output_text_present"] is True
    assert response["input_tokens"] == 123
    assert response["output_tokens"] == 7


@pytest.mark.asyncio
async def test_non_finite_request_value_fails_preflight_before_http(monkeypatch) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    called = False

    async def post(_url, _headers, _payload, _timeout):
        nonlocal called
        called = True
        return _valid_response()

    monkeypatch.setattr(
        "app.processing.openai_structure_refinement_provider.build_structure_refinement_request",
        lambda _spr, **_kwargs: {"spr": {"non_finite": float("nan")}},
    )
    refiner = OpenAIResponsesStructureRefiner(
        api_key="secret",
        model_id="diagnostic-model",
        async_http_post=post,
        event_sink=lambda event, fields: events.append((event, dict(fields))),
    )

    with pytest.raises(ValueError):
        await refiner.propose_async(_spr())

    assert called is False
    failure = next(
        fields
        for event, fields in events
        if event == "PDF_STRUCTURE_REFINEMENT_REQUEST_PREFLIGHT_FAILED"
    )
    assert failure["error_stage"] == "request_json_preflight"
    assert failure["json_preflight_passed"] is False
    assert "private-document-ref" not in repr(failure)


@pytest.mark.asyncio
async def test_incomplete_response_records_output_text_extraction_stage() -> None:
    events: list[tuple[str, dict[str, object]]] = []

    async def post(_url, _headers, _payload, _timeout):
        return {
            "id": "resp_incomplete",
            "model": "diagnostic-model",
            "status": "incomplete",
            "output": [],
            "incomplete_details": {"reason": "max_output_tokens"},
            "usage": {"input_tokens": 999, "output_tokens": 200},
        }

    refiner = OpenAIResponsesStructureRefiner(
        api_key="secret",
        model_id="diagnostic-model",
        async_http_post=post,
        event_sink=lambda event, fields: events.append((event, dict(fields))),
    )

    with pytest.raises(ValueError, match="did not contain output text"):
        await refiner.propose_async(_spr())

    response = next(
        fields
        for event, fields in events
        if event == "PDF_STRUCTURE_REFINEMENT_RESPONSE_RECEIVED"
    )
    assert response["response_status"] == "incomplete"
    assert response["incomplete_reason"] == "max_output_tokens"
    assert response["output_text_present"] is False

    failure = next(
        fields
        for event, fields in events
        if event == "PDF_STRUCTURE_REFINEMENT_RESPONSE_PARSE_FAILED"
    )
    assert failure["error_stage"] == "output_text_extraction"
    assert failure["error_type"] == "ValueError"


def _invalid_toc_operation_response() -> dict[str, object]:
    return {
        "operations": [
            {
                "op": "set_toc_level",
                "node_id": "toc-item",
                "confidence": 0.95,
                "reason_codes": ["layout_hierarchy"],
                "target_kind": None,
                "heading_level": None,
                "toc_level": None,
                "parent_id": None,
                "original_text": None,
                "corrected_text": None,
                "warning": None,
            }
        ]
    }


def test_operation_semantic_error_identifies_index_kind_and_null_fields() -> None:
    with pytest.raises(StructureRefinementResponseError) as raised:
        parse_structure_refinement_response(
            _invalid_toc_operation_response(),
            model_id="diagnostic-model",
        )

    exc = raised.value
    assert exc.stage == "operation_semantics"
    assert exc.operation_index == 0
    assert exc.operation_kind == "set_toc_level"
    assert "toc_level" in exc.null_fields
    assert str(exc) == "set_toc_level requires a positive integer toc_level"


@pytest.mark.asyncio
async def test_batch_failure_carries_bounded_operation_diagnostics() -> None:
    events: list[tuple[str, dict[str, object]]] = []

    async def post(_url, _headers, _payload, _timeout):
        return {"output_text": json.dumps(_invalid_toc_operation_response())}

    def factory(_images):
        return OpenAIResponsesStructureRefiner(
            api_key="secret",
            model_id="diagnostic-model",
            async_http_post=post,
            event_sink=lambda event, fields: events.append((event, dict(fields))),
        )

    refiner = BatchedStructureRefiner(
        model_id="diagnostic-model",
        batch_planner=lambda _spr: ({"pdf-page:000001": "data:image/jpeg;base64,AA=="},),
        refiner_factory=factory,
        max_concurrent_batches=1,
        batch_timeout_seconds=10,
        event_sink=lambda event, fields: events.append((event, dict(fields))),
    )

    with pytest.raises(RequiredHeadingReviewError, match="batch failed"):
        await refiner.propose_async(_spr())

    failed = next(
        fields
        for event, fields in events
        if event == "PDF_STRUCTURE_REFINEMENT_BATCH_FAILED"
    )
    assert failed["error_type"] == "StructureRefinementResponseError"
    assert failed["error_stage"] == "operation_semantics"
    assert failed["operation_index"] == 0
    assert failed["operation_kind"] == "set_toc_level"
    assert "toc_level" in failed["null_fields"]
    assert failed["required_heading_review"] is True

    parse_failed = next(
        fields
        for event, fields in events
        if event == "PDF_STRUCTURE_REFINEMENT_RESPONSE_PARSE_FAILED"
    )
    assert parse_failed["error_stage"] == "operation_semantics"
    assert parse_failed["error_summary"] == (
        "set_toc_level requires a positive integer toc_level"
    )
