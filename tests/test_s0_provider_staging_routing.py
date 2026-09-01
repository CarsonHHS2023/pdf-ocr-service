from __future__ import annotations

from pathlib import Path

import pytest

from app.s0_provider_staging_routing import (
    S0_PROVIDER_STAGING_BASE_URL,
    exact_staging_artifact,
    resolve_s0_provider_base_url,
)
from scripts.apply_s0_provider_staging_routing import (
    ensure_authoritative_staging_revision_marker,
    patch_pdf_ingestion,
    patch_processing_operator,
)


def test_non_staging_runtime_preserves_configured_provider_url(tmp_path: Path) -> None:
    marker = tmp_path / "staging-revision.txt"
    configured = "https://provider-production.example"

    assert exact_staging_artifact(marker) is False
    assert resolve_s0_provider_base_url(configured, revision_path=marker) == configured


def test_valid_exact_staging_marker_selects_isolated_provider_preview(tmp_path: Path) -> None:
    marker = tmp_path / "staging-revision.txt"
    marker.write_text("a" * 40 + "\n", encoding="utf-8")

    assert exact_staging_artifact(marker) is True
    assert (
        resolve_s0_provider_base_url(
            "https://provider-production.example",
            revision_path=marker,
        )
        == S0_PROVIDER_STAGING_BASE_URL
    )
    assert "paddle-vl-api-s0-staging" in S0_PROVIDER_STAGING_BASE_URL


def test_invalid_or_uppercase_marker_never_enables_staging_route(tmp_path: Path) -> None:
    marker = tmp_path / "staging-revision.txt"
    for value in ("short", "A" * 40, "g" * 40, "a" * 41):
        marker.write_text(value, encoding="utf-8")
        assert exact_staging_artifact(marker) is False
        assert (
            resolve_s0_provider_base_url(
                "https://provider-production.example",
                revision_path=marker,
            )
            == "https://provider-production.example"
        )


def test_empty_non_staging_configuration_stays_empty(tmp_path: Path) -> None:
    marker = tmp_path / "missing-revision.txt"
    assert resolve_s0_provider_base_url(None, revision_path=marker) == ""


def test_authoritative_staging_ci_writes_exact_marker_before_runtime_contracts(tmp_path: Path) -> None:
    marker = tmp_path / "staging-revision.txt"
    sha = "b" * 40
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_WORKFLOW": "Staging Backend Integration CI",
        "GITHUB_SHA": sha,
    }

    assert ensure_authoritative_staging_revision_marker(revision_path=marker, env=env) is True
    assert marker.read_text(encoding="utf-8") == sha + "\n"
    assert exact_staging_artifact(marker) is True
    assert (
        resolve_s0_provider_base_url(
            "https://provider-production.example",
            revision_path=marker,
        )
        == S0_PROVIDER_STAGING_BASE_URL
    )
    # Reapplying the authoritative overlay must preserve the same exact marker.
    assert ensure_authoritative_staging_revision_marker(revision_path=marker, env=env) is True
    assert marker.read_text(encoding="utf-8") == sha + "\n"


def test_non_authoritative_ci_never_writes_staging_marker(tmp_path: Path) -> None:
    marker = tmp_path / "staging-revision.txt"
    for env in (
        {},
        {
            "GITHUB_ACTIONS": "true",
            "GITHUB_WORKFLOW": "S0 Baseline CI",
            "GITHUB_SHA": "c" * 40,
        },
        {
            "GITHUB_ACTIONS": "false",
            "GITHUB_WORKFLOW": "Staging Backend Integration CI",
            "GITHUB_SHA": "c" * 40,
        },
    ):
        assert ensure_authoritative_staging_revision_marker(revision_path=marker, env=env) is False
        assert marker.exists() is False


def test_authoritative_staging_marker_fails_closed_on_sha_mismatch(tmp_path: Path) -> None:
    marker = tmp_path / "staging-revision.txt"
    marker.write_text("d" * 40 + "\n", encoding="utf-8")
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_WORKFLOW": "Staging Backend Integration CI",
        "GITHUB_SHA": "e" * 40,
    }

    with pytest.raises(RuntimeError, match="disagrees"):
        ensure_authoritative_staging_revision_marker(revision_path=marker, env=env)


def test_pdf_routing_overlay_is_idempotent_and_does_not_embed_credentials(tmp_path: Path) -> None:
    source = '''from app.config import settings\n\n        _diagnostic(\n            "PDF_PROVIDER_CONFIGURATION",\n            document_id=document_id,\n            processing_attempt_id=ids.processing_attempt_id,\n            base_url_configured=bool(settings.paddle_vl_api_base_url),\n            bearer_token_configured=bool(settings.paddle_vl_api_bearer_token),\n            public_origin_configured=bool(settings.public_source_transport_origin),\n        )\n        client = PaddleVLClient(\n            PaddleVLClientConfig(\n                base_url=settings.paddle_vl_api_base_url or "",\n                bearer_token=settings.paddle_vl_api_bearer_token or "",\n'''
    path = tmp_path / "pdf_ingestion.py"
    path.write_text(source, encoding="utf-8")

    patch_pdf_ingestion(path)
    first = path.read_text(encoding="utf-8")
    patch_pdf_ingestion(path)
    second = path.read_text(encoding="utf-8")

    assert first == second
    assert "resolve_s0_provider_base_url" in second
    assert "base_url=provider_base_url" in second
    assert "bearer_token=settings.paddle_vl_api_bearer_token or \"\"" in second
    assert "paddle-vl-api-s0-staging-fastapi-app.modal.run" not in second


def test_processing_operator_uses_same_exact_staging_resolver(tmp_path: Path) -> None:
    source = '''from app.config import settings\n\nasync def create_operator_integration_dependency():\n    client = None\n    try:\n        config = PaddleVLClientConfig(\n            base_url=settings.paddle_vl_api_base_url or "",\n            bearer_token=settings.paddle_vl_api_bearer_token or "",\n            timeout_seconds=settings.paddle_vl_api_timeout_seconds,\n            default_result_profile=settings.paddle_vl_api_default_result_profile,\n        )\n'''
    path = tmp_path / "processing_operator.py"
    path.write_text(source, encoding="utf-8")

    patch_processing_operator(path)
    first = path.read_text(encoding="utf-8")
    patch_processing_operator(path)
    second = path.read_text(encoding="utf-8")

    assert first == second
    assert "from app.s0_provider_staging_routing import resolve_s0_provider_base_url" in second
    assert "provider_base_url = resolve_s0_provider_base_url(" in second
    assert "base_url=provider_base_url" in second
    assert "bearer_token=settings.paddle_vl_api_bearer_token or \"\"" in second
    assert "paddle-vl-api-s0-staging-fastapi-app.modal.run" not in second


def test_authoritative_workflow_runs_phase0_composer_before_runtime_contracts() -> None:
    workflow = Path(".github/workflows/staging-integration-ci.yml").read_text(encoding="utf-8")
    phase0_index = workflow.index("python scripts/apply_s0_v5_phase0_observability.py")
    runtime_contract_index = workflow.index("- name: Run production-equivalent staging contracts")
    artifact_index = workflow.index("- name: Prepare exact tested staging artifact")

    assert phase0_index < runtime_contract_index < artifact_index
