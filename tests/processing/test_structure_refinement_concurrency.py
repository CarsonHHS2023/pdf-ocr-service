from __future__ import annotations

import asyncio

import pytest

from app.processing.structure_refinement_concurrency import (
    ProcessStructureRefinementLimiter,
    _reset_process_structure_refinement_limiter_for_tests,
    process_structure_refinement_limiter_from_env,
)


def test_process_limiter_bounds_concurrency_across_event_loops() -> None:
    limiter = ProcessStructureRefinementLimiter(2)
    active = 0
    peak = 0
    state_lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal active, peak
        async with limiter:
            async with state_lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.01)
            async with state_lock:
                active -= 1

    async def run() -> None:
        await asyncio.gather(*(worker() for _ in range(6)))

    asyncio.run(run())
    assert peak == 2


def test_env_factory_returns_one_process_limiter(monkeypatch) -> None:
    _reset_process_structure_refinement_limiter_for_tests()
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_GLOBAL_MAX_CONCURRENT_BATCHES", "3")

    first = process_structure_refinement_limiter_from_env()
    second = process_structure_refinement_limiter_from_env()

    assert first is second
    assert first.limit == 3
    _reset_process_structure_refinement_limiter_for_tests()


@pytest.mark.parametrize("value", ["0", "-1", "not-an-int"])
def test_env_factory_rejects_invalid_limit(monkeypatch, value: str) -> None:
    _reset_process_structure_refinement_limiter_for_tests()
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_GLOBAL_MAX_CONCURRENT_BATCHES", value)

    with pytest.raises(ValueError, match="positive integer"):
        process_structure_refinement_limiter_from_env()

    _reset_process_structure_refinement_limiter_for_tests()
