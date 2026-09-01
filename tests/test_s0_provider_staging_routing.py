from __future__ import annotations

from pathlib import Path

from app.s0_provider_staging_routing import (
    S0_PROVIDER_STAGING_BASE_URL,
    exact_staging_artifact,
    resolve_s0_provider_base_url,
)
from scripts.apply_s0_provider_staging_routing import patch_pdf_ingestion


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


def test_routing_overlay_is_idempotent_and_does_not_embed_credentials(tmp_path: Path) -> None:
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
