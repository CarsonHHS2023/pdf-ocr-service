from __future__ import annotations

import copy, json
from pathlib import Path
from typing import Any

from app.processing.structured_result import StructuredProcessingResult
from app.processing.structured_result.serialization import serialize_structured_processing_result
from app.structured_content.enums import ContentNodeType, PageRecoveryState
from app.structured_content.model import StructuredContentCandidate, TableAttributes
from app.structured_content.serialization import serialize_structured_content_candidate
from app.structured_content.transformation import CandidateIdentityInput, TransformationContext, transform_spr_to_candidate
from app.structured_content.validation import validate_content_candidate

FIXTURE_DIR = Path('tests/fixtures/structured_content/transformation')


def load_spr(name: str) -> StructuredProcessingResult:
    return StructuredProcessingResult(json.loads((FIXTURE_DIR / f'{name}_spr.json').read_text()))


def golden_bytes(name: str) -> bytes:
    return (FIXTURE_DIR / f'{name}_candidate.json').read_bytes()


def context(name: str, *, candidate_id: str | None = None, seed: str | None = None, doc: str = 'doc-golden') -> TransformationContext:
    return TransformationContext(doc, CandidateIdentityInput(candidate_id or f'candidate-{name}', seed or f'lineage-{name}'), processing_run_ref='run-golden', source_file_ref='source-golden')


def transform_fixture(name: str, ctx: TransformationContext | None = None) -> StructuredContentCandidate:
    return transform_spr_to_candidate(load_spr(name), context=ctx or context(name))


def canonical(candidate: StructuredContentCandidate) -> bytes:
    return serialize_structured_content_candidate(candidate)


def assert_candidate_invariants(candidate: StructuredContentCandidate) -> None:
    assert validate_content_candidate(candidate).is_valid
    pages = {p.page_id for p in candidate.pages}
    nodes = {n.node_id for n in candidate.nodes}
    evidence = {e.evidence_id for e in candidate.evidence}
    assets = {a.asset_id for a in candidate.assets}
    warnings = {w.warning_id for w in candidate.warnings}
    assert len(pages) == len(candidate.pages)
    assert len(nodes) == len(candidate.nodes)
    assert len(evidence) == len(candidate.evidence)
    assert len(assets) == len(candidate.assets)
    assert len(warnings) == len(candidate.warnings)
    for page in candidate.pages:
        assert tuple(page.root_node_ids) == tuple(dict.fromkeys(page.root_node_ids))
        for root in page.root_node_ids:
            assert root in nodes
            n = next(x for x in candidate.nodes if x.node_id == root)
            assert n.page_id == page.page_id
            assert n.parent_id is None
        if page.recovery_state is PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT:
            assert not page.root_node_ids
        assert set(page.warning_ids) <= warnings
    by_node = {n.node_id: n for n in candidate.nodes}
    for node in candidate.nodes:
        assert node.page_id in pages
        assert set(node.evidence_ids) <= evidence
        assert set(node.asset_ids) <= assets
        assert set(node.warning_ids) <= warnings
        assert node.parent_id != node.node_id
        seen = set()
        parent = node.parent_id
        while parent is not None:
            assert parent in nodes
            assert parent not in seen
            seen.add(parent)
            assert by_node[parent].page_id == node.page_id
            parent = by_node[parent].parent_id
        if node.node_type is ContentNodeType.TABLE:
            assert isinstance(node.attributes, TableAttributes)
            occupied: set[tuple[int, int]] = set()
            for cell in node.attributes.structure.cells:
                assert cell.row_index >= 0 and cell.column_index >= 0
                assert cell.row_span > 0 and cell.column_span > 0
                assert cell.row_index + cell.row_span <= node.attributes.structure.row_count
                assert cell.column_index + cell.column_span <= node.attributes.structure.column_count
                covered = {(r, c) for r in range(cell.row_index, cell.row_index + cell.row_span) for c in range(cell.column_index, cell.column_index + cell.column_span)}
                assert not occupied & covered
                occupied |= covered
    assert candidate.recovery_summary.total_pages == len(candidate.pages)
    assert candidate.recovery_summary.complete_pages == sum(p.recovery_state is PageRecoveryState.COMPLETE for p in candidate.pages)
    assert candidate.recovery_summary.degraded_pages == sum(p.recovery_state is PageRecoveryState.DEGRADED for p in candidate.pages)
    assert candidate.recovery_summary.no_usable_semantic_content_pages == sum(p.recovery_state is PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT for p in candidate.pages)
    assert set(candidate.recovery_summary.warning_ids) == warnings


def clone_spr(spr: StructuredProcessingResult) -> StructuredProcessingResult:
    return StructuredProcessingResult(json.loads(serialize_structured_processing_result(spr)))


def assert_no_payload_leak(candidate: StructuredContentCandidate, sentinels: tuple[str, ...] = ()) -> None:
    text = canonical(candidate).decode()
    banned = ('Bearer ', 'api_key', 'secret-token', 'X-Amz-Signature', 'signature=', 'BEGIN PRIVATE', 'Traceback', 'file:///tmp', '/home/', 'data:image/', 'base64') + sentinels
    for value in banned:
        assert value not in text


def spr_dict(name: str) -> dict[str, Any]:
    return copy.deepcopy(load_spr(name).to_dict())
