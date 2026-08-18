from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


_REFINEMENT_ENV_NAMES = (
    "PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY",
    "PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL",
    "PDF_STRUCTURE_REFINEMENT_OPENAI_ENDPOINT",
    "PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS",
    "PDF_STRUCTURE_REFINEMENT_MAX_ATTEMPTS",
    "PDF_STRUCTURE_REFINEMENT_INITIAL_BACKOFF_SECONDS",
    "PDF_STRUCTURE_REFINEMENT_MAX_BACKOFF_SECONDS",
    "PDF_STRUCTURE_REFINEMENT_MAX_CONCURRENT_BATCHES",
    "PDF_STRUCTURE_REFINEMENT_GLOBAL_MAX_CONCURRENT_BATCHES",
    "PDF_STRUCTURE_REFINEMENT_MAX_PAGES_PER_BATCH",
    "PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_DIMENSION_PIXELS",
    "PDF_STRUCTURE_REFINEMENT_JPEG_QUALITY",
    "PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_BYTES",
)

_PROCESS_SMOKE_SCRIPT = r"""
import json
from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as client:
    health = client.get('/api/v1/health')
    config = client.get('/api/v1/health/config')
    health.raise_for_status()
    config.raise_for_status()
    print(json.dumps({'health': health.json(), 'config': config.json()}, sort_keys=True))
"""


def _subprocess_env(database_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    for name in _REFINEMENT_ENV_NAMES:
        env.pop(name, None)
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{database_path}",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def _run_application_process(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _PROCESS_SMOKE_SCRIPT],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=45,
        check=False,
    )


def test_application_process_starts_with_valid_refinement_config_and_serves_health(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "valid-startup.db"
    secret = "process-smoke-secret-must-not-leak"
    endpoint = "https://provider.invalid/v1/responses?token=must-not-leak"
    env = _subprocess_env(database_path)
    env.update(
        {
            "PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY": secret,
            "PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL": "process-smoke-model",
            "PDF_STRUCTURE_REFINEMENT_OPENAI_ENDPOINT": endpoint,
            "PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS": "17",
            "PDF_STRUCTURE_REFINEMENT_MAX_ATTEMPTS": "2",
            "PDF_STRUCTURE_REFINEMENT_INITIAL_BACKOFF_SECONDS": "0.25",
            "PDF_STRUCTURE_REFINEMENT_MAX_BACKOFF_SECONDS": "1.5",
            "PDF_STRUCTURE_REFINEMENT_MAX_CONCURRENT_BATCHES": "1",
            "PDF_STRUCTURE_REFINEMENT_GLOBAL_MAX_CONCURRENT_BATCHES": "2",
            "PDF_STRUCTURE_REFINEMENT_MAX_PAGES_PER_BATCH": "3",
            "PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_DIMENSION_PIXELS": "900",
            "PDF_STRUCTURE_REFINEMENT_JPEG_QUALITY": "65",
            "PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_BYTES": "400000",
        }
    )

    result = _run_application_process(env)

    assert result.returncode == 0, result.stderr
    assert database_path.exists()
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["health"] == {"status": "healthy", "service": "pdf-ocr-service"}
    assert payload["config"]["enabled"] is True
    assert payload["config"]["model"] == "process-smoke-model"
    assert payload["config"]["timeout_seconds"] == 17.0
    assert payload["config"]["image_policy"] == {
        "max_pages_per_batch": 3,
        "max_dimension_pixels": 900,
        "jpeg_quality": 65,
        "max_image_bytes": 400000,
    }
    combined_output = result.stdout + result.stderr
    assert "PDF_STRUCTURE_REFINEMENT_CONFIG" in combined_output
    assert secret not in combined_output
    assert endpoint not in combined_output
    assert "must-not-leak" not in combined_output


def test_application_process_rejects_invalid_refinement_config_before_database_init(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "invalid-startup.db"
    env = _subprocess_env(database_path)
    env["PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS"] = "0"

    result = _run_application_process(env)

    assert result.returncode != 0
    assert "PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS must be a positive number" in result.stderr
    assert "Database initialized" not in result.stderr
    assert "Database schema upgraded to Alembic head" not in result.stderr
    assert not database_path.exists()
