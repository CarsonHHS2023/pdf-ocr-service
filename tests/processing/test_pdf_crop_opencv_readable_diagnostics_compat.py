from __future__ import annotations

import json
from pathlib import Path

from app.processing import pdf_crop_opencv_readable_diagnostics_compat as readable


def test_write_record_creates_human_readable_stage_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(readable, "_ROOT", tmp_path)
    record = {
        "before_png": b"before",
        "raw_opencv_png": b"raw",
        "semantic_candidate_png": b"anchored",
    }
    histogram = {
        "plot_png": b"plot",
        "data_json": b'{"histogram":true}',
    }

    readable._write_record(
        asset_id="pdf-visual:test:asset",
        node_id="node:test",
        record=record,
        histogram=histogram,
    )

    folders = [item for item in tmp_path.iterdir() if item.is_dir()]
    assert len(folders) == 1
    folder = folders[0]
    assert (folder / "crop-before.png").read_bytes() == b"before"
    assert (folder / "crop-opencv-raw.png").read_bytes() == b"raw"
    assert (folder / "crop-anchor-restored.png").read_bytes() == b"anchored"
    assert (folder / "crop-histogram.png").read_bytes() == b"plot"
    assert (folder / "crop-histogram.json").read_bytes() == b'{"histogram":true}'
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["asset_id"] == "pdf-visual:test:asset"
    assert manifest["stages"]["crop-opencv-raw.png"] == "raw_opencv_before_dark_anchor"
    assert manifest["stages"]["crop-anchor-restored.png"] == "semantic_candidate_after_dark_anchor"
    assert set(manifest["checksums"]) == {
        "crop-before.png",
        "crop-opencv-raw.png",
        "crop-anchor-restored.png",
        "crop-histogram.png",
        "crop-histogram.json",
    }


def test_malformed_record_is_ignored_without_writes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(readable, "_ROOT", tmp_path)
    readable._write_record(
        asset_id="pdf-visual:bad",
        node_id=None,
        record={
            "before_png": b"before",
            "raw_opencv_png": b"raw",
            "semantic_candidate_png": object(),  # type: ignore[dict-item]
        },
        histogram=None,
    )
    assert list(tmp_path.iterdir()) == []


def test_safe_component_removes_storage_path_metacharacters() -> None:
    assert readable._safe_component("pdf-visual:a/b:c") == "pdf-visual_a_b_c"
    assert "/" not in readable._safe_component("../escape")
