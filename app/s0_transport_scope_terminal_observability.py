"""Staging-only terminal proof for Provider source-transport retrieval scopes.

A per-retrieval StorageProvider event proves that one backend read happened, but
fail-open event persistence can lose the last successful read while leaving a
valid ordinal prefix. This observer records a separate terminal fact only after
the integration service successfully revokes a transport grant. The post-revoke
``retrieval_count`` is therefore the authoritative final count for that scope.

Timeout/submission-uncertain paths and revocation failures deliberately emit no
terminal proof because future retrievals may still occur.
"""
from __future__ import annotations

from functools import wraps
import hashlib
import re
from typing import Any, Callable


TRANSPORT_SCOPE_TERMINAL_EVENT = "S0_OBJECT_STORE_TRANSPORT_SCOPE_TERMINAL"
TRANSPORT_SCOPE_TERMINAL_SCOPE = "backend_storage_provider_logical_io_v1"
TRANSPORT_SCOPE_TERMINAL_STAGE = "provider_source_transport"

_INSTALLED = False
_SCOPE_ID_RE = re.compile(r"^transport_[0-9a-f]{16}$")


def _safe_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def transport_scope_id(grant_id: object) -> str | None:
    """Return the same privacy-safe scope id used by per-retrieval I/O events."""
    if not isinstance(grant_id, str) or not grant_id.strip():
        return None
    return "transport_" + hashlib.sha256(grant_id.strip().encode("utf-8")).hexdigest()[:16]


def _state_value(value: object) -> str | None:
    candidate = getattr(value, "value", value)
    if not isinstance(candidate, str):
        return None
    normalized = candidate.strip().lower()
    return normalized or None


def record_transport_scope_terminal(descriptor: object) -> bool:
    """Persist one post-revoke final retrieval count without affecting work."""
    try:
        from app.s0_object_store_io_observability import (
            staging_storage_io_observability_enabled,
        )

        if not staging_storage_io_observability_enabled():
            return False

        processing_run_id = str(
            getattr(descriptor, "atlas_attempt_id", "") or ""
        ).strip()
        document_id = str(getattr(descriptor, "document_id", "") or "").strip()
        scope_id = transport_scope_id(getattr(descriptor, "grant_id", None))
        terminal_count = _safe_nonnegative_int(
            getattr(descriptor, "retrieval_count", None)
        )
        if (
            not processing_run_id
            or not document_id
            or scope_id is None
            or _SCOPE_ID_RE.fullmatch(scope_id) is None
            or terminal_count is None
            or _state_value(getattr(descriptor, "state", None)) != "revoked"
        ):
            return False

        from app.processing.processing_events import record_processing_event

        return bool(
            record_processing_event(
                processing_run_id=processing_run_id,
                document_id=document_id,
                event_name=TRANSPORT_SCOPE_TERMINAL_EVENT,
                severity="info",
                payload={
                    "succeeded": True,
                    "measurement_scope": TRANSPORT_SCOPE_TERMINAL_SCOPE,
                    "stage": TRANSPORT_SCOPE_TERMINAL_STAGE,
                    "scope_id": scope_id,
                    "terminal_retrieval_count": terminal_count,
                },
            )
        )
    except Exception:
        # S0 telemetry is fail-open and must never change Provider lifecycle.
        return False


def _wrap_finalize(delegate: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(delegate, "__atlas_s0_transport_terminal__", False):
        return delegate

    @wraps(delegate)
    def wrapped(self, grant_id: str, *, revoke: bool, warnings: list[str]):
        final = delegate(self, grant_id, revoke=revoke, warnings=warnings)
        if revoke and getattr(final, "revoked", False) is True:
            descriptor = getattr(final, "descriptor", None)
            if descriptor is not None:
                record_transport_scope_terminal(descriptor)
        return final

    setattr(wrapped, "__atlas_s0_transport_terminal__", True)
    setattr(wrapped, "__atlas_s0_transport_terminal_delegate__", delegate)
    return wrapped


def install_s0_transport_scope_terminal_observability(*, force: bool = False) -> bool:
    """Observe only the authoritative post-revoke integration lifecycle boundary."""
    global _INSTALLED
    if _INSTALLED:
        return True

    if not force:
        try:
            from app.s0_object_store_io_observability import (
                staging_storage_io_observability_enabled,
            )

            if not staging_storage_io_observability_enabled():
                return False
        except Exception:
            return False

    from app.processing import integration

    delegate = integration.EndToEndProcessingIntegrationService._finalize
    if not getattr(delegate, "__atlas_s0_transport_terminal__", False):
        integration.EndToEndProcessingIntegrationService._finalize = _wrap_finalize(
            delegate
        )
    _INSTALLED = True
    return True


__all__ = [
    "TRANSPORT_SCOPE_TERMINAL_EVENT",
    "TRANSPORT_SCOPE_TERMINAL_SCOPE",
    "TRANSPORT_SCOPE_TERMINAL_STAGE",
    "install_s0_transport_scope_terminal_observability",
    "record_transport_scope_terminal",
    "transport_scope_id",
]
