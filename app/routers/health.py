"""Health and sanitized runtime configuration routes."""
import logging

from fastapi import APIRouter

from app.database_integrity import production_database_integrity_snapshot
from app.production_sqlite_backup import production_sqlite_backup_status
from app.production_sqlite_recovery_cutover import production_sqlite_recovery_cutover_status
from app.processing.structure_refinement_config_snapshot import (
    structure_refinement_config_snapshot,
)
from app.schemas import HealthCheckResponse, StructureRefinementConfigResponse

router = APIRouter(prefix="/api/v1", tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """Return the basic service liveness response."""
    return HealthCheckResponse(
        status="healthy",
        service="pdf-ocr-service",
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
