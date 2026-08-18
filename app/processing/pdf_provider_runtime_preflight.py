"""Fail-fast validation for the PDF provider runtime boundary.

The expensive PDF preprocessing path must not start when the deployment cannot
submit provider work or expose transport grants.  This module validates presence
only; it never logs or returns credential values.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderRuntimeConfigurationStatus:
    base_url_configured: bool
    bearer_token_configured: bool
    public_origin_configured: bool

    @property
    def ready(self) -> bool:
        return bool(
            self.base_url_configured
            and self.bearer_token_configured
            and self.public_origin_configured
        )

    @property
    def missing_fields(self) -> tuple[str, ...]:
        missing: list[str] = []
        if not self.base_url_configured:
            missing.append("PADDLE_VL_API_BASE_URL")
        if not self.bearer_token_configured:
            missing.append("PADDLE_VL_API_BEARER_TOKEN")
        if not self.public_origin_configured:
            missing.append("ATLAS_PUBLIC_SOURCE_TRANSPORT_ORIGIN")
        return tuple(missing)


class PdfProviderRuntimeConfigurationError(RuntimeError):
    """Safe deployment-configuration failure before expensive preprocessing."""

    safe_message = "PDF provider configuration is unavailable"

    def __init__(self, status: ProviderRuntimeConfigurationStatus) -> None:
        super().__init__("pdf_provider_runtime_configuration_missing")
        self.status = status


def provider_runtime_configuration_status(
    settings: Any,
) -> ProviderRuntimeConfigurationStatus:
    """Return secret-safe presence flags for all provider submission inputs."""
    return ProviderRuntimeConfigurationStatus(
        base_url_configured=bool(getattr(settings, "paddle_vl_api_base_url", None)),
        bearer_token_configured=bool(
            getattr(settings, "paddle_vl_api_bearer_token", None)
        ),
        public_origin_configured=bool(
            getattr(settings, "public_source_transport_origin", None)
        ),
    )


def validate_provider_runtime_configuration(settings: Any) -> None:
    """Raise a safe error when any required runtime setting is absent."""
    status = provider_runtime_configuration_status(settings)
    if not status.ready:
        raise PdfProviderRuntimeConfigurationError(status)


__all__ = [
    "PdfProviderRuntimeConfigurationError",
    "ProviderRuntimeConfigurationStatus",
    "provider_runtime_configuration_status",
    "validate_provider_runtime_configuration",
]
