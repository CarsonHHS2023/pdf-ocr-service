from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document, StructuredContentSelection, StructuredContentCandidate as CandidateRow, StructuredContentNode
from app.structured_content.identity import ContentCandidateId, ContentLineageKey, DocumentRef
from app.structured_content.repository import StructuredContentCandidateRepository
from app.structured_content.selection_repository import StructuredContentSelectionRepository
from app.structured_content.selection_service import StructuredContentSelectionService
from app.structured_content.selection_types import StructuredContentSelectionState
from app.structured_content.errors import (
    CandidateNotSelectable,
    CandidateSelectionConflict,
    CandidateSelectionDocumentMismatch,
)
from tests.structured_content.candidate_factory import make_linear_candidate, make_table_candidate, make_asset_evidence_warning_candidate


@pytest.fixture()
def session():
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    @event.listens_for(engine, 'connect')
    def fk(conn, rec): conn.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close(); engine.dispose()


def add_doc(s, doc_id):
    s.add(Document(id=doc_id, title=doc_id, file_type='pdf')); s.flush()


def persist(s, candidate):
    add_doc(s, candidate.document_ref.value)
    StructuredContentCandidateRepository().create_candidate(s, candidate)
    return candidate


def variant(candidate, suffix):
    return replace(candidate, candidate_id=ContentCandidateId(f'{candidate.candidate_id.value}-{suffix}'), lineage_key=ContentLineageKey(f'{candidate.lineage_key.value}-{suffix}'))


def row_snapshot(s, candidate):
    r = s.query(CandidateRow).filter_by(candidate_id=candidate.candidate_id.value).one()
    return (r.id, r.candidate_id, r.document_id, r.created_at, s.query(StructuredContentNode).filter_by(candidate_id=r.id).count())


def test_zero_selection_remains_valid_after_candidate_creation_and_listing(session):
    c1 = persist(session, make_linear_candidate(1, 1))
    c2 = variant(c1, 'two')
    StructuredContentCandidateRepository().create_candidate(session, c2)
    repo = StructuredContentSelectionRepository()
    assert repo.get_selection(session, c1.document_ref) is None
    assert repo.get_selected_candidate(session, c1.document_ref) is None
    assert StructuredContentCandidateRepository().list_candidates_for_document(session, c1.document_ref)
    assert session.query(StructuredContentSelection).count() == 0


def test_first_selection_returns_dto_and_does_not_mutate_candidate(session):
    c = persist(session, make_linear_candidate(2, 2))
    before = row_snapshot(session, c)
    state = StructuredContentSelectionRepository().set_selection(session, document_ref=c.document_ref, candidate_id=c.candidate_id, expected_version=0, selected_by='user-α', reason='manual ✓')
    assert isinstance(state, StructuredContentSelectionState)
    assert state.document_ref == c.document_ref.value
    assert state.candidate_id == c.candidate_id.value
    assert state.selection_version == 1
    assert state.selected_by == 'user-α'
    assert state.reason == 'manual ✓'
    assert StructuredContentSelectionRepository().get_selected_candidate(session, c.document_ref) == c
    assert row_snapshot(session, c) == before
    assert not hasattr(c, 'selected') and not hasattr(c, 'current') and not hasattr(c, 'accepted')


def test_replacement_and_explicit_rollback_keep_one_selection_and_immutable_candidates(session):
    a = persist(session, make_linear_candidate(2, 2))
    b = variant(a, 'b'); StructuredContentCandidateRepository().create_candidate(session, b)
    repo = StructuredContentSelectionRepository()
    snap_a = row_snapshot(session, a); snap_b = row_snapshot(session, b)
    assert repo.set_selection(session, document_ref=a.document_ref, candidate_id=a.candidate_id, expected_version=0).selection_version == 1
    second = repo.set_selection(session, document_ref=a.document_ref, candidate_id=b.candidate_id, expected_version=1)
    assert second.selection_version == 2 and second.candidate_id == b.candidate_id.value
    third = repo.rollback_selection(session, document_ref=a.document_ref, candidate_id=a.candidate_id, expected_version=2)
    assert third.selection_version == 3 and third.candidate_id == a.candidate_id.value
    assert session.query(StructuredContentSelection).count() == 1
    assert session.query(CandidateRow).count() == 2
    assert row_snapshot(session, a) == snap_a and row_snapshot(session, b) == snap_b


def test_stale_replacement_and_first_selection_race_conflict_deterministically(session):
    a = persist(session, make_linear_candidate(1, 1))
    b = variant(a, 'b'); c = variant(a, 'c')
    crepo = StructuredContentCandidateRepository(); crepo.create_candidate(session, b); crepo.create_candidate(session, c)
    repo = StructuredContentSelectionRepository()
    assert repo.set_selection(session, document_ref=a.document_ref, candidate_id=a.candidate_id, expected_version=0).selection_version == 1
    observed = repo.get_selection(session, a.document_ref).selection_version
    repo.set_selection(session, document_ref=a.document_ref, candidate_id=b.candidate_id, expected_version=observed)
    with pytest.raises(CandidateSelectionConflict) as exc:
        repo.set_selection(session, document_ref=a.document_ref, candidate_id=c.candidate_id, expected_version=observed)
    assert exc.value.expected_version == 1 and exc.value.actual_version == 2
    assert repo.get_selection(session, a.document_ref).candidate_id == b.candidate_id.value
    new_doc = 'race-doc'; add_doc(session, new_doc)
    d = replace(make_linear_candidate(1, 1), document_ref=DocumentRef(new_doc), candidate_id=ContentCandidateId('race-a'), lineage_key=ContentLineageKey('race-a'))
    e = replace(d, candidate_id=ContentCandidateId('race-b'), lineage_key=ContentLineageKey('race-b'))
    crepo.create_candidate(session, d); crepo.create_candidate(session, e)
    repo.set_selection(session, document_ref=new_doc, candidate_id=d.candidate_id, expected_version=0)
    with pytest.raises(CandidateSelectionConflict):
        repo.set_selection(session, document_ref=new_doc, candidate_id=e.candidate_id, expected_version=0)
    assert session.query(StructuredContentSelection).filter_by(document_id=new_doc).count() == 1


def test_same_candidate_idempotency_does_not_change_version_or_metadata(session):
    c = persist(session, make_linear_candidate(1, 1)); repo = StructuredContentSelectionRepository()
    first = repo.set_selection(session, document_ref=c.document_ref, candidate_id=c.candidate_id, expected_version=0, selected_by='one', reason='first')
    again = repo.set_selection(session, document_ref=c.document_ref, candidate_id=c.candidate_id, expected_version=1, selected_by='two', reason='changed')
    assert again == first
    assert repo.get_selection(session, c.document_ref).selection_version == 1
    with pytest.raises(CandidateSelectionConflict):
        repo.set_selection(session, document_ref=c.document_ref, candidate_id=c.candidate_id, expected_version=0)


def test_cross_document_rejection_preserves_existing_selection(session):
    a = persist(session, make_linear_candidate(1, 1))
    b = replace(make_linear_candidate(1, 1), document_ref=DocumentRef('doc-b'), candidate_id=ContentCandidateId('cand-b'), lineage_key=ContentLineageKey('lineage-b'))
    persist(session, b)
    repo = StructuredContentSelectionRepository(); repo.set_selection(session, document_ref=b.document_ref, candidate_id=b.candidate_id, expected_version=0)
    before = repo.get_selection(session, b.document_ref)
    with pytest.raises(CandidateSelectionDocumentMismatch):
        repo.set_selection(session, document_ref=b.document_ref, candidate_id=a.candidate_id, expected_version=1)
    assert repo.get_selection(session, b.document_ref) == before
    assert session.query(StructuredContentSelection).filter_by(document_id=b.document_ref.value).count() == 1


def test_corrupt_candidate_not_selectable_and_selection_unchanged(session):
    a = persist(session, make_table_candidate(2, 2))
    b = variant(a, 'b'); StructuredContentCandidateRepository().create_candidate(session, b)
    repo = StructuredContentSelectionRepository(); repo.set_selection(session, document_ref=a.document_ref, candidate_id=a.candidate_id, expected_version=0)
    n = session.query(StructuredContentNode).join(CandidateRow, StructuredContentNode.candidate_id == CandidateRow.id).filter(CandidateRow.candidate_id == b.candidate_id.value, StructuredContentNode.node_type == 'table').one()
    n.attribute_json = '{'; session.flush()
    with pytest.raises(CandidateNotSelectable):
        repo.set_selection(session, document_ref=a.document_ref, candidate_id=b.candidate_id, expected_version=1)
    assert repo.get_selection(session, a.document_ref).candidate_id == a.candidate_id.value


def test_degraded_no_usable_and_warning_rich_valid_candidates_are_selectable(session):
    base = persist(session, make_linear_candidate(3, 1))
    degraded = replace(base, candidate_id=ContentCandidateId('degraded'), lineage_key=ContentLineageKey('degraded'), recovery_summary=replace(base.recovery_summary, degraded_pages=1))
    warning = replace(make_asset_evidence_warning_candidate(3, 3, 3), document_ref=base.document_ref, candidate_id=ContentCandidateId('warning-rich'), lineage_key=ContentLineageKey('warning-rich'))
    crepo = StructuredContentCandidateRepository(); crepo.create_candidate(session, degraded); crepo.create_candidate(session, warning)
    repo = StructuredContentSelectionRepository()
    assert repo.set_selection(session, document_ref=base.document_ref, candidate_id=degraded.candidate_id, expected_version=0).candidate_id == 'degraded'
    assert repo.set_selection(session, document_ref=base.document_ref, candidate_id=warning.candidate_id, expected_version=1).candidate_id == 'warning-rich'


def test_outer_transaction_rollback_restores_prior_selection(session):
    c = persist(session, make_linear_candidate(1, 1)); repo = StructuredContentSelectionRepository()
    repo.set_selection(session, document_ref=c.document_ref, candidate_id=c.candidate_id, expected_version=0)
    assert repo.get_selection(session, c.document_ref) is not None
    session.rollback()
    assert session.query(CandidateRow).count() == 0
    assert repo.get_selection(session, c.document_ref) is None


def test_candidate_creation_after_selection_does_not_change_selection(session):
    a = persist(session, make_linear_candidate(1, 1)); repo = StructuredContentSelectionRepository()
    selected = repo.set_selection(session, document_ref=a.document_ref, candidate_id=a.candidate_id, expected_version=0)
    b = variant(a, 'new'); StructuredContentCandidateRepository().create_candidate(session, b)
    assert repo.get_selection(session, a.document_ref) == selected


def test_service_facade_and_no_automatic_helpers(session):
    c = persist(session, make_linear_candidate(1, 1)); service = StructuredContentSelectionService(session)
    assert service.get_selection(c.document_ref) is None
    assert service.select_candidate(c.document_ref, c.candidate_id, 0).selection_version == 1
    assert service.get_selected_candidate(c.document_ref) == c
    assert service.rollback_to_candidate(c.document_ref, c.candidate_id, 1).selection_version == 1
    public = set(dir(StructuredContentSelectionRepository)) | set(dir(StructuredContentSelectionService))
    forbidden = {'select_latest', 'promote_latest', 'auto_select', 'accept_latest', 'current_candidate_by_timestamp', 'choose_best_candidate'}
    assert public.isdisjoint(forbidden)
