"""S0 compatibility layer for bounded ordinary-page V4 output construction.

The V4 quality algorithm remains unchanged.  Large ordinary-page PDFs are split
into small execution chunks, each chunk runs through the existing V4 function,
and only already-processed PDF chunks are merged afterward.  This prevents the
300-DPI page loop from retaining one ever-growing raster output document.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import gc
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Callable, Iterator

import fitz  # type: ignore[import]

from app.processing.pdf_geometry_preprocessing import GeometryPreprocessedPdf


S0_V4_CHUNK_PAGE_LIMIT = 16
_INSTALLED = False
_BASE_PREPROCESSOR: Callable[..., GeometryPreprocessedPdf] | None = None


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _temporary_root() -> str | None:
    root = Path("/data/output")
    return str(root) if root.exists() and root.is_dir() else None


def _active_s0_state() -> tuple[Any | None, dict[str, object] | None]:
    try:
        from app.processing import s0_pdf_resource_heartbeat as heartbeat
    except Exception:
        return None, None
    state = heartbeat._active_state()
    return heartbeat, state if isinstance(state, dict) else None


def _current_page_offset(heartbeat: Any) -> int:
    state = heartbeat._active_state()
    if not isinstance(state, dict):
        return 0
    lock = state.get("lock")
    if not hasattr(lock, "__enter__"):
        return int(state.get("s0_v4_page_offset") or 0)
    with lock:
        return int(state.get("s0_v4_page_offset") or 0)


def _set_page_offset(offset: int) -> None:
    heartbeat, state = _active_s0_state()
    if heartbeat is None or state is None:
        return
    lock = state.get("lock")
    if not hasattr(lock, "__enter__"):
        return
    with lock:
        state["s0_v4_page_offset"] = max(0, int(offset))


@contextmanager
def _page_offset(offset: int) -> Iterator[None]:
    heartbeat, state = _active_s0_state()
    previous = 0
    if heartbeat is not None and state is not None:
        previous = _current_page_offset(heartbeat)
    _set_page_offset(offset)
    try:
        yield
    finally:
        _set_page_offset(previous)


def _install_heartbeat_page_offset_compat() -> None:
    """Translate chunk-local V4 page numbers back to provider-global numbers."""
    try:
        from app.processing import s0_pdf_resource_heartbeat as heartbeat
    except Exception:
        return

    current_stage = heartbeat._set_opencv_stage
    if not getattr(current_stage, "__atlas_s0_chunk_offset__", False):
        def offset_stage(
            stage: str,
            *,
            page_number: int | None = None,
            durable_first_page: bool = True,
        ) -> None:
            if page_number is not None and page_number > 0:
                page_number = int(page_number) + _current_page_offset(heartbeat)
            current_stage(
                stage,
                page_number=page_number,
                durable_first_page=durable_first_page,
            )

        setattr(offset_stage, "__atlas_s0_chunk_offset__", True)
        heartbeat._set_opencv_stage = offset_stage

    current_handle = heartbeat._handle_page_decision
    if not getattr(current_handle, "__atlas_s0_chunk_offset__", False):
        def offset_handle(decision: dict[str, object]) -> None:
            offset = _current_page_offset(heartbeat)
            if offset <= 0:
                current_handle(decision)
                return
            adjusted = dict(decision)
            raw_page = adjusted.get("page_number")
            if isinstance(raw_page, int) and raw_page > 0:
                adjusted["page_number"] = raw_page + offset
            current_handle(adjusted)

        setattr(offset_handle, "__atlas_s0_chunk_offset__", True)
        heartbeat._handle_page_decision = offset_handle


def _record_chunk_checkpoint(
    *,
    page_start: int,
    page_end: int,
    page_count: int,
    output_size_bytes: int,
) -> None:
    try:
        from app.processing import s0_pdf_resource_heartbeat as heartbeat

        state = heartbeat._active_state()
        if not isinstance(state, dict):
            return
        heartbeat.record_pdf_processing_heartbeat(
            processing_run_id=str(state["processing_run_id"]),
            document_id=str(state["document_id"]),
            phase="opencv_chunk_completed",
            page_number=int(page_end),
            page_count=int(page_count),
            chunk_page_start=int(page_start),
            chunk_page_end=int(page_end),
            chunk_page_count=int(page_end - page_start + 1),
            chunk_output_size_bytes=int(output_size_bytes),
            current_stage="ordinary_v4_preprocessing:chunk_completed",
            last_completed_page=int(page_end),
        )
    except Exception:
        return


def _serialize_source_chunk(
    source: fitz.Document,
    *,
    start_index: int,
    end_index: int,
) -> bytes:
    chunk = fitz.open()
    try:
        if source.metadata:
            chunk.set_metadata(source.metadata)
        chunk.insert_pdf(source, from_page=start_index, to_page=end_index)
        return chunk.tobytes(garbage=4, deflate=True)
    finally:
        chunk.close()


def _take_chunk_manifest(v4: Any, checksum: str) -> dict[str, object] | None:
    with v4._DIAGNOSTIC_LOCK:
        value = v4._DIAGNOSTIC_MANIFESTS.pop(checksum, None)
    return _json_clone(value) if isinstance(value, dict) else None


def _register_final_manifest(
    v4: Any,
    *,
    checksum: str,
    manifest: dict[str, object],
) -> None:
    with v4._DIAGNOSTIC_LOCK:
        v4._DIAGNOSTIC_MANIFESTS[checksum] = _json_clone(manifest)


def _merge_processed_chunks(
    chunk_paths: list[Path],
    *,
    metadata: dict[str, str],
    expected_page_count: int,
    output_path: Path,
) -> None:
    merged = fitz.open()
    try:
        if metadata:
            merged.set_metadata(metadata)
        for chunk_path in chunk_paths:
            chunk = fitz.open(str(chunk_path))
            try:
                merged.insert_pdf(chunk)
            finally:
                chunk.close()
        if merged.page_count != expected_page_count:
            raise RuntimeError("bounded V4 merge changed page count")
        merged.save(str(output_path), garbage=4, deflate=True)
    finally:
        merged.close()


def preprocess_pdf_geometry_opencv_bounded(
    pdf_bytes: bytes,
    *,
    expected_page_count: int | None = None,
    **kwargs: object,
) -> GeometryPreprocessedPdf:
    """Run unchanged V4 in page-bounded chunks and merge processed PDF objects."""
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("pdf_bytes must contain a PDF")
    base = _BASE_PREPROCESSOR
    if base is None:
        raise RuntimeError("bounded V4 output compatibility is not installed")

    from app.processing import pdf_opencv_quality_pipeline as v4

    source = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_count = int(source.page_count)
        if page_count <= 0:
            raise ValueError("PDF must contain at least one page")
        if expected_page_count is not None and page_count != int(expected_page_count):
            raise ValueError("PDF page count does not match upload metadata")
        if page_count <= S0_V4_CHUNK_PAGE_LIMIT:
            return base(
                pdf_bytes,
                expected_page_count=expected_page_count,
                **kwargs,
            )

        metadata = dict(source.metadata or {})
        all_results = []
        all_manifest_pages: list[dict[str, object]] = []
        changed_page_count = 0
        chunk_evidence: list[dict[str, object]] = []

        with tempfile.TemporaryDirectory(
            prefix="atlas-v4-chunks-",
            dir=_temporary_root(),
        ) as temp_dir:
            root = Path(temp_dir)
            chunk_paths: list[Path] = []

            for chunk_index, start_index in enumerate(
                range(0, page_count, S0_V4_CHUNK_PAGE_LIMIT)
            ):
                end_index = min(
                    page_count - 1,
                    start_index + S0_V4_CHUNK_PAGE_LIMIT - 1,
                )
                local_count = end_index - start_index + 1
                chunk_source_bytes = _serialize_source_chunk(
                    source,
                    start_index=start_index,
                    end_index=end_index,
                )
                with _page_offset(start_index):
                    processed = base(
                        chunk_source_bytes,
                        expected_page_count=local_count,
                        **kwargs,
                    )

                chunk_path = root / f"processed-{chunk_index:04d}.pdf"
                chunk_path.write_bytes(processed.pdf_bytes)
                chunk_paths.append(chunk_path)
                changed_page_count += int(processed.changed_page_count)
                all_results.extend(
                    replace(result, page_index=start_index + int(result.page_index))
                    for result in processed.pages
                )

                chunk_manifest = _take_chunk_manifest(
                    v4,
                    processed.checksum_sha256,
                )
                if chunk_manifest is not None:
                    pages = chunk_manifest.get("pages")
                    if isinstance(pages, list):
                        for item in pages:
                            if not isinstance(item, dict):
                                continue
                            cloned = _json_clone(item)
                            local_page = cloned.get("page_number")
                            if isinstance(local_page, int) and local_page > 0:
                                cloned["page_number"] = start_index + local_page
                            all_manifest_pages.append(cloned)

                chunk_evidence.append(
                    {
                        "chunk_index": chunk_index,
                        "page_start": start_index + 1,
                        "page_end": end_index + 1,
                        "page_count": local_count,
                        "output_size_bytes": int(processed.byte_size),
                    }
                )
                _record_chunk_checkpoint(
                    page_start=start_index + 1,
                    page_end=end_index + 1,
                    page_count=page_count,
                    output_size_bytes=int(processed.byte_size),
                )

                processed = None
                chunk_source_bytes = b""
                gc.collect()

            if len(all_results) != page_count:
                raise RuntimeError("bounded V4 page result count changed")

            if changed_page_count == 0:
                # Preserve the base V4 exact-byte no-op contract. Re-serializing
                # an unchanged document would create a different checksum even
                # though no page was selected by a quality gate.
                processed_bytes = pdf_bytes
            else:
                merged_path = root / "processed-merged.pdf"
                _merge_processed_chunks(
                    chunk_paths,
                    metadata=metadata,
                    expected_page_count=page_count,
                    output_path=merged_path,
                )
                processed_bytes = merged_path.read_bytes()

        checksum = hashlib.sha256(processed_bytes).hexdigest()
        final_manifest = {
            "version": v4.GEOMETRY_PREPROCESSING_VERSION,
            "source_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
            "output_sha256": checksum,
            "source_size_bytes": len(pdf_bytes),
            "output_size_bytes": len(processed_bytes),
            "changed_page_count": changed_page_count,
            "pages": all_manifest_pages,
            "paddle_vl_skipped": True,
            "s0_bounded_v4_output": {
                "chunk_page_limit": S0_V4_CHUNK_PAGE_LIMIT,
                "chunk_count": len(chunk_evidence),
                "chunks": chunk_evidence,
            },
        }
        _register_final_manifest(
            v4,
            checksum=checksum,
            manifest=final_manifest,
        )
        return GeometryPreprocessedPdf(
            pdf_bytes=processed_bytes,
            checksum_sha256=checksum,
            byte_size=len(processed_bytes),
            page_count=page_count,
            changed_page_count=changed_page_count,
            pages=tuple(all_results),
            version=v4.GEOMETRY_PREPROCESSING_VERSION,
        )
    finally:
        _set_page_offset(0)
        source.close()


def install_s0_bounded_v4_output_compat() -> None:
    """Replace only the V4 whole-document coordinator, never its page algorithm."""
    global _BASE_PREPROCESSOR, _INSTALLED
    if _INSTALLED:
        return

    from app.processing import pdf_opencv_quality_pipeline as v4

    current = v4.preprocess_pdf_geometry_opencv
    if current is preprocess_pdf_geometry_opencv_bounded:
        _INSTALLED = True
        _install_heartbeat_page_offset_compat()
        return
    _BASE_PREPROCESSOR = current
    v4.preprocess_pdf_geometry_opencv = preprocess_pdf_geometry_opencv_bounded
    _install_heartbeat_page_offset_compat()
    _INSTALLED = True


__all__ = [
    "S0_V4_CHUNK_PAGE_LIMIT",
    "install_s0_bounded_v4_output_compat",
    "preprocess_pdf_geometry_opencv_bounded",
]
