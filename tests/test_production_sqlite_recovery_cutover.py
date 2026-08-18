from __future__ import annotations

import json
from pathlib import Path

import app.production_sqlite_recovery_cutover as cutover


def _write_marker(path: Path, **overrides: object) -> None:
    payload: dict[str, object] = {
        "format_version": 1,
        "incident_id": cutover.INCIDENT_ID,
        "status": "complete",
        "completed_at_utc": "2026-08-14T19:10:30.541191Z",
        "candidate_sha256": cutover.CANDIDATE_SHA256,
        "candidate_byte_size": cutover.CANDIDATE_BYTE_SIZE,
        "rollback_preserved": True,
        "rollback_database_filename": "pre-cutover-live-deadbeef.db",
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_completed_cutover_marker_is_reported_read_only(tmp_path: Path) -> None:
    marker = tmp_path / "complete.json"
    _write_marker(marker)

    result = cutover.production_sqlite_recovery_cutover_status(
        marker_path=marker,
        space_id=cutover.PRODUCTION_SPACE_ID,
    )

    assert result.status == "complete"
    assert result.candidate_sha256 == cutover.CANDIDATE_SHA256
    assert result.completed_at_utc == "2026-08-14T19:10:30.541191Z"
    assert result.rollback_preserved is True


def test_missing_or_invalid_marker_is_pending(tmp_path: Path) -> None:
    missing = cutover.production_sqlite_recovery_cutover_status(
        marker_path=tmp_path / "missing.json",
        space_id=cutover.PRODUCTION_SPACE_ID,
    )
    assert missing.status == "pending"

    marker = tmp_path / "invalid.json"
    _write_marker(marker, candidate_sha256="0" * 64)
    invalid = cutover.production_sqlite_recovery_cutover_status(
        marker_path=marker,
        space_id=cutover.PRODUCTION_SPACE_ID,
    )
    assert invalid.status == "pending"


def test_marker_rejects_unsafe_rollback_filename(tmp_path: Path) -> None:
    marker = tmp_path / "unsafe.json"
    _write_marker(marker, rollback_database_filename="../outside.db")

    result = cutover.production_sqlite_recovery_cutover_status(
        marker_path=marker,
        space_id=cutover.PRODUCTION_SPACE_ID,
    )

    assert result.status == "pending"


def test_cutover_status_is_not_applicable_outside_exact_production_space(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "complete.json"
    _write_marker(marker)

    result = cutover.production_sqlite_recovery_cutover_status(
        marker_path=marker,
        space_id="some-other/space",
    )

    assert result.status == "not_applicable"


def test_completed_incident_module_has_no_cutover_executor() -> None:
    assert not hasattr(cutover, "execute_production_sqlite_recovery_cutover")
    assert not hasattr(cutover, "ProductionSqliteRecoveryCutoverError")
