from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import Document, SourceFile
from app.processing import pdf_ingestion
from app.processing.integration import RetainedSourceDescriptor
from app.processing.txt import canonicalization as txt_canonicalization
from app.processing.txt.canonicalization import (
    RetainedTxtCanonicalizationRequest,
    TxtCanonicalizationError,
    TxtCanonicalizationService,
)
from app.storage.models import StorageReference
from app.upload_policy import BookSourceTooLarge
from scripts.apply_provider_input_presigned_read import patch_provider_input_presigned_read
from scripts.apply_provider_runtime_preflight import patch_provider_runtime_preflight
from scripts.apply_s0_pdf_resource_heartbeat import patch_s0_pdf_resource_heartbeat
from scripts.apply_s0_v5_phase0_observability import patch_s0_v5_phase0_observability


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_PDF_INGESTION = REPO_ROOT / "app" / "processing" / "pdf_ingestion.py"
BASE_PRESENTATION_LIFECYCLE = (
    REPO_ROOT / "app" / "processing" / "pdf_page_presentation_lifecycle_compat.py"
)
BASE_PROVIDER_SHARDING = REPO_ROOT / "app" / "processing" / "pdf_provider_sharding.py"


def _pdf_descriptor(byte_size: int) -> RetainedSourceDescriptor:
    return RetainedSourceDescriptor(
        document_id="doc-pdf-admission",
        source_file_id="source-pdf-admission",
        storage_reference=StorageReference.parse("src_" + "1" * 32),
        retained=True,
        sha256="a" * 64,
        byte_size=byte_size,
        media_type="application/pdf",
        filename="book.pdf",
    )


class _ForbiddenStorageRead:
    def __init__(self) -> None:
        self.get_calls = 0

    def get(self, reference):
        self.get_calls += 1
        raise AssertionError("oversized retained source must not be read from storage")


def test_pdf_source_read_rejects_oversize_before_storage_get(monkeypatch) -> None:
    monkeypatch.setattr(pdf_ingestion.settings, "book_source_max_bytes", 5)
    storage = _ForbiddenStorageRead()

    with pytest.raises(BookSourceTooLarge):
        pdf_ingestion._read_verified_source_pdf(storage, _pdf_descriptor(6))

    assert storage.get_calls == 0


def test_pdf_async_admission_runs_before_preprocessing_capacity(monkeypatch) -> None:
    monkeypatch.setattr(pdf_ingestion.settings, "book_source_max_bytes", 5)

    class ForbiddenCapacity:
        def __init__(self) -> None:
            self.acquire_calls = 0

        def acquire(self, *, blocking):
            self.acquire_calls += 1
            raise AssertionError("oversized source must not consume preprocessing capacity")

    capacity = ForbiddenCapacity()
    monkeypatch.setattr(pdf_ingestion, "_PDF_PREPROCESSING_CAPACITY", capacity)

    with pytest.raises(BookSourceTooLarge):
        asyncio.run(
            pdf_ingestion._prepare_geometry_provider_input_async(
                storage=_ForbiddenStorageRead(),
                descriptor=_pdf_descriptor(6),
                processing_attempt_id="pdf-ingest-admission",
                document_id="doc-pdf-admission",
                expected_page_count=None,
            )
        )

    assert capacity.acquire_calls == 0


class _TxtSession:
    def __init__(self, *, byte_size: int | None) -> None:
        self.source = SimpleNamespace(
            id="source-txt-admission",
            document_id="doc-txt-admission",
            file_type="txt",
            retained=1,
            storage_reference="src_" + "2" * 32,
            byte_size=byte_size,
            checksum_sha256="b" * 64,
        )
        self.document = SimpleNamespace(id="doc-txt-admission")
        self.closed = False
        self.rollback_calls = 0

    def get(self, model, key):
        if model is SourceFile:
            return self.source
        if model is Document:
            return self.document
        raise AssertionError("unexpected model lookup")

    def close(self) -> None:
        self.closed = True

    def rollback(self) -> None:
        self.rollback_calls += 1


class _UnusedAnalyzer:
    def analyze(self, window):
        raise AssertionError("oversized TXT source must not reach analysis")


def test_txt_processing_rejects_oversize_before_storage_get(monkeypatch) -> None:
    monkeypatch.setattr(txt_canonicalization.settings, "book_source_max_bytes", 5)
    storage = _ForbiddenStorageRead()
    session = _TxtSession(byte_size=6)
    service = TxtCanonicalizationService(
        storage=storage,
        session_factory=lambda: session,
        analyzer=_UnusedAnalyzer(),
    )

    with pytest.raises(TxtCanonicalizationError) as exc_info:
        service.canonicalize(
            RetainedTxtCanonicalizationRequest(
                document_ref="doc-txt-admission",
                source_file_ref="source-txt-admission",
                processing_run_ref="txt-run-admission",
            )
        )

    assert exc_info.value.stage == "source_validation"
    assert "processing limit" in str(exc_info.value)
    assert storage.get_calls == 0
    assert session.closed is True


def _copy(tmp_path: Path, source: Path) -> Path:
    target = tmp_path / source.name
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def test_pdf_admission_preserves_heartbeat_overlay_preprocessing_anchor(tmp_path) -> None:
    candidate = _copy(tmp_path, BASE_PDF_INGESTION)

    patch_s0_pdf_resource_heartbeat(candidate)
    transformed = candidate.read_text(encoding="utf-8")

    assert "validate_book_source_size(descriptor.byte_size, settings)" in transformed
    assert 'phase="source_read_start"' in transformed
    assert "await_with_pdf_processing_lease(" in transformed


def test_pdf_admission_composes_with_full_staging_provider_and_s0_overlay_chain(
    tmp_path,
) -> None:
    ingestion = _copy(tmp_path, BASE_PDF_INGESTION)
    lifecycle = _copy(tmp_path, BASE_PRESENTATION_LIFECYCLE)
    sharding = _copy(tmp_path, BASE_PROVIDER_SHARDING)

    patch_s0_pdf_resource_heartbeat(ingestion)
    patch_provider_runtime_preflight(ingestion)
    patch_provider_input_presigned_read(
        ingestion,
        presentation_lifecycle_path=lifecycle,
        provider_sharding_path=sharding,
    )
    patch_s0_v5_phase0_observability(ingestion)

    transformed = ingestion.read_text(encoding="utf-8")
    assert "validate_book_source_size(descriptor.byte_size, settings)" in transformed
    assert "provider_delivery = provider_delivery_descriptor(geometry_input)" in transformed
    assert "source_transport_url_factory=provider_source_url_factory" in transformed
    assert "install_s0_v5_phase0_observability()" in transformed
    assert "install_s0_v5_phase1_shared_analysis()" in transformed
    assert "await_with_pdf_processing_lease(" in transformed
