from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.processing.structured_result import StructuredProcessingResult
from app.structured_content.enums import ContentNodeType
from app.structured_content.serialization import serialize_structured_content_candidate
from app.structured_content.transformation import CandidateIdentityInput, DEFAULT_TRANSFORMATION_POLICY, InvalidStructuredProcessingResult, TransformationContext, TransformationInvariantViolation, TransformationNotImplemented, transform_spr_to_candidate
from app.structured_content.validation import validate_content_candidate

FIXTURE_ROOT = Path("tests/fixtures/processing/structured_processing_result_v1/expected")


def load_data(name: str = "no_geometry.spr.json") -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text())


def spr_from(data: dict) -> StructuredProcessingResult:
    return StructuredProcessingResult(copy.deepcopy(data))


def ctx(candidate_id: str = "candidate-core", seed: str = "lineage-core") -> TransformationContext:
    return TransformationContext("doc-core", CandidateIdentityInput(candidate_id, seed), processing_run_ref="run-core", source_file_ref="source-core")


def transform(data: dict):
    return transform_spr_to_candidate(spr_from(data), context=ctx())


def only_core(data: dict) -> dict:
    data = copy.deepcopy(data)
    for node in data["nodes"]:
        if node.get("node_type") == "footer":
            node["node_type"] = "paragraph"
    for observation in data["normalized_observations"]:
        if observation.get("observation_type") == "footer":
            observation["observation_type"] = "text"
    supported = {"title", "heading", "paragraph", "text"}
    node_ids = {n["node_id"] for n in data["nodes"] if n["node_type"] in supported}
    obs_ids = {oid for n in data["nodes"] if n["node_id"] in node_ids for oid in n.get("observation_ids", [])}
    ev_ids = {eid for n in data["nodes"] if n["node_id"] in node_ids for eid in n.get("evidence_link_ids", [])}
    data["nodes"] = [n for n in data["nodes"] if n["node_id"] in node_ids]
    data["normalized_observations"] = [o for o in data["normalized_observations"] if o["observation_id"] in obs_ids]
    data["evidence_links"] = [e for e in data["evidence_links"] if e["evidence_link_id"] in ev_ids]
    for p in data["pages"]:
        p["root_node_ids"] = [nid for nid in p["root_node_ids"] if nid in node_ids]
    data["warnings"] = []
    data["quality_summary"]["warning_counts"] = {}
    return data


def test_one_page_title_and_paragraph_maps_to_validator_clean_candidate() -> None:
    candidate = transform(load_data("complete_single_page_text.spr.json"))
    assert candidate.candidate_id.value == "candidate-core"
    assert candidate.processing_run_ref.value == "run-core"
    assert [p.source_page_index for p in candidate.pages] == [0]
    assert [n.node_type for n in candidate.nodes] == [ContentNodeType.HEADING, ContentNodeType.PARAGRAPH]
    assert validate_content_candidate(candidate).is_valid


def test_heading_paragraph_multipage_order_geometry_and_evidence_are_deterministic() -> None:
    candidate = transform(only_core(load_data("complete_multipage_mixed.spr.json")))
    assert [p.source_page_index for p in candidate.pages] == [0, 1]
    assert [n.text for n in candidate.nodes] == ["Synthetic report", "Synthetic paragraph.", "Synthetic footer"]
    assert candidate.nodes[0].source_locations[0].bounding_box is not None
    assert candidate.evidence[0].structured_processing_result_ref.value == "spr_complete_multipage_mixed"
    assert "payload" not in json.dumps(candidate.evidence[0].extensions)


def test_repeated_transformation_is_dataclass_and_canonical_byte_identical() -> None:
    data = only_core(load_data("complete_multipage_mixed.spr.json"))
    first = transform_spr_to_candidate(spr_from(data), context=ctx(), policy=DEFAULT_TRANSFORMATION_POLICY)
    second = transform_spr_to_candidate(spr_from(data), context=ctx(), policy=DEFAULT_TRANSFORMATION_POLICY)
    assert first == second
    assert serialize_structured_content_candidate(first) == serialize_structured_content_candidate(second)
    assert [p.root_node_ids for p in first.pages] == [p.root_node_ids for p in second.pages]
    assert [n.lineage_key for n in first.nodes] == [n.lineage_key for n in second.nodes]


def test_different_candidate_context_separates_candidate_page_and_node_identities() -> None:
    data = load_data("no_geometry.spr.json")
    a = transform_spr_to_candidate(spr_from(data), context=ctx("candidate-a", "lineage-a"))
    b = transform_spr_to_candidate(spr_from(data), context=ctx("candidate-b", "lineage-b"))
    assert a.candidate_id != b.candidate_id
    assert {p.page_id for p in a.pages}.isdisjoint({p.page_id for p in b.pages})
    assert {n.node_id for n in a.nodes}.isdisjoint({n.node_id for n in b.nodes})


def test_text_normalization_is_conservative() -> None:
    data = load_data("complete_single_page_text.spr.json")
    data["nodes"][1]["text"] = "Cafe\u0301\r\nkeeps   spaces"
    data["normalized_observations"][1]["content"]["text"] = data["nodes"][1]["text"]
    candidate = transform(data)
    assert candidate.nodes[1].text == "Café\nkeeps   spaces"


def test_unsupported_control_text_fails_boundedly() -> None:
    data = load_data("complete_single_page_text.spr.json")
    data["nodes"][1]["text"] = "bad\x00text"
    data["normalized_observations"][1]["content"]["text"] = "bad\x00text"
    with pytest.raises(TransformationInvariantViolation):
        transform(data)


@pytest.mark.parametrize("node_type", ["table_cell", "diagram", "rendered_table_image", "image_crop"])
def test_unsupported_later_slice_kinds_fail_boundedly(node_type: str) -> None:
    data = load_data("complete_single_page_text.spr.json")
    data["nodes"][1]["node_type"] = node_type
    data["normalized_observations"][1]["observation_type"] = node_type
    before = copy.deepcopy(data)
    with pytest.raises(TransformationNotImplemented):
        transform(data)
    assert data == before


def test_missing_optional_order_falls_back_deterministically() -> None:
    data = load_data("no_geometry.spr.json")
    for node in data["nodes"]:
        node.pop("ordinal", None)
    first = transform(data)
    second = transform(data)
    assert [n.node_id for n in first.nodes] == [n.node_id for n in second.nodes]


def test_invalid_geometry_boundary_is_bounded() -> None:
    spr = object.__new__(StructuredProcessingResult)
    data = load_data("no_geometry.spr.json")
    data["nodes"][0]["geometry"] = {"normalized_bbox": [0, 0, 2, 1]}
    object.__setattr__(spr, "data", data)
    with pytest.raises(InvalidStructuredProcessingResult):
        transform_spr_to_candidate(spr, context=ctx())
