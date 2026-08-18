"""Terminal subprocess used to render bounded PDF comparison snapshots."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sys

from app.processing.pdf_geometry_preprocessing import (
    OcrmypdfPreprocessingError,
    _PageSnapshot,
    _SnapshotWorkBudget,
    _full_page_image_resolution,
    _snapshot_scales,
)


def _snapshot_payload(snapshot: _PageSnapshot) -> dict[str, object]:
    return {
        "render_sha256": snapshot.render_sha256,
        "render_size": list(snapshot.render_size),
        "media_size_points": list(snapshot.media_size_points),
        "crop_size_points": list(snapshot.crop_size_points),
        "source_xres": snapshot.source_xres,
        "source_yres": snapshot.source_yres,
        "effective_xdpi": snapshot.effective_xdpi,
        "effective_ydpi": snapshot.effective_ydpi,
    }


def _write_payload(result_path: Path, payload: dict[str, object]) -> None:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    temporary_path = result_path.with_name(f".{result_path.name}.tmp")
    temporary_path.write_text(encoded, encoding="utf-8")
    os.replace(temporary_path, result_path)


def _run(input_path: Path, result_path: Path, max_total_pixels: int) -> None:
    import fitz  # type: ignore[import]

    budget = _SnapshotWorkBudget(max_total_pixels=max_total_pixels)
    document = fitz.open(input_path)
    try:
        page_count = int(document.page_count)
        _write_payload(
            result_path,
            {
                "status": "structure",
                "page_count": page_count,
                "used_pixels": 0,
                "pages": [],
            },
        )

        scales = _snapshot_scales(document, budget=budget)
        preflight_pages: list[_PageSnapshot] = []
        for page_index, scale in enumerate(scales):
            page = document.load_page(page_index)
            render_width = max(1, math.ceil(float(page.rect.width) * scale))
            render_height = max(1, math.ceil(float(page.rect.height) * scale))
            xres, yres, xdpi, ydpi = _full_page_image_resolution(page)
            preflight_pages.append(
                _PageSnapshot(
                    render_sha256="",
                    render_size=(render_width, render_height),
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

        _write_payload(
            result_path,
            {
                "status": "preflight",
                "page_count": page_count,
                "used_pixels": budget.used_pixels,
                "pages": [_snapshot_payload(page) for page in preflight_pages],
            },
        )

        completed_pages: list[_PageSnapshot] = []
        for page_index, (scale, preflight) in enumerate(
            zip(scales, preflight_pages, strict=True)
        ):
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
            completed_pages.append(
                _PageSnapshot(
                    render_sha256=digest.hexdigest(),
                    render_size=(pixmap.width, pixmap.height),
                    media_size_points=preflight.media_size_points,
                    crop_size_points=preflight.crop_size_points,
                    source_xres=preflight.source_xres,
                    source_yres=preflight.source_yres,
                    effective_xdpi=preflight.effective_xdpi,
                    effective_ydpi=preflight.effective_ydpi,
                )
            )

        _write_payload(
            result_path,
            {
                "status": "complete",
                "page_count": page_count,
                "used_pixels": budget.used_pixels,
                "pages": [_snapshot_payload(page) for page in completed_pages],
            },
        )
    finally:
        document.close()


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 3:
        return 2
    input_path = Path(arguments[0])
    result_path = Path(arguments[1])
    try:
        max_total_pixels = int(arguments[2])
    except ValueError:
        return 2
    if max_total_pixels <= 0:
        return 2

    try:
        _run(input_path, result_path, max_total_pixels)
    except OcrmypdfPreprocessingError as exc:
        _write_payload(
            result_path,
            {"status": "error", "error": str(exc)},
        )
    except BaseException:
        _write_payload(
            result_path,
            {"status": "error", "error": "pdf_snapshot_worker_failed"},
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
