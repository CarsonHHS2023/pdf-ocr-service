from __future__ import annotations

from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import StructuredContentAsset as AssetRow, StructuredContentCandidate as CandidateRow
from app.reader_asset_service import build_selected_reader_asset
from app.routers import reader
from app.structured_content.identity import ContentCandidateId, ContentLineageKey
from app.structured_content.repository import StructuredContentCandidateRepository
from app.structured_content.selection_repository import StructuredContentSelectionRepository
from tests.structured_content.candidate_factory import make_asset_evidence_warning_candidate, make_table_candidate
from tests.structured_content.integration_factory import add_document, sqlite_session


class _Storage:
    def __init__(self, data: bytes = b"png-bytes"):
        self.data = data

    def get(self, reference):
        return self.data


def _persist_selected(session, candidate):
    candidates = StructuredContentCandidateRepository()
    selections = StructuredContentSelectionRepository(candidates)
    add_document(session, str(candidate.document_ref), source_file_id="source-file")
    candidates.create_candidate(session, candidate)
    selections.set_selection(
        session,
        document_ref=str(candidate.document_ref),
        candidate_id=str(candidate.candidate_id),
        expected_version=0,
    )
    return candidates, selections


def _app(session) -> FastAPI:
    app = FastAPI()
    app.include_router(reader.router)
    app.dependency_overrides[reader.get_db] = lambda: session
    return app


def _asset_url(candidate, suffix: str = "") -> str:
    return (
        f"/api/reader/v1/documents/{candidate.document_ref}/assets/asset-0000{suffix}"
        f"?candidate_id={candidate.candidate_id}"
    )


def test_selected_asset_metadata_degrades_safely_when_no_durable_locator_exists():
    session, _ = sqlite_session()
    candidate = make_asset_evidence_warning_candidate(evidence_count=1, asset_count=1, warning_count=0)
    _persist_selected(session, candidate)

    delivery = build_selected_reader_asset(
        session=session,
        document_ref=str(candidate.document_ref),
        candidate_id=str(candidate.candidate_id),
        asset_id="asset-0000",
    )
    assert delivery.delivery_state == "degraded"
    assert delivery.storage_ref is None

    response = TestClient(_app(session)).get(_asset_url(candidate))
    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "asset-0000"
    assert payload["candidate_id"] == str(candidate.candidate_id)
    assert payload["recovery_state"] == "available"
    assert payload["delivery_state"] == "degraded"
    assert payload["content_href"] is None
    assert "storage_ref" not in payload


def test_asset_content_unavailable_is_bounded_and_does_not_break_metadata():
    session, _ = sqlite_session()
    candidate = make_asset_evidence_warning_candidate(evidence_count=1, asset_count=1, warning_count=0)
    _persist_selected(session, candidate)
    client = TestClient(_app(session))

    response = client.get(_asset_url(candidate, "/content"))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "reader_asset_unavailable"
    assert client.get(_asset_url(candidate)).status_code == 200


def test_asset_content_uses_selected_candidate_storage_locator_without_exposing_it(monkeypatch):
    session, _ = sqlite_session()
    candidate = make_asset_evidence_warning_candidate(evidence_count=1, asset_count=1, warning_count=0)
    _persist_selected(session, candidate)

    candidate_row = session.execute(
        select(CandidateRow).where(CandidateRow.candidate_id == str(candidate.candidate_id))
    ).scalar_one()
    asset_row = session.execute(
        select(AssetRow).where(AssetRow.candidate_id == candidate_row.id, AssetRow.asset_id == "asset-0000")
    ).scalar_one()
    asset_row.storage_ref = "src_0123456789abcdef0123456789abcdef"
    session.flush()
    monkeypatch.setattr(reader, "get_storage_provider", lambda: _Storage())

    client = TestClient(_app(session))
    metadata = client.get(_asset_url(candidate))
    assert metadata.status_code == 200
    assert metadata.json()["delivery_state"] == "available"
    assert metadata.json()["content_href"].endswith(
        f"/assets/asset-0000/content?candidate_id={candidate.candidate_id}"
    )
    assert "storage_ref" not in metadata.json()

    content = client.get(metadata.json()["content_href"])
    assert content.status_code == 200
    assert content.content == b"png-bytes"
    assert content.headers["cache-control"] == "private, no-store"
    assert content.headers["x-content-type-options"] == "nosniff"


def test_unsafe_asset_media_type_degrades_without_inline_content_href():
    session, _ = sqlite_session()
    candidate = make_asset_evidence_warning_candidate(evidence_count=1, asset_count=1, warning_count=0)
    _persist_selected(session, candidate)

    candidate_row = session.execute(
        select(CandidateRow).where(CandidateRow.candidate_id == str(candidate.candidate_id))
    ).scalar_one()
    asset_row = session.execute(
        select(AssetRow).where(AssetRow.candidate_id == candidate_row.id, AssetRow.asset_id == "asset-0000")
    ).scalar_one()
    asset_row.storage_ref = "src_0123456789abcdef0123456789abcdef"
    asset_row.media_type = "text/html"
    session.flush()

    client = TestClient(_app(session))
    metadata = client.get(_asset_url(candidate))
    assert metadata.status_code == 200
    assert metadata.json()["delivery_state"] == "degraded"
    assert metadata.json()["content_href"] is None
    content = client.get(_asset_url(candidate, "/content"))
    assert content.status_code == 409
    assert content.json()["detail"]["code"] == "reader_asset_unavailable"


def test_asset_identity_is_scoped_to_explicit_selected_candidate():
    session, _ = sqlite_session()
    candidate = make_asset_evidence_warning_candidate(evidence_count=1, asset_count=1, warning_count=0)
    _persist_selected(session, candidate)
    response = TestClient(_app(session)).get(
        f"/api/reader/v1/documents/{candidate.document_ref}/assets/not-selected"
        f"?candidate_id={candidate.candidate_id}"
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "reader_asset_not_found"


def test_stale_asset_location_fails_closed_after_reselection_even_when_asset_id_repeats():
    session, _ = sqlite_session()
    first = make_asset_evidence_warning_candidate(evidence_count=1, asset_count=1, warning_count=0)
    candidates, selections = _persist_selected(session, first)
    second = replace(
        first,
        candidate_id=ContentCandidateId("candidate-assets-2"),
        lineage_key=ContentLineageKey("lineage-assets-2"),
    )
    candidates.create_candidate(session, second)
    selections.set_selection(
        session,
        document_ref=str(first.document_ref),
        candidate_id=str(second.candidate_id),
        expected_version=1,
    )

    response = TestClient(_app(session)).get(_asset_url(first))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "reader_selection_changed"


def test_table_endpoint_delivers_bounded_deterministic_cells():
    session, _ = sqlite_session()
    candidate = make_table_candidate(rows=2, columns=2)
    _persist_selected(session, candidate)

    base = f"/api/reader/v1/documents/{candidate.document_ref}/tables/{candidate.nodes[0].node_id}"
    response = TestClient(_app(session)).get(
        f"{base}?candidate_id={candidate.candidate_id}&cell_offset=0&cell_limit=2"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["content_state"] == "ready"
    assert payload["row_count"] == 2
    assert payload["column_count"] == 2
    assert payload["cell_offset"] == 0
    assert payload["cell_limit"] == 2
    assert [cell["text"] for cell in payload["cells"]] == ["R0C0", "R0C1"]
    assert payload["has_more"] is True
    assert payload["next_cell_offset"] == 2

    follow = TestClient(_app(session)).get(
        f"{base}?candidate_id={candidate.candidate_id}&cell_offset=2&cell_limit=2"
    ).json()
    assert [cell["text"] for cell in follow["cells"]] == ["R1C0", "R1C1"]
    assert follow["has_more"] is False
    assert follow["next_cell_offset"] is None
    assert payload["rendered_asset_id"] is None
    assert payload["rendered_asset_href"] is None


def test_table_cell_limit_is_strictly_bounded():
    session, _ = sqlite_session()
    candidate = make_table_candidate(rows=2, columns=2)
    _persist_selected(session, candidate)
    response = TestClient(_app(session)).get(
        f"/api/reader/v1/documents/{candidate.document_ref}/tables/{candidate.nodes[0].node_id}"
        f"?candidate_id={candidate.candidate_id}&cell_limit={reader.MAX_TABLE_CELL_LIMIT + 1}"
    )
    assert response.status_code == 422


def test_non_table_node_is_not_fabricated_as_table():
    session, _ = sqlite_session()
    candidate = make_asset_evidence_warning_candidate(evidence_count=1, asset_count=1, warning_count=0)
    _persist_selected(session, candidate)
    response = TestClient(_app(session)).get(
        f"/api/reader/v1/documents/{candidate.document_ref}/tables/{candidate.nodes[0].node_id}"
        f"?candidate_id={candidate.candidate_id}"
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "reader_table_not_found"
