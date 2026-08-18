import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.structured_content import *
from tests.structured_content.fixture_loader import candidate_from_dict, load_json

BASE = Path("tests/fixtures/structured_content/v1")


def _candidate(*, pages=None, nodes=None, evidence=(), assets=(), warnings=(), summary=None):
    pages = tuple(pages or ())
    nodes = tuple(nodes or ())
    summary = summary or ContentRecoverySummary(
        ContentRecoveryState.COMPLETE,
        len(pages),
        complete_pages=sum(p.recovery_state == PageRecoveryState.COMPLETE for p in pages),
        partial_pages=sum(p.recovery_state == PageRecoveryState.PARTIAL for p in pages),
        degraded_pages=sum(p.recovery_state == PageRecoveryState.DEGRADED for p in pages),
        unavailable_pages=sum(p.recovery_state in {PageRecoveryState.UNAVAILABLE, PageRecoveryState.UNSUPPORTED} for p in pages),
        no_usable_semantic_content_pages=sum(p.recovery_state == PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT for p in pages),
    )
    return StructuredContentCandidate(
        SCHEMA_ID,
        SCHEMA_VERSION,
        DocumentRef("doc"),
        ContentCandidateId("cand"),
        ContentLineageKey("lineage"),
        summary,
        pages,
        nodes,
        tuple(evidence),
        tuple(assets),
        tuple(warnings),
        {"org.atlas.test": "validation"},
    )


def _page(page_id="p1", *, order=0, state=PageRecoveryState.COMPLETE, roots=(), source_page_index=0, evidence_ids=(), warning_ids=()):
    return ContentPage(ContentPageId(page_id), source_page_index, order, state, tuple(ContentNodeId(r) for r in roots), evidence_ids=tuple(EvidenceReferenceId(e) for e in evidence_ids), warning_ids=tuple(warning_ids))


def _node(node_id="n1", *, page_id="p1", parent_id=None, order=0, node_type=ContentNodeType.PARAGRAPH, attributes=None, evidence_ids=(), asset_ids=(), warning_ids=()):
    return ContentNode(ContentNodeId(node_id), ContentLineageKey(f"lineage-{node_id}"), node_type, ContentPageId(page_id), order, NodeRecoveryState.COMPLETE, parent_id=ContentNodeId(parent_id) if parent_id else None, text="text", attributes=attributes, evidence_ids=tuple(EvidenceReferenceId(e) for e in evidence_ids), asset_ids=tuple(AssetId(a) for a in asset_ids), warning_ids=tuple(warning_ids))


def _codes(candidate):
    return [issue.code for issue in validate_content_candidate(candidate).issues]


def _result_dict(candidate):
    return validation_result_to_canonical_dict(validate_content_candidate(candidate))


def test_valid_fixture_candidates_have_no_issues_and_are_repeatable():
    manifest = load_json(BASE / "manifest.json")
    valid_paths = [case["candidate_path"] for case in manifest["cases"] if case["expected_validity"] == "valid"]
    assert valid_paths[:2] == ["valid/minimal_empty_candidate/candidate.json", "valid/one_page_heading_paragraph/candidate.json"]
    assert all(path.startswith("valid/") and path.endswith("/candidate.json") for path in valid_paths)
    for rel in valid_paths:
        candidate = candidate_from_dict(load_json(BASE / rel))
        first = validate_content_candidate(candidate)
        second = validate_content_candidate(candidate)
        assert first.is_valid
        assert first.issues == ()
        assert first.blocking_issue_count == 0
        assert first == second


def test_result_helpers_and_immutability():
    issue = ContentValidationIssue(ContentValidationCode.DANGLING_PARENT, scope_path="$.nodes['n'].parent_id", safe_summary="Parent missing.")
    result = ContentValidationResult(False, [issue], 999, 999)
    assert not result.is_valid
    assert isinstance(result.issues, tuple)
    assert result.blocking_issue_count == 1
    assert result.nonblocking_issue_count == 0
    assert result.has_code("DANGLING_PARENT")
    assert result.blocking_issues == (issue,)
    assert result.nonblocking_issues == ()
    with pytest.raises(FrozenInstanceError):
        issue.scope_path = "$"
    with pytest.raises(FrozenInstanceError):
        result.is_valid = True


def test_all_required_issue_codes_are_defined():
    required = {
        "UNSUPPORTED_SCHEMA", "EMPTY_CANDIDATE_ID", "EMPTY_LINEAGE_KEY", "DUPLICATE_PAGE_ID", "DUPLICATE_NODE_ID", "DUPLICATE_EVIDENCE_ID", "DUPLICATE_ASSET_ID", "DUPLICATE_WARNING_ID", "DUPLICATE_PAGE_ORDER", "NEGATIVE_PAGE_ORDER", "NEGATIVE_SOURCE_PAGE_INDEX", "ROOT_NODE_NOT_FOUND", "ROOT_NODE_PAGE_MISMATCH", "ROOT_NODE_HAS_PARENT", "DANGLING_PARENT", "PARENT_PAGE_MISMATCH", "HIERARCHY_CYCLE", "DUPLICATE_SIBLING_ORDER", "DANGLING_EVIDENCE_REFERENCE", "DANGLING_ASSET_REFERENCE", "DANGLING_WARNING_REFERENCE", "DANGLING_RENDITION_REFERENCE", "INVALID_GEOMETRY_REFERENCE", "NODE_ATTRIBUTE_TYPE_MISMATCH", "NO_USABLE_PAGE_HAS_SEMANTIC_ROOTS", "RECOVERY_SUMMARY_COUNT_MISMATCH", "UNSAFE_EXTENSION", "NONDETERMINISTIC_SERIALIZATION",
    }
    assert required <= {code.value for code in ContentValidationCode}


def test_issue_ordering_and_result_serialization_are_deterministic():
    page = _page(roots=("missing",), evidence_ids=("missing-e",), warning_ids=("missing-w",))
    candidate = _candidate(pages=(page,), nodes=(_node("n1", evidence_ids=("missing-e",), asset_ids=("missing-a",), warning_ids=("missing-w",)),))
    first = validate_content_candidate(candidate)
    second = validate_content_candidate(candidate)
    assert first.issues == second.issues
    assert _result_dict(candidate) == _result_dict(candidate)
    assert json.dumps(_result_dict(candidate), sort_keys=True, separators=(",", ":"))


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda c: object.__setattr__(c, "schema_version", 999), "UNSUPPORTED_SCHEMA"),
        (lambda c: object.__setattr__(c, "pages", c.pages + (c.pages[0],)), "DUPLICATE_PAGE_ID"),
        (lambda c: object.__setattr__(c, "nodes", c.nodes + (c.nodes[0],)), "DUPLICATE_NODE_ID"),
        (lambda c: object.__setattr__(c, "evidence", c.evidence + (c.evidence[0],)), "DUPLICATE_EVIDENCE_ID"),
        (lambda c: object.__setattr__(c, "assets", c.assets + (c.assets[0],)), "DUPLICATE_ASSET_ID"),
        (lambda c: object.__setattr__(c, "warnings", c.warnings + (c.warnings[0],)), "DUPLICATE_WARNING_ID"),
    ],
)
def test_schema_and_duplicate_registry_checks(mutate, code):
    evidence = EvidenceReference(EvidenceReferenceId("e1"), EvidenceKind.SOURCE_LOCATION, source_page_index=0)
    asset = AssetReference(AssetId("a1"), AssetRole.FIGURE, AssetRecoveryState.AVAILABLE)
    warning = ContentWarning("w1", "WARN", WarningSeverity.WARNING, "$", "warn")
    page = _page(roots=("n1",), evidence_ids=("e1",), warning_ids=("w1",))
    candidate = _candidate(pages=(page,), nodes=(_node("n1"),), evidence=(evidence,), assets=(asset,), warnings=(warning,))
    mutate(candidate)
    assert code in _codes(candidate)


def test_page_order_and_source_page_index_are_validated():
    duplicate_p1 = _page("p1", order=0, roots=("n1",))
    duplicate_p2 = _page("p2", order=0, roots=("n2",), source_page_index=1)
    duplicate_candidate = _candidate(
        pages=(duplicate_p1, duplicate_p2),
        nodes=(
            _node("n1", page_id="p1"),
            _node("n2", page_id="p2"),
        ),
    )
    assert "DUPLICATE_PAGE_ORDER" in _codes(duplicate_candidate)

    negative_p1 = _page("p1", order=0, roots=("n1",))
    negative_p2 = _page("p2", order=1, roots=("n2",), source_page_index=1)
    negative_candidate = _candidate(
        pages=(negative_p1, negative_p2),
        nodes=(
            _node("n1", page_id="p1"),
            _node("n2", page_id="p2"),
        ),
    )
    object.__setattr__(negative_p2, "page_order", -1)
    object.__setattr__(negative_p2, "source_page_index", -1)
    negative_codes = _codes(negative_candidate)
    assert "NEGATIVE_PAGE_ORDER" in negative_codes
    assert "NEGATIVE_SOURCE_PAGE_INDEX" in negative_codes


def test_page_root_validation_cases():
    page1 = _page("p1", roots=("missing", "n2", "n3", "n3"), warning_ids=("missing-w",))
    page2 = _page("p2", order=1, roots=("n2",), source_page_index=1)
    n2 = _node("n2", page_id="p2")
    n3 = _node("n3", page_id="p1", parent_id="n2")
    codes = _codes(_candidate(pages=(page1, page2), nodes=(n2, n3)))
    assert "ROOT_NODE_NOT_FOUND" in codes
    assert "ROOT_NODE_PAGE_MISMATCH" in codes
    assert "ROOT_NODE_HAS_PARENT" in codes
    assert "DUPLICATE_ROOT_NODE_REFERENCE" in codes
    assert "DANGLING_WARNING_REFERENCE" in codes


def test_no_usable_page_with_roots_or_nodes_is_invalid():
    page = _page("p1", state=PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT, roots=("n1",))
    summary = ContentRecoverySummary(ContentRecoveryState.PARTIAL, 1, no_usable_semantic_content_pages=1)
    codes = _codes(_candidate(pages=(page,), nodes=(_node("n1"),), summary=summary))
    assert "NO_USABLE_PAGE_HAS_SEMANTIC_ROOTS" in codes


def test_node_page_parent_hierarchy_and_sibling_checks():
    p1 = _page("p1", roots=("n1",))
    p2 = _page("p2", order=1, roots=("p2root",), source_page_index=1)
    nodes = (_node("n1"), _node("child1", parent_id="n1"), _node("child2", parent_id="n1"), _node("cross", page_id="p2", parent_id="n1"), _node("orphan", parent_id="missing"), _node("nopage", page_id="missing"), _node("p2root", page_id="p2"))
    codes = _codes(_candidate(pages=(p1, p2), nodes=nodes))
    assert "DUPLICATE_SIBLING_ORDER" in codes
    assert "PARENT_PAGE_MISMATCH" in codes
    assert "DANGLING_PARENT" in codes
    assert "NODE_PAGE_NOT_FOUND" in codes


def test_same_sibling_order_under_different_parents_is_valid_and_root_order_preserved():
    page = _page("p1", roots=("parent2", "parent1"))
    nodes = (_node("parent1", order=1), _node("parent2", order=0), _node("child1", parent_id="parent1", order=0), _node("child2", parent_id="parent2", order=0))
    result = validate_content_candidate(_candidate(pages=(page,), nodes=nodes))
    assert result.is_valid
    assert page.root_node_ids == (ContentNodeId("parent2"), ContentNodeId("parent1"))


def test_self_and_multi_node_cycles_are_deterministic():
    self_node = _node("self", parent_id="self")
    self_result = validate_content_candidate(_candidate(pages=(_page(roots=()),), nodes=(self_node,)))
    assert [issue.code for issue in self_result.issues if issue.code == "HIERARCHY_CYCLE"] == ["HIERARCHY_CYCLE"]
    a = _node("a", parent_id="c")
    b = _node("b", parent_id="a")
    c = _node("c", parent_id="b")
    multi_result = validate_content_candidate(_candidate(pages=(_page(roots=()),), nodes=(a, b, c)))
    assert [issue for issue in multi_result.issues if issue.code == "HIERARCHY_CYCLE"][0].details == {"node_ids": ["a", "b", "c"]}


def test_reference_validation_cases():
    asset = AssetReference(AssetId("asset-1"), AssetRole.FIGURE, AssetRecoveryState.MISSING, rendition_refs=(AssetRenditionId("rendition-1"), AssetRenditionId("rendition-1")), evidence_ids=(EvidenceReferenceId("missing-e"),))
    warning = ContentWarning("warning-1", "WARN", WarningSeverity.WARNING, "$", "warn", evidence_ids=(EvidenceReferenceId("missing-e"),))
    page = _page(roots=("n1",), evidence_ids=("missing-e",), warning_ids=("missing-w",))
    node = _node("n1", evidence_ids=("missing-e",), asset_ids=("missing-a",), warning_ids=("missing-w",))
    codes = _codes(_candidate(pages=(page,), nodes=(node,), assets=(asset,), warnings=(warning,)))
    assert "DANGLING_EVIDENCE_REFERENCE" in codes
    assert "DANGLING_ASSET_REFERENCE" in codes
    assert "DANGLING_WARNING_REFERENCE" in codes
    assert "DANGLING_RENDITION_REFERENCE" in codes


def test_attribute_compatibility_positive_and_negative_cases():
    positive = [
        _node("heading", node_type=ContentNodeType.HEADING, attributes=HeadingAttributes(1)),
        _node("list", node_type=ContentNodeType.LIST, attributes=ListAttributes()),
        _node("item", node_type=ContentNodeType.LIST_ITEM, attributes=ListItemAttributes()),
        _node("table", node_type=ContentNodeType.TABLE, attributes=TableAttributes(TableStructure(1, 1))),
        _node("figure", node_type=ContentNodeType.FIGURE, attributes=FigureAttributes()),
        _node("caption", node_type=ContentNodeType.CAPTION, attributes=CaptionAttributes()),
        _node("formula", node_type=ContentNodeType.FORMULA, attributes=FormulaAttributes()),
        _node("unknown", node_type=ContentNodeType.UNKNOWN),
    ]
    page = _page(roots=tuple(node.node_id.value for node in positive))
    assert validate_content_candidate(_candidate(pages=(page,), nodes=positive)).is_valid
    bad_heading = _node("bad-heading", node_type=ContentNodeType.HEADING, attributes=ListAttributes())
    bad_paragraph = _node("bad-paragraph", node_type=ContentNodeType.PARAGRAPH, attributes=HeadingAttributes(1))
    codes = _codes(_candidate(pages=(_page(roots=("bad-heading", "bad-paragraph")),), nodes=(bad_heading, bad_paragraph)))
    assert codes.count("NODE_ATTRIBUTE_TYPE_MISMATCH") == 2


def test_recovery_summary_complete_degraded_and_mismatched_counts():
    complete_page = _page(roots=("n1",))
    assert validate_content_candidate(_candidate(pages=(complete_page,), nodes=(_node("n1"),))).is_valid
    degraded_page = _page(state=PageRecoveryState.DEGRADED, roots=("n1",))
    degraded_summary = ContentRecoverySummary(ContentRecoveryState.DEGRADED, 1, degraded_pages=1)
    assert validate_content_candidate(_candidate(pages=(degraded_page,), nodes=(_node("n1"),), summary=degraded_summary)).is_valid
    bad_total = ContentRecoverySummary(ContentRecoveryState.COMPLETE, 2, complete_pages=1)
    assert "RECOVERY_SUMMARY_COUNT_MISMATCH" in _codes(_candidate(pages=(complete_page,), nodes=(_node("n1"),), summary=bad_total))
    bad_state = ContentRecoverySummary(ContentRecoveryState.COMPLETE, 1, partial_pages=1)
    assert "RECOVERY_SUMMARY_COUNT_MISMATCH" in _codes(_candidate(pages=(complete_page,), nodes=(_node("n1"),), summary=bad_state))
    negative = ContentRecoverySummary(ContentRecoveryState.COMPLETE, -1, complete_pages=-1)
    assert "RECOVERY_SUMMARY_COUNT_MISMATCH" in _codes(_candidate(summary=negative))


def test_extension_boundaries_remain_model_level_and_serialization_is_checked():
    with pytest.raises(ValueError):
        StructuredContentCandidate(SCHEMA_ID, SCHEMA_VERSION, DocumentRef("doc"), ContentCandidateId("cand"), ContentLineageKey("lineage"), ContentRecoverySummary(ContentRecoveryState.COMPLETE, 0), (), (), (), (), (), {"identity": "bad"})
    with pytest.raises(ValueError):
        StructuredContentCandidate(SCHEMA_ID, SCHEMA_VERSION, DocumentRef("doc"), ContentCandidateId("cand"), ContentLineageKey("lineage"), ContentRecoverySummary(ContentRecoveryState.COMPLETE, 0), (), (), (), (), (), {"org.atlas.nan": float("nan")})
    candidate = _candidate()
    assert validate_content_candidate(candidate).is_valid


def test_every_manifest_entry_loads_and_fixture_expectations_match_repeatedly():
    manifest = load_json(BASE / "manifest.json")
    assert manifest["fixture_suite"] == "atlas.structured-content.fixtures"
    assert manifest["schema_version"] == 1
    names = [case["name"] for case in manifest["cases"]]
    assert names[:2] == ["minimal_empty_candidate", "one_page_heading_paragraph"]
    assert len(names) == len(set(names))
    for case in manifest["cases"]:
        assert case.get("transformer_input_dependency") is None
        candidate = candidate_from_dict(load_json(BASE / case["candidate_path"]))
        result = validate_content_candidate(candidate)
        assert result == validate_content_candidate(candidate)
        if case["expected_validity"] == "valid":
            assert result.is_valid
        else:
            assert not result.is_valid
            expected = load_json(BASE / case["validation_path"])
            assert validation_result_to_canonical_dict(result) == expected


def test_invalid_fixture_directories_are_complete():
    invalid_dirs = sorted((BASE / "invalid").iterdir())
    invalid_names = [path.name for path in invalid_dirs]
    assert {
        "dangling_asset_reference", "dangling_evidence_reference", "dangling_parent", "duplicate_node_id", "duplicate_sibling_order", "hierarchy_cycle", "invalid_page_root_association", "no_usable_page_with_semantic_roots",
    }.issubset(invalid_names)
    for case_dir in invalid_dirs:
        assert (case_dir / "candidate.json").is_file()
        assert (case_dir / "validation.json").is_file()
        expected = load_json(case_dir / "validation.json")
        assert expected["is_valid"] is False
        assert expected["blocking_issue_count"] == len(expected["issues"])
        assert all(issue["code"] and issue["scope_path"] for issue in expected["issues"])
