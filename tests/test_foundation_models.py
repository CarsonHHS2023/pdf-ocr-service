"""Focused tests for the Document/SourceFile foundation cutover."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import (
    Base,
    BookImage,
    ContentBlock,
    Document,
    DocumentType,
    MineruResult,
    PdfPage,
    SourceFile,
    validate_document_type,
)
from app.ocr_service import OCRExtractionResult


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session, monkeypatch):
    def override_get_db():
        yield db_session

    monkeypatch.setattr(
        "app.routers.ocr.get_ocr_service",
        lambda: type(
            "FakeOCR",
            (),
            {"process_txt": lambda self, path: OCRExtractionResult(Path(path).read_text(encoding="utf-8"), 1.0)},
        )(),
    )
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _upload_txt(client: TestClient, content: str = "foundation content", name: str = "foundation.txt"):
    return client.post(
        "/api/v1/upload",
        files=[("file", (name, io.BytesIO(content.encode("utf-8")), "text/plain"))],
    )


def test_document_model_defaults_and_validation(db_session):
    document = Document(title="Doc", file_type="txt", status="completed")
    db_session.add(document)
    db_session.commit()

    assert document.document_type == DocumentType.BOOK.value
    assert document.book_title == "Doc"
    assert "metadata" not in Document.__mapper__.attrs
    assert validate_document_type("INVOICE") == DocumentType.INVOICE.value
    with pytest.raises(ValueError):
        Document(title="Bad", file_type="txt", document_type="invalid")


def test_document_type_all_controlled_values_are_valid(db_session):
    """Foundation integrity: only accepted DocumentType machine values persist."""
    for document_type in DocumentType:
        document = Document(
            title=f"{document_type.value} document",
            file_type="txt",
            document_type=document_type.value,
        )
        db_session.add(document)
        db_session.flush()
        assert document.document_type == document_type.value
        assert validate_document_type(document_type.value) == document_type.value

    db_session.rollback()


def test_invalid_document_type_is_rejected_at_model_boundary():
    """Foundation integrity: unsupported document types are rejected in app code."""
    with pytest.raises(ValueError):
        validate_document_type("category")

    with pytest.raises(ValueError):
        Document(title="Bad", file_type="txt", document_type="category")


def test_source_file_relationship_and_cascade(db_session):
    document = Document(id="doc-1", title="Doc", file_type="txt")
    document.source_files = [
        SourceFile(original_filename="a.txt", file_type="txt", is_primary=1),
        SourceFile(original_filename="b.txt", file_type="txt", is_primary=0),
    ]
    db_session.add(document)
    db_session.commit()

    saved = db_session.query(Document).filter_by(id="doc-1").one()
    assert len(saved.source_files) == 2
    assert saved.source_files[0].document is saved

    db_session.delete(saved)
    db_session.commit()
    assert db_session.query(SourceFile).count() == 0


def test_upload_creates_book_document_and_source_file(client, db_session):
    response = _upload_txt(client, content="hello reader", name="reader.txt")
    assert response.status_code == 200, response.text
    data = response.json()

    document = db_session.query(Document).filter_by(id=data["book_id"]).one()
    assert document.document_type == DocumentType.BOOK.value
    assert document.title == "reader"
    assert document.source_files[0].original_filename == "reader.txt"
    assert document.source_files[0].byte_size == len("hello reader".encode("utf-8"))
    assert document.source_files[0].checksum_sha256 is not None


def test_books_endpoint_filters_to_book_documents(client, db_session):
    book = Document(id="book-doc", title="Book", document_type=DocumentType.BOOK, file_type="txt", status="completed")
    receipt = Document(id="receipt-doc", title="Receipt", document_type=DocumentType.RECEIPT, file_type="txt", status="completed")
    db_session.add_all([book, receipt])
    db_session.commit()

    response = client.get("/api/v1/books")
    assert response.status_code == 200
    ids = {item["book_id"] for item in response.json()["books"]}
    assert "book-doc" in ids
    assert "receipt-doc" not in ids


def test_reader_api_is_backed_by_document_not_bookshelf_table(client, db_session):
    response = _upload_txt(client)
    assert response.status_code == 200
    book_id = response.json()["book_id"]

    assert db_session.query(Document).filter_by(id=book_id).count() == 1
    assert "bookshelf" not in Base.metadata.tables
    detail = client.get(f"/api/v1/books/{book_id}").json()
    assert detail["book_id"] == book_id
    assert detail["book_title"] == "foundation"


def test_reader_upload_creates_exactly_one_primary_source_file(client, db_session):
    """Compatibility: current Reader uploads create one primary source evidence row."""
    response = _upload_txt(client, content="primary source", name="primary.txt")
    assert response.status_code == 200, response.text

    document = db_session.query(Document).filter_by(id=response.json()["book_id"]).one()
    assert len(document.source_files) == 1
    assert document.source_files[0].is_primary is True or document.source_files[0].is_primary == 1


def test_deleting_document_cascades_current_dependent_records(db_session):
    """Document identity: deleting the aggregate leaves no current child orphans."""
    document = Document(id="cascade-doc", title="Cascade", file_type="pdf")
    document.source_files = [SourceFile(original_filename="cascade.pdf", file_type="pdf", is_primary=1)]
    document.content_blocks = [
        ContentBlock(page_num=1, block_index=0, block_type="text", content="hello"),
    ]
    document.images = [
        BookImage(image_id="img_cascade", image_data=b"png", image_size=3),
    ]
    document.pages = [
        PdfPage(page_num=1, status="completed", page_image_data=b"page"),
    ]
    document.mineru_result = MineruResult(status="completed", result_json="[]")

    db_session.add(document)
    db_session.commit()

    assert db_session.query(SourceFile).filter_by(document_id="cascade-doc").count() == 1
    assert db_session.query(ContentBlock).filter_by(book_id="cascade-doc").count() == 1
    assert db_session.query(BookImage).filter_by(book_id="cascade-doc").count() == 1
    assert db_session.query(PdfPage).filter_by(book_id="cascade-doc").count() == 1
    assert db_session.query(MineruResult).filter_by(book_id="cascade-doc").count() == 1

    db_session.delete(document)
    db_session.commit()

    assert db_session.query(SourceFile).filter_by(document_id="cascade-doc").count() == 0
    assert db_session.query(ContentBlock).filter_by(book_id="cascade-doc").count() == 0
    assert db_session.query(BookImage).filter_by(book_id="cascade-doc").count() == 0
    assert db_session.query(PdfPage).filter_by(book_id="cascade-doc").count() == 0
    assert db_session.query(MineruResult).filter_by(book_id="cascade-doc").count() == 0


def test_reader_books_endpoint_excludes_each_non_book_document_type(client, db_session):
    """Reader boundary: non-book Documents must not leak through book APIs."""
    book = Document(id="reader-book", title="Reader Book", document_type=DocumentType.BOOK, file_type="txt")
    db_session.add(book)
    for document_type in DocumentType:
        if document_type is DocumentType.BOOK:
            continue
        db_session.add(
            Document(
                id=f"reader-{document_type.value}",
                title=f"Reader {document_type.value}",
                document_type=document_type,
                file_type="txt",
            )
        )
    db_session.commit()

    response = client.get("/api/v1/books")
    assert response.status_code == 200
    ids = {item["book_id"] for item in response.json()["books"]}

    assert "reader-book" in ids
    for document_type in DocumentType:
        if document_type is not DocumentType.BOOK:
            assert f"reader-{document_type.value}" not in ids


def test_reader_book_detail_content_and_delete_exclude_non_book_documents(client, db_session):
    """Reader boundary: book resource routes must not operate on non-book Documents."""
    receipt = Document(
        id="non-book-receipt",
        title="Receipt",
        document_type=DocumentType.RECEIPT,
        file_type="txt",
        status="completed",
        processed_file_path="/tmp/non-book-receipt.txt",
    )
    db_session.add(receipt)
    db_session.commit()

    detail = client.get("/api/v1/books/non-book-receipt")
    content = client.get("/api/v1/books/non-book-receipt/content")
    delete = client.delete("/api/v1/books/non-book-receipt")

    assert detail.status_code == 404
    assert content.status_code == 404
    assert delete.status_code == 404
    assert db_session.query(Document).filter_by(id="non-book-receipt").count() == 1
