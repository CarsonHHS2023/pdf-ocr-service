"""Stateless signed claims for browser-direct source uploads."""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import time
from typing import Any


class DirectUploadTokenError(ValueError):
    """Signed direct-upload claims are missing, invalid, or expired."""


@dataclass(frozen=True, slots=True)
class DirectUploadClaims:
    upload_id: str
    document_id: str
    source_file_id: str
    storage_reference: str
    filename: str
    byte_size: int
    checksum_sha256: str
    content_type: str
    expires_at: int
    version: int = 1


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    # Tokens are emitted as canonical, unpadded base64url. Python's permissive
    # urlsafe_b64decode accepts alternate final characters whose unused padding
    # bits differ but decode to the same bytes. Reject those aliases so one
    # signed token has exactly one accepted textual representation.
    if not isinstance(value, str) or not value or "=" in value:
        raise DirectUploadTokenError("Invalid direct upload token encoding")
    try:
        encoded = value.encode("ascii")
        padding = b"=" * (-len(encoded) % 4)
        decoded = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
    except Exception as exc:
        raise DirectUploadTokenError("Invalid direct upload token encoding") from exc
    if _b64encode(decoded) != value:
        raise DirectUploadTokenError("Invalid direct upload token encoding")
    return decoded


def sign_direct_upload_claims(claims: DirectUploadClaims, secret: str) -> str:
    key = str(secret or "").encode("utf-8")
    if len(key) < 32:
        raise DirectUploadTokenError("Direct upload signing secret must be at least 32 characters")
    payload = json.dumps(
        asdict(claims),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded_payload = _b64encode(payload)
    signature = hmac.new(key, encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_payload}.{_b64encode(signature)}"


def verify_direct_upload_token(
    token: str,
    secret: str,
    *,
    now: int | None = None,
) -> DirectUploadClaims:
    try:
        encoded_payload, encoded_signature = str(token).split(".", 1)
    except ValueError as exc:
        raise DirectUploadTokenError("Invalid direct upload token") from exc
    key = str(secret or "").encode("utf-8")
    if len(key) < 32:
        raise DirectUploadTokenError("Direct upload signing secret is unavailable")
    expected = hmac.new(key, encoded_payload.encode("ascii"), hashlib.sha256).digest()
    supplied = _b64decode(encoded_signature)
    if not hmac.compare_digest(expected, supplied):
        raise DirectUploadTokenError("Invalid direct upload token signature")
    try:
        raw: Any = json.loads(_b64decode(encoded_payload).decode("utf-8"))
        claims = DirectUploadClaims(
            upload_id=str(raw["upload_id"]),
            document_id=str(raw["document_id"]),
            source_file_id=str(raw["source_file_id"]),
            storage_reference=str(raw["storage_reference"]),
            filename=str(raw["filename"]),
            byte_size=int(raw["byte_size"]),
            checksum_sha256=str(raw["checksum_sha256"]).lower(),
            content_type=str(raw["content_type"]),
            expires_at=int(raw["expires_at"]),
            version=int(raw.get("version", 0)),
        )
    except Exception as exc:
        raise DirectUploadTokenError("Invalid direct upload token payload") from exc
    if claims.version != 1:
        raise DirectUploadTokenError("Unsupported direct upload token version")
    current = int(time.time()) if now is None else int(now)
    if claims.expires_at < current:
        raise DirectUploadTokenError("Direct upload token expired")
    return claims
