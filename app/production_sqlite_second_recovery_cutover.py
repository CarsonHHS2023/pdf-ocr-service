"""One-time fail-closed recovery for the second Production SQLite corruption.

The recovery is deliberately pinned to:
- the exact malformed live database audited on 2026-08-15;
- the immutable content-addressed snapshot of that malformed database; and
- the previously validated clean recovery candidate used successfully in the
  first incident.

The cutover runs only in the exact Production Space and only before normal
Alembic startup. Any mismatch fails closed without replacing the live file.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import Engine

from app.database import engine
from app import production_sqlite_recovery_cutover_base as base

logger = logging.getLogger(__name__)

PRODUCTION_SPACE_ID = "carsonhhs/pdf-ocr-service"
INCIDENT_ID = "sqlite-corruption-20260814-second-corruption-v1"

EXPECTED_DAMAGED_LIVE_SHA256 = "0c0b9040a2c74d9aad5cb269f57923be0d04a04e7dd5d2737bfbd94f587a9a94"
EXPECTED_DAMAGED_LIVE_BYTE_SIZE = 25_407_488
EXPECTED_DAMAGED_LIVE_XET_HASH = "273c3ea5e862206397c5f164d95cf2ee2dc9e44918cdfdd36a167fafe0de948c"

CANDIDATE_INCIDENT_ID = "sqlite-corruption-20260814-pre-recovery-v1"
CANDIDATE_SHA256 = "c679b7faba2187ca1f022d6db5842372a2697b932664dfa43548f3a8bdb76403"
CANDIDATE_BYTE_SIZE = 25_407_488
CANDIDATE_REMOTE_PATH = (
    f"database-recovery-candidates/{CANDIDATE_INCIDENT_ID}/candidate-{CANDIDATE_SHA256}.db"
)
CANDIDATE_PATH = Path("/data") / CANDIDATE_REMOTE_PATH
CANDIDATE_MANIFEST_PATH = (
    Path("/data/database-recovery-candidates")
    / CANDIDATE_INCIDENT_ID
    / f"manifest-{CANDIDATE_SHA256}.json"
)

IMMUTABLE_SNAPSHOT_REMOTE_PATH = (
    f"database-backups/{INCIDENT_ID}/ocr_tasks-{EXPECTED_DAMAGED_LIVE_XET_HASH}.db"
)
IMMUTABLE_SNAPSHOT_PATH = Path("/data") / IMMUTABLE_SNAPSHOT_REMOTE_PATH
IMMUTABLE_SNAPSHOT_MANIFEST_PATH = Path("/data/database-backups") / INCIDENT_ID / "manifest.json"

CUTOVER_ROOT = Path("/data/database-recovery-cutovers") / INCIDENT_ID
MARKER_PATH = CUTOVER_ROOT / f"complete-{CANDIDATE_SHA256}.json"


class ProductionSqliteSecondRecoveryError(RuntimeError):
    """Raised when the second Production recovery cannot proceed safely."""


def _load_completion_marker(marker_path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    expected = {
        "format_version": 1,
        "incident_id": INCIDENT_ID,
        "status": "complete",
        "candidate_sha256": CANDIDATE_SHA256,
        "damaged_live_sha256": EXPECTED_DAMAGED_LIVE_SHA256,
        "immutable_snapshot_remote_path": IMMUTABLE_SNAPSHOT_REMOTE_PATH,
        "rollback_preserved": True,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            return None
    completed_at = payload.get("completed_at_utc")
    if not isinstance(completed_at, str) or not completed_at:
        return None
    return payload


def _validate_immutable_snapshot(
    snapshot_path: Path = IMMUTABLE_SNAPSHOT_PATH,
    manifest_path: Path = IMMUTABLE_SNAPSHOT_MANIFEST_PATH,
) -> None:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionSqliteSecondRecoveryError("Immutable snapshot manifest is unavailable") from exc
    if not isinstance(payload, dict):
        raise ProductionSqliteSecondRecoveryError("Immutable snapshot manifest is invalid")

    expected_manifest = {
        "format_version": 1,
        "incident_id": INCIDENT_ID,
        "status": "complete",
        "source_bucket": "carsonhhs/pdf-ocr-service-storage",
        "source_path": "ocr_tasks.db",
        "source_xet_hash": EXPECTED_DAMAGED_LIVE_XET_HASH,
        "source_size": EXPECTED_DAMAGED_LIVE_BYTE_SIZE,
        "snapshot_path": IMMUTABLE_SNAPSHOT_REMOTE_PATH,
        "snapshot_xet_hash": EXPECTED_DAMAGED_LIVE_XET_HASH,
        "snapshot_size": EXPECTED_DAMAGED_LIVE_BYTE_SIZE,
        "readback_verified": True,
        "source_mutated": False,
    }
    for key, value in expected_manifest.items():
        if payload.get(key) != value:
            raise ProductionSqliteSecondRecoveryError(
                f"Immutable snapshot manifest mismatch for {key}"
            )

    try:
        if snapshot_path.is_symlink() or not snapshot_path.is_file():
            raise ProductionSqliteSecondRecoveryError("Immutable snapshot file is unavailable")
        if snapshot_path.stat().st_size != EXPECTED_DAMAGED_LIVE_BYTE_SIZE:
            raise ProductionSqliteSecondRecoveryError("Immutable snapshot byte size mismatch")
        if base._sha256_file(snapshot_path) != EXPECTED_DAMAGED_LIVE_SHA256:
            raise ProductionSqliteSecondRecoveryError("Immutable snapshot SHA-256 mismatch")
    except OSError as exc:
        raise ProductionSqliteSecondRecoveryError("Immutable snapshot cannot be read") from exc


def _validate_pinned_candidate(
    candidate_path: Path = CANDIDATE_PATH,
    manifest_path: Path = CANDIDATE_MANIFEST_PATH,
) -> None:
    # Reuse the exact validation contract that protected the first successful
    # cutover. The base helper is intentionally unchanged from that reviewed code.
    base._load_validated_manifest(
        manifest_path,
        expected_sha256=CANDIDATE_SHA256,
        expected_byte_size=CANDIDATE_BYTE_SIZE,
        expected_remote_path=CANDIDATE_REMOTE_PATH,
    )
    base._validate_candidate_file(
        candidate_path,
        expected_sha256=CANDIDATE_SHA256,
        expected_byte_size=CANDIDATE_BYTE_SIZE,
    )
    base._validate_sqlite_clean(candidate_path)


def execute_production_sqlite_second_recovery_cutover(
    *,
    target_engine: Engine = engine,
    candidate_path: Path = CANDIDATE_PATH,
    candidate_manifest_path: Path = CANDIDATE_MANIFEST_PATH,
    snapshot_path: Path = IMMUTABLE_SNAPSHOT_PATH,
    snapshot_manifest_path: Path = IMMUTABLE_SNAPSHOT_MANIFEST_PATH,
    cutover_root: Path = CUTOVER_ROOT,
    marker_path: Path = MARKER_PATH,
    expected_live_sha256: str = EXPECTED_DAMAGED_LIVE_SHA256,
    expected_live_byte_size: int = EXPECTED_DAMAGED_LIVE_BYTE_SIZE,
    space_id: str | None = None,
) -> base.ProductionSqliteRecoveryCutoverStatus:
    """Replace only the exact audited malformed Production DB with the clean candidate."""
    resolved_space_id = os.getenv("SPACE_ID") if space_id is None else space_id
    if resolved_space_id != PRODUCTION_SPACE_ID:
        return base.ProductionSqliteRecoveryCutoverStatus(
            status="not_applicable",
            incident_id=INCIDENT_ID,
            candidate_sha256=CANDIDATE_SHA256,
        )
    if str(target_engine.dialect.name or "unknown") != "sqlite":
        return base.ProductionSqliteRecoveryCutoverStatus(
            status="not_applicable",
            incident_id=INCIDENT_ID,
            candidate_sha256=CANDIDATE_SHA256,
        )

    existing_marker = _load_completion_marker(marker_path)
    if existing_marker is not None:
        return base.ProductionSqliteRecoveryCutoverStatus(
            status="complete",
            incident_id=INCIDENT_ID,
            candidate_sha256=CANDIDATE_SHA256,
            completed_at_utc=str(existing_marker["completed_at_utc"]),
            rollback_preserved=True,
        )

    _validate_immutable_snapshot(snapshot_path, snapshot_manifest_path)
    _validate_pinned_candidate(candidate_path, candidate_manifest_path)

    live_path = base._sqlite_database_path(target_engine)
    if live_path == candidate_path.resolve() or live_path == snapshot_path.resolve():
        raise ProductionSqliteSecondRecoveryError("Recovery source cannot be the live database")
    if live_path.is_symlink() or not live_path.is_file():
        raise ProductionSqliteSecondRecoveryError("Live Production SQLite file is unavailable")
    try:
        live_size = live_path.stat().st_size
        live_sha = base._sha256_file(live_path)
    except OSError as exc:
        raise ProductionSqliteSecondRecoveryError("Live Production SQLite cannot be read") from exc
    if live_size != expected_live_byte_size:
        raise ProductionSqliteSecondRecoveryError(
            "Live Production SQLite changed since read-only audit (byte size mismatch)"
        )
    if live_sha != expected_live_sha256:
        raise ProductionSqliteSecondRecoveryError(
            "Live Production SQLite changed since read-only audit (SHA-256 mismatch)"
        )

    # Re-check that the preserved immutable evidence is byte-for-byte identical
    # to the exact live file we are about to replace.
    if base._sha256_file(snapshot_path) != live_sha or snapshot_path.stat().st_size != live_size:
        raise ProductionSqliteSecondRecoveryError(
            "Immutable snapshot does not match the audited live Production database"
        )

    cutover_root.mkdir(parents=True, exist_ok=True)
    rollback_database = cutover_root / f"pre-cutover-live-{live_sha}.db"
    rollback_sidecars: dict[str, Path] = {}

    # Prevent SQLAlchemy from retaining a DBAPI connection to the inode that is
    # about to be replaced. This executes synchronously before init_db().
    target_engine.dispose()

    replaced = False
    try:
        base._verified_copy(live_path, rollback_database)
        for suffix in base._SQLITE_SIDECAR_SUFFIXES:
            sidecar = Path(str(live_path) + suffix)
            if not sidecar.exists():
                continue
            rollback_sidecar = cutover_root / f"pre-cutover-live-{live_sha}.db{suffix}"
            base._verified_copy(sidecar, rollback_sidecar)
            rollback_sidecars[suffix] = rollback_sidecar

        candidate_fd, candidate_name = tempfile.mkstemp(
            prefix=f".{live_path.name}.second-recovery-",
            suffix=".tmp",
            dir=str(live_path.parent),
        )
        os.close(candidate_fd)
        candidate_temp = Path(candidate_name)
        try:
            shutil.copy2(candidate_path, candidate_temp)
            base._fsync_file(candidate_temp)
            if candidate_temp.stat().st_size != CANDIDATE_BYTE_SIZE:
                raise ProductionSqliteSecondRecoveryError("Staged candidate byte size mismatch")
            if base._sha256_file(candidate_temp) != CANDIDATE_SHA256:
                raise ProductionSqliteSecondRecoveryError("Staged candidate SHA-256 mismatch")

            os.replace(candidate_temp, live_path)
            replaced = True
            for suffix in base._SQLITE_SIDECAR_SUFFIXES:
                Path(str(live_path) + suffix).unlink(missing_ok=True)
            base._fsync_directory(live_path.parent)
        finally:
            candidate_temp.unlink(missing_ok=True)

        if live_path.stat().st_size != CANDIDATE_BYTE_SIZE:
            raise ProductionSqliteSecondRecoveryError("Replacement read-back byte size mismatch")
        if base._sha256_file(live_path) != CANDIDATE_SHA256:
            raise ProductionSqliteSecondRecoveryError("Replacement read-back SHA-256 mismatch")
        base._validate_sqlite_clean(live_path)

        completed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        marker_payload = {
            "format_version": 1,
            "incident_id": INCIDENT_ID,
            "status": "complete",
            "completed_at_utc": completed_at,
            "candidate_sha256": CANDIDATE_SHA256,
            "candidate_byte_size": CANDIDATE_BYTE_SIZE,
            "damaged_live_sha256": expected_live_sha256,
            "damaged_live_byte_size": expected_live_byte_size,
            "immutable_snapshot_remote_path": IMMUTABLE_SNAPSHOT_REMOTE_PATH,
            "rollback_preserved": True,
            "rollback_database_filename": rollback_database.name,
        }
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_fd, marker_name = tempfile.mkstemp(
            prefix=f".{marker_path.name}.", suffix=".tmp", dir=str(marker_path.parent)
        )
        with os.fdopen(marker_fd, "w", encoding="utf-8") as handle:
            json.dump(marker_payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        marker_temp = Path(marker_name)
        try:
            os.replace(marker_temp, marker_path)
            base._fsync_directory(marker_path.parent)
        finally:
            marker_temp.unlink(missing_ok=True)

        logger.info(
            "PRODUCTION_SQLITE_SECOND_RECOVERY_CUTOVER status=complete incident_id=%s "
            "damaged_live_sha256=%s candidate_sha256=%s rollback_preserved=true",
            INCIDENT_ID,
            expected_live_sha256,
            CANDIDATE_SHA256,
        )
        return base.ProductionSqliteRecoveryCutoverStatus(
            status="complete",
            incident_id=INCIDENT_ID,
            candidate_sha256=CANDIDATE_SHA256,
            completed_at_utc=completed_at,
            rollback_preserved=True,
        )
    except Exception:
        target_engine.dispose()
        if replaced:
            try:
                base._restore_previous_live_database(
                    live_path=live_path,
                    rollback_database=rollback_database,
                    rollback_sidecars=rollback_sidecars,
                )
            except Exception as rollback_exc:
                logger.critical(
                    "PRODUCTION_SQLITE_SECOND_RECOVERY_CUTOVER status=rollback_failed "
                    "incident_id=%s error_type=%s",
                    INCIDENT_ID,
                    type(rollback_exc).__name__,
                )
                raise ProductionSqliteSecondRecoveryError(
                    "Second Production SQLite recovery failed and rollback also failed"
                ) from rollback_exc
        logger.error(
            "PRODUCTION_SQLITE_SECOND_RECOVERY_CUTOVER status=failed incident_id=%s",
            INCIDENT_ID,
        )
        raise


__all__ = [
    "CANDIDATE_SHA256",
    "EXPECTED_DAMAGED_LIVE_SHA256",
    "IMMUTABLE_SNAPSHOT_REMOTE_PATH",
    "INCIDENT_ID",
    "MARKER_PATH",
    "ProductionSqliteSecondRecoveryError",
    "execute_production_sqlite_second_recovery_cutover",
]
