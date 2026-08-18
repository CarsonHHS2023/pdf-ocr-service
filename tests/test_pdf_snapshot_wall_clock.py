from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import shutil
import subprocess

import pytest

from app.processing import pdf_geometry_bounded as bounded
from app.processing import pdf_geometry_snapshot_worker as snapshot_worker
from app.processing.pdf_geometry_preprocessing import (
    OcrmypdfPreprocessingError,
    _PageSnapshot,
    _SnapshotWorkBudget,
)


def _pdf(*, pages: int = 1) -> bytes:
    import fitz

    document = fitz.open()
    try:
        for page_index in range(pages):
            page = document.new_page(width=400, height=500)
            page.insert_text((50, 80), f"bounded snapshot {page_index}")
        return document.tobytes(garbage=4, deflate=True)
    finally:
        document.close()


def _snapshot(*, render_sha256: str = "a" * 64) -> _PageSnapshot:
    return _PageSnapshot(
        render_sha256=render_sha256,
        render_size=(400, 500),
        media_size_points=(400.0, 500.0),
        crop_size_points=(400.0, 500.0),
        source_xres=0,
        source_yres=0,
        effective_xdpi=0.0,
        effective_ydpi=0.0,
    )


def test_terminal_snapshot_worker_round_trip() -> None:
    budget = _SnapshotWorkBudget(max_total_pixels=1_000_000)

    pages = bounded._inspect_pdf_in_terminal_process(
        _pdf(),
        budget=budget,
        timeout_seconds=10.0,
        known_page_count=1,
    )

    assert len(pages) == 1
    assert len(pages[0].render_sha256) == 64
    assert pages[0].render_size == (400, 500)
    assert budget.used_pixels == 200_000


def test_snapshot_worker_writes_page_count_before_page_content_inspection(
    monkeypatch,
    tmp_path,
) -> None:
    input_path = tmp_path / "input.pdf"
    result_path = tmp_path / "snapshot.json"
    input_path.write_bytes(_pdf(pages=2))

    def stop_during_preflight(document, *, budget):
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        assert payload == {
            "page_count": 2,
            "pages": [],
            "status": "structure",
            "used_pixels": 0,
        }
        raise OcrmypdfPreprocessingError("pdf_snapshot_preflight_stopped")

    monkeypatch.setattr(snapshot_worker, "_snapshot_scales", stop_during_preflight)

    with pytest.raises(
        OcrmypdfPreprocessingError,
        match="pdf_snapshot_preflight_stopped",
    ):
        snapshot_worker._run(input_path, result_path, 1_000_000)

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["status"] == "structure"
    assert payload["page_count"] == 2


@pytest.mark.skipif(os.name != "posix", reason="POSIX terminal process group")
def test_snapshot_worker_timeout_kills_and_reaps_terminal_process(monkeypatch) -> None:
    observed = {
        "command": None,
        "popen_options": None,
        "signals": [],
        "communicate_calls": 0,
        "parent_structure": None,
    }

    class FakeProcess:
        pid = 2468
        returncode = None

        def communicate(self, *, timeout):
            observed["communicate_calls"] += 1
            if observed["communicate_calls"] == 1:
                raise subprocess.TimeoutExpired("snapshot-worker", timeout)
            self.returncode = -int(signal.SIGKILL)
            return "", ""

        def kill(self):
            raise AssertionError("POSIX worker must be killed through its group")

        def wait(self, *, timeout):
            raise AssertionError("second communicate call reaps the worker")

    def fake_popen(command, **kwargs):
        observed["command"] = command
        observed["popen_options"] = kwargs
        result_path = Path(command[4])
        observed["parent_structure"] = json.loads(
            result_path.read_text(encoding="utf-8")
        )
        return FakeProcess()

    monkeypatch.setattr(bounded.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        bounded.os,
        "killpg",
        lambda pid, sig: observed["signals"].append((pid, sig)),
    )

    with pytest.raises(
        bounded._SnapshotRenderingTimeout,
        match="pdf_snapshot_timeout",
    ) as captured:
        bounded._inspect_pdf_in_terminal_process(
            _pdf(pages=3),
            budget=_SnapshotWorkBudget(),
            timeout_seconds=0.01,
            known_page_count=3,
        )

    assert observed["command"][1:3] == (
        "-m",
        "app.processing.pdf_geometry_snapshot_worker",
    )
    assert observed["popen_options"]["start_new_session"] is True
    assert observed["parent_structure"] == {
        "page_count": 3,
        "pages": [],
        "status": "structure",
        "used_pixels": 0,
    }
    assert len(captured.value.pages) == 3
    assert all(page.render_size == (0, 0) for page in captured.value.pages)
    assert observed["signals"] == [(2468, signal.SIGKILL)]
    assert observed["communicate_calls"] == 2


def test_source_snapshot_timeout_fails_open_before_ocrmypdf(monkeypatch) -> None:
    source = _pdf()
    preflight = _snapshot(render_sha256="")

    def timeout_snapshot(*args, **kwargs):
        raise bounded._SnapshotRenderingTimeout((preflight,))

    class Runner:
        def run(self, input_pdf, output_pdf, *, timeout_seconds):
            raise AssertionError("OCRmyPDF must not start after source snapshot timeout")

    monkeypatch.setattr(
        bounded,
        "_inspect_pdf_in_terminal_process",
        timeout_snapshot,
    )

    result = bounded.preprocess_pdf_geometry_bounded(
        source,
        expected_page_count=1,
        runner=Runner(),
        timeout_seconds=30,
    )

    assert result.pdf_bytes == source
    assert result.page_count == 1
    assert result.changed_page_count == 0
    assert result.pages[0].fallback_used is True
    assert result.pages[0].safe_reason == "pdf_snapshot_timeout"


def test_source_snapshot_timeout_preserves_structural_page_count(monkeypatch) -> None:
    source = _pdf(pages=3)
    structural_pages = bounded._preflight_pages(
        {
            "status": "structure",
            "page_count": 3,
            "used_pixels": 0,
            "pages": [],
        }
    )

    def timeout_snapshot(*args, **kwargs):
        assert kwargs["known_page_count"] == 3
        raise bounded._SnapshotRenderingTimeout(structural_pages)

    class Runner:
        def run(self, input_pdf, output_pdf, *, timeout_seconds):
            raise AssertionError("OCRmyPDF must not start after source snapshot timeout")

    monkeypatch.setattr(
        bounded,
        "_inspect_pdf_in_terminal_process",
        timeout_snapshot,
    )

    result = bounded.preprocess_pdf_geometry_bounded(
        source,
        expected_page_count=3,
        runner=Runner(),
        timeout_seconds=30,
    )

    assert result.pdf_bytes == source
    assert result.page_count == 3
    assert len(result.pages) == 3
    assert [page.page_index for page in result.pages] == [0, 1, 2]
    assert all(page.input_size == (0, 0) for page in result.pages)
    assert all(page.output_size == (0, 0) for page in result.pages)
    assert all(page.fallback_used for page in result.pages)
    assert all(page.safe_reason == "pdf_snapshot_timeout" for page in result.pages)


def test_all_phases_share_one_preprocessing_deadline(monkeypatch) -> None:
    source = _pdf()
    page = _snapshot()
    snapshot_timeouts = []
    known_page_counts = []
    runner_timeouts = []
    monotonic_values = iter((100.0, 101.0, 105.0, 106.0))

    def fake_snapshot(
        pdf_bytes,
        *,
        budget,
        timeout_seconds,
        known_page_count,
    ):
        snapshot_timeouts.append(timeout_seconds)
        known_page_counts.append(known_page_count)
        return (page,)

    class CopyRunner:
        def run(
            self,
            input_pdf: Path,
            output_pdf: Path,
            *,
            timeout_seconds: int,
        ) -> None:
            runner_timeouts.append(timeout_seconds)
            shutil.copyfile(input_pdf, output_pdf)

    monkeypatch.setattr(
        bounded,
        "_inspect_pdf_in_terminal_process",
        fake_snapshot,
    )
    monkeypatch.setattr(
        bounded.time,
        "monotonic",
        lambda: next(monotonic_values),
    )

    result = bounded.preprocess_pdf_geometry_bounded(
        source,
        expected_page_count=1,
        runner=CopyRunner(),
        timeout_seconds=30,
    )

    assert result.pdf_bytes == source
    assert snapshot_timeouts == [29.0, 24.0]
    assert known_page_counts == [1, 1]
    assert runner_timeouts == [25]
