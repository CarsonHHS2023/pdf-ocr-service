"""Disposable internal operator entry for one processing integration invocation."""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Extra, Field, root_validator, validator

from app.config import settings
from app.processing.integration import (
    EndToEndProcessingIntegrationService,
    IntegrationError,
    ProcessingIntegrationOutcome,
    ProcessingIntegrationRequest,
    RetainedSourceDescriptor,
)
from app.processing.orchestration import ProcessingOrchestrator
from app.processing.paddle_vl.client import PaddleVLClient, PaddleVLClientConfig
from app.processing.transport.dependencies import get_storage_provider_factory, get_transport_grant_service
from app.storage.dependencies import get_storage_provider
from app.storage.errors import (
    IntegrityMismatch,
    ObjectAlreadyExists,
    ProviderUnavailable,
    ReadFailure,
    StorageError,
    WriteFailure,
)
from app.storage.models import StorageReference
from app.processing.raw_result import is_valid_sha256

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/operator", tags=["internal-processing-operator"], include_in_schema=False)
_COLLAPSED_NOT_FOUND = {"detail": "Not found"}
_ALLOWED_PROFILE = "standard"
_MIN_OPERATOR_TOKEN_CHARS = 32
_TEST_FIXTURE_SHA256 = "fb084e43d06e039118d2a72a40353eebcec09abdbe732cf30917608723126420"
_TEST_FIXTURE_BYTE_SIZE = 605
_TEST_FIXTURE_MEDIA_TYPE = "application/pdf"

_TEST_FIXTURE_LABEL = "test-only-source-transport"
_TEST_FIXTURE_RESOURCE = (
    Path(__file__).resolve().parents[1] / "resources" / "source_transport" / "test-only-source-transport.pdf"
)
_SMOKE_STORAGE_REFERENCE = StorageReference.parse(
    "src_"
    + hashlib.sha256(f"source-transport-smoke/{_TEST_FIXTURE_SHA256}.pdf".encode("ascii")).hexdigest()[:32]
)


class SmokeFixturePreparationResponse(BaseModel):
    status: str
    fixture_id: str
    storage_reference: str
    sha256: str
    byte_size: int
    media_type: str
    disposition: str
    message: str


def _load_verified_smoke_fixture(resource_path: Path | None = None) -> bytes:
    resource_path = resource_path or _TEST_FIXTURE_RESOURCE
    try:
        if not resource_path.exists() or not resource_path.is_file():
            raise RuntimeError("fixture unavailable")
        data = resource_path.read_bytes()
    except Exception as exc:
        raise RuntimeError("fixture unavailable") from exc
    guessed_media_type, _ = mimetypes.guess_type(resource_path.name)
    actual_sha = hashlib.sha256(data).hexdigest()
    if (
        len(data) != _TEST_FIXTURE_BYTE_SIZE
        or actual_sha != _TEST_FIXTURE_SHA256
        or guessed_media_type != _TEST_FIXTURE_MEDIA_TYPE
        or not data.startswith(b"%PDF-")
    ):
        raise RuntimeError("fixture integrity mismatch")
    return data


def _verify_retained_smoke_bytes(data: bytes) -> None:
    if not isinstance(data, bytes):
        raise IntegrityMismatch("retained fixture bytes failed verification")
    if len(data) != _TEST_FIXTURE_BYTE_SIZE or hashlib.sha256(data).hexdigest() != _TEST_FIXTURE_SHA256:
        raise IntegrityMismatch("retained fixture bytes failed verification")


def redact_operator_id(value: str | None) -> str | None:
    """Return an audit-safe identifier preserving a known prefix and final four characters."""
    if value is None:
        return None
    text = str(value)
    suffix = text[-4:] if len(text) >= 4 else "****"
    if "_" in text:
        prefix = text.split("_", 1)[0]
        if prefix:
            return f"{prefix}_...{suffix}"
    return f"...{suffix}" if len(text) >= 4 else "...****"


class RetainedSourceInput(BaseModel):
    document_id: str
    source_file_id: str
    storage_reference: str
    retained: bool
    sha256: str
    byte_size: int
    media_type: str
    etag: str | None = None
    filename: str | None = None

    class Config:
        extra = Extra.forbid

    @validator("document_id", "source_file_id", "storage_reference", "sha256", "media_type")
    def _required(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("field is required")
        return value

    @validator("retained")
    def _retained(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("source must already be retained")
        return value

    @validator("byte_size")
    def _byte_size(cls, value: int) -> int:
        if isinstance(value, bool) or value <= 0:
            raise ValueError("byte_size must be positive")
        return value

    @validator("storage_reference")
    def _storage_reference(cls, value: str) -> str:
        try:
            StorageReference.parse(value)
        except Exception as exc:
            raise ValueError("storage_reference is invalid") from exc
        return value

    @validator("sha256")
    def _sha256(cls, value: str) -> str:
        if not is_valid_sha256(value):
            raise ValueError("sha256 must be a SHA-256 hex digest")
        return value.lower()

    @validator("media_type")
    def _pdf_only(cls, value: str) -> str:
        if value != "application/pdf":
            raise ValueError("only application/pdf is supported")
        return value


class ProcessingOperatorRequest(BaseModel):
    processing_attempt_id: str
    correlation_id: str | None = None
    retained_source: RetainedSourceInput
    provider_name: str = "paddle-vl"
    provider_job_id: str
    provider_request_id: str | None = None
    result_profile: str = _ALLOWED_PROFILE
    expected_page_count: int | None = None
    provider_options: dict[str, Any] | None = None
    test_fixture_only: bool = True

    class Config:
        extra = Extra.forbid

    @validator("processing_attempt_id", "provider_name", "provider_job_id", "result_profile")
    def _required(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("field is required")
        return value

    @validator("result_profile")
    def _standard_only(cls, value: str) -> str:
        if value != _ALLOWED_PROFILE:
            raise ValueError("only the standard result profile is enabled")
        return value

    @validator("provider_options")
    def _no_options(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value not in (None, {}):
            raise ValueError("provider options are not accepted by this operator entry")
        return value

    @validator("test_fixture_only")
    def _fixture_ack(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("test_fixture_only must be true")
        return value

    @validator("expected_page_count")
    def _expected_pages(cls, value: int | None) -> int | None:
        if value is not None and (isinstance(value, bool) or value < 0):
            raise ValueError("expected_page_count must be non-negative")
        return value

    @root_validator(skip_on_failure=True)
    def _fixture_only_matches_committed_evidence(cls, values: dict[str, Any]) -> dict[str, Any]:
        source = values.get("retained_source")
        if values.get("test_fixture_only") is True and source is not None:
            if (
                source.sha256 != _TEST_FIXTURE_SHA256
                or source.byte_size != _TEST_FIXTURE_BYTE_SIZE
                or source.media_type != _TEST_FIXTURE_MEDIA_TYPE
            ):
                raise ValueError("test_fixture_only requests must match committed fixture checksum, size, and media type")
        return values


class ProcessingOperatorResponse(BaseModel):
    status: str
    processing_attempt_id: str
    provider_name: str
    provider_job_id: str | None
    provider_request_id: str | None = None
    provider_terminal_status: str | None = None
    integration_terminal_phase: str | None = None
    raw_result_storage_reference: str | None = None
    raw_result_sha256: str | None = None
    raw_result_byte_size: int | None = None
    poll_count: int | None = None
    elapsed_seconds: float | None = None
    grant_id: str | None = None
    grant_final_state: str | None = None
    revocation_succeeded: bool | None = None
    error_category: str | None = None
    error_phase: str | None = None
    retry_guidance: str | None = None
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class OperatorIntegrationDependency:
    service: EndToEndProcessingIntegrationService
    owned_client: PaddleVLClient | None = None

    async def close(self) -> None:
        if self.owned_client is not None:
            await self.owned_client.aclose()


def _collapsed_not_found() -> NoReturn:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_COLLAPSED_NOT_FOUND["detail"])


def _configured_operator_token() -> str | None:
    return settings.processing_operator_token


def require_operator_auth(authorization: str | None = Header(default=None)) -> None:
    if not settings.processing_operator_enabled:
        _collapsed_not_found()
    expected = _configured_operator_token()
    if not expected or len(expected) < _MIN_OPERATOR_TOKEN_CHARS:
        _collapsed_not_found()
    if settings.paddle_vl_api_bearer_token and secrets.compare_digest(expected, settings.paddle_vl_api_bearer_token):
        _collapsed_not_found()
    if authorization is None or not authorization.startswith("Bearer "):
        _collapsed_not_found()
    supplied = authorization.removeprefix("Bearer ")
    if not supplied or not secrets.compare_digest(supplied, expected):
        _collapsed_not_found()


OperatorIntegrationFactory = Callable[[], Awaitable[OperatorIntegrationDependency]]


async def create_operator_integration_dependency() -> OperatorIntegrationDependency:
    client: PaddleVLClient | None = None
    try:
        config = PaddleVLClientConfig(
            base_url=settings.paddle_vl_api_base_url or "",
            bearer_token=settings.paddle_vl_api_bearer_token or "",
            timeout_seconds=settings.paddle_vl_api_timeout_seconds,
            default_result_profile=settings.paddle_vl_api_default_result_profile,
        )
        client = PaddleVLClient(config)
        orchestrator = ProcessingOrchestrator(provider=client, storage=get_storage_provider())
        service = EndToEndProcessingIntegrationService(
            grant_service=get_transport_grant_service(),
            orchestrator=orchestrator,
            public_origin=settings.public_source_transport_origin,
        )
        return OperatorIntegrationDependency(service=service, owned_client=client)
    except Exception:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                logger.exception("processing operator provider client cleanup failed during composition")
        raise


def get_operator_integration_dependency() -> OperatorIntegrationFactory:
    return create_operator_integration_dependency


def _integration_request(body: ProcessingOperatorRequest) -> ProcessingIntegrationRequest:
    source = body.retained_source
    return ProcessingIntegrationRequest(
        processing_attempt_id=body.processing_attempt_id,
        correlation_id=body.correlation_id,
        retained_source=RetainedSourceDescriptor(
            document_id=source.document_id,
            source_file_id=source.source_file_id,
            storage_reference=StorageReference.parse(source.storage_reference),
            retained=source.retained,
            sha256=source.sha256,
            byte_size=source.byte_size,
            media_type=source.media_type,
            etag=source.etag,
            filename=source.filename,
        ),
        provider_name=body.provider_name,
        provider_job_id=body.provider_job_id,
        provider_request_id=body.provider_request_id,
        result_profile=body.result_profile,
    )


def _response_from_outcome(request: ProcessingIntegrationRequest, outcome: ProcessingIntegrationOutcome) -> ProcessingOperatorResponse:
    err = outcome.error
    return ProcessingOperatorResponse(
        status="succeeded" if err is None else "failed",
        processing_attempt_id=request.processing_attempt_id,
        provider_name=outcome.provider_name,
        provider_job_id=redact_operator_id(outcome.provider_job_id),
        provider_request_id=redact_operator_id(outcome.provider_request_id),
        provider_terminal_status=outcome.provider_terminal_status.value if outcome.provider_terminal_status else None,
        integration_terminal_phase=outcome.integration_terminal_phase.value,
        raw_result_storage_reference=str(outcome.raw_result_storage_reference) if outcome.raw_result_storage_reference else None,
        raw_result_sha256=outcome.raw_result_checksum_sha256,
        raw_result_byte_size=outcome.raw_result_size_bytes,
        poll_count=outcome.poll_count,
        elapsed_seconds=round(outcome.elapsed_seconds, 3),
        grant_id=redact_operator_id(outcome.grant_id),
        grant_final_state=outcome.grant_final_state.value if outcome.grant_final_state else None,
        revocation_succeeded=outcome.revocation_succeeded,
        error_category=err.category.value if err else None,
        error_phase=err.orchestration_error.phase.value if err and err.orchestration_error else None,
        retry_guidance=_retry_guidance(err),
        warnings=list(outcome.warnings),
    )


def _response_from_error(request: ProcessingIntegrationRequest, exc: IntegrationError) -> ProcessingOperatorResponse:
    return ProcessingOperatorResponse(
        status="failed",
        processing_attempt_id=request.processing_attempt_id,
        provider_name=request.provider_name,
        provider_job_id=redact_operator_id(request.provider_job_id),
        provider_request_id=redact_operator_id(request.provider_request_id),
        integration_terminal_phase=exc.orchestration_error.phase.value if exc.orchestration_error else None,
        grant_id=redact_operator_id(exc.grant_id),
        grant_final_state=exc.grant_final_state.value if exc.grant_final_state else None,
        revocation_succeeded=exc.revocation_succeeded,
        error_category=exc.category.value,
        error_phase=exc.orchestration_error.phase.value if exc.orchestration_error else None,
        retry_guidance=_retry_guidance(exc),
        warnings=list(exc.warnings),
    )


def _retry_guidance(err: IntegrationError | None) -> str | None:
    if err is None:
        return None
    if err.category.value in {"timeout", "submission_uncertain"}:
        return "Do not resubmit automatically; reconcile the provider job and active grant before any new attempt."
    return "Do not retry automatically from this operator response."



@router.post("/prepare-smoke-fixture/", include_in_schema=False)
async def prepare_smoke_fixture_trailing_slash() -> None:
    _collapsed_not_found()


@router.post("/prepare-smoke-fixture", response_model=SmokeFixturePreparationResponse)
async def prepare_smoke_fixture(
    request: Request,
    _: None = Depends(require_operator_auth),
    storage_provider_factory = Depends(get_storage_provider_factory),
) -> SmokeFixturePreparationResponse:
    try:
        if request.query_params:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Smoke fixture preparation does not accept query parameters",
            )
        if await request.body():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Smoke fixture preparation does not accept a request body",
            )
        data = _load_verified_smoke_fixture()
        storage = storage_provider_factory()
        put_result = storage.put(
            data,
            _SMOKE_STORAGE_REFERENCE,
            expected_size=_TEST_FIXTURE_BYTE_SIZE,
            expected_sha256=_TEST_FIXTURE_SHA256,
        )
        retained = storage.get(put_result.reference)
        _verify_retained_smoke_bytes(retained)
        return SmokeFixturePreparationResponse(
            status="ready",
            fixture_id=_TEST_FIXTURE_LABEL,
            storage_reference=str(put_result.reference),
            sha256=put_result.checksum_sha256,
            byte_size=put_result.byte_size,
            media_type=_TEST_FIXTURE_MEDIA_TYPE,
            disposition="retained_or_already_present",
            message="Smoke fixture retained and verified for controlled operator use.",
        )
    except HTTPException:
        raise
    except ObjectAlreadyExists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Smoke fixture preparation conflict"
        ) from None
    except (ProviderUnavailable, WriteFailure, ReadFailure):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Smoke fixture preparation unavailable"
        ) from None
    except (IntegrityMismatch, StorageError, RuntimeError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Smoke fixture preparation failed"
        ) from None
    except Exception:
        logger.exception("smoke fixture preparation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Smoke fixture preparation failed"
        ) from None

@router.post("/process-once/", include_in_schema=False)
async def process_once_trailing_slash() -> None:
    _collapsed_not_found()

@router.post("/process-once", response_model=ProcessingOperatorResponse)
async def process_once(
    request: Request,
    _: None = Depends(require_operator_auth),
    dependency_factory: OperatorIntegrationFactory = Depends(get_operator_integration_dependency),
) -> ProcessingOperatorResponse:
    integration_request: ProcessingIntegrationRequest | None = None
    try:
        try:
            body = ProcessingOperatorRequest.parse_obj(await request.json())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid processing operator request") from None
        integration_request = _integration_request(body)
        dependency = await dependency_factory()
        outcome = await dependency.service.process(integration_request)
        return _response_from_outcome(integration_request, outcome)
    except HTTPException:
        raise
    except IntegrationError as exc:
        if integration_request is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.safe_message) from None
        return _response_from_error(integration_request, exc)
    except Exception:
        logger.exception("processing operator invocation failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Processing operator failed") from None
    finally:
        if "dependency" in locals():
            try:
                await dependency.close()
            except Exception:
                logger.exception("processing operator dependency cleanup failed")
