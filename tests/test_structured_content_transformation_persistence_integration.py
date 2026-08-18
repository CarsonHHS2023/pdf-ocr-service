from __future__ import annotations

import copy

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document, SourceFile, StructuredContentCandidate as CandidateRow, StructuredContentSelection, encode_json_text
from app.processing_runs import ProcessingRunCreate, ProcessingRunRepository
from app.structured_content.errors import CandidateProcessingRunMismatch, StructuredContentCandidateConflict
from app.structured_content.identity import ContentCandidateId, ContentLineageKey
from app.structured_content.repository import StructuredContentCandidateRepository
from app.structured_content.selection_repository import StructuredContentSelectionRepository
from app.structured_content.transformation import CandidateIdentityInput, TransformationContext, TransformationInvariantViolation, transform_spr_to_candidate
from app.processing.structured_result import StructuredProcessingResult
from tests.structured_content.transformation_s3e_helpers import assert_candidate_invariants, canonical, spr_dict


@pytest.fixture()
def session():
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    @event.listens_for(engine, 'connect')
    def fk(conn, rec):
        conn.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close(); engine.dispose()


def add_doc(s, doc_id='doc-persist'):
    s.add(Document(id=doc_id, title=doc_id, file_type='pdf')); s.flush()


def add_source(s, source_id='source-persist', doc_id='doc-persist'):
    s.add(SourceFile(id=source_id, document_id=doc_id, original_filename=source_id, file_type='pdf')); s.flush()


def ctx(candidate_id='candidate-persist', seed='lineage-persist', doc='doc-persist', run='run-persist'):
    return TransformationContext(doc, CandidateIdentityInput(candidate_id, seed), processing_run_ref=run, source_file_ref='source-persist')


def transform(name='mixed_document', context=None):
    return transform_spr_to_candidate(StructuredProcessingResult(spr_dict(name)), context=context or ctx())


def test_transform_persist_reconstruct_canonical_equality_no_auto_selection_and_explicit_selection_compatibility(session) -> None:
    add_doc(session); add_source(session)
    ProcessingRunRepository().create_run(session, ProcessingRunCreate('run-persist', 'doc-persist', 'source-persist'))
    candidate = transform()
    assert_candidate_invariants(candidate)
    repo = StructuredContentCandidateRepository(); selection = StructuredContentSelectionRepository()
    assert selection.get_selection(session, candidate.document_ref) is None
    persisted = repo.create_candidate(session, candidate)
    reconstructed = repo.get_candidate(session, candidate.candidate_id)
    assert persisted == candidate == reconstructed
    assert canonical(reconstructed) == canonical(candidate)
    assert reconstructed.processing_run_ref == candidate.processing_run_ref
    row = session.query(CandidateRow).filter_by(candidate_id=candidate.candidate_id.value).one()
    assert '__atlas_persistence__' in row.extensions_json
    assert '__atlas_persistence__' not in reconstructed.extensions
    assert session.query(StructuredContentSelection).count() == 0
    selected = selection.set_selection(session, document_ref=candidate.document_ref, candidate_id=candidate.candidate_id, expected_version=0)
    assert selected.candidate_id == candidate.candidate_id.value
    assert canonical(selection.get_selected_candidate(session, candidate.document_ref)) == canonical(candidate)


def test_legacy_candidate_without_persistence_metadata_keeps_legacy_fallback(session) -> None:
    add_doc(session); add_source(session)
    ProcessingRunRepository().create_run(session, ProcessingRunCreate('run-persist', 'doc-persist', 'source-persist'))
    candidate = transform()
    repo = StructuredContentCandidateRepository()
    repo.create_candidate(session, candidate)
    row = session.query(CandidateRow).filter_by(candidate_id=candidate.candidate_id.value).one()
    row.extensions_json = encode_json_text(candidate.extensions)
    session.flush()

    reconstructed = repo.get_candidate(session, candidate.candidate_id)
    assert reconstructed.extensions == candidate.extensions
    assert reconstructed.recovery_summary.warning_ids == ()
    assert reconstructed.recovery_summary.recovery_policy_ref is None
    assert [node.node_id.value for node in reconstructed.nodes] == sorted(node.node_id.value for node in candidate.nodes)


def test_persistence_idempotency_and_conflict_are_repository_boundary_behaviors(session) -> None:
    add_doc(session); add_source(session)
    ProcessingRunRepository().create_run(session, ProcessingRunCreate('run-persist', 'doc-persist', 'source-persist'))
    repo = StructuredContentCandidateRepository()
    first = transform('core_text')
    equivalent = transform('core_text')
    repo.create_candidate(session, first)
    row_count = session.query(CandidateRow).count()
    assert repo.create_candidate(session, equivalent) == first
    assert session.query(CandidateRow).count() == row_count
    different_spr = spr_dict('core_text')
    different_spr['nodes'][1]['text'] = 'Changed text'
    different = transform_spr_to_candidate(StructuredProcessingResult(different_spr), context=ctx('candidate-persist', 'lineage-persist'))
    with pytest.raises(StructuredContentCandidateConflict):
        repo.create_candidate(session, different)
    assert canonical(repo.get_candidate(session, first.candidate_id)) == canonical(first)
    assert session.query(StructuredContentSelection).count() == 0


def test_processing_run_wrong_document_remains_persistence_boundary(session) -> None:
    add_doc(session); add_source(session)
    add_doc(session, 'other-doc')
    ProcessingRunRepository().create_run(session, ProcessingRunCreate('other-run', 'other-doc'))
    candidate = transform('core_text', ctx(run='other-run'))
    assert candidate.processing_run_ref.value == 'other-run'
    with pytest.raises(CandidateProcessingRunMismatch):
        StructuredContentCandidateRepository().create_candidate(session, candidate)
    assert session.query(CandidateRow).count() == 0


def test_atomic_transform_failure_and_persistence_rollback_do_not_select(session) -> None:
    add_doc(session); add_source(session)
    bad = spr_dict('tables_assets')
    bad['nodes'][0]['table']['cells'][1]['column_index'] = 0
    with pytest.raises(TransformationInvariantViolation):
        transform_spr_to_candidate(StructuredProcessingResult(bad), context=ctx())
    assert session.query(CandidateRow).count() == 0
    assert session.query(StructuredContentSelection).count() == 0
    ProcessingRunRepository().create_run(session, ProcessingRunCreate('run-persist', 'doc-persist', 'source-persist'))
    candidate = transform('core_text')
    StructuredContentCandidateRepository().create_candidate(session, candidate)
    session.rollback()
    assert session.query(CandidateRow).count() == 0
    assert session.query(StructuredContentSelection).count() == 0
