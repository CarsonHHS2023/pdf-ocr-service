"""Install Staging-only S0 v5 Phase 0 observability plus Phase 1 sharing."""
from __future__ import annotations

from pathlib import Path


PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")
_ANCHOR = "from app.database import SessionLocal\n"
_INSTALL = (
    "from app.processing.s0_v5_shadow_geometry import "
    "install_s0_v5_cheap_shadow_geometry\n"
    "from app.processing.s0_v5_phase0_observability_compat import "
    "install_s0_v5_phase0_observability\n"
    "from app.processing.s0_v5_phase1_shared_analysis_compat import "
    "install_s0_v5_phase1_shared_analysis\n\n"
    "install_s0_v5_cheap_shadow_geometry()\n"
    "install_s0_v5_phase0_observability()\n"
    "install_s0_v5_phase1_shared_analysis()\n\n"
)


def patch_s0_v5_phase0_observability(
    path: Path = PDF_INGESTION_PATH,
) -> None:
    """Install Phase 0 first, then Phase 1 cache checks around its delegates."""
    source = path.read_text(encoding="utf-8")
    if _INSTALL in source:
        return
    if source.count(_ANCHOR) != 1:
        raise RuntimeError("Could not find unique pdf_ingestion database import anchor")
    source = source.replace(_ANCHOR, _INSTALL + _ANCHOR, 1)
    path.write_text(source, encoding="utf-8")


def main() -> None:
    # Staging executes this script after the heartbeat and provider-preflight
    # overlays. Keep the reusable Phase0 patch function independent for focused
    # tests, while the deployment entry point installs provider-input access
    # immediately before the Phase0/Phase1 low-level wrappers capture delegates.
    if __package__:
        from scripts.apply_provider_input_presigned_read import (
            patch_provider_input_presigned_read,
        )
        from scripts.apply_provider_20mib_observability_v2 import (
            main as apply_provider_20mib_observability,
        )
    else:
        from apply_provider_input_presigned_read import (
            patch_provider_input_presigned_read,
        )
        from apply_provider_20mib_observability_v2 import (
            main as apply_provider_20mib_observability,
        )

    patch_provider_input_presigned_read()
    patch_s0_v5_phase0_observability()
    # This is deliberately last. It observes the fully composed production-like
    # presentation/native path and patches the already resilience-hardened
    # Provider sharding implementation that will be packed into the tested
    # Staging artifact.
    apply_provider_20mib_observability()


if __name__ == "__main__":
    main()
