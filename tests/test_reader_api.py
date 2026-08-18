from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.reader import (
    NoSelectedReaderContent,
    ReaderContentState,
    ReaderDocumentMetadata,
    ReaderDocumentView,
    ReaderLocation,
    ReaderNodeView,
    ReaderPageView,
    ReaderProcessingState,
)
from app.routers import reader
from app.structured_content.enums import ContentNodeType
from app.structured_content.errors import CandidateSelectionPersistenceError
from app.structured_content.identity import ContentCandidateId, ContentNodeId, ContentPageId, DocumentRef


def _location(*, page_id: str | None = None, node_id: str | None = None) -> ReaderLocation:
    return ReaderLocation(
        document_ref=DocumentRef("doc"),
        candidate_id=ContentCandidateId("candidate"),
        candidate_schema_id="structured-content",
        candidate_schema_version=1,
        page_id=ContentPageId(page_id) if page_id is not None else None,
        node_id=ContentNodeId(node_id) if node_id is not None else None,
    )


def _view(page_count: int = 3) -> ReaderDocumentView:
    pages = []
    for order in range(page_count):
        page_id = f"page-{order}"
        node_id = f"node-{order}"
        node = ReaderNodeView(
            location=_location(page_id=page_id, node_id=node_id),
            node_id=ContentNodeId(node_id),
            node_type=ContentNodeType.PARAGRAPH,
            order=0,
            content_state=ReaderContentState.READY,
            text=f"Page {order}",
        )
        pages.append(
            ReaderPageView(
                location=_location(page_id=page_id),
                page_id=ContentPageId(page_id),
                page_order=order,
                content_state=ReaderContentState.READY,
                nodes=(node,),
            )
        )
    return ReaderDocumentView(
        document_ref=DocumentRef("doc"),
        candidate_id=ContentCandidateId("candidate"),
        candidate_schema_id="structured-content",
        candidate_schema_version=1,
        processing_state=ReaderProcessingState.COMPLETED,
        content_state=ReaderContentState.READY,
        metadata=ReaderDocumentMetadata(title="Example", page_count=page_count),
        pages=tuple(pages),
    )


def _test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(reader.router)
    app.dependency_overrides[reader.get_db] = lambda: object()
    return app


@pytest.fixture
def client(monkeypatch):
    app = _test_app()
    monkeypatch.setattr(reader, "_build_view", lambda db, document_ref: _view())
    return TestClient(app)


def test_open_reader_document_excludes_page_bodies(client: TestClient):
    response = client.get("/api/reader/v1/documents/doc")
    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == "1"
    assert payload["document_ref"] == "doc"
    assert payload["candidate_id"] == "candidate"
    assert payload["metadata"] == {"title": "Example", "page_count": 3}
    assert payload["navigation"] == []
    assert "pages" not in payload


def test_navigation_is_delivered_separately(client: TestClient):
    response = client.get("/api/reader/v1/documents/doc/navigation")
    assert response.status_code == 200
    assert response.json()["navigation"] == []
    assert "pages" not in response.json()


def test_content_is_bounded_and_emits_forward_continuation(client: TestClient):
    response = client.get("/api/reader/v1/documents/doc/content?start_page_order=0&limit=2")
    assert response.status_code == 200
    payload = response.json()
    assert [page["page_order"] for page in payload["pages"]] == [0, 1]
    assert payload["has_more"] is True
    assert payload["continuation"]["page_order"] == 2
    assert payload["continuation"]["location"]["page_id"] == "page-2"
    assert payload["continuation"]["location"]["candidate_id"] == "candidate"


def test_content_start_page_order_is_an_inclusive_lower_bound(client: TestClient):
    response = client.get("/api/reader/v1/documents/doc/content?start_page_order=1&limit=2")
    assert response.status_code == 200
    payload = response.json()
    assert [page["page_order"] for page in payload["pages"]] == [1, 2]
    assert payload["has_more"] is False
    assert payload["continuation"] is None


def test_candidate_bound_content_request_rejects_stale_continuation(client: TestClient):
    current = client.get(
        "/api/reader/v1/documents/doc/content?candidate_id=candidate&start_page_order=2&limit=1"
    )
    assert current.status_code == 200
    assert [page["page_order"] for page in current.json()["pages"]] == [2]

    stale = client.get(
        "/api/reader/v1/documents/doc/content?candidate_id=old-candidate&start_page_order=2&limit=1"
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "reader_selection_changed"


def test_content_limit_is_strictly_bounded(client: TestClient):
    response = client.get(f"/api/reader/v1/documents/doc/content?limit={reader.MAX_PAGE_LIMIT + 1}")
    assert response.status_code == 422


def test_content_rejects_negative_start_order(client: TestClient):
    response = client.get("/api/reader/v1/documents/doc/content?start_page_order=-1")
    assert response.status_code == 422


def test_no_selection_maps_to_bounded_not_ready_error(monkeypatch):
    app = _test_app()

    def no_selection(*, session, document_ref):
        raise NoSelectedReaderContent("no selection")

    monkeypatch.setattr(reader, "build_selected_reader_document", no_selection)
    response = TestClient(app).get("/api/reader/v1/documents/doc")
    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "reader_not_ready",
            "message": "Reader content is not available for this document.",
        }
    }


def test_internal_repository_failures_are_not_collapsed_to_409(monkeypatch):
    app = _test_app()

    def persistence_failure(*, session, document_ref):
        raise CandidateSelectionPersistenceError("database unavailable")

    monkeypatch.setattr(reader, "build_selected_reader_document", persistence_failure)
    response = TestClient(app, raise_server_exceptions=False).get("/api/reader/v1/documents/doc")
    assert response.status_code == 500


def test_reader_api_exposes_explicit_response_models():
    schema = _test_app().openapi()
    open_response = schema["paths"]["/api/reader/v1/documents/{document_ref}"]["get"]["responses"]["200"]
    content_response = schema["paths"]["/api/reader/v1/documents/{document_ref}/content"]["get"]["responses"]["200"]
    assert open_response["content"]["application/json"]["schema"]["$ref"].endswith("/ReaderOpenResponse")
    assert content_response["content"]["application/json"]["schema"]["$ref"].endswith("/ReaderContentResponse")


def test_reader_api_is_opt_in_and_versioned(client: TestClient):
    assert client.get("/api/reader/v1/documents/doc").status_code == 200
    assert client.get("/api/reader/documents/doc").status_code == 404
