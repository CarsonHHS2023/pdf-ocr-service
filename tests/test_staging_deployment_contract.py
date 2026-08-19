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


def test_staging_deploy_uses_same_artifact_that_passed_integration() -> None:
    source = (WORKFLOWS / "staging-integration-ci.yml").read_text(encoding="utf-8")

    assert "deploy:" in source
    assert "needs: integration" in source
    assert "github.event_name == 'push'" in source
    assert "github.ref == 'refs/heads/staging'" in source
    assert "actions/upload-artifact@v4" in source
    assert "actions/download-artifact@v4" in source
    assert "atlas-staging-tested-${{ github.sha }}" in source
    assert "staging-revision.txt" in source
    assert "refs/heads/staging" in source
    assert "payload.get('revision') == sha" in source
    assert "expected_revision={sha}" in source


def test_deprecated_staging_writers_cannot_write_shared_space() -> None:
    for workflow_name in ("deploy-staging-branch.yml", "deploy-staging.yml"):
        source = (WORKFLOWS / workflow_name).read_text(encoding="utf-8")
        assert STAGING_SPACE not in source
        assert "DEPRECATED" in source
