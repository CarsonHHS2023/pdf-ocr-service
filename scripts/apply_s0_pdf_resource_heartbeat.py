"""Install S0 PDF resource heartbeat instrumentation into deployed ingestion."""
from __future__ import annotations

from pathlib import Path


PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")

_INSTALL = '''import pymupdf

from app.processing.s0_pdf_resource_heartbeat import (
    install_opencv_page_heartbeat_probe,
    pdf_resource_observation_context,
    record_pdf_processing_heartbeat,
    start_pdf_processing_run,
    sync_pdf_processing_run_terminal,
)
from app.processing.s0_provider_wait_lease import await_with_pdf_processing_lease

install_opencv_page_heartbeat_probe()

'''
_LOGGER_ANCHOR = 'logger = logging.getLogger("uvicorn.error")\n'

_PREP_ORIGINAL = '''    source_pdf = _read_verified_source_pdf(storage, descriptor)
    return prepare_geometry_provider_input(
        storage=storage,
        source_pdf_bytes=source_pdf,
        original_filename=descriptor.filename,
        processing_attempt_id=processing_attempt_id,
        expected_page_count=expected_page_count,
    )
'''
_PREP_INSTRUMENTED = '''    record_pdf_processing_heartbeat(
        processing_run_id=processing_attempt_id,
        document_id=descriptor.document_id,
        phase="source_read_start",
        page_count=expected_page_count,
    )
    source_pdf = _read_verified_source_pdf(storage, descriptor)
    resolved_page_count = expected_page_count
    if resolved_page_count is None:
        with pymupdf.open(stream=source_pdf, filetype="pdf") as source_document:
            resolved_page_count = int(source_document.page_count)
        if resolved_page_count <= 0:
            raise RuntimeError("Retained PDF source page count is invalid")
        record_pdf_processing_heartbeat(
            processing_run_id=processing_attempt_id,
            document_id=descriptor.document_id,
            phase="source_page_count_discovered",
            page_count=resolved_page_count,
            source_size_bytes=len(source_pdf),
        )
    record_pdf_processing_heartbeat(
        processing_run_id=processing_attempt_id,
        document_id=descriptor.document_id,
        phase="source_loaded",
        page_count=resolved_page_count,
        source_size_bytes=len(source_pdf),
    )
    record_pdf_processing_heartbeat(
        processing_run_id=processing_attempt_id,
        document_id=descriptor.document_id,
        phase="opencv_preprocessing_start",
        page_count=resolved_page_count,
    )
    with pdf_resource_observation_context(
        processing_run_id=processing_attempt_id,
        document_id=descriptor.document_id,
        page_count=resolved_page_count,
    ):
        result = prepare_geometry_provider_input(
            storage=storage,
            source_pdf_bytes=source_pdf,
            original_filename=descriptor.filename,
            processing_attempt_id=processing_attempt_id,
            expected_page_count=resolved_page_count,
        )
    record_pdf_processing_heartbeat(
        processing_run_id=processing_attempt_id,
        document_id=descriptor.document_id,
        phase="provider_input_ready",
        page_number=resolved_page_count,
        page_count=resolved_page_count,
        provider_input_size_bytes=result.byte_size,
        changed_page_count=result.preprocessing.changed_page_count,
    )
    return result
'''

_RUN_START_ANCHOR = '''    finally:
        db.close()

    storage = get_storage_provider()
'''
_RUN_START_INSTRUMENTED = '''    finally:
        db.close()

    start_pdf_processing_run(
        processing_run_id=ids.processing_attempt_id,
        document_id=document_id,
        source_file_id=source_file_id,
    )
    record_pdf_processing_heartbeat(
        processing_run_id=ids.processing_attempt_id,
        document_id=document_id,
        phase="background_started",
        page_count=expected_page_count,
        source_size_bytes=descriptor.byte_size,
    )

    storage = get_storage_provider()
'''

_PROVIDER_START_ANCHOR = '''        _diagnostic(
            "PDF_PROVIDER_REQUEST_STARTED",
'''
_PROVIDER_START_INSTRUMENTED = '''        record_pdf_processing_heartbeat(
            processing_run_id=ids.processing_attempt_id,
            document_id=document_id,
            phase="provider_request_start",
            page_number=(
                expected_page_count
                if expected_page_count is not None
                else geometry_input.preprocessing.page_count
            ),
            page_count=(
                expected_page_count
                if expected_page_count is not None
                else geometry_input.preprocessing.page_count
            ),
            provider_input_size_bytes=geometry_input.byte_size,
        )
        _diagnostic(
            "PDF_PROVIDER_REQUEST_STARTED",
'''

_PROVIDER_AWAIT_ANCHOR = '''        provider_submission_started = True
        outcome = await service.process(request)
'''
_PROVIDER_AWAIT_INSTRUMENTED = '''        provider_submission_started = True
        outcome = await await_with_pdf_processing_lease(
            service.process(request),
            processing_run_id=ids.processing_attempt_id,
            document_id=document_id,
            page_count=geometry_input.preprocessing.page_count,
            provider_job_id=ids.provider_job_id,
        )
'''

_PROVIDER_TERMINAL_ANCHOR = '''        _diagnostic(
            "PDF_PROVIDER_TERMINAL",
'''
_PROVIDER_TERMINAL_INSTRUMENTED = '''        record_pdf_processing_heartbeat(
            processing_run_id=ids.processing_attempt_id,
            document_id=document_id,
            phase="provider_terminal",
            page_number=(
                expected_page_count
                if expected_page_count is not None
                else geometry_input.preprocessing.page_count
            ),
            page_count=(
                expected_page_count
                if expected_page_count is not None
                else geometry_input.preprocessing.page_count
            ),
            provider_status=(
                outcome.provider_terminal_status.value
                if outcome.provider_terminal_status is not None
                else None
            ),
        )
        _diagnostic(
            "PDF_PROVIDER_TERMINAL",
'''

_FINAL_SYNC_ANCHOR = '''        if client is not None:
            try:
                await client.aclose()
            except Exception:
                logger.exception("Failed to close PaddleVL client document_id=%s", document_id)
'''
_FINAL_SYNC_INSTRUMENTED = '''        if client is not None:
            try:
                await client.aclose()
            except Exception:
                logger.exception("Failed to close PaddleVL client document_id=%s", document_id)
        sync_pdf_processing_run_terminal(
            processing_run_id=ids.processing_attempt_id,
            document_id=document_id,
        )
'''


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} anchor")
    return source.replace(old, new, 1)


def patch_s0_pdf_resource_heartbeat(path: Path = PDF_INGESTION_PATH) -> None:
    """Install fail-open resource checkpoints without changing processing policy."""
    source = path.read_text(encoding="utf-8")
    if _INSTALL not in source:
        if source.count(_LOGGER_ANCHOR) != 1:
            raise RuntimeError("Could not find unique pdf_ingestion logger anchor")
        source = source.replace(_LOGGER_ANCHOR, _INSTALL + _LOGGER_ANCHOR, 1)

    source = _replace_once(source, _PREP_ORIGINAL, _PREP_INSTRUMENTED, "preprocessing")
    source = _replace_once(source, _RUN_START_ANCHOR, _RUN_START_INSTRUMENTED, "run start")
    source = _replace_once(
        source,
        _PROVIDER_START_ANCHOR,
        _PROVIDER_START_INSTRUMENTED,
        "provider start",
    )
    source = _replace_once(
        source,
        _PROVIDER_AWAIT_ANCHOR,
        _PROVIDER_AWAIT_INSTRUMENTED,
        "provider wait lease",
    )
    source = _replace_once(
        source,
        _PROVIDER_TERMINAL_ANCHOR,
        _PROVIDER_TERMINAL_INSTRUMENTED,
        "provider terminal",
    )
    source = _replace_once(source, _FINAL_SYNC_ANCHOR, _FINAL_SYNC_INSTRUMENTED, "final sync")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    patch_s0_pdf_resource_heartbeat()


if __name__ == "__main__":
    main()
