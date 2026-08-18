"""Direct-upload PDFs may defer page counting until preprocessing."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pymupdf
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document, DocumentType
from app.processing import pdf_ingestion


def _two_page_pdf_bytes() -> bytes:
    document = pymupdf.open()
    try:
        document.new_page()
        document.new_page()
        return document.tobytes()
    finally:
        document.close()


def test_preprocessing_accepts_unknown_expected_page_count(monkeypatch):
    pdf_bytes = _two_page_pdf_bytes()
    descriptor = SimpleNamespace(
        document_id="document-direct",
        storage_reference=object(),
        byte_size=len(pdf_bytes),
        sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        filename="direct.pdf",
    )
    observed = {}

    class Storage:
        def get(self, reference):
            assert reference is descriptor.storage_reference
            return pdf_bytes

    def fake_prepare_geometry_provider_input(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(
            byte_size=len(pdf_bytes),
            preprocessing=SimpleNamespace(changed_page_count=0),
        )

    monkeypatch.setattr(
        pdf_ingestion,
        "prepare_geometry_provider_input",
        fake_prepare_geometry_provider_input,
    )

    pdf_ingestion._prepare_geometry_provider_input_from_storage(
        storage=Storage(),
        descriptor=descriptor,
        processing_attempt_id="attempt-direct",
        expected_page_count=None,
    )

    # The repository source path accepts an unknown count. The Staging
    # production overlay resolves it from the already-loaded PDF before opening
    # the heartbeat/OpenCV context, so CI after overlays must pass the real count.
    if hasattr(pdf_ingestion, "pdf_resource_observation_context"):
        assert observed["expected_page_count"] == 2
    else:
        assert observed["expected_page_count"] is None
    assert observed["source_pdf_bytes"] == pdf_bytes


def test_discovered_page_count_is_persisted_only_when_missing(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    document = Document(
        id="document-direct",
        document_type=DocumentType.BOOK,
        title="Direct",
        file_type="pdf",
        pages_count=None,
        status="processing",
    )
    db.add(document)
    db.commit()
    db.close()
    monkeypatch.setattr(pdf_ingestion, "SessionLocal", SessionLocal)

    pdf_ingestion._set_document_page_count_if_missing("document-direct", 528)
    check = SessionLocal()
    assert check.get(Document, "document-direct").pages_count == 528
    check.close()

    pdf_ingestion._set_document_page_count_if_missing("document-direct", 999)
    check = SessionLocal()
    assert check.get(Document, "document-direct").pages_count == 528
    check.close()
    engine.dispose()
