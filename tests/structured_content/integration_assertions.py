from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from app.models import (
    BookImage,
    ContentBlock,
    Document,
    MineruResult,
    OCRTask,
    PdfPage,
    ProcessingRun,
    StructuredContentCandidate as CandidateRow,
    StructuredContentNode,
    StructuredContentSelection,
)
from app.structured_content.serialization import serialize_structured_content_candidate

LEGACY_TABLES = ("ocr_tasks", "pdf_pages", "mineru_results", "content_blocks", "book_images")


def canonical(candidate) -> bytes:
    return serialize_structured_content_candidate(candidate)


def candidate_row_snapshot(session, public_candidate_id: str):
    row = session.query(CandidateRow).filter_by(candidate_id=public_candidate_id).one()
    node_count = session.query(StructuredContentNode).filter_by(candidate_id=row.id).count()
    return (row.id, row.candidate_id, row.document_id, row.processing_run_ref, row.created_at, node_count)


def selection_count(session, document_id: str | None = None) -> int:
    q = session.query(StructuredContentSelection)
    if document_id is not None:
        q = q.filter_by(document_id=document_id)
    return q.count()


def run_count(session, document_id: str | None = None) -> int:
    q = session.query(ProcessingRun)
    if document_id is not None:
        q = q.filter_by(document_id=document_id)
    return q.count()


def legacy_counts(session):
    counts = {}
    for table in LEGACY_TABLES:
        counts[table] = session.execute(text(f"select count(*) from {table}")).scalar_one()
    return counts


def seed_representative_legacy_rows(session, document_id: str = "legacy-doc") -> str:
    created = datetime(2026, 1, 1, 12, 0, 0)
    updated = datetime(2026, 1, 1, 12, 5, 0)
    session.add(Document(id=document_id, title="Legacy Book", file_type="pdf", status="completed", pages_count=2, original_file_path="legacy/original.pdf", processed_file_path="legacy/processed.pdf", created_at=created, updated_at=updated))
    session.add(OCRTask(id="legacy-ocr", filename="legacy.pdf", status="COMPLETED", created_at=created, updated_at=updated, result_text="legacy ocr text", error_message=None, pages_count=2))
    session.add(PdfPage(id="legacy-page", book_id=document_id, page_num=1, status="completed", page_image_data=b"page-bytes", page_width=800, page_height=1000, ocr_raw_json='{"text":"page"}', error_message=None, created_at=created, updated_at=updated))
    session.add(MineruResult(id="legacy-mineru", book_id=document_id, status="completed", result_json='[{"type":"text","content":"legacy"}]', error_message=None, created_at=created, updated_at=updated))
    session.add(ContentBlock(id="legacy-block", book_id=document_id, page_num=1, block_index=0, block_type="text", content="legacy block", bbox="1,2,3,4", confidence=0.99, created_at=created))
    session.add(BookImage(id="legacy-image", book_id=document_id, image_id="img-legacy", image_format="png", image_data=b"image-bytes", image_size=11, page_num=1, bbox="5,6,7,8", block_type="image", created_at=created))
    session.flush()
    return document_id


def snapshot_legacy_rows(session):
    return {
        "ocr_tasks": tuple(session.execute(text("select id, filename, status, result_text, error_message, pages_count from ocr_tasks order by id")).all()),
        "pdf_pages": tuple(session.execute(text("select id, book_id, page_num, status, page_width, page_height, ocr_raw_json, error_message from pdf_pages order by id")).all()),
        "mineru_results": tuple(session.execute(text("select id, book_id, status, result_json, error_message from mineru_results order by id")).all()),
        "content_blocks": tuple(session.execute(text("select id, book_id, page_num, block_index, block_type, content, bbox, confidence from content_blocks order by id")).all()),
        "book_images": tuple(session.execute(text("select id, book_id, image_id, image_format, image_size, page_num, bbox, block_type, image_data from book_images order by id")).all()),
    }


def assert_legacy_snapshot_unchanged(session, snapshot) -> None:
    assert snapshot_legacy_rows(session) == snapshot
