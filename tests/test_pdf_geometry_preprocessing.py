from __future__ import annotations

import shutil
from pathlib import Path
import signal
import subprocess

import pytest

from app.processing import pdf_geometry_preprocessing as geometry
from app.processing.pdf_geometry_preprocessing import (
    GEOMETRY_PREPROCESSING_VERSION,
    OcrmypdfPreprocessingError,
    SubprocessOcrmypdfRunner,
    _SNAPSHOT_MAX_PAGES,
    _SNAPSHOT_MAX_PIXELS,
    _SNAPSHOT_MAX_SIDE_PIXELS,
    _SNAPSHOT_MAX_TOTAL_PIXELS,
    _SnapshotWorkBudget,
    _bounded_snapshot_scale,
    _full_page_image_resolution,
    _inspect_pdf,
    _snapshot_scales,
    build_ocrmypdf_command,
    preprocess_pdf_geometry,
)


def _pdf(*, pages: int = 1, label: str = "source") -> bytes:
    import fitz

    document = fitz.open()
    try:
        for index in range(pages):
            page = document.new_page(width=400, height=500)
            page.insert_text((50, 80), f"{label}-{index}")
        return document.tobytes(garbage=4, deflate=True)
    finally:
        document.close()


class CopyRunner:
    def run(
        self,
        input_pdf: Path,
        output_pdf: Path,
        *,
        timeout_seconds: int,
    ) -> None:
        assert timeout_seconds >= 30
        shutil.copyfile(input_pdf, output_pdf)


class VisualChangeRunner:
    def run(
        self,
        input_pdf: Path,
        output_pdf: Path,
        *,
        timeout_seconds: int,
    ) -> None:
        import fitz

        document = fitz.open(input_pdf)
        try:
            page = document[0]
            page.draw_rect(
                fitz.Rect(15, 15, 45, 45),
                color=(0, 0, 0),
                fill=(0, 0, 0),
            )
            document.save(output_pdf, garbage=4, deflate=True)
        finally:
            document.close()


class FailureRunner:
    def run(
        self,
        input_pdf: Path,
        output_pdf: Path,
        *,
        timeout_seconds: int,
    ) -> None:
        raise OcrmypdfPreprocessingError("ocrmypdf_exit_6")


class PageCountChangeRunner:
    def run(
        self,
        input_pdf: Path,
        output_pdf: Path,
        *,
        timeout_seconds: int,
    ) -> None:
        output_pdf.write_bytes(_pdf(pages=2, label="bad-output"))


def test_command_uses_tesseract_orientation_without_generating_ocr_text() -> None:
    command = build_ocrmypdf_command(
        Path("input.pdf"),
        Path("output.pdf"),
        binary="ocrmypdf-test",
    )

    assert command[0] == "ocrmypdf-test"
    assert ("--ocr-engine", "tesseract") == command[1:3]
    timeout_index = command.index("--tesseract-timeout")
    assert command[timeout_index + 1] == "0"
    mode_index = command.index("--mode")
    assert command[mode_index + 1] == "force"
    assert "skip" not in command
    assert "--rotate-pages" in command
    assert "--remove-background" in command
    assert "--deskew" in command
    assert "--output-type" in command
    assert "pdf" in command
    assert "--optimize" in command
    assert "0" in command
    assert "--force-ocr" not in command
    assert ("--ocr-engine", "none") != command[1:3]
    assert command[-2:] == ("input.pdf", "output.pdf")


def test_subprocess_runner_uses_isolated_process_group_without_shell(
    monkeypatch,
    tmp_path,
) -> None:
    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    input_pdf.write_bytes(_pdf())
    captured = {}

    class FakeProcess:
        pid = 4321
        returncode = 0

        def communicate(self, *, timeout):
            captured["communicate_timeout"] = timeout
            output_pdf.write_bytes(_pdf())
            return "", ""

        def terminate(self):
            raise AssertionError("successful process must not be terminated")

        def kill(self):
            raise AssertionError("successful process must not be killed")

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    SubprocessOcrmypdfRunner("ocrmypdf-test").run(
        input_pdf,
        output_pdf,
        timeout_seconds=123,
    )

    assert ("--ocr-engine", "tesseract") == captured["command"][1:3]
    timeout_index = captured["command"].index("--tesseract-timeout")
    assert captured["command"][timeout_index + 1] == "0"
    assert captured["communicate_timeout"] == 123
    assert "shell" not in captured["kwargs"]
    if geometry.os.name == "posix":
        assert captured["kwargs"]["start_new_session"] is True
    assert output_pdf.read_bytes().startswith(b"%PDF-")


def test_subprocess_runner_returns_bounded_error_for_nonzero_exit(
    monkeypatch,
    tmp_path,
) -> None:
    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    input_pdf.write_bytes(_pdf())

    class FakeProcess:
        pid = 4321
        returncode = 6

        def communicate(self, *, timeout):
            return "", "private temp path"

    monkeypatch.setattr(subprocess, "Popen", lambda command, **kwargs: FakeProcess())

    with pytest.raises(OcrmypdfPreprocessingError, match="ocrmypdf_exit_6"):
        SubprocessOcrmypdfRunner("ocrmypdf-test").run(
            input_pdf,
            output_pdf,
            timeout_seconds=123,
        )


def test_subprocess_runner_verifies_group_and_kills_surviving_descendant(
    monkeypatch,
    tmp_path,
) -> None:
    if geometry.os.name != "posix":
        pytest.skip("POSIX process-group behavior")

    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    input_pdf.write_bytes(_pdf())
    observed = {
        "signals": [],
        "communicate_calls": 0,
        "group_waits": [],
    }

    class FakeProcess:
        pid = 9876
        returncode = None

        def communicate(self, *, timeout):
            observed["communicate_calls"] += 1
            if observed["communicate_calls"] == 1:
                raise subprocess.TimeoutExpired("ocrmypdf-test", timeout)
            self.returncode = -int(signal.SIGKILL)
            return "", ""

        def terminate(self):
            raise AssertionError("POSIX timeout must signal the process group")

        def kill(self):
            raise AssertionError("POSIX timeout must signal the process group")

        def wait(self, *, timeout):
            raise AssertionError("communicate reaps the direct process")

    def fake_popen(command, **kwargs):
        observed["popen_kwargs"] = kwargs
        return FakeProcess()

    wait_results = iter((False, True))

    def fake_wait_for_group(
        process_group_id,
        *,
        timeout_seconds,
        leader=None,
    ):
        assert leader is not None
        observed["group_waits"].append((process_group_id, timeout_seconds))
        return next(wait_results)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        geometry,
        "_wait_for_posix_process_group_exit",
        fake_wait_for_group,
    )
    monkeypatch.setattr(
        geometry.os,
        "killpg",
        lambda pid, sig: observed["signals"].append((pid, sig)),
    )

    with pytest.raises(OcrmypdfPreprocessingError, match="ocrmypdf_timeout"):
        SubprocessOcrmypdfRunner("ocrmypdf-test").run(
            input_pdf,
            output_pdf,
            timeout_seconds=123,
        )

    assert observed["popen_kwargs"]["start_new_session"] is True
    assert observed["signals"] == [
        (9876, signal.SIGTERM),
        (9876, signal.SIGKILL),
    ]
    assert observed["group_waits"] == [
        (9876, geometry._TIMEOUT_TERMINATION_GRACE_SECONDS),
        (9876, geometry._TIMEOUT_TERMINATION_GRACE_SECONDS),
    ]
    assert observed["communicate_calls"] == 2


def test_process_group_wait_observes_group_members_independent_of_pipes(
    monkeypatch,
) -> None:
    if geometry.os.name != "posix":
        pytest.skip("POSIX process-group behavior")

    group_states = iter((True, True, False))
    monotonic_values = iter((100.0, 100.0, 100.01))
    sleeps = []

    monkeypatch.setattr(
        geometry,
        "_posix_process_group_exists",
        lambda process_group_id: next(group_states),
    )
    monkeypatch.setattr(geometry.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(geometry.time, "sleep", sleeps.append)

    assert geometry._wait_for_posix_process_group_exit(
        9876,
        timeout_seconds=1.0,
    ) is True
    assert sleeps == [0.05, 0.05]


def test_process_group_wait_reaps_exited_leader_before_escalation(
    monkeypatch,
) -> None:
    if geometry.os.name != "posix":
        pytest.skip("POSIX process-group behavior")

    observed = {
        "poll_calls": 0,
        "leader_reaped": False,
    }

    class FakeProcess:
        pid = 9123
        returncode = None

        def poll(self):
            observed["poll_calls"] += 1
            observed["leader_reaped"] = True
            self.returncode = -int(signal.SIGTERM)
            return self.returncode

    process = FakeProcess()
    monkeypatch.setattr(
        geometry,
        "_posix_process_group_exists",
        lambda process_group_id: not observed["leader_reaped"],
    )

    assert geometry._wait_for_posix_process_group_exit(
        process.pid,
        timeout_seconds=1.0,
        leader=process,
    ) is True
    assert observed["poll_calls"] == 1


def test_snapshot_scale_bounds_large_page_render() -> None:
    width = 100_000.0
    height = 80_000.0

    scale = _bounded_snapshot_scale(width, height)

    rendered_width = width * scale
    rendered_height = height * scale
    assert max(rendered_width, rendered_height) <= _SNAPSHOT_MAX_SIDE_PIXELS
    assert rendered_width * rendered_height <= _SNAPSHOT_MAX_PIXELS


def test_snapshot_scale_rejects_absurd_or_invalid_page_dimensions() -> None:
    with pytest.raises(OcrmypdfPreprocessingError, match="dimensions_too_large"):
        _bounded_snapshot_scale(2_000_000.0, 612.0)
    with pytest.raises(OcrmypdfPreprocessingError, match="dimensions_invalid"):
        _bounded_snapshot_scale(float("inf"), 612.0)


def test_snapshot_page_count_is_rejected_before_any_page_load(monkeypatch) -> None:
    import fitz

    class OversizedDocument:
        page_count = _SNAPSHOT_MAX_PAGES + 1

        def __init__(self) -> None:
            self.closed = False

        def load_page(self, page_index):
            raise AssertionError("page loading must not begin above the job limit")

        def close(self) -> None:
            self.closed = True

    document = OversizedDocument()
    monkeypatch.setattr(fitz, "open", lambda *args, **kwargs: document)

    with pytest.raises(OcrmypdfPreprocessingError, match="page_count_too_large"):
        _inspect_pdf(b"%PDF-bounded-page-count")

    assert document.closed is True


def test_snapshot_total_work_is_preflighted_before_rendering() -> None:
    class Rect:
        width = 1000.0
        height = 1000.0

    class Page:
        rect = Rect()

        def get_pixmap(self, **kwargs):
            raise AssertionError("rendering must not begin before preflight passes")

    class Document:
        page_count = 2

        def load_page(self, page_index):
            return Page()

    assert _SNAPSHOT_MAX_TOTAL_PIXELS > 1_500_000
    with pytest.raises(OcrmypdfPreprocessingError, match="snapshot_work_too_large"):
        _snapshot_scales(
            Document(),
            max_pages=2,
            max_total_pixels=1_500_000,
        )


def test_snapshot_pixel_budget_is_shared_across_both_passes() -> None:
    class Rect:
        width = 1000.0
        height = 1000.0

    class Page:
        rect = Rect()

    class Document:
        page_count = 1

        def load_page(self, page_index):
            return Page()

    budget = _SnapshotWorkBudget(max_total_pixels=1_500_000)

    assert _snapshot_scales(Document(), max_pages=1, budget=budget) == (1.0,)
    assert budget.used_pixels == 1_000_000

    with pytest.raises(OcrmypdfPreprocessingError, match="snapshot_work_too_large"):
        _snapshot_scales(Document(), max_pages=1, budget=budget)

    assert budget.used_pixels == 1_000_000


def test_full_page_scan_uses_effective_dpi_without_extracting_payload() -> None:
    class Rect:
        width = 612.0
        height = 792.0

    class Document:
        def extract_image(self, xref):
            raise AssertionError("image payload must not be extracted")

    class Page:
        rect = Rect()
        parent = Document()

        def get_image_info(self, *, xrefs):
            assert xrefs is False
            return [
                {
                    "xref": 99,
                    "bbox": (10.0, 10.0, 20.0, 20.0),
                    "width": 100_000,
                    "height": 100_000,
                },
                {
                    "xref": 7,
                    "bbox": (0.0, 0.0, 612.0, 792.0),
                    "width": 2550,
                    "height": 3300,
                },
            ]

    source_xres, source_yres, effective_xdpi, effective_ydpi = (
        _full_page_image_resolution(Page())
    )

    assert (source_xres, source_yres) == (300, 300)
    assert (source_xres, source_yres) != (2550, 3300)
    assert effective_xdpi == 300.0
    assert effective_ydpi == 300.0


def test_visual_change_becomes_provider_pdf_with_ocrmypdf_provenance() -> None:
    source = _pdf()

    result = preprocess_pdf_geometry(source, runner=VisualChangeRunner())

    assert result.version == GEOMETRY_PREPROCESSING_VERSION
    assert result.version == "ocrmypdf_provider_preprocess_force_v1"
    assert result.pdf_bytes != source
    assert result.changed_page_count == 1
    assert result.page_count == 1
    assert result.pages[0].route == "ocrmypdf"
    assert result.pages[0].applied_steps == ("ocrmypdf_preprocess",)
    assert result.pages[0].fallback_used is False


def test_no_visual_change_preserves_original_pdf_bytes_and_checksum() -> None:
    source = _pdf()

    result = preprocess_pdf_geometry(source, runner=CopyRunner())

    assert result.pdf_bytes == source
    assert result.changed_page_count == 0
    assert result.pages[0].route == "no_op"
    assert result.pages[0].safe_reason == "ocrmypdf_no_visual_change"


def test_ocrmypdf_failure_fails_open_to_retained_source() -> None:
    source = _pdf()

    result = preprocess_pdf_geometry(source, runner=FailureRunner())

    assert result.pdf_bytes == source
    assert result.changed_page_count == 0
    assert result.pages[0].fallback_used is True
    assert result.pages[0].safe_reason == "ocrmypdf_exit_6"


def test_invalid_output_page_count_fails_open_to_retained_source() -> None:
    source = _pdf()

    result = preprocess_pdf_geometry(source, runner=PageCountChangeRunner())

    assert result.pdf_bytes == source
    assert result.changed_page_count == 0
    assert result.pages[0].fallback_used is True
    assert result.pages[0].safe_reason == "ocrmypdf_page_count_changed"


def test_timeout_is_bounded_from_environment(monkeypatch) -> None:
    source = _pdf()
    observed = {}

    class TimeoutCaptureRunner:
        def run(self, input_pdf, output_pdf, *, timeout_seconds):
            observed["timeout"] = timeout_seconds
            shutil.copyfile(input_pdf, output_pdf)

    monkeypatch.setenv("PDF_OCRMYPDF_TIMEOUT_SECONDS", "99999")

    preprocess_pdf_geometry(source, runner=TimeoutCaptureRunner())

    assert observed["timeout"] == 3600
