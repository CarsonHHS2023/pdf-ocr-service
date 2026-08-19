from __future__ import annotations

from pathlib import Path

import pytest

from scripts.apply_durable_ingestion_dispatch import patch_resumable_durable_dispatch


def _raw_resumable_source() -> str:
    return Path("app/routers/resumable_upload.py").read_text(encoding="utf-8")


def test_resumable_overlay_installs_durable_acceptance_before_spool_lookup(tmp_path: Path):
    path = tmp_path / "resumable_upload.py"
    source = _raw_resumable_source()
    if "RESUMABLE_UPLOAD_COMPLETE_IDEMPOTENT" in source:
        pytest.skip("checkout is already overlay-transformed")
    path.write_text(source, encoding="utf-8")

    patch_resumable_durable_dispatch(path)
    transformed = path.read_text(encoding="utf-8")

    assert "from app.routers.ocr import upload_file as _accept_upload_file" not in transformed
    assert "resumable_acceptance_key" in transformed
    assert "retain_and_commit_ingestion" in transformed
    assert "run_ingestion_dispatch" in transformed
    assert "RESUMABLE_UPLOAD_COMPLETE_IDEMPOTENT" in transformed
    assert transformed.index("existing = find_accepted_ingestion") < transformed.index("metadata = _load_metadata")
    assert "background_tasks.add_task(run_ingestion_dispatch, existing.dispatch_id)" in transformed
    assert "background_tasks.add_task(run_ingestion_dispatch, accepted.dispatch_id)" in transformed
    assert "cleanup_on_db_failure=False" in transformed

    first = transformed
    patch_resumable_durable_dispatch(path)
    assert path.read_text(encoding="utf-8") == first
    compile(first, str(path), "exec")


def test_resumable_overlay_fails_closed_when_completion_anchor_drifts(tmp_path: Path):
    path = tmp_path / "resumable_upload.py"
    source = _raw_resumable_source()
    if "RESUMABLE_UPLOAD_COMPLETE_IDEMPOTENT" in source:
        pytest.skip("checkout is already overlay-transformed")
    source = source.replace(
        '@router.post("/{upload_id}/complete", response_model=UploadBookResponse)\nasync def complete_upload_session(\n',
        '@router.post("/{upload_id}/complete", response_model=UploadBookResponse)\nasync def changed_complete_upload_session(\n',
        1,
    )
    path.write_text(source, encoding="utf-8")

    with pytest.raises(RuntimeError, match="complete anchor"):
        patch_resumable_durable_dispatch(path)
