"""Install durable ingestion acceptance/dispatch into the staging direct-upload path.

The transform is intentionally fail-closed and keeps rollout compatibility with
pre-dispatch direct uploads that already committed Document/SourceFile rows.
"""
from __future__ import annotations

from pathlib import Path


DIRECT_PATH = Path("app/routers/direct_upload.py")

_OLD_PROCESS_IMPORT = (
    "from app.processing.pdf_ingestion import new_pdf_ingestion_ids, "
    "process_pdf_document_background\n"
)
_NEW_PROCESS_IMPORT = '''from app.processing.ingestion_acceptance import (
    IngestionAcceptanceError,
    commit_retained_ingestion,
    direct_acceptance_key,
    find_accepted_ingestion,
)
from app.processing.ingestion_dispatch import run_ingestion_dispatch
'''

_COMPLETE_START = '''@router.post("/{upload_id}/complete", response_model=UploadBookResponse)
def complete_direct_upload_session(
'''

_COMPLETE_REPLACEMENT = '''@router.post("/{upload_id}/complete", response_model=UploadBookResponse)
def complete_direct_upload_session(
    upload_id: str,
    request: DirectUploadCompleteRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> UploadBookResponse:
    complete_started = time.perf_counter()

    # Token verification is deliberately separated from object-storage runtime.
    # An already-committed durable acceptance must remain readable/re-kickable
    # when S3 configuration or the remote gateway is temporarily unavailable.
    secret = settings.direct_upload_signing_secret or ""
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="Direct object upload signing is not configured")
    claims = _claims_from_token(upload_id, request.completion_token, secret)
    acceptance_key = direct_acceptance_key(claims.upload_id)

    try:
        existing = find_accepted_ingestion(
            db,
            acceptance_key,
            expected_document_id=claims.document_id,
            expected_source_file_id=claims.source_file_id,
            expected_storage_reference=claims.storage_reference,
            expected_byte_size=claims.byte_size,
            expected_checksum_sha256=claims.checksum_sha256,
        )
    except IngestionAcceptanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if existing is not None:
        background_tasks.add_task(run_ingestion_dispatch, existing.dispatch_id)
        existing_document = db.get(Document, existing.document_id)
        existing_source = db.get(SourceFile, existing.source_file_id)
        if existing_document is None or existing_source is None:
            raise HTTPException(status_code=409, detail="Existing direct upload metadata is incomplete")
        logger.info(
            "DIRECT_UPLOAD_COMPLETE_IDEMPOTENT upload_id=%s document_id=%s dispatch_id=%s status=%s",
            claims.upload_id,
            existing.document_id,
            existing.dispatch_id,
            existing.response.status,
        )
        return _response_for_existing(existing_document, existing_source, claims)

    # Rollout compatibility: direct uploads committed before durable dispatch
    # existed have deterministic Document/Source ids from their signed claims but
    # no acceptance row. Preserve the prior idempotent response instead of
    # attempting to republish an ingress object that was already deleted. Do not
    # blindly re-run OCR because the pre-rollout worker may still be active.
    legacy_document = db.get(Document, claims.document_id)
    if legacy_document is not None:
        legacy_source = db.get(SourceFile, claims.source_file_id)
        if legacy_source is None:
            raise HTTPException(status_code=409, detail="Existing direct upload source metadata is incomplete")
        logger.warning(
            "DIRECT_UPLOAD_LEGACY_ACCEPTANCE_WITHOUT_DISPATCH upload_id=%s document_id=%s status=%s",
            claims.upload_id,
            legacy_document.id,
            legacy_document.status,
        )
        return _response_for_existing(legacy_document, legacy_source, claims)

    # Only a genuinely new completion needs the object-storage runtime.
    provider, _runtime_secret = _runtime()
    reference = StorageReference.parse(claims.storage_reference)
    _enforce_direct_completion_source_size(provider, claims)

    publish_started = time.perf_counter()
    try:
        published = provider.publish_ingress(
            upload_id=claims.upload_id,
            reference=reference,
            expected_size=claims.byte_size,
            expected_sha256=claims.checksum_sha256,
            expected_content_type=claims.content_type,
        )
    except ObjectNotFound as exc:
        raise HTTPException(status_code=409, detail="Direct upload object has not completed") from exc
    except IntegrityMismatch as exc:
        raise HTTPException(status_code=409, detail="Direct upload object failed integrity validation") from exc
    except StorageError as exc:
        logger.exception("Direct upload publish failed upload_id=%s", claims.upload_id)
        raise HTTPException(status_code=503, detail="Direct object upload could not be committed") from exc
    publish_ms = (time.perf_counter() - publish_started) * 1000.0

    db_commit_started = time.perf_counter()
    try:
        accepted = commit_retained_ingestion(
            db,
            acceptance_key=acceptance_key,
            filename=claims.filename,
            file_type="pdf",
            mime_type=claims.content_type,
            byte_size=published.byte_size,
            checksum_sha256=published.checksum_sha256,
            storage_reference=str(published.reference),
            page_count=None,
            document_id=claims.document_id,
            source_file_id=claims.source_file_id,
        )
    except IngestionAcceptanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        # The published object is deterministic for the signed claims. Preserve
        # it on DB failure so the same completion token remains retryable and a
        # concurrent winner is never deleted by the loser.
        logger.exception(
            "Direct upload durable acceptance failed; preserving published object for retry upload_id=%s storage_reference=%s",
            claims.upload_id,
            reference,
        )
        raise
    db_commit_ms = (time.perf_counter() - db_commit_started) * 1000.0

    # Only after the durable Document+Source+Dispatch transaction succeeds is
    # the temporary ingress object no longer required for retry.
    ingress_delete_started = time.perf_counter()
    try:
        provider.delete_ingress(claims.upload_id)
    except Exception:
        logger.exception("Direct upload ingress cleanup failed upload_id=%s", claims.upload_id)
    ingress_delete_ms = (time.perf_counter() - ingress_delete_started) * 1000.0

    # BackgroundTasks is a latency optimization only. The queued dispatch row is
    # already durable, so a process crash here cannot lose the accepted work.
    background_tasks.add_task(run_ingestion_dispatch, accepted.dispatch_id)
    total_ms = (time.perf_counter() - complete_started) * 1000.0
    logger.info(
        "DIRECT_UPLOAD_COMPLETE_TIMING upload_id=%s byte_size=%s publish_ms=%.1f db_commit_ms=%.1f ingress_delete_ms=%.1f total_ms=%.1f",
        claims.upload_id,
        claims.byte_size,
        publish_ms,
        db_commit_ms,
        ingress_delete_ms,
        total_ms,
    )
    logger.info(
        "DIRECT_UPLOAD_COMMITTED upload_id=%s document_id=%s source_file_id=%s storage_reference=%s byte_size=%s dispatch_id=%s created=%s",
        claims.upload_id,
        accepted.document_id,
        accepted.source_file_id,
        published.reference,
        published.byte_size,
        accepted.dispatch_id,
        accepted.created,
    )
    return accepted.response.model_copy(
        update={
            "message": (
                f"File '{claims.filename}' uploaded directly to object storage; "
                "PDF processing and Reader v2 canonicalization queued."
            )
        }
    )
'''


def patch_direct_durable_dispatch(path: Path = DIRECT_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    if "DIRECT_UPLOAD_COMPLETE_IDEMPOTENT" in source:
        return
    if source.count(_OLD_PROCESS_IMPORT) != 1:
        raise RuntimeError("Could not find unique direct-upload processor import anchor")
    if source.count(_COMPLETE_START) != 1:
        raise RuntimeError("Could not find unique direct-upload complete anchor")
    source = source.replace(_OLD_PROCESS_IMPORT, _NEW_PROCESS_IMPORT, 1)
    start = source.index(_COMPLETE_START)
    source = source[:start] + _COMPLETE_REPLACEMENT
    path.write_text(source, encoding="utf-8")


def main() -> None:
    patch_direct_durable_dispatch()


if __name__ == "__main__":
    main()
