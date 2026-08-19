"""Bounded resumable upload transport for large bookshelf files.

Large browser uploads are split into small requests so a single long multipart
request does not have to survive the Hugging Face proxy/runtime path.
In-progress upload sessions use the Space's local ephemeral filesystem so
latency or stalls in a mounted Storage Bucket cannot block chunk requests.
Completed sessions are then handed to the existing canonical /api/v1/upload
acceptance function, which persists the retained source through the configured
StorageProvider.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.datastructures import Headers, UploadFile

from app.config import settings
from app.database import get_db
from app.routers.ocr import upload_file as _accept_upload_file
from app.schemas import UploadBookResponse
from app.storage.base import StorageProvider
from app.storage.dependencies import get_storage_provider
from app.upload_policy import BookSourceTooLarge, validate_book_source_size

router = APIRouter(prefix="/api/v1/upload-sessions", tags=["uploads"])
logger = logging.getLogger(__name__)

# Keep each browser -> HF request deliberately small. This transport size is
# independent of provider/OCR sharding and is only a protocol hard ceiling.
CHUNK_SIZE_BYTES = 2 * 1024 * 1024
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024
SESSION_TTL_SECONDS = 24 * 60 * 60
_UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{32}$")

# Upload-session chunks are transient transport state, not durable artifacts.
# Keep them on the Space-local filesystem rather than a mounted Storage Bucket.
# An override exists for tests or environments with a dedicated local spool.
UPLOAD_SPOOL_ROOT = Path(
    os.getenv(
        "ATLAS_UPLOAD_SPOOL_ROOT",
        str(Path(tempfile.gettempdir()) / "atlas-upload-sessions"),
    )
)


class CreateUploadSessionRequest(BaseModel):
    filename: str
    byte_size: int = Field(gt=0, le=MAX_UPLOAD_BYTES)
    content_type: str | None = None


class CreateUploadSessionResponse(BaseModel):
    upload_id: str
    chunk_size_bytes: int
    chunk_count: int
    byte_size: int


def _enforce_application_source_size(byte_size: int) -> None:
    try:
        validate_book_source_size(int(byte_size), settings)
    except BookSourceTooLarge as exc:
        raise HTTPException(
            status_code=413,
            detail="Book source exceeds the current application upload limit",
        ) from exc


def _root() -> Path:
    root = UPLOAD_SPOOL_ROOT.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _session_dir(upload_id: str) -> Path:
    if not _UPLOAD_ID_RE.fullmatch(upload_id or ""):
        raise HTTPException(status_code=404, detail="Upload session not found")
    root = _root()
    path = (root / upload_id).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Upload session not found") from exc
    return path


def _metadata_path(upload_id: str) -> Path:
    return _session_dir(upload_id) / "session.json"


def _load_metadata(upload_id: str) -> dict:
    path = _metadata_path(upload_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail="Upload session not found") from exc
    if not isinstance(payload, dict) or payload.get("upload_id") != upload_id:
        raise HTTPException(status_code=409, detail="Upload session metadata is invalid")
    return payload


def _validate_filename(filename: str) -> str:
    if not filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".txt"}:
        raise HTTPException(status_code=400, detail="Unsupported file type. Only PDF and TXT files are accepted.")
    return filename


def _normalized_content_type(filename: str, content_type: str | None) -> str:
    fallback = "application/pdf" if filename.lower().endswith(".pdf") else "text/plain"
    value = str(content_type or "").strip()
    if not value or value == "application/octet-stream":
        return fallback
    return value


def _chunk_path(session_dir: Path, chunk_index: int) -> Path:
    return session_dir / f"chunk-{chunk_index:06d}.bin"


def _expected_chunk_size(metadata: dict, chunk_index: int) -> int:
    chunk_count = int(metadata["chunk_count"])
    if chunk_index < 0 or chunk_index >= chunk_count:
        raise HTTPException(status_code=404, detail="Upload chunk not found")
    total = int(metadata["byte_size"])
    start = chunk_index * int(metadata["chunk_size_bytes"])
    return min(int(metadata["chunk_size_bytes"]), total - start)


def _cleanup_stale_sessions() -> None:
    cutoff = time.time() - SESSION_TTL_SECONDS
    root = _root()
    for child in root.iterdir():
        if not child.is_dir() or not _UPLOAD_ID_RE.fullmatch(child.name):
            continue
        try:
            if child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue


@router.post("", response_model=CreateUploadSessionResponse)
async def create_upload_session(request: CreateUploadSessionRequest) -> CreateUploadSessionResponse:
    filename = _validate_filename(request.filename)
    _enforce_application_source_size(request.byte_size)
    _cleanup_stale_sessions()
    upload_id = uuid.uuid4().hex
    session_dir = _session_dir(upload_id)
    session_dir.mkdir(parents=True, exist_ok=False)
    chunk_count = math.ceil(request.byte_size / CHUNK_SIZE_BYTES)
    payload = {
        "format_version": 1,
        "upload_id": upload_id,
        "filename": filename,
        "byte_size": int(request.byte_size),
        "content_type": _normalized_content_type(filename, request.content_type),
        "chunk_size_bytes": CHUNK_SIZE_BYTES,
        "chunk_count": chunk_count,
        "created_at_epoch": time.time(),
    }
    metadata = session_dir / "session.json"
    with metadata.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.flush()
    logger.info(
        "RESUMABLE_UPLOAD_SESSION_CREATED upload_id=%s byte_size=%s chunk_size_bytes=%s chunk_count=%s file_type=%s spool_root=%s",
        upload_id,
        request.byte_size,
        CHUNK_SIZE_BYTES,
        chunk_count,
        Path(filename).suffix.lower(),
        _root(),
    )
    return CreateUploadSessionResponse(
        upload_id=upload_id,
        chunk_size_bytes=CHUNK_SIZE_BYTES,
        chunk_count=chunk_count,
        byte_size=request.byte_size,
    )


def _store_upload_chunk(upload_id: str, chunk_index: int, body: bytes, *, transport: str) -> dict:
    metadata = _load_metadata(upload_id)
    session_dir = _session_dir(upload_id)
    expected_size = _expected_chunk_size(metadata, chunk_index)
    if len(body) != expected_size:
        logger.warning(
            "RESUMABLE_UPLOAD_CHUNK_SIZE_MISMATCH upload_id=%s chunk_index=%s expected_bytes=%s received_bytes=%s transport=%s",
            upload_id,
            chunk_index,
            expected_size,
            len(body),
            transport,
        )
        raise HTTPException(
            status_code=400,
            detail=f"Chunk byte size mismatch: expected {expected_size}, received {len(body)}",
        )
    digest = hashlib.sha256(body).hexdigest()
    final_path = _chunk_path(session_dir, chunk_index)
    if final_path.exists():
        existing = final_path.read_bytes()
        if len(existing) == len(body) and hashlib.sha256(existing).hexdigest() == digest:
            logger.info(
                "RESUMABLE_UPLOAD_CHUNK_IDEMPOTENT upload_id=%s chunk_index=%s received_bytes=%s transport=%s",
                upload_id,
                chunk_index,
                len(body),
                transport,
            )
            return {
                "upload_id": upload_id,
                "chunk_index": chunk_index,
                "received_bytes": len(body),
                "idempotent": True,
            }
        raise HTTPException(status_code=409, detail="Chunk already exists with different bytes")

    created = False
    try:
        with final_path.open("xb") as handle:
            created = True
            handle.write(body)
            handle.flush()
    except FileExistsError:
        existing = final_path.read_bytes()
        if len(existing) == len(body) and hashlib.sha256(existing).hexdigest() == digest:
            logger.info(
                "RESUMABLE_UPLOAD_CHUNK_IDEMPOTENT upload_id=%s chunk_index=%s received_bytes=%s transport=%s",
                upload_id,
                chunk_index,
                len(body),
                transport,
            )
            return {
                "upload_id": upload_id,
                "chunk_index": chunk_index,
                "received_bytes": len(body),
                "idempotent": True,
            }
        raise HTTPException(status_code=409, detail="Chunk already exists with different bytes")
    except Exception:
        if created:
            final_path.unlink(missing_ok=True)
        logger.exception(
            "RESUMABLE_UPLOAD_CHUNK_WRITE_FAILED upload_id=%s chunk_index=%s expected_bytes=%s transport=%s",
            upload_id,
            chunk_index,
            expected_size,
            transport,
        )
        raise

    logger.info(
        "RESUMABLE_UPLOAD_CHUNK_RECEIVED upload_id=%s chunk_index=%s chunk_count=%s received_bytes=%s transport=%s",
        upload_id,
        chunk_index,
        metadata["chunk_count"],
        len(body),
        transport,
    )
    return {
        "upload_id": upload_id,
        "chunk_index": chunk_index,
        "received_bytes": len(body),
        "sha256": digest,
    }


# Raw body endpoints are retained for compatibility with the first staging
# clients. The browser now prefers the multipart endpoint below because ordinary
# multipart uploads have already been proven reliable through the HF proxy.
@router.put("/{upload_id}/chunks/{chunk_index}")
@router.post("/{upload_id}/chunks/{chunk_index}")
async def receive_upload_chunk(upload_id: str, chunk_index: int, request: Request) -> dict:
    body = await request.body()
    return _store_upload_chunk(upload_id, chunk_index, body, transport="raw")


@router.post("/{upload_id}/chunks/{chunk_index}/multipart")
async def receive_upload_chunk_multipart(upload_id: str, chunk_index: int, request: Request) -> dict:
    started = time.monotonic()
    logger.info(
        "RESUMABLE_UPLOAD_MULTIPART_ENTERED upload_id=%s chunk_index=%s content_length=%s content_type=%s",
        upload_id,
        chunk_index,
        request.headers.get("content-length"),
        request.headers.get("content-type"),
    )
    try:
        form = await request.form()
    except Exception as exc:
        logger.warning(
            "RESUMABLE_UPLOAD_MULTIPART_PARSE_FAILED upload_id=%s chunk_index=%s elapsed_ms=%s",
            upload_id,
            chunk_index,
            int((time.monotonic() - started) * 1000),
            exc_info=True,
        )
        raise HTTPException(status_code=400, detail="Invalid multipart upload chunk") from exc

    logger.info(
        "RESUMABLE_UPLOAD_MULTIPART_PARSED upload_id=%s chunk_index=%s elapsed_ms=%s",
        upload_id,
        chunk_index,
        int((time.monotonic() - started) * 1000),
    )
    chunk = form.get("chunk")
    if not isinstance(chunk, UploadFile):
        logger.warning(
            "RESUMABLE_UPLOAD_MULTIPART_MISSING_CHUNK upload_id=%s chunk_index=%s elapsed_ms=%s",
            upload_id,
            chunk_index,
            int((time.monotonic() - started) * 1000),
        )
        raise HTTPException(status_code=400, detail="Multipart upload chunk is missing field 'chunk'")
    try:
        body = await chunk.read()
    finally:
        await chunk.close()
    logger.info(
        "RESUMABLE_UPLOAD_MULTIPART_READ upload_id=%s chunk_index=%s received_bytes=%s elapsed_ms=%s",
        upload_id,
        chunk_index,
        len(body),
        int((time.monotonic() - started) * 1000),
    )
    result = _store_upload_chunk(upload_id, chunk_index, body, transport="multipart")
    logger.info(
        "RESUMABLE_UPLOAD_MULTIPART_STORED upload_id=%s chunk_index=%s received_bytes=%s idempotent=%s elapsed_ms=%s",
        upload_id,
        chunk_index,
        len(body),
        bool(result.get("idempotent", False)),
        int((time.monotonic() - started) * 1000),
    )
    return result


@router.get("/{upload_id}")
async def get_upload_session(upload_id: str) -> dict:
    metadata = _load_metadata(upload_id)
    session_dir = _session_dir(upload_id)
    received = []
    received_bytes = 0
    for index in range(int(metadata["chunk_count"])):
        path = _chunk_path(session_dir, index)
        if path.is_file():
            received.append(index)
            received_bytes += path.stat().st_size
    return {
        "upload_id": upload_id,
        "byte_size": int(metadata["byte_size"]),
        "chunk_size_bytes": int(metadata["chunk_size_bytes"]),
        "chunk_count": int(metadata["chunk_count"]),
        "received_chunks": received,
        "received_bytes": received_bytes,
    }


@router.delete("/{upload_id}")
async def abort_upload_session(upload_id: str) -> dict:
    session_dir = _session_dir(upload_id)
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="Upload session not found")
    shutil.rmtree(session_dir)
    logger.info("RESUMABLE_UPLOAD_SESSION_ABORTED upload_id=%s", upload_id)
    return {"upload_id": upload_id, "aborted": True}


@router.post("/{upload_id}/complete", response_model=UploadBookResponse)
async def complete_upload_session(
    upload_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    storage: StorageProvider = Depends(get_storage_provider),
) -> UploadBookResponse:
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
        with assembled.open("rb") as source:
            synthetic = UploadFile(
                source,
                size=total,
                filename=str(metadata["filename"]),
                headers=Headers({"content-type": str(metadata["content_type"])}),
            )
            result = await _accept_upload_file(background_tasks, synthetic, db, storage)
        logger.info(
            "RESUMABLE_UPLOAD_ACCEPTED upload_id=%s book_id=%s status=%s",
            upload_id,
            getattr(result, "book_id", None),
            getattr(result, "status", None),
        )
        shutil.rmtree(session_dir, ignore_errors=True)
        return result
    finally:
        lock_path.unlink(missing_ok=True)
