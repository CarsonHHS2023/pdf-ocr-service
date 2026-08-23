from datetime import timedelta
from types import SimpleNamespace

from app.processing import pdf_ingestion
from app.processing import pdf_provider_sharding_compat as sharding_compat
from app.processing import provider_input_source_access as source_access
from app.storage.errors import ProviderUnavailable
from app.storage.models import StorageReference


def test_sharding_diagnostic_persists_only_low_frequency_timeline(monkeypatch):
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(
        sharding_compat,
        "record_processing_event",
        lambda **kwargs: captured.append(kwargs) or True,
    )

    sharding_compat._diagnostic(
        "PDF_PROVIDER_DELIVERY_READY",
        document_id="document-test",
        processing_attempt_id="pdf-ingest-test",
        provider_job_id="pdf-job-test",
        provider_byte_size=1772664,
        provider_page_count=1,
        sharding_required=False,
    )

    assert len(captured) == 1
    assert captured[0]["processing_run_id"] == "pdf-ingest-test"
    assert captured[0]["document_id"] == "document-test"
    assert captured[0]["event_name"] == "PDF_PROVIDER_DELIVERY_READY"
    assert captured[0]["payload"]["provider_byte_size"] == 1772664

    captured.clear()
    sharding_compat._diagnostic(
        "PDF_PROVIDER_SHARD_STARTED",
        processing_attempt_id="pdf-ingest-test",
        provider_job_id="pdf-job-test-s001",
        shard_index=0,
    )
    assert captured == []

    sharding_compat._diagnostic(
        "PDF_PROVIDER_SHARD_EXECUTION_FAILED",
        processing_attempt_id="pdf-ingest-test",
        provider_job_id="pdf-job-test-s001",
        shard_index=0,
        error_type="RuntimeError",
    )
    assert len(captured) == 1
    assert captured[0]["event_name"] == "PDF_PROVIDER_SHARD_EXECUTION_FAILED"
    assert captured[0]["severity"] == "error"


def test_source_access_fallback_persists_route_without_url(monkeypatch):
    captured: list[dict[str, object]] = []

    def unavailable(*args, **kwargs):
        raise ProviderUnavailable("presigned read unavailable")

    monkeypatch.setattr(source_access, "generate_existing_provider_read_url", unavailable)
    monkeypatch.setattr(
        source_access,
        "record_processing_event",
        lambda **kwargs: captured.append(kwargs) or True,
    )

    factory = source_access.build_provider_input_source_url_factory(
        storage=object(),
        reference=StorageReference.generate(),
        byte_size=1772664,
        processing_run_id="pdf-ingest-test",
        document_id="document-test",
    )

    assert factory(timedelta(seconds=4200)) is None
    assert len(captured) == 1
    event = captured[0]
    assert event["event_name"] == "PDF_PROVIDER_SOURCE_ACCESS"
    assert event["severity"] == "warning"
    assert event["payload"] == {
        "route": "atlas_source_transport_fallback",
        "byte_size": 1772664,
        "expires_seconds": 4200,
        "reason": "ProviderUnavailable",
    }
    assert "url" not in event["payload"]


def test_source_access_presigned_route_persists_host_not_signed_url(monkeypatch):
    captured: list[dict[str, object]] = []
    signed_url = (
        "https://objects.example.test/private.pdf?"
        "X-Amz-Signature=do-not-persist&X-Amz-Credential=secret"
    )

    monkeypatch.setattr(
        source_access,
        "generate_existing_provider_read_url",
        lambda *args, **kwargs: signed_url,
    )
    monkeypatch.setattr(
        source_access,
        "record_processing_event",
        lambda **kwargs: captured.append(kwargs) or True,
    )

    factory = source_access.build_provider_input_source_url_factory(
        storage=object(),
        reference=StorageReference.generate(),
        byte_size=2048,
        processing_run_id="pdf-ingest-test",
        document_id="document-test",
    )

    result = factory(timedelta(seconds=3600))
    assert result is not None
    assert len(captured) == 1
    event = captured[0]
    assert event["event_name"] == "PDF_PROVIDER_SOURCE_ACCESS"
    assert event["payload"] == {
        "route": "presigned_object_get",
        "host": "objects.example.test",
        "byte_size": 2048,
        "expires_seconds": 3600,
    }
    serialized = repr(event["payload"])
    assert "X-Amz-Signature" not in serialized
    assert "do-not-persist" not in serialized
    assert signed_url not in serialized


def test_document_state_event_keeps_processing_run_correlation(monkeypatch):
    document = SimpleNamespace(status="processing", error_message=None)
    diagnostics: list[tuple[str, dict[str, object]]] = []

    class FakeSession:
        def get(self, model, identity):
            return document

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(pdf_ingestion, "SessionLocal", FakeSession)
    monkeypatch.setattr(
        pdf_ingestion,
        "_diagnostic",
        lambda event, **fields: diagnostics.append((event, fields)),
    )

    pdf_ingestion._set_document_terminal_state(
        "document-test",
        processing_attempt_id="pdf-ingest-test",
        status="failed",
        error_message="provider request failed",
    )

    assert document.status == "failed"
    assert document.error_message == "provider request failed"
    assert diagnostics == [
        (
            "PDF_DOCUMENT_STATE_UPDATED",
            {
                "document_id": "document-test",
                "processing_attempt_id": "pdf-ingest-test",
                "status": "failed",
                "has_error": True,
            },
        )
    ]
