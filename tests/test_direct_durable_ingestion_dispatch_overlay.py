from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from scripts.apply_direct_durable_ingestion_dispatch import patch_direct_durable_dispatch


def _raw_direct_source() -> str:
    completed = subprocess.run(
        ["git", "show", "HEAD:app/routers/direct_upload.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_direct_overlay_installs_durable_acceptance_before_storage_runtime(tmp_path: Path) -> None:
    path = tmp_path / "direct_upload.py"
    source = _raw_direct_source()
    assert "DIRECT_UPLOAD_COMPLETE_IDEMPOTENT" not in source
    path.write_text(source, encoding="utf-8")

    patch_direct_durable_dispatch(path)
    transformed = path.read_text(encoding="utf-8")

    assert "new_pdf_ingestion_ids" not in transformed
    assert "process_pdf_document_background" not in transformed
    assert "direct_acceptance_key" in transformed
    assert "commit_retained_ingestion" in transformed
    assert "run_ingestion_dispatch" in transformed
    assert "DIRECT_UPLOAD_COMPLETE_IDEMPOTENT" in transformed
    assert "DIRECT_UPLOAD_LEGACY_ACCEPTANCE_WITHOUT_DISPATCH" in transformed

    complete_start = transformed.index(
        '@router.post("/{upload_id}/complete", response_model=UploadBookResponse)'
    )
    complete = transformed[complete_start:]
    assert complete.index("claims = _claims_from_token") < complete.index(
        "existing = find_accepted_ingestion"
    )
    assert complete.index("existing = find_accepted_ingestion") < complete.index(
        "provider, _runtime_secret = _runtime()"
    )
    assert complete.index("commit_retained_ingestion") < complete.index(
        "background_tasks.add_task(run_ingestion_dispatch, accepted.dispatch_id)"
    )

    first = transformed
    patch_direct_durable_dispatch(path)
    assert path.read_text(encoding="utf-8") == first
    compile(first, str(path), "exec")


def test_direct_overlay_fails_closed_when_completion_anchor_drifts(tmp_path: Path) -> None:
    path = tmp_path / "direct_upload.py"
    source = _raw_direct_source()
    source = source.replace(
        '@router.post("/{upload_id}/complete", response_model=UploadBookResponse)\ndef complete_direct_upload_session(\n',
        '@router.post("/{upload_id}/complete", response_model=UploadBookResponse)\ndef changed_complete_direct_upload_session(\n',
        1,
    )
    path.write_text(source, encoding="utf-8")

    with pytest.raises(RuntimeError, match="direct-upload complete anchor"):
        patch_direct_durable_dispatch(path)
