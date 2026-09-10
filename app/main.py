"""FastAPI application configuration."""

import asyncio
import logging
import os
import time

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

S0_STALE_RECOVERY_SWEEP_SECONDS = 60.0
_stale_processing_run_recovery_task: asyncio.Task | None = None


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


def _scope_header(scope: dict, name: bytes, max_length: int = 512) -> str:
    for key, value in scope.get("headers") or []:
        if key.lower() == name:
            return value.decode("latin-1", errors="replace")[:max_length]
    return ""


class UploadTransportProbeMiddleware:
    """Log upload-session HTTP boundaries without reading request bodies."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        raw_path = str(scope.get("path") or "")
        if not (
            raw_path == "/api/v1/upload-sessions"
            or raw_path.startswith("/api/v1/upload-sessions/")
        ):
            await self.app(scope, receive, send)
            return

        path = raw_path[:1024]
        method = str(scope.get("method") or "")[:16]
        origin = _scope_header(scope, b"origin")
        requested_method = _scope_header(scope, b"access-control-request-method")
        requested_headers = _scope_header(scope, b"access-control-request-headers")
        content_length = _scope_header(scope, b"content-length")
        authorization_present = bool(_scope_header(scope, b"authorization", max_length=1))
        started = time.monotonic()
        status_code = None

        logger.info(
            "RESUMABLE_UPLOAD_HTTP_ENTERED method=%s path=%s origin=%s "
            "access_control_request_method=%s access_control_request_headers=%s "
            "content_length=%s authorization_present=%s",
            method,
            path,
            origin,
            requested_method,
            requested_headers,
            content_length,
            authorization_present,
        )

        async def send_probe(message):
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = message.get("status")
            await send(message)

        try:
            await self.app(scope, receive, send_probe)
        except Exception:
            logger.exception(
                "RESUMABLE_UPLOAD_HTTP_FAILED method=%s path=%s elapsed_ms=%s",
                method,
                path,
                int((time.monotonic() - started) * 1000),
            )
            raise

        logger.info(
            "RESUMABLE_UPLOAD_HTTP_COMPLETED method=%s path=%s status=%s elapsed_ms=%s",
            method,
            path,
            status_code,
            int((time.monotonic() - started) * 1000),
        )


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
# Add the transport probe last so it is outside CORS and can observe preflight
# OPTIONS requests that never reach an application route. The probe never reads
# request bodies or Authorization values.
app.add_middleware(UploadTransportProbeMiddleware)

from app.database import init_db  # noqa: E402
from app.production_sqlite_second_recovery_cutover import (  # noqa: E402
    execute_production_sqlite_second_recovery_cutover,
)
from app.processing import install_refinement_provider_stderr_handler  # noqa: E402
from app.processing.s0_stale_processing_run_recovery import (  # noqa: E402
    recover_stale_s0_pdf_processing_runs,
)
from app.processing.structure_refinement_config_snapshot import (  # noqa: E402
    validate_and_log_structure_refinement_config,
)
from app.routers import (  # noqa: E402
    access,
    books,
    direct_upload,
    health,
    images,
    ocr,
    processing_operator,
    reader,
    reader_v2,
    resumable_upload,
    source_transport,
    study,
)

# Include normal application routers.
app.include_router(health.router)
app.include_router(access.router)
app.include_router(ocr.router)
app.include_router(resumable_upload.router)
app.include_router(direct_upload.router)
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


def _log_stale_recovery_report(prefix: str, report) -> None:
    logger.info(
        "%s scanned=%s recovered=%s skipped_fresh=%s "
        "skipped_non_processing_document=%s errors=%s",
        prefix,
        report.scanned,
        report.recovered,
        report.skipped_fresh,
        report.skipped_non_processing_document,
        report.errors,
    )


async def _stale_processing_run_recovery_loop() -> None:
    """Run stale-run recovery immediately in the background, then at low rate."""
    while True:
        try:
            report = await asyncio.to_thread(recover_stale_s0_pdf_processing_runs)
        except asyncio.CancelledError:
            raise
        except Exception:
            # The synchronous recovery already fails open per row/discovery. This
            # boundary also protects the long-lived sweep from an unexpected bug.
            logger.exception("S0 stale ProcessingRun recovery sweep failed open")
        else:
            if report.recovered or report.errors:
                _log_stale_recovery_report("S0 stale ProcessingRun recovery sweep", report)

        # Always rate-limit the loop, including after an unexpected exception, so
        # a database/provider fault cannot turn recovery into a hot retry loop.
        await asyncio.sleep(S0_STALE_RECOVERY_SWEEP_SECONDS)


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
    global _stale_processing_run_recovery_task

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

    # Database schema readiness remains a hard startup requirement. Best-effort
    # stale-worker recovery is deliberately kept out of the HF readiness-critical
    # path and starts in the background immediately after this coroutine returns.
    init_db()
    configure_application_logging()
    install_refinement_provider_stderr_handler()

    # A restart can occur seconds after the previous heartbeat. The background
    # task performs one immediate sweep, preserving fresh rows via the existing
    # five-minute heartbeat lease, then repeats at the low-rate interval. Healthy
    # workers continue writing 60-second heartbeats and remain outside the stale
    # window. Recovery policy, row locks and terminal state transitions are
    # unchanged; only scheduling moves out of the synchronous startup path.
    if (
        _stale_processing_run_recovery_task is None
        or _stale_processing_run_recovery_task.done()
    ):
        _stale_processing_run_recovery_task = asyncio.create_task(
            _stale_processing_run_recovery_loop(),
            name="s0-stale-processing-run-recovery",
        )

    logger.info("Database initialized")


@app.on_event("shutdown")
async def shutdown_event():
    global _stale_processing_run_recovery_task

    task = _stale_processing_run_recovery_task
    _stale_processing_run_recovery_task = None
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("PDF OCR Service stopped")
