from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Document, ProcessingRun, SourceFile, encode_json_text
from app.processing.processing_event_model import ProcessingEvent
from app.processing.processing_events import MAX_EVENT_PAYLOAD_BYTES
from app.processing.s0_baseline import collect_s0_run_snapshot


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _metric(snapshot, key: str):
    for metric in (*snapshot.required_metrics, *snapshot.auxiliary_metrics):
        if metric.key == key:
            return metric
    raise AssertionError(f"metric not found: {key}")


def _seed_phase2_run(db, *, with_measurements: bool = True) -> str:
    started = datetime(2026, 8, 24, 22, 47, 28)
    document = Document(
        id="doc-phase2-map",
        title="private-title",
        file_type="pdf",
        pages_count=1,
        status="completed",
        created_at=started - timedelta(seconds=3),
        updated_at=started + timedelta(seconds=150),
    )
    source = SourceFile(
        id="source-phase2-map",
        document_id=document.id,
        original_filename="private.pdf",
        file_type="pdf",
        byte_size=784_772,
        checksum_sha256="b" * 64,
        retained=1,
        is_primary=1,
        created_at=started - timedelta(seconds=2),
    )
    run = ProcessingRun(
        id="run-row-phase2-map",
        processing_run_id="pdf-ingest-phase2-map",
        document_id=document.id,
        source_file_id=source.id,
        status="succeeded",
        started_at=started,
        completed_at=started + timedelta(seconds=146.677670),
        created_at=started,
    )
    db.add_all([document, source, run])
    db.flush()

    if with_measurements:
        events = [
            (
                "phase2-classification",
                "PDF_S0_CLASSIFICATION_MEASURED",
                {
                    "elapsed_seconds": 20.049503,
                    "page_count": 1,
                    "process_cpu_delta_seconds": 13.320083,
                    "process_lifetime_peak_rss_mb": 495.5,
                    "process_rss_endpoint_mb": 428.3,
                    "resource_scope": "process_wide",
                    "succeeded": True,
                },
                22,
            ),
            (
                "phase2-preprocessing",
                "PDF_S0_PREPROCESSING_MEASURED",
                {
                    "elapsed_seconds": 43.562509,
                    "page_count": 1,
                    "process_cpu_delta_seconds": 26.5654,
                    "process_lifetime_peak_rss_mb": 652.4,
                    "process_rss_endpoint_mb": 517.4,
                    "provider_input_size_bytes": 982_161,
                    "resource_scope": "process_wide",
                    "succeeded": True,
                },
                45,
            ),
            (
                "phase2-canonicalization",
                "PDF_S0_CANONICALIZATION_MEASURED",
                {
                    "elapsed_seconds": 15.962947,
                    "process_cpu_delta_seconds": 0.765504,
                    "process_lifetime_peak_rss_mb": 652.4,
                    "process_rss_endpoint_mb": 533.8,
                    "raw_result_size_bytes": 52_305,
                    "resource_scope": "process_wide",
                    "succeeded": True,
                },
                152,
            ),
            (
                "phase2-provider",
                "PDF_S0_PROVIDER_INTEGRATION_MEASURED",
                {
                    "canonicalizer_configured": True,
                    "elapsed_seconds": 105.885544,
                    "poll_count": 11,
                    "process_cpu_delta_seconds": 1.134836,
                    "process_lifetime_peak_rss_mb": 652.4,
                    "process_rss_endpoint_mb": 533.8,
                    "provider_input_size_bytes": 982_161,
                    "provider_status": "provider_completed",
                    "raw_result_size_bytes": 52_305,
                    "resource_scope": "process_wide",
                    "succeeded": True,
                },
                153,
            ),
        ]
        for event_id, event_name, payload, seconds in events:
            db.add(
                ProcessingEvent(
                    id=event_id,
                    processing_run_id=run.processing_run_id,
                    document_id=document.id,
                    schema_version="atlas.processing.event.v1",
                    event_name=event_name,
                    severity="info",
                    payload_json=encode_json_text(payload),
                    created_at=started + timedelta(seconds=seconds),
                )
            )

    db.commit()
    return run.processing_run_id


def test_phase2_events_map_only_semantically_matching_required_metrics() -> None:
    db = _session()
    run_id = _seed_phase2_run(db)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    preprocessing_wall = _metric(snapshot, "preprocessing_wall_seconds")
    assert preprocessing_wall.status == "observed"
    assert preprocessing_wall.value == 43.562509
    assert "PDF_S0_PREPROCESSING_MEASURED" in preprocessing_wall.source

    canonicalization = _metric(snapshot, "canonicalization_duration_seconds")
    assert canonicalization.status == "observed"
    assert canonicalization.value == 15.962947
    assert "PDF_S0_CANONICALIZATION_MEASURED" in canonicalization.source

    assert _metric(snapshot, "preprocessing_cpu_seconds").status == "not_instrumented"
    assert _metric(snapshot, "backend_upload_peak_memory_mb").status == "not_instrumented"
    assert _metric(snapshot, "backend_to_modal_transport_bytes").status == "not_instrumented"
    assert _metric(snapshot, "ocr_batch_duration_seconds").status == "not_instrumented"
    assert _metric(snapshot, "raw_result_shard_bytes").status == "not_instrumented"


def test_phase2_process_wide_and_size_evidence_is_auxiliary_only() -> None:
    db = _session()
    run_id = _seed_phase2_run(db)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    cpu = _metric(snapshot, "preprocessing_process_cpu_delta_seconds")
    assert cpu.status == "observed"
    assert cpu.value == 26.5654
    assert "process-wide" in (cpu.note or "").lower()

    rss = _metric(snapshot, "preprocessing_process_rss_endpoint_mb")
    assert rss.status == "observed"
    assert rss.value == 517.4
    assert "process-wide" in (rss.note or "").lower()

    peak = _metric(snapshot, "process_lifetime_peak_rss_mb")
    assert peak.status == "observed"
    assert peak.value == 652.4
    assert "process-lifetime" in (peak.note or "").lower()

    provider_elapsed = _metric(snapshot, "provider_integration_wall_seconds")
    assert provider_elapsed.status == "observed"
    assert provider_elapsed.value == 105.885544
    assert "not equivalent" in (provider_elapsed.note or "").lower()

    provider_input = _metric(snapshot, "provider_input_size_bytes")
    assert provider_input.status == "observed"
    assert provider_input.value == 982_161
    assert "not backend-to-modal" in (provider_input.note or "").lower()

    raw_result = _metric(snapshot, "raw_result_size_bytes")
    assert raw_result.status == "observed"
    assert raw_result.value == 52_305
    assert "not a per-shard" in (raw_result.note or "").lower()


def test_phase2_measurement_events_are_allowlisted_without_private_payload_fields() -> None:
    db = _session()
    run_id = _seed_phase2_run(db)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert set(snapshot.observed_event_names) >= {
        "PDF_S0_CLASSIFICATION_MEASURED",
        "PDF_S0_PREPROCESSING_MEASURED",
        "PDF_S0_CANONICALIZATION_MEASURED",
        "PDF_S0_PROVIDER_INTEGRATION_MEASURED",
    }
    assert set(snapshot.observed_numeric_event_fields) >= {
        "elapsed_seconds",
        "process_cpu_delta_seconds",
        "process_lifetime_peak_rss_mb",
        "process_rss_endpoint_mb",
        "provider_input_size_bytes",
        "raw_result_size_bytes",
    }


def test_historical_run_without_phase2_events_reports_mapped_metrics_unavailable() -> None:
    db = _session()
    run_id = _seed_phase2_run(db, with_measurements=False)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    preprocessing_wall = _metric(snapshot, "preprocessing_wall_seconds")
    canonicalization = _metric(snapshot, "canonicalization_duration_seconds")
    assert preprocessing_wall.status == "not_available"
    assert preprocessing_wall.value is None
    assert canonicalization.status == "not_available"
    assert canonicalization.value is None
    assert _metric(snapshot, "preprocessing_cpu_seconds").status == "not_instrumented"


def test_process_wide_auxiliaries_reject_wrong_resource_scope_without_hiding_wall_time() -> None:
    db = _session()
    run_id = _seed_phase2_run(db)
    event = db.get(ProcessingEvent, "phase2-preprocessing")
    assert event is not None
    event.payload_json = encode_json_text(
        {
            "elapsed_seconds": 43.562509,
            "page_count": 1,
            "process_cpu_delta_seconds": 26.5654,
            "process_lifetime_peak_rss_mb": 652.4,
            "process_rss_endpoint_mb": 517.4,
            "provider_input_size_bytes": 982_161,
            "resource_scope": "stage_local",
            "succeeded": True,
        }
    )
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert _metric(snapshot, "preprocessing_wall_seconds").status == "observed"
    assert _metric(snapshot, "preprocessing_wall_seconds").value == 43.562509

    cpu = _metric(snapshot, "preprocessing_process_cpu_delta_seconds")
    rss = _metric(snapshot, "preprocessing_process_rss_endpoint_mb")
    assert cpu.status == "not_available"
    assert cpu.value is None
    assert rss.status == "not_available"
    assert rss.value is None


def test_duplicate_successful_stage_measurements_are_not_collapsed_even_if_one_is_unusable() -> None:
    db = _session()
    run_id = _seed_phase2_run(db)
    started = datetime(2026, 8, 24, 22, 47, 28)
    db.add(
        ProcessingEvent(
            id="phase2-preprocessing-duplicate",
            processing_run_id=run_id,
            document_id="doc-phase2-map",
            schema_version="atlas.processing.event.v1",
            event_name="PDF_S0_PREPROCESSING_MEASURED",
            severity="info",
            payload_json=encode_json_text(
                {
                    "process_cpu_delta_seconds": 30.0,
                    "process_lifetime_peak_rss_mb": 700.0,
                    "process_rss_endpoint_mb": 550.0,
                    "provider_input_size_bytes": 982_161,
                    "resource_scope": "process_wide",
                    "succeeded": True,
                }
            ),
            created_at=started + timedelta(seconds=46),
        )
    )
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    preprocessing_wall = _metric(snapshot, "preprocessing_wall_seconds")
    assert preprocessing_wall.status == "not_available"
    assert preprocessing_wall.value is None
    assert "multiple successful" in (preprocessing_wall.note or "").lower()


def test_truncated_window_marks_retained_phase2_measurement_partial() -> None:
    db = _session()
    run_id = _seed_phase2_run(db)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id, max_events=2)

    assert snapshot.event_window_truncated is True
    preprocessing_wall = _metric(snapshot, "preprocessing_wall_seconds")
    assert preprocessing_wall.status == "partial"
    assert preprocessing_wall.value == 43.562509
    assert "incomplete" in (preprocessing_wall.note or "").lower()

    canonicalization = _metric(snapshot, "canonicalization_duration_seconds")
    assert canonicalization.status == "not_available"
    assert canonicalization.value is None


def test_unrelated_elapsed_seconds_cannot_satisfy_phase2_required_measurements() -> None:
    db = _session()
    run_id = _seed_phase2_run(db, with_measurements=False)
    started = datetime(2026, 8, 24, 22, 47, 28)
    db.add(
        ProcessingEvent(
            id="unrelated-elapsed",
            processing_run_id=run_id,
            document_id="doc-phase2-map",
            schema_version="atlas.processing.event.v1",
            event_name="PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL",
            severity="info",
            payload_json=encode_json_text(
                {"elapsed_seconds": 99.0, "shard_count": 2}
            ),
            created_at=started + timedelta(seconds=60),
        )
    )
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert "elapsed_seconds" in snapshot.observed_numeric_event_fields
    assert _metric(snapshot, "preprocessing_wall_seconds").status == "not_available"
    assert _metric(snapshot, "preprocessing_wall_seconds").value is None
    assert _metric(snapshot, "canonicalization_duration_seconds").status == "not_available"
    assert _metric(snapshot, "canonicalization_duration_seconds").value is None


def test_malformed_same_name_event_blocks_definitive_preprocessing_measurement() -> None:
    db = _session()
    run_id = _seed_phase2_run(db)
    started = datetime(2026, 8, 24, 22, 47, 28)
    db.add(
        ProcessingEvent(
            id="phase2-preprocessing-malformed",
            processing_run_id=run_id,
            document_id="doc-phase2-map",
            schema_version="atlas.processing.event.v1",
            event_name="PDF_S0_PREPROCESSING_MEASURED",
            severity="info",
            payload_json="{malformed-json",
            created_at=started + timedelta(seconds=46),
        )
    )
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert snapshot.event_payload_decode_incomplete is True
    preprocessing_wall = _metric(snapshot, "preprocessing_wall_seconds")
    assert preprocessing_wall.status == "not_available"
    assert preprocessing_wall.value is None
    assert "could not be inspected" in (preprocessing_wall.note or "").lower()


def test_oversized_same_name_event_blocks_definitive_canonicalization_measurement() -> None:
    db = _session()
    run_id = _seed_phase2_run(db)
    started = datetime(2026, 8, 24, 22, 47, 28)
    db.add(
        ProcessingEvent(
            id="phase2-canonicalization-oversized",
            processing_run_id=run_id,
            document_id="doc-phase2-map",
            schema_version="atlas.processing.event.v1",
            event_name="PDF_S0_CANONICALIZATION_MEASURED",
            severity="info",
            payload_json="x" * (MAX_EVENT_PAYLOAD_BYTES + 1),
            created_at=started + timedelta(seconds=152, microseconds=1),
        )
    )
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert snapshot.event_payload_oversized_incomplete is True
    canonicalization = _metric(snapshot, "canonicalization_duration_seconds")
    assert canonicalization.status == "not_available"
    assert canonicalization.value is None
    assert "could not be inspected" in (canonicalization.note or "").lower()
