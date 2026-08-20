from __future__ import annotations

from pathlib import Path

from app.routers import health


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
STAGING_SPACE = "carsonhhs/pdf-ocr-service-staging"


def test_runtime_build_revision_reads_exact_staging_revision_file(
    monkeypatch,
    tmp_path,
) -> None:
    revision = "b" * 40
    monkeypatch.setattr(health, "_RUNTIME_ROOT", tmp_path)
    (tmp_path / "staging-revision.txt").write_text(revision + "\n", encoding="utf-8")

    assert health.runtime_build_revision() == revision


def test_runtime_build_revision_rejects_untrusted_or_missing_text(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(health, "_RUNTIME_ROOT", tmp_path)
    assert health.runtime_build_revision() is None

    (tmp_path / "staging-revision.txt").write_text(
        "revision=not-a-sha\nsecret=must-not-leak\n",
        encoding="utf-8",
    )
    assert health.runtime_build_revision() is None


def test_shared_staging_space_has_one_authoritative_writer() -> None:
    writers = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if STAGING_SPACE in path.read_text(encoding="utf-8"):
            writers.append(path.name)

    assert writers == ["staging-integration-ci.yml"]


def test_staging_deploy_uses_verified_artifact_from_integration() -> None:
    source = (WORKFLOWS / "staging-integration-ci.yml").read_text(encoding="utf-8")

    assert "artifact_verification:" in source
    assert "needs: integration" in source
    assert "deploy:" in source
    assert "needs: artifact_verification" in source
    assert "github.event_name == 'push'" in source
    assert "github.ref == 'refs/heads/staging'" in source
    assert "actions/upload-artifact@v4" in source
    assert source.count("actions/download-artifact@v4") >= 2
    assert "atlas-staging-tested-${{ github.sha }}" in source
    assert "staging-revision.txt" in source
    assert "refs/heads/staging" in source
    assert "payload.get('revision') == sha" in source
    assert "expected_revision={sha}" in source


def test_staging_artifact_verification_checks_provider_delivery_contract() -> None:
    source = (WORKFLOWS / "staging-integration-ci.yml").read_text(encoding="utf-8")

    verification = source[source.index("artifact_verification:") : source.index("\n  deploy:")]
    for module in (
        "app/processing/pdf_ingestion.py",
        "app/processing/pdf_provider_sharding.py",
        "app/processing/pdf_provider_sharding_compat.py",
        "app/processing/pdf_page_presentation_lifecycle_compat.py",
        "app/processing/provider_input_source_access.py",
        "app/processing/provider_lifecycle_policy.py",
    ):
        assert module in verification

    for marker in (
        "provider_delivery_descriptor(geometry_input)",
        "source_transport_url_factory=provider_source_url_factory",
        "ShardingAwareEndToEndProcessingIntegrationService(",
        "shard_delivery = integration.provider_delivery_descriptor(shard_input)",
        "source_transport_url_factory=shard_source_url_factory",
        "select_provider_input_storage(get_storage_provider())",
        "PDF_PROVIDER_DELIVERY_READY",
        "PDF_PROVIDER_SHARDING_DECISION",
    ):
        assert marker in verification


def test_staging_provider_runtime_installer_includes_presigned_delivery() -> None:
    workflow = (WORKFLOWS / "staging-integration-ci.yml").read_text(encoding="utf-8")
    installer = (
        REPO_ROOT / "scripts" / "apply_provider_runtime_preflight.py"
    ).read_text(encoding="utf-8")

    heartbeat = "python scripts/apply_s0_pdf_resource_heartbeat.py"
    preflight = "python scripts/apply_provider_runtime_preflight.py"
    sharding = "python scripts/apply_provider_transport_sharding.py"

    assert heartbeat in workflow
    assert preflight in workflow
    assert sharding in workflow
    assert workflow.index(sharding) < workflow.index(preflight)
    assert workflow.index(heartbeat) < workflow.index(preflight)
    assert "patch_provider_input_presigned_read" in installer
    assert "_presigned_lifecycle_installer" in installer
    assert installer.index("patch_provider_runtime_preflight()") < installer.index(
        "_presigned_lifecycle_installer()()"
    )


def test_overlay_installers_do_not_depend_on_provider_wait_call_shape() -> None:
    for script_name in (
        "apply_provider_transport_sharding.py",
        "apply_opencv_v4_modal_bridge.py",
    ):
        source = (REPO_ROOT / "scripts" / script_name).read_text(encoding="utf-8")
        required_start = source.index("required = (")
        required_end = source.index(")", required_start)
        required_block = source[required_start:required_end]
        assert "outcome = await service.process(request)" not in required_block


def test_deprecated_staging_writers_cannot_write_shared_space() -> None:
    for workflow_name in ("deploy-staging-branch.yml", "deploy-staging.yml"):
        source = (WORKFLOWS / workflow_name).read_text(encoding="utf-8")
        assert STAGING_SPACE not in source
        assert "DEPRECATED" in source
