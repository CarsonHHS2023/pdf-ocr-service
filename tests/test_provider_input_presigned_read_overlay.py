from __future__ import annotations

from pathlib import Path

import pytest

from scripts.apply_provider_input_presigned_read import (
    patch_provider_input_presigned_read,
)
from scripts.apply_provider_runtime_preflight import patch_provider_runtime_preflight
from scripts.apply_s0_pdf_resource_heartbeat import patch_s0_pdf_resource_heartbeat
from scripts.apply_s0_v5_phase0_observability import patch_s0_v5_phase0_observability


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_INGESTION = REPO_ROOT / "app" / "processing" / "pdf_ingestion.py"
PHASE0_INSTALLER = REPO_ROOT / "scripts" / "apply_s0_v5_phase0_observability.py"


def _copy_ingestion(tmp_path) -> Path:
    path = tmp_path / "pdf_ingestion.py"
    path.write_text(BASE_INGESTION.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _apply_required_predecessors(path: Path) -> None:
    patch_s0_pdf_resource_heartbeat(path)
    patch_provider_runtime_preflight(path)


def test_overlay_requires_heartbeat_and_provider_preflight(tmp_path) -> None:
    path = _copy_ingestion(tmp_path)
    with pytest.raises(RuntimeError, match="S0 heartbeat"):
        patch_provider_input_presigned_read(path)

    patch_s0_pdf_resource_heartbeat(path)
    with pytest.raises(RuntimeError, match="provider runtime preflight"):
        patch_provider_input_presigned_read(path)


def test_overlay_routes_provider_input_and_lifecycle_without_touching_provider_wait(tmp_path) -> None:
    path = _copy_ingestion(tmp_path)
    _apply_required_predecessors(path)
    patch_provider_input_presigned_read(path)
    source = path.read_text(encoding="utf-8")

    assert "provider_input_storage = select_provider_input_storage(storage)" in source
    assert "storage=provider_input_storage" in source
    assert source.count("provider_input_storage=provider_input_storage") == 2
    assert "build_provider_input_source_url_factory(" in source
    assert "source_transport_url_factory=provider_source_url_factory" in source
    assert "seconds=PROVIDER_SOURCE_ACCESS_TTL_SECONDS" in source
    assert '"ttl_seconds": PROVIDER_JOB_TTL_SECONDS' in source
    assert "timeout_seconds=ATLAS_PROVIDER_ORCHESTRATION_TIMEOUT_SECONDS" in source
    assert '"ttl_seconds": 3600' not in source
    assert "timeout_seconds=1800" not in source
    assert "provider_input_storage.delete(geometry_input.storage_reference)" in source

    # Existing reliability overlays remain authoritative around provider work.
    assert "await_with_pdf_processing_lease(" in source
    assert "validate_provider_runtime_configuration(settings)" in source


def test_overlay_is_idempotent_and_phase1_can_install_after_it(tmp_path) -> None:
    path = _copy_ingestion(tmp_path)
    _apply_required_predecessors(path)
    patch_provider_input_presigned_read(path)
    once = path.read_text(encoding="utf-8")

    patch_provider_input_presigned_read(path)
    twice = path.read_text(encoding="utf-8")
    assert twice == once

    patch_s0_v5_phase0_observability(path)
    final = path.read_text(encoding="utf-8")
    assert "install_s0_v5_phase0_observability()" in final
    assert "install_s0_v5_phase1_shared_analysis()" in final
    assert "provider_input_storage = select_provider_input_storage(storage)" in final


def test_overlay_keeps_source_read_and_provider_output_storage_separate(tmp_path) -> None:
    path = _copy_ingestion(tmp_path)
    _apply_required_predecessors(path)
    patch_provider_input_presigned_read(path)
    source = path.read_text(encoding="utf-8")

    # Original retained source still comes through the authoritative federated
    # storage path and keeps checksum verification unchanged.
    assert "source_pdf = _read_verified_source_pdf(storage, descriptor)" in source
    # Only the already-produced derived PDF is routed through remote-first output.
    assert "result = prepare_geometry_provider_input(" in source
    assert "storage=provider_input_storage" in source


def test_staging_phase0_entrypoint_installs_provider_access_before_phase0_cache() -> None:
    source = PHASE0_INSTALLER.read_text(encoding="utf-8")
    provider_call = source.index("patch_provider_input_presigned_read()")
    phase0_call = source.index("patch_s0_v5_phase0_observability()", provider_call + 1)

    assert provider_call < phase0_call
