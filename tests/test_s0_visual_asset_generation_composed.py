"""Final Staging composition and baseline-mapping regressions."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import s0_visual_asset_generation_metrics as metrics
from app import s0_visual_asset_generation_observability as observer
from app.models import Base
from app.processing import pdf_canonicalization, pdf_ingestion, s0_baseline
from tests.test_s0_provider_source_download_observability import (
    DOCUMENT_ID,
    RUN_ID,
    SOURCE_FILE_ID,
    _seed_base,
)
from tests.test_s0_visual_asset_generation_observability import REVISION


def _factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'visual-composed.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as database:
        _seed_base(database)
    return engine, factory


def _root(*, generated_assets=1, generated_renditions=1):
    root = observer.Root(RUN_ID, DOCUMENT_ID, SOURCE_FILE_ID, REVISION)
    root.terminal = {
        "operation_outcome": "completed",
        "clock_status": "measured",
        "duration_ns": 1_250_000_000,
        "generated_asset_count": generated_assets,
        "generated_rendition_count": generated_renditions,
        "reason": "none",
    }
    return root


def test_final_runtime_wrappers_are_installed_last_and_idempotently():
    canonicalize = pdf_canonicalization.PdfCanonicalizationService.canonicalize
    enrich = pdf_canonicalization.enrich_candidate_with_pdf_visual_assets
    assert getattr(canonicalize, "_s0_visual_asset_generation_installed", False)
    assert getattr(enrich, "_s0_visual_asset_generation_installed", False)

    source = Path(pdf_ingestion.__file__).read_text(encoding="utf-8")
    visual_index = source.index("install_visual_asset_generation_observability()")
    assert visual_index > source.index("install_preprocessing_cpu_observability()")
    assert visual_index > source.index("install_pdf_visual_crop_lifecycle_compat()")
    assert visual_index > source.index("install_opencv_v4_modal_bridge()")

    observer.install_visual_asset_generation_observability()
    assert pdf_canonicalization.PdfCanonicalizationService.canonicalize is canonicalize
    assert pdf_canonicalization.enrich_candidate_with_pdf_visual_assets is enrich


def test_required_metric_maps_only_exact_durable_evidence(tmp_path, monkeypatch):
    engine, factory = _factory(tmp_path)
    monkeypatch.setattr(observer, "_revision", lambda: REVISION)
    try:
        root = _root(generated_assets=2, generated_renditions=3)
        assert observer._persist(root, root.records(), session_factory=factory)
        with factory() as database:
            snapshot = s0_baseline.collect_s0_run_snapshot(
                database,
                processing_run_id=RUN_ID,
            )
        required = {reading.key: reading for reading in snapshot.required_metrics}
        visual = required["visual_asset_generation_seconds"]
        assert visual.status == "observed"
        assert visual.value == 1.25
        assert visual.source == "processing_events.S0_VISUAL_ASSET_GENERATION_*"
        auxiliary = {reading.key: reading for reading in snapshot.auxiliary_metrics}
        breakdown = auxiliary["visual_asset_generation_breakdown"]
        assert breakdown.status == "observed"
        assert breakdown.value["generated_asset_count"] == 2
        assert breakdown.value["generated_rendition_count"] == 3
        assert required["backend_upload_peak_memory_mb"].status == "not_instrumented"
        assert required["preprocessing_cpu_seconds"].status == "not_instrumented"
        assert required["upload_to_reader_ready_seconds"].status == "not_instrumented"
        assert set(metrics.EVENT_NAMES).issubset(snapshot.observed_event_names)
    finally:
        engine.dispose()


def test_not_required_and_oversized_payload_never_map_as_observed(
    tmp_path, monkeypatch
):
    engine, factory = _factory(tmp_path)
    monkeypatch.setattr(observer, "_revision", lambda: REVISION)
    try:
        root = observer.Root(RUN_ID, DOCUMENT_ID, SOURCE_FILE_ID, REVISION)
        assert observer._persist(root, root.records(), session_factory=factory)
        with factory() as database:
            snapshot = s0_baseline.collect_s0_run_snapshot(
                database,
                processing_run_id=RUN_ID,
            )
        required = {reading.key: reading for reading in snapshot.required_metrics}
        assert required["visual_asset_generation_seconds"].status == "not_available"

        with factory() as database:
            terminal = (
                database.query(s0_baseline.ProcessingEvent)
                .filter(s0_baseline.ProcessingEvent.event_name == metrics.TERMINAL)
                .one()
            )
            terminal.payload_json = json.dumps({"padding": "x" * 9000})
            database.commit()
        with factory() as database:
            snapshot = s0_baseline.collect_s0_run_snapshot(
                database,
                processing_run_id=RUN_ID,
            )
        required = {reading.key: reading for reading in snapshot.required_metrics}
        assert required["visual_asset_generation_seconds"].status == "not_available"
    finally:
        engine.dispose()


def test_overlay_is_idempotent_on_composed_runtime():
    from scripts.apply_s0_visual_asset_generation_observability import main

    paths = (
        Path("app/processing/pdf_ingestion.py"),
        Path("app/processing/s0_baseline.py"),
    )
    before = {path: path.read_bytes() for path in paths}
    main()
    main()
    assert before == {path: path.read_bytes() for path in paths}
