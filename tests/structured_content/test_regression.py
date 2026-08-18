from __future__ import annotations

import hashlib, json, re
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from app.structured_content.identity import ContentNodeId, DocumentRef
from app.structured_content.model import ContentNode, ContentPage, HeadingAttributes, SCHEMA_ID, SCHEMA_VERSION
from app.structured_content.serialization import serialize_structured_content_candidate, to_canonical_dict
from app.structured_content.validation import ContentValidationIssue, validate_content_candidate, validation_result_to_canonical_dict
from tests.structured_content.candidate_factory import make_asset_evidence_warning_candidate, make_deep_hierarchy, make_linear_candidate, make_table_candidate, permute_registries
from tests.structured_content.fixture_loader import candidate_from_dict, load_candidate, load_expected_canonical, load_expected_validation, load_json, load_manifest

BASE = Path("tests/fixtures/structured_content/v1")
FORBIDDEN_KEYS = {"accepted","current","is_current","selected","selected_version","reader","projection","provider_payload","paddle","mineru","sqlalchemy","session","database_id","orm_state"}
UNSAFE_RE = re.compile(rb"0x[0-9a-fA-F]+|<[^>]+ object at |\bNaN\b|\bInfinity\b")


def _fixture_cases():
    return load_manifest(BASE)["cases"]


def _result_dict(candidate):
    return validation_result_to_canonical_dict(validate_content_candidate(candidate))


def _assert_safe_serialization(payload: bytes):
    assert payload.endswith(b"\n") and not payload.endswith(b"\n\n")
    assert payload.count(b"\n") == 1
    assert not UNSAFE_RE.search(payload)
    data = json.loads(payload.decode("utf-8"))
    assert data["schema_id"] == SCHEMA_ID and data["schema_version"] == SCHEMA_VERSION
    def walk(obj):
        if isinstance(obj, dict):
            assert not (set(obj) & FORBIDDEN_KEYS)
            for value in obj.values(): walk(value)
        elif isinstance(obj, list):
            for value in obj: walk(value)
    walk(data)


@pytest.mark.parametrize("case", _fixture_cases(), ids=lambda c: c["name"])
def test_fixture_suite_reloads_validates_serializes_without_mutation(case):
    candidate_path = BASE / case["candidate_path"]
    before_bytes = candidate_path.read_bytes()
    source = load_json(candidate_path)
    source_snapshot = deepcopy(source)
    loaded_a = candidate_from_dict(source)
    loaded_b = candidate_from_dict(source)
    assert loaded_a == loaded_b
    assert source == source_snapshot
    assert candidate_path.read_bytes() == before_bytes
    assert _result_dict(loaded_a) == _result_dict(loaded_b)
    if case["expected_validity"] == "valid":
        canonical_path = BASE / case["canonical_path"]
        expected = load_expected_canonical(canonical_path)
        assert json.loads(serialize_structured_content_candidate(loaded_a)) == expected
        assert serialize_structured_content_candidate(loaded_a) == serialize_structured_content_candidate(loaded_b)
        assert canonical_path.read_bytes() == canonical_path.read_bytes()
    else:
        expected = load_expected_validation(BASE / case["validation_path"])
        assert _result_dict(loaded_a) == expected


def test_canonical_registry_permutation_invariance():
    candidate = make_asset_evidence_warning_candidate()
    assert validate_content_candidate(candidate).is_valid
    assert serialize_structured_content_candidate(candidate) == serialize_structured_content_candidate(permute_registries(candidate))


def test_semantic_ordering_changes_canonical_output():
    table = make_table_candidate()
    swapped = make_table_candidate(swap_rows=True)
    assert validate_content_candidate(table).is_valid
    assert serialize_structured_content_candidate(table) != serialize_structured_content_candidate(swapped)


def test_mapping_key_invariance_and_no_mutation():
    left = make_linear_candidate(1, 2, extensions={"org.atlas.z": {"b": 2, "a": 1}, "org.atlas.a": "x"})
    right = replace(left, extensions={"org.atlas.a": "x", "org.atlas.z": {"a": 1, "b": 2}})
    snapshot = deepcopy(left.extensions)
    assert serialize_structured_content_candidate(left) == serialize_structured_content_candidate(right)
    assert _result_dict(left) == _result_dict(right)
    assert left.extensions == snapshot


def test_unicode_normalization_is_deterministic_and_utf8_preserving():
    nfc = make_linear_candidate(1, 1, extensions={"org.atlas.café": "Résumé"})
    decomp = make_linear_candidate(1, 1, extensions={"org.atlas.cafe\u0301": "Re\u0301sume\u0301"})
    nfc = replace(nfc, nodes=(replace(nfc.nodes[0], text="Café"),))
    decomp = replace(decomp, nodes=(replace(decomp.nodes[0], text="Cafe\u0301"),))
    payload = serialize_structured_content_candidate(nfc)
    assert payload == serialize_structured_content_candidate(decomp) == serialize_structured_content_candidate(nfc)
    assert "Café" in payload.decode("utf-8") and b"\\u00" not in payload
    assert payload.endswith(b"\n") and payload.count(b"\n") == 1


def test_immutability_and_nested_input_detachment():
    candidate = make_linear_candidate(1, 1)
    with pytest.raises(FrozenInstanceError):
        candidate.document_ref = DocumentRef("changed")
    with pytest.raises(FrozenInstanceError):
        candidate.pages[0].page_label = "changed"
    with pytest.raises(FrozenInstanceError):
        candidate.nodes[0].text = "changed"
    with pytest.raises(FrozenInstanceError):
        candidate.candidate_id.value = "changed"
    with pytest.raises(AttributeError):
        candidate.nodes.append(candidate.nodes[0])
    source = {"org.atlas.list": ["a"]}
    detached = make_linear_candidate(1, 1, extensions=source)
    source["org.atlas.list"].append("b")
    assert detached.extensions["org.atlas.list"] == ("a",)
    issue_details = {"items": ["a"]}
    issue = ContentValidationIssue("X", details=issue_details)
    issue_details["items"].append("b")
    assert issue.details["items"] == ["a"]


def test_validation_and_serialization_do_not_mutate_candidate():
    candidate = make_asset_evidence_warning_candidate()
    snapshot = deepcopy(candidate)
    assert validate_content_candidate(candidate) == validate_content_candidate(candidate)
    assert candidate == snapshot
    assert serialize_structured_content_candidate(candidate) == serialize_structured_content_candidate(candidate)
    assert candidate == snapshot


@pytest.mark.parametrize("fixture_name", ["duplicate_node_id","dangling_parent","parent_page_mismatch","hierarchy_cycle","duplicate_sibling_order","duplicate_root_node_reference","dangling_evidence_reference","dangling_asset_reference","dangling_warning_reference","invalid_geometry_reference","node_attribute_type_mismatch","recovery_summary_count_mismatch"])
def test_validation_results_are_deterministic_for_malformed_fixtures(fixture_name):
    candidate = load_candidate(BASE / "invalid" / fixture_name / "candidate.json")
    results = [_result_dict(candidate) for _ in range(3)]
    assert results[0] == results[1] == results[2]
    if fixture_name == "hierarchy_cycle":
        assert sum(1 for issue in results[0]["issues"] if issue["code"] == "HIERARCHY_CYCLE") == 1


def test_duplicate_page_id_validation_is_deterministic():
    candidate = make_linear_candidate(2, 1)
    malformed = replace(candidate, pages=(candidate.pages[0], replace(candidate.pages[1], page_id=candidate.pages[0].page_id)))
    assert _result_dict(malformed) == _result_dict(malformed)


@pytest.mark.parametrize("candidate", [load_candidate(BASE / "valid/full_vocabulary_document/candidate.json"), make_deep_hierarchy(1000), make_linear_candidate(100, 10), make_asset_evidence_warning_candidate()])
def test_serialization_safety_and_provider_lifecycle_neutrality(candidate):
    _assert_safe_serialization(serialize_structured_content_candidate(candidate))


def test_hash_stability_for_fixture_and_generated_candidates():
    fixture = load_candidate(BASE / "valid/one_page_heading_paragraph/candidate.json")
    full = load_candidate(BASE / "valid/full_vocabulary_document/candidate.json")
    generated = make_linear_candidate(100, 10)
    assert json.loads(serialize_structured_content_candidate(fixture)) == load_expected_canonical(BASE / "valid/one_page_heading_paragraph/canonical.json")
    for candidate in (fixture, full, generated):
        hashes = [hashlib.sha256(serialize_structured_content_candidate(candidate)).hexdigest() for _ in range(3)]
        assert hashes[0] == hashes[1] == hashes[2]


def test_error_messages_are_safe_and_inputs_are_not_mutated():
    source = load_json(BASE / "valid/one_page_heading_paragraph/candidate.json")
    source["nodes"][0]["node_type"] = "unsupported_type"
    snapshot = deepcopy(source)
    with pytest.raises(ValueError) as first:
        candidate_from_dict(source)
    with pytest.raises(ValueError) as second:
        candidate_from_dict(source)
    for message in (str(first.value), str(second.value)):
        assert "unsupported node type" in message
        assert not re.search(r"0x[0-9a-fA-F]+|provider_payload", message)
    assert source == snapshot
