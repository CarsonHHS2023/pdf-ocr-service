"""One-time, non-destructive Production SQLite snapshot for recovery preparation.

The live database is never copied directly. SQLite's online backup API writes a
complete local snapshot under /tmp first; only after the SQLite connections are
closed is that immutable file copied to the private mounted storage bucket and
verified by SHA-256 read-back. A manifest written last is the publication marker.

This module intentionally provides no restore, replace, delete, REINDEX, VACUUM,
or recovery operation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import Engine

from app.database import engine

logger = logging.getLogger(__name__)

PRODUCTION_SPACE_ID = "carsonhhs/pdf-ocr-service"
INCIDENT_ID = "sqlite-corruption-20260814-pre-recovery-v1"
DEFAULT_BACKUP_ROOT = Path("/data/database-backups")
_MANIFEST_NAME = f"{INCIDENT_ID}.json"
_MAX_QUICK_CHECK_ERRORS = 100


@dataclass(frozen=True, slots=True)
class ProductionSqliteBackupStatus:
    status: str
    incident_id: str
    created_at_utc: str | None = None
    byte_size: int | None = None
    sha256: str | None = None
    readback_verified: bool = False
    quick_check: str = "not_run"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _quick_check_summary(path: Path) -> str:
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30.0)
        try:
            rows = connection.execute(
                f"PRAGMA quick_check({_MAX_QUICK_CHECK_ERRORS})"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.DatabaseError:
        return "error"

    values = [str(row[0]).strip().lower() for row in rows if row]
    return "ok" if values == ["ok"] else "issues"


def _manifest_path(backup_root: Path) -> Path:
    return backup_root / _MANIFEST_NAME


def _manifest_to_status(payload: dict[str, object]) -> ProductionSqliteBackupStatus | None:
    if payload.get("format_version") != 1:
        return None
    if payload.get("incident_id") != INCIDENT_ID or payload.get("status") != "complete":
        return None
    snapshot_filename = payload.get("snapshot_filename")
    sha256 = payload.get("sha256")
    byte_size = payload.get("byte_size")
    created_at_utc = payload.get("created_at_utc")
    quick_check = payload.get("quick_check")
    readback_verified = payload.get("readback_verified")
    if not isinstance(snapshot_filename, str) or Path(snapshot_filename).name != snapshot_filename:
        return None
    if not isinstance(sha256, str) or len(sha256) != 64:
        return None
    if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size <= 0:
        return None
    if not isinstance(created_at_utc, str) or not created_at_utc:
        return None
    if quick_check not in {"ok", "issues", "error"}:
        return None
    if readback_verified is not True:
        return None
    return ProductionSqliteBackupStatus(
        status="complete",
        incident_id=INCIDENT_ID,
        created_at_utc=created_at_utc,
        byte_size=byte_size,
        sha256=sha256.lower(),
        readback_verified=True,
        quick_check=str(quick_check),
    )


def _read_manifest(backup_root: Path) -> tuple[dict[str, object], ProductionSqliteBackupStatus] | None:
    try:
        payload = json.loads(_manifest_path(backup_root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    status = _manifest_to_status(payload)
    if status is None:
        return None
    return payload, status


def production_sqlite_backup_status(
    *,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
    space_id: str | None = None,
) -> ProductionSqliteBackupStatus:
    """Return sanitized publication status without opening the live database."""
    resolved_space_id = os.getenv("SPACE_ID") if space_id is None else space_id
    if resolved_space_id != PRODUCTION_SPACE_ID:
        return ProductionSqliteBackupStatus(
            status="not_applicable",
            incident_id=INCIDENT_ID,
        )

    loaded = _read_manifest(backup_root)
    if loaded is None:
        return ProductionSqliteBackupStatus(status="missing", incident_id=INCIDENT_ID)
    payload, status = loaded
    snapshot_filename = str(payload["snapshot_filename"])
    snapshot = backup_root / snapshot_filename
    try:
        if not snapshot.is_file() or snapshot.stat().st_size != status.byte_size:
            return ProductionSqliteBackupStatus(status="invalid", incident_id=INCIDENT_ID)
    except OSError:
        return ProductionSqliteBackupStatus(status="invalid", incident_id=INCIDENT_ID)
    return status


def _verified_existing_backup(backup_root: Path) -> ProductionSqliteBackupStatus | None:
    loaded = _read_manifest(backup_root)
    if loaded is None:
        return None
    payload, status = loaded
    snapshot = backup_root / str(payload["snapshot_filename"])
    try:
        if not snapshot.is_file() or snapshot.stat().st_size != status.byte_size:
            return None
        if _sha256_file(snapshot) != status.sha256:
            return None
    except OSError:
        return None
    return status


def _create_local_online_backup(target_engine: Engine) -> Path:
    fd, name = tempfile.mkstemp(prefix="production-pre-recovery-", suffix=".db", dir="/tmp")
    os.close(fd)
    destination_path = Path(name)
    try:
        destination = sqlite3.connect(str(destination_path), timeout=30.0)
        try:
            with target_engine.connect() as connection:
                source = connection.connection.driver_connection
                if not isinstance(source, sqlite3.Connection):
                    raise TypeError("SQLite driver connection unavailable")
                source.backup(destination, pages=256, sleep=0.05)
        finally:
            destination.close()
        if destination_path.stat().st_size <= 0:
            raise OSError("SQLite online backup produced an empty file")
        return destination_path
    except Exception:
        destination_path.unlink(missing_ok=True)
        raise


def create_production_pre_recovery_backup(
    *,
    target_engine: Engine = engine,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
    space_id: str | None = None,
) -> ProductionSqliteBackupStatus:
    """Create exactly one verified immutable Production backup for this incident.

    Failure is reported as a sanitized status and does not mutate or replace the
    live database. Existing complete backups are hash-verified before reuse.
    """
    resolved_space_id = os.getenv("SPACE_ID") if space_id is None else space_id
    if resolved_space_id != PRODUCTION_SPACE_ID:
        return ProductionSqliteBackupStatus(
            status="not_applicable",
            incident_id=INCIDENT_ID,
        )
    if str(target_engine.dialect.name or "unknown") != "sqlite":
        return ProductionSqliteBackupStatus(
            status="not_applicable",
            incident_id=INCIDENT_ID,
        )

    try:
        backup_root.mkdir(parents=True, exist_ok=True)
        existing = _verified_existing_backup(backup_root)
        if existing is not None:
            logger.info(
                "PRODUCTION_SQLITE_PRE_RECOVERY_BACKUP status=already_complete incident_id=%s",
                INCIDENT_ID,
            )
            return existing

        local_backup = _create_local_online_backup(target_engine)
        try:
            checksum = _sha256_file(local_backup)
            byte_size = local_backup.stat().st_size
            quick_check = _quick_check_summary(local_backup)
            created_at = datetime.now(timezone.utc)
            timestamp = created_at.strftime("%Y%m%dT%H%M%S%fZ")
            snapshot_filename = f"{INCIDENT_ID}_{timestamp}_{uuid.uuid4().hex}.db"
            snapshot = backup_root / snapshot_filename

            # The live SQLite file is never copied directly to the mounted bucket.
            # Only the closed local online-backup result is copied, then read back.
            shutil.copyfile(local_backup, snapshot)
            if snapshot.stat().st_size != byte_size or _sha256_file(snapshot) != checksum:
                raise OSError("Production backup read-back verification failed")

            payload = {
                "format_version": 1,
                "incident_id": INCIDENT_ID,
                "status": "complete",
                "created_at_utc": created_at.isoformat().replace("+00:00", "Z"),
                "snapshot_filename": snapshot_filename,
                "byte_size": byte_size,
                "sha256": checksum,
                "readback_verified": True,
                "quick_check": quick_check,
            }
            # Manifest is written last and acts as the publication marker. No live
            # database path, table name, index name, or raw SQLite message is stored.
            _manifest_path(backup_root).write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            result = _manifest_to_status(payload)
            assert result is not None
            logger.info(
                "PRODUCTION_SQLITE_PRE_RECOVERY_BACKUP status=complete incident_id=%s bytes=%s quick_check=%s",
                INCIDENT_ID,
                byte_size,
                quick_check,
            )
            return result
        finally:
            local_backup.unlink(missing_ok=True)
    except Exception as exc:
        logger.error(
            "PRODUCTION_SQLITE_PRE_RECOVERY_BACKUP status=error incident_id=%s error_type=%s",
            INCIDENT_ID,
            type(exc).__name__,
        )
        return ProductionSqliteBackupStatus(status="error", incident_id=INCIDENT_ID)


__all__ = [
    "DEFAULT_BACKUP_ROOT",
    "INCIDENT_ID",
    "PRODUCTION_SPACE_ID",
    "ProductionSqliteBackupStatus",
    "create_production_pre_recovery_backup",
    "production_sqlite_backup_status",
]
