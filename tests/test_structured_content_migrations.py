"""Migration coverage for M4 Slice 2A Structured Content persistence."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

PREVIOUS_REVISION = "0001_foundation_schema"
NEW_REVISION = "0002_structured_content_persistence_schema"
STRUCTURED_TABLES = {
    "structured_content_candidates", "structured_content_pages", "structured_content_nodes", "structured_content_page_roots",
    "structured_content_evidence", "structured_content_warnings", "structured_content_assets", "structured_content_asset_renditions",
    "structured_content_page_evidence", "structured_content_page_warning", "structured_content_node_evidence", "structured_content_node_asset",
    "structured_content_node_warning", "structured_content_asset_evidence", "structured_content_warning_evidence", "structured_content_table_cells",
    "structured_content_selection",
}
LEGACY_TABLES = {"documents", "source_files", "ocr_tasks", "content_blocks", "book_images", "pdf_pages", "mineru_results"}


def _cfg(path: Path) -> Config:
    cfg = Config("alembic.ini"); cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path}"); return cfg


def _engine(path: Path):
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as c: c.execute(text("PRAGMA foreign_keys=ON"))
    return engine


def test_single_head_is_structured_content_revision(tmp_path):
    assert ScriptDirectory.from_config(_cfg(tmp_path / "heads.sqlite")).get_heads() == [NEW_REVISION]


def test_upgrade_downgrade_reupgrade_and_schema_invariants(tmp_path):
    path = tmp_path / "m4_slice_2a.sqlite"; cfg = _cfg(path)
    command.upgrade(cfg, PREVIOUS_REVISION)
    e = _engine(path); before = set(inspect(e).get_table_names()); e.dispose()
    assert LEGACY_TABLES <= before and STRUCTURED_TABLES.isdisjoint(before)

    command.upgrade(cfg, "head")
    e = _engine(path); i = inspect(e); tables = set(i.get_table_names())
    assert STRUCTURED_TABLES <= tables and LEGACY_TABLES <= tables
    assert i.get_unique_constraints("structured_content_candidates")
    assert i.get_unique_constraints("structured_content_pages")
    assert i.get_unique_constraints("structured_content_nodes")
    assert {fk["referred_table"] for fk in i.get_foreign_keys("structured_content_selection")} == {"documents", "structured_content_candidates"}
    assert "ix_sc_pages_candidate_order" in {ix["name"] for ix in i.get_indexes("structured_content_pages")}
    with e.begin() as c:
        c.execute(text("PRAGMA foreign_keys=ON"))
        c.execute(text("insert into documents (id, document_type, title, file_type, status, created_at, updated_at) values ('doc','book','Doc','pdf','processing',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        c.execute(text("insert into structured_content_candidates (id,candidate_id,document_id,lineage_key,schema_id,schema_version,recovery_state,total_page_count,complete_page_count,degraded_page_count,no_usable_page_count,unavailable_page_count,unsupported_page_count,created_at) values ('c','cand','doc','line','atlas.structured-content-candidate',1,'complete',1,1,0,0,0,0,CURRENT_TIMESTAMP)"))
        c.execute(text("insert into structured_content_pages (id,candidate_id,page_id,page_order,source_page_index,recovery_state) values ('p','c','page',0,0,'complete')"))
        c.execute(text("insert into structured_content_nodes (id,candidate_id,page_id,node_id,lineage_key,node_type,sibling_order,recovery_state) values ('n','c','p','node','node-line','paragraph',0,'complete')"))
        c.execute(text("insert into structured_content_page_roots (id,candidate_id,page_id,node_id,root_order) values ('r','c','p','n',0)"))
        assert c.execute(text("select count(*) from structured_content_selection")).scalar_one() == 0
    e.dispose()

    command.downgrade(cfg, PREVIOUS_REVISION)
    e = _engine(path); after = set(inspect(e).get_table_names()); e.dispose()
    assert LEGACY_TABLES <= after and STRUCTURED_TABLES.isdisjoint(after)
    command.upgrade(cfg, "head")
    e = _engine(path); assert STRUCTURED_TABLES <= set(inspect(e).get_table_names()); e.dispose()
