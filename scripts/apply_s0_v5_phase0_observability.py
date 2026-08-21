"""Install Staging-only S0 v5 Phase 0 observability plus Phase 1 sharing."""
from __future__ import annotations

from pathlib import Path


PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")
PROVIDER_SHARDING_PATH = Path("app/processing/pdf_provider_sharding.py")
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
_PROVIDER_20MIB_FINAL_MARKERS = (
    "PROVIDER_TRANSPORT_SHARD_TARGET_BYTES = 20 * _MIB",
    "PROVIDER_TRANSPORT_SHARD_MAX_BYTES = 20 * _MIB",
    'PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE = "sequential"',
    "PDF_PROVIDER_SHARD_CANONICALIZATION_FAILED",
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


def _provider_20mib_final_composition_installed(
    path: Path = PROVIDER_SHARDING_PATH,
) -> bool:
    """Return true once the v2-v5/review chain has reached its final contract."""
    source = path.read_text(encoding="utf-8")
    return all(marker in source for marker in _PROVIDER_20MIB_FINAL_MARKERS)


def main() -> None:
    # Staging executes this script after the heartbeat and provider-preflight
    # overlays. Keep the reusable Phase0 patch function independent for focused
    # tests, while the deployment entry point installs provider-input access
    # immediately before the Phase0/Phase1 low-level wrappers capture delegates.
    if __package__:
        from scripts.apply_provider_input_presigned_read import (
            patch_provider_input_presigned_read,
        )
        from scripts.apply_provider_20mib_review_fixes import (
            main as apply_provider_20mib_observability,
        )
        from scripts.apply_provider_20mib_poll_count_fix import (
            main as apply_provider_20mib_poll_count_fix,
        )
        from scripts.apply_provider_terminal_poll_diagnostic import (
            main as apply_provider_terminal_poll_diagnostic,
        )
    else:
        from apply_provider_input_presigned_read import (
            patch_provider_input_presigned_read,
        )
        from apply_provider_20mib_review_fixes import (
            main as apply_provider_20mib_observability,
        )
        from apply_provider_20mib_poll_count_fix import (
            main as apply_provider_20mib_poll_count_fix,
        )
        from apply_provider_terminal_poll_diagnostic import (
            main as apply_provider_terminal_poll_diagnostic,
        )

    patch_provider_input_presigned_read()
    patch_s0_v5_phase0_observability()
    # The historical v2-v5 overlays rewrite exact anchors and are intentionally
    # a one-way composition chain. On a second invocation, recognize the final
    # 20 MiB sequential contract and skip replaying that legacy chain. The later
    # poll/terminal guards are independently idempotent and still run.
    if not _provider_20mib_final_composition_installed():
        apply_provider_20mib_observability()
    apply_provider_20mib_poll_count_fix()
    apply_provider_terminal_poll_diagnostic()


if __name__ == "__main__":
    main()
