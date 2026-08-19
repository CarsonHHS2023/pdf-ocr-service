"""Install durable ingestion acceptance/dispatch into staging upload paths.

The overlay is deliberately fail-closed and is expanded path-by-path. Resumable,
direct, legacy acceptance, and the single durable recovery supervisor are installed
from the same authoritative staging entrypoint so tested-artifact assembly cannot
drift between upload transports and recovery behavior.
"""
from __future__ import annotations

from pathlib import Path


RESUMABLE_PATH = Path("app/routers/resumable_upload.py")

_OLD_ACCEPT_IMPORT = "from app.routers.ocr import upload_file as _accept_upload_file\n"
_NEW_ACCEPT_IMPORT = '''from app.processing.ingestion_acceptance import (
    find_accepted_ingestion,
    resumable_acceptance_key,
    retain_and_commit_ingestion,
    stable_entity_id,
)
from app.processing.ingestion_dispatch import run_ingestion_dispatch
'''

_COMPLETE_START = '''@router.post("/{upload_id}/complete", response_model=UploadBookResponse)
async def complete_upload_session(
'''

_COMPLETE_REPLACEMENT = '''@router.post("/{upload_id}/complete", response_model=UploadBookResponse)
async def complete_upload_session(
    upload_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    storage: StorageProvider = Depends(get_storage_provider),
) -> UploadBookResponse:
    acceptance_key = resumable_acceptance_key(upload_id)

    # Durable acceptance is checked before ephemeral spool state. A process may
    # have committed the business acceptance and then died before deleting the
    # local session directory (or the restart may have removed that directory).
    # In either case retry must return the same business object and re-kick only
    # the same durable dispatch.
    existing = find_accepted_ingestion(db, acceptance_key)
    if existing is not None:
        background_tasks.add_task(run_ingestion_dispatch, existing.dispatch_id)
        session_dir = _session_dir(upload_id)
        shutil.rmtree(session_dir, ignore_errors=True)
        logger.info(
            "RESUMABLE_UPLOAD_COMPLETE_IDEMPOTENT upload_id=%s book_id=%s dispatch_id=%s status=%s",
            upload_id,
            existing.document_id,
            existing.dispatch_id,
            existing.response.status,
        )
        return existing.response

    metadata = _load_metadata(upload_id)
    _enforce_application_source_size(int(metadata["byte_size"]))
    session_dir = _session_dir(upload_id)
    lock_path = session_dir / ".complete.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(lock_fd)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="Upload session is already completing") from exc

    logger.info(
        "RESUMABLE_UPLOAD_COMPLETE_STARTED upload_id=%s byte_size=%s chunk_count=%s",
        upload_id,
        metadata["byte_size"],
        metadata["chunk_count"],
    )
    assembled = session_dir / "assembled.upload"
    try:
        total = 0
        with assembled.open("wb") as output:
            for index in range(int(metadata["chunk_count"])):
                chunk = _chunk_path(session_dir, index)
                if not chunk.is_file():
                    raise HTTPException(status_code=409, detail=f"Upload is incomplete; missing chunk {index}")
                expected = _expected_chunk_size(metadata, index)
                if chunk.stat().st_size != expected:
                    raise HTTPException(status_code=409, detail=f"Upload chunk {index} has an invalid byte size")
                with chunk.open("rb") as source:
                    while True:
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        output.write(block)
                        total += len(block)
            output.flush()
        if total != int(metadata["byte_size"]):
            raise HTTPException(status_code=409, detail="Assembled upload byte size mismatch")

        logger.info(
            "RESUMABLE_UPLOAD_ASSEMBLED upload_id=%s assembled_bytes=%s",
            upload_id,
            total,
        )
        content = assembled.read_bytes()
        filename = str(metadata["filename"])
        file_type = "pdf" if Path(filename).suffix.lower() == ".pdf" else "txt"
        page_count = None
        if file_type == "pdf":
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
                logger.exception(
                    "Resumable PDF could not be opened upload_id=%s",
                    upload_id,
                )
                shutil.rmtree(session_dir, ignore_errors=True)
                return UploadBookResponse(
                    book_id=stable_entity_id(acceptance_key, "document"),
                    book_title=Path(filename).stem,
                    file_type="pdf",
                    status="failed",
                    error_message="Uploaded PDF could not be opened",
                    message=f"Failed to accept PDF '{filename}'.",
                )

        accepted = retain_and_commit_ingestion(
            db,
            storage,
            acceptance_key=acceptance_key,
            filename=filename,
            file_type=file_type,
            mime_type=str(metadata["content_type"]),
            content=content,
            page_count=page_count,
            # A concurrent completion may already own the deterministic object.
            # Preserving it also makes a transient DB failure retryable.
            cleanup_on_db_failure=False,
        )
        background_tasks.add_task(run_ingestion_dispatch, accepted.dispatch_id)
        logger.info(
            "RESUMABLE_UPLOAD_ACCEPTED upload_id=%s book_id=%s dispatch_id=%s status=%s created=%s",
            upload_id,
            accepted.document_id,
            accepted.dispatch_id,
            accepted.response.status,
            accepted.created,
        )
        shutil.rmtree(session_dir, ignore_errors=True)
        return accepted.response
    finally:
        lock_path.unlink(missing_ok=True)
'''


def patch_resumable_durable_dispatch(path: Path = RESUMABLE_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    if "RESUMABLE_UPLOAD_COMPLETE_IDEMPOTENT" in source:
        return
    if source.count(_OLD_ACCEPT_IMPORT) != 1:
        raise RuntimeError("Could not find unique resumable canonical-accept import anchor")
    if source.count(_COMPLETE_START) != 1:
        raise RuntimeError("Could not find unique resumable complete anchor")
    source = source.replace(_OLD_ACCEPT_IMPORT, _NEW_ACCEPT_IMPORT, 1)
    start = source.index(_COMPLETE_START)
    source = source[:start] + _COMPLETE_REPLACEMENT
    path.write_text(source, encoding="utf-8")


def main() -> None:
    patch_resumable_durable_dispatch()
    # Keep the per-path transforms independent for unit testing, but install
    # them together from the one authoritative Staging assembly entrypoint.
    from apply_direct_durable_ingestion_dispatch import patch_direct_durable_dispatch
    from apply_ingestion_dispatch_supervisor import patch_ingestion_dispatch_supervisor
    from apply_legacy_durable_ingestion_dispatch import patch_legacy_durable_dispatch

    patch_direct_durable_dispatch()
    patch_legacy_durable_dispatch()
    patch_ingestion_dispatch_supervisor()


if __name__ == "__main__":
    main()
