"""Install Staging-only S0 v5 Phase 0 observability plus Phase 1 sharing."""
from __future__ import annotations

from pathlib import Path


PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")
PRESENTATION_LIFECYCLE_PATH = Path(
    "app/processing/pdf_page_presentation_lifecycle_compat.py"
)
PROVIDER_SHARDING_PATH = Path("app/processing/pdf_provider_sharding.py")
PROVIDER_SHARDING_COMPAT_PATH = Path(
    "app/processing/pdf_provider_sharding_compat.py"
)
CLASSIFICATION_OBSERVABILITY_PATH = Path(
    "app/processing/pdf_page_classification_observability_compat.py"
)
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


def _final_staging_composition_installed() -> bool:
    """Recognize the complete final runtime so a second invocation is a no-op."""
    ingestion = PDF_INGESTION_PATH.read_text(encoding="utf-8")
    lifecycle = PRESENTATION_LIFECYCLE_PATH.read_text(encoding="utf-8")
    sharding = PROVIDER_SHARDING_PATH.read_text(encoding="utf-8")
    compat = PROVIDER_SHARDING_COMPAT_PATH.read_text(encoding="utf-8")
    classification = CLASSIFICATION_OBSERVABILITY_PATH.read_text(encoding="utf-8")

    return (
        _INSTALL in ingestion
        and "with page_classification_observation_context(processing_attempt_id):" in ingestion
        and "poll_count=outcome.poll_count" in ingestion
        and "select_provider_input_storage(get_storage_provider())" in lifecycle
        and all(marker in sharding for marker in _PROVIDER_20MIB_FINAL_MARKERS)
        and "shard_source_url_factory = build_provider_input_source_url_factory(" in sharding
        and "source_transport_url_factory=shard_source_url_factory" in sharding
        and "poll_count: int = 0" in sharding
        and "total_poll_count += max(0, int(outcome.poll_count or 0))" in sharding
        and sharding.count("poll_count=total_poll_count") >= 1
        and "PDF_PROVIDER_SHARD_INPUT_ALREADY_DELETED" in sharding
        and "already_missing=False" in sharding
        and "provider_phase_completed: bool = False" in sharding
        and compat.count("poll_count=result.poll_count") == 2
        and "PdfCanonicalizationError" in compat
        and "IntegrationErrorCategory.CANONICALIZATION_FAILURE" in compat
        and "def _logical_terminal_diagnostic_fields(" in compat
        and 'fields["provider_status"] = ProviderLifecycleStatus.PROVIDER_COMPLETED.value' in compat
        and "provider_phase_completed=result.provider_phase_completed" in compat
        and "print(message, file=sys.stderr, flush=True)" in classification
        and classification.count("_diagnostic(") >= 4
        and '"presentation_page_high_resolution_confirmed",' in classification
    )


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
        from scripts.apply_staging_baseline_observability_hotfix import (
            main as apply_staging_baseline_observability_hotfix,
        )
        from scripts.apply_staging_baseline_canonicalization_terminal_fix import (
            main as apply_staging_baseline_canonicalization_terminal_fix,
        )
        from scripts.apply_staging_post_provider_terminal_fix import (
            main as apply_staging_post_provider_terminal_fix,
        )
        from scripts.apply_staging_classification_summary_highres_fix import (
            main as apply_staging_classification_summary_highres_fix,
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
        from apply_staging_baseline_observability_hotfix import (
            main as apply_staging_baseline_observability_hotfix,
        )
        from apply_staging_baseline_canonicalization_terminal_fix import (
            main as apply_staging_baseline_canonicalization_terminal_fix,
        )
        from apply_staging_post_provider_terminal_fix import (
            main as apply_staging_post_provider_terminal_fix,
        )
        from apply_staging_classification_summary_highres_fix import (
            main as apply_staging_classification_summary_highres_fix,
        )

    # The source-rewrite stack below is a composition step, not a migration that
    # should keep editing an already composed checkout. Once every final runtime
    # marker is present, a repeated invocation is deliberately a byte-for-byte
    # no-op. The regression suite verifies the key composed file digests remain
    # unchanged across that second invocation.
    if _final_staging_composition_installed():
        print("staging provider composition already installed: no changes")
        return

    patch_provider_input_presigned_read()
    patch_s0_v5_phase0_observability()
    # The historical v2-v5 overlays rewrite exact anchors and are intentionally
    # a one-way composition chain. If a partially composed checkout has already
    # reached the final 20 MiB review contract, skip replaying that legacy chain
    # and finish only the later poll/terminal guards.
    if not _provider_20mib_final_composition_installed():
        apply_provider_20mib_observability()
    apply_provider_20mib_poll_count_fix()
    apply_provider_terminal_poll_diagnostic()
    apply_staging_baseline_observability_hotfix()
    apply_staging_baseline_canonicalization_terminal_fix()
    apply_staging_post_provider_terminal_fix()
    apply_staging_classification_summary_highres_fix()


if __name__ == "__main__":
    main()
