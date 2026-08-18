from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.models import Base, Document, ProcessingRun, SourceFile
import app.models_v2  # noqa: F401
import app.models_v2_selection  # noqa: F401
from app.processing.txt.ingestion import (
    TxtIngestionConfigurationError,
    TxtIngestionIds,
    build_production_txt_structure_analyzer,
    process_txt_document_background,
)
from app.processing.txt.structure_recovery import (
    TxtLineStructureAssignment,
    TxtStructureKind,
    TxtStructureWindowResult,
)
from app.storage.local import LocalStorageProvider
from app.storage.models import StorageReference
from app.structured_content_v2.selection import (
    StructuredContentV2SelectionNotFound,
    StructuredContentV2SelectionRepository,
)


OPENAI_TXT_BASE_URL = "https://api.openai.com/v1"
OPENAI_TXT_MODEL = "gpt-5.6-luna"


def _database(raw: bytes):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    digest = hashlib.sha256(raw).hexdigest()
    with factory.begin() as session:
        session.add(Document(id="doc-txt", title="TXT", file_type="txt", status="processing"))
        session.add(
            SourceFile(
                id="source-txt",
                document_id="doc-txt",
                original_filename="fixture.txt",
                file_type="txt",
                mime_type="text/plain",
                byte_size=len(raw),
                checksum_sha256=digest,
                storage_reference="src_" + "3" * 32,
                retained=1,
                is_primary=1,
            )
        )
    return engine, factory


class _Analyzer:
    def analyze(self, window):
        assignments = []
        for line in window.lines:
            if line.is_empty:
                continue
            if line.line_id == "L000001":
                kind, starts, level = TxtStructureKind.TITLE, True, None
            elif line.text.startswith("1 "):
                kind, starts, level = TxtStructureKind.HEADING, True, 1
            else:
                kind, starts, level = TxtStructureKind.PARAGRAPH, True, None
            assignments.append(TxtLineStructureAssignment(line.line_id, kind, starts, level))
        return TxtStructureWindowResult(window.window_id, tuple(assignments))


def _retain(storage, raw: bytes) -> None:
    ref = StorageReference.parse("src_" + "3" * 32)
    storage.put(
        raw,
        ref,
        expected_size=len(raw),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
    )


def test_production_runner_marks_document_completed_only_after_canonical_selection(tmp_path, monkeypatch) -> None:
    import app.processing.txt.ingestion as ingestion

    raw = "Book\n1 Intro\nBody\n".encode("utf-8")
    engine, factory = _database(raw)
    storage = LocalStorageProvider(tmp_path)
    _retain(storage, raw)
    monkeypatch.setattr(ingestion, "SessionLocal", factory)
    monkeypatch.setattr(ingestion, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(ingestion, "build_production_txt_structure_analyzer", lambda: _Analyzer())
    try:
        process_txt_document_background(
            "doc-txt",
            "source-txt",
            TxtIngestionIds("txt-ingest-test"),
        )
        with factory() as session:
            document = session.get(Document, "doc-txt")
            assert document.status == "completed"
            assert document.error_message is None
            assert document.original_file_path is None
            assert document.processed_file_path is None
            run = session.execute(
                select(ProcessingRun).where(ProcessingRun.processing_run_id == "txt-ingest-test")
            ).scalar_one()
            assert run.status == "succeeded"
            selection = StructuredContentV2SelectionRepository().get_selection(session, "doc-txt")
            assert selection.candidate_id.startswith("scv2_txt_")
    finally:
        engine.dispose()


def test_production_runner_fails_closed_when_structure_provider_is_not_configured(tmp_path, monkeypatch) -> None:
    import app.processing.txt.ingestion as ingestion

    raw = b"Book\nBody\n"
    engine, factory = _database(raw)
    storage = LocalStorageProvider(tmp_path)
    _retain(storage, raw)
    monkeypatch.setattr(ingestion, "SessionLocal", factory)
    monkeypatch.setattr(ingestion, "get_storage_provider", lambda: storage)

    def missing():
        raise TxtIngestionConfigurationError("missing")

    monkeypatch.setattr(ingestion, "build_production_txt_structure_analyzer", missing)
    try:
        process_txt_document_background(
            "doc-txt",
            "source-txt",
            TxtIngestionIds("txt-ingest-missing-config"),
        )
        with factory() as session:
            document = session.get(Document, "doc-txt")
            assert document.status == "failed"
            assert document.error_message == "TXT structure analysis is not configured"
            with pytest.raises(StructuredContentV2SelectionNotFound):
                StructuredContentV2SelectionRepository().get_selection(session, "doc-txt")
    finally:
        engine.dispose()


def test_txt_structure_defaults_target_openai_gpt_5_6_luna(monkeypatch) -> None:
    for name in (
        "ATLAS_TXT_STRUCTURE_API_BASE_URL",
        "ATLAS_TXT_STRUCTURE_API_KEY",
        "ATLAS_TXT_STRUCTURE_MODEL",
        "PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    configured = Settings(_env_file=None)
    assert configured.txt_structure_api_base_url == OPENAI_TXT_BASE_URL
    assert configured.txt_structure_model == OPENAI_TXT_MODEL
    assert configured.txt_structure_api_key is None
    assert configured.pdf_structure_refinement_openai_api_key is None


def test_existing_pdf_openai_secret_is_loaded_as_txt_compatible_fallback(monkeypatch) -> None:
    monkeypatch.delenv("ATLAS_TXT_STRUCTURE_API_KEY", raising=False)
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "shared-openai-secret")

    configured = Settings(_env_file=None)
    assert configured.txt_structure_api_key is None
    assert configured.pdf_structure_refinement_openai_api_key == "shared-openai-secret"


def test_production_analyzer_requires_one_secret_and_prefers_txt_specific_key(monkeypatch) -> None:
    import app.processing.txt.ingestion as ingestion

    monkeypatch.setattr(ingestion.settings, "txt_structure_api_base_url", OPENAI_TXT_BASE_URL)
    monkeypatch.setattr(ingestion.settings, "txt_structure_model", OPENAI_TXT_MODEL)
    monkeypatch.setattr(ingestion.settings, "txt_structure_api_key", None)
    monkeypatch.setattr(ingestion.settings, "pdf_structure_refinement_openai_api_key", None)
    with pytest.raises(TxtIngestionConfigurationError, match="PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY"):
        build_production_txt_structure_analyzer()

    monkeypatch.setattr(ingestion.settings, "pdf_structure_refinement_openai_api_key", "shared-secret")
    analyzer = build_production_txt_structure_analyzer()
    assert analyzer.config.base_url == OPENAI_TXT_BASE_URL
    assert analyzer.config.model == OPENAI_TXT_MODEL
    assert analyzer.config.api_key == "shared-secret"

    monkeypatch.setattr(ingestion.settings, "txt_structure_api_key", "txt-specific-secret")
    analyzer = build_production_txt_structure_analyzer()
    assert analyzer.config.api_key == "txt-specific-secret"


def test_explicit_blank_target_settings_still_fail_closed(monkeypatch) -> None:
    import app.processing.txt.ingestion as ingestion

    monkeypatch.setattr(ingestion.settings, "txt_structure_api_base_url", None)
    monkeypatch.setattr(ingestion.settings, "txt_structure_api_key", None)
    monkeypatch.setattr(ingestion.settings, "pdf_structure_refinement_openai_api_key", None)
    monkeypatch.setattr(ingestion.settings, "txt_structure_model", None)
    with pytest.raises(TxtIngestionConfigurationError, match="ATLAS_TXT_STRUCTURE_API_BASE_URL"):
        build_production_txt_structure_analyzer()


def test_upload_router_txt_branch_has_no_legacy_processed_text_or_ocr_path() -> None:
    source = Path("app/routers/ocr.py").read_text(encoding="utf-8")
    txt_start = source.index('if file_type == "txt":')
    pdf_start = source.index("# ── PDF:", txt_start)
    txt_branch = source[txt_start:pdf_start]

    assert "process_txt(" not in txt_branch
    assert "_processed.txt" not in txt_branch
    assert "original_file_path =" not in txt_branch
    assert "process_txt_document_background" in txt_branch
    assert 'status="processing"' in txt_branch
    assert "TXT structure analysis and Reader v2" in txt_branch
    assert "canonicalization queued." in txt_branch
