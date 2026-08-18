from alembic.config import Config
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from pathlib import Path

def cfg(url):
 c=Config('alembic.ini'); c.set_main_option('script_location','alembic'); c.set_main_option('sqlalchemy.url',url); return c

def test_processing_run_migration_upgrade_downgrade_reupgrade(tmp_path):
 url=f"sqlite:///{tmp_path/'m.db'}"; c=cfg(url); script=ScriptDirectory.from_config(c)
 assert len(script.get_heads())==1
 command.upgrade(c,'0002_structured_content_persistence_schema')
 e=create_engine(url); insp=inspect(e); assert 'structured_content_candidates' in insp.get_table_names(); assert 'processing_runs' not in insp.get_table_names()
 with e.begin() as conn:
  conn.execute(text("insert into documents (id,document_type,title,file_type,status,created_at,updated_at) values ('d','book','d','pdf','processing',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
 e.dispose()
 command.upgrade(c,'head'); e=create_engine(url); insp=inspect(e)
 assert 'processing_runs' in insp.get_table_names() and 'structured_content_selection' in insp.get_table_names()
 assert {'ix_processing_runs_document_created','ix_processing_runs_source_file_id'} <= {i['name'] for i in insp.get_indexes('processing_runs')}
 with e.connect() as conn: assert conn.execute(text('select count(*) from processing_runs')).scalar()==0
 e.dispose(); command.downgrade(c,'0002_structured_content_persistence_schema')
 e=create_engine(url); insp=inspect(e); assert 'processing_runs' not in insp.get_table_names(); assert 'structured_content_candidates' in insp.get_table_names(); e.dispose()
 command.upgrade(c,'head'); e=create_engine(url); assert 'processing_runs' in inspect(e).get_table_names(); e.dispose()
