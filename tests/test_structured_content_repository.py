from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document, StructuredContentSelection, StructuredContentCandidate as CandidateRow, StructuredContentNode, encode_json_text
from app.structured_content.identity import ContentCandidateId, ContentLineageKey, DocumentRef
from app.structured_content.repository import StructuredContentCandidateRepository
from app.structured_content.errors import InvalidStructuredContentCandidate, StructuredContentCandidateConflict, PersistedCandidateCorrupt
from app.structured_content.serialization import serialize_structured_content_candidate
from app.structured_content.validation import validate_content_candidate
from tests.structured_content.fixture_loader import load_candidate
from tests.structured_content.candidate_factory import make_linear_candidate, make_table_candidate, make_asset_evidence_warning_candidate

VALID = sorted(Path('tests/fixtures/structured_content/v1/valid').glob('*/candidate.json'))
INVALID = sorted(Path('tests/fixtures/structured_content/v1/invalid').glob('*/candidate.json'))

@pytest.fixture()
def session():
    engine=create_engine('sqlite:///:memory:', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    @event.listens_for(engine,'connect')
    def fk(conn, rec): conn.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine); Session=sessionmaker(bind=engine); s=Session()
    try: yield s
    finally: s.close(); engine.dispose()

def add_doc(s, doc_id):
    s.add(Document(id=doc_id, title=doc_id, file_type='pdf')); s.flush()

def counts(s):
    return s.query(CandidateRow).count(), s.query(StructuredContentSelection).count()

@pytest.mark.parametrize('path', VALID, ids=lambda p:p.parent.name)
def test_valid_fixture_round_trips_canonically_without_selection(session, path):
    repo=StructuredContentCandidateRepository(); c=load_candidate(path); add_doc(session, c.document_ref.value)
    out=repo.create_candidate(session,c); session.commit()
    got=repo.get_candidate(session,c.candidate_id)
    assert out == c
    assert got == c
    assert serialize_structured_content_candidate(got) == serialize_structured_content_candidate(c)
    assert validate_content_candidate(got).is_valid
    assert session.query(StructuredContentSelection).count() == 0
    assert repo.get_candidate(session,c.candidate_id) == got

@pytest.mark.parametrize('path', INVALID, ids=lambda p:p.parent.name)
def test_invalid_fixtures_rejected_before_persistence(session, path):
    repo=StructuredContentCandidateRepository(); c=load_candidate(path); add_doc(session, c.document_ref.value)
    before=counts(session)
    with pytest.raises(InvalidStructuredContentCandidate): repo.create_candidate(session,c)
    assert counts(session)==before
    session.rollback(); add_doc(session,'usable-doc')

def test_idempotent_retry_and_conflict(session):
    repo=StructuredContentCandidateRepository(); c=make_linear_candidate(1,2); add_doc(session,c.document_ref.value)
    first=repo.create_candidate(session,c); created=repo._row(session,c.candidate_id.value).created_at; row_count=session.query(CandidateRow).count()
    second=repo.create_candidate(session,c)
    assert first == second == c
    assert session.query(CandidateRow).count()==row_count
    assert repo._row(session,c.candidate_id.value).created_at == created
    changed=replace(c, lineage_key=ContentLineageKey('different-lineage'))
    with pytest.raises(StructuredContentCandidateConflict): repo.create_candidate(session, changed)
    assert serialize_structured_content_candidate(repo.get_candidate(session,c.candidate_id)) == serialize_structured_content_candidate(c)
    assert session.query(StructuredContentSelection).count()==0

def test_listing_existence_ownership(session):
    repo=StructuredContentCandidateRepository(); c1=make_linear_candidate(1,1); c2=replace(make_linear_candidate(1,1), candidate_id=ContentCandidateId('candidate-two'), lineage_key=ContentLineageKey('same-lineage'))
    add_doc(session,c1.document_ref.value); add_doc(session,'other')
    assert not repo.candidate_exists(session,c1.candidate_id)
    repo.create_candidate(session,c1); repo.create_candidate(session,c2); session.commit()
    assert repo.candidate_exists(session,c1.candidate_id)
    assert repo.candidate_belongs_to_document(session,c1.candidate_id,c1.document_ref)
    assert not repo.candidate_belongs_to_document(session,c1.candidate_id,DocumentRef('other'))
    assert [x.candidate_id for x in repo.list_candidates_for_document(session,c1.document_ref)] == ['candidate-linear','candidate-two']
    assert repo.list_candidates_for_document(session,DocumentRef('other')) == ()
    assert all(not hasattr(x,'selected') and not hasattr(x,'current') and not hasattr(x,'id') for x in repo.list_candidates_for_document(session,c1.document_ref))

def test_caller_rollback_removes_graph(session):
    repo=StructuredContentCandidateRepository(); c=make_linear_candidate(2,2); add_doc(session,c.document_ref.value)
    repo.create_candidate(session,c); assert session.query(CandidateRow).count()==1
    session.rollback()
    assert session.query(CandidateRow).count()==0
    assert session.query(StructuredContentSelection).count()==0

def test_corrupt_attribute_json_detected(session):
    repo=StructuredContentCandidateRepository(); c=make_table_candidate(2,2); add_doc(session,c.document_ref.value); repo.create_candidate(session,c); session.commit()
    n=session.query(StructuredContentNode).filter_by(node_type='table').one(); n.attribute_json='{'; session.commit()
    with pytest.raises(PersistedCandidateCorrupt): repo.get_candidate(session,c.candidate_id)

def test_scale_round_trips(session):
    repo=StructuredContentCandidateRepository()
    for c in [make_linear_candidate(100,10), make_table_candidate(50,10), make_asset_evidence_warning_candidate(100,50,50)]:
        c=replace(c, candidate_id=ContentCandidateId(c.candidate_id.value+'-scale'), document_ref=DocumentRef(c.document_ref.value+'-scale'))
        add_doc(session,c.document_ref.value); repo.create_candidate(session,c); session.commit()
        assert serialize_structured_content_candidate(repo.get_candidate(session,c.candidate_id)) == serialize_structured_content_candidate(c)
        assert session.query(StructuredContentSelection).count()==0
