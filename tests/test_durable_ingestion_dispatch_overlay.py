from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from scripts.apply_direct_durable_ingestion_dispatch import patch_direct_durable_dispatch
from scripts.apply_durable_ingestion_dispatch import patch_resumable_durable_dispatch
from scripts.apply_legacy_durable_ingestion_dispatch import patch_legacy_durable_dispatch


def _raw_source(path: str) -> str:
    """Read committed raw source even after CI transformed the workspace."""
    completed = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_resumable_overlay_installs_durable_acceptance_before_spool_lookup(tmp_path: Path):
    path = tmp_path / "resumable_upload.py"
    source = _raw_source("app/routers/resumable_upload.py")
    assert "RESUMABLE_UPLOAD_COMPLETE_IDEMPOTENT" not in source
    path.write_text(source, encoding="utf-8")

    patch_resumable_durable_dispatch(path)
    transformed = path.read_text(encoding="utf-8")

    assert "from app.routers.ocr import upload_file as _accept_upload_file" not in transformed
    assert "resumable_acceptance_key" in transformed
    assert "retain_and_commit_ingestion" in transformed
    assert "run_ingestion_dispatch" in transformed
    assert "RESUMABLE_UPLOAD_COMPLETE_IDEMPOTENT" in transformed

    complete_start = transformed.index(
        '@router.post("/{upload_id}/complete", response_model=UploadBookResponse)'
    )
    complete_source = transformed[complete_start:]
    assert complete_source.index("existing = find_accepted_ingestion") < complete_source.index(
        "metadata = _load_metadata"
    )
    assert "background_tasks.add_task(run_ingestion_dispatch, existing.dispatch_id)" in complete_source
    assert "background_tasks.add_task(run_ingestion_dispatch, accepted.dispatch_id)" in complete_source
    assert "cleanup_on_db_failure=False" in complete_source

    first = transformed
    patch_resumable_durable_dispatch(path)
    assert path.read_text(encoding="utf-8") == first
    compile(first, str(path), "exec")


def test_resumable_overlay_fails_closed_when_completion_anchor_drifts(tmp_path: Path):
    path = tmp_path / "resumable_upload.py"
    source = _raw_source("app/routers/resumable_upload.py")
    assert "RESUMABLE_UPLOAD_COMPLETE_IDEMPOTENT" not in source
    source = source.replace(
        '@router.post("/{upload_id}/complete", response_model=UploadBookResponse)\nasync def complete_upload_session(\n',
        '@router.post("/{upload_id}/complete", response_model=UploadBookResponse)\nasync def changed_complete_upload_session(\n',
        1,
    )
    path.write_text(source, encoding="utf-8")

    with pytest.raises(RuntimeError, match="complete anchor"):
        patch_resumable_durable_dispatch(path)


def test_direct_overlay_installs_durable_acceptance_before_storage_runtime(tmp_path: Path) -> None:
    path = tmp_path / "direct_upload.py"
    source = _raw_source("app/routers/direct_upload.py")
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
        "existing = _lookup_durable_acceptance()"
    )
    assert complete.index("existing = _lookup_durable_acceptance()") < complete.index(
        "provider, _runtime_secret = _runtime()"
    )
    assert complete.index("commit_retained_ingestion") < complete.index(
        "background_tasks.add_task(run_ingestion_dispatch, accepted.dispatch_id)"
    )

    object_missing = complete[
        complete.index("except ObjectNotFound as exc:") : complete.index(
            "except IntegrityMismatch as exc:"
        )
    ]
    assert "winner = _lookup_durable_acceptance()" in object_missing
    assert "return _return_durable_existing(winner)" in object_missing

    storage_failure = complete[
        complete.index("except StorageError as exc:") : complete.index(
            "publish_ms = (time.perf_counter() - publish_started)"
        )
    ]
    assert "winner = _lookup_durable_acceptance()" in storage_failure
    assert "return _return_durable_existing(winner)" in storage_failure

    first = transformed
    patch_direct_durable_dispatch(path)
    assert path.read_text(encoding="utf-8") == first
    compile(first, str(path), "exec")


def test_direct_overlay_fails_closed_when_completion_anchor_drifts(tmp_path: Path) -> None:
    path = tmp_path / "direct_upload.py"
    source = _raw_source("app/routers/direct_upload.py")
    source = source.replace(
        '@router.post("/{upload_id}/complete", response_model=UploadBookResponse)\ndef complete_direct_upload_session(\n',
        '@router.post("/{upload_id}/complete", response_model=UploadBookResponse)\ndef changed_complete_direct_upload_session(\n',
        1,
    )
    path.write_text(source, encoding="utf-8")

    with pytest.raises(RuntimeError, match="direct-upload complete anchor"):
        patch_direct_durable_dispatch(path)


def test_legacy_overlay_commits_dispatch_before_background_kick(tmp_path: Path) -> None:
    path = tmp_path / "ocr.py"
    source = _raw_source("app/routers/ocr.py")
    assert "legacy_acceptance_key" not in source
    path.write_text(source, encoding="utf-8")

    patch_legacy_durable_dispatch(path)
    transformed = path.read_text(encoding="utf-8")

    assert "new_pdf_ingestion_ids" not in transformed
    assert "process_pdf_document_background" not in transformed
    assert "new_txt_ingestion_ids" not in transformed
    assert "process_txt_document_background" not in transformed
    assert "legacy_acceptance_key" in transformed
    assert "new_dispatch_payload" in transformed
    assert "run_ingestion_dispatch" in transformed

    upload_start = transformed.index('@router.post("/upload", response_model=UploadBookResponse)')
    next_route = transformed.index(
        '@router.post("/ocr/{task_id}", response_model=OCRProcessResponse)',
        upload_start,
    )
    upload = transformed[upload_start:next_route]
    assert upload.count("commit_retained_ingestion(") == 2
    assert upload.count(
        "background_tasks.add_task(run_ingestion_dispatch, accepted.dispatch_id)"
    ) == 2
    assert upload.index("dispatch_payload = new_dispatch_payload(file_type)") < upload.index(
        "commit_retained_ingestion("
    )
    assert '@router.post("/ocr/{task_id}", response_model=OCRProcessResponse)' in transformed

    first = transformed
    patch_legacy_durable_dispatch(path)
    assert path.read_text(encoding="utf-8") == first
    compile(first, str(path), "exec")


def test_legacy_overlay_fails_closed_when_next_route_anchor_drifts(tmp_path: Path) -> None:
    path = tmp_path / "ocr.py"
    source = _raw_source("app/routers/ocr.py")
    source = source.replace(
        '@router.post("/ocr/{task_id}", response_model=OCRProcessResponse)\n',
        '@router.post("/changed-ocr/{task_id}", response_model=OCRProcessResponse)\n',
        1,
    )
    path.write_text(source, encoding="utf-8")

    with pytest.raises(RuntimeError, match="legacy upload end anchor"):
        patch_legacy_durable_dispatch(path)


def test_legacy_txt_acceptance_survives_task_registration_crash(tmp_path: Path) -> None:
    import asyncio

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models import Base, Document, SourceFile
    from app.processing.ingestion_dispatch_model import IngestionDispatch
    from app.routers import ocr
    from app.storage.local import LocalStorageProvider
    from app.storage.models import StorageReference

    if not hasattr(ocr, "run_ingestion_dispatch"):
        pytest.skip("raw/unit environment has not installed legacy durable overlay")

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    storage = LocalStorageProvider(tmp_path / "legacy-storage")
    payload = b"durable legacy txt"

    class Upload:
        filename = "legacy.txt"
        size = len(payload)
        content_type = "text/plain"

        async def read(self):
            return payload

    class CrashingBackgroundTasks:
        def add_task(self, *args, **kwargs):
            raise RuntimeError("simulated crash after legacy durable acceptance")

    try:
        with pytest.raises(RuntimeError, match="simulated crash"):
            asyncio.run(
                ocr.upload_file(
                    CrashingBackgroundTasks(),
                    Upload(),
                    db,
                    storage,
                )
            )

        assert db.query(Document).count() == 1
        assert db.query(SourceFile).count() == 1
        assert db.query(IngestionDispatch).count() == 1
        document = db.query(Document).one()
        source = db.query(SourceFile).one()
        dispatch = db.query(IngestionDispatch).one()
        assert document.status == "processing"
        assert source.document_id == document.id
        assert source.retained == 1
        assert dispatch.document_id == document.id
        assert dispatch.source_file_id == source.id
        assert dispatch.kind == "txt"
        assert dispatch.status == "queued"
        assert storage.exists(StorageReference.parse(source.storage_reference)) is True
    finally:
        db.close()
        engine.dispose()


def test_staging_workspace_installs_all_durable_upload_paths_from_one_entrypoint() -> None:
    resumable = Path("app/routers/resumable_upload.py").read_text(encoding="utf-8")
    direct = Path("app/routers/direct_upload.py").read_text(encoding="utf-8")
    legacy = Path("app/routers/ocr.py").read_text(encoding="utf-8")
    if "RESUMABLE_UPLOAD_COMPLETE_IDEMPOTENT" not in resumable:
        pytest.skip("raw/unit environment has not installed staging durable overlays")
    assert "DIRECT_UPLOAD_COMPLETE_IDEMPOTENT" in direct
    assert "legacy_acceptance_key" in legacy
    assert "background_tasks.add_task(run_ingestion_dispatch, accepted.dispatch_id)" in legacy
