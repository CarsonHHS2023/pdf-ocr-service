"""Read-only status for the completed Production SQLite recovery cutover.

The incident cutover was completed and verified on 2026-08-14. Runtime startup
must never execute the cutover again. This module intentionally retains only the
sanitized completion-marker reader used by the health endpoint; it contains no
SQLite replacement, recovery, rollback, deletion, or mutation capability.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

PRODUCTION_SPACE_ID = "carsonhhs/pdf-ocr-service"
INCIDENT_ID = "sqlite-corruption-20260814-pre-recovery-v1"
CANDIDATE_SHA256 = "c679b7faba2187ca1f022d6db5842372a2697b932664dfa43548f3a8bdb76403"
CANDIDATE_BYTE_SIZE = 25_407_488
CUTOVER_ROOT = Path("/data/database-recovery-cutovers") / INCIDENT_ID
MARKER_PATH = CUTOVER_ROOT / f"complete-{CANDIDATE_SHA256}.json"


@dataclass(frozen=True, slots=True)
class ProductionSqliteRecoveryCutoverStatus:
    status: str
    incident_id: str
    candidate_sha256: str = CANDIDATE_SHA256
    completed_at_utc: str | None = None
    rollback_preserved: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _load_marker(
    marker_path: Path,
    *,
    expected_sha256: str = CANDIDATE_SHA256,
    expected_byte_size: int = CANDIDATE_BYTE_SIZE,
) -> ProductionSqliteRecoveryCutoverStatus | None:
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
    if payload.get("candidate_byte_size") != expected_byte_size:
        return None
    completed_at = payload.get("completed_at_utc")
    if not isinstance(completed_at, str) or not completed_at:
        return None
    if payload.get("rollback_preserved") is not True:
        return None
    rollback_filename = payload.get("rollback_database_filename")
    if (
        not isinstance(rollback_filename, str)
        or Path(rollback_filename).name != rollback_filename
        or not rollback_filename.startswith("pre-cutover-live-")
        or not rollback_filename.endswith(".db")
    ):
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
    """Return sanitized completion status without mutating Production state."""
    resolved_space_id = os.getenv("SPACE_ID") if space_id is None else space_id
    if resolved_space_id != PRODUCTION_SPACE_ID:
        return ProductionSqliteRecoveryCutoverStatus(
            status="not_applicable",
            incident_id=INCIDENT_ID,
        )
    marker = _load_marker(marker_path)
    if marker is not None:
        return marker
    return ProductionSqliteRecoveryCutoverStatus(
        status="pending",
        incident_id=INCIDENT_ID,
    )


__all__ = [
    "CANDIDATE_BYTE_SIZE",
    "CANDIDATE_SHA256",
    "CUTOVER_ROOT",
    "INCIDENT_ID",
    "MARKER_PATH",
    "PRODUCTION_SPACE_ID",
    "ProductionSqliteRecoveryCutoverStatus",
    "production_sqlite_recovery_cutover_status",
]
