"""Private provider-only source transport endpoint."""
from __future__ import annotations

import hashlib
import secrets
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.processing.transport.dependencies import StorageProviderFactory, get_storage_provider_factory, get_transport_grant_service
from app.processing.transport.errors import TransportGrantError
from app.processing.transport.service import InMemoryTransportGrantService
from app.storage.errors import InvalidReference, ObjectNotFound, ProviderUnavailable, ReadFailure, StorageError

router = APIRouter(prefix="/internal/source-transport", tags=["internal-source-transport"], include_in_schema=False)

_COLLAPSED_BODY = {"detail": "Not found"}
_PDF_MEDIA_TYPE = "application/pdf"


def _collapsed_not_found() -> NoReturn:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_COLLAPSED_BODY["detail"])


def _transport_failure(status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR) -> NoReturn:
    raise HTTPException(status_code=status_code, detail="Source transport failed")


def _normalized_media_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


@router.head("/{token}")
def head_source_transport(token: str) -> Response:
    """Reject HEAD so credential probes cannot consume retrieval counts."""
    raise HTTPException(status_code=status.HTTP_405_METHOD_NOT_ALLOWED, detail="Method Not Allowed")


@router.get("/{token}", response_class=Response)
def get_source_transport(
    token: str,
    grants: InMemoryTransportGrantService = Depends(get_transport_grant_service),
    storage_factory: StorageProviderFactory = Depends(get_storage_provider_factory),
) -> Response:
    """Return exact retained PDF bytes for an authorized opaque transport token."""
    try:
        grant = grants.authorize(token)
    except TransportGrantError:
        _collapsed_not_found()

    if _normalized_media_type(grant.media_type) != _PDF_MEDIA_TYPE:
        _transport_failure()

    try:
        storage = storage_factory()
    except ProviderUnavailable:
        _transport_failure(status.HTTP_503_SERVICE_UNAVAILABLE)
    except StorageError:
        _transport_failure()
    except Exception:
        _transport_failure()

    try:
        payload = storage.get(grant.storage_reference)
    except (ObjectNotFound, InvalidReference):
        _collapsed_not_found()
    except (ProviderUnavailable, ReadFailure):
        _transport_failure(status.HTTP_503_SERVICE_UNAVAILABLE)
    except StorageError:
        _transport_failure()
    except Exception:
        _transport_failure()

    if not isinstance(payload, bytes):
        _transport_failure()
    if len(payload) != grant.source_byte_size:
        _transport_failure()
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if not secrets.compare_digest(actual_sha256, grant.source_sha256.lower()):
        _transport_failure()

    try:
        grants.authorize(token)
    except TransportGrantError:
        _collapsed_not_found()

    response = Response(
        content=payload,
        media_type=_PDF_MEDIA_TYPE,
        headers={
            "Cache-Control": "private, no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(len(payload)),
        },
    )

    try:
        grants.record_retrieval(token)
    except TransportGrantError:
        _collapsed_not_found()

    return response
