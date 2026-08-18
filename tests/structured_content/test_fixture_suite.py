from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.structured_content.enums import ContentNodeType, PageRecoveryState
from app.structured_content.model import (
    CaptionAttributes,
    FigureAttributes,
    FormulaAttributes,
    HeadingAttributes,
    ListAttributes,
    ListItemAttributes,
    TableAttributes,
)
from app.structured_content.serialization import serialize_structured_content_candidate
from app.structured_content.validation import validate_content_candidate, validation_result_to_canonical_dict
from tests.structured_content.fixture_loader import (
    candidate_from_dict,
    load_candidate,
    load_expected_canonical,
    load_expected_validation,
    load_json,
    load_manifest,
)

BASE = Path(__file__).resolve().parents[1] / "fixtures" / "structured_content" / "v1"
VALID_NAMES = ["minimal_empty_candidate","one_page_heading_paragraph","section_with_nested_paragraphs","heading_list_and_items","table_with_structure","figure_caption_and_asset","formula_and_surrounding_text","header_footer_footnote","unknown_node_preserved","multi_page_hierarchy","degraded_page_with_recovered_content","no_usable_page_without_nodes","unavailable_page_in_mixed_document","multiple_evidence_and_warnings","multiple_assets_and_renditions","full_vocabulary_document"]
INVALID_CODES = {"duplicate_node_id":"DUPLICATE_NODE_ID","dangling_parent":"DANGLING_PARENT","hierarchy_cycle":"HIERARCHY_CYCLE","duplicate_sibling_order":"DUPLICATE_SIBLING_ORDER","invalid_page_root_association":"ROOT_NODE_PAGE_MISMATCH","dangling_evidence_reference":"DANGLING_EVIDENCE_REFERENCE","dangling_asset_reference":"DANGLING_ASSET_REFERENCE","no_usable_page_with_semantic_roots":"NO_USABLE_PAGE_HAS_SEMANTIC_ROOTS","node_page_not_found":"NODE_PAGE_NOT_FOUND","parent_page_mismatch":"PARENT_PAGE_MISMATCH","root_node_has_parent":"ROOT_NODE_HAS_PARENT","dangling_warning_reference":"DANGLING_WARNING_REFERENCE","node_attribute_type_mismatch":"NODE_ATTRIBUTE_TYPE_MISMATCH","recovery_summary_count_mismatch":"RECOVERY_SUMMARY_COUNT_MISMATCH","invalid_geometry_reference":"INVALID_GEOMETRY_REFERENCE","duplicate_root_node_reference":"DUPLICATE_ROOT_NODE_REFERENCE"}
EXPECTED_ORDER = VALID_NAMES + list(INVALID_CODES)


def _manifest():
    return load_manifest(BASE)


def _case(name: str):
    return next(case for case in _manifest()["cases"] if case["name"] == name)


def _candidate_for(case):
    return load_candidate(BASE / case["candidate_path"])


def test_manifest_contract_and_ordering():
    manifest = _manifest()
    assert manifest["fixture_suite"] == "atlas.structured-content.fixtures"
    assert manifest["schema_version"] == 1
    assert manifest["candidate_schema_id"] == "atlas.structured-content-candidate"
    assert manifest["candidate_schema_version"] == 1
    cases = manifest["cases"]
    assert [case["name"] for case in cases] == EXPECTED_ORDER
    assert len({case["name"] for case in cases}) == len(cases)
    paths = []
    for case in cases:
        assert case["transformer_input_dependency"] is None
        candidate_path = BASE / case["candidate_path"]
        assert candidate_path.exists()
        paths.append(case["candidate_path"])
        if case["expected_validity"] == "valid":
            assert (BASE / case["canonical_path"]).exists()
            paths.append(case["canonical_path"])
        else:
            assert (BASE / case["validation_path"]).exists()
            paths.append(case["validation_path"])
    assert len(set(paths)) == len(paths)


@pytest.mark.parametrize("name", VALID_NAMES)
def test_valid_fixtures_validate_and_match_canonical(name):
    case = _case(name)
    source = load_json(BASE / case["candidate_path"])
    before = copy.deepcopy(source)
    candidate = candidate_from_dict(source)
    assert source == before
    assert candidate == _candidate_for(case)
    result = validate_content_candidate(candidate)
    assert result.is_valid, validation_result_to_canonical_dict(result)
    assert result.issues == ()
    first = serialize_structured_content_candidate(candidate)
    second = serialize_structured_content_candidate(candidate)
    assert first == second
    assert first.endswith(b"\n")
    assert json.loads(first.decode("utf-8")) == load_expected_canonical(BASE / case["canonical_path"])
    forbidden = ("accepted", "current", "projection", "reader", "provider", "paddle", "mineru")
    payload = first.decode("utf-8").lower()
    assert not any(token in payload for token in forbidden)


@pytest.mark.parametrize("name,expected_code", INVALID_CODES.items())
def test_invalid_fixtures_match_validation(name, expected_code):
    case = _case(name)
    candidate = _candidate_for(case)
    first = validation_result_to_canonical_dict(validate_content_candidate(candidate))
    second = validation_result_to_canonical_dict(validate_content_candidate(candidate))
    assert first == second
    assert first == load_expected_validation(BASE / case["validation_path"])
    assert first["is_valid"] is False
    assert expected_code in {issue["code"] for issue in first["issues"]}


def test_full_vocabulary_document_represents_current_enum_and_attributes():
    candidate = _candidate_for(_case("full_vocabulary_document"))
    assert validate_content_candidate(candidate).is_valid
    represented = {node.node_type for node in candidate.nodes}
    assert represented == set(ContentNodeType)
    expected = {ContentNodeType.HEADING: HeadingAttributes, ContentNodeType.LIST: ListAttributes, ContentNodeType.LIST_ITEM: ListItemAttributes, ContentNodeType.TABLE: TableAttributes, ContentNodeType.FIGURE: FigureAttributes, ContentNodeType.CAPTION: CaptionAttributes, ContentNodeType.FORMULA: FormulaAttributes}
    for node in candidate.nodes:
        if node.node_type in expected:
            assert isinstance(node.attributes, expected[node.node_type])
        else:
            assert not isinstance(node.attributes, tuple(expected.values()))
    assert ContentNodeType.UNKNOWN in represented


def test_hierarchy_and_ordering_coverage_across_valid_suite():
    saw_hierarchy = saw_multipage = False
    for name in VALID_NAMES:
        c1 = _candidate_for(_case(name)); c2 = _candidate_for(_case(name))
        assert c1 == c2
        assert [p.page_order for p in c1.pages] == sorted(p.page_order for p in c1.pages)
        assert all(p.source_page_index >= 0 for p in c1.pages)
        assert len({p.page_id for p in c1.pages}) == len(c1.pages)
        assert len({n.node_id for n in c1.nodes}) == len(c1.nodes)
        nodes = {n.node_id: n for n in c1.nodes}
        for page in c1.pages:
            assert len(set(page.root_node_ids)) == len(page.root_node_ids)
            for root_id in page.root_node_ids:
                assert nodes[root_id].parent_id is None
        for node in c1.nodes:
            if node.parent_id is not None:
                saw_hierarchy = True
                assert node.parent_id in nodes
                assert nodes[node.parent_id].page_id == node.page_id
        for parent_id in {n.parent_id for n in c1.nodes if n.parent_id is not None}:
            orders = [n.sibling_order for n in c1.nodes if n.parent_id == parent_id]
            assert len(orders) == len(set(orders))
        assert serialize_structured_content_candidate(c1) == serialize_structured_content_candidate(c2)
        saw_multipage |= len(c1.pages) >= 3
    assert saw_hierarchy and saw_multipage


def test_evidence_warning_asset_and_recovery_coverage():
    candidates = [_candidate_for(_case(name)) for name in VALID_NAMES]
    assert any(p.evidence_ids for c in candidates for p in c.pages)
    assert any(n.evidence_ids for c in candidates for n in c.nodes)
    assert any(a.evidence_ids for c in candidates for a in c.assets)
    assert any(w.evidence_ids for c in candidates for w in c.warnings)
    assert any(p.warning_ids for c in candidates for p in c.pages)
    assert any(n.warning_ids for c in candidates for n in c.nodes)
    assert any(n.node_type is ContentNodeType.FIGURE and n.asset_ids for c in candidates for n in c.nodes)
    assert any(isinstance(n.attributes, CaptionAttributes) and n.attributes.target_asset_id for c in candidates for n in c.nodes)
    assert any(isinstance(n.attributes, TableAttributes) and n.attributes.rendered_asset_id for c in candidates for n in c.nodes)
    assert any(len(c.assets) >= 2 for c in candidates)
    assert any(len(a.rendition_refs) >= 2 for c in candidates for a in c.assets)
    assert any(c.recovery_summary.state.value == "complete" for c in candidates)
    assert any(c.recovery_summary.state.value == "degraded" for c in candidates)
    assert any(p.recovery_state is PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT for c in candidates for p in c.pages)
    assert any(p.recovery_state in {PageRecoveryState.UNAVAILABLE, PageRecoveryState.UNSUPPORTED} for c in candidates for p in c.pages)
    assert any(c.warnings for c in candidates)
    assert any(n.node_type is ContentNodeType.UNKNOWN and not n.source_locations[0].bounding_box for c in candidates for n in c.nodes if n.source_locations)
    assert any(n.node_type is ContentNodeType.UNKNOWN for c in candidates for n in c.nodes)


def test_loader_failures_and_optional_references():
    data = load_json(BASE / "valid/one_page_heading_paragraph/candidate.json")
    unsupported = copy.deepcopy(data); unsupported["nodes"][0]["node_type"] = "alien"
    with pytest.raises(ValueError, match="unsupported node type"):
        candidate_from_dict(unsupported)
    bad_attrs = copy.deepcopy(data); bad_attrs["nodes"][1]["attributes"] = {"level": 2}
    with pytest.raises(ValueError, match="unsupported attribute shape"):
        candidate_from_dict(bad_attrs)
    figure = _candidate_for(_case("figure_caption_and_asset"))
    assert figure.raw_result_ref is not None
    assert figure.structured_processing_result_ref is not None
    assert [node.node_id.value for node in figure.nodes] == ["node-figure-001", "node-caption-001"]
