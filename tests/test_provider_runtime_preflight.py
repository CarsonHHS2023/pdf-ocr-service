from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.processing.pdf_provider_runtime_preflight import (
    PdfProviderRuntimeConfigurationError,
    provider_runtime_configuration_status,
    validate_provider_runtime_configuration,
)
from scripts import apply_provider_input_presigned_read as presigned_installer
from scripts import apply_provider_runtime_preflight as runtime_installer
from scripts.apply_provider_runtime_preflight import patch_provider_runtime_preflight


def _settings(**overrides):
    values = {
        "paddle_vl_api_base_url": "https://provider.example",
        "paddle_vl_api_bearer_token": "secret",
        "public_source_transport_origin": "https://atlas.example",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_provider_runtime_configuration_requires_all_three_inputs() -> None:
    status = provider_runtime_configuration_status(
        _settings(
            paddle_vl_api_base_url=None,
            public_source_transport_origin=None,
        )
    )

    assert status.ready is False
    assert status.base_url_configured is False
    assert status.bearer_token_configured is True
    assert status.public_origin_configured is False
    assert status.missing_fields == (
        "PADDLE_VL_API_BASE_URL",
        "ATLAS_PUBLIC_SOURCE_TRANSPORT_ORIGIN",
    )


def test_provider_runtime_configuration_validation_is_secret_safe() -> None:
    with pytest.raises(PdfProviderRuntimeConfigurationError) as raised:
        validate_provider_runtime_configuration(
            _settings(paddle_vl_api_bearer_token="")
        )

    assert str(raised.value) == "pdf_provider_runtime_configuration_missing"
    assert raised.value.safe_message == "PDF provider configuration is unavailable"
    assert raised.value.status.missing_fields == ("PADDLE_VL_API_BEARER_TOKEN",)
    assert "secret" not in str(raised.value)


def test_provider_runtime_configuration_accepts_complete_settings() -> None:
    validate_provider_runtime_configuration(_settings())


def test_preflight_overlay_is_idempotent_and_precedes_storage(tmp_path: Path) -> None:
    path = tmp_path / "pdf_ingestion.py"
    path.write_text(
        "from app.storage.models import StorageReference\n"
        "sync_pdf_processing_run_terminal = object()\n\n"
        "async def process_pdf_document_background():\n"
        "    storage = get_storage_provider()\n",
        encoding="utf-8",
    )

    patch_provider_runtime_preflight(path)
    once = path.read_text(encoding="utf-8")
    patch_provider_runtime_preflight(path)
    twice = path.read_text(encoding="utf-8")

    assert once == twice
    assert once.count("validate_provider_runtime_configuration(settings)") == 1
    assert once.index("validate_provider_runtime_configuration(settings)") < once.index(
        "storage = get_storage_provider()"
    )


def test_cli_installer_composes_preflight_then_presigned_lifecycle(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        runtime_installer,
        "patch_provider_runtime_preflight",
        lambda: calls.append("preflight"),
    )
    monkeypatch.setattr(
        presigned_installer,
        "patch_provider_input_presigned_read",
        lambda: calls.append("presigned"),
    )

    runtime_installer.main()

    assert calls == ["preflight", "presigned"]
