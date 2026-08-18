"""Wall-clock-bounded production wrapper for OCRmyPDF geometry preprocessing.

PyMuPDF can spend unbounded CPU time interpreting a pathological page content
stream even when the requested raster dimensions are small. Production snapshot
renders therefore run in a terminal child process. The parent can kill that
process on a fixed deadline without leaving the sole preprocessing worker stuck
inside ``Page.get_pixmap()``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any

from app.processing.pdf_geometry_preprocessing import (
    GeometryPreprocessedPdf,
    OcrmypdfPreprocessingError,
    OcrmypdfRunner,
    SubprocessOcrmypdfRunner,
    _PageSnapshot,
    _SnapshotWorkBudget,
    _fallback_result,
    _page_result,
    _timeout_seconds,
    _unchanged_result,
    _validate_output_geometry,
)

logger = logging.getLogger(__name__)

_DEFAULT_SNAPSHOT_TIMEOUT_SECONDS = 120.0
_MAX_SNAPSHOT_TIMEOUT_SECONDS = 300.0
_SNAPSHOT_RESULT_MAX_BYTES = 2_000_000
_SNAPSHOT_WORKER_MODULE = "app.processing.pdf_geometry_snapshot_worker"


class _SnapshotRenderingTimeout(OcrmypdfPreprocessingError):
    """A terminal snapshot worker exceeded its wall-clock allowance."""

    def __init__(self, pages: tuple[_PageSnapshot, ...] = ()) -> None:
        super().__init__("pdf_snapshot_timeout")
        self.pages = pages


def preprocess_pdf_geometry_bounded(
    pdf_bytes: bytes,
    *,
    expected_page_count: int | None = None,
    runner: OcrmypdfRunner | None = None,
    timeout_seconds: int | None = None,
    deskewer: object | None = None,
    unwarper: object | None = None,
) -> GeometryPreprocessedPdf:
    """Run production preprocessing with bounded snapshot and overall phases.

    Snapshot rasterization is isolated from the backend process. A separate
    per-snapshot cap prevents a complex source or output page from consuming the
    dedicated preprocessing worker for the full OCRmyPDF allowance. All phases
    also share the existing preprocessing deadline, so time already spent on the
    source snapshot is not granted again to OCRmyPDF or the output snapshot.

    ``expected_page_count`` is the count established by upload validation. It is
    persisted by the parent before the snapshot subprocess is launched so worker
    startup/import/open timeouts still retain one fallback record per known page.
    """
    del deskewer, unwarper
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("pdf_bytes must contain a PDF")

    known_page_count = (
        _bounded_page_count(expected_page_count)
        if expected_page_count is not None
        else None
    )
    selected_runner = runner or SubprocessOcrmypdfRunner()
    selected_timeout = _timeout_seconds(timeout_seconds)
    deadline = time.monotonic() + selected_timeout
    snapshot_budget = _SnapshotWorkBudget()

    try:
        source_pages = _inspect_pdf_in_terminal_process(
            pdf_bytes,
            budget=snapshot_budget,
            timeout_seconds=_snapshot_phase_timeout(deadline),
            known_page_count=known_page_count,
        )
    except _SnapshotRenderingTimeout as exc:
        logger.warning("PDF source snapshot timed out; using retained source")
        return _fallback_result(pdf_bytes, exc.pages, str(exc))

    if not source_pages:
        raise ValueError("PDF must contain at least one page")

    try:
        with tempfile.TemporaryDirectory(prefix="atlas-ocrmypdf-") as temp_dir:
            input_path = Path(temp_dir) / "input.pdf"
            output_path = Path(temp_dir) / "output.pdf"
            input_path.write_bytes(pdf_bytes)
            selected_runner.run(
                input_path,
                output_path,
                timeout_seconds=_remaining_runner_timeout(deadline),
            )
            processed_bytes = output_path.read_bytes()

        if not processed_bytes.startswith(b"%PDF-"):
            raise OcrmypdfPreprocessingError("ocrmypdf_invalid_output")
        output_pages = _inspect_pdf_in_terminal_process(
            processed_bytes,
            budget=snapshot_budget,
            timeout_seconds=_snapshot_phase_timeout(deadline),
            known_page_count=len(source_pages),
        )
        _validate_output_geometry(source_pages, output_pages)
    except Exception as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        reason = (
            str(exc)
            if isinstance(exc, OcrmypdfPreprocessingError)
            else f"ocrmypdf_validation_{type(exc).__name__}"
        )
        logger.warning("OCRmyPDF preprocessing failed open reason=%s", reason)
        return _fallback_result(pdf_bytes, source_pages, reason)

    changed = tuple(
        source.render_sha256 != output.render_sha256
        for source, output in zip(source_pages, output_pages, strict=True)
    )
    if not any(changed):
        return _unchanged_result(pdf_bytes, source_pages)

    page_results = tuple(
        _page_result(
            page_index=index,
            source=source,
            output=output,
            changed=page_changed,
        )
        for index, (source, output, page_changed) in enumerate(
            zip(source_pages, output_pages, changed, strict=True)
        )
    )
    checksum = hashlib.sha256(processed_bytes).hexdigest()
    return GeometryPreprocessedPdf(
        pdf_bytes=processed_bytes,
        checksum_sha256=checksum,
        byte_size=len(processed_bytes),
        page_count=len(page_results),
        changed_page_count=sum(changed),
        pages=page_results,
    )


def _snapshot_timeout_seconds() -> float:
    raw = os.environ.get(
        "PDF_SNAPSHOT_TIMEOUT_SECONDS",
        str(_DEFAULT_SNAPSHOT_TIMEOUT_SECONDS),
    )
    try:
        value = float(raw)
    except ValueError:
        value = _DEFAULT_SNAPSHOT_TIMEOUT_SECONDS
    if not math.isfinite(value):
        value = _DEFAULT_SNAPSHOT_TIMEOUT_SECONDS
    return max(1.0, min(value, _MAX_SNAPSHOT_TIMEOUT_SECONDS))


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if not math.isfinite(remaining) or remaining <= 0:
        raise OcrmypdfPreprocessingError("pdf_preprocessing_timeout")
    return remaining


def _snapshot_phase_timeout(deadline: float) -> float:
    return min(_snapshot_timeout_seconds(), _remaining_seconds(deadline))


def _remaining_runner_timeout(deadline: float) -> int:
    return max(1, math.ceil(_remaining_seconds(deadline)))


def _inspect_pdf_in_terminal_process(
    pdf_bytes: bytes,
    *,
    budget: _SnapshotWorkBudget,
    timeout_seconds: float,
    known_page_count: int | None = None,
) -> tuple[_PageSnapshot, ...]:
    """Render one PDF snapshot pass in a killable terminal subprocess."""
    remaining_pixels = budget.max_total_pixels - budget.used_pixels
    if remaining_pixels <= 0:
        raise OcrmypdfPreprocessingError("pdf_snapshot_work_too_large")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise OcrmypdfPreprocessingError("pdf_preprocessing_timeout")
    bounded_known_count = (
        _bounded_page_count(known_page_count)
        if known_page_count is not None
        else None
    )

    with tempfile.TemporaryDirectory(prefix="atlas-pdf-snapshot-") as temp_dir:
        input_path = Path(temp_dir) / "input.pdf"
        result_path = Path(temp_dir) / "snapshot.json"
        input_path.write_bytes(pdf_bytes)
        if bounded_known_count is not None:
            _write_parent_structure_payload(result_path, bounded_known_count)
        command = (
            sys.executable,
            "-m",
            _SNAPSHOT_WORKER_MODULE,
            str(input_path),
            str(result_path),
            str(remaining_pixels),
        )
        popen_options: dict[str, object] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if os.name == "posix":
            popen_options["start_new_session"] = True
        elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            process = subprocess.Popen(command, **popen_options)
        except OSError as exc:
            raise OcrmypdfPreprocessingError(
                "pdf_snapshot_worker_launch_failed"
            ) from exc

        try:
            process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            _kill_snapshot_worker(process)
            payload = _read_snapshot_payload(result_path, allow_missing=True)
            pages = _preflight_pages(payload)
            if not pages and bounded_known_count is not None:
                pages = _unknown_page_snapshots(bounded_known_count)
            raise _SnapshotRenderingTimeout(pages) from exc

        if process.returncode != 0:
            raise OcrmypdfPreprocessingError("pdf_snapshot_worker_failed")

        payload = _read_snapshot_payload(result_path)
        status = payload.get("status")
        if status == "error":
            raise OcrmypdfPreprocessingError(_safe_worker_error(payload.get("error")))
        if status != "complete":
            raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")

        used_pixels = payload.get("used_pixels")
        if (
            isinstance(used_pixels, bool)
            or not isinstance(used_pixels, int)
            or used_pixels < 0
            or used_pixels > remaining_pixels
        ):
            raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")
        pages = _decode_snapshot_pages(payload.get("pages"), allow_empty_hash=False)
        if bounded_known_count is not None and len(pages) != bounded_known_count:
            raise OcrmypdfPreprocessingError("pdf_snapshot_page_count_changed")
        budget.reserve(used_pixels)
        return pages


def _write_parent_structure_payload(result_path: Path, page_count: int) -> None:
    """Persist upload-known structure before worker startup can consume time."""
    payload = {
        "status": "structure",
        "page_count": _bounded_page_count(page_count),
        "used_pixels": 0,
        "pages": [],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    temporary_path = result_path.with_name(f".{result_path.name}.parent.tmp")
    temporary_path.write_text(encoded, encoding="utf-8")
    os.replace(temporary_path, result_path)


def _kill_snapshot_worker(process: subprocess.Popen[str]) -> None:
    """Kill and reap the terminal worker; it intentionally has no descendants."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            logger.warning(
                "Could not kill PDF snapshot worker process group pid=%s",
                process.pid,
                exc_info=True,
            )
    else:
        try:
            process.kill()
        except ProcessLookupError:
            pass

    try:
        process.communicate(timeout=5.0)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        process.kill()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5.0)
    except (subprocess.TimeoutExpired, ProcessLookupError):
        logger.error("Could not reap PDF snapshot worker pid=%s", process.pid)


def _read_snapshot_payload(
    result_path: Path,
    *,
    allow_missing: bool = False,
) -> dict[str, Any] | None:
    try:
        size = result_path.stat().st_size
    except FileNotFoundError:
        if allow_missing:
            return None
        raise OcrmypdfPreprocessingError("pdf_snapshot_worker_missing_result")
    if size <= 0 or size > _SNAPSHOT_RESULT_MAX_BYTES:
        raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OcrmypdfPreprocessingError(
            "pdf_snapshot_worker_invalid_result"
        ) from exc
    if not isinstance(payload, dict):
        raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")
    return payload


def _preflight_pages(payload: dict[str, Any] | None) -> tuple[_PageSnapshot, ...]:
    if not payload:
        return ()

    status = payload.get("status")
    if status == "preflight":
        try:
            pages = _decode_snapshot_pages(
                payload.get("pages"),
                allow_empty_hash=True,
            )
            page_count = payload.get("page_count")
            if page_count is not None and _bounded_page_count(page_count) != len(pages):
                return ()
            return pages
        except OcrmypdfPreprocessingError:
            return ()

    if status != "structure":
        return ()
    try:
        page_count = _bounded_page_count(payload.get("page_count"))
    except OcrmypdfPreprocessingError:
        return ()
    return _unknown_page_snapshots(page_count)


def _unknown_page_snapshots(page_count: int) -> tuple[_PageSnapshot, ...]:
    return tuple(_unknown_page_snapshot() for _ in range(page_count))


def _unknown_page_snapshot() -> _PageSnapshot:
    """Represent one structurally known page whose content metadata timed out."""
    return _PageSnapshot(
        render_sha256="",
        render_size=(0, 0),
        media_size_points=(0.0, 0.0),
        crop_size_points=(0.0, 0.0),
        source_xres=0,
        source_yres=0,
        effective_xdpi=0.0,
        effective_ydpi=0.0,
    )


def _bounded_page_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 750:
        raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")
    return value


def _safe_worker_error(value: object) -> str:
    if (
        isinstance(value, str)
        and 0 < len(value) <= 128
        and value.startswith(("pdf_", "ocrmypdf_"))
        and all(character.isalnum() or character == "_" for character in value)
    ):
        return value
    return "pdf_snapshot_worker_failed"


def _decode_snapshot_pages(
    value: object,
    *,
    allow_empty_hash: bool,
) -> tuple[_PageSnapshot, ...]:
    if not isinstance(value, list) or len(value) > 750:
        raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")
    pages: list[_PageSnapshot] = []
    for item in value:
        if not isinstance(item, dict):
            raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")
        render_sha256 = item.get("render_sha256")
        if allow_empty_hash and render_sha256 == "":
            pass
        elif (
            not isinstance(render_sha256, str)
            or len(render_sha256) != 64
            or any(character not in "0123456789abcdef" for character in render_sha256)
        ):
            raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")

        render_size = _int_pair(item.get("render_size"), allow_zero=False)
        media_size = _float_pair(item.get("media_size_points"), allow_zero=False)
        crop_size = _float_pair(item.get("crop_size_points"), allow_zero=False)
        source_xres = _bounded_nonnegative_int(item.get("source_xres"))
        source_yres = _bounded_nonnegative_int(item.get("source_yres"))
        effective_xdpi = _bounded_nonnegative_float(item.get("effective_xdpi"))
        effective_ydpi = _bounded_nonnegative_float(item.get("effective_ydpi"))
        pages.append(
            _PageSnapshot(
                render_sha256=render_sha256,
                render_size=render_size,
                media_size_points=media_size,
                crop_size_points=crop_size,
                source_xres=source_xres,
                source_yres=source_yres,
                effective_xdpi=effective_xdpi,
                effective_ydpi=effective_ydpi,
            )
        )
    return tuple(pages)


def _int_pair(value: object, *, allow_zero: bool) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")
    result: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")
        minimum = 0 if allow_zero else 1
        if item < minimum or item > 2_000_000:
            raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")
        result.append(item)
    return result[0], result[1]


def _float_pair(value: object, *, allow_zero: bool) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")
        number = float(item)
        minimum = 0.0 if allow_zero else 0.0
        if not math.isfinite(number) or number <= minimum or number > 1_000_000.0:
            raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")
        result.append(number)
    return result[0], result[1]


def _bounded_nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2_000_000:
        raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")
    return value


def _bounded_nonnegative_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 2_000_000.0:
        raise OcrmypdfPreprocessingError("pdf_snapshot_worker_invalid_result")
    return number
