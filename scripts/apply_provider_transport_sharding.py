"""Install byte-bounded provider transport sharding into production PDF ingestion."""
from __future__ import annotations

from pathlib import Path


_INSTALL = (
    "from app.processing.pdf_provider_sharding_compat import "
    "install_provider_transport_sharding_compat\n\n"
    "install_provider_transport_sharding_compat()\n\n"
)
_LOGGER_ANCHOR = 'logger = logging.getLogger("uvicorn.error")\n'


def patch_provider_transport_sharding_installation() -> None:
    """Install after all normal imports and preserve existing overlay order."""
    path = Path("app/processing/pdf_ingestion.py")
    source = path.read_text(encoding="utf-8")
    if _INSTALL in source:
        return
    if source.count(_LOGGER_ANCHOR) != 1:
        raise RuntimeError("Could not find unique pdf_ingestion logger anchor")

    required = (
        "PRODUCTION_BATCH_SIZE = 50",
        "PRODUCTION_MAX_CONCURRENT_WORKERS = 5",
        "EndToEndProcessingIntegrationService(",
        "outcome = await service.process(request)",
    )
    missing = [value for value in required if value not in source]
    if missing:
        raise RuntimeError(
            f"Provider transport sharding production path is incomplete: {missing}"
        )

    path.write_text(
        source.replace(_LOGGER_ANCHOR, _INSTALL + _LOGGER_ANCHOR, 1),
        encoding="utf-8",
    )


def main() -> None:
    patch_provider_transport_sharding_installation()


if __name__ == "__main__":
    main()
