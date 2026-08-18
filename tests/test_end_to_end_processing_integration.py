from __future__ import annotations

import asyncio
import hashlib
import pytest

from app.config import Settings
from app.processing.integration import (
    EndToEndProcessingIntegrationService, IntegrationError, IntegrationErrorCategory,
    ProcessingIntegrationRequest, RetainedSourceDescriptor, TrustedPublicSourceOrigin,
    build_temporary_source_transport_url,
)
from app.processing.models import ProviderLifecycleStatus
from app.processing.orchestration import OrchestrationError, OrchestrationErrorCategory, OrchestrationOutcome, OrchestrationPhase, OrchestrationRequest
from app.processing.paddle_vl.models import PaddleVLDocument, PaddleVLJobRequest
from app.processing.raw_result import RawProcessingResultEnvelope, RawResultEvidenceSource, RawResultIdentity, RawResultIngestionMetadata, RawResultProviderProvenance, RawResultSourceProvenance
from app.processing.transport.models import TransportGrantState
from app.processing.transport.service import InMemoryTransportGrantService
from app.storage.models import StorageReference

SHA = "a" * 64
TOKEN = "tok_" + "b" * 40
URL = f"https://public.example/internal/source-transport/{TOKEN}"

def src(**kw):
    data = dict(document_id="doc-1", source_file_id="sf-1", storage_reference=StorageReference.generate(), retained=True, sha256=SHA, byte_size=12, media_type="application/pdf", etag='"e"', filename="x.pdf")
    data.update(kw)
    return RetainedSourceDescriptor(**data)

def integ_req(**kw):
    data = dict(processing_attempt_id="attempt-1", correlation_id="corr-1", retained_source=src(), provider_job_id="job-1234", provider_request_id="req-1234")
    data.update(kw)
    return ProcessingIntegrationRequest(**data)

def raw():
    body = b"{}"; digest = hashlib.sha256(body).hexdigest()
    return RawProcessingResultEnvelope(
        RawResultIdentity("attempt-1", "corr-1", "doc-1", "sf-1", "paddle-vl", "job-1234", "req-1234", "standard", "provider_completed"),
        RawResultSourceProvenance(SHA, '"e"', "application/pdf"),
        RawResultProviderProvenance(),
        RawResultIngestionMetadata(__import__('datetime').datetime.now(__import__('datetime').timezone.utc), "application/json", None, None, len(body), digest, StorageReference.generate(), RawResultEvidenceSource.INLINE_JSON),
    )

class FakeOrchestrator:
    def __init__(self, outcome=None, error=None): self.calls=[]; self.outcome=outcome; self.error=error
    async def run_once(self, request, policy=None):
        self.calls.append((request, policy))
        if self.error: raise self.error
        return self.outcome

def outcome(status=ProviderLifecycleStatus.PROVIDER_COMPLETED, phase=OrchestrationPhase.RAW_RESULT_RETAINED, err=None, retained=True):
    return OrchestrationOutcome("attempt-1", "corr-1", "doc-1", "sf-1", "paddle-vl", "job-1234", "req-1234", phase, status, 3.0, 2, None, raw() if retained else None, None, (), (), err)

def test_url_bearing_repr_is_redacted_but_provider_json_keeps_url():
    o = OrchestrationRequest("a","c","d","s",URL,SHA,"application/pdf","p","j","r","standard")
    d = PaddleVLDocument("doc", URL, pdf_source_sha256=SHA)
    j = PaddleVLJobRequest("job", "req", [d])
    for model in (o, d, j):
        assert TOKEN not in repr(model)
        assert URL not in repr(model)
    assert d.to_provider_json()["pdf_source_url"] == URL
    assert j.to_provider_json()["documents"][0]["pdf_source_url"] == URL

def test_origin_and_url_builder_validation_redacts_token():
    assert build_temporary_source_transport_url("https://public.example/", TOKEN).url == URL
    assert TrustedPublicSourceOrigin("https://public.example").origin == "https://public.example/"
    for bad in ["http://public.example", "https://public.example/?x=1", "https://public.example/#f", "https://u:p@public.example", "https://public.example/base"]:
        with pytest.raises(IntegrationError) as e: TrustedPublicSourceOrigin(bad)
        assert e.value.category == IntegrationErrorCategory.INVALID_PUBLIC_ORIGIN
    with pytest.raises(IntegrationError) as e: build_temporary_source_transport_url("https://public.example", "bad token")
    assert "bad token" not in str(e.value)
    assert TOKEN not in repr(build_temporary_source_transport_url("https://public.example", TOKEN))

def test_missing_origin_fails_only_when_service_is_used():
    service = EndToEndProcessingIntegrationService(grant_service=InMemoryTransportGrantService(), orchestrator=FakeOrchestrator(outcome()), app_settings=Settings(ATLAS_PUBLIC_SOURCE_TRANSPORT_ORIGIN=None))
    with pytest.raises(IntegrationError) as e: asyncio.run(service.process(integ_req()))
    assert e.value.category == IntegrationErrorCategory.INVALID_PUBLIC_ORIGIN

@pytest.mark.parametrize("bad", [dict(retained=False), dict(sha256="bad"), dict(byte_size=-1), dict(media_type="text/plain"), dict(document_id="")])
def test_source_descriptor_validation(bad):
    with pytest.raises(IntegrationError): src(**bad).validate()

@pytest.mark.parametrize("status,phase", [(ProviderLifecycleStatus.FAILED, OrchestrationPhase.FAILED), (ProviderLifecycleStatus.EXPIRED, OrchestrationPhase.FAILED)])
def test_provider_terminal_failures_revoke(status, phase):
    grants=InMemoryTransportGrantService(); orch=FakeOrchestrator(outcome(status, phase, retained=False))
    out=asyncio.run(EndToEndProcessingIntegrationService(grant_service=grants, orchestrator=orch, public_origin="https://public.example").process(integ_req()))
    assert out.grant_final_state == TransportGrantState.REVOKED
    assert len(orch.calls) == 1

def test_happy_path_one_grant_one_orchestration_and_revoke():
    grants=InMemoryTransportGrantService(); orch=FakeOrchestrator(outcome())
    out=asyncio.run(EndToEndProcessingIntegrationService(grant_service=grants, orchestrator=orch, public_origin="https://public.example").process(integ_req()))
    assert out.raw_result is not None and out.raw_result_storage_reference is not None
    assert out.revocation_succeeded is True and out.grant_final_state == TransportGrantState.REVOKED
    assert len(orch.calls) == 1
    req, policy = orch.calls[0]
    assert req.source_url.startswith("https://public.example/internal/source-transport/")
    assert policy.timeout_seconds == 300 and policy.initial_interval_seconds == 2 and policy.max_interval_seconds == 10
    assert req.result_profile == "standard"
    assert req.provider_job_options == {}
    assert req.source_url not in repr(out) and "internal/source-transport" not in repr(out)

def test_timeout_and_submission_uncertain_keep_grant_active():
    for cat in (OrchestrationErrorCategory.TIMEOUT, OrchestrationErrorCategory.SUBMISSION_UNCERTAIN):
        phase = OrchestrationPhase.TIMED_OUT if cat == OrchestrationErrorCategory.TIMEOUT else OrchestrationPhase.SUBMISSION_UNCERTAIN
        err = OrchestrationError(cat, "safe", phase, "job-1234")
        grants=InMemoryTransportGrantService(); orch=FakeOrchestrator(error=err)
        with pytest.raises(IntegrationError) as e: asyncio.run(EndToEndProcessingIntegrationService(grant_service=grants, orchestrator=orch, public_origin="https://public.example").process(integ_req()))
        assert e.value.category in {IntegrationErrorCategory.TIMEOUT, IntegrationErrorCategory.SUBMISSION_UNCERTAIN}
        assert len(orch.calls) == 1
        # one grant exists and is still active
        created = list(grants._digest_by_id.keys())[0]
        assert grants.inspect(created).state == TransportGrantState.ACTIVE

def test_revocation_failure_preserves_primary_outcome_with_warning():
    class BadRevoke(InMemoryTransportGrantService):
        def revoke(self, grant_id): raise RuntimeError("nope")
    out=asyncio.run(EndToEndProcessingIntegrationService(grant_service=BadRevoke(), orchestrator=FakeOrchestrator(outcome()), public_origin="https://public.example").process(integ_req()))
    assert out.raw_result is not None and out.revocation_succeeded is False
    assert "revocation failed" in out.warnings[0]
    assert TOKEN not in repr(out)


def test_provider_source_document_and_parent_repr_are_redacted():
    from app.processing.orchestration import ProviderJobRequest, ProviderSourceDocumentRequest
    child = ProviderSourceDocumentRequest("doc", URL, pdf_source_sha256=SHA)
    parent = ProviderJobRequest("job", "req", [child], {"batch_size": 1})
    for model in (child, parent):
        assert URL not in repr(model)
        assert TOKEN not in repr(model)
        assert URL not in str(model)
        assert TOKEN not in str(model)
    assert parent.to_provider_json()["documents"][0]["pdf_source_url"] == URL


def test_origin_validation_rejects_missing_host_protocol_relative_and_whitespace():
    for bad in ["https://", "//public.example", " https://public.example", "https://public.example ", "https://exa mple.test", "https://public.example/.", "https://public.example/%2f"]:
        with pytest.raises(IntegrationError) as e:
            TrustedPublicSourceOrigin(bad)
        assert e.value.category == IntegrationErrorCategory.INVALID_PUBLIC_ORIGIN
        assert bad not in str(e.value)
    assert TrustedPublicSourceOrigin("https://localhost:7860").origin == "https://localhost:7860/"


def test_url_construction_failure_after_grant_creation_revokes_and_does_not_invoke_orchestrator():
    class BadTokenGrantService(InMemoryTransportGrantService):
        def create_grant(self, **kwargs):
            result = super().create_grant(**kwargs)
            from dataclasses import replace
            return replace(result, token="bad token")
    grants = BadTokenGrantService(); orch = FakeOrchestrator(outcome())
    with pytest.raises(IntegrationError) as e:
        asyncio.run(EndToEndProcessingIntegrationService(grant_service=grants, orchestrator=orch, public_origin="https://public.example").process(integ_req()))
    assert e.value.category == IntegrationErrorCategory.URL_CONSTRUCTION_FAILURE
    assert e.value.grant_final_state == TransportGrantState.REVOKED
    assert e.value.revocation_succeeded is True
    assert len(orch.calls) == 0
    assert "bad token" not in str(e.value)


def test_ingestion_failure_outcome_revokes_and_preserves_structured_error():
    err = OrchestrationError(OrchestrationErrorCategory.INGESTION_FAILURE, "raw result storage write failed", OrchestrationPhase.INGESTING_RAW_RESULT, "job-1234")
    out = outcome(ProviderLifecycleStatus.PROVIDER_COMPLETED, OrchestrationPhase.INGESTING_RAW_RESULT, err=err, retained=False)
    grants=InMemoryTransportGrantService(); orch=FakeOrchestrator(out)
    result=asyncio.run(EndToEndProcessingIntegrationService(grant_service=grants, orchestrator=orch, public_origin="https://public.example").process(integ_req()))
    assert result.grant_final_state == TransportGrantState.REVOKED
    assert result.error is not None
    assert result.error.orchestration_error.category == OrchestrationErrorCategory.INGESTION_FAILURE
    assert len(orch.calls) == 1


def test_integration_uses_one_grant_and_one_point_five_backoff_policy():
    class CountingGrantService(InMemoryTransportGrantService):
        def __init__(self): super().__init__(); self.create_calls = 0
        def create_grant(self, **kwargs): self.create_calls += 1; return super().create_grant(**kwargs)
    grants=CountingGrantService(); orch=FakeOrchestrator(outcome())
    asyncio.run(EndToEndProcessingIntegrationService(grant_service=grants, orchestrator=orch, public_origin="https://public.example").process(integ_req()))
    assert grants.create_calls == 1
    assert len(orch.calls) == 1
    assert orch.calls[0][1].backoff_factor == 1.5


def test_restart_grant_loss_during_cleanup_is_safe_and_does_not_resubmit():
    class LostGrantOnRevoke(InMemoryTransportGrantService):
        def revoke(self, grant_id):
            self._digest_by_id.clear(); self._by_digest.clear()
            raise RuntimeError("registry lost")
    grants=LostGrantOnRevoke(); orch=FakeOrchestrator(outcome())
    out=asyncio.run(EndToEndProcessingIntegrationService(grant_service=grants, orchestrator=orch, public_origin="https://public.example").process(integ_req()))
    assert out.revocation_succeeded is False
    assert out.grant_final_state is None
    assert "revocation failed" in out.warnings[0]
    assert len(orch.calls) == 1
