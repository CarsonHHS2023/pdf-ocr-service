from __future__ import annotations

import asyncio
import json

import fitz  # type: ignore[import]
import httpx

from app.processing.normalized_observations import NormalizedObservationBundle
from app.processing.openai_batched_structure_refinement import OpenAIBatchedStructureRefiner
from app.processing.openai_structure_refinement_provider import OpenAIResponsesStructureRefiner
from app.processing.pdf_recovery import recover_pdf_observations_to_spr_v2
from app.processing.pdf_structure_refinement_images import (
    PdfPageImageBatchPlanner,
    PdfPageImagePolicy,
)
from app.processing.structured_result_v2.model import (
    ProcessingEvidence,
    ProcessingNodeKind,
    ProcessingObservation,
    normalize_spr_v2,
)
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind, SpatialAnchor


def _real_two_page_pdf() -> bytes:
    document = fitz.open()
    try:
        first = document.new_page(width=600, height=800)
        first.insert_text((72, 72), "STOP", fontsize=22)
        first.insert_text((72, 140), "Contents", fontsize=18)
        first.insert_text((90, 180), "1. Background ........ 2", fontsize=12)
        first.insert_text((72, 250), "B0DY", fontsize=12)
        second = document.new_page(width=600, height=800)
        second.insert_text((72, 72), "Background", fontsize=22)
        second.insert_text((72, 120), "Body on page two.", fontsize=12)
        return document.tobytes()
    finally:
        document.close()


def _unit(page: int) -> SourceUnit:
    return SourceUnit(
        source_unit_id=f"pdf-page:{page:06d}",
        kind=SourceUnitKind.PHYSICAL_PAGE,
        source_order=page - 1,
        source_ref="source-pdf",
        dimensions=SourceUnitDimensions(600, 800),
    )


def _observation(
    page: int,
    order: int,
    observed_kind: str,
    text: str,
    *,
    confidence: float = 0.9,
) -> tuple[ProcessingObservation, ProcessingEvidence]:
    unit_id = f"pdf-page:{page:06d}"
    observation_id = f"obs-{page}-{order}"
    evidence_id = f"ev-{page}-{order}"
    top = 0.08 + order * 0.12
    anchor = SpatialAnchor(unit_id, 0.1, top, 0.9, top + 0.08)
    observation = ProcessingObservation(
        observation_id=observation_id,
        source_unit_id=unit_id,
        order=order,
        observed_kind=observed_kind,
        text=text,
        anchors=(anchor,),
        confidence=confidence,
        evidence_ids=(evidence_id,),
    )
    evidence = ProcessingEvidence(
        evidence_id=evidence_id,
        source_unit_id=unit_id,
        anchors=(anchor,),
        observation_id=observation_id,
        processing_run_ref="run-acceptance",
        raw_result_ref="raw-acceptance",
        provider_ref="provider-normalized",
    )
    return observation, evidence


def _bundle() -> NormalizedObservationBundle:
    pairs = (
        _observation(1, 0, "paragraph_title", "STOP"),
        _observation(1, 1, "toc", "1. Background ........ 2"),
        _observation(1, 2, "text", "B0DY", confidence=0.2),
        _observation(2, 0, "paragraph_title", "Background"),
        _observation(2, 1, "text", "Body on page two."),
    )
    return NormalizedObservationBundle(
        document_ref="doc-acceptance",
        source_ref="source-pdf",
        processing_run_ref="run-acceptance",
        raw_result_ref="raw-acceptance",
        source_units=(_unit(1), _unit(2)),
        observations=tuple(item for item, _ in pairs),
        evidence=tuple(item for _, item in pairs),
    )


class _Response:
    status_code = 200
    headers: dict[str, str] = {}

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _PartiallyFailingClient:
    def __init__(self, response_payload: dict[str, object]) -> None:
        self.response_payload = response_payload
        self.post_count = 0
        self.image_inputs: list[str] = []
        self.exit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_count += 1

    async def post(self, url, *, headers, json, timeout):
        self.post_count += 1
        for item in json["input"][0]["content"]:
            if item.get("type") == "input_image":
                self.image_inputs.append(item["image_url"])
        await asyncio.sleep(0)
        if self.post_count == 2:
            raise httpx.ConnectError(
                "simulated second-page provider outage",
                request=httpx.Request("POST", url),
            )
        return _Response(self.response_payload)


def test_real_pdf_refinement_applies_successful_batch_and_fails_open() -> None:
    bundle = _bundle()
    baseline = recover_pdf_observations_to_spr_v2(bundle)
    false_heading = next(node for node in baseline.nodes if node.text == "STOP")
    toc_item = next(
        node
        for node in baseline.nodes
        if node.kind is ProcessingNodeKind.LIST_ITEM and node.text == "1. Background ........ 2"
    )
    low_confidence_text = next(node for node in baseline.nodes if node.text == "B0DY")

    provider_output = {
        "operations": [
            {
                "op": "reclassify_node",
                "node_id": false_heading.node_id,
                "confidence": 0.99,
                "reason_codes": ["embedded_visual_text"],
                "target_kind": "caption",
                "heading_level": None,
                "toc_level": None,
                "parent_id": None,
                "original_text": None,
                "corrected_text": None,
                "warning": None,
            },
            {
                "op": "set_toc_level",
                "node_id": toc_item.node_id,
                "confidence": 0.99,
                "reason_codes": ["toc_context", "layout_hierarchy"],
                "target_kind": None,
                "heading_level": None,
                "toc_level": 1,
                "parent_id": None,
                "original_text": None,
                "corrected_text": None,
                "warning": None,
            },
            {
                "op": "correct_text",
                "node_id": low_confidence_text.node_id,
                "confidence": 0.99,
                "reason_codes": ["clear_visual_character_evidence"],
                "target_kind": None,
                "heading_level": None,
                "toc_level": None,
                "parent_id": None,
                "original_text": "B0DY",
                "corrected_text": "BODY",
                "warning": None,
            },
        ]
    }
    client = _PartiallyFailingClient(
        {"output_text": json.dumps(provider_output)}
    )
    events: list[tuple[str, dict[str, object]]] = []
    probe = OpenAIResponsesStructureRefiner(
        api_key="secret",
        model_id="vision-model",
        max_attempts=1,
        event_sink=lambda event, fields: events.append((event, dict(fields))),
    )
    refiner = OpenAIBatchedStructureRefiner(
        probe=probe,
        batch_planner=PdfPageImageBatchPlanner(
            _real_two_page_pdf(),
            policy=PdfPageImagePolicy(max_pages=1, max_dimension_pixels=1000),
        ),
        max_concurrent_batches=1,
        batch_timeout_seconds=30,
        client_factory=lambda _timeout: client,
    )

    refined = recover_pdf_observations_to_spr_v2(
        bundle,
        structure_refiner=refiner,
        refinement_fail_closed=False,
    )

    refined_false_heading = next(node for node in refined.nodes if node.node_id == false_heading.node_id)
    refined_toc_item = next(node for node in refined.nodes if node.node_id == toc_item.node_id)
    refined_text = next(node for node in refined.nodes if node.node_id == low_confidence_text.node_id)

    assert refined_false_heading.kind is ProcessingNodeKind.CAPTION
    assert refined_false_heading.heading_level is None
    assert refined_toc_item.kind is ProcessingNodeKind.LIST_ITEM
    assert refined_toc_item.metadata["toc_level"] == 1
    assert refined_text.text == "BODY"
    assert refined_text.metadata["ocr_text_corrections"][0]["original_text"] == "B0DY"
    assert client.post_count == 2
    assert client.exit_count == 1
    assert len(client.image_inputs) == 2
    assert all(value.startswith("data:image/jpeg;base64,") for value in client.image_inputs)

    metrics = next(fields for event, fields in events if event == "PDF_STRUCTURE_REFINEMENT_DOCUMENT_METRICS")
    assert metrics["outcome"] == "succeeded"
    assert metrics["batch_count"] == 2
    assert metrics["successful_batch_count"] == 1
    assert metrics["failed_batch_count"] == 1
    assert metrics["provider_unavailable_count"] == 1
    assert metrics["operation_count"] == 3

    normalized = normalize_spr_v2(refined)
    assert normalized["schema_id"] == refined.schema_id
    assert "doc-acceptance" not in str(metrics)
    assert "B0DY" not in str(metrics)
