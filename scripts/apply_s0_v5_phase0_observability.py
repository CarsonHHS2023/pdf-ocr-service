"""Install Staging-only S0 v5 Phase 0 observability plus Phase 1/2 sharing."""
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
    "install_s0_v5_phase1_shared_analysis\n"
    "from app.processing.s0_phase2_stage_observability import "
    "install_s0_phase2_stage_observability\n\n"
    "install_s0_v5_cheap_shadow_geometry()\n"
    "install_s0_v5_phase0_observability()\n"
    "install_s0_v5_phase1_shared_analysis()\n"
    "install_s0_phase2_stage_observability()\n\n"
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
    """Install Phase 0/1/2 observational wrappers around existing delegates."""
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


def _make_shard_document_correlation_optional() -> None:
    """Never make a telemetry-only document field part of the Provider runner contract."""
    source = PROVIDER_SHARDING_PATH.read_text(encoding="utf-8")
    safe = (
        'document_id=descriptor.document_id if hasattr(descriptor, "document_id") '
        'else None,'
    )
    if safe in source:
        return
    old = "document_id=descriptor.document_id,"
    if old not in source:
        if "shard_source_url_factory = build_provider_input_source_url_factory(" in source:
            raise RuntimeError("final shard source factory lacks document correlation hook")
        return
    PROVIDER_SHARDING_PATH.write_text(
        source.replace(old, safe, 1),
        encoding="utf-8",
    )


def main() -> None:
    # Staging executes this script after the heartbeat and provider-preflight
    # overlays. Keep the reusable Phase0 patch function independent for focused
    # tests, while the deployment entry point installs provider-input access
    # immediately before the Phase0/Phase1/Phase2 low-level wrappers capture delegates.
    if __package__:
        from scripts.apply_durable_processing_events import (
            patch_durable_processing_events,
        )
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
        from scripts.apply_s0_object_store_io_observability import (
            main as apply_s0_object_store_io_observability,
        )
        from scripts.apply_s0_transport_terminal_collector import (
            main as apply_s0_transport_terminal_collector,
        )
        from scripts.apply_s0_transport_download_observability import (
            main as apply_s0_transport_download_observability,
        )
        from scripts.apply_s0_reader_open_observability import main as apply_s0_reader_open_observability
        from scripts.apply_s0_provider_compute_observability import (
            main as apply_s0_provider_compute_observability,
        )
        from scripts.apply_s0_provider_source_download_observability import (
            main as apply_s0_provider_source_download_observability,
        )
        from scripts.apply_s0_provider_staging_routing import (
            main as apply_s0_provider_staging_routing,
        )
        from scripts.apply_s0_upload_baseline_mapping import (
            patch_s0_upload_baseline_mapping,
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
        from scripts.apply_structure_refinement_batch_budgeting import (
            main as apply_structure_refinement_batch_budgeting,
        )
        from scripts.apply_structure_refinement_heading_batch_atomicity import (
            main as apply_structure_refinement_heading_batch_atomicity,
        )
        from scripts.apply_structure_refinement_batch_safety import (
            main as apply_structure_refinement_batch_safety,
        )
        from scripts.apply_structure_refinement_shared_node_ownership import (
            main as apply_structure_refinement_shared_node_ownership,
        )
        from scripts.apply_structure_refinement_soft_batch_targets import (
            main as apply_structure_refinement_soft_batch_targets,
        )
    else:
        from apply_durable_processing_events import patch_durable_processing_events
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
        from apply_s0_object_store_io_observability import (
            main as apply_s0_object_store_io_observability,
        )
        from apply_s0_transport_terminal_collector import (
            main as apply_s0_transport_terminal_collector,
        )
        from apply_s0_transport_download_observability import (
            main as apply_s0_transport_download_observability,
        )
        from apply_s0_reader_open_observability import main as apply_s0_reader_open_observability
        from apply_s0_provider_compute_observability import (
            main as apply_s0_provider_compute_observability,
        )
        from apply_s0_provider_source_download_observability import (
            main as apply_s0_provider_source_download_observability,
        )
        from apply_s0_provider_staging_routing import (
            main as apply_s0_provider_staging_routing,
        )
        from apply_s0_upload_baseline_mapping import patch_s0_upload_baseline_mapping
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
        from apply_structure_refinement_batch_budgeting import (
            main as apply_structure_refinement_batch_budgeting,
        )
        from apply_structure_refinement_heading_batch_atomicity import (
            main as apply_structure_refinement_heading_batch_atomicity,
        )
        from apply_structure_refinement_batch_safety import (
            main as apply_structure_refinement_batch_safety,
        )
        from apply_structure_refinement_shared_node_ownership import (
            main as apply_structure_refinement_shared_node_ownership,
        )
        from apply_structure_refinement_soft_batch_targets import (
            main as apply_structure_refinement_soft_batch_targets,
        )

    apply_structure_refinement_batch_budgeting()
    apply_structure_refinement_heading_batch_atomicity()
    apply_structure_refinement_batch_safety()
    apply_structure_refinement_shared_node_ownership()
    apply_structure_refinement_soft_batch_targets()
    # Patch the read-only S0 collector before either the fast-path return or the
    # remaining Provider composition. This is idempotent and changes only how
    # already-durable upload/storage evidence is interpreted in the tested artifact.
    patch_s0_upload_baseline_mapping()
    apply_s0_object_store_io_observability()
    apply_s0_transport_terminal_collector()
    # S0.3.3 must be part of the authoritative tested Staging artifact, not only
    # the focused baseline CI. Compose Backend send/route evidence first, then
    # Provider consumer-download evidence, then the exact-Staging Provider route.
    # These overlays are idempotent and fail open at runtime / closed in the
    # collector. The endpoint resolver changes routing only when staging-revision.txt
    # contains a valid exact tested Staging SHA.
    apply_s0_transport_download_observability()
    apply_s0_provider_source_download_observability()
    # S0.3.4 closes compute evidence against the S0.3.3 Provider scopes.
    apply_s0_provider_compute_observability()
    apply_s0_reader_open_observability()
    apply_s0_provider_staging_routing()

    # Durable telemetry is deliberately finalized after the historical Provider
    # rewrite chain. A prior preflight pass may install it early, but v2-v5 can
    # replace source-factory call sites. Re-running the idempotent installer here
    # restores only observability correlation on the exact final runtime.
    if _final_staging_composition_installed():
        patch_durable_processing_events()
        _make_shard_document_correlation_optional()
        print("staging provider composition already installed: no changes")
        return

    patch_provider_input_presigned_read()
    patch_s0_v5_phase0_observability()
    if not _provider_20mib_final_composition_installed():
        apply_provider_20mib_observability()
    apply_provider_20mib_poll_count_fix()
    apply_provider_terminal_poll_diagnostic()
    apply_staging_baseline_observability_hotfix()
    apply_staging_baseline_canonicalization_terminal_fix()
    apply_staging_post_provider_terminal_fix()
    apply_staging_classification_summary_highres_fix()
    patch_durable_processing_events()
    _make_shard_document_correlation_optional()


if __name__ == "__main__":
    main()
