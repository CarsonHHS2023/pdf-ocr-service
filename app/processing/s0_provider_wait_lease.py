"""Durable ProcessingRun lease renewal while an S0 worker awaits the provider.

The stale-run recovery lease is intentionally short (five minutes) so a lost
in-process worker converges quickly.  Provider polling/canonicalization can
legitimately run much longer, so the owning Atlas task must continue renewing
that same durable lease while it is alive.

This helper does not alter provider polling, timeout, cancellation, batching, or
quality policy.  It only runs a fail-open companion heartbeat task around the
authoritative awaitable.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
from typing import Awaitable, TypeVar

from app.processing.s0_pdf_resource_heartbeat import record_pdf_processing_heartbeat


logger = logging.getLogger("uvicorn.error")
PROVIDER_WAIT_HEARTBEAT_SECONDS = 60.0
_T = TypeVar("_T")


async def _provider_wait_heartbeat_loop(
    *,
    processing_run_id: str,
    document_id: str,
    page_count: int,
    provider_job_id: str,
    interval_seconds: float,
) -> None:
    interval = max(1.0, float(interval_seconds))
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(
                record_pdf_processing_heartbeat,
                processing_run_id=processing_run_id,
                document_id=document_id,
                phase="provider_wait_liveness",
                page_number=page_count,
                page_count=page_count,
                provider_job_id=provider_job_id,
                current_stage="provider_wait",
                last_completed_page=page_count,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Lease telemetry is protective observability.  A transient database
            # failure must not replace the authoritative provider result/error.
            logger.exception(
                "PDF provider-wait lease heartbeat failed open "
                "processing_run_id=%s document_id=%s",
                processing_run_id,
                document_id,
            )


async def await_with_pdf_processing_lease(
    awaitable: Awaitable[_T],
    *,
    processing_run_id: str,
    document_id: str,
    page_count: int,
    provider_job_id: str,
    heartbeat_interval_seconds: float = PROVIDER_WAIT_HEARTBEAT_SECONDS,
) -> _T:
    """Await provider work while the live Atlas task renews its durable lease."""
    if int(page_count) <= 0:
        raise ValueError("page_count must be positive")

    heartbeat_task = asyncio.create_task(
        _provider_wait_heartbeat_loop(
            processing_run_id=processing_run_id,
            document_id=document_id,
            page_count=int(page_count),
            provider_job_id=provider_job_id,
            interval_seconds=heartbeat_interval_seconds,
        ),
        name=f"pdf-provider-wait-lease:{processing_run_id}",
    )
    try:
        # Do not shield or wrap the authoritative awaitable: caller cancellation
        # and provider exceptions retain their existing semantics.
        return await awaitable
    finally:
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task


__all__ = [
    "PROVIDER_WAIT_HEARTBEAT_SECONDS",
    "await_with_pdf_processing_lease",
]
