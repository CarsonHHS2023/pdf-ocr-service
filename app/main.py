"""FastAPI application configuration."""

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.access_middleware import AppAccessGateMiddleware
from app.logging_config import configure_application_logging
from app.routers import dark_anchor_diagnostics

configure_application_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PDF OCR Service",
    description="FastAPI backend for PaddleOCR-based PDF processing and bookshelf management",
    version="2.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)


def _cors_origins() -> list[str]:
    configured = os.getenv("APP_CORS_ORIGINS", "").strip()
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "https://carsonhhs2023.github.io",
        "http://localhost:3000",
        "http://localhost:4173",
        "http://localhost:5173",
        "http://localhost:5500",
        "http://localhost:8000",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:4173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5500",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8080",
    ]


# Add the access gate first, then CORS. Starlette inserts newly added middleware
# at the outside of the stack, so CORS can decorate 401/503 gate responses too.
app.add_middleware(AppAccessGateMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.database import init_db  # noqa: E402
from app.production_sqlite_second_recovery_cutover import (  # noqa: E402
    execute_production_sqlite_second_recovery_cutover,
)
from app.processing import install_refinement_provider_stderr_handler  # noqa: E402
from app.processing.structure_refinement_config_snapshot import (  # noqa: E402
    validate_and_log_structure_refinement_config,
)
from app.routers import (  # noqa: E402
    access,
    books,
    health,
    images,
    ocr,
    processing_operator,
    reader,
    reader_v2,
    source_transport,
    study,
)

# Include normal application routers.
app.include_router(health.router)
app.include_router(access.router)
app.include_router(ocr.router)
app.include_router(books.router)
app.include_router(images.router)
app.include_router(source_transport.router)
app.include_router(processing_operator.router)
app.include_router(reader.router)
app.include_router(reader_v2.router)
app.include_router(study.router)

# Test-only histogram downloads are intentionally not part of Reader v2's router.
# The PDF compatibility chain can import Reader modules while app.main itself is
# initializing, so include_router() can observe a partially initialized diagnostic
# router. At the end of startup assembly the diagnostic module is complete; append
# only routes that are still missing, preserving exactly one route per path and
# keeping normal Reader routing/fallback untouched.
_existing_paths = {getattr(route, "path", None) for route in app.routes}
for _route in dark_anchor_diagnostics.router.routes:
    if getattr(_route, "path", None) not in _existing_paths:
        app.router.routes.append(_route)
        _existing_paths.add(getattr(_route, "path", None))


@app.get("/")
async def root():
    """Root endpoint - API is running."""
    return {
        "service": "pdf-ocr-service",
        "status": "running",
        "docs": "/docs",
        "health": "/api/v1/health",
        "version": "2.0.0",
    }


@app.on_event("startup")
async def startup_event():
    validate_and_log_structure_refinement_config(logger)
    logger.info("PDF OCR Service started")

    # One-time second-corruption recovery. This is gated to the exact Production
    # Space and the exact malformed live SHA-256 observed by the read-only audit.
    # It also verifies the immutable snapshot before replacing anything and
    # preserves a local rollback copy. Any mismatch fails closed before init_db().
    cutover_status = execute_production_sqlite_second_recovery_cutover()
    logger.info(
        "Production SQLite second recovery cutover status=%s rollback_preserved=%s",
        cutover_status.status,
        cutover_status.rollback_preserved,
    )

    init_db()
    configure_application_logging()
    install_refinement_provider_stderr_handler()

    logger.info("Database initialized")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("PDF OCR Service stopped")
