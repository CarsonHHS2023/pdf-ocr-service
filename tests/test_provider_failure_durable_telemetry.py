from datetime import timedelta
import hashlib
import inspect
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from app.processing import pdf_ingestion
from app.processing import pdf_provider_sharding as provider_sharding
from app.processing import pdf_provider_sharding_compat as sharding_compat
from app.processing import provider_input_source_access as source_access
from app.processing.errors import (
    ProviderClientError,
    ProviderErrorCategory,
    ProviderErrorDetail,
)
from app.processing.integration import IntegrationError, IntegrationErrorCategory
from app.processing.orchestration import (
    OrchestrationError,
    OrchestrationErrorCategory,
    OrchestrationPhase,
)
from app.storage.errors import ProviderUnavailable
from app.storage.models import StorageReference


def _wrapped_provider_error() -> IntegrationError:
    provider_error = ProviderClientError(
        ProviderErrorDetail(
            category=ProviderErrorCategory.UNAVAILABLE,
            safe_message="provider request failed",
            http_status=502,
            provider_code="UPSTREAM_FAILURE",
            retryable=True,
        )
    )
    orchestration_error = OrchestrationError(
        category=OrchestrationErrorCategory.UNEXPECTED,
        safe_message="provider request failed",
        phase=OrchestrationPhase.SUBMITTING,
        provider_job_id="pdf-job-test",
        provider_error_code="UPSTREAM_FAILURE",
        retryable=True,
        elapsed_seconds=59.5,
        poll_count=0,
    )
    orchestration_error.__cause__ = provider_error
    return IntegrationError(
        category=IntegrationErrorCategory.ORCHESTRATION_FAILURE,
        safe_message="provider request failed",
        orchestration_error=orchestration_error,
    )


def test_provider_http_failure_metadata_survives_exception_wrapping():
    fields = pdf_ingestion._durable_failure_fields(_wrapped_provider_error())

    assert fields == {
        "integration_error_category": "orchestration_failure",
        "orchestration_error_category": "unexpected_orchestration_failure",
        "orchestration_phase": "submitting",
        "provider_error_code": "UPSTREAM_FAILURE",
        "retryable": True,
        "elapsed_seconds": 59.5,
        "poll_count": 0,
        "provider_error_category": "provider_unavailable",
        "provider_http_status": 502,
    }


def test_sharded_provider_failure_preserves_wrapped_http_metadata() -> None:
    fields = provider_sharding._provider_failure_metadata(_wrapped_provider_error())

    assert fields == {
        "provider_error_category": "provider_unavailable",
        "provider_http_status": 502,
        "provider_error_code": "UPSTREAM_FAILURE",
    }
    source = inspect.getsource(provider_sharding.run_provider_transport_shards)
    assert (
        "_provider_failure_metadata(exc)" in source
        or "_provider_failure_metadata(error)" in source
    )


def test_unhandled_failure_writer_persists_safe_error_event_without_stdout_rewrite(
    monkeypatch,
):
    captured = {}

    def capture_event(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(pdf_ingestion, "record_processing_event", capture_event)

    pdf_ingestion._record_unhandled_failure_event(
        document_id="document-test",
        processing_attempt_id="pdf-ingest-test",
        exc=_wrapped_provider_error(),
    )

    assert captured["processing_run_id"] == "pdf-ingest-test"
    assert captured["document_id"] == "document-test"
    assert captured["event_name"] == "PDF_INGESTION_UNHANDLED_FAILURE"
    assert captured["severity"] == "error"
    assert captured["payload"]["error_type"] == "IntegrationError"
    assert captured["payload"]["provider_http_status"] == 502
    assert captured["payload"]["provider_error_category"] == "provider_unavailable"
    assert captured["payload"]["provider_error_code"] == "UPSTREAM_FAILURE"


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
    signed_url = "https://objects.example.test/private.pdf?sig=do-not-persist"

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


def test_provider_timeline_overlay_is_idempotent() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    targets = (
        repo_root / "app" / "processing" / "pdf_ingestion.py",
        repo_root / "app" / "processing" / "pdf_provider_sharding_compat.py",
        repo_root / "app" / "processing" / "provider_input_source_access.py",
    )

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    before = {str(path): digest(path) for path in targets}
    subprocess.run(
        [sys.executable, "scripts/apply_durable_processing_events.py"],
        cwd=repo_root,
        check=True,
    )
    after = {str(path): digest(path) for path in targets}
    assert after == before


def test_live_failure_marker_precedes_durable_database_write() -> None:
    source = Path("app/processing/pdf_ingestion.py").read_text(encoding="utf-8")
    marker = '        print(\n            "PDF_INGESTION_UNHANDLED_FAILURE "\n'
    durable = '''        _record_unhandled_failure_event(
            document_id=document_id,
            processing_attempt_id=ids.processing_attempt_id,
            exc=exc,
        )
'''

    assert marker in source
    assert durable in source
    assert source.index(marker) < source.index(durable)
