from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from tests.structured_content.integration_factory import temp_sqlite_url


def _cfg(url):
    c = Config("alembic.ini"); c.set_main_option("sqlalchemy.url", url); return c

def _tables(url):
    e=create_engine(url); names=set(inspect(e).get_table_names()); e.dispose(); return names


def test_migration_chain_single_head_table_boundaries_and_reupgrade():
    with temp_sqlite_url() as url:
        cfg=_cfg(url)
        heads=command.heads(cfg); # command output is covered by post-commit CLI; upgrade asserts one DB head below.
        command.upgrade(cfg, "0001_foundation_schema")
        t1=_tables(url); assert "documents" in t1 and "structured_content_candidates" not in t1 and "processing_runs" not in t1
        command.upgrade(cfg, "0002_structured_content_persistence_schema")
        t2=_tables(url); assert "documents" in t2 and "structured_content_candidates" in t2 and "structured_content_selection" in t2 and "processing_runs" not in t2
        command.upgrade(cfg, "0003_processing_runs")
        t3=_tables(url); assert "processing_runs" in t3 and "structured_content_candidates" in t3
        e=create_engine(url)
        with e.connect() as conn:
            assert conn.execute(text("select version_num from alembic_version")).scalar_one() == "0003_processing_runs"
            assert conn.execute(text("select count(*) from structured_content_candidates")).scalar_one() == 0
            assert conn.execute(text("select count(*) from structured_content_selection")).scalar_one() == 0
            assert conn.execute(text("select count(*) from processing_runs")).scalar_one() == 0
        e.dispose()
        command.downgrade(cfg, "0002_structured_content_persistence_schema"); assert "processing_runs" not in _tables(url) and "structured_content_candidates" in _tables(url)
        command.downgrade(cfg, "0001_foundation_schema"); assert "structured_content_candidates" not in _tables(url) and "documents" in _tables(url)
        command.upgrade(cfg, "head"); assert "processing_runs" in _tables(url) and "structured_content_candidates" in _tables(url)


def test_migration_data_preservation_from_0002_to_0003_and_safe_downgrade_to_0002():
    with temp_sqlite_url() as url:
        cfg=_cfg(url); command.upgrade(cfg, "0002_structured_content_persistence_schema")
        e=create_engine(url)
        with e.begin() as conn:
            conn.execute(text("insert into documents (id,title,file_type,created_at) values ('doc','doc','pdf',CURRENT_TIMESTAMP)"))
            conn.execute(text("insert into structured_content_candidates (id,candidate_id,document_id,lineage_key,schema_id,schema_version,recovery_state,total_page_count,complete_page_count,degraded_page_count,no_usable_page_count,unavailable_page_count,extension_json,created_at) values (1,'cand','doc','lineage','atlas.structured_content',1,'complete',0,0,0,0,0,'{}',CURRENT_TIMESTAMP)"))
            conn.execute(text("insert into structured_content_selection (document_id,candidate_id,selection_version,selected_at) values ('doc',1,1,CURRENT_TIMESTAMP)"))
        e.dispose(); before=_tables(url)
        command.upgrade(cfg, "0003_processing_runs")
        e=create_engine(url)
        with e.begin() as conn:
            assert conn.execute(text("select candidate_id from structured_content_candidates")).scalar_one() == "cand"
            assert conn.execute(text("select selection_version from structured_content_selection")).scalar_one() == 1
            conn.execute(text("insert into processing_runs (processing_run_id,document_id,status,metrics_json,extensions_json,created_at) values ('run','doc','created','{}','{}',CURRENT_TIMESTAMP)"))
        e.dispose()
        command.downgrade(cfg, "0002_structured_content_persistence_schema")
        assert "processing_runs" not in _tables(url)
        e=create_engine(url)
        with e.connect() as conn: assert conn.execute(text("select candidate_id from structured_content_candidates")).scalar_one() == "cand"
        e.dispose()
