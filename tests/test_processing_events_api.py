from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_db
from app.models import Base, Document, encode_json_text
from app.processing.processing_event_model import ProcessingEvent
from app.routers import processing_events, processing_operator


_TEST_OPERATOR_TOKEN = "processing-events-test-operator-token-0001"


def _app_and_factory(tmp_path, monkeypatch, *, enabled: bool, token: str | None):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'processing-events-api.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(
        engine,
        tables=[Document.__table__, ProcessingEvent.__table__],
    )
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = factory()
    try:
        db.add(
            Document(
                id="doc-api-events",
                title="API auth durable events test",
                file_type="pdf",
                status="processing",
            )
        )
        db.add(
            ProcessingEvent(
                id="event-api-1",
                processing_run_id="pdf-ingest-api-events",
                document_id="doc-api-events",
                schema_version="atlas.processing.event.v1",
                event_name="PDF_SOURCE_VALIDATED",
                severity="info",
                page_number=1,
                payload_json=encode_json_text({"phase": "validated"}) or "{}",
                created_at=datetime(2026, 8, 22, 12, 0, 0),
            )
        )
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        processing_operator,
        "settings",
        SimpleNamespace(
            processing_operator_enabled=enabled,
            processing_operator_token=token,
            paddle_vl_api_bearer_token=None,
        ),
    )

    app = FastAPI()
    app.include_router(processing_events.router)

    def _override_db():
        session: Session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_db
    return app, engine


def test_processing_events_operator_route_is_hidden_when_disabled(tmp_path, monkeypatch):
    app, engine = _app_and_factory(
        tmp_path,
        monkeypatch,
        enabled=False,
        token=_TEST_OPERATOR_TOKEN,
    )
    try:
        client = TestClient(app)
        response = client.get(
            "/internal/operator/processing-events",
            params={"processing_run_id": "pdf-ingest-api-events"},
            headers={"Authorization": f"Bearer {_TEST_OPERATOR_TOKEN}"},
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "Not found"}
    finally:
        engine.dispose()


def test_processing_events_operator_route_requires_exact_bearer_token(tmp_path, monkeypatch):
    app, engine = _app_and_factory(
        tmp_path,
        monkeypatch,
        enabled=True,
        token=_TEST_OPERATOR_TOKEN,
    )
    try:
        client = TestClient(app)
        params = {"processing_run_id": "pdf-ingest-api-events"}

        assert client.get(
            "/internal/operator/processing-events",
            params=params,
        ).status_code == 404
        assert client.get(
            "/internal/operator/processing-events",
            params=params,
            headers={"Authorization": "Bearer wrong-token"},
        ).status_code == 404
        assert client.get(
            "/internal/operator/processing-events",
            params=params,
            headers={"Authorization": f"Basic {_TEST_OPERATOR_TOKEN}"},
        ).status_code == 404

        response = client.get(
            "/internal/operator/processing-events",
            params=params,
            headers={"Authorization": f"Bearer {_TEST_OPERATOR_TOKEN}"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["processing_run_id"] == "pdf-ingest-api-events"
        assert payload["count"] == 1
        assert payload["events"][0]["event_name"] == "PDF_SOURCE_VALIDATED"
        assert payload["events"][0]["payload"] == {"phase": "validated"}
    finally:
        engine.dispose()


def test_processing_events_operator_route_requires_query_scope_after_auth(tmp_path, monkeypatch):
    app, engine = _app_and_factory(
        tmp_path,
        monkeypatch,
        enabled=True,
        token=_TEST_OPERATOR_TOKEN,
    )
    try:
        client = TestClient(app)
        response = client.get(
            "/internal/operator/processing-events",
            headers={"Authorization": f"Bearer {_TEST_OPERATOR_TOKEN}"},
        )
        assert response.status_code == 422
        assert response.json() == {
            "detail": "processing_run_id or document_id is required"
        }
    finally:
        engine.dispose()
