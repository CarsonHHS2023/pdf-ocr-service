"""Regression tests for the M1-002B Document/SourceFile schema cutover."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.models import Base, Bookshelf, Document, SourceFile


PROHIBITED_BOOKSHELF_QUERY_PATTERNS = (
    re.compile(r"\bdb\s*\.\s*query\s*\(\s*Bookshelf\s*\)"),
    re.compile(r"\bsession\s*\.\s*query\s*\(\s*Bookshelf\s*\)"),
    re.compile(r"\bselect\s*\(\s*Bookshelf\s*\)"),
)

# Keep this list narrow and tied to current persistence paths instead of scanning
# the whole repository for every textual mention of the compatibility name.
PRODUCTION_PERSISTENCE_MODULES = (
    Path("app/book_service.py"),
    Path("app/routers/books.py"),
    Path("app/routers/ocr.py"),
    Path("app/services/database_service.py"),
    Path("app/services/page_ocr_service.py"),
)


def test_bookshelf_is_document_alias_without_separate_metadata_table(tmp_path):
    """Bookshelf must remain only a Python alias for the Document table."""
    assert Bookshelf is Document
    assert Document.__table__.name == "documents"
    assert Bookshelf.__table__.name == "documents"
    assert SourceFile.__table__.name == "source_files"

    metadata_tables = set(Base.metadata.tables)
    assert "documents" in metadata_tables
    assert "source_files" in metadata_tables
    assert "bookshelf" not in metadata_tables
    assert "bookshelves" not in metadata_tables

    database_path = tmp_path / "foundation_schema.sqlite"
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        Base.metadata.create_all(bind=engine)
        physical_tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert "documents" in physical_tables
    assert "source_files" in physical_tables
    assert "bookshelf" not in physical_tables
    assert "bookshelves" not in physical_tables


def test_active_persistence_paths_do_not_query_bookshelf():
    """Document is the query model; Bookshelf is not an active persistence root."""
    violations: list[str] = []

    for module_path in PRODUCTION_PERSISTENCE_MODULES:
        source = module_path.read_text(encoding="utf-8")
        for pattern in PROHIBITED_BOOKSHELF_QUERY_PATTERNS:
            if pattern.search(source):
                violations.append(f"{module_path}: {pattern.pattern}")

    assert violations == []
