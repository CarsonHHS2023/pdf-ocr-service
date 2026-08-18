from __future__ import annotations

import json, re, time
from dataclasses import replace
from statistics import median

from app.structured_content.enums import PageRecoveryState
from app.structured_content.identity import ContentNodeId, EvidenceReferenceId
from app.structured_content.model import ContentRecoverySummary
from app.structured_content.serialization import serialize_structured_content_candidate
from app.structured_content.validation import ContentValidationCode, validate_content_candidate, validation_result_to_canonical_dict
from tests.structured_content.candidate_factory import make_asset_evidence_warning_candidate, make_deep_hierarchy, make_linear_candidate, make_multi_page_candidate, make_table_candidate, make_wide_hierarchy, permute_registries

BUDGET = 5.0


def _canonical_result(candidate):
    return validation_result_to_canonical_dict(validate_content_candidate(candidate))


def _assert_valid(candidate):
    result = validate_content_candidate(candidate)
    assert result.is_valid, validation_result_to_canonical_dict(result)
    assert result.issues == ()
    return result


def _time_once(label, operation):
    start = time.perf_counter(); value = operation(); duration = time.perf_counter() - start
    assert duration < BUDGET, f"{label} took {duration:.3f}s; budget {BUDGET:.3f}s"
    return value, duration


def test_deep_1000_node_hierarchy_validates_and_serializes_deterministically():
    candidate = make_deep_hierarchy(1000)
    _assert_valid(candidate)
    assert _canonical_result(candidate) == _canonical_result(candidate)
    assert serialize_structured_content_candidate(candidate) == serialize_structured_content_candidate(candidate)


def test_deep_cycle_reports_bounded_deterministic_cycle_without_recursion_error():
    candidate = make_deep_hierarchy(1000, cycle=True)
    first = _canonical_result(candidate); second = _canonical_result(candidate)
    assert first == second
    cycle_issues = [i for i in first["issues"] if i["code"] == ContentValidationCode.HIERARCHY_CYCLE.value]
    assert len(cycle_issues) == 1


def test_wide_2000_child_hierarchy_preserves_unique_sibling_order():
    candidate = make_wide_hierarchy(2000)
    _assert_valid(candidate)
    orders = [node.sibling_order for node in candidate.nodes if node.parent_id == ContentNodeId("node-root")]
    assert orders == list(range(2000))
    assert serialize_structured_content_candidate(candidate) == serialize_structured_content_candidate(candidate)


def test_malformed_wide_hierarchy_duplicate_sibling_order_is_bounded():
    candidate = make_wide_hierarchy(2000, duplicate_sibling=True)
    first = _canonical_result(candidate); second = _canonical_result(candidate)
    assert first == second
    duplicates = [i for i in first["issues"] if i["code"] == ContentValidationCode.DUPLICATE_SIBLING_ORDER.value]
    assert len(duplicates) == 1
    assert duplicates[0]["details"]["sibling_order"] == 0


def test_100_page_1000_node_candidate_is_valid_and_registry_order_invariant():
    candidate = make_multi_page_candidate(100, 10, 0)
    _assert_valid(candidate)
    payload = serialize_structured_content_candidate(candidate)
    assert payload == serialize_structured_content_candidate(candidate)
    assert payload == serialize_structured_content_candidate(permute_registries(candidate))
    data = json.loads(payload)
    assert [p["page_id"] for p in data["pages"]] == [f"page-{i:04d}" for i in range(100)]
    assert data["nodes"][0]["node_id"] == "node-00000" and data["nodes"][-1]["node_id"] == "node-00999"


def test_50_by_10_table_preserves_cell_order_and_row_swap_changes_canonical_output():
    table = make_table_candidate(50, 10)
    swapped = make_table_candidate(50, 10, swap_rows=True)
    _assert_valid(table); _assert_valid(swapped)
    cells = table.nodes[0].attributes.structure.cells
    assert len(cells) == 500
    assert [(c.row_index, c.column_index) for c in cells[:12]] == [(0, c) for c in range(10)] + [(1, 0), (1, 1)]
    assert serialize_structured_content_candidate(table) == serialize_structured_content_candidate(table)
    assert serialize_structured_content_candidate(table) != serialize_structured_content_candidate(swapped)


def test_asset_evidence_warning_and_rendition_scale_is_valid_and_deterministic():
    candidate = make_asset_evidence_warning_candidate(100, 50, 50)
    _assert_valid(candidate)
    assert len(candidate.evidence) >= 100 and len(candidate.assets) >= 50 and len(candidate.warnings) >= 50
    assert all(len(asset.rendition_refs) >= 2 for asset in candidate.assets)
    assert serialize_structured_content_candidate(candidate) == serialize_structured_content_candidate(candidate)


def test_malformed_validation_results_remain_bounded_safe_and_deterministic():
    base = make_wide_hierarchy(120, duplicate_sibling=True)
    no_roots = replace(base, pages=(replace(base.pages[0], root_node_ids=(), recovery_state=PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT),), recovery_summary=ContentRecoverySummary(base.recovery_summary.state, 1, no_usable_semantic_content_pages=1))
    dangling = replace(base, nodes=tuple(replace(n, evidence_ids=(EvidenceReferenceId(f"missing-{i:04d}"),)) for i, n in enumerate(base.nodes)))
    for candidate in (base, no_roots, dangling):
        first = _canonical_result(candidate); second = _canonical_result(candidate)
        assert first == second and len(first["issues"]) == len(second["issues"])
        payload = json.dumps(first, sort_keys=True, ensure_ascii=False).encode()
        assert not re.search(rb"0x[0-9a-fA-F]+|<[^>]+ object at ", payload)
        assert all(len(issue["safe_summary"]) < 200 for issue in first["issues"])


def test_performance_characterization_generous_budgets():
    linear = make_linear_candidate(1, 1000)
    wide = make_wide_hierarchy(2000)
    multi = make_multi_page_candidate(100, 10, 0)
    for label, candidate in (("1000-node validation", linear), ("2000-child validation", wide), ("100-page validation", multi)):
        result, duration = _time_once(label, lambda c=candidate: validate_content_candidate(c))
        assert result.is_valid, f"{label} invalid after {duration:.3f}s"
    for label, candidate in (("1000-node serialization", linear), ("100-page serialization", multi)):
        payload, duration = _time_once(label, lambda c=candidate: serialize_structured_content_candidate(c))
        assert payload.endswith(b"\n"), f"{label} malformed after {duration:.3f}s"


def test_complexity_characterization_no_catastrophic_growth():
    small = make_linear_candidate(1, 500); large = make_linear_candidate(1, 1000)
    def sample(candidate):
        durations = []
        for _ in range(3):
            start = time.perf_counter(); result = validate_content_candidate(candidate); durations.append(time.perf_counter() - start)
            assert result.is_valid
        return median(durations)
    small_duration, large_duration = sample(small), sample(large)
    if small_duration > 0.001 and large_duration > 0.001:
        assert large_duration <= small_duration * 6 + 0.05, f"1000-node validation {large_duration:.4f}s exceeded 6x 500-node {small_duration:.4f}s plus allowance"
