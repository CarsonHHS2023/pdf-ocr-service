"""Install Staging provider-delivery placement and presigned reads.

Ordering matters: the S0 heartbeat overlay must first instrument preprocessing
and provider wait, and provider runtime preflight must then guard configuration
before expensive S0 work. This overlay does not move the full render PDF. It
routes only the exact deferred provider subset/shards to remote-first storage,
then gives both single-job and sharded provider services a safe source URL
factory for that exact delivery identity.
"""
from __future__ import annotations

from pathlib import Path


PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")
PRESENTATION_LIFECYCLE_PATH = Path(
    "app/processing/pdf_page_presentation_lifecycle_compat.py"
)
PROVIDER_SHARDING_PATH = Path("app/processing/pdf_provider_sharding.py")

_DATACLASS_ANCHOR = "from dataclasses import dataclass\n"
_DATACLASS_WITH_TTL = "from dataclasses import dataclass\nfrom datetime import timedelta\n"

_ORCHESTRATION_IMPORT_ANCHOR = "from app.processing.orchestration import PollingPolicy\n"
_ORCHESTRATION_IMPORTS = '''from app.processing.provider_input_source_access import (
    build_provider_input_source_url_factory,
)
from app.processing.provider_lifecycle_policy import (
    ATLAS_PROVIDER_ORCHESTRATION_TIMEOUT_SECONDS,
    PROVIDER_JOB_TTL_SECONDS,
    PROVIDER_SOURCE_ACCESS_TTL_SECONDS,
)
from app.processing.orchestration import PollingPolicy
'''

_GEOMETRY_IMPORT_ANCHOR = '''    ProviderInputGrantService,
    prepare_geometry_provider_input,
)
'''
_GEOMETRY_IMPORTS = '''    ProviderInputGrantService,
    prepare_geometry_provider_input,
    provider_delivery_descriptor,
)
'''

_PROVIDER_TTL_ANCHOR = '    "ttl_seconds": 3600,\n'
_PROVIDER_TTL_POLICY = '    "ttl_seconds": PROVIDER_JOB_TTL_SECONDS,\n'

_GRANT_SERVICE_ANCHOR = '''        grant_service = ProviderInputGrantService(
            get_transport_grant_service(),
            geometry_input,
        )
'''
_GRANT_SERVICE_WITH_SOURCE_FACTORY = '''        grant_service = ProviderInputGrantService(
            get_transport_grant_service(),
            geometry_input,
        )
        provider_delivery = provider_delivery_descriptor(geometry_input)
        provider_source_url_factory = build_provider_input_source_url_factory(
            storage=storage,
            reference=provider_delivery.storage_reference,
            byte_size=provider_delivery.byte_size,
        )
'''

_SERVICE_POLICY_ANCHOR = '''            public_origin=settings.public_source_transport_origin,
            polling_policy=PollingPolicy(
                timeout_seconds=1800,
'''
_SERVICE_POLICY_ROUTED = '''            public_origin=settings.public_source_transport_origin,
            source_transport_url_factory=provider_source_url_factory,
            source_access_ttl=timedelta(
                seconds=PROVIDER_SOURCE_ACCESS_TTL_SECONDS,
            ),
            polling_policy=PollingPolicy(
                timeout_seconds=ATLAS_PROVIDER_ORCHESTRATION_TIMEOUT_SECONDS,
'''

_DELIVERY_CLEANUP_ANCHOR = '''                except Exception:
                    logger.exception(
                        "Could not delete temporary geometry PDF document_id=%s processing_attempt_id=%s",
                        document_id,
                        ids.processing_attempt_id,
                    )
            else:
'''
_DELIVERY_CLEANUP_ROUTED = '''                except Exception:
                    logger.exception(
                        "Could not delete temporary geometry PDF document_id=%s processing_attempt_id=%s",
                        document_id,
                        ids.processing_attempt_id,
                    )
                try:
                    provider_delivery = provider_delivery_descriptor(geometry_input)
                    if (
                        provider_delivery.storage_reference
                        != geometry_input.storage_reference
                        and storage.exists(provider_delivery.storage_reference)
                    ):
                        storage.delete(provider_delivery.storage_reference)
                        _diagnostic(
                            "PDF_PROVIDER_DELIVERY_INPUT_DELETED",
                            document_id=document_id,
                            processing_attempt_id=ids.processing_attempt_id,
                            byte_size=provider_delivery.byte_size,
                        )
                except Exception:
                    logger.exception(
                        "Could not delete temporary provider delivery PDF "
                        "document_id=%s processing_attempt_id=%s",
                        document_id,
                        ids.processing_attempt_id,
                    )
            else:
'''

_DEFERRED_STORE_ANCHOR = '''    from app.storage.dependencies import get_storage_provider

    storage = get_storage_provider()
    put = storage.put(
'''
_DEFERRED_STORE_REMOTE_FIRST = '''    from app.storage.dependencies import get_storage_provider
    from app.storage.provider_input_access import select_provider_input_storage

    storage = select_provider_input_storage(get_storage_provider())
    put = storage.put(
'''

_SHARD_DATACLASS_ANCHOR = "from dataclasses import dataclass, field, fields, replace\n"
_SHARD_DATACLASS_WITH_TTL = (
    "from dataclasses import dataclass, field, fields, replace\n"
    "from datetime import timedelta\n"
)
_SHARD_POLICY_IMPORT_ANCHOR = "from app.processing.orchestration import PollingPolicy\n"
_SHARD_POLICY_IMPORTS = '''from app.processing.provider_input_source_access import (
    build_provider_input_source_url_factory,
)
from app.processing.provider_lifecycle_policy import (
    PROVIDER_SOURCE_ACCESS_TTL_SECONDS,
)
from app.processing.orchestration import PollingPolicy
'''
_SHARD_GRANT_ANCHOR = '''        grant_service = integration.ProviderInputGrantService(
            get_transport_grant_service(),
            shard_input,
        )
        service = EndToEndProcessingIntegrationService(
            grant_service=grant_service,
            orchestrator=orchestrator,
            canonicalizer=None,
            public_origin=public_origin,
            polling_policy=polling_policy,
        )
'''
_SHARD_GRANT_WITH_SOURCE_FACTORY = '''        grant_service = integration.ProviderInputGrantService(
            get_transport_grant_service(),
            shard_input,
        )
        shard_delivery = integration.provider_delivery_descriptor(shard_input)
        shard_source_url_factory = build_provider_input_source_url_factory(
            storage=storage,
            reference=shard_delivery.storage_reference,
            byte_size=shard_delivery.byte_size,
        )
        service = EndToEndProcessingIntegrationService(
            grant_service=grant_service,
            orchestrator=orchestrator,
            canonicalizer=None,
            public_origin=public_origin,
            source_transport_url_factory=shard_source_url_factory,
            source_access_ttl=timedelta(
                seconds=PROVIDER_SOURCE_ACCESS_TTL_SECONDS,
            ),
            polling_policy=polling_policy,
        )
'''


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} anchor")
    return source.replace(old, new, 1)


def patch_pdf_ingestion(path: Path = PDF_INGESTION_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    if "await_with_pdf_processing_lease" not in source:
        raise RuntimeError(
            "Provider-input presigned read must be applied after the S0 heartbeat overlay"
        )
    if "validate_provider_runtime_configuration(settings)" not in source:
        raise RuntimeError(
            "Provider-input presigned read must be applied after provider runtime preflight"
        )

    source = _replace_once(source, _DATACLASS_ANCHOR, _DATACLASS_WITH_TTL, "timedelta import")
    source = _replace_once(
        source,
        _ORCHESTRATION_IMPORT_ANCHOR,
        _ORCHESTRATION_IMPORTS,
        "provider lifecycle imports",
    )
    source = _replace_once(
        source,
        _GEOMETRY_IMPORT_ANCHOR,
        _GEOMETRY_IMPORTS,
        "provider delivery import",
    )
    source = _replace_once(source, _PROVIDER_TTL_ANCHOR, _PROVIDER_TTL_POLICY, "provider job ttl")
    source = _replace_once(
        source,
        _GRANT_SERVICE_ANCHOR,
        _GRANT_SERVICE_WITH_SOURCE_FACTORY,
        "single-job provider source URL factory",
    )
    source = _replace_once(
        source,
        _SERVICE_POLICY_ANCHOR,
        _SERVICE_POLICY_ROUTED,
        "single-job provider lifecycle policy",
    )
    source = _replace_once(
        source,
        _DELIVERY_CLEANUP_ANCHOR,
        _DELIVERY_CLEANUP_ROUTED,
        "provider delivery cleanup",
    )
    path.write_text(source, encoding="utf-8")


def patch_deferred_provider_materialization(
    path: Path = PRESENTATION_LIFECYCLE_PATH,
) -> None:
    source = path.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        _DEFERRED_STORE_ANCHOR,
        _DEFERRED_STORE_REMOTE_FIRST,
        "deferred provider subset remote-first materialization",
    )
    path.write_text(source, encoding="utf-8")


def patch_provider_sharding(path: Path = PROVIDER_SHARDING_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        _SHARD_DATACLASS_ANCHOR,
        _SHARD_DATACLASS_WITH_TTL,
        "sharding timedelta import",
    )
    source = _replace_once(
        source,
        _SHARD_POLICY_IMPORT_ANCHOR,
        _SHARD_POLICY_IMPORTS,
        "sharding source-access imports",
    )
    source = _replace_once(
        source,
        _SHARD_GRANT_ANCHOR,
        _SHARD_GRANT_WITH_SOURCE_FACTORY,
        "per-shard provider source URL factory",
    )
    path.write_text(source, encoding="utf-8")


def patch_provider_input_presigned_read(
    path: Path = PDF_INGESTION_PATH,
    *,
    presentation_lifecycle_path: Path = PRESENTATION_LIFECYCLE_PATH,
    provider_sharding_path: Path = PROVIDER_SHARDING_PATH,
) -> None:
    """Install exact provider-delivery source access for single and sharded jobs."""
    patch_pdf_ingestion(path)
    patch_deferred_provider_materialization(presentation_lifecycle_path)
    patch_provider_sharding(provider_sharding_path)


def main() -> None:
    patch_provider_input_presigned_read()


if __name__ == "__main__":
    main()
