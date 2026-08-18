"""Whole-PDF provider preprocessing through OCRmyPDF.

This is intentionally a small production-path experiment. The public integration
contract remains the existing ``GeometryPreprocessedPdf`` contract, but the
implementation now delegates scan cleanup to OCRmyPDF instead of the former
Leptonica/UVDoc router.

OCRmyPDF uses the Tesseract engine for page-orientation detection while rotating
pages, removing background, and deskewing. ``--tesseract-timeout 0`` suppresses
the OCR recognition pass and therefore prevents text-layer generation while
leaving Tesseract's non-OCR orientation work available. PaddleOCR-VL remains the
only OCR provider. Force mode deliberately rasterizes pages that already contain
printable or invisible OCR text so their scanned page images are still cleaned.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from typing import Protocol

logger = logging.getLogger(__name__)

GEOMETRY_PREPROCESSING_VERSION = "ocrmypdf_provider_preprocess_force_v1"
_DEFAULT_TIMEOUT_SECONDS = 900
_TIMEOUT_TERMINATION_GRACE_SECONDS = 5.0
_PAGE_BOX_TOLERANCE_POINTS = 0.5
_SNAPSHOT_MAX_SIDE_PIXELS = 1600
_SNAPSHOT_MAX_PIXELS = 2_000_000
_SNAPSHOT_MAX_PAGES = 750
_SNAPSHOT_MAX_TOTAL_PIXELS = 250_000_000
_MAX_PAGE_DIMENSION_POINTS = 1_000_000.0


@dataclass(frozen=True, slots=True)
class GeometryPageResult:
    page_index: int
    applied_steps: tuple[str, ...]
    deskew_angle_degrees: float
    deskew_confidence: float
    perspective_confidence: float
    perspective_distortion: float
    input_size: tuple[int, int]
    output_size: tuple[int, int]
    fallback_used: bool = False
    safe_reason: str | None = None
    route: str = "no_op"
    source_kind: str = "pdf_page"
    residual_angle_degrees: float = 0.0
    residual_confidence: float = 0.0
    source_xres: int = 0
    source_yres: int = 0
    effective_xdpi: float = 0.0
    effective_ydpi: float = 0.0


@dataclass(frozen=True, slots=True)
class GeometryPreprocessedPdf:
    pdf_bytes: bytes
    checksum_sha256: str
    byte_size: int
    page_count: int
    changed_page_count: int
    pages: tuple[GeometryPageResult, ...]
    version: str = GEOMETRY_PREPROCESSING_VERSION


@dataclass(frozen=True, slots=True)
class _PageSnapshot:
    render_sha256: str
    render_size: tuple[int, int]
    media_size_points: tuple[float, float]
    crop_size_points: tuple[float, float]
    source_xres: int
    source_yres: int
    effective_xdpi: float
    effective_ydpi: float


@dataclass(slots=True)
class _SnapshotWorkBudget:
    """One cumulative render budget shared by source and output inspections."""

    max_total_pixels: int = _SNAPSHOT_MAX_TOTAL_PIXELS
    used_pixels: int = 0

    def reserve(self, planned_pixels: int) -> None:
        if planned_pixels < 0:
            raise ValueError("planned_pixels must be non-negative")
        if self.used_pixels + planned_pixels > self.max_total_pixels:
            raise OcrmypdfPreprocessingError("pdf_snapshot_work_too_large")
        self.used_pixels += planned_pixels


class OcrmypdfPreprocessingError(RuntimeError):
    """Bounded OCRmyPDF failure suitable for fail-open preprocessing."""


class OcrmypdfRunner(Protocol):
    def run(
        self,
        input_pdf: Path,
        output_pdf: Path,
        *,
        timeout_seconds: int,
    ) -> None: ...


def build_ocrmypdf_command(
    input_pdf: Path,
    output_pdf: Path,
    *,
    binary: str = "ocrmypdf",
) -> tuple[str, ...]:
    """Build the fixed orientation-capable preprocessing command."""
    return (
        binary,
        "--ocr-engine",
        "tesseract",
        "--tesseract-timeout",
        "0",
        "--mode",
        "force",
        "--rotate-pages",
        "--remove-background",
        "--deskew",
        "--output-type",
        "pdf",
        "--optimize",
        "0",
        "--jobs",
        "1",
        str(input_pdf),
        str(output_pdf),
    )


def _signal_ocrmypdf_process_tree(
    process: subprocess.Popen[str],
    sig: signal.Signals,
) -> None:
    """Signal the OCRmyPDF process and descendants in its isolated session."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, sig)
            return
        except ProcessLookupError:
            return
        except OSError:
            logger.warning(
                "Could not signal OCRmyPDF process group pid=%s signal=%s",
                process.pid,
                int(sig),
                exc_info=True,
            )

    try:
        if sig == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()
    except ProcessLookupError:
        return


def _posix_process_group_exists(process_group_id: int) -> bool:
    """Return whether the isolated process group still has any members."""
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        logger.warning(
            "Could not inspect OCRmyPDF process group pid=%s",
            process_group_id,
            exc_info=True,
        )
        return True
    return True


def _poll_ocrmypdf_leader(process: subprocess.Popen[str]) -> None:
    """Reap an exited direct child so its zombie does not keep the group alive."""
    poll = getattr(process, "poll", None)
    if not callable(poll):
        return
    try:
        poll()
    except (ChildProcessError, OSError):
        logger.warning(
            "Could not poll OCRmyPDF leader pid=%s during process-group teardown",
            process.pid,
            exc_info=True,
        )


def _wait_for_posix_process_group_exit(
    process_group_id: int,
    *,
    timeout_seconds: float,
    leader: subprocess.Popen[str] | None = None,
) -> bool:
    """Wait for all live group members while reaping an exited direct leader."""
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        if leader is not None:
            _poll_ocrmypdf_leader(leader)
        if not _posix_process_group_exists(process_group_id):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.05, remaining))


def _reap_ocrmypdf_process(
    process: subprocess.Popen[str],
    *,
    timeout_seconds: float,
) -> None:
    """Drain pipes and reap the direct OCRmyPDF process after tree teardown."""
    try:
        process.communicate(timeout=max(0.0, timeout_seconds))
        return
    except subprocess.TimeoutExpired:
        logger.error("Could not reap OCRmyPDF process promptly pid=%s", process.pid)

    try:
        process.kill()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=max(0.0, timeout_seconds))
    except (subprocess.TimeoutExpired, ProcessLookupError):
        logger.error("Could not reap OCRmyPDF process pid=%s", process.pid)


def _terminate_ocrmypdf_process_tree(
    process: subprocess.Popen[str],
    *,
    grace_seconds: float = _TIMEOUT_TERMINATION_GRACE_SECONDS,
) -> None:
    """Terminate the whole isolated group, then escalate and reap the leader."""
    _signal_ocrmypdf_process_tree(process, signal.SIGTERM)

    if os.name == "posix":
        if _wait_for_posix_process_group_exit(
            process.pid,
            timeout_seconds=grace_seconds,
            leader=process,
        ):
            _reap_ocrmypdf_process(process, timeout_seconds=grace_seconds)
            return

        _signal_ocrmypdf_process_tree(process, signal.SIGKILL)
        if not _wait_for_posix_process_group_exit(
            process.pid,
            timeout_seconds=grace_seconds,
            leader=process,
        ):
            logger.error(
                "OCRmyPDF process group still exists after SIGKILL pid=%s",
                process.pid,
            )
        _reap_ocrmypdf_process(process, timeout_seconds=grace_seconds)
        return

    try:
        process.communicate(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass

    _signal_ocrmypdf_process_tree(process, signal.SIGKILL)
    _reap_ocrmypdf_process(process, timeout_seconds=grace_seconds)


class SubprocessOcrmypdfRunner:
    """Run OCRmyPDF in an isolated process group with bounded teardown."""

    def __init__(self, binary: str | None = None) -> None:
        self.binary = binary or os.environ.get("OCRMYPDF_BINARY", "ocrmypdf")

    def run(
        self,
        input_pdf: Path,
        output_pdf: Path,
        *,
        timeout_seconds: int,
    ) -> None:
        command = build_ocrmypdf_command(
            input_pdf,
            output_pdf,
            binary=self.binary,
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
        except FileNotFoundError as exc:
            raise OcrmypdfPreprocessingError("ocrmypdf_not_installed") from exc
        except OSError as exc:
            raise OcrmypdfPreprocessingError("ocrmypdf_launch_failed") from exc

        try:
            _, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            _terminate_ocrmypdf_process_tree(process)
            raise OcrmypdfPreprocessingError("ocrmypdf_timeout") from exc

        if process.returncode != 0:
            logger.warning(
                "OCRmyPDF exited unsuccessfully returncode=%s stderr_tail=%r",
                process.returncode,
                (stderr or "")[-1000:],
            )
            raise OcrmypdfPreprocessingError(
                f"ocrmypdf_exit_{process.returncode}"
            )
        if not output_pdf.is_file() or output_pdf.stat().st_size <= 0:
            raise OcrmypdfPreprocessingError("ocrmypdf_missing_output")


def preprocess_pdf_geometry(
    pdf_bytes: bytes,
    *,
    runner: OcrmypdfRunner | None = None,
    timeout_seconds: int | None = None,
    deskewer: object | None = None,
    unwarper: object | None = None,
) -> GeometryPreprocessedPdf:
    """Apply OCRmyPDF preprocessing and fail open to the retained source PDF.

    ``deskewer`` and ``unwarper`` remain accepted temporarily so older callers do
    not fail while this experiment replaces the previous implementation. They
    are deliberately ignored.
    """
    del deskewer, unwarper
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("pdf_bytes must contain a PDF")

    snapshot_budget = _SnapshotWorkBudget()
    source_pages = _inspect_pdf(pdf_bytes, budget=snapshot_budget)
    if not source_pages:
        raise ValueError("PDF must contain at least one page")

    selected_runner = runner or SubprocessOcrmypdfRunner()
    selected_timeout = _timeout_seconds(timeout_seconds)

    try:
        with tempfile.TemporaryDirectory(prefix="atlas-ocrmypdf-") as temp_dir:
            input_path = Path(temp_dir) / "input.pdf"
            output_path = Path(temp_dir) / "output.pdf"
            input_path.write_bytes(pdf_bytes)
            selected_runner.run(
                input_path,
                output_path,
                timeout_seconds=selected_timeout,
            )
            processed_bytes = output_path.read_bytes()

        if not processed_bytes.startswith(b"%PDF-"):
            raise OcrmypdfPreprocessingError("ocrmypdf_invalid_output")
        output_pages = _inspect_pdf(processed_bytes, budget=snapshot_budget)
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


def _timeout_seconds(explicit: int | None) -> int:
    if explicit is not None:
        value = explicit
    else:
        raw = os.environ.get(
            "PDF_OCRMYPDF_TIMEOUT_SECONDS",
            str(_DEFAULT_TIMEOUT_SECONDS),
        )
        try:
            value = int(raw)
        except ValueError:
            value = _DEFAULT_TIMEOUT_SECONDS
    return max(30, min(int(value), 3600))


def _bounded_snapshot_scale(width_points: float, height_points: float) -> float:
    """Return a render scale that bounds memory before PyMuPDF allocates pixels."""
    dimensions = (width_points, height_points)
    if any(not math.isfinite(value) or value <= 0 for value in dimensions):
        raise OcrmypdfPreprocessingError("pdf_page_dimensions_invalid")
    if any(value > _MAX_PAGE_DIMENSION_POINTS for value in dimensions):
        raise OcrmypdfPreprocessingError("pdf_page_dimensions_too_large")

    page_area = width_points * height_points
    if not math.isfinite(page_area) or page_area <= 0:
        raise OcrmypdfPreprocessingError("pdf_page_dimensions_invalid")

    side_scale = _SNAPSHOT_MAX_SIDE_PIXELS / max(dimensions)
    area_scale = math.sqrt(_SNAPSHOT_MAX_PIXELS / page_area)
    scale = min(1.0, side_scale, area_scale)
    if not math.isfinite(scale) or scale <= 0:
        raise OcrmypdfPreprocessingError("pdf_page_dimensions_invalid")
    return scale


def _snapshot_scales(
    document,
    *,
    max_pages: int = _SNAPSHOT_MAX_PAGES,
    max_total_pixels: int | None = None,
    budget: _SnapshotWorkBudget | None = None,
) -> tuple[float, ...]:
    """Preflight one pass and reserve it against the whole-job render budget."""
    if budget is not None and max_total_pixels is not None:
        raise ValueError("pass either budget or max_total_pixels, not both")
    work_budget = budget or _SnapshotWorkBudget(
        max_total_pixels=(
            _SNAPSHOT_MAX_TOTAL_PIXELS
            if max_total_pixels is None
            else max_total_pixels
        )
    )

    page_count = int(document.page_count)
    if page_count <= 0:
        return ()
    if page_count > max_pages:
        raise OcrmypdfPreprocessingError("pdf_page_count_too_large")

    scales: list[float] = []
    planned_pixels = 0
    for page_index in range(page_count):
        page = document.load_page(page_index)
        page_width = float(page.rect.width)
        page_height = float(page.rect.height)
        scale = _bounded_snapshot_scale(page_width, page_height)
        rendered_width = max(1, math.ceil(page_width * scale))
        rendered_height = max(1, math.ceil(page_height * scale))
        planned_pixels += rendered_width * rendered_height
        if planned_pixels > work_budget.max_total_pixels:
            raise OcrmypdfPreprocessingError("pdf_snapshot_work_too_large")
        scales.append(scale)

    work_budget.reserve(planned_pixels)
    return tuple(scales)


def _inspect_pdf(
    pdf_bytes: bytes,
    *,
    budget: _SnapshotWorkBudget | None = None,
) -> tuple[_PageSnapshot, ...]:
    import fitz  # type: ignore[import]

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        scales = _snapshot_scales(document, budget=budget)
        snapshots: list[_PageSnapshot] = []
        for page_index, scale in enumerate(scales):
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale),
                colorspace=fitz.csGRAY,
                alpha=False,
                annots=True,
            )
            digest = hashlib.sha256()
            digest.update(pixmap.width.to_bytes(4, "big", signed=False))
            digest.update(pixmap.height.to_bytes(4, "big", signed=False))
            digest.update(bytes(pixmap.samples))
            xres, yres, xdpi, ydpi = _full_page_image_resolution(page)
            snapshots.append(
                _PageSnapshot(
                    render_sha256=digest.hexdigest(),
                    render_size=(pixmap.width, pixmap.height),
                    media_size_points=(
                        float(page.mediabox.width),
                        float(page.mediabox.height),
                    ),
                    crop_size_points=(
                        float(page.cropbox.width),
                        float(page.cropbox.height),
                    ),
                    source_xres=xres,
                    source_yres=yres,
                    effective_xdpi=xdpi,
                    effective_ydpi=ydpi,
                )
            )
        return tuple(snapshots)
    finally:
        document.close()


def _full_page_image_resolution(page) -> tuple[int, int, float, float]:
    """Report full-page raster resolution without extracting image payloads.

    PyMuPDF's ``extract_image()`` includes the complete encoded image bytes in its
    result. Calling it merely to read x/y resolution can therefore materialize a
    very large compressed XObject. For preprocessing metadata, the effective DPI
    derived from image pixel dimensions and its placement on the page is both
    bounded and directly relevant to the rendered provider input.
    """
    page_area = max(float(page.rect.width * page.rect.height), 1.0)
    best: tuple[float, float, float] | None = None
    for info in page.get_image_info(xrefs=False):
        bbox = info.get("bbox")
        width = int(info.get("width") or 0)
        height = int(info.get("height") or 0)
        if not bbox or width <= 0 or height <= 0:
            continue
        placed_width = abs(float(bbox[2]) - float(bbox[0]))
        placed_height = abs(float(bbox[3]) - float(bbox[1]))
        if placed_width <= 0 or placed_height <= 0:
            continue
        coverage = (placed_width * placed_height) / page_area
        xdpi = width * 72.0 / placed_width
        ydpi = height * 72.0 / placed_height
        if not math.isfinite(xdpi) or not math.isfinite(ydpi):
            continue
        candidate = (coverage, xdpi, ydpi)
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None or best[0] < 0.80:
        return 0, 0, 0.0, 0.0

    effective_xdpi = round(best[1], 4)
    effective_ydpi = round(best[2], 4)
    return (
        max(0, int(round(effective_xdpi))),
        max(0, int(round(effective_ydpi))),
        effective_xdpi,
        effective_ydpi,
    )


def _validate_output_geometry(
    source_pages: tuple[_PageSnapshot, ...],
    output_pages: tuple[_PageSnapshot, ...],
) -> None:
    if len(output_pages) != len(source_pages):
        raise OcrmypdfPreprocessingError("ocrmypdf_page_count_changed")
    for source, output in zip(source_pages, output_pages, strict=True):
        if not _size_compatible(
            source.media_size_points,
            output.media_size_points,
        ):
            raise OcrmypdfPreprocessingError("ocrmypdf_mediabox_changed")
        if not _size_compatible(
            source.crop_size_points,
            output.crop_size_points,
        ):
            raise OcrmypdfPreprocessingError("ocrmypdf_cropbox_changed")


def _size_compatible(
    source: tuple[float, float],
    output: tuple[float, float],
) -> bool:
    def close(left: float, right: float) -> bool:
        return abs(left - right) <= _PAGE_BOX_TOLERANCE_POINTS

    return (
        close(source[0], output[0]) and close(source[1], output[1])
    ) or (
        close(source[0], output[1]) and close(source[1], output[0])
    )


def _page_result(
    *,
    page_index: int,
    source: _PageSnapshot,
    output: _PageSnapshot,
    changed: bool,
) -> GeometryPageResult:
    return GeometryPageResult(
        page_index=page_index,
        applied_steps=("ocrmypdf_preprocess",) if changed else (),
        deskew_angle_degrees=0.0,
        deskew_confidence=0.0,
        perspective_confidence=0.0,
        perspective_distortion=0.0,
        input_size=source.render_size,
        output_size=output.render_size,
        fallback_used=False,
        safe_reason=None if changed else "ocrmypdf_no_visual_change",
        route="ocrmypdf" if changed else "no_op",
        source_kind="pdf_page",
        source_xres=source.source_xres,
        source_yres=source.source_yres,
        effective_xdpi=(
            output.effective_xdpi
            if output.effective_xdpi > 0
            else source.effective_xdpi
        ),
        effective_ydpi=(
            output.effective_ydpi
            if output.effective_ydpi > 0
            else source.effective_ydpi
        ),
    )


def _unchanged_result(
    pdf_bytes: bytes,
    pages: tuple[_PageSnapshot, ...],
) -> GeometryPreprocessedPdf:
    results = tuple(
        _page_result(
            page_index=index,
            source=page,
            output=page,
            changed=False,
        )
        for index, page in enumerate(pages)
    )
    return GeometryPreprocessedPdf(
        pdf_bytes=pdf_bytes,
        checksum_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        byte_size=len(pdf_bytes),
        page_count=len(results),
        changed_page_count=0,
        pages=results,
    )


def _fallback_result(
    pdf_bytes: bytes,
    pages: tuple[_PageSnapshot, ...],
    reason: str,
) -> GeometryPreprocessedPdf:
    results = tuple(
        GeometryPageResult(
            page_index=index,
            applied_steps=(),
            deskew_angle_degrees=0.0,
            deskew_confidence=0.0,
            perspective_confidence=0.0,
            perspective_distortion=0.0,
            input_size=page.render_size,
            output_size=page.render_size,
            fallback_used=True,
            safe_reason=reason,
            route="no_op",
            source_kind="pdf_page",
            source_xres=page.source_xres,
            source_yres=page.source_yres,
            effective_xdpi=page.effective_xdpi,
            effective_ydpi=page.effective_ydpi,
        )
        for index, page in enumerate(pages)
    )
    return GeometryPreprocessedPdf(
        pdf_bytes=pdf_bytes,
        checksum_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        byte_size=len(pdf_bytes),
        page_count=len(results),
        changed_page_count=0,
        pages=results,
    )


__all__ = [
    "GEOMETRY_PREPROCESSING_VERSION",
    "GeometryPageResult",
    "GeometryPreprocessedPdf",
    "OcrmypdfPreprocessingError",
    "OcrmypdfRunner",
    "SubprocessOcrmypdfRunner",
    "build_ocrmypdf_command",
    "preprocess_pdf_geometry",
]
