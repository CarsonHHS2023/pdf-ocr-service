"""Shared PDF provider lifecycle timing contract.

These values describe different boundaries and must remain ordered. Atlas may
stop polling before the remote provider job expires, while the provider source
URL must remain usable slightly beyond the provider job lifetime so queued or
late-starting workers do not lose access at the exact TTL boundary.
"""
from __future__ import annotations


ATLAS_PROVIDER_ORCHESTRATION_TIMEOUT_SECONDS = 30 * 60
PROVIDER_JOB_TTL_SECONDS = 60 * 60
PROVIDER_SOURCE_ACCESS_TTL_SECONDS = 70 * 60
PROVIDER_SOURCE_GRANT_MAX_TTL_SECONDS = 90 * 60


def validate_provider_lifecycle_policy() -> None:
    values = (
        ATLAS_PROVIDER_ORCHESTRATION_TIMEOUT_SECONDS,
        PROVIDER_JOB_TTL_SECONDS,
        PROVIDER_SOURCE_ACCESS_TTL_SECONDS,
        PROVIDER_SOURCE_GRANT_MAX_TTL_SECONDS,
    )
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in values):
        raise ValueError("provider lifecycle values must be positive integers")
    if not (
        ATLAS_PROVIDER_ORCHESTRATION_TIMEOUT_SECONDS
        < PROVIDER_JOB_TTL_SECONDS
        < PROVIDER_SOURCE_ACCESS_TTL_SECONDS
        <= PROVIDER_SOURCE_GRANT_MAX_TTL_SECONDS
    ):
        raise ValueError(
            "provider lifecycle must satisfy atlas_timeout < provider_job_ttl "
            "< source_access_ttl <= grant_max_ttl"
        )


validate_provider_lifecycle_policy()


__all__ = [
    "ATLAS_PROVIDER_ORCHESTRATION_TIMEOUT_SECONDS",
    "PROVIDER_JOB_TTL_SECONDS",
    "PROVIDER_SOURCE_ACCESS_TTL_SECONDS",
    "PROVIDER_SOURCE_GRANT_MAX_TTL_SECONDS",
    "validate_provider_lifecycle_policy",
]
