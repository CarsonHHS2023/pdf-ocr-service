from __future__ import annotations

import copy
import json

from app.processing.structured_result import StructuredProcessingResult
from app.processing.structured_result.serialization import serialize_structured_processing_result
from app.structured_content.enums import ContentNodeType, ContentRecoveryState, NodeRecoveryState, PageRecoveryState
from app.structured_content.transformation import CandidateIdentityInput, TransformationContext, transform_spr_to_candidate
from tests.structured_content.transformation_s3e_helpers import assert_candidate_invariants, assert_no_payload_leak, canonical, clone_spr, context, golden_bytes, load_spr, spr_dict, transform_fixture

GOLDENS = ('core_text', 'structural', 'tables_assets', 'mixed_document')


def test_golden_fixtures_match_canonical_candidates() -> None:
    for name in GOLDENS:
        candidate = transform_fixture(name)
        assert_candidate_invariants(candidate)
        assert canonical(candidate) == golden_bytes(name)
        assert_no_payload_leak(candidate)


def test_core_text_golden_covers_pages_order_geometry_evidence_and_provenance() -> None:
    candidate = transform_fixture('core_text')
    assert [p.page_order for p in candidate.pages] == [0, 1]
    assert [n.node_type for n in candidate.nodes] == [ContentNodeType.HEADING, ContentNodeType.PARAGRAPH, ContentNodeType.HEADING, ContentNodeType.PARAGRAPH]
    assert all(n.source_locations and n.source_locations[0].bounding_box for n in candidate.nodes)
    assert all(n.evidence_ids for n in candidate.nodes)
    assert candidate.processing_run_ref.value == 'run-golden'


def test_structural_golden_warnings_and_recovery_are_deterministic() -> None:
    candidate = transform_fixture('structural')
    assert [w.code for w in candidate.warnings] == ['UNRESOLVED_CAPTION_ASSOCIATION', 'MISSING_PARENT', 'UNKNOWN_ELEMENT_KIND']
    assert all(w.safe_summary and 'Traceback' not in w.safe_summary for w in candidate.warnings)
    assert candidate.nodes[4].recovery_state is NodeRecoveryState.RECOVERED
    assert candidate.nodes[7].node_type is ContentNodeType.UNKNOWN
    assert candidate.pages[0].recovery_state is PageRecoveryState.DEGRADED
    assert candidate.recovery_summary.state is ContentRecoveryState.DEGRADED


def test_tables_assets_golden_preserves_tables_assets_and_associations() -> None:
    candidate = transform_fixture('tables_assets')
    table, table_caption, figure, figure_caption, missing = candidate.nodes
    assert table.node_type is ContentNodeType.TABLE
    assert [(c.row_index, c.column_index, c.row_span, c.column_span, c.text) for c in table.attributes.structure.cells] == [(0, 0, 2, 1, 'Region'), (0, 1, 1, 2, 'Totals'), (1, 1, 1, 1, 'A'), (1, 2, 1, 1, 'B')]
    assert table.attributes.rendered_asset_id in {a.asset_id for a in candidate.assets}
    assert table_caption.attributes.target_node_id == table.node_id
    assert figure.attributes.caption_node_id == figure_caption.node_id
    assert figure_caption.attributes.target_node_id == figure.node_id
    assert missing.recovery_state is NodeRecoveryState.DEGRADED
    assert 'MISSING_ASSET_REFERENCE' in [w.code for w in candidate.warnings]


def test_mixed_document_verifies_order_hierarchy_recovery_and_bytes() -> None:
    candidate = transform_fixture('mixed_document')
    assert [p.page_order for p in candidate.pages] == [0, 1, 2]
    assert [len(p.root_node_ids) for p in candidate.pages] == [7, 6, 6]
    list_node = next(n for n in candidate.nodes if n.node_id.value.endswith(':olist'))
    item = next(n for n in candidate.nodes if n.node_id.value.endswith(':li'))
    assert item.parent_id == list_node.node_id
    assert [w.code for w in candidate.warnings] == ['UNKNOWN_ELEMENT_KIND']
    assert canonical(candidate) == golden_bytes('mixed_document')


def test_canonical_determinism_across_retry_deepcopy_and_spr_reparse() -> None:
    for name in GOLDENS:
        spr = load_spr(name)
        ctx = context(name)
        first = transform_spr_to_candidate(spr, context=ctx)
        second = transform_spr_to_candidate(spr, context=ctx)
        third = transform_spr_to_candidate(copy.deepcopy(spr), context=copy.deepcopy(ctx))
        fourth = transform_spr_to_candidate(clone_spr(spr), context=ctx)
        assert first == second == third == fourth
        assert canonical(first) == canonical(second) == canonical(third) == canonical(fourth)
        assert [p.page_id for p in first.pages] == [p.page_id for p in fourth.pages]
        assert [n.lineage_key for n in first.nodes] == [n.lineage_key for n in fourth.nodes]
        assert [w.warning_id for w in first.warnings] == [w.warning_id for w in fourth.warnings]


def test_input_ordering_perturbations_that_are_semantically_safe_are_canonical() -> None:
    data = spr_dict('tables_assets')
    permuted = copy.deepcopy(data)
    permuted['assets'] = list(reversed(permuted['assets']))
    for node in permuted['nodes']:
        if node['node_id'] == 'tbl':
            node['table']['cells'] = list(reversed(node['table']['cells']))
            node['evidence_link_ids'] = list(reversed(node['evidence_link_ids']))
    assert canonical(transform_spr_to_candidate(StructuredProcessingResult(data), context=context('tables_assets'))) == canonical(transform_spr_to_candidate(StructuredProcessingResult(permuted), context=context('tables_assets')))


def test_provider_origin_normalized_spr_derivative_has_no_provider_payload_leakage() -> None:
    data = spr_dict('core_text')
    data['raw_result']['provider'] = 'paddle-vl'
    data['raw_result']['raw_payload'] = {'provider_task_id': 'provider-secret-task', 'authorization': 'Bearer secret-token'}
    data['nodes'][0]['extensions'] = {'provider_raw_block': {'token': 'secret-token'}, 'level': 1}
    candidate = transform_spr_to_candidate(StructuredProcessingResult(data), context=context('core_text'))
    assert_candidate_invariants(candidate)
    assert_no_payload_leak(candidate, ('provider-secret-task', 'provider_raw_block', 'secret-token'))


def test_fixture_and_context_immutability() -> None:
    data = spr_dict('mixed_document')
    before = copy.deepcopy(data)
    spr = StructuredProcessingResult(data)
    ctx = context('mixed_document')
    ctx_before = copy.deepcopy(ctx)
    transform_spr_to_candidate(spr, context=ctx)
    assert data == before
    assert ctx == ctx_before
