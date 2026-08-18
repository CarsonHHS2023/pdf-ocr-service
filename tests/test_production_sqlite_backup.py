from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine

from app.access_middleware import is_public_access_path
from app.production_sqlite_backup import (
    INCIDENT_ID,
    PRODUCTION_SPACE_ID,
    create_production_pre_recovery_backup,
    production_sqlite_backup_status,
)


def _create_live_database(path: Path):
    target_engine = create_engine(f"sqlite:///{path}")
    with target_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.exec_driver_sql("INSERT INTO sample (value) VALUES ('before')")
    return target_engine


def test_non_production_environment_does_not_create_backup(tmp_path: Path) -> None:
    live = tmp_path / "live.db"
    target_engine = _create_live_database(live)
    backup_root = tmp_path / "backups"

    result = create_production_pre_recovery_backup(
        target_engine=target_engine,
        backup_root=backup_root,
        space_id="someone/example-space",
    )

    assert result.status == "not_applicable"
    assert result.incident_id == INCIDENT_ID
    assert backup_root.exists() is False


def test_production_backup_is_verified_immutable_and_idempotent(tmp_path: Path) -> None:
    live = tmp_path / "live.db"
    target_engine = _create_live_database(live)
    backup_root = tmp_path / "backups"

    first = create_production_pre_recovery_backup(
        target_engine=target_engine,
        backup_root=backup_root,
        space_id=PRODUCTION_SPACE_ID,
    )

    assert first.status == "complete"
    assert first.readback_verified is True
    assert first.quick_check == "ok"
    assert first.byte_size is not None and first.byte_size > 0
    assert first.sha256 is not None and len(first.sha256) == 64

    manifest_path = backup_root / f"{INCIDENT_ID}.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshot = backup_root / payload["snapshot_filename"]
    assert snapshot.is_file()
    assert snapshot.stat().st_size == first.byte_size

    with sqlite3.connect(str(snapshot)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 1

    # The backup operation itself must not make the live database read-only or
    # otherwise change normal application writes.
    with target_engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO sample (value) VALUES ('after')")
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM sample").scalar_one() == 2

    second = create_production_pre_recovery_backup(
        target_engine=target_engine,
        backup_root=backup_root,
        space_id=PRODUCTION_SPACE_ID,
    )

    assert second == first
    assert len(list(backup_root.glob("*.db"))) == 1
    with sqlite3.connect(str(snapshot)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 1


def test_backup_health_status_is_sanitized(tmp_path: Path) -> None:
    live = tmp_path / "live.db"
    target_engine = _create_live_database(live)
    backup_root = tmp_path / "backups"
    create_production_pre_recovery_backup(
        target_engine=target_engine,
        backup_root=backup_root,
        space_id=PRODUCTION_SPACE_ID,
    )

    status = production_sqlite_backup_status(
        backup_root=backup_root,
        space_id=PRODUCTION_SPACE_ID,
    )
    public = status.as_dict()

    assert public["status"] == "complete"
    assert public["readback_verified"] is True
    assert "snapshot_filename" not in public
    assert "path" not in public


def test_database_backup_health_path_bypasses_shared_app_gate() -> None:
    assert is_public_access_path("/api/v1/health/database-backup", "GET") is True
    assert is_public_access_path("/api/v1/books", "GET") is False


def test_normal_startup_no_longer_runs_completed_recovery_backup(monkeypatch) -> None:
    import app.main as main_module

    assert not hasattr(main_module, "create_production_pre_recovery_backup")
    assert not hasattr(main_module, "execute_production_sqlite_recovery_cutover")

    events: list[str] = []
    monkeypatch.setattr(
        main_module,
        "validate_and_log_structure_refinement_config",
        lambda _logger: events.append("validate"),
    )
    monkeypatch.setattr(main_module, "init_db", lambda: events.append("init_db"))
    monkeypatch.setattr(
        main_module,
        "configure_application_logging",
        lambda: events.append("logging"),
    )
    monkeypatch.setattr(
        main_module,
        "install_refinement_provider_stderr_handler",
        lambda: events.append("stderr_handler"),
    )

    asyncio.run(main_module.startup_event())

    assert events == ["validate", "init_db", "logging", "stderr_handler"]
