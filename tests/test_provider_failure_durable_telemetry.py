from app.processing import pdf_ingestion
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


def test_provider_http_failure_metadata_survives_exception_wrapping():
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
    integration_error = IntegrationError(
        category=IntegrationErrorCategory.ORCHESTRATION_FAILURE,
        safe_message="provider request failed",
        orchestration_error=orchestration_error,
    )

    fields = pdf_ingestion._durable_failure_fields(integration_error)

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


def test_ingestion_failure_diagnostic_is_persisted_as_error(monkeypatch):
    captured = {}

    def capture_event(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(pdf_ingestion, "record_processing_event", capture_event)

    pdf_ingestion._diagnostic(
        "PDF_INGESTION_UNHANDLED_FAILURE",
        document_id="document-test",
        processing_attempt_id="pdf-ingest-test",
        error_type="IntegrationError",
        provider_http_status=502,
    )

    assert captured["processing_run_id"] == "pdf-ingest-test"
    assert captured["document_id"] == "document-test"
    assert captured["event_name"] == "PDF_INGESTION_UNHANDLED_FAILURE"
    assert captured["severity"] == "error"
    assert captured["payload"]["provider_http_status"] == 502
