"""Browser -> object storage direct PDF upload control plane."""
from __future__ import annotations

import logging
from pathlib import Path
import re
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Document, DocumentType, SourceFile
from app.processing.pdf_ingestion import new_pdf_ingestion_ids, process_pdf_document_background
from app.schemas import UploadBookResponse
from app.storage.direct_upload import (
    DirectUploadClaims,
    DirectUploadTokenError,
    sign_direct_upload_claims,
    verify_direct_upload_token,
)
from app.storage.errors import IntegrityMismatch, ObjectNotFound, StorageError
from app.storage.factory import create_object_storage_provider, object_storage_is_configured
from app.storage.models import StorageReference
from app.upload_policy import BookSourceTooLarge, validate_book_source_size

logger = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/api/v1/direct-upload-sessions", tags=["direct-upload"])
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class DirectUploadCreateRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(gt=0)
    checksum_sha256: str = Field(min_length=64, max_length=64)
    content_type: str | None = None


class DirectUploadCreateResponse(BaseModel):
    upload_id: str
    upload_mode: str
    upload_url: str
    upload_method: str
    upload_headers: dict[str, str]
    expires_in_seconds: int
    byte_size: int
    checksum_sha256: str
    completion_token: str


class DirectUploadCompleteRequest(BaseModel):
    completion_token: str = Field(min_length=20)


def _runtime():
    if not settings.direct_upload_enabled:
        raise HTTPException(status_code=503, detail="Direct object upload is not enabled")
    if not object_storage_is_configured(settings):
        raise HTTPException(status_code=503, detail="Direct object upload storage is not configured")
    secret = settings.direct_upload_signing_secret or ""
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="Direct object upload signing is not configured")
    provider = create_object_storage_provider(settings)
    if provider is None:  # defensive; configuration was checked above
        raise HTTPException(status_code=503, detail="Direct object upload storage is unavailable")
    return provider, secret


def _enforce_application_source_size(byte_size: int) -> None:
    try:
        validate_book_source_size(int(byte_size), settings)
    except BookSourceTooLarge as exc:
        raise HTTPException(
            status_code=413,
            detail="Book source exceeds the current application upload limit",
        ) from exc


def _validate_pdf_request(request: DirectUploadCreateRequest) -> tuple[str, str]:
    filename = request.filename.strip()
    if not filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Direct upload currently supports PDF files only")
    _enforce_application_source_size(request.byte_size)
    if request.byte_size > int(settings.direct_upload_single_put_max_bytes):
        raise HTTPException(
            status_code=413,
            detail="PDF exceeds the current direct single-PUT upload limit",
        )
    checksum = request.checksum_sha256.lower()
    if not _SHA256_RE.fullmatch(checksum):
        raise HTTPException(status_code=400, detail="Invalid SHA-256 checksum")
    return filename, checksum


def _claims_from_token(upload_id: str, token: str, secret: str) -> DirectUploadClaims:
    try:
        claims = verify_direct_upload_token(token, secret)
    except DirectUploadTokenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if claims.upload_id != upload_id:
        raise HTTPException(status_code=400, detail="Direct upload token does not match upload session")
    return claims


def _response_for_existing(document: Document, source: SourceFile, claims: DirectUploadClaims) -> UploadBookResponse:
    if (
        source.document_id != document.id
        or source.storage_reference != claims.storage_reference
        or int(source.byte_size or -1) != claims.byte_size
        or str(source.checksum_sha256 or "").lower() != claims.checksum_sha256
        or not source.retained
    ):
        raise HTTPException(status_code=409, detail="Existing direct upload metadata does not match session")
    return UploadBookResponse(
        book_id=document.id,
        book_title=document.title,
        file_type=document.file_type,
        status=document.status,
        processed_file_path=document.processed_file_path,
        original_file_path=document.original_file_path,
        error_message=document.error_message,
        message=f"File '{claims.filename}' direct upload is already committed.",
    )


@router.post("", response_model=DirectUploadCreateResponse)
def create_direct_upload_session(request: DirectUploadCreateRequest) -> DirectUploadCreateResponse:
    filename, checksum = _validate_pdf_request(request)
    provider, secret = _runtime()
    upload_id = uuid.uuid4().hex
    document_id = str(uuid.uuid4())
    source_file_id = str(uuid.uuid4())
    storage_reference = StorageReference.generate()
    ttl = max(60, min(int(settings.direct_upload_url_ttl_seconds), 604800))
    claims = DirectUploadClaims(
        upload_id=upload_id,
        document_id=document_id,
        source_file_id=source_file_id,
        storage_reference=str(storage_reference),
        filename=filename,
        byte_size=int(request.byte_size),
        checksum_sha256=checksum,
        content_type="application/pdf",
        expires_at=int(time.time()) + ttl,
    )
    try:
        upload_url, upload_headers = provider.generate_ingress_put_url(
            upload_id=upload_id,
            content_type=claims.content_type,
            checksum_sha256=checksum,
            expires_seconds=ttl,
        )
        completion_token = sign_direct_upload_claims(claims, secret)
    except (StorageError, DirectUploadTokenError) as exc:
        logger.exception("Direct upload session creation failed upload_id=%s", upload_id)
        raise HTTPException(status_code=503, detail="Direct object upload is temporarily unavailable") from exc
    logger.info(
        "DIRECT_UPLOAD_SESSION_CREATED upload_id=%s document_id=%s source_file_id=%s byte_size=%s mode=single_put",
        upload_id,
        document_id,
        source_file_id,
        request.byte_size,
    )
    return DirectUploadCreateResponse(
        upload_id=upload_id,
        upload_mode="single_put",
        upload_url=upload_url,
        upload_method="PUT",
        upload_headers=upload_headers,
        expires_in_seconds=ttl,
        byte_size=request.byte_size,
        checksum_sha256=checksum,
        completion_token=completion_token,
    )


@router.post("/{upload_id}/complete", response_model=UploadBookResponse)
def complete_direct_upload_session(
    upload_id: str,
    request: DirectUploadCompleteRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> UploadBookResponse:
    complete_started = time.perf_counter()
    provider, secret = _runtime()
    claims = _claims_from_token(upload_id, request.completion_token, secret)
    _enforce_application_source_size(claims.byte_size)
    reference = StorageReference.parse(claims.storage_reference)

    existing_document = db.get(Document, claims.document_id)
    if existing_document is not None:
        existing_source = db.get(SourceFile, claims.source_file_id)
        if existing_source is None:
            raise HTTPException(status_code=409, detail="Existing direct upload source metadata is incomplete")
        return _response_for_existing(existing_document, existing_source, claims)

    publish_started = time.perf_counter()
    try:
        # publish_ingress owns the authoritative integrity boundary and performs
        # its own ingress verification before destination lookup/copy. Calling
        # verify_ingress here as well adds a redundant remote HEAD request.
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

    book = Document(
        id=claims.document_id,
        document_type=DocumentType.BOOK,
        title=Path(claims.filename).stem,
        file_type="pdf",
        pages_count=None,
        status="processing",
    )
    source = SourceFile(
        id=claims.source_file_id,
        document=book,
        original_filename=claims.filename,
        file_type="pdf",
        mime_type=claims.content_type,
        byte_size=published.byte_size,
        checksum_sha256=published.checksum_sha256,
        storage_reference=str(published.reference),
        retained=1,
        is_primary=1,
    )
    db.add(book)
    db.add(source)
    db_commit_started = time.perf_counter()
    try:
        db.commit()
    except Exception:
        # Do not delete the published object here. A concurrent completion using
        # the same deterministic claims may have committed the same source, and
        # transient DB failures should remain retryable with the same token.
        db.rollback()
        logger.exception(
            "Direct upload database commit failed; preserving published object for retry upload_id=%s storage_reference=%s",
            claims.upload_id,
            reference,
        )
        raise
    db_commit_ms = (time.perf_counter() - db_commit_started) * 1000.0

    # Only now is the durable object business-owned. The ingress object remains
    # available until commit, which makes a failed DB transaction retryable.
    ingress_delete_started = time.perf_counter()
    try:
        provider.delete_ingress(claims.upload_id)
    except Exception:
        logger.exception("Direct upload ingress cleanup failed upload_id=%s", claims.upload_id)
    ingress_delete_ms = (time.perf_counter() - ingress_delete_started) * 1000.0

    ingestion_ids = new_pdf_ingestion_ids()
    background_tasks.add_task(
        process_pdf_document_background,
        book.id,
        source.id,
        ingestion_ids,
    )
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
        "DIRECT_UPLOAD_COMMITTED upload_id=%s document_id=%s source_file_id=%s storage_reference=%s byte_size=%s processing_attempt_id=%s",
        claims.upload_id,
        book.id,
        source.id,
        source.storage_reference,
        source.byte_size,
        ingestion_ids.processing_attempt_id,
    )
    return UploadBookResponse(
        book_id=book.id,
        book_title=book.title,
        file_type="pdf",
        status="processing",
        processed_file_path=None,
        original_file_path=None,
        message=(
            f"File '{claims.filename}' uploaded directly to object storage; "
            "PDF processing and Reader v2 canonicalization queued."
        ),
    )
