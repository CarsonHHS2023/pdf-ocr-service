from __future__ import annotations

from sqlalchemy import create_engine

import app.database_integrity as database_integrity_module
from app.access_middleware import is_public_access_path
from app.database_integrity import (
    DatabaseIntegritySnapshot,
    _classify,
    database_integrity_snapshot,
)


def test_healthy_sqlite_snapshot_is_read_only_and_restores_connection_state() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.exec_driver_sql("INSERT INTO sample (value) VALUES ('before')")

    snapshot = database_integrity_snapshot(engine)

    assert snapshot.status == "healthy"
    assert snapshot.backend == "sqlite"
    assert snapshot.quick_check == "ok"
    assert snapshot.integrity_check == "ok"
    assert snapshot.classification == "ok"
    assert snapshot.issue_count == 0
    assert snapshot.truncated is False

    # The diagnostic temporarily enables SQLite query_only on its connection.
    # It must restore that connection-local state before returning it to the pool.
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO sample (value) VALUES ('after')")
        count = connection.exec_driver_sql("SELECT COUNT(*) FROM sample").scalar_one()
    assert count == 2


def test_production_integrity_scan_is_cached_per_process(monkeypatch) -> None:
    calls = 0
    expected = DatabaseIntegritySnapshot(
        status="healthy",
        backend="sqlite",
        quick_check="ok",
        integrity_check="ok",
        classification="ok",
        issue_count=0,
        truncated=False,
    )

    def fake_snapshot(_engine):
        nonlocal calls
        calls += 1
        return expected

    database_integrity_module.production_database_integrity_snapshot.cache_clear()
    monkeypatch.setattr(database_integrity_module, "database_integrity_snapshot", fake_snapshot)
    try:
        first = database_integrity_module.production_database_integrity_snapshot()
        second = database_integrity_module.production_database_integrity_snapshot()
    finally:
        database_integrity_module.production_database_integrity_snapshot.cache_clear()

    assert first is expected
    assert second is expected
    assert calls == 1


def test_classifier_identifies_narrow_index_only_case() -> None:
    classification, issue_count, truncated = _classify(
        ("ok",),
        ("row 12 missing from index ix_example",),
    )

    assert classification == "index_only"
    assert issue_count == 1
    assert truncated is False


def test_classifier_fails_closed_for_quick_check_issue() -> None:
    classification, issue_count, truncated = _classify(
        ("database disk image is malformed",),
        ("row 12 missing from index ix_example",),
    )

    assert classification == "table_or_page_or_unknown"
    assert issue_count == 1
    assert truncated is False


def test_classifier_fails_closed_for_non_index_integrity_issue() -> None:
    classification, issue_count, truncated = _classify(
        ("ok",),
        ("Page 42 is never used",),
    )

    assert classification == "table_or_page_or_unknown"
    assert issue_count == 1
    assert truncated is False


def test_database_integrity_health_path_bypasses_shared_app_gate() -> None:
    assert is_public_access_path("/api/v1/health/database-integrity", "GET") is True
    assert is_public_access_path("/api/v1/books", "GET") is False
