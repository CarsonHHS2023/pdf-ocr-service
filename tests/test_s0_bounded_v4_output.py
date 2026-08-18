from __future__ import annotations

import hashlib
from pathlib import Path

import fitz  # type: ignore[import]

from app.processing import pdf_opencv_quality_pipeline as v4
from app.processing.pdf_geometry_preprocessing import (
    GeometryPageResult,
    GeometryPreprocessedPdf,
)
from app.processing import pdf_s0_bounded_v4_output_compat as bounded
from scripts.apply_s0_bounded_v4_output import (
    patch_s0_bounded_v4_output_installation,
)


def _pdf(page_count: int) -> bytes:
    document = fitz.open()
    try:
        for index in range(page_count):
            page = document.new_page(width=300, height=400)
            page.insert_text((36, 72), f"page {index + 1}")
        return document.tobytes(garbage=4, deflate=True)
    finally:
        document.close()


def _fake_preprocessor(calls: list[int], *, changed: bool = True):
    def fake(
        pdf_bytes: bytes,
        *,
        expected_page_count: int | None = None,
        **_: object,
    ) -> GeometryPreprocessedPdf:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            count = int(document.page_count)
        finally:
            document.close()
        calls.append(count)
        assert expected_page_count == count
        checksum = hashlib.sha256(pdf_bytes).hexdigest()
        changed_page_count = count if changed else 0
        route = "normalized_scan" if changed else "quality_gate_original"
        selected = "background" if changed else "original"
        results = tuple(
            GeometryPageResult(
                page_index=index,
                applied_steps=(),
                deskew_angle_degrees=0.0,
                deskew_confidence=0.0,
                perspective_confidence=0.0,
                perspective_distortion=0.0,
                input_size=(300, 400),
                output_size=(300, 400),
                route=route,
            )
            for index in range(count)
        )
        with v4._DIAGNOSTIC_LOCK:
            v4._DIAGNOSTIC_MANIFESTS[checksum] = {
                "version": v4.GEOMETRY_PREPROCESSING_VERSION,
                "output_sha256": checksum,
                "output_size_bytes": len(pdf_bytes),
                "changed_page_count": changed_page_count,
                "pages": [
                    {
                        "page_number": index + 1,
                        "route": route,
                        "selected": selected,
                    }
                    for index in range(count)
                ],
            }
        return GeometryPreprocessedPdf(
            pdf_bytes=pdf_bytes,
            checksum_sha256=checksum,
            byte_size=len(pdf_bytes),
            page_count=count,
            changed_page_count=changed_page_count,
            pages=results,
            version=v4.GEOMETRY_PREPROCESSING_VERSION,
        )

    return fake


def test_bounded_v4_limits_page_execution_chunks_and_restores_global_results(
    monkeypatch,
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(bounded, "_BASE_PREPROCESSOR", _fake_preprocessor(calls))

    result = bounded.preprocess_pdf_geometry_opencv_bounded(
        _pdf(35),
        expected_page_count=35,
    )

    assert calls == [16, 16, 3]
    assert max(calls) == bounded.S0_V4_CHUNK_PAGE_LIMIT
    assert result.page_count == 35
    assert result.changed_page_count == 35
    assert [item.page_index for item in result.pages] == list(range(35))

    output = fitz.open(stream=result.pdf_bytes, filetype="pdf")
    try:
        assert output.page_count == 35
    finally:
        output.close()

    with v4._DIAGNOSTIC_LOCK:
        manifest = v4._DIAGNOSTIC_MANIFESTS.pop(result.checksum_sha256)
    assert manifest["s0_bounded_v4_output"]["chunk_page_limit"] == 16
    assert manifest["s0_bounded_v4_output"]["chunk_count"] == 3
    assert [page["page_number"] for page in manifest["pages"]] == list(
        range(1, 36)
    )


def test_bounded_v4_preserves_exact_source_bytes_when_all_chunks_are_noop(
    monkeypatch,
) -> None:
    calls: list[int] = []
    source_pdf = _pdf(35)
    monkeypatch.setattr(
        bounded,
        "_BASE_PREPROCESSOR",
        _fake_preprocessor(calls, changed=False),
    )

    result = bounded.preprocess_pdf_geometry_opencv_bounded(
        source_pdf,
        expected_page_count=35,
    )

    assert calls == [16, 16, 3]
    assert result.changed_page_count == 0
    assert result.pdf_bytes == source_pdf
    assert result.checksum_sha256 == hashlib.sha256(source_pdf).hexdigest()
    assert result.byte_size == len(source_pdf)

    with v4._DIAGNOSTIC_LOCK:
        manifest = v4._DIAGNOSTIC_MANIFESTS.pop(result.checksum_sha256)
    assert manifest["changed_page_count"] == 0
    assert manifest["output_sha256"] == hashlib.sha256(source_pdf).hexdigest()


def test_bounded_v4_keeps_small_documents_on_original_single_call(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(bounded, "_BASE_PREPROCESSOR", _fake_preprocessor(calls))

    result = bounded.preprocess_pdf_geometry_opencv_bounded(
        _pdf(8),
        expected_page_count=8,
    )

    assert calls == [8]
    assert result.page_count == 8


def test_bounded_v4_install_overlay_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "pdf_ingestion.py"
    path.write_text(
        "from app.processing.pdf_s0_bounded_memory_compat import "
        "install_s0_bounded_memory_compat\n\n"
        "install_s0_bounded_memory_compat()\n\n",
        encoding="utf-8",
    )

    patch_s0_bounded_v4_output_installation(path)
    once = path.read_text(encoding="utf-8")
    patch_s0_bounded_v4_output_installation(path)
    twice = path.read_text(encoding="utf-8")

    assert once == twice
    assert once.count("install_s0_bounded_v4_output_compat()") == 1
    assert once.index("install_s0_bounded_memory_compat()") < once.index(
        "install_s0_bounded_v4_output_compat()"
    )
