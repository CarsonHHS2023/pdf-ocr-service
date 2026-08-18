from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app import production_sqlite_recovery_cutover_base as base
import app.production_sqlite_second_recovery_cutover as recovery


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_db(path: Path, value: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample(value) VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def _candidate_manifest(path: Path, *, sha256: str, byte_size: int, remote_path: str) -> None:
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "incident_id": base.INCIDENT_ID,
                "status": "validated_recovery_candidate",
                "candidate_remote_path": remote_path,
                "candidate_byte_size": byte_size,
                "candidate_sha256": sha256,
                "candidate_readback_verified": True,
                "validation_contract": {
                    "quick_check": "ok",
                    "integrity_check": "ok",
                    "foreign_key_violation_count": 0,
                    "alembic_head_match": True,
                    "reader_v2_selected_document_count": 7,
                    "reader_v2_unselected_not_ready_count": 1,
                    "orm_flush_rollback": "ok",
                },
            }
        ),
        encoding="utf-8",
    )


def _snapshot_manifest(
    path: Path,
    *,
    remote_path: str,
    xet_hash: str,
    byte_size: int,
) -> None:
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "incident_id": recovery.INCIDENT_ID,
                "status": "complete",
                "source_bucket": "carsonhhs/pdf-ocr-service-storage",
                "source_path": "ocr_tasks.db",
                "source_xet_hash": xet_hash,
                "source_size": byte_size,
                "snapshot_path": remote_path,
                "snapshot_xet_hash": xet_hash,
                "snapshot_size": byte_size,
                "readback_verified": True,
                "source_mutated": False,
            }
        ),
        encoding="utf-8",
    )


def _configure_fixture(tmp_path: Path, monkeypatch):
    live = tmp_path / "live.db"
    candidate = tmp_path / "candidate.db"
    snapshot = tmp_path / "snapshot.db"
    candidate_manifest = tmp_path / "candidate.json"
    snapshot_manifest = tmp_path / "snapshot.json"
    cutover_root = tmp_path / "cutovers"
    marker = cutover_root / "complete.json"

    _make_db(live, "damaged-live-placeholder")
    _make_db(candidate, "validated-recovery")
    shutil.copy2(live, snapshot)

    live_sha = _sha256(live)
    live_size = live.stat().st_size
    candidate_sha = _sha256(candidate)
    candidate_size = candidate.stat().st_size
    xet_hash = "a" * 64
    candidate_remote = "database-recovery-candidates/test/candidate.db"
    snapshot_remote = "database-backups/test/snapshot.db"

    monkeypatch.setattr(recovery, "EXPECTED_DAMAGED_LIVE_SHA256", live_sha)
    monkeypatch.setattr(recovery, "EXPECTED_DAMAGED_LIVE_BYTE_SIZE", live_size)
    monkeypatch.setattr(recovery, "EXPECTED_DAMAGED_LIVE_XET_HASH", xet_hash)
    monkeypatch.setattr(recovery, "CANDIDATE_SHA256", candidate_sha)
    monkeypatch.setattr(recovery, "CANDIDATE_BYTE_SIZE", candidate_size)
    monkeypatch.setattr(recovery, "CANDIDATE_REMOTE_PATH", candidate_remote)
    monkeypatch.setattr(recovery, "IMMUTABLE_SNAPSHOT_REMOTE_PATH", snapshot_remote)
    monkeypatch.setattr(base, "_sqlite_database_path", lambda _engine: live)

    _candidate_manifest(
        candidate_manifest,
        sha256=candidate_sha,
        byte_size=candidate_size,
        remote_path=candidate_remote,
    )
    _snapshot_manifest(
        snapshot_manifest,
        remote_path=snapshot_remote,
        xet_hash=xet_hash,
        byte_size=live_size,
    )

    return {
        "live": live,
        "candidate": candidate,
        "snapshot": snapshot,
        "candidate_manifest": candidate_manifest,
        "snapshot_manifest": snapshot_manifest,
        "cutover_root": cutover_root,
        "marker": marker,
        "live_sha": live_sha,
        "live_size": live_size,
        "candidate_sha": candidate_sha,
    }


def _execute(files, engine):
    return recovery.execute_production_sqlite_second_recovery_cutover(
        target_engine=engine,
        candidate_path=files["candidate"],
        candidate_manifest_path=files["candidate_manifest"],
        snapshot_path=files["snapshot"],
        snapshot_manifest_path=files["snapshot_manifest"],
        cutover_root=files["cutover_root"],
        marker_path=files["marker"],
        expected_live_sha256=files["live_sha"],
        expected_live_byte_size=files["live_size"],
        space_id=recovery.PRODUCTION_SPACE_ID,
    )


def test_second_recovery_replaces_exact_audited_live_and_is_idempotent(tmp_path, monkeypatch):
    files = _configure_fixture(tmp_path, monkeypatch)
    engine = create_engine(f"sqlite:///{files['live']}")

    result = _execute(files, engine)

    assert result.status == "complete"
    assert result.rollback_preserved is True
    assert _sha256(files["live"]) == files["candidate_sha"]
    rollback = files["cutover_root"] / f"pre-cutover-live-{files['live_sha']}.db"
    assert rollback.is_file()
    assert _sha256(rollback) == files["live_sha"]
    assert files["marker"].is_file()

    second = _execute(files, engine)
    assert second.status == "complete"
    assert _sha256(files["live"]) == files["candidate_sha"]


def test_second_recovery_refuses_live_changed_after_audit(tmp_path, monkeypatch):
    files = _configure_fixture(tmp_path, monkeypatch)
    engine = create_engine(f"sqlite:///{files['live']}")

    with sqlite3.connect(files["live"]) as connection:
        connection.execute("INSERT INTO sample(value) VALUES ('changed-after-audit')")
        connection.commit()
    changed_sha = _sha256(files["live"])
    assert changed_sha != files["live_sha"]

    with pytest.raises(recovery.ProductionSqliteSecondRecoveryError, match="changed since read-only audit"):
        _execute(files, engine)

    assert _sha256(files["live"]) == changed_sha
    assert not files["marker"].exists()


def test_second_recovery_refuses_snapshot_that_does_not_match_live(tmp_path, monkeypatch):
    files = _configure_fixture(tmp_path, monkeypatch)
    engine = create_engine(f"sqlite:///{files['live']}")
    with sqlite3.connect(files["snapshot"]) as connection:
        connection.execute("INSERT INTO sample(value) VALUES ('not-the-live-snapshot')")
        connection.commit()

    with pytest.raises(recovery.ProductionSqliteSecondRecoveryError, match="Immutable snapshot SHA-256 mismatch"):
        _execute(files, engine)

    assert _sha256(files["live"]) == files["live_sha"]
    assert not files["marker"].exists()


def test_second_recovery_restores_previous_live_if_post_replace_validation_fails(
    tmp_path, monkeypatch
):
    files = _configure_fixture(tmp_path, monkeypatch)
    engine = create_engine(f"sqlite:///{files['live']}")
    real_validate = base._validate_sqlite_clean
    calls = {"count": 0}

    def fail_second_validation(path: Path) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise base.ProductionSqliteRecoveryCutoverError("forced post-replace failure")
        real_validate(path)

    monkeypatch.setattr(base, "_validate_sqlite_clean", fail_second_validation)

    with pytest.raises(base.ProductionSqliteRecoveryCutoverError, match="forced post-replace failure"):
        _execute(files, engine)

    assert _sha256(files["live"]) == files["live_sha"]
    assert not files["marker"].exists()


def test_second_recovery_is_not_applicable_outside_exact_production_space(tmp_path):
    live = tmp_path / "live.db"
    _make_db(live, "unchanged")
    engine = create_engine(f"sqlite:///{live}")
    before = _sha256(live)

    result = recovery.execute_production_sqlite_second_recovery_cutover(
        target_engine=engine,
        candidate_path=tmp_path / "missing-candidate.db",
        candidate_manifest_path=tmp_path / "missing-candidate.json",
        snapshot_path=tmp_path / "missing-snapshot.db",
        snapshot_manifest_path=tmp_path / "missing-snapshot.json",
        cutover_root=tmp_path / "cutovers",
        marker_path=tmp_path / "marker.json",
        space_id="some-other/space",
    )

    assert result.status == "not_applicable"
    assert _sha256(live) == before
