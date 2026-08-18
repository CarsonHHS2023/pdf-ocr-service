from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest
from app.models import Base, Document, SourceFile, ProcessingRun, encode_json_text, decode_json_text

def db():
 e=create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
 @event.listens_for(e,'connect')
 def fk(c,r): c.execute('PRAGMA foreign_keys=ON')
 Base.metadata.create_all(e); S=sessionmaker(bind=e); s=S(); return s,e

def test_processing_run_schema_minimal_constraints_and_absent_payloads():
 s,e=db(); s.add(Document(id='d',title='d',file_type='pdf')); s.flush(); sf=SourceFile(id='sf',document_id='d',original_filename='a.pdf',file_type='pdf'); s.add(sf); s.flush()
 s.add(ProcessingRun(processing_run_id='run',document_id='d',source_file_id='sf',status='created',metrics_json=encode_json_text({'b':2,'a':1}),extensions_json=encode_json_text({'x.y':True}))); s.commit()
 r=s.query(ProcessingRun).one(); assert decode_json_text(r.metrics_json)=={'a':1,'b':2}; assert r.source_file.id=='sf'
 cols={c['name'] for c in inspect(e).get_columns('processing_runs')}
 assert cols.isdisjoint({'provider_payload','payload','pages','nodes','content_blocks','table_cells','selected','current','accepted','reader','projection','queue_lease','heartbeat','retry_schedule'})
 assert {'ix_processing_runs_document_created','ix_processing_runs_source_file_id'} <= {i['name'] for i in inspect(e).get_indexes('processing_runs')}
 assert any(fk['referred_table']=='documents' for fk in inspect(e).get_foreign_keys('processing_runs'))
 with pytest.raises(IntegrityError): s.add(ProcessingRun(processing_run_id='run',document_id='d',status='created')); s.commit()
 s.rollback();
 with pytest.raises(IntegrityError): s.add(ProcessingRun(processing_run_id='bad',document_id='missing',status='created')); s.commit()
 s.rollback();
 with pytest.raises(IntegrityError): s.add(ProcessingRun(processing_run_id='bad-status',document_id='d',status='weird')); s.commit()
 s.close(); e.dispose()
