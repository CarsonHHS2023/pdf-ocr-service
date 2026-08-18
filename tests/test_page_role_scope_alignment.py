from __future__ import annotations

import asyncio
import importlib
import json

from scripts.apply_page_role_scope_alignment import main as apply_fix

apply_fix()

from app.processing import batched_structure_refinement as batched
from app.processing import openai_batched_structure_refinement as openai_batched
from app.processing.llm_structure_refinement import PageRole
from app.processing.openai_structure_refinement_provider import (
    OpenAIResponsesStructureRefiner,
)
from app.processing.structured_result_v2.model import (
    ProcessingNode,
    ProcessingNodeKind,
    StructuredProcessingResultV2,
)
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind

openai_batched = importlib.reload(openai_batched)
OpenAIBatchedStructureRefiner = openai_batched.OpenAIBatchedStructureRefiner


def _spr() -> StructuredProcessingResultV2:
    units = tuple(
        SourceUnit(
            f"pdf-page:{index:06d}",
            SourceUnitKind.PHYSICAL_PAGE,
            index - 1,
            "pdf-source",
            dimensions=SourceUnitDimensions(612, 792),
        )
        for index in (1, 2)
    )
    nodes = tuple(
        ProcessingNode(
            f"paragraph-{index}",
            ProcessingNodeKind.PARAGRAPH,
            index - 1,
            (unit.source_unit_id,),
            text=f"Paragraph {index}",
        )
        for index, unit in enumerate(units, start=1)
    )
    return StructuredProcessingResultV2(
        document_ref="document-test",
        processing_run_ref="run-test",
        source_units=units,
        observations=(),
        nodes=nodes,
    )


class _Response:
    status_code = 200
    headers: dict[str, str] = {}

    def __init__(self, output_text: str) -> None:
        self._output_text = output_text

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {
            "id": "response-test",
            "model": "vision-model",
            "status": "completed",
            "output_text": self._output_text,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }


class _Client:
    def __init__(self) -> None:
        self.requested_page_role_ids: list[list[str]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        request_payload = kwargs["json"]
        serialized_request = request_payload["input"][0]["content"][0]["text"]
        request = json.loads(serialized_request)
        source_unit_ids = list(
            request["review_scope"]["page_role_review_source_unit_ids"]
        )
        self.requested_page_role_ids.append(source_unit_ids)
        page_reviews = [
            {
                "source_unit_id": source_unit_id,
                "page_role": "body",
                "confidence": 0.99,
                "reason_codes": ["test_scope_alignment"],
            }
            for source_unit_id in source_unit_ids
        ]
        return _Response(
            json.dumps(
                {"page_reviews": page_reviews, "operations": []},
                separators=(",", ":"),
            )
        )


def _refiner(client: _Client) -> OpenAIBatchedStructureRefiner:
    probe = OpenAIResponsesStructureRefiner(
        api_key="secret",
        model_id="vision-model",
    )
    return OpenAIBatchedStructureRefiner(
        probe=probe,
        batch_planner=lambda _spr: (
            {
                "pdf-page:000001": "data:image/jpeg;base64,AAAA",
                "pdf-page:000002": "data:image/jpeg;base64,BBBB",
            },
        ),
        max_concurrent_batches=1,
        batch_timeout_seconds=60,
        client_factory=lambda _timeout: client,
        event_sink=lambda _event, _fields: None,
    )


def test_pre_reviewed_boundaries_stay_absent_from_openai_request(monkeypatch) -> None:
    spr = _spr()
    assert openai_batched._document_boundary_positions(spr) == {
        "pdf-page:000001": "first_page",
        "pdf-page:000002": "last_page",
    }
    monkeypatch.setattr(batched, "_document_boundary_positions", lambda _spr: {})
    client = _Client()

    patch = asyncio.run(_refiner(client).propose_async(spr))

    assert client.requested_page_role_ids == [[]]
    assert patch.page_reviews == ()
    assert patch.operations == ()


def test_unfiltered_boundaries_remain_required_and_validate(monkeypatch) -> None:
    required = {
        "pdf-page:000001": "first_page",
        "pdf-page:000002": "last_page",
    }
    monkeypatch.setattr(
        batched,
        "_document_boundary_positions",
        lambda _spr: dict(required),
    )
    client = _Client()

    patch = asyncio.run(_refiner(client).propose_async(_spr()))

    assert client.requested_page_role_ids == [list(required)]
    assert tuple(review.source_unit_id for review in patch.page_reviews) == tuple(
        required
    )
    assert all(review.page_role is PageRole.BODY for review in patch.page_reviews)
    assert patch.operations == ()
