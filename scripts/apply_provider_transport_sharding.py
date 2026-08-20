"""Install byte-bounded provider transport sharding into production PDF ingestion."""
from __future__ import annotations

from pathlib import Path


PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")
PROVIDER_SHARDING_PATH = Path("app/processing/pdf_provider_sharding.py")

_INSTALL = (
    "from app.processing.pdf_provider_sharding_compat import (\n"
    "    ShardingAwareEndToEndProcessingIntegrationService,\n"
    "    install_provider_transport_sharding_compat,\n"
    ")\n\n"
    "install_provider_transport_sharding_compat()\n\n"
)
_LEGACY_INSTALL = (
    "from app.processing.pdf_provider_sharding_compat import "
    "install_provider_transport_sharding_compat\n\n"
    "install_provider_transport_sharding_compat()\n\n"
)
_LOGGER_ANCHOR = 'logger = logging.getLogger("uvicorn.error")\n'
_SERVICE_ANCHOR = "        service = EndToEndProcessingIntegrationService(\n"
_SERVICE_SHARDING_AWARE = (
    "        service = ShardingAwareEndToEndProcessingIntegrationService(\n"
)
_SINGLE_SHARD_GUARD = (
    "    if shard_count <= 1 or not 0 <= plan.shard_index < shard_count:\n"
)
_SINGLE_SHARD_GUARD_FIXED = (
    "    if shard_count < 1 or not 0 <= plan.shard_index < shard_count:\n"
)


def patch_provider_transport_sharding_installation(
    path: Path = PDF_INGESTION_PATH,
) -> None:
    """Install sharding and make the production service choice explicit."""
    source = path.read_text(encoding="utf-8")
    install_present = _INSTALL in source
    legacy_install_present = _LEGACY_INSTALL in source
    explicit_service_present = _SERVICE_SHARDING_AWARE in source
    if install_present and explicit_service_present:
        return
    if legacy_install_present and not install_present:
        source = source.replace(_LEGACY_INSTALL, _INSTALL, 1)
        install_present = True
    if source.count(_LOGGER_ANCHOR) != 1:
        raise RuntimeError("Could not find unique pdf_ingestion logger anchor")

    required = (
        "PRODUCTION_BATCH_SIZE = 50",
        "PRODUCTION_MAX_CONCURRENT_WORKERS = 5",
        "EndToEndProcessingIntegrationService(",
    )
    missing = [value for value in required if value not in source]
    if missing:
        raise RuntimeError(
            f"Provider transport sharding production path is incomplete: {missing}"
        )

    if not install_present:
        source = source.replace(_LOGGER_ANCHOR, _INSTALL + _LOGGER_ANCHOR, 1)
    if not explicit_service_present:
        if source.count(_SERVICE_ANCHOR) != 1:
            raise RuntimeError(
                "Could not find unique production provider service constructor"
            )
        source = source.replace(
            _SERVICE_ANCHOR,
            _SERVICE_SHARDING_AWARE,
            1,
        )
    path.write_text(source, encoding="utf-8")


def patch_provider_single_shard_boundary(
    path: Path = PROVIDER_SHARDING_PATH,
) -> None:
    """Allow a valid one-plan compacted delivery while still rejecting zero shards."""
    source = path.read_text(encoding="utf-8")
    if _SINGLE_SHARD_GUARD_FIXED in source:
        return
    if source.count(_SINGLE_SHARD_GUARD) != 1:
        raise RuntimeError("Could not find unique provider single-shard guard")
    path.write_text(
        source.replace(_SINGLE_SHARD_GUARD, _SINGLE_SHARD_GUARD_FIXED, 1),
        encoding="utf-8",
    )


def main() -> None:
    patch_provider_transport_sharding_installation()
    patch_provider_single_shard_boundary()


if __name__ == "__main__":
    main()
