from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from scripts.apply_provider_input_presigned_read import (
    patch_provider_input_presigned_read,
)
from scripts.apply_provider_runtime_preflight import patch_provider_runtime_preflight
from scripts.apply_provider_transport_sharding import (
    patch_provider_transport_sharding_installation,
)
from scripts.apply_s0_pdf_resource_heartbeat import patch_s0_pdf_resource_heartbeat
from scripts.apply_s0_v5_phase0_observability import patch_s0_v5_phase0_observability


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_INGESTION = REPO_ROOT / "app" / "processing" / "pdf_ingestion.py"
BASE_LIFECYCLE = (
    REPO_ROOT / "app" / "processing" / "pdf_page_presentation_lifecycle_compat.py"
)
BASE_SHARDING = REPO_ROOT / "app" / "processing" / "pdf_provider_sharding.py"
PHASE0_INSTALLER = REPO_ROOT / "scripts" / "apply_s0_v5_phase0_observability.py"


def _copy_target(tmp_path, source: Path) -> Path:
    path = tmp_path / source.name
    path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _copy_raw_head_target(tmp_path, relative_path: str) -> Path:
    content = subprocess.check_output(
        ["git", "show", f"HEAD:{relative_path}"],
        cwd=REPO_ROOT,
        text=True,
    )
    path = tmp_path / Path(relative_path).name
    path.write_text(content, encoding="utf-8")
    return path


def _targets(tmp_path) -> tuple[Path, Path, Path]:
    return (
        _copy_target(tmp_path, BASE_INGESTION),
        _copy_target(tmp_path, BASE_LIFECYCLE),
        _copy_target(tmp_path, BASE_SHARDING),
    )


def _raw_head_targets(tmp_path) -> tuple[Path, Path, Path]:
    return (
        _copy_raw_head_target(tmp_path, "app/processing/pdf_ingestion.py"),
        _copy_raw_head_target(
            tmp_path,
            "app/processing/pdf_page_presentation_lifecycle_compat.py",
        ),
        _copy_raw_head_target(tmp_path, "app/processing/pdf_provider_sharding.py"),
    )


def _apply_required_predecessors(path: Path) -> None:
    patch_s0_pdf_resource_heartbeat(path)
    patch_provider_runtime_preflight(path)


def _apply_provider_overlay(
    ingestion: Path,
    lifecycle: Path,
    sharding: Path,
) -> None:
    patch_provider_input_presigned_read(
        ingestion,
        presentation_lifecycle_path=lifecycle,
        provider_sharding_path=sharding,
    )


def test_overlay_requires_heartbeat_and_provider_preflight(tmp_path) -> None:
    ingestion, lifecycle, sharding = _targets(tmp_path)
    with pytest.raises(RuntimeError, match="S0 heartbeat"):
        _apply_provider_overlay(ingestion, lifecycle, sharding)

    patch_s0_pdf_resource_heartbeat(ingestion)
    with pytest.raises(RuntimeError, match="provider runtime preflight"):
        _apply_provider_overlay(ingestion, lifecycle, sharding)


def test_overlay_routes_exact_delivery_and_lifecycle_without_touching_provider_wait(
    tmp_path,
) -> None:
    ingestion, lifecycle, sharding = _targets(tmp_path)
    _apply_required_predecessors(ingestion)
    _apply_provider_overlay(ingestion, lifecycle, sharding)
    source = ingestion.read_text(encoding="utf-8")

    assert "provider_delivery = provider_delivery_descriptor(geometry_input)" in source
    assert "reference=provider_delivery.storage_reference" in source
    assert "byte_size=provider_delivery.byte_size" in source
    assert "source_transport_url_factory=provider_source_url_factory" in source
    assert "seconds=PROVIDER_SOURCE_ACCESS_TTL_SECONDS" in source
    assert '"ttl_seconds": PROVIDER_JOB_TTL_SECONDS' in source
    assert "timeout_seconds=ATLAS_PROVIDER_ORCHESTRATION_TIMEOUT_SECONDS" in source
    assert '"ttl_seconds": 3600' not in source
    assert "timeout_seconds=1800" not in source

    # Full render/preprocessing placement and cleanup stay on the pre-existing
    # storage path. Only the true provider delivery object is remote-first.
    assert "provider_input_storage" not in source
    assert "storage=storage" in source
    assert "storage.delete(geometry_input.storage_reference)" in source

    # Existing reliability overlays remain authoritative around provider work.
    assert "await_with_pdf_processing_lease(" in source
    assert "validate_provider_runtime_configuration(settings)" in source


def test_staging_overlay_order_composes_sharding_and_presigned_access(tmp_path) -> None:
    ingestion, lifecycle, sharding = _raw_head_targets(tmp_path)
    patch_provider_transport_sharding_installation(ingestion)
    _apply_required_predecessors(ingestion)
    _apply_provider_overlay(ingestion, lifecycle, sharding)
    source = ingestion.read_text(encoding="utf-8")

    assert "service = ShardingAwareEndToEndProcessingIntegrationService(" in source
    assert "provider_delivery = provider_delivery_descriptor(geometry_input)" in source
    assert "source_transport_url_factory=provider_source_url_factory" in source
    assert "seconds=PROVIDER_SOURCE_ACCESS_TTL_SECONDS" in source
    assert "timeout_seconds=ATLAS_PROVIDER_ORCHESTRATION_TIMEOUT_SECONDS" in source


def test_overlay_cleanup_deletes_distinct_provider_delivery_only_when_safe(tmp_path) -> None:
    ingestion, lifecycle, sharding = _targets(tmp_path)
    _apply_required_predecessors(ingestion)
    _apply_provider_overlay(ingestion, lifecycle, sharding)
    source = ingestion.read_text(encoding="utf-8")

    full_render_delete = source.index(
        "storage.delete(geometry_input.storage_reference)"
    )
    delivery_descriptor = source.index(
        "provider_delivery = provider_delivery_descriptor(geometry_input)",
        full_render_delete,
    )
    distinct_guard = source.index(
        "provider_delivery.storage_reference\n                        != geometry_input.storage_reference",
        delivery_descriptor,
    )
    exists_guard = source.index(
        "storage.exists(provider_delivery.storage_reference)",
        distinct_guard,
    )
    delivery_delete = source.index(
        "storage.delete(provider_delivery.storage_reference)",
        exists_guard,
    )
    deleted_diagnostic = source.index(
        '"PDF_PROVIDER_DELIVERY_INPUT_DELETED"',
        delivery_delete,
    )
    retained_branch = source.index(
        '"PDF_GEOMETRY_PROVIDER_INPUT_RETAINED"',
        deleted_diagnostic,
    )

    # Both temporary objects are cleaned only inside the cleanup-safe branch.
    # The provider delivery must be distinct from the full render and must
    # actually exist before deletion, which keeps sharded/unmaterialized refs safe.
    assert full_render_delete < delivery_descriptor < distinct_guard
    assert distinct_guard < exists_guard < delivery_delete < deleted_diagnostic
    assert deleted_diagnostic < retained_branch


def test_overlay_remote_first_materializes_deferred_subset_and_each_shard(tmp_path) -> None:
    ingestion, lifecycle, sharding = _targets(tmp_path)
    _apply_required_predecessors(ingestion)
    _apply_provider_overlay(ingestion, lifecycle, sharding)

    lifecycle_source = lifecycle.read_text(encoding="utf-8")
    assert "from app.storage.provider_input_access import select_provider_input_storage" in lifecycle_source
    assert "storage = select_provider_input_storage(get_storage_provider())" in lifecycle_source

    sharding_source = sharding.read_text(encoding="utf-8")
    assert "shard_delivery = integration.provider_delivery_descriptor(shard_input)" in sharding_source
    assert "reference=shard_delivery.storage_reference" in sharding_source
    assert "byte_size=shard_delivery.byte_size" in sharding_source
    assert "source_transport_url_factory=shard_source_url_factory" in sharding_source
    assert "seconds=PROVIDER_SOURCE_ACCESS_TTL_SECONDS" in sharding_source


def test_overlay_is_idempotent_and_phase1_can_install_after_it(tmp_path) -> None:
    ingestion, lifecycle, sharding = _targets(tmp_path)
    _apply_required_predecessors(ingestion)
    _apply_provider_overlay(ingestion, lifecycle, sharding)
    once = tuple(
        path.read_text(encoding="utf-8")
        for path in (ingestion, lifecycle, sharding)
    )

    _apply_provider_overlay(ingestion, lifecycle, sharding)
    twice = tuple(
        path.read_text(encoding="utf-8")
        for path in (ingestion, lifecycle, sharding)
    )
    assert twice == once

    patch_s0_v5_phase0_observability(ingestion)
    final = ingestion.read_text(encoding="utf-8")
    assert "install_s0_v5_phase0_observability()" in final
    assert "install_s0_v5_phase1_shared_analysis()" in final
    assert "provider_delivery = provider_delivery_descriptor(geometry_input)" in final


def test_overlay_keeps_original_source_read_separate_from_provider_delivery(tmp_path) -> None:
    ingestion, lifecycle, sharding = _targets(tmp_path)
    _apply_required_predecessors(ingestion)
    _apply_provider_overlay(ingestion, lifecycle, sharding)
    source = ingestion.read_text(encoding="utf-8")

    # Original retained source still comes through the authoritative federated
    # storage path and keeps checksum verification unchanged.
    assert "source_pdf = _read_verified_source_pdf(storage, descriptor)" in source
    assert "result = prepare_geometry_provider_input(" in source
    assert "storage=storage" in source


def test_staging_phase0_entrypoint_installs_provider_access_before_phase0_cache() -> None:
    source = PHASE0_INSTALLER.read_text(encoding="utf-8")
    provider_call = source.index("patch_provider_input_presigned_read()")
    phase0_call = source.index("patch_s0_v5_phase0_observability()", provider_call + 1)

    assert provider_call < phase0_call
