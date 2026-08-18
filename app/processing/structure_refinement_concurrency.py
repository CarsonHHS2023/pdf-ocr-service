"""Loop-neutral process-wide concurrency protection for LLM refinement batches."""
from __future__ import annotations

import asyncio
import os
import threading
from types import TracebackType


class ProcessStructureRefinementLimiter:
    """Async context manager backed by a thread-safe process-local semaphore.

    Canonicalization may run in worker threads with separate event loops, so an
    asyncio.Semaphore cannot safely serve as the process-wide limiter. The
    underlying threading semaphore is loop-neutral; acquisition is delegated to
    a worker thread so no event loop is blocked while waiting for a permit.
    """

    def __init__(self, limit: int) -> None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("global refinement concurrency limit must be a positive integer")
        self.limit = limit
        self._semaphore = threading.BoundedSemaphore(limit)

    async def __aenter__(self) -> "ProcessStructureRefinementLimiter":
        await asyncio.to_thread(self._semaphore.acquire)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._semaphore.release()


_limiter_lock = threading.Lock()
_limiter: ProcessStructureRefinementLimiter | None = None
_limiter_size: int | None = None


def process_structure_refinement_limiter_from_env() -> ProcessStructureRefinementLimiter:
    """Return one process-local limiter, validating configuration on first use."""

    global _limiter, _limiter_size
    raw = os.getenv("PDF_STRUCTURE_REFINEMENT_GLOBAL_MAX_CONCURRENT_BATCHES", "4")
    try:
        limit = int(raw)
    except ValueError as exc:
        raise ValueError(
            "PDF_STRUCTURE_REFINEMENT_GLOBAL_MAX_CONCURRENT_BATCHES must be a positive integer"
        ) from exc
    if limit < 1:
        raise ValueError(
            "PDF_STRUCTURE_REFINEMENT_GLOBAL_MAX_CONCURRENT_BATCHES must be a positive integer"
        )

    with _limiter_lock:
        if _limiter is None:
            _limiter = ProcessStructureRefinementLimiter(limit)
            _limiter_size = limit
        elif _limiter_size != limit:
            raise RuntimeError(
                "global refinement concurrency limit cannot change after initialization"
            )
        return _limiter


def _reset_process_structure_refinement_limiter_for_tests() -> None:
    global _limiter, _limiter_size
    with _limiter_lock:
        _limiter = None
        _limiter_size = None


__all__ = [
    "ProcessStructureRefinementLimiter",
    "process_structure_refinement_limiter_from_env",
]
