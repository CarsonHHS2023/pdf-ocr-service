from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
import hashlib
import hmac

import httpx

from app.processing.errors import ProviderClientError, ProviderErrorCategory, ProviderErrorDetail
from app.processing.models import (
    ArtifactMetadata,
    ProviderArtifact,
    ProviderJobStatus,
    ProviderResult,
    ProviderSubmission,
)
from app.processing.paddle_vl.mapping import map_progress, map_status
from app.processing.paddle_vl.models import PaddleVLJobRequest

VALID_RESULT_PROFILES = {"summary", "standard", "full"}


def _configuration_error(message: str) -> ProviderClientError:
    return ProviderClientError(
        ProviderErrorDetail(
            ProviderErrorCategory.CONFIGURATION,
            message,
        )
    )


def _normalized_provider_base_url(value: str) -> str:
    if not isinstance(value, str):
        raise _configuration_error("paddle-vl-api base URL must be configured with HTTPS")

    # Environment-variable editors can preserve an otherwise invisible trailing
    # CR/LF or surrounding spaces. Strip only the outer deployment noise; URL
    # syntax itself remains fail-closed below.
    normalized = value.strip()
    if not normalized:
        raise _configuration_error("paddle-vl-api base URL must be configured with HTTPS")

    try:
        parsed = httpx.URL(normalized)
    except httpx.InvalidURL as exc:
        raise _configuration_error("paddle-vl-api base URL is invalid") from exc

    if parsed.scheme != "https" or not parsed.host:
        raise _configuration_error("paddle-vl-api base URL must be configured with HTTPS")
    return normalized


@dataclass(frozen=True)
class PaddleVLClientConfig:
    base_url: str
    bearer_token: str
    timeout_seconds: float = 30.0
    default_result_profile: str = "standard"

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _normalized_provider_base_url(self.base_url))
        if not self.bearer_token:
            raise ProviderClientError(
                ProviderErrorDetail(
                    ProviderErrorCategory.CONFIGURATION,
                    "paddle-vl-api bearer token must be configured",
                )
            )
        if self.timeout_seconds <= 0:
            raise ProviderClientError(
                ProviderErrorDetail(
                    ProviderErrorCategory.CONFIGURATION,
                    "paddle-vl-api timeout must be positive",
                )
            )
        _validate_result_profile(self.default_result_profile)

    def __repr__(self) -> str:
        return (
            "PaddleVLClientConfig("
            f"base_url={self.base_url!r}, bearer_token=<redacted>, "
            f"timeout_seconds={self.timeout_seconds!r}, "
            f"default_result_profile={self.default_result_profile!r})"
        )


class PaddleVLClient:
    def __init__(
        self,
        config: PaddleVLClientConfig,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._owns_client = client is None
        try:
            self._client = client or httpx.AsyncClient(
                base_url=_normalize_base_url(config.base_url),
                timeout=config.timeout_seconds,
                follow_redirects=False,
                transport=transport,
            )
        except httpx.InvalidURL as exc:
            raise _configuration_error("paddle-vl-api base URL is invalid") from exc

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "PaddleVLClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.bearer_token}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(
                method,
                _relative_path(path),
                headers=self._headers(),
                **kwargs,
            )
        except httpx.TimeoutException:
            raise ProviderClientError(
                ProviderErrorDetail(
                    ProviderErrorCategory.TIMEOUT,
                    "provider request timed out",
                    retryable=True,
                )
            )
        except httpx.TransportError:
            raise ProviderClientError(
                ProviderErrorDetail(
                    ProviderErrorCategory.UNAVAILABLE,
                    "provider is unavailable",
                    retryable=True,
                )
            )
        if response.status_code >= 400:
            self._raise_http(response)
        return response

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception:
            raise ProviderClientError(
                ProviderErrorDetail(
                    ProviderErrorCategory.MALFORMED_RESPONSE,
                    "provider response was not valid JSON",
                    http_status=response.status_code,
                )
            )
        if not isinstance(payload, dict):
            raise ProviderClientError(
                ProviderErrorDetail(
                    ProviderErrorCategory.MALFORMED_RESPONSE,
                    "provider response JSON was not an object",
                    http_status=response.status_code,
                )
            )
        return payload

    def _raise_http(self, response: httpx.Response) -> None:
        provider_code = None
        safe_message = "provider request failed"
        retryable = False
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = body.get("detail", body.get("error", body))
                if isinstance(detail, dict):
                    provider_code = detail.get("code")
                    safe_message = detail.get("message") or safe_message
                    retryable = bool(detail.get("retryable", False))
        except Exception:
            pass

        category = _category_for_error(response.status_code, provider_code)
        raise ProviderClientError(
            ProviderErrorDetail(
                category,
                safe_message,
                response.status_code,
                provider_code,
                retryable,
            )
        )

    async def submit_job(self, request: PaddleVLJobRequest) -> ProviderSubmission:
        response = await self._request("POST", "ocr/jobs", json=request.to_provider_json())
        payload = self._json(response)
        try:
            return ProviderSubmission(
                payload["job_id"],
                payload.get("request_id"),
                map_status(payload.get("status", "queued")),
                payload.get("poll_url"),
                payload.get("result_url"),
                payload,
            )
        except KeyError as exc:
            raise _malformed_missing(exc, response.status_code)

    async def get_job_status(self, job_id: str) -> ProviderJobStatus:
        safe_job_id = _validate_path_id(job_id, "job_id")
        response = await self._request("GET", f"ocr/jobs/{safe_job_id}")
        payload = self._json(response)
        try:
            return ProviderJobStatus(
                payload["job_id"],
                payload.get("request_id"),
                map_status(payload["status"]),
                bool(payload.get("result_ready", False)),
                map_progress(payload),
                payload.get("error"),
                payload,
            )
        except KeyError as exc:
            raise _malformed_missing(exc, response.status_code)

    async def get_job_result(self, job_id: str, profile: str | None = None) -> ProviderResult:
        safe_job_id = _validate_path_id(job_id, "job_id")
        result_profile = _validate_result_profile(profile or self.config.default_result_profile)
        response = await self._request(
            "GET",
            f"ocr/jobs/{safe_job_id}/result",
            params={"profile": result_profile},
        )
        payload = self._json(response)
        error = payload.get("error")
        if isinstance(error, dict) and error.get("code") == "RESULT_NOT_READY":
            raise ProviderClientError(
                ProviderErrorDetail(
                    ProviderErrorCategory.RESULT_NOT_READY,
                    "OCR job result is not ready yet.",
                    response.status_code,
                    "RESULT_NOT_READY",
                    True,
                    job_id,
                    payload.get("request_id"),
                )
            )
        try:
            return ProviderResult(
                payload["job_id"],
                payload.get("request_id"),
                map_status(payload["status"]),
                payload.get("profile", result_profile),
                payload.get("result_artifact"),
                payload.get("documents", []),
                payload,
            )
        except KeyError as exc:
            raise _malformed_missing(exc, response.status_code)

    async def get_job_artifact(
        self,
        job_id: str,
        metadata: ArtifactMetadata | None = None,
    ) -> ProviderArtifact:
        safe_job_id = _validate_path_id(job_id, "job_id")
        response = await self._request("GET", f"ocr/jobs/{safe_job_id}/artifact")
        content = response.content
        metadata = metadata or _metadata_from_headers(response.headers)
        _verify_artifact_metadata(content, metadata)
        return ProviderArtifact(job_id, content, metadata)


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/"


def _relative_path(path: str) -> str:
    return path.lstrip("/")


def _validate_path_id(value: str, field_name: str) -> str:
    if not value or not value.strip():
        raise ProviderClientError(
            ProviderErrorDetail(ProviderErrorCategory.VALIDATION, f"{field_name} must be non-empty")
        )
    return quote(quote(value, safe=""), safe="")


def _validate_result_profile(profile: str) -> str:
    if profile not in VALID_RESULT_PROFILES:
        raise ProviderClientError(
            ProviderErrorDetail(
                ProviderErrorCategory.VALIDATION,
                "result profile must be one of: summary, standard, full",
            )
        )
    return profile


def _metadata_from_headers(headers: httpx.Headers) -> ArtifactMetadata:
    size_bytes = None
    if headers.get("Content-Length"):
        try:
            size_bytes = int(headers["Content-Length"])
        except ValueError:
            raise ProviderClientError(
                ProviderErrorDetail(
                    ProviderErrorCategory.MALFORMED_RESPONSE,
                    "artifact Content-Length was not an integer",
                )
            )
    return ArtifactMetadata(
        sha256=headers.get("X-Artifact-SHA256"),
        size_bytes=size_bytes,
        format=headers.get("Content-Type"),
    )


def _verify_artifact_metadata(content: bytes, metadata: ArtifactMetadata) -> None:
    if metadata.size_bytes is not None and metadata.size_bytes < 0:
        raise ProviderClientError(
            ProviderErrorDetail(
                ProviderErrorCategory.MALFORMED_RESPONSE,
                "artifact size metadata must be non-negative",
            )
        )
    if metadata.size_bytes is not None and len(content) != metadata.size_bytes:
        raise ProviderClientError(
            ProviderErrorDetail(
                ProviderErrorCategory.MALFORMED_RESPONSE,
                "artifact size did not match metadata",
            )
        )
    if metadata.sha256:
        digest = hashlib.sha256(content).hexdigest().lower()
        if not hmac.compare_digest(digest, metadata.sha256.lower()):
            raise ProviderClientError(
                ProviderErrorDetail(
                    ProviderErrorCategory.MALFORMED_RESPONSE,
                    "artifact SHA-256 did not match metadata",
                )
            )


def _category_for_error(status_code: int, provider_code: str | None) -> ProviderErrorCategory:
    if provider_code == "RESULT_NOT_READY":
        return ProviderErrorCategory.RESULT_NOT_READY
    if provider_code == "ARTIFACT_NOT_FOUND":
        return ProviderErrorCategory.ARTIFACT_MISSING
    if provider_code == "OCR_JOB_FAILED":
        return ProviderErrorCategory.EXECUTION_FAILED
    return {
        401: ProviderErrorCategory.AUTHENTICATION,
        404: ProviderErrorCategory.JOB_NOT_FOUND,
        409: ProviderErrorCategory.CONFLICT,
        410: ProviderErrorCategory.RESULT_EXPIRED,
        422: ProviderErrorCategory.VALIDATION,
        503: ProviderErrorCategory.UNAVAILABLE,
    }.get(status_code, ProviderErrorCategory.UNEXPECTED)


def _malformed_missing(exc: KeyError, http_status: int) -> ProviderClientError:
    return ProviderClientError(
        ProviderErrorDetail(
            ProviderErrorCategory.MALFORMED_RESPONSE,
            f"provider response missing required field: {exc.args[0]}",
            http_status=http_status,
        )
    )
