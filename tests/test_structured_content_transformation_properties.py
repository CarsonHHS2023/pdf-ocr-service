from __future__ import annotations

import builtins
import copy
import inspect

import pytest

import app.structured_content.transformation.transformer as transformer
from app.processing.structured_result import StructuredProcessingResult
from app.structured_content.enums import AssetRecoveryState
from app.structured_content.serialization import serialize_structured_content_candidate
from app.structured_content.transformation import CandidateIdentityInput, TransformationContext, TransformationInvariantViolation, transform_spr_to_candidate
from tests.structured_content.transformation_s3e_helpers import assert_candidate_invariants, assert_no_payload_leak, canonical, context, spr_dict, transform_fixture


def test_all_representative_candidates_satisfy_identity_hierarchy_table_asset_warning_invariants() -> None:
    for name in ('core_text', 'structural', 'tables_assets', 'mixed_document'):
        assert_candidate_invariants(transform_fixture(name))


def test_retry_identity_rebuild_separation_and_lineage_contract() -> None:
    spr = StructuredProcessingResult(spr_dict('core_text'))
    same = context('core_text')
    first = transform_spr_to_candidate(spr, context=same)
    retry = transform_spr_to_candidate(spr, context=same)
    rebuild = transform_spr_to_candidate(spr, context=context('core_text', candidate_id='candidate-core-rebuild'))
    reseeded = transform_spr_to_candidate(spr, context=context('core_text', seed='lineage-core-reseed'))
    assert first == retry
    assert canonical(first) == canonical(retry)
    assert first.candidate_id != rebuild.candidate_id
    assert [n.node_id for n in first.nodes] != [n.node_id for n in rebuild.nodes]
    assert [n.lineage_key for n in first.nodes] == [n.lineage_key for n in rebuild.nodes]
    assert first.candidate_id == reseeded.candidate_id
    assert first.lineage_key != reseeded.lineage_key
    assert [n.lineage_key for n in first.nodes] != [n.lineage_key for n in reseeded.nodes]


@pytest.mark.parametrize('mutator, message', [
    (lambda d: d['nodes'].append(copy.deepcopy(d['nodes'][0])), 'duplicate source node identity'),
    (lambda d: d['nodes'][0].update(parent_id=d['nodes'][0]['node_id']), 'self-parent'),
    (lambda d: d['nodes'][0].update(page_ids=['p1', 'p2']), 'exactly one page'),
    (lambda d: d['nodes'][0].update(geometry={'normalized_bbox': ['bad']}), 'invalid source geometry'),
])
def test_malformed_spr_failures_are_bounded_deterministic_atomic_and_immutable(mutator, message: str) -> None:
    data = spr_dict('core_text')
    before = copy.deepcopy(data)
    mutator(data)
    mutated = copy.deepcopy(data)
    errors = []
    for _ in range(2):
        with pytest.raises(Exception) as exc:
            transform_spr_to_candidate(StructuredProcessingResult(copy.deepcopy(data)), context=context('core_text'))
        errors.append(exc.value)
    assert type(errors[0]) is type(errors[1])
    assert str(errors[0]) == str(errors[1])
    assert message in str(errors[0])
    assert 'Traceback' not in str(errors[0]) and 'secret' not in str(errors[0]).lower()
    assert data == mutated
    assert before != data


def test_hierarchy_rejections_cover_cycles_cross_page_and_unsupported_parent() -> None:
    cycle = spr_dict('structural')
    by_id = {n['node_id']: n for n in cycle['nodes']}
    by_id['lst']['parent_id'] = 'li1'; by_id['li1']['child_ids'].append('lst')
    with pytest.raises(TransformationInvariantViolation, match='cycle'):
        transform_spr_to_candidate(StructuredProcessingResult(cycle), context=context('structural'))
    cross = spr_dict('mixed_document')
    node = next(n for n in cross['nodes'] if n['node_id'] == 'li')
    node['parent_id'] = 'h2'
    parent = next(n for n in cross['nodes'] if n['node_id'] == 'h2')
    parent.setdefault('child_ids', []).append('li')
    with pytest.raises(TransformationInvariantViolation, match='crosses pages'):
        transform_spr_to_candidate(StructuredProcessingResult(cross), context=context('mixed_document'))


def test_warning_ids_messages_scopes_and_order_are_stable() -> None:
    candidate = transform_fixture('structural')
    assert [(w.code, w.severity.value, w.scope_path, w.safe_summary, tuple(e.value for e in w.evidence_ids)) for w in candidate.warnings] == [(w.code, w.severity.value, w.scope_path, w.safe_summary, tuple(e.value for e in w.evidence_ids)) for w in transform_fixture('structural').warnings]
    assert [w.warning_id for w in candidate.warnings] == sorted([w.warning_id for w in candidate.warnings], key=lambda wid: next((w.scope_path, w.code, w.warning_id) for w in candidate.warnings if w.warning_id == wid))


def test_recovery_states_cover_complete_degraded_and_no_usable_page() -> None:
    complete = transform_fixture('core_text')
    degraded = transform_fixture('structural')
    data = spr_dict('core_text')
    data['pages'].append({'page_id': 'empty', 'page_index': 2, 'page_number': 3, 'width': 1, 'height': 1, 'status': 'no_usable_semantic_content', 'root_node_ids': []})
    mixed = transform_spr_to_candidate(StructuredProcessingResult(data), context=context('core_text'))
    assert complete.recovery_summary.complete_pages == 2
    assert degraded.recovery_summary.degraded_pages == 1
    assert mixed.recovery_summary.no_usable_semantic_content_pages == 1
    assert canonical(mixed) == canonical(transform_spr_to_candidate(StructuredProcessingResult(data), context=context('core_text')))


def test_asset_safety_durable_classification_and_sorting() -> None:
    candidate = transform_fixture('tables_assets')
    assert [a.asset_id.value for a in candidate.assets] == sorted(a.asset_id.value for a in candidate.assets)
    assert any(a.recovery_state is AssetRecoveryState.AVAILABLE for a in candidate.assets)
    assert_no_payload_leak(candidate)
    transient = spr_dict('tables_assets')
    transient['assets'][0]['renditions'] = [{'artifact_ref': 'https://example.test/x.png?X-Amz-Signature=secret'}]
    out = transform_spr_to_candidate(StructuredProcessingResult(transient), context=context('tables_assets'))
    assert out.assets[0].recovery_state is AssetRecoveryState.DEGRADED
    assert 'example.test' not in serialize_structured_content_candidate(out).decode()


def test_transformer_source_and_runtime_purity_tripwires(monkeypatch) -> None:
    source = inspect.getsource(transformer)
    forbidden = ('StructuredContentCandidateRepository', 'StructuredContentSelectionRepository', 'ProcessingRunRepository', 'requests.', 'httpx.', 'boto3', 'paddle_vl.client')
    assert not any(token in source for token in forbidden)
    original_open = builtins.open
    def blocked_open(*args, **kwargs):
        raise AssertionError('transformer attempted file IO')
    monkeypatch.setattr(builtins, 'open', blocked_open)
    try:
        candidate = transform_fixture('core_text')
    finally:
        monkeypatch.setattr(builtins, 'open', original_open)
    assert_candidate_invariants(candidate)


def test_wrong_input_type_error_is_deterministic() -> None:
    ctx = context('core_text')
    with pytest.raises(Exception) as a:
        transform_spr_to_candidate({'not': 'spr'}, context=ctx)  # type: ignore[arg-type]
    with pytest.raises(Exception) as b:
        transform_spr_to_candidate({'not': 'spr'}, context=ctx)  # type: ignore[arg-type]
    assert type(a.value) is type(b.value)
    assert str(a.value) == str(b.value)
