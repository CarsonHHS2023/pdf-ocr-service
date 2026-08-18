"""Configuration regressions for the PostgreSQL stabilization path."""
from __future__ import annotations

import app.database as database


def test_provider_postgresql_urls_use_explicit_psycopg3_dialect():
    assert (
        database.normalize_database_url("postgresql://user:pass@db.example/atlas")
        == "postgresql+psycopg://user:pass@db.example/atlas"
    )
    assert (
        database.normalize_database_url("postgres://user:pass@db.example/atlas")
        == "postgresql+psycopg://user:pass@db.example/atlas"
    )


def test_explicit_database_drivers_are_not_rewritten():
    explicit = "postgresql+psycopg://user:pass@db.example/atlas"
    assert database.normalize_database_url(explicit) == explicit
    legacy_explicit = "postgresql+psycopg2://user:pass@db.example/atlas"
    assert database.normalize_database_url(legacy_explicit) == legacy_explicit


def test_non_postgresql_urls_are_not_rewritten():
    sqlite_url = "sqlite:///./ocr_tasks.db"
    assert database.normalize_database_url(sqlite_url) == sqlite_url


def test_alembic_config_preserves_percent_encoded_credentials(monkeypatch):
    url = "postgresql+psycopg://atlas:p%25ss@db.example/atlas"
    monkeypatch.setattr(database, "DATABASE_URL", url)
    config = database.alembic_config()
    assert config.get_main_option("sqlalchemy.url") == url
