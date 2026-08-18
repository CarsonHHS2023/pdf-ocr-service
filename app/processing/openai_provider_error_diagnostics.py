"""Bounded OpenAI HTTP error diagnostics for structure refinement."""
from __future__ import annotations

from typing import Any, AsyncContextManager, Mapping

import httpx

from app.processing.openai_structure_refinement_provider import (
    StructureRefinementProviderError,
)
from app.processing.refinement_provider_diagnostics import (
    emit_refinement_provider_event,
)

_RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})
_NON_RETRYABLE_QUOTA_ERROR_TYPES = frozenset({"insufficient_quota"})
_NON_RETRYABLE_QUOTA_ERROR_CODES = frozenset(
    {"credit_balance_exhausted", "insufficient_quota"}
)
_MAX_ERROR_FIELD_LENGTH = 300


def _bounded_error_field(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    return normalized[:_MAX_ERROR_FIELD_LENGTH]


def _safe_openai_error_fields(response: httpx.Response) -> dict[str, object]:
    """Return only structured provider metadata that cannot contain request content."""

    fields: dict[str, object] = {"status_code": response.status_code}
    try:
        decoded = response.json()
    except ValueError:
        return fields
    if not isinstance(decoded, Mapping):
        return fields
    error = decoded.get("error")
    if not isinstance(error, Mapping):
        return fields
    for source_name, field_name in (
        ("type", "provider_error_type"),
        ("code", "provider_error_code"),
        ("param", "provider_error_param"),
    ):
        value = _bounded_error_field(error.get(source_name))
        if value is not None:
            fields[field_name] = value
    return fields


def _is_non_retryable_quota_error(fields: Mapping[str, object]) -> bool:
    return (
        fields.get("provider_error_type") in _NON_RETRYABLE_QUOTA_ERROR_TYPES
        or fields.get("provider_error_code") in _NON_RETRYABLE_QUOTA_ERROR_CODES
    )


async def _emit_http_error_response(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    await response.aread()
    fields = _safe_openai_error_fields(response)
    emit_refinement_provider_event(
        "PDF_STRUCTURE_REFINEMENT_PROVIDER_HTTP_ERROR",
        fields,
    )
    if response.status_code == 429 and _is_non_retryable_quota_error(fields):
        raise StructureRefinementProviderError(
            "structure refinement provider credit balance exhausted",
            retryable=False,
            status_code=response.status_code,
        )


def diagnostic_openai_client_factory(
    timeout_seconds: float,
) -> AsyncContextManager[httpx.AsyncClient]:
    """Build the shared batched client with safe HTTP-error response diagnostics."""

    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds),
        event_hooks={"response": [_emit_http_error_response]},
    )


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value.strip())
    except (TypeError, ValueError):
        return None
    return max(0.0, parsed)


async def diagnostic_openai_http_post(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    """Compatibility adapter for non-batched calls with the same safe diagnostics."""

    try:
        async with diagnostic_openai_client_factory(timeout_seconds) as client:
            response = await client.post(url, headers=dict(headers), json=payload)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        raise StructureRefinementProviderError(
            f"structure refinement provider HTTP {status_code}",
            retryable=status_code in _RETRYABLE_STATUS_CODES,
            status_code=status_code,
            retry_after_seconds=_retry_after_seconds(
                exc.response.headers.get("Retry-After")
            ),
        ) from exc
    except httpx.RequestError as exc:
        raise StructureRefinementProviderError(
            "structure refinement provider unavailable",
            retryable=True,
        ) from exc

    try:
        decoded = response.json()
    except ValueError as exc:
        raise StructureRefinementProviderError(
            "structure refinement provider returned invalid JSON",
            retryable=False,
            status_code=response.status_code,
        ) from exc
    if not isinstance(decoded, Mapping):
        raise StructureRefinementProviderError(
            "structure refinement provider response must be an object",
            retryable=False,
            status_code=response.status_code,
        )
    return decoded


__all__ = [
    "diagnostic_openai_client_factory",
    "diagnostic_openai_http_post",
]
