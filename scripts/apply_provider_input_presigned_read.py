"""Install Staging provider-input object placement and presigned reads.

Ordering matters: the S0 heartbeat overlay must first instrument preprocessing
and provider wait, and provider runtime preflight must then guard configuration
before expensive S0 work. This overlay only changes where the already-produced
provider-input PDF is placed and how the remote provider receives its source URL.
"""
from __future__ import annotations

from pathlib import Path


PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")

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

_STORAGE_IMPORT_ANCHOR = "from app.storage.models import StorageReference\n"
_STORAGE_IMPORTS = '''from app.storage.models import StorageReference
from app.storage.provider_input_access import select_provider_input_storage
'''

_PROVIDER_TTL_ANCHOR = '    "ttl_seconds": 3600,\n'
_PROVIDER_TTL_POLICY = '    "ttl_seconds": PROVIDER_JOB_TTL_SECONDS,\n'

_PREP_SYNC_SIGNATURE = '''def _prepare_geometry_provider_input_from_storage(
    *,
    storage,
    descriptor: RetainedSourceDescriptor,
'''
_PREP_SYNC_WITH_OUTPUT_STORAGE = '''def _prepare_geometry_provider_input_from_storage(
    *,
    storage,
    provider_input_storage,
    descriptor: RetainedSourceDescriptor,
'''

_PREP_OUTPUT_ANCHOR = '''        result = prepare_geometry_provider_input(
            storage=storage,
'''
_PREP_OUTPUT_ROUTED = '''        result = prepare_geometry_provider_input(
            storage=provider_input_storage,
'''

_PREP_ASYNC_SIGNATURE = '''async def _prepare_geometry_provider_input_async(
    *,
    storage,
    descriptor: RetainedSourceDescriptor,
'''
_PREP_ASYNC_WITH_OUTPUT_STORAGE = '''async def _prepare_geometry_provider_input_async(
    *,
    storage,
    provider_input_storage,
    descriptor: RetainedSourceDescriptor,
'''

_JOB_STATE_ANCHOR = '''    job_state = _PreprocessingJobState(
        storage=storage,
'''
_JOB_STATE_ROUTED = '''    job_state = _PreprocessingJobState(
        storage=provider_input_storage,
'''

_EXECUTOR_ANCHOR = '''                _prepare_geometry_provider_input_from_storage,
                storage=storage,
                descriptor=descriptor,
'''
_EXECUTOR_ROUTED = '''                _prepare_geometry_provider_input_from_storage,
                storage=storage,
                provider_input_storage=provider_input_storage,
                descriptor=descriptor,
'''

_RUNTIME_STORAGE_ANCHOR = '''    storage = get_storage_provider()
    client: PaddleVLClient | None = None
'''
_RUNTIME_STORAGE_ROUTED = '''    storage = get_storage_provider()
    provider_input_storage = select_provider_input_storage(storage)
    client: PaddleVLClient | None = None
'''

_ASYNC_CALL_ANCHOR = '''        geometry_input = await _prepare_geometry_provider_input_async(
            storage=storage,
            descriptor=descriptor,
'''
_ASYNC_CALL_ROUTED = '''        geometry_input = await _prepare_geometry_provider_input_async(
            storage=storage,
            provider_input_storage=provider_input_storage,
            descriptor=descriptor,
'''

_GRANT_SERVICE_ANCHOR = '''        grant_service = ProviderInputGrantService(
            get_transport_grant_service(),
            geometry_input,
        )
        service = EndToEndProcessingIntegrationService(
'''
_GRANT_SERVICE_WITH_SOURCE_FACTORY = '''        grant_service = ProviderInputGrantService(
            get_transport_grant_service(),
            geometry_input,
        )
        provider_source_url_factory = build_provider_input_source_url_factory(
            storage=provider_input_storage,
            reference=geometry_input.storage_reference,
            byte_size=geometry_input.byte_size,
        )
        service = EndToEndProcessingIntegrationService(
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

_FINAL_DELETE_ANCHOR = "                    storage.delete(geometry_input.storage_reference)\n"
_FINAL_DELETE_ROUTED = (
    "                    provider_input_storage.delete(geometry_input.storage_reference)\n"
)


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} anchor")
    return source.replace(old, new, 1)


def patch_provider_input_presigned_read(path: Path = PDF_INGESTION_PATH) -> None:
    """Route one computed provider input through remote-first storage and safe URL access."""
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
        _STORAGE_IMPORT_ANCHOR,
        _STORAGE_IMPORTS,
        "provider input storage import",
    )
    source = _replace_once(source, _PROVIDER_TTL_ANCHOR, _PROVIDER_TTL_POLICY, "provider job ttl")
    source = _replace_once(
        source,
        _PREP_SYNC_SIGNATURE,
        _PREP_SYNC_WITH_OUTPUT_STORAGE,
        "sync preprocessing storage parameter",
    )
    source = _replace_once(
        source,
        _PREP_OUTPUT_ANCHOR,
        _PREP_OUTPUT_ROUTED,
        "provider input output storage",
    )
    source = _replace_once(
        source,
        _PREP_ASYNC_SIGNATURE,
        _PREP_ASYNC_WITH_OUTPUT_STORAGE,
        "async preprocessing storage parameter",
    )
    source = _replace_once(source, _JOB_STATE_ANCHOR, _JOB_STATE_ROUTED, "cancel cleanup storage")
    source = _replace_once(source, _EXECUTOR_ANCHOR, _EXECUTOR_ROUTED, "executor output storage")
    source = _replace_once(
        source,
        _RUNTIME_STORAGE_ANCHOR,
        _RUNTIME_STORAGE_ROUTED,
        "runtime provider input router",
    )
    source = _replace_once(source, _ASYNC_CALL_ANCHOR, _ASYNC_CALL_ROUTED, "async output storage")
    source = _replace_once(
        source,
        _GRANT_SERVICE_ANCHOR,
        _GRANT_SERVICE_WITH_SOURCE_FACTORY,
        "provider source URL factory",
    )
    source = _replace_once(
        source,
        _SERVICE_POLICY_ANCHOR,
        _SERVICE_POLICY_ROUTED,
        "provider lifecycle policy",
    )
    source = _replace_once(
        source,
        _FINAL_DELETE_ANCHOR,
        _FINAL_DELETE_ROUTED,
        "provider input final cleanup",
    )
    path.write_text(source, encoding="utf-8")


def main() -> None:
    patch_provider_input_presigned_read()


if __name__ == "__main__":
    main()
