"""Install durable ingestion recovery into the existing staging recovery supervisor."""
from __future__ import annotations

from pathlib import Path


MAIN_PATH = Path("app/main.py")

_IMPORT_ANCHOR = '''from app.processing.s0_stale_processing_run_recovery import (  # noqa: E402
    recover_stale_s0_pdf_processing_runs,
)
'''
_IMPORT_REPLACEMENT = '''from app.processing.ingestion_dispatch import (  # noqa: E402
    recover_ingestion_dispatches,
    run_ingestion_dispatch,
)
from app.processing.s0_stale_processing_run_recovery import (  # noqa: E402
    recover_stale_s0_pdf_processing_runs,
)
'''

_GLOBAL_ANCHOR = '''S0_STALE_RECOVERY_SWEEP_SECONDS = 60.0
_stale_processing_run_recovery_task: asyncio.Task | None = None
'''
_GLOBAL_REPLACEMENT = '''S0_STALE_RECOVERY_SWEEP_SECONDS = 60.0
_stale_processing_run_recovery_task: asyncio.Task | None = None
_ingestion_dispatch_tasks: dict[str, asyncio.Task] = {}
'''

_LOOP_ANCHOR = '''async def _stale_processing_run_recovery_loop() -> None:
    """Low-rate lease sweep that closes the just-restarted freshness window."""
    while True:
        await asyncio.sleep(S0_STALE_RECOVERY_SWEEP_SECONDS)
        try:
            report = await asyncio.to_thread(recover_stale_s0_pdf_processing_runs)
        except asyncio.CancelledError:
            raise
        except Exception:
            # The synchronous recovery already fails open per row/discovery.  This
            # boundary also protects the long-lived sweep from an unexpected bug.
            logger.exception("S0 stale ProcessingRun recovery sweep failed open")
            continue
        if report.recovered or report.errors:
            _log_stale_recovery_report("S0 stale ProcessingRun recovery sweep", report)
'''
_LOOP_REPLACEMENT = '''def _log_ingestion_dispatch_recovery_report(prefix: str, report) -> None:
    logger.info(
        "%s scanned=%s ready=%s failed_running=%s skipped_races=%s errors=%s",
        prefix,
        report.scanned,
        len(report.ready_dispatch_ids),
        report.failed_running,
        report.skipped_races,
        report.errors,
    )


def _kick_ingestion_dispatch(dispatch_id: str) -> asyncio.Task:
    existing = _ingestion_dispatch_tasks.get(dispatch_id)
    if existing is not None and not existing.done():
        return existing

    task = asyncio.create_task(
        run_ingestion_dispatch(dispatch_id),
        name=f"ingestion-dispatch:{dispatch_id}",
    )
    _ingestion_dispatch_tasks[dispatch_id] = task

    def _consume_result(finished: asyncio.Task) -> None:
        if _ingestion_dispatch_tasks.get(dispatch_id) is finished:
            _ingestion_dispatch_tasks.pop(dispatch_id, None)
        try:
            finished.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception(
                "Durable ingestion dispatch task failed outside worker boundary dispatch_id=%s",
                dispatch_id,
            )

    task.add_done_callback(_consume_result)
    return task


async def _recover_and_kick_ingestion_dispatches(prefix: str) -> None:
    try:
        report = await asyncio.to_thread(recover_ingestion_dispatches)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Durable ingestion dispatch recovery failed open prefix=%s", prefix)
        return

    if report.scanned or report.failed_running or report.skipped_races or report.errors:
        _log_ingestion_dispatch_recovery_report(prefix, report)
    for dispatch_id in report.ready_dispatch_ids:
        _kick_ingestion_dispatch(dispatch_id)


async def _stale_processing_run_recovery_loop() -> None:
    """Single low-rate supervisor for S0 leases and durable ingestion dispatch."""
    while True:
        await asyncio.sleep(S0_STALE_RECOVERY_SWEEP_SECONDS)

        # The two recovery domains are intentionally failure-isolated. A bug or
        # transient failure in S0 recovery must not starve durable queued work,
        # and dispatch recovery must not stop the existing S0 lease sweep.
        try:
            report = await asyncio.to_thread(recover_stale_s0_pdf_processing_runs)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("S0 stale ProcessingRun recovery sweep failed open")
        else:
            if report.recovered or report.errors:
                _log_stale_recovery_report("S0 stale ProcessingRun recovery sweep", report)

        await _recover_and_kick_ingestion_dispatches(
            "Durable ingestion dispatch recovery sweep"
        )
'''

_STARTUP_ANCHOR = '''    recovery_report = recover_stale_s0_pdf_processing_runs()
    _log_stale_recovery_report("S0 stale ProcessingRun startup recovery", recovery_report)

    # A restart can occur seconds after the previous heartbeat.  The immediate
'''
_STARTUP_REPLACEMENT = '''    recovery_report = recover_stale_s0_pdf_processing_runs()
    _log_stale_recovery_report("S0 stale ProcessingRun startup recovery", recovery_report)

    # Durable business acceptance is committed before any in-process task kick.
    # Recover queued or expired-prestart dispatches immediately after database
    # initialization so a restart closes the DB-commit -> BackgroundTasks gap.
    await _recover_and_kick_ingestion_dispatches(
        "Durable ingestion dispatch startup recovery"
    )

    # A restart can occur seconds after the previous heartbeat.  The immediate
'''

_SHUTDOWN_ANCHOR = '''    task = _stale_processing_run_recovery_task
    _stale_processing_run_recovery_task = None
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("PDF OCR Service stopped")
'''
_SHUTDOWN_REPLACEMENT = '''    task = _stale_processing_run_recovery_task
    _stale_processing_run_recovery_task = None
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Clean shutdown cancels only this process's local task handles. A task that
    # had already entered running keeps its durable lease state; cancellation
    # stops its heartbeat and the lease is conservatively failed later rather
    # than automatically re-running potentially partial OCR/canonicalization.
    dispatch_tasks = list(_ingestion_dispatch_tasks.values())
    for dispatch_task in dispatch_tasks:
        if not dispatch_task.done():
            dispatch_task.cancel()
    if dispatch_tasks:
        await asyncio.gather(*dispatch_tasks, return_exceptions=True)
    _ingestion_dispatch_tasks.clear()

    logger.info("PDF OCR Service stopped")
'''


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} anchor")
    return source.replace(old, new, 1)


def patch_ingestion_dispatch_supervisor(path: Path = MAIN_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    if "Durable ingestion dispatch startup recovery" in source:
        return
    source = _replace_once(source, _IMPORT_ANCHOR, _IMPORT_REPLACEMENT, "dispatch import")
    source = _replace_once(source, _GLOBAL_ANCHOR, _GLOBAL_REPLACEMENT, "dispatch task registry")
    source = _replace_once(source, _LOOP_ANCHOR, _LOOP_REPLACEMENT, "single recovery loop")
    source = _replace_once(source, _STARTUP_ANCHOR, _STARTUP_REPLACEMENT, "startup recovery")
    source = _replace_once(source, _SHUTDOWN_ANCHOR, _SHUTDOWN_REPLACEMENT, "shutdown cleanup")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    patch_ingestion_dispatch_supervisor()


if __name__ == "__main__":
    main()
