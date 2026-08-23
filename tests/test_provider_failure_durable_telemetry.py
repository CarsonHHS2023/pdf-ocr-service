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
