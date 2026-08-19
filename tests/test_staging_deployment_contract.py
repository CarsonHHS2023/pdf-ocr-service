from __future__ import annotations

from pathlib import Path

from app.routers import health


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
STAGING_SPACE = "carsonhhs/pdf-ocr-service-staging"


def test_runtime_build_revision_prefers_valid_environment(monkeypatch, tmp_path) -> None:
    revision = "a" * 40
    monkeypatch.setattr(health, "_RUNTIME_ROOT", tmp_path)
    monkeypatch.setenv("ATLAS_BUILD_REVISION", revision.upper())

    assert health.runtime_build_revision() == revision


def test_runtime_build_revision_reads_exact_staging_revision_file(
    monkeypatch,
    tmp_path,
) -> None:
    revision = "b" * 40
    monkeypatch.setattr(health, "_RUNTIME_ROOT", tmp_path)
    monkeypatch.delenv("ATLAS_BUILD_REVISION", raising=False)
    (tmp_path / "staging-revision.txt").write_text(revision + "\n", encoding="utf-8")

    assert health.runtime_build_revision() == revision


def test_runtime_build_revision_rejects_untrusted_text(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(health, "_RUNTIME_ROOT", tmp_path)
    monkeypatch.setenv("ATLAS_BUILD_REVISION", "staging")
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

    assert writers == ["deploy-staging-branch.yml"]


def test_staging_deploy_is_gated_by_exact_successful_integration_head() -> None:
    source = (WORKFLOWS / "deploy-staging-branch.yml").read_text(encoding="utf-8")

    assert "workflow_run:" in source
    assert "workflows: [Staging Backend Integration CI]" in source
    assert "branches: [staging]" in source
    assert "types: [completed]" in source
    assert "github.event.workflow_run.conclusion == 'success'" in source
    assert "github.event.workflow_run.head_sha" in source
    assert "refs/heads/staging" in source
    assert "staging-revision.txt" in source
    assert "payload.get('revision')" in source
    assert "payload.get('revision') != sha" in source


def test_legacy_main_candidate_workflow_cannot_write_shared_staging_space() -> None:
    source = (WORKFLOWS / "deploy-staging.yml").read_text(encoding="utf-8")

    assert STAGING_SPACE not in source
    assert "DEPRECATED" in source
