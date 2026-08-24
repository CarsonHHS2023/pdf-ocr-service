from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from app.processing import s0_phase2_stage_observability as stage


RUN_ID = "pdf-ingest-" + "a" * 32
DOCUMENT_ID = "document-phase2-test"


def _capture(monkeypatch):
    events: list[dict[str, object]] = []

    def fake_record_processing_event(**kwargs):
        events.append(dict(kwargs))
        return True

    monkeypatch.setattr(stage, "record_processing_event", fake_record_processing_event)
    monkeypatch.setattr(
        stage,
        "resource_snapshot",
        lambda: {"rss_mb": 123.5, "peak_rss_mb": 150.25, "disk_free_mb": 999.0},
    )
    return events


def _clock(monkeypatch, *, wall_start=10.0, wall_end=12.5, cpu_start=3.0, cpu_end=4.0):
    wall = iter((wall_start, wall_end))
    cpu = iter((cpu_start, cpu_end))
    monkeypatch.setattr(stage, "perf_counter", lambda: next(wall))
    monkeypatch.setattr(stage, "process_time", lambda: next(cpu))


def test_preprocessing_wrapper_records_wall_and_explicit_process_wide_resources(monkeypatch) -> None:
    events = _capture(monkeypatch)
    _clock(monkeypatch)

    def delegate(*, processing_attempt_id, source_pdf_bytes):
        assert processing_attempt_id == RUN_ID
        assert source_pdf_bytes == b"%PDF-test"
        return SimpleNamespace(
            preprocessing=SimpleNamespace(page_count=7),
            byte_size=4567,
        )

    wrapped = stage._wrap_preprocessing(delegate)
    result = wrapped(
        processing_attempt_id=RUN_ID,
        source_pdf_bytes=b"%PDF-test",
    )

    assert result.byte_size == 4567
    assert len(events) == 1
    event = events[0]
    assert event["processing_run_id"] == RUN_ID
    assert event["event_name"] == "PDF_S0_PREPROCESSING_MEASURED"
    assert event["severity"] == "info"
    payload = event["payload"]
    assert payload["succeeded"] is True
    assert payload["elapsed_seconds"] == 2.5
    assert payload["process_cpu_delta_seconds"] == 1.0
    assert payload["resource_scope"] == "process_wide"
    assert payload["process_rss_endpoint_mb"] == 123.5
    assert payload["process_lifetime_peak_rss_mb"] == 150.25
    assert "cpu_seconds" not in payload
    assert "rss_mb" not in payload
    assert "peak_rss_mb" not in payload
    assert payload["page_count"] == 7
    assert payload["provider_input_size_bytes"] == 4567


def test_classification_wrapper_uses_bound_processing_identity(monkeypatch) -> None:
    events = _capture(monkeypatch)
    _clock(monkeypatch, wall_start=20.0, wall_end=21.25, cpu_start=6.0, cpu_end=6.5)

    wrapped = stage._wrap_classification(
        lambda source: [{"page_number": number} for number in range(1, 4)],
        run_id_getter=lambda: RUN_ID,
    )
    result = wrapped(object())

    assert len(result) == 3
    payload = events[0]["payload"]
    assert events[0]["processing_run_id"] == RUN_ID
    assert events[0]["event_name"] == "PDF_S0_CLASSIFICATION_MEASURED"
    assert payload["elapsed_seconds"] == 1.25
    assert payload["process_cpu_delta_seconds"] == 0.5
    assert payload["resource_scope"] == "process_wide"
    assert payload["page_count"] == 3


def test_canonicalization_wrapper_records_raw_result_size_without_changing_result(monkeypatch) -> None:
    events = _capture(monkeypatch)
    _clock(monkeypatch, wall_start=30.0, wall_end=34.0, cpu_start=8.0, cpu_end=9.25)

    expected = SimpleNamespace(candidate_id="candidate-phase2")

    def delegate(service, envelope):
        return expected

    wrapped = stage._wrap_canonicalization(delegate)
    envelope = SimpleNamespace(
        identity=SimpleNamespace(
            atlas_attempt_id=RUN_ID,
            document_id=DOCUMENT_ID,
        ),
        ingestion=SimpleNamespace(payload_size_bytes=4321),
    )

    result = wrapped(object(), envelope)

    assert result is expected
    event = events[0]
    assert event["processing_run_id"] == RUN_ID
    assert event["document_id"] == DOCUMENT_ID
    assert event["event_name"] == "PDF_S0_CANONICALIZATION_MEASURED"
    payload = event["payload"]
    assert payload["elapsed_seconds"] == 4.0
    assert payload["process_cpu_delta_seconds"] == 1.25
    assert payload["resource_scope"] == "process_wide"
    assert payload["raw_result_size_bytes"] == 4321


def test_provider_wrapper_records_one_logical_integration_measurement(monkeypatch) -> None:
    events = _capture(monkeypatch)
    _clock(monkeypatch, wall_start=40.0, wall_end=46.0, cpu_start=10.0, cpu_end=11.0)

    expected = SimpleNamespace(
        error=None,
        poll_count=9,
        raw_result_size_bytes=7654,
        provider_terminal_status=SimpleNamespace(value="provider_completed"),
        canonicalization=SimpleNamespace(candidate_id="candidate-provider-logical"),
    )

    async def delegate(service, request):
        return expected

    wrapped = stage._wrap_provider_process(delegate)
    service = SimpleNamespace(canonicalizer=object())
    request = SimpleNamespace(
        processing_attempt_id=RUN_ID,
        provider_job_id="pdf-job-phase2-logical",
        retained_source=SimpleNamespace(document_id=DOCUMENT_ID),
    )

    result = asyncio.run(wrapped(service, request))

    assert result is expected
    assert len(events) == 1
    event = events[0]
    assert event["processing_run_id"] == RUN_ID
    assert event["document_id"] == DOCUMENT_ID
    assert event["event_name"] == "PDF_S0_PROVIDER_INTEGRATION_MEASURED"
    payload = event["payload"]
    assert payload["succeeded"] is True
    assert payload["canonicalizer_configured"] is True
    assert payload["elapsed_seconds"] == 6.0
    assert payload["process_cpu_delta_seconds"] == 1.0
    assert payload["resource_scope"] == "process_wide"
    assert payload["poll_count"] == 9
    assert payload["raw_result_size_bytes"] == 7654
    assert payload["provider_status"] == "provider_completed"
    assert payload["provider_job_id"] == "pdf-job-phase2-logical"


def test_installer_wraps_final_sharding_aware_process_not_base_service() -> None:
    source = inspect.getsource(stage.install_s0_phase2_stage_observability)
    assert "ShardingAwareEndToEndProcessingIntegrationService.process" in source
    assert "integration.EndToEndProcessingIntegrationService.process =" not in source


def test_measurement_failure_is_fail_open_for_telemetry_but_preserves_delegate_error(monkeypatch) -> None:
    events = _capture(monkeypatch)
    _clock(monkeypatch, wall_start=50.0, wall_end=50.75, cpu_start=12.0, cpu_end=12.1)

    error = RuntimeError("delegate failed")

    def delegate(*, processing_attempt_id):
        raise error

    wrapped = stage._wrap_preprocessing(delegate)
    with pytest.raises(RuntimeError) as caught:
        wrapped(processing_attempt_id=RUN_ID)

    assert caught.value is error
    assert events[0]["severity"] == "error"
    payload = events[0]["payload"]
    assert payload["succeeded"] is False
    assert payload["error_type"] == "RuntimeError"
    assert payload["elapsed_seconds"] == 0.75
    assert payload["resource_scope"] == "process_wide"


def test_recording_failure_never_changes_delegate_result(monkeypatch) -> None:
    _clock(monkeypatch, wall_start=60.0, wall_end=61.0, cpu_start=13.0, cpu_end=13.2)
    monkeypatch.setattr(
        stage,
        "resource_snapshot",
        lambda: {"rss_mb": 1, "peak_rss_mb": 2},
    )

    def broken_recorder(**kwargs):
        raise RuntimeError("telemetry unavailable")

    monkeypatch.setattr(stage, "record_processing_event", broken_recorder)
    expected = object()
    wrapped = stage._wrap_classification(
        lambda source: expected,
        run_id_getter=lambda: RUN_ID,
    )

    assert wrapped(object()) is expected
