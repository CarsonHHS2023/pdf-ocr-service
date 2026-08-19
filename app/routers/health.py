"""Health and sanitized runtime configuration routes."""
import logging
from pathlib import Path
import re

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.database_integrity import production_database_integrity_snapshot
from app.production_sqlite_backup import production_sqlite_backup_status
from app.production_sqlite_recovery_cutover import production_sqlite_recovery_cutover_status
from app.processing.structure_refinement_config_snapshot import (
    structure_refinement_config_snapshot,
)
from app.schemas import HealthCheckResponse, StructureRefinementConfigResponse
from app.storage.factory import object_storage_is_configured
from app.upload_policy import book_source_max_bytes

router = APIRouter(prefix="/api/v1", tags=["health"])
logger = logging.getLogger(__name__)

_RUNTIME_ROOT = Path(__file__).resolve().parents[2]
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


class UploadCapabilitiesResponse(BaseModel):
    schema_version: int
    application_max_bytes: int
    supported_file_types: list[str]
    direct_upload_available: bool
    direct_upload_file_types: list[str]
    direct_single_put_max_bytes: int
    resumable_upload_available: bool
    resumable_upload_file_types: list[str]
    resumable_transport_max_bytes: int


def runtime_build_revision() -> str | None:
    """Return the exact sanitized SHA embedded in the deployed Staging artifact."""
    revision_file = _RUNTIME_ROOT / "staging-revision.txt"
    try:
        value = revision_file.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return None
    return value if _REVISION_RE.fullmatch(value) else None


def _direct_upload_is_configured() -> bool:
    secret = settings.direct_upload_signing_secret or ""
    return bool(
        settings.direct_upload_enabled
        and object_storage_is_configured(settings)
        and len(secret) >= 32
    )


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    response_model_exclude_none=True,
)
async def health_check():
    """Return liveness plus a sanitized deployment revision when available."""
    return HealthCheckResponse(
        status="healthy",
        service="pdf-ocr-service",
        revision=runtime_build_revision(),
    )


@router.get("/upload-capabilities", response_model=UploadCapabilitiesResponse)
async def upload_capabilities() -> UploadCapabilitiesResponse:
    """Return sanitized application and transport limits for browser routing."""
    # Lazy import avoids changing router import order while keeping the browser
    # contract tied to the resumable transport's authoritative hard ceiling.
    from app.routers.resumable_upload import MAX_UPLOAD_BYTES

    return UploadCapabilitiesResponse(
        schema_version=1,
        application_max_bytes=book_source_max_bytes(settings),
        supported_file_types=["pdf", "txt"],
        direct_upload_available=_direct_upload_is_configured(),
        direct_upload_file_types=["pdf"],
        direct_single_put_max_bytes=max(
            0,
            int(settings.direct_upload_single_put_max_bytes),
        ),
        resumable_upload_available=True,
        resumable_upload_file_types=["pdf", "txt"],
        resumable_transport_max_bytes=int(MAX_UPLOAD_BYTES),
    )


@router.get("/health/config", response_model=StructureRefinementConfigResponse)
async def health_config():
    """Return effective non-secret PDF structure-refinement settings."""
    return StructureRefinementConfigResponse(**structure_refinement_config_snapshot())


@router.get("/health/database-integrity")
def health_database_integrity():
    """Return a bounded, sanitized, read-only database integrity snapshot."""
    return production_database_integrity_snapshot().as_dict()


@router.get("/health/database-backup")
def health_database_backup():
    """Return sanitized status for the one-time pre-recovery SQLite backup."""
    return production_sqlite_backup_status().as_dict()


@router.get("/health/database-recovery-cutover")
def health_database_recovery_cutover():
    """Return sanitized status for the one-time Production SQLite cutover."""
    return production_sqlite_recovery_cutover_status().as_dict()
