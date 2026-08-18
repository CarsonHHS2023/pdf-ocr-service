from __future__ import annotations

import hashlib
import math
import asyncio
from functools import wraps
import pytest


def run_async(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper

from app.processing.errors import ProviderClientError, ProviderErrorCategory, ProviderErrorDetail
from app.processing.models import ArtifactMetadata, ProviderArtifact, ProviderJobStatus, ProviderLifecycleStatus, ProviderProgress, ProviderResult, ProviderSubmission
from app.processing.orchestration import OrchestrationError, OrchestrationErrorCategory, OrchestrationPhase, OrchestrationRequest, PollingPolicy, ProcessingOrchestrator
from app.processing.raw_result import RawResultEvidenceSource
from app.storage.local import LocalStorageProvider

SHA = "a" * 64

class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t
    async def sleep(self, seconds): self.t += seconds

class RecordingClock(Clock):
    def __init__(self):
        super().__init__()
        self.sleeps = []
    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        await super().sleep(seconds)

class FakeProvider:
    def __init__(self):
        self.submission = ProviderSubmission("job-1", "req-1", ProviderLifecycleStatus.QUEUED)
        self.statuses = []
        self.results = []
        self.artifact = None
        self.submitted = []
        self.artifact_calls = []
        self.closed = False
    async def submit_job(self, request):
        self.submitted.append(request)
        if isinstance(self.submission, Exception): raise self.submission
        return self.submission
    async def get_job_status(self, job_id):
        item = self.statuses.pop(0)
        if isinstance(item, Exception): raise item
        return item
    async def get_job_result(self, job_id, profile=None):
        item = self.results.pop(0)
        if isinstance(item, Exception): raise item
        return item
    async def get_job_artifact(self, job_id, metadata=None):
        self.artifact_calls.append(metadata)
        if isinstance(self.artifact, Exception): raise self.artifact
        return self.artifact

def req(**kw):
    data = dict(processing_attempt_id="attempt-1", correlation_id="corr-1", document_id="doc-1", source_file_id="sf-1", source_url="https://example.test/doc.pdf", source_checksum_sha256=SHA, source_media_type="application/pdf", provider_name="paddle-vl", provider_job_id="job-1", provider_request_id="req-1", result_profile="full")
    data.update(kw)
    return OrchestrationRequest(**data)

def status(s, pct=None):
    return ProviderJobStatus("job-1", "req-1", s, s in {ProviderLifecycleStatus.PROVIDER_COMPLETED, ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED}, ProviderProgress(percent_complete=pct, provider_execution_complete=s not in {ProviderLifecycleStatus.QUEUED, ProviderLifecycleStatus.RUNNING}))

def inline_result(profile="full", status=ProviderLifecycleStatus.PROVIDER_COMPLETED):
    pages=[{"page_number":1,"page_index":0,"local_page_index":0,"source_page_range":[1,1]}]
    return ProviderResult("job-1", "req-1", status, profile, None, [{"document_id":"doc-1","raw_result":pages}], {"job_id":"job-1","status":status.value,"profile":profile,"documents":[{"raw_result":pages}],"warnings":["w"]})

@pytest.mark.parametrize("bad", [
    {"processing_attempt_id":""}, {"processing_attempt_id":123}, {"document_id":"   "}, {"source_url":"http://x"}, {"source_checksum_sha256":"bad"}, {"expected_page_count":-1}, {"result_profile":"tiny"}, {"provider_job_options":{"batch_size": math.inf}},
])
def test_request_validation_rejects_bad_inputs(tmp_path, bad):
    p=FakeProvider(); c=Clock()
    with pytest.raises(OrchestrationError) as e:
        import asyncio; asyncio.run(ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req(**bad)))
    assert e.value.category == OrchestrationErrorCategory.INVALID_INPUT

@pytest.mark.parametrize("policy", [
    PollingPolicy(timeout_seconds=0),
    PollingPolicy(timeout_seconds=math.nan),
    PollingPolicy(timeout_seconds=math.inf),
    PollingPolicy(initial_interval_seconds=0),
    PollingPolicy(max_interval_seconds=0.5, initial_interval_seconds=1),
    PollingPolicy(max_status_requests=0),
    PollingPolicy(max_result_requests=0),
])
def test_polling_policy_validation_rejects_invalid_values(tmp_path, policy):
    p=FakeProvider(); c=Clock()
    with pytest.raises(OrchestrationError) as e:
        asyncio.run(ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req(), policy))
    assert e.value.category == OrchestrationErrorCategory.INVALID_INPUT

def test_provider_options_are_defensively_copied_and_schema_compatible():
    options = {"batch_size": 2}
    request = req(provider_job_options=options)
    options["batch_size"] = 99
    assert request.provider_job_options["batch_size"] == 2
    with pytest.raises(TypeError):
        request.provider_job_options["batch_size"] = 3

@run_async
async def test_queued_running_completed_inline_ingests_after_provider_completion(tmp_path):
    p=FakeProvider(); c=Clock()
    p.statuses=[status(ProviderLifecycleStatus.QUEUED,0), status(ProviderLifecycleStatus.RUNNING,100), status(ProviderLifecycleStatus.PROVIDER_COMPLETED,100)]
    p.results=[inline_result()]
    out=await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req(), PollingPolicy(timeout_seconds=30, initial_interval_seconds=1, max_interval_seconds=2))
    assert out.final_phase == OrchestrationPhase.RAW_RESULT_RETAINED
    assert out.succeeded is True
    assert out.poll_count == 3
    assert out.provider_status_snapshot.progress.percent_complete == 100
    assert out.raw_result.ingestion.evidence_source == RawResultEvidenceSource.INLINE_JSON
    assert out.page_summary.page_count_observed == 1
    assert "source_url" not in out.raw_result.provider.configuration
    assert [s for s in p.submitted[0].documents][0].pdf_source_url.startswith("https://")
    assert p.submitted[0].to_provider_json()["schema_version"] == "2026-07-10"
    assert len(p.submitted) == 1

@run_async
async def test_selected_standard_profile_is_preserved(tmp_path):
    p=FakeProvider(); c=Clock()
    p.statuses=[status(ProviderLifecycleStatus.PROVIDER_COMPLETED)]
    p.results=[inline_result("standard")]
    out=await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req(result_profile="standard"))
    assert out.raw_result.identity.provider_result_profile == "standard"

@run_async
async def test_result_not_ready_after_completed_polls_result_again(tmp_path):
    p=FakeProvider(); c=Clock()
    p.statuses=[status(ProviderLifecycleStatus.PROVIDER_COMPLETED)]
    p.results=[ProviderClientError(ProviderErrorDetail(ProviderErrorCategory.RESULT_NOT_READY,"not ready", retryable=True)), inline_result()]
    out=await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req())
    assert out.final_phase == OrchestrationPhase.RAW_RESULT_RETAINED
    assert c.t == 1.0
    assert out.poll_count == 1

@run_async
async def test_result_not_ready_is_bounded_and_sleep_clamped(tmp_path):
    p=FakeProvider(); c=RecordingClock()
    p.statuses=[status(ProviderLifecycleStatus.PROVIDER_COMPLETED)]
    p.results=[ProviderClientError(ProviderErrorDetail(ProviderErrorCategory.RESULT_NOT_READY,"not ready", retryable=True))] * 3
    with pytest.raises(OrchestrationError) as e:
        await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req(), PollingPolicy(timeout_seconds=5, initial_interval_seconds=2, max_interval_seconds=10, max_result_requests=2))
    assert e.value.category == OrchestrationErrorCategory.RESULT_UNAVAILABLE
    assert e.value.poll_count == 1
    assert c.sleeps == [2, 2]

@run_async
async def test_backoff_sequence_is_bounded_and_not_used_after_terminal(tmp_path):
    p=FakeProvider(); c=RecordingClock()
    p.statuses=[status(ProviderLifecycleStatus.QUEUED), status(ProviderLifecycleStatus.RUNNING), status(ProviderLifecycleStatus.RUNNING), status(ProviderLifecycleStatus.PROVIDER_COMPLETED)]
    p.results=[inline_result()]
    await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req(), PollingPolicy(timeout_seconds=30, initial_interval_seconds=1, max_interval_seconds=3))
    assert c.sleeps == [1, 2, 3]

@run_async
async def test_job_id_mismatch_fails_closed_before_polling(tmp_path):
    p=FakeProvider(); c=Clock(); p.submission=ProviderSubmission("other", "req-1", ProviderLifecycleStatus.QUEUED)
    with pytest.raises(OrchestrationError) as e:
        await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req())
    assert e.value.category == OrchestrationErrorCategory.IDENTITY_MISMATCH
    assert p.statuses == []
    assert len(p.submitted) == 1

@run_async
async def test_rejected_and_uncertain_submission_are_distinct(tmp_path):
    p=FakeProvider(); c=Clock(); p.submission=ProviderClientError(ProviderErrorDetail(ProviderErrorCategory.VALIDATION,"bad request"))
    with pytest.raises(OrchestrationError) as e:
        await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req())
    assert e.value.category == OrchestrationErrorCategory.SUBMISSION_REJECTED
    assert len(p.submitted) == 1
    p=FakeProvider(); p.submission=ProviderClientError(ProviderErrorDetail(ProviderErrorCategory.TIMEOUT,"timed out", retryable=True))
    with pytest.raises(OrchestrationError) as e:
        await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req())
    assert e.value.category == OrchestrationErrorCategory.SUBMISSION_UNCERTAIN
    assert e.value.phase == OrchestrationPhase.SUBMISSION_UNCERTAIN
    assert e.value.poll_count == 0
    assert e.value.provider_job_id == "job-1"
    assert "reconcile provider job" in e.value.safe_message
    assert len(p.submitted) == 1

@run_async
async def test_failed_and_expired_do_not_ingest(tmp_path):
    for s, cat in [(ProviderLifecycleStatus.FAILED, OrchestrationErrorCategory.PROVIDER_FAILED),(ProviderLifecycleStatus.EXPIRED, OrchestrationErrorCategory.JOB_EXPIRED)]:
        p=FakeProvider(); c=Clock(); p.statuses=[status(s)]
        out=await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req())
        assert out.error.category == cat
        assert out.raw_result is None
        assert p.results == []

@run_async
async def test_partial_failed_with_and_without_evidence(tmp_path):
    p=FakeProvider(); c=Clock(); p.statuses=[status(ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED)]; p.results=[inline_result(status=ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED)]
    out=await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req())
    assert out.final_phase == OrchestrationPhase.PROVIDER_PARTIAL_FAILED and out.succeeded is False and out.raw_result is not None
    p=FakeProvider(); p.statuses=[status(ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED)]; p.results=[ProviderResult("job-1","req-1",ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED,"full",None,[],None)]
    out=await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req())
    assert out.raw_result is None and out.final_phase == OrchestrationPhase.PROVIDER_PARTIAL_FAILED
    p=FakeProvider(); p.statuses=[status(ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED)]
    digest = hashlib.sha256(b"x").hexdigest()
    p.results=[ProviderResult("job-1","req-1",ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED,"full",{"artifact_id":"a1","size_bytes":1,"sha256":digest},[],{"job_id":"job-1","status":"partial_failed","profile":"full"})]
    p.artifact=ProviderArtifact("job-1", b"x", ArtifactMetadata("a1", None, "application/json", None, 1, digest))
    out=await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req())
    assert out.raw_result is not None and out.succeeded is False

@run_async
async def test_artifact_download_preserves_exact_bytes_and_metadata(tmp_path):
    body = b"\x1f\x8bcompressed"
    digest = hashlib.sha256(body).hexdigest()
    p=FakeProvider(); c=Clock(); p.statuses=[status(ProviderLifecycleStatus.PROVIDER_COMPLETED)]
    p.results=[ProviderResult("job-1","req-1",ProviderLifecycleStatus.PROVIDER_COMPLETED,"full",{"artifact_id":"a1","format":"application/json","compression":"gzip","size_bytes":len(body),"sha256":digest},[],{"job_id":"job-1","status":"completed","profile":"full"})]
    p.artifact=ProviderArtifact("job-1", body, ArtifactMetadata("a1", "https://provider/art", "application/json", "gzip", len(body), digest))
    out=await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req())
    assert out.raw_result.ingestion.evidence_source == RawResultEvidenceSource.ARTIFACT_BYTES
    assert LocalStorageProvider(tmp_path).get(out.raw_result.ingestion.storage_reference) == body
    assert out.raw_result.ingestion.artifact_metadata.provider_metadata.get("download_endpoint") is None

@run_async
async def test_malformed_results_fail_closed(tmp_path):
    p=FakeProvider(); c=Clock(); p.statuses=[status(ProviderLifecycleStatus.PROVIDER_COMPLETED)]
    p.results=[ProviderResult("job-1","other",ProviderLifecycleStatus.PROVIDER_COMPLETED,"full",None,[],{"job_id":"job-1","status":"completed","profile":"full"})]
    with pytest.raises(OrchestrationError) as e:
        await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req())
    assert e.value.category == OrchestrationErrorCategory.RESULT_MALFORMED
    p=FakeProvider(); p.statuses=[status(ProviderLifecycleStatus.PROVIDER_COMPLETED)]
    p.results=[ProviderResult("job-1","req-1",ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED,"full",None,[],{"job_id":"job-1","status":"partial_failed","profile":"full"})]
    with pytest.raises(OrchestrationError):
        await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req())
    p=FakeProvider(); p.statuses=[status(ProviderLifecycleStatus.PROVIDER_COMPLETED)]
    p.results=[ProviderResult("job-1","req-1",ProviderLifecycleStatus.PROVIDER_COMPLETED,"full",{"artifact_id":"a"},[{"raw_result":[]}],{"job_id":"job-1"})]
    with pytest.raises(OrchestrationError):
        await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req())

@run_async
async def test_malformed_completed_page_mapping_fails_but_partial_mapping_is_retained_as_diagnostic(tmp_path):
    bad_pages=[{"page_number":2,"page_index":0,"local_page_index":0,"source_page_range":[2,2]}]
    p=FakeProvider(); c=Clock(); p.statuses=[status(ProviderLifecycleStatus.PROVIDER_COMPLETED)]
    p.results=[ProviderResult("job-1","req-1",ProviderLifecycleStatus.PROVIDER_COMPLETED,"full",None,[{"raw_result":bad_pages}],{"job_id":"job-1","status":"completed","profile":"full","documents":[{"raw_result":bad_pages}]})]
    with pytest.raises(OrchestrationError) as e:
        await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req())
    assert e.value.category == OrchestrationErrorCategory.RESULT_MALFORMED
    p=FakeProvider(); p.statuses=[status(ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED)]
    p.results=[ProviderResult("job-1","req-1",ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED,"full",None,[{"raw_result":bad_pages}],{"job_id":"job-1","status":"partial_failed","profile":"full","documents":[{"raw_result":bad_pages}]})]
    out=await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req())
    assert out.page_summary.mapping_valid is False

@run_async
async def test_timeout_and_max_poll_count_use_injected_clock_and_sleep(tmp_path):
    p=FakeProvider(); c=Clock(); p.statuses=[status(ProviderLifecycleStatus.RUNNING)]*10
    with pytest.raises(OrchestrationError) as e:
        await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req(), PollingPolicy(timeout_seconds=2, initial_interval_seconds=1, max_interval_seconds=1))
    assert e.value.category == OrchestrationErrorCategory.TIMEOUT
    assert e.value.poll_count == 2
    p=FakeProvider(); c=Clock(); p.statuses=[status(ProviderLifecycleStatus.RUNNING)]*10
    with pytest.raises(OrchestrationError) as e:
        await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req(), PollingPolicy(timeout_seconds=30, max_status_requests=1))
    assert e.value.poll_count == 1

@run_async
async def test_ingestion_failure_after_completed_is_orchestration_failure(tmp_path):
    p=FakeProvider(); c=Clock(); p.statuses=[status(ProviderLifecycleStatus.PROVIDER_COMPLETED)]; p.results=[inline_result()]
    out=await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req(source_checksum_sha256="b"*64, raw_result_storage_reference="not-valid"))
    assert out.error.category == OrchestrationErrorCategory.INGESTION_FAILURE
    assert out.provider_terminal_status == ProviderLifecycleStatus.PROVIDER_COMPLETED

@run_async
async def test_provider_error_messages_are_redacted(tmp_path):
    p=FakeProvider(); c=Clock(); p.submission=ProviderClientError(ProviderErrorDetail(ProviderErrorCategory.TIMEOUT,"Bearer secret https://source.example/file.pdf", retryable=True))
    with pytest.raises(OrchestrationError) as e:
        await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req())
    text = repr(e.value) + str(e.value)
    assert "secret" not in text
    assert "source.example" not in text

@run_async
async def test_no_background_tasks_no_close_no_db_or_route_imports(tmp_path):
    import sys
    before = set(sys.modules)
    p=FakeProvider(); c=Clock(); p.statuses=[status(ProviderLifecycleStatus.PROVIDER_COMPLETED)]; p.results=[inline_result()]
    await ProcessingOrchestrator(provider=p, storage=LocalStorageProvider(tmp_path), sleep=c.sleep, monotonic=c).run_once(req())
    assert p.closed is False
    newly_imported = set(sys.modules) - before
    assert "sqlalchemy" not in newly_imported
    assert "app.routes" not in newly_imported
    assert "app.routers" not in newly_imported
