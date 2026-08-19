from __future__ import annotations

from datetime import timedelta

from app.processing.provider_lifecycle_policy import (
    ATLAS_PROVIDER_ORCHESTRATION_TIMEOUT_SECONDS,
    PROVIDER_JOB_TTL_SECONDS,
    PROVIDER_SOURCE_ACCESS_TTL_SECONDS,
    PROVIDER_SOURCE_GRANT_MAX_TTL_SECONDS,
    validate_provider_lifecycle_policy,
)
from app.processing.transport import dependencies as transport_dependencies


def test_provider_lifecycle_boundaries_are_strictly_ordered() -> None:
    validate_provider_lifecycle_policy()
    assert ATLAS_PROVIDER_ORCHESTRATION_TIMEOUT_SECONDS == 1800
    assert PROVIDER_JOB_TTL_SECONDS == 3600
    assert PROVIDER_SOURCE_ACCESS_TTL_SECONDS == 4200
    assert PROVIDER_SOURCE_GRANT_MAX_TTL_SECONDS == 5400
    assert (
        ATLAS_PROVIDER_ORCHESTRATION_TIMEOUT_SECONDS
        < PROVIDER_JOB_TTL_SECONDS
        < PROVIDER_SOURCE_ACCESS_TTL_SECONDS
        <= PROVIDER_SOURCE_GRANT_MAX_TTL_SECONDS
    )


def test_runtime_grant_registry_allows_source_access_margin_without_changing_default_ttl() -> None:
    policy = transport_dependencies._transport_grant_service._policy

    assert policy.default_ttl == timedelta(minutes=20)
    assert policy.maximum_ttl == timedelta(seconds=PROVIDER_SOURCE_GRANT_MAX_TTL_SECONDS)
    # The existing Atlas fallback byte ceiling remains deliberately unchanged in
    # this slice; presigned-provider bookkeeping is decoupled in a later slice.
    assert policy.default_max_source_bytes == 100 * 1024 * 1024
