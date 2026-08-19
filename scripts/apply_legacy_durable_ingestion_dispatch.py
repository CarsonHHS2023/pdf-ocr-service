"""Install durable ingestion dispatch into the legacy multipart upload route."""
from __future__ import annotations

from pathlib import Path


OCR_PATH = Path("app/routers/ocr.py")

_OLD_PROCESS_IMPORTS = '''from app.processing.pdf_ingestion import new_pdf_ingestion_ids, process_pdf_document_background
from app.processing.txt.ingestion import new_txt_ingestion_ids, process_txt_document_background
'''
_NEW_PROCESS_IMPORTS = '''from app.processing.ingestion_acceptance import (
    commit_retained_ingestion,
    legacy_acceptance_key,
)
from app.processing.ingestion_dispatch import new_dispatch_payload, run_ingestion_dispatch
'''

_UPLOAD_START = '''@router.post("/upload", response_model=UploadBookResponse)
async def upload_file(
'''
_NEXT_ROUTE = '''@router.post("/ocr/{task_id}", response_model=OCRProcessResponse)
'''

_UPLOAD_REPLACEMENT = r'''@router.post("/upload", response_model=UploadBookResponse)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    storage: StorageProvider = Depends(get_storage_provider),
) -> UploadBookResponse:
    """Upload a PDF or TXT file and durably queue canonical processing."""
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename is required")

    filename = file.filename
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    ext = Path(filename).suffix.lower()
    if ext not in {".pdf", ".txt"}:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Only PDF and TXT files are accepted.",
        )

    if isinstance(file.size, int) and not isinstance(file.size, bool):
        _enforce_book_source_size(file.size)

    file_type = "pdf" if ext == ".pdf" else "txt"
    book_title = Path(filename).stem
    book_id = str(uuid.uuid4())
    source_file_id = str(uuid.uuid4())
    acceptance_key = legacy_acceptance_key()
    dispatch_payload = new_dispatch_payload(file_type)

    content = await file.read()
    _enforce_book_source_size(len(content))
    _upload_diagnostic(
        "PDF_UPLOAD_ACCEPTED" if file_type == "pdf" else "TXT_UPLOAD_ACCEPTED",
        document_id=book_id,
        filename=filename,
        byte_size=len(content),
    )

    try:
        storage_reference, retained_size, retained_checksum = _retain_source_bytes(storage, content)
    except StorageError as exc:
        logger.exception("Source retention failed document_id=%s", book_id)
        raise HTTPException(status_code=500, detail=f"Failed to retain uploaded source: {exc}") from exc

    if file_type == "txt":
        try:
            accepted = commit_retained_ingestion(
                db,
                acceptance_key=acceptance_key,
                filename=filename,
                file_type="txt",
                mime_type=file.content_type or "text/plain",
                byte_size=retained_size,
                checksum_sha256=retained_checksum,
                storage_reference=storage_reference,
                document_id=book_id,
                source_file_id=source_file_id,
                dispatch_payload=dispatch_payload,
            )
        except Exception:
            _cleanup_retained_source(storage, storage_reference)
            raise

        _upload_diagnostic(
            "TXT_SOURCE_RETAINED",
            document_id=accepted.document_id,
            source_file_id=accepted.source_file_id,
            processing_run_ref=dispatch_payload.txt_processing_run_ref,
            storage_reference=storage_reference,
            byte_size=retained_size,
        )
        background_tasks.add_task(run_ingestion_dispatch, accepted.dispatch_id)
        _upload_diagnostic(
            "TXT_BACKGROUND_TASK_QUEUED",
            document_id=accepted.document_id,
            source_file_id=accepted.source_file_id,
            processing_run_ref=dispatch_payload.txt_processing_run_ref,
            dispatch_id=accepted.dispatch_id,
        )
        return accepted.response

    _upload_diagnostic(
        "PDF_SOURCE_RETAINED",
        document_id=book_id,
        storage_reference=storage_reference,
        byte_size=retained_size,
    )

    try:
        import fitz  # type: ignore[import]

        pdf = fitz.open(stream=content, filetype="pdf")
        try:
            page_count = pdf.page_count
        finally:
            pdf.close()
        if page_count <= 0:
            raise ValueError("Uploaded PDF contains no pages")
    except Exception:
        logger.exception("Uploaded PDF could not be opened document_id=%s", book_id)
        _cleanup_retained_source(storage, storage_reference)
        return UploadBookResponse(
            book_id=book_id,
            book_title=book_title,
            file_type=file_type,
            status="failed",
            error_message="Uploaded PDF could not be opened",
            message=f"Failed to accept PDF '{filename}'.",
        )

    try:
        accepted = commit_retained_ingestion(
            db,
            acceptance_key=acceptance_key,
            filename=filename,
            file_type="pdf",
            mime_type="application/pdf",
            byte_size=retained_size,
            checksum_sha256=retained_checksum,
            storage_reference=storage_reference,
            page_count=page_count,
            document_id=book_id,
            source_file_id=source_file_id,
            dispatch_payload=dispatch_payload,
        )
    except Exception:
        _cleanup_retained_source(storage, storage_reference)
        logger.exception(
            "PDF durable acceptance failed document_id=%s source_file_id=%s",
            book_id,
            source_file_id,
        )
        raise

    _upload_diagnostic(
        "PDF_DATABASE_COMMITTED",
        document_id=accepted.document_id,
        source_file_id=accepted.source_file_id,
        processing_attempt_id=dispatch_payload.processing_attempt_id,
        page_count=page_count,
        dispatch_id=accepted.dispatch_id,
    )
    background_tasks.add_task(run_ingestion_dispatch, accepted.dispatch_id)
    _upload_diagnostic(
        "PDF_BACKGROUND_TASK_QUEUED",
        document_id=accepted.document_id,
        source_file_id=accepted.source_file_id,
        processing_attempt_id=dispatch_payload.processing_attempt_id,
        provider_job_id=dispatch_payload.provider_job_id,
        dispatch_id=accepted.dispatch_id,
    )

    return accepted.response.model_copy(
        update={
            "message": (
                f"File '{filename}' uploaded; {page_count} page(s) queued for Modal "
                "processing and Reader v2 canonicalization."
            )
        }
    )


'''


def patch_legacy_durable_dispatch(path: Path = OCR_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    if "dispatch_id=accepted.dispatch_id" in source and "legacy_acceptance_key" in source:
        return
    if source.count(_OLD_PROCESS_IMPORTS) != 1:
        raise RuntimeError("Could not find unique legacy processor import anchor")
    if source.count(_UPLOAD_START) != 1:
        raise RuntimeError("Could not find unique legacy upload start anchor")
    if source.count(_NEXT_ROUTE) != 1:
        raise RuntimeError("Could not find unique legacy upload end anchor")

    source = source.replace(_OLD_PROCESS_IMPORTS, _NEW_PROCESS_IMPORTS, 1)
    start = source.index(_UPLOAD_START)
    end = source.index(_NEXT_ROUTE, start)
    source = source[:start] + _UPLOAD_REPLACEMENT + source[end:]
    path.write_text(source, encoding="utf-8")


def main() -> None:
    patch_legacy_durable_dispatch()


if __name__ == "__main__":
    main()
