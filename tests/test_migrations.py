"""Lightweight regression tests for the Alembic foundation baseline."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.models import Base, Document, SourceFile
import app.models_v2  # noqa: F401  # register v2 tables on shared metadata
import app.models_v2_selection  # noqa: F401  # register v2 selection on shared metadata

EXPECTED_HEAD = "0005_structured_content_v2_selection"
EXPECTED_TABLES = {
    "alembic_version",
    "structured_content_candidates",
    "structured_content_pages",
    "structured_content_nodes",
    "structured_content_page_roots",
    "structured_content_evidence",
    "structured_content_warnings",
    "structured_content_assets",
    "structured_content_asset_renditions",
    "structured_content_page_evidence",
    "structured_content_page_warning",
    "structured_content_node_evidence",
    "structured_content_node_asset",
    "structured_content_node_warning",
    "structured_content_asset_evidence",
    "structured_content_warning_evidence",
    "structured_content_table_cells",
    "structured_content_selection",
    "structured_content_v2_candidates",
    "structured_content_v2_source_units",
    "structured_content_v2_nodes",
    "structured_content_v2_node_source_units",
    "structured_content_v2_evidence",
    "structured_content_v2_warnings",
    "structured_content_v2_assets",
    "structured_content_v2_asset_source_units",
    "structured_content_v2_asset_renditions",
    "structured_content_v2_anchors",
    "structured_content_v2_source_unit_evidence",
    "structured_content_v2_source_unit_warnings",
    "structured_content_v2_node_evidence",
    "structured_content_v2_node_assets",
    "structured_content_v2_node_warnings",
    "structured_content_v2_asset_evidence",
    "structured_content_v2_warning_evidence",
    "structured_content_v2_selection",
    "processing_runs",
    "book_images",
    "content_blocks",
    "documents",
    "mineru_results",
    "ocr_tasks",
    "pdf_pages",
    "source_files",
}
BASELINE_TABLES = EXPECTED_TABLES - {"alembic_version"}
PROHIBITED_TABLES = {"bookshelf", "bookshelves"}


def _config(database_path: Path) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return cfg


def _table_names(database_path: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_fresh_upgrade_creates_foundation_schema_without_bookshelf_tables(tmp_path):
    database_path = tmp_path / "fresh.sqlite"
    command.upgrade(_config(database_path), "head")
    tables = _table_names(database_path)
    assert EXPECTED_TABLES <= tables
    assert PROHIBITED_TABLES.isdisjoint(tables)


def test_revision_state_is_single_expected_head(tmp_path):
    database_path = tmp_path / "revision.sqlite"
    cfg = _config(database_path)
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == [EXPECTED_HEAD]
    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            current = connection.execute(text("select version_num from alembic_version")).scalar_one()
    finally:
        engine.dispose()
    assert current == EXPECTED_HEAD


def test_downgrade_base_and_reupgrade_round_trip(tmp_path):
    database_path = tmp_path / "roundtrip.sqlite"
    cfg = _config(database_path)
    command.upgrade(cfg, "head")
    assert BASELINE_TABLES <= _table_names(database_path)
    command.downgrade(cfg, "base")
    assert BASELINE_TABLES.isdisjoint(_table_names(database_path))
    command.upgrade(cfg, "head")
    assert BASELINE_TABLES <= _table_names(database_path)


def test_alembic_tables_match_current_metadata_at_maintainable_level(tmp_path):
    database_path = tmp_path / "parity.sqlite"
    command.upgrade(_config(database_path), "head")
    physical_tables = _table_names(database_path) - {"alembic_version"}
    metadata_tables = set(Base.metadata.tables)
    assert physical_tables == metadata_tables
    assert PROHIBITED_TABLES.isdisjoint(physical_tables)

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        document_columns = {column["name"]: column for column in inspector.get_columns("documents")}
        source_columns = {column["name"]: column for column in inspector.get_columns("source_files")}
        source_fks = inspector.get_foreign_keys("source_files")
    finally:
        engine.dispose()

    assert set(Document.__table__.columns.keys()) == set(document_columns)
    assert set(SourceFile.__table__.columns.keys()) == set(source_columns)
    assert document_columns["title"]["nullable"] is False
    assert source_columns["document_id"]["nullable"] is False
    assert [fk["referred_table"] for fk in source_fks] == ["documents"]
    assert [fk["referred_columns"] for fk in source_fks] == [["id"]]


def test_production_startup_schema_management_uses_alembic_not_create_all():
    source = Path("app/database.py").read_text(encoding="utf-8")
    assert "command.upgrade" in source
    assert ".create_all" not in source
