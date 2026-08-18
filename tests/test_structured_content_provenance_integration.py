from dataclasses import replace
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models import Base, Document, SourceFile, StructuredContentSelection
from app.processing_runs import ProcessingRunCreate, ProcessingRunRepository
from app.structured_content.identity import ContentCandidateId, ContentLineageKey, DocumentRef, ProcessingRunRef
from app.structured_content.repository import StructuredContentCandidateRepository
from app.structured_content.errors import CandidateProcessingRunMismatch
from app.structured_content.selection_repository import StructuredContentSelectionRepository
from tests.structured_content.candidate_factory import make_linear_candidate, make_asset_evidence_warning_candidate

def session():
 e=create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
 @event.listens_for(e,'connect')
 def fk(c,r): c.execute('PRAGMA foreign_keys=ON')
 Base.metadata.create_all(e); S=sessionmaker(bind=e); s=S(); return s,e

def add_doc(s,id): s.add(Document(id=id,title=id,file_type='pdf')); s.flush()
def add_sf(s,id,doc): s.add(SourceFile(id=id,document_id=doc,original_filename=id,file_type='pdf')); s.flush()

def with_run(c, ref): return replace(c, processing_run_ref=ProcessingRunRef(ref))

def test_candidate_run_validation_roundtrip_no_selection_and_status_independence():
 s,e=session(); crepo=StructuredContentCandidateRepository(); rrepo=ProcessingRunRepository(); c=make_linear_candidate(1,1); add_doc(s,c.document_ref.value); add_sf(s,'source-file',c.document_ref.value)
 assert crepo.create_candidate(s,c)==c
 with pytest.raises(CandidateProcessingRunMismatch): crepo.create_candidate(s, with_run(replace(c,candidate_id=ContentCandidateId('unknown'),lineage_key=ContentLineageKey('unknown')), 'missing'))
 run=rrepo.create_run(s, ProcessingRunCreate('run',c.document_ref.value,'source-file'))
 linked=with_run(replace(c,candidate_id=ContentCandidateId('linked'),lineage_key=ContentLineageKey('linked')), 'run')
 assert crepo.create_candidate(s, linked)==linked
 assert crepo.get_candidate(s, linked.candidate_id).processing_run_ref.value=='run'
 assert rrepo.get_run(s,'run')==run and s.query(StructuredContentSelection).count()==0
 rrepo.mark_running(s,'run'); rrepo.mark_succeeded(s,'run'); assert s.query(StructuredContentSelection).count()==0
 selected=StructuredContentSelectionRepository().set_selection(s, document_ref=c.document_ref, candidate_id=c.candidate_id, expected_version=0)
 rrepo.create_run(s, ProcessingRunCreate('newer',c.document_ref.value)); newer=with_run(replace(c,candidate_id=ContentCandidateId('newer-c'),lineage_key=ContentLineageKey('newer-c')), 'newer'); crepo.create_candidate(s,newer)
 assert StructuredContentSelectionRepository().get_selection(s,c.document_ref)==selected
 other=make_linear_candidate(1,1); add_doc(s,'other'); rrepo.create_run(s, ProcessingRunCreate('other-run','other'))
 with pytest.raises(CandidateProcessingRunMismatch): crepo.create_candidate(s, with_run(replace(c,candidate_id=ContentCandidateId('cross'),lineage_key=ContentLineageKey('cross')), 'other-run'))
 rrepo.create_run(s, ProcessingRunCreate('no-candidate',c.document_ref.value)); rrepo.mark_running(s,'no-candidate'); rrepo.mark_failed(s,'no-candidate',safe_error_code='safe')
 rrepo.create_run(s, ProcessingRunCreate('cancel',c.document_ref.value)); rrepo.mark_cancelled(s,'cancel')
 warning=with_run(replace(make_asset_evidence_warning_candidate(2,1,1), document_ref=c.document_ref, candidate_id=ContentCandidateId('warning'), lineage_key=ContentLineageKey('warning')), 'run')
 assert crepo.create_candidate(s, warning)==warning
 s.close(); e.dispose()
