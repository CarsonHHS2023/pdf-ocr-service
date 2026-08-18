"""One-time fail-closed Production SQLite recovery cutover.

This module is intentionally pinned to one validated recovery candidate for one
incident. It runs only in the exact Production Space, before Alembic startup.
The validated candidate is copied from the private /data mount to a temporary
file beside the live SQLite database, then atomically replaces the live file.

The previous live file and any SQLite sidecars are copied to a private rollback
folder first. If post-replacement validation fails, the previous files are
restored and startup fails closed. A completion marker is written last so later
restarts do not repeat the cutover.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import Engine

from app.database import engine

logger = logging.getLogger(__name__)

PRODUCTION_SPACE_ID = "carsonhhs/pdf-ocr-service"
INCIDENT_ID = "sqlite-corruption-20260814-pre-recovery-v1"
CANDIDATE_SHA256 = "c679b7faba2187ca1f022d6db5842372a2697b932664dfa43548f3a8bdb76403"
CANDIDATE_BYTE_SIZE = 25_407_488
RECOVERY_ROOT = Path("/data/database-recovery-candidates") / INCIDENT_ID
CANDIDATE_REMOTE_PATH = (
    f"database-recovery-candidates/{INCIDENT_ID}/candidate-{CANDIDATE_SHA256}.db"
)
CANDIDATE_PATH = RECOVERY_ROOT / f"candidate-{CANDIDATE_SHA256}.db"
MANIFEST_PATH = RECOVERY_ROOT / f"manifest-{CANDIDATE_SHA256}.json"
CUTOVER_ROOT = Path("/data/database-recovery-cutovers") / INCIDENT_ID
MARKER_PATH = CUTOVER_ROOT / f"complete-{CANDIDATE_SHA256}.json"
_SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


class ProductionSqliteRecoveryCutoverError(RuntimeError):
    """Raised when the pinned Production cutover cannot complete safely."""


@dataclass(frozen=True, slots=True)
class ProductionSqliteRecoveryCutoverStatus:
    status: str
    incident_id: str
    candidate_sha256: str = CANDIDATE_SHA256
    completed_at_utc: str | None = None
    rollback_preserved: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sqlite_database_path(target_engine: Engine) -> Path:
    if str(target_engine.dialect.name or "unknown") != "sqlite":
        raise ProductionSqliteRecoveryCutoverError("Production database is not SQLite")
    database = target_engine.url.database
    if not isinstance(database, str) or not database or database == ":memory:":
        raise ProductionSqliteRecoveryCutoverError("Production SQLite path is unavailable")
    path = Path(database)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()
    try:
        path.relative_to(Path("/data"))
    except ValueError as exc:
        raise ProductionSqliteRecoveryCutoverError(
            "Production SQLite path is outside the private /data mount"
        ) from exc
    return path


def _load_validated_manifest(
    manifest_path: Path,
    *,
    expected_sha256: str,
    expected_byte_size: int,
    expected_remote_path: str,
) -> dict[str, object]:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionSqliteRecoveryCutoverError("Recovery manifest is unavailable") from exc
    if not isinstance(payload, dict):
        raise ProductionSqliteRecoveryCutoverError("Recovery manifest is invalid")
    if payload.get("format_version") != 1:
        raise ProductionSqliteRecoveryCutoverError("Recovery manifest version mismatch")
    if payload.get("incident_id") != INCIDENT_ID:
        raise ProductionSqliteRecoveryCutoverError("Recovery incident mismatch")
    if payload.get("status") != "validated_recovery_candidate":
        raise ProductionSqliteRecoveryCutoverError("Recovery candidate is not validated")
    if payload.get("candidate_remote_path") != expected_remote_path:
        raise ProductionSqliteRecoveryCutoverError("Recovery candidate path mismatch")
    if payload.get("candidate_sha256") != expected_sha256:
        raise ProductionSqliteRecoveryCutoverError("Recovery candidate SHA mismatch")
    if payload.get("candidate_byte_size") != expected_byte_size:
        raise ProductionSqliteRecoveryCutoverError("Recovery candidate size mismatch")
    if payload.get("candidate_readback_verified") is not True:
        raise ProductionSqliteRecoveryCutoverError("Recovery candidate lacks read-back verification")
    contract = payload.get("validation_contract")
    if not isinstance(contract, dict):
        raise ProductionSqliteRecoveryCutoverError("Recovery validation contract is missing")
    expected_contract = {
        "quick_check": "ok",
        "integrity_check": "ok",
        "foreign_key_violation_count": 0,
        "alembic_head_match": True,
        "reader_v2_selected_document_count": 7,
        "reader_v2_unselected_not_ready_count": 1,
        "orm_flush_rollback": "ok",
    }
    if contract != expected_contract:
        raise ProductionSqliteRecoveryCutoverError("Recovery validation contract mismatch")
    return payload


def _validate_candidate_file(path: Path, *, expected_sha256: str, expected_byte_size: int) -> None:
    try:
        if path.is_symlink() or not path.is_file():
            raise ProductionSqliteRecoveryCutoverError("Recovery candidate file is unavailable")
        if path.stat().st_size != expected_byte_size:
            raise ProductionSqliteRecoveryCutoverError("Recovery candidate byte size mismatch")
        if _sha256_file(path) != expected_sha256:
            raise ProductionSqliteRecoveryCutoverError("Recovery candidate hash mismatch")
    except OSError as exc:
        raise ProductionSqliteRecoveryCutoverError("Recovery candidate cannot be read") from exc


def _validate_sqlite_clean(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30.0)
    try:
        quick = tuple(str(row[0]).strip().lower() for row in connection.execute("PRAGMA quick_check"))
        if quick != ("ok",):
            raise ProductionSqliteRecoveryCutoverError("Recovery SQLite quick_check failed")
        integrity = tuple(
            str(row[0]).strip().lower() for row in connection.execute("PRAGMA integrity_check")
        )
        if integrity != ("ok",):
            raise ProductionSqliteRecoveryCutoverError("Recovery SQLite integrity_check failed")
        fk_count = sum(1 for _ in connection.execute("PRAGMA foreign_key_check"))
        if fk_count != 0:
            raise ProductionSqliteRecoveryCutoverError("Recovery SQLite foreign_key_check failed")
    except sqlite3.DatabaseError as exc:
        raise ProductionSqliteRecoveryCutoverError("Recovery SQLite validation failed") from exc
    finally:
        connection.close()


def _load_marker(marker_path: Path, *, expected_sha256: str) -> ProductionSqliteRecoveryCutoverStatus | None:
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("format_version") != 1:
        return None
    if payload.get("incident_id") != INCIDENT_ID:
        return None
    if payload.get("status") != "complete":
        return None
    if payload.get("candidate_sha256") != expected_sha256:
        return None
    completed_at = payload.get("completed_at_utc")
    if not isinstance(completed_at, str) or not completed_at:
        return None
    if payload.get("rollback_preserved") is not True:
        return None
    return ProductionSqliteRecoveryCutoverStatus(
        status="complete",
        incident_id=INCIDENT_ID,
        candidate_sha256=expected_sha256,
        completed_at_utc=completed_at,
        rollback_preserved=True,
    )


def production_sqlite_recovery_cutover_status(
    *,
    marker_path: Path = MARKER_PATH,
    space_id: str | None = None,
) -> ProductionSqliteRecoveryCutoverStatus:
    resolved_space_id = os.getenv("SPACE_ID") if space_id is None else space_id
    if resolved_space_id != PRODUCTION_SPACE_ID:
        return ProductionSqliteRecoveryCutoverStatus(
            status="not_applicable",
            incident_id=INCIDENT_ID,
        )
    marker = _load_marker(marker_path, expected_sha256=CANDIDATE_SHA256)
    if marker is not None:
        return marker
    return ProductionSqliteRecoveryCutoverStatus(status="pending", incident_id=INCIDENT_ID)


def _verified_copy(source: Path, destination: Path) -> None:
    source_sha = _sha256_file(source)
    source_size = source.stat().st_size
    if destination.exists():
        if destination.stat().st_size != source_size or _sha256_file(destination) != source_sha:
            raise ProductionSqliteRecoveryCutoverError("Existing rollback copy does not match source")
        return
    shutil.copy2(source, destination)
    _fsync_file(destination)
    if destination.stat().st_size != source_size or _sha256_file(destination) != source_sha:
        raise ProductionSqliteRecoveryCutoverError("Rollback copy verification failed")


def _restore_previous_live_database(
    *,
    live_path: Path,
    rollback_database: Path,
    rollback_sidecars: dict[str, Path],
) -> None:
    restore_fd, restore_name = tempfile.mkstemp(
        prefix=f".{live_path.name}.rollback-",
        suffix=".tmp",
        dir=str(live_path.parent),
    )
    os.close(restore_fd)
    restore_temp = Path(restore_name)
    try:
        shutil.copy2(rollback_database, restore_temp)
        _fsync_file(restore_temp)
        os.replace(restore_temp, live_path)
        for suffix in _SQLITE_SIDECAR_SUFFIXES:
            Path(str(live_path) + suffix).unlink(missing_ok=True)
        for suffix, rollback_sidecar in rollback_sidecars.items():
            destination = Path(str(live_path) + suffix)
            shutil.copy2(rollback_sidecar, destination)
            _fsync_file(destination)
        _fsync_directory(live_path.parent)
    finally:
        restore_temp.unlink(missing_ok=True)


def execute_production_sqlite_recovery_cutover(
    *,
    target_engine: Engine = engine,
    candidate_path: Path = CANDIDATE_PATH,
    manifest_path: Path = MANIFEST_PATH,
    cutover_root: Path = CUTOVER_ROOT,
    marker_path: Path = MARKER_PATH,
    expected_sha256: str = CANDIDATE_SHA256,
    expected_byte_size: int = CANDIDATE_BYTE_SIZE,
    expected_remote_path: str = CANDIDATE_REMOTE_PATH,
    space_id: str | None = None,
) -> ProductionSqliteRecoveryCutoverStatus:
    """Atomically replace the Production SQLite file with the pinned candidate."""
    resolved_space_id = os.getenv("SPACE_ID") if space_id is None else space_id
    if resolved_space_id != PRODUCTION_SPACE_ID:
        return ProductionSqliteRecoveryCutoverStatus(
            status="not_applicable",
            incident_id=INCIDENT_ID,
            candidate_sha256=expected_sha256,
        )
    if str(target_engine.dialect.name or "unknown") != "sqlite":
        return ProductionSqliteRecoveryCutoverStatus(
            status="not_applicable",
            incident_id=INCIDENT_ID,
            candidate_sha256=expected_sha256,
        )

    existing_marker = _load_marker(marker_path, expected_sha256=expected_sha256)
    if existing_marker is not None:
        logger.info(
            "PRODUCTION_SQLITE_RECOVERY_CUTOVER status=already_complete incident_id=%s",
            INCIDENT_ID,
        )
        return existing_marker

    _load_validated_manifest(
        manifest_path,
        expected_sha256=expected_sha256,
        expected_byte_size=expected_byte_size,
        expected_remote_path=expected_remote_path,
    )
    _validate_candidate_file(
        candidate_path,
        expected_sha256=expected_sha256,
        expected_byte_size=expected_byte_size,
    )
    _validate_sqlite_clean(candidate_path)

    live_path = _sqlite_database_path(target_engine)
    if live_path == candidate_path.resolve():
        raise ProductionSqliteRecoveryCutoverError("Recovery candidate cannot be the live database")
    if live_path.is_symlink() or not live_path.is_file():
        raise ProductionSqliteRecoveryCutoverError("Live Production SQLite file is unavailable")

    cutover_root.mkdir(parents=True, exist_ok=True)
    live_sha = _sha256_file(live_path)
    rollback_database = cutover_root / f"pre-cutover-live-{live_sha}.db"
    rollback_sidecars: dict[str, Path] = {}

    # The pre-recovery backup helper can leave a closed DBAPI connection in the
    # SQLAlchemy pool. Dispose it before replacing the file so init_db() cannot
    # later reuse a connection tied to the old inode.
    target_engine.dispose()

    replaced = False
    try:
        _verified_copy(live_path, rollback_database)
        for suffix in _SQLITE_SIDECAR_SUFFIXES:
            sidecar = Path(str(live_path) + suffix)
            if not sidecar.exists():
                continue
            rollback_sidecar = cutover_root / f"pre-cutover-live-{live_sha}.db{suffix}"
            _verified_copy(sidecar, rollback_sidecar)
            rollback_sidecars[suffix] = rollback_sidecar

        candidate_fd, candidate_name = tempfile.mkstemp(
            prefix=f".{live_path.name}.recovery-",
            suffix=".tmp",
            dir=str(live_path.parent),
        )
        os.close(candidate_fd)
        candidate_temp = Path(candidate_name)
        try:
            shutil.copy2(candidate_path, candidate_temp)
            _fsync_file(candidate_temp)
            if candidate_temp.stat().st_size != expected_byte_size:
                raise ProductionSqliteRecoveryCutoverError("Staged recovery candidate size mismatch")
            if _sha256_file(candidate_temp) != expected_sha256:
                raise ProductionSqliteRecoveryCutoverError("Staged recovery candidate hash mismatch")

            # Make the clean main DB visible atomically first. No new application
            # connection can open in this synchronous startup section. Only after
            # replace succeeds do we remove sidecars that belonged to the old DB.
            os.replace(candidate_temp, live_path)
            replaced = True
            for suffix in _SQLITE_SIDECAR_SUFFIXES:
                Path(str(live_path) + suffix).unlink(missing_ok=True)
            _fsync_directory(live_path.parent)
        finally:
            candidate_temp.unlink(missing_ok=True)

        if live_path.stat().st_size != expected_byte_size or _sha256_file(live_path) != expected_sha256:
            raise ProductionSqliteRecoveryCutoverError("Live database replacement read-back failed")
        _validate_sqlite_clean(live_path)

        completed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        marker_payload = {
            "format_version": 1,
            "incident_id": INCIDENT_ID,
            "status": "complete",
            "completed_at_utc": completed_at,
            "candidate_sha256": expected_sha256,
            "candidate_byte_size": expected_byte_size,
            "rollback_preserved": True,
            "rollback_database_filename": rollback_database.name,
        }
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_fd, marker_name = tempfile.mkstemp(
            prefix=f".{marker_path.name}.",
            suffix=".tmp",
            dir=str(marker_path.parent),
        )
        with os.fdopen(marker_fd, "w", encoding="utf-8") as handle:
            json.dump(marker_payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        marker_temp = Path(marker_name)
        try:
            os.replace(marker_temp, marker_path)
            _fsync_directory(marker_path.parent)
        finally:
            marker_temp.unlink(missing_ok=True)

        logger.info(
            "PRODUCTION_SQLITE_RECOVERY_CUTOVER status=complete incident_id=%s rollback_preserved=true",
            INCIDENT_ID,
        )
        return ProductionSqliteRecoveryCutoverStatus(
            status="complete",
            incident_id=INCIDENT_ID,
            candidate_sha256=expected_sha256,
            completed_at_utc=completed_at,
            rollback_preserved=True,
        )
    except Exception:
        target_engine.dispose()
        if replaced:
            try:
                _restore_previous_live_database(
                    live_path=live_path,
                    rollback_database=rollback_database,
                    rollback_sidecars=rollback_sidecars,
                )
            except Exception as rollback_exc:
                logger.critical(
                    "PRODUCTION_SQLITE_RECOVERY_CUTOVER status=rollback_failed incident_id=%s error_type=%s",
                    INCIDENT_ID,
                    type(rollback_exc).__name__,
                )
                raise ProductionSqliteRecoveryCutoverError(
                    "Production SQLite recovery cutover failed and rollback also failed"
                ) from rollback_exc
        logger.error(
            "PRODUCTION_SQLITE_RECOVERY_CUTOVER status=failed incident_id=%s",
            INCIDENT_ID,
        )
        raise


__all__ = [
    "CANDIDATE_BYTE_SIZE",
    "CANDIDATE_PATH",
    "CANDIDATE_SHA256",
    "CUTOVER_ROOT",
    "INCIDENT_ID",
    "MARKER_PATH",
    "MANIFEST_PATH",
    "PRODUCTION_SPACE_ID",
    "ProductionSqliteRecoveryCutoverError",
    "ProductionSqliteRecoveryCutoverStatus",
    "execute_production_sqlite_recovery_cutover",
    "production_sqlite_recovery_cutover_status",
]
