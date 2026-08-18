from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.processing.integration import IntegrationError, IntegrationErrorCategory
from app.processing.models import ProviderLifecycleStatus
from app.processing.orchestration import OrchestrationError, OrchestrationErrorCategory, OrchestrationOutcome, OrchestrationPhase
from app.processing.raw_result import RawProcessingResultEnvelope, RawResultEvidenceSource, RawResultIdentity, RawResultIngestionMetadata, RawResultProviderProvenance, RawResultSourceProvenance
from app.processing.transport.dependencies import get_transport_grant_service
from app.processing.transport.models import TransportGrantState
from app.routers import processing_operator
from app.routers.processing_operator import OperatorIntegrationDependency, get_operator_integration_dependency, redact_operator_id
from app.storage.models import StorageReference

TOKEN = "op_" + "a" * 40
SHA = "fb084e43d06e039118d2a72a40353eebcec09abdbe732cf30917608723126420"


def body(**overrides):
    data = {
        "processing_attempt_id": "attempt-1234",
        "correlation_id": "corr-1234",
        "retained_source": {
            "document_id": "doc-1234",
            "source_file_id": "sf-1234",
            "storage_reference": "src_" + "1" * 32,
            "retained": True,
            "sha256": SHA,
            "byte_size": 605,
            "media_type": "application/pdf",
            "etag": '"etag"',
            "filename": "test-only.pdf",
        },
        "provider_name": "paddle-vl",
        "provider_job_id": "job_abcdef1234567f3a",
        "provider_request_id": "req_abcdef12345691bc",
        "result_profile": "standard",
        "test_fixture_only": True,
    }
    data.update(overrides)
    return data


def raw_envelope():
    return RawProcessingResultEnvelope(
        RawResultIdentity("attempt-1234", "corr-1234", "doc-1234", "sf-1234", "paddle-vl", "job_abcdef1234567f3a", "req_abcdef12345691bc", "standard", "provider_completed"),
        RawResultSourceProvenance(SHA, '"etag"', "application/pdf"),
        RawResultProviderProvenance(),
        RawResultIngestionMetadata(__import__("datetime").datetime.now(__import__("datetime").timezone.utc), "application/json", None, None, 2, "c" * 64, StorageReference.parse("src_" + "2" * 32), RawResultEvidenceSource.INLINE_JSON),
    )


def orchestration_outcome(error=None, phase=OrchestrationPhase.RAW_RESULT_RETAINED, status=ProviderLifecycleStatus.PROVIDER_COMPLETED, raw=True):
    return OrchestrationOutcome("attempt-1234", "corr-1234", "doc-1234", "sf-1234", "paddle-vl", "job_abcdef1234567f3a", "req_abcdef12345691bc", phase, status, 1.2, 3, None, raw_envelope() if raw else None, None, (), (), error)


class FakeIntegrationService:
    def __init__(self, outcome=None, error=None, unexpected=False):
        self.calls = []
        self.outcome = outcome or orchestration_outcome()
        self.error = error
        self.unexpected = unexpected

    async def process(self, request):
        self.calls.append(request)
        if self.unexpected:
            raise RuntimeError("secret internal detail")
        if self.error:
            raise self.error
        return _make_processing_outcome(request, self.outcome)


def _make_processing_outcome(request, orch_outcome):
    from app.processing.integration import ProcessingIntegrationOutcome
    return ProcessingIntegrationOutcome(
        request.retained_source.document_id,
        request.retained_source.source_file_id,
        request.provider_name,
        orch_outcome.provider_job_id,
        orch_outcome.provider_request_id,
        orch_outcome.final_phase,
        orch_outcome.provider_terminal_status,
        orch_outcome,
        orch_outcome.raw_result,
        orch_outcome.raw_result.ingestion.storage_reference if orch_outcome.raw_result else None,
        orch_outcome.raw_result.ingestion.payload_sha256 if orch_outcome.raw_result else None,
        orch_outcome.raw_result.ingestion.payload_size_bytes if orch_outcome.raw_result else None,
        1.23456,
        orch_outcome.poll_count,
        ("safe warning",),
        "grant_abcdef123456abcd",
        TransportGrantState.REVOKED,
        True,
        None if orch_outcome.error is None else IntegrationError(IntegrationErrorCategory.TIMEOUT, "safe", orch_outcome.error, grant_id="grant_abcdef123456abcd", grant_final_state=TransportGrantState.ACTIVE, revocation_succeeded=False),
    )


class FakeDependency(OperatorIntegrationDependency):
    def __init__(self, service, close_error=False):
        object.__setattr__(self, "service", service)
        object.__setattr__(self, "owned_client", None)
        self.closed = False
        self.close_error = close_error

    async def close(self):
        self.closed = True
        if self.close_error:
            raise RuntimeError("close secret detail")


@pytest.fixture(autouse=True)
def clean_overrides(monkeypatch):
    app.dependency_overrides.clear()
    monkeypatch.setattr(processing_operator.settings, "processing_operator_enabled", False)
    monkeypatch.setattr(processing_operator.settings, "processing_operator_token", None)
    yield
    app.dependency_overrides.clear()


def enable(monkeypatch, service=None):
    monkeypatch.setattr(processing_operator.settings, "processing_operator_enabled", True)
    monkeypatch.setattr(processing_operator.settings, "processing_operator_token", TOKEN)
    dep = FakeDependency(service or FakeIntegrationService())
    async def factory():
        return dep
    app.dependency_overrides[get_operator_integration_dependency] = lambda: factory
    return dep


def post(payload=None, token=TOKEN):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return TestClient(app).post("/internal/operator/process-once", json=payload or body(), headers=headers)


def test_disabled_by_default_and_startup_accepts_missing_token():
    assert Settings().processing_operator_enabled is False
    assert "secret" not in repr(Settings(ATLAS_PROCESSING_OPERATOR_TOKEN="secret" * 8))
    response = post(token=None)
    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


@pytest.mark.parametrize("header", [None, "Basic abc", "Bearer wrong"])
def test_authentication_collapses_missing_malformed_and_invalid(monkeypatch, header):
    enable(monkeypatch)
    headers = {} if header is None else {"Authorization": header}
    response = TestClient(app).post("/internal/operator/process-once", json=body(), headers=headers)
    assert response.status_code == 404
    assert "wrong" not in response.text


def test_enabled_without_high_entropy_token_fails_safely(monkeypatch):
    monkeypatch.setattr(processing_operator.settings, "processing_operator_enabled", True)
    monkeypatch.setattr(processing_operator.settings, "processing_operator_token", "short")
    response = post(token="short")
    assert response.status_code == 404


def test_reusing_provider_token_fails_safely(monkeypatch):
    enable(monkeypatch)
    monkeypatch.setattr(processing_operator.settings, "paddle_vl_api_bearer_token", TOKEN)
    response = post(token=TOKEN)
    assert response.status_code == 404


def test_settings_false_string_parsing(monkeypatch):
    for raw in ("false", "False", "0", "off"):
        monkeypatch.setenv("ATLAS_PROCESSING_OPERATOR_ENABLED", raw)
        assert Settings(_env_file=None).processing_operator_enabled is False


def test_invalid_body_with_missing_or_invalid_auth_still_collapses(monkeypatch):
    enable(monkeypatch)
    client = TestClient(app)
    invalid_json = "{not-json"
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        response = client.post("/internal/operator/process-once", content=invalid_json, headers=headers)
        assert response.status_code == 404
        assert response.json() == {"detail": "Not found"}
    invalid_schema = {"source_url": "https://example.test/secret.pdf"}
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        response = client.post("/internal/operator/process-once", json=invalid_schema, headers=headers)
        assert response.status_code == 404
        assert response.json() == {"detail": "Not found"}


def test_unauthorized_requests_do_not_construct_integration_dependencies(monkeypatch):
    monkeypatch.setattr(processing_operator.settings, "processing_operator_enabled", True)
    monkeypatch.setattr(processing_operator.settings, "processing_operator_token", TOKEN)
    calls = {"factory": 0}

    async def factory():
        calls["factory"] += 1
        return FakeDependency(FakeIntegrationService())

    app.dependency_overrides[get_operator_integration_dependency] = lambda: factory
    response = TestClient(app).post("/internal/operator/process-once", json={"bad": "body"}, headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 404
    assert calls == {"factory": 0}


def test_query_body_and_cookie_credentials_are_not_fallbacks(monkeypatch):
    enable(monkeypatch)
    client = TestClient(app)
    assert client.post(f"/internal/operator/process-once?token={TOKEN}", json=body()).status_code == 404
    payload = body(operator_token=TOKEN)
    assert client.post("/internal/operator/process-once", json=payload).status_code == 404
    assert client.post("/internal/operator/process-once", json=body(), cookies={"Authorization": f"Bearer {TOKEN}"}).status_code == 404


def test_blank_and_whitespace_bearers_collapse(monkeypatch):
    enable(monkeypatch)
    client = TestClient(app)
    for header in ("Bearer ", f"Bearer  {TOKEN}", f"Bearer {TOKEN} "):
        response = client.post("/internal/operator/process-once", json=body(), headers={"Authorization": header})
        assert response.status_code == 404


def test_route_hidden_from_openapi_and_only_post_invokes(monkeypatch):
    dep = enable(monkeypatch)
    client = TestClient(app)
    assert "/internal/operator/process-once" not in client.get("/openapi.json").text
    for method in (client.get, client.head, client.put, client.delete):
        assert method("/internal/operator/process-once", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 405
    assert client.post("/internal/operator/process-once/", json=body(), headers={"Authorization": f"Bearer {TOKEN}"}).status_code in {307, 404}
    assert dep.service.calls == []


@pytest.mark.parametrize("extra", [
    {"source_url": "https://example.test/file.pdf"},
    {"transport_token": "tok_secret"},
    {"local_path": "/tmp/file.pdf"},
    {"provider_bearer_token": "secret"},
    {"atlas_public_origin": "https://evil.test"},
])
def test_request_rejects_forbidden_top_level_fields(monkeypatch, extra):
    enable(monkeypatch)
    payload = body(**extra)
    response = post(payload)
    assert response.status_code == 422
    assert "secret" not in response.text


@pytest.mark.parametrize("patch", [
    {"retained": False},
    {"storage_reference": "not-valid"},
    {"sha256": "bad"},
    {"byte_size": 0},
    {"media_type": "text/plain"},
])
def test_request_validation_rejects_bad_source(monkeypatch, patch):
    enable(monkeypatch)
    payload = body()
    payload["retained_source"].update(patch)
    response = post(payload)
    assert response.status_code in {422, 400}


@pytest.mark.parametrize("patch", [{"result_profile": "full"}, {"provider_options": {"batch_size": 1}}, {"test_fixture_only": False}])
def test_rejects_non_standard_profile_options_and_non_fixture_ack(monkeypatch, patch):
    enable(monkeypatch)
    response = post(body(**patch))
    assert response.status_code == 422


def test_fixture_only_requires_committed_fixture_evidence(monkeypatch):
    enable(monkeypatch)
    payload = body()
    payload["retained_source"]["sha256"] = "b" * 64
    response = post(payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid processing operator request"}


def test_valid_request_invokes_integration_once_and_returns_safe_response(monkeypatch):
    service = FakeIntegrationService()
    dep = enable(monkeypatch, service)
    response = post()
    assert response.status_code == 200
    assert len(service.calls) == 1
    assert dep.closed is True
    data = response.json()
    assert data["status"] == "succeeded"
    assert data["provider_job_id"] == "job_...7f3a"
    assert data["provider_request_id"] == "req_...91bc"
    assert data["grant_id"] == "grant_...abcd"
    assert data["raw_result_storage_reference"] == "src_" + "2" * 32
    forbidden = [TOKEN, "Bearer", "internal/source-transport", "tok_", "https://", "secret", "/tmp"]
    assert not any(item in response.text for item in forbidden)


def test_timeout_and_submission_uncertainty_are_safe_failures(monkeypatch):
    for cat in (OrchestrationErrorCategory.TIMEOUT, OrchestrationErrorCategory.SUBMISSION_UNCERTAIN):
        err = OrchestrationError(cat, "safe", OrchestrationPhase.TIMED_OUT if cat == OrchestrationErrorCategory.TIMEOUT else OrchestrationPhase.SUBMISSION_UNCERTAIN, "job_abcdef1234567f3a")
        service = FakeIntegrationService(outcome=orchestration_outcome(error=err, phase=err.phase, status=ProviderLifecycleStatus.RUNNING, raw=False))
        enable(monkeypatch, service)
        response = post()
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert "Do not resubmit automatically" in data["retry_guidance"]
        assert len(service.calls) == 1


def test_definite_integration_exception_returns_safe_failure(monkeypatch):
    exc = IntegrationError(IntegrationErrorCategory.ORCHESTRATION_FAILURE, "safe failure", grant_id="grant_abcdef123456abcd", grant_final_state=TransportGrantState.REVOKED, revocation_succeeded=True)
    enable(monkeypatch, FakeIntegrationService(error=exc))
    response = post()
    assert response.status_code == 200
    assert response.json()["error_category"] == "orchestration_failure"
    assert "abcdef123456abcd" not in response.text


def test_default_composition_uses_shared_grant_and_closes_owned_client(monkeypatch):
    created = []
    closed = []
    seen = {}

    class FakeClient:
        def __init__(self, config):
            self.config = config
            created.append(self)

        async def aclose(self):
            closed.append(self)

    class FakeConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeOrchestrator:
        def __init__(self, *, provider, storage):
            seen["provider"] = provider
            seen["storage"] = storage

    class FakeService:
        def __init__(self, *, grant_service, orchestrator, public_origin):
            seen["grant_service"] = grant_service
            seen["orchestrator"] = orchestrator
            seen["public_origin"] = public_origin

    storage = object()
    monkeypatch.setattr(processing_operator, "PaddleVLClient", FakeClient)
    monkeypatch.setattr(processing_operator, "PaddleVLClientConfig", FakeConfig)
    monkeypatch.setattr(processing_operator, "ProcessingOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(processing_operator, "EndToEndProcessingIntegrationService", FakeService)
    monkeypatch.setattr(processing_operator, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(processing_operator.settings, "paddle_vl_api_base_url", "https://provider.test")
    monkeypatch.setattr(processing_operator.settings, "paddle_vl_api_bearer_token", "provider-token")
    monkeypatch.setattr(processing_operator.settings, "public_source_transport_origin", "https://atlas.test")

    import asyncio
    dep = asyncio.run(processing_operator.create_operator_integration_dependency())
    assert len(created) == 1
    assert seen["provider"] is created[0]
    assert seen["storage"] is storage
    assert seen["grant_service"] is get_transport_grant_service()
    assert seen["public_origin"] == "https://atlas.test"
    asyncio.run(dep.close())
    assert closed == created


def test_default_composition_closes_client_when_storage_resolution_fails(monkeypatch):
    created = []
    closed = []

    class FakeClient:
        def __init__(self, config):
            created.append(self)

        async def aclose(self):
            closed.append(self)

    class FakeConfig:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(processing_operator, "PaddleVLClient", FakeClient)
    monkeypatch.setattr(processing_operator, "PaddleVLClientConfig", FakeConfig)
    monkeypatch.setattr(processing_operator, "get_storage_provider", lambda: (_ for _ in ()).throw(RuntimeError("storage failed")))

    import asyncio
    with pytest.raises(RuntimeError):
        asyncio.run(processing_operator.create_operator_integration_dependency())
    assert len(created) == 1
    assert closed == created


def test_dependency_close_failure_does_not_expose_detail(monkeypatch):
    service = FakeIntegrationService()
    dep = FakeDependency(service, close_error=True)

    async def factory():
        return dep

    monkeypatch.setattr(processing_operator.settings, "processing_operator_enabled", True)
    monkeypatch.setattr(processing_operator.settings, "processing_operator_token", TOKEN)
    app.dependency_overrides[get_operator_integration_dependency] = lambda: factory
    response = post()
    assert response.status_code == 200
    assert dep.closed is True
    assert "close secret detail" not in response.text


def test_unexpected_failure_is_generic_and_closes_owned_dependency(monkeypatch):
    dep = enable(monkeypatch, FakeIntegrationService(unexpected=True))
    response = post()
    assert response.status_code == 500
    assert response.json() == {"detail": "Processing operator failed"}
    assert "secret internal detail" not in response.text
    assert dep.closed is True


def test_redact_operator_id_preserves_prefix_and_final_four():
    assert redact_operator_id("job_abcdef1234567f3a") == "job_...7f3a"
    assert redact_operator_id("req_abcdef12345691bc") == "req_...91bc"
    assert redact_operator_id("abcd") == "...abcd"
    assert redact_operator_id("xy") == "...****"
    assert redact_operator_id(None) is None


def test_operator_uses_application_lifetime_grant_service_dependency():
    assert get_transport_grant_service() is get_transport_grant_service()
