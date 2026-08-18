from dataclasses import replace
from datetime import datetime
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models import Base, Document, SourceFile, ProcessingRun, StructuredContentSelection
from app.processing_runs import *

def session():
 e=create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
 @event.listens_for(e,'connect')
 def fk(c,r): c.execute('PRAGMA foreign_keys=ON')
 Base.metadata.create_all(e); S=sessionmaker(bind=e); s=S(); return s,e

def add_doc(s,id): s.add(Document(id=id,title=id,file_type='pdf')); s.flush()
def add_sf(s,id,doc): s.add(SourceFile(id=id,document_id=doc,original_filename=id,file_type='pdf')); s.flush()

def test_create_get_list_idempotency_ownership_rollback_corruption_transitions_scale():
 s,e=session(); repo=ProcessingRunRepository(); add_doc(s,'d'); add_doc(s,'other'); add_sf(s,'sf','d')
 c=ProcessingRunCreate('run','d','sf',provider_ref='p',provider_model_ref='m',processing_policy_ref='pol',idempotency_key='idem',raw_result_ref='raw',structured_processing_result_ref='spr',metrics={'n':1},extensions={'x.y':'z'})
 out=repo.create_run(s,c); assert out.processing_run_ref=='run' and out.document_ref=='d' and out.source_file_ref=='sf'
 assert repo.get_run(s,'run')==out and repo.run_exists(s,'run') and not repo.run_exists(s,'missing')
 assert repo.create_run(s,c)==out and s.query(ProcessingRun).count()==1
 with pytest.raises(ProcessingRunConflict): repo.create_run(s, replace(c, provider_ref='different'))
 with pytest.raises(ProcessingRunDocumentNotFound): repo.create_run(s, ProcessingRunCreate('missing-doc','nope'))
 with pytest.raises(ProcessingRunSourceFileMismatch): repo.create_run(s, ProcessingRunCreate('bad-sf','d','missing'))
 add_sf(s,'sf-other','other')
 with pytest.raises(ProcessingRunSourceFileMismatch): repo.create_run(s, ProcessingRunCreate('bad-sf2','d','sf-other'))
 running=repo.mark_running(s,'run',started_at=datetime(2026,1,1)); assert running.status=='running' and running.started_at.year==2026
 succeeded=repo.mark_succeeded(s,'run',completed_at=datetime(2026,1,2)); assert succeeded.status=='succeeded' and succeeded.completed_at.year==2026
 with pytest.raises(ProcessingRunInvalidTransition): repo.mark_running(s,'run')
 assert s.query(StructuredContentSelection).count()==0
 s.execute(text("update processing_runs set metrics_json='{' where processing_run_id='run'")); s.flush()
 with pytest.raises(PersistedProcessingRunCorrupt): repo.get_run(s,'run')
 s.rollback(); add_doc(s,'bulk')
 for i in range(100): repo.create_run(s, ProcessingRunCreate(f'r{i:03}','bulk'))
 assert [x.processing_run_ref for x in repo.list_runs_for_document(s,'bulk')][:3]==['r000','r001','r002']
 assert repo.list_runs_for_document(s,'other')==()
 repo.create_run(s, ProcessingRunCreate('rollback','d')); assert repo.run_exists(s,'rollback'); s.rollback(); assert not repo.run_exists(s,'rollback')
 s.close(); e.dispose()
