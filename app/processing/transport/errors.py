"""Typed errors for provider-independent source transport grants."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TransportGrantError(Exception):
    """Base class with only log-safe diagnostic fields."""

    category: str
    safe_message: str
    retryable: bool = False
    regrant_recommended: bool = False
    grant_id: str | None = None
    atlas_attempt_id: str | None = None
    provider_job_id: str | None = None

    def __str__(self) -> str:
        parts = [self.category, self.safe_message]
        if self.grant_id:
            parts.append(f"grant_id={self.grant_id}")
        if self.atlas_attempt_id:
            parts.append(f"atlas_attempt_id={self.atlas_attempt_id}")
        if self.provider_job_id:
            parts.append(f"provider_job_id={self.provider_job_id}")
        return ": ".join(parts)


class InvalidGrantInput(TransportGrantError):
    def __init__(self, message: str) -> None:
        super().__init__("invalid_grant_input", message)


class InvalidToken(TransportGrantError):
    def __init__(self, message: str = "Invalid transport credential") -> None:
        super().__init__("invalid_token", message, regrant_recommended=True)


class UnauthorizedGrant(TransportGrantError):
    def __init__(self, message: str = "Transport grant is not authorized") -> None:
        super().__init__("unauthorized_grant", message, regrant_recommended=True)


class ExpiredGrant(TransportGrantError):
    def __init__(self, grant_id: str | None = None) -> None:
        super().__init__("expired_grant", "Transport grant is not authorized", regrant_recommended=True, grant_id=grant_id)


class RevokedGrant(TransportGrantError):
    def __init__(self, grant_id: str | None = None) -> None:
        super().__init__("revoked_grant", "Transport grant is not authorized", regrant_recommended=True, grant_id=grant_id)


class RetrievalLimitExceeded(TransportGrantError):
    def __init__(self, grant_id: str | None = None) -> None:
        super().__init__("retrieval_limit_exceeded", "Transport grant retrieval limit is exhausted", regrant_recommended=True, grant_id=grant_id)


class GrantNotFound(TransportGrantError):
    def __init__(self) -> None:
        super().__init__("grant_not_found", "Transport grant is not authorized", regrant_recommended=True)


class GrantConflict(TransportGrantError):
    def __init__(self, message: str, grant_id: str | None = None) -> None:
        super().__init__("grant_conflict", message, retryable=True, grant_id=grant_id)


class UnsafeMetadata(TransportGrantError):
    def __init__(self, message: str) -> None:
        super().__init__("unsafe_metadata", message)


class RegistryFailure(TransportGrantError):
    def __init__(self, message: str) -> None:
        super().__init__("registry_failure", message, retryable=True)


class InvalidRetrievalState(TransportGrantError):
    def __init__(self, message: str, grant_id: str | None = None) -> None:
        super().__init__("invalid_retrieval_state", message, grant_id=grant_id)
