"""Synthetic visual timing and local durable-persistence contracts only."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import s0_visual_asset_generation_metrics as metrics
from app import s0_visual_asset_generation_observability as observer
from app.models import Base
from app.processing.processing_event_model import ProcessingEvent
from tests.test_s0_provider_source_download_observability import (
    DOCUMENT_ID,
    RUN_ID,
    SOURCE_FILE_ID,
    _seed_base,
)


REVISION = "a" * 40


def _asset(identifier: str):
    return NS(asset_id=identifier)


def _rendition(identifier: str):
    return NS(rendition_id=identifier)


def _candidate(*, assets=(), renditions=()):
    return NS(assets=tuple(assets), renditions=tuple(renditions))


def _enriched_candidate():
    return _candidate(
        assets=(_asset("asset-1"),),
        renditions=(_rendition("rendition-1"),),
    )


def _envelope():
    return NS(
        identity=NS(
            atlas_attempt_id=RUN_ID,
            document_id=DOCUMENT_ID,
            source_file_id=SOURCE_FILE_ID,
        )
    )


def _decoded(rows):
    return [NS(event_name=name, payload=payload) for name, payload in rows]


def _measure(rows, *, run_status="succeeded", **kwargs):
    return metrics.measure_visual_asset_generation(
        _decoded(rows),
        expected_source_scope=metrics.source_scope_id(SOURCE_FILE_ID),
        run_status=run_status,
        **kwargs,
    )


@pytest.fixture
def capture(monkeypatch):
    rows = []
    monkeypatch.setattr(observer, "_revision", lambda: REVISION)
    monkeypatch.setattr(
        observer,
        "_persist",
        lambda _root, records: rows.extend(copy.deepcopy(records)) or True,
    )
    ticks = iter((100, 350))
    monkeypatch.setattr(observer, "_clock_read", lambda: next(ticks))
    monkeypatch.setattr(observer, "_clock_resolution_ns", lambda: 1)
    return rows


def test_successful_exact_boundary_is_observed(capture):
    before = _candidate()
    after = _enriched_candidate()

    def canonicalize(_instance, _envelope_value):
        return observer.measure_visual_asset_generation(
            lambda candidate: after,
            before,
        )

    assert observer.observe_canonicalization(canonicalize, object(), _envelope()) is after
    result = _measure(capture)
    assert result["status"] == "observed"
    assert result["value"] == 250 / 1e9
    assert result["breakdown"]["generated_asset_count"] == 1
    assert result["breakdown"]["generated_rendition_count"] == 1
    assert [payload["ordinal"] for _name, payload in capture] == [0, 1]


def test_zero_duration_is_a_real_measurement(monkeypatch, capture):
    monkeypatch.setattr(observer, "_clock_read", lambda: 100)

    def canonicalize(_instance, _envelope_value):
        return observer.measure_visual_asset_generation(
            lambda _candidate_value: _enriched_candidate(),
            _candidate(),
        )

    observer.observe_canonicalization(canonicalize, object(), _envelope())
    assert _measure(capture)["value"] == 0


def test_no_visual_call_is_instrumented_but_not_available(capture):
    sentinel = object()
    assert (
        observer.observe_canonicalization(
            lambda _instance, _envelope_value: sentinel,
            object(),
            _envelope(),
        )
        is sentinel
    )
    terminal = capture[-1][1]
    assert terminal["operation_outcome"] == "not_required"
    assert terminal["reason"] == "no_visual_enrichment_call"
    assert _measure(capture)["status"] == "not_available"


def test_delegate_failure_is_preserved_and_private_message_is_not_recorded(capture):
    failure = ValueError("synthetic-private-filename.pdf")

    def canonicalize(_instance, _envelope_value):
        def fail(_candidate_value):
            raise failure

        return observer.measure_visual_asset_generation(fail, _candidate())

    with pytest.raises(ValueError) as caught:
        observer.observe_canonicalization(canonicalize, object(), _envelope())
    assert caught.value is failure
    assert capture[-1][1]["operation_outcome"] == "failed"
    assert "synthetic-private-filename.pdf" not in str(capture)
    assert _measure(capture, run_status="failed")["status"] == "not_available"


def test_multiple_calls_execute_normally_but_invalidate_evidence(capture):
    calls = []

    def enrich(_candidate_value):
        calls.append(True)
        return _enriched_candidate()

    def canonicalize(_instance, _envelope_value):
        observer.measure_visual_asset_generation(enrich, _candidate())
        return observer.measure_visual_asset_generation(enrich, _candidate())

    observer.observe_canonicalization(canonicalize, object(), _envelope())
    assert calls == [True, True]
    assert capture[-1][1]["operation_outcome"] == "invalid"
    assert capture[-1][1]["reason"] == "multiple_visual_enrichment_calls"
    assert _measure(capture)["status"] == "not_available"


@pytest.mark.parametrize(
    ("ticks", "resolution", "reason"),
    [
        ((None, None), 1, "clock_unavailable"),
        ((200, 100), 1, "invalid_clock"),
        ((100, 200), None, "clock_unavailable"),
        ((100, metrics.MAX_NS + 102), 1, "invalid_clock"),
    ],
)
def test_unavailable_or_invalid_clock_never_becomes_zero(
    monkeypatch, capture, ticks, resolution, reason
):
    values = iter(ticks)
    monkeypatch.setattr(observer, "_clock_read", lambda: next(values))
    monkeypatch.setattr(observer, "_clock_resolution_ns", lambda: resolution)

    def canonicalize(_instance, _envelope_value):
        return observer.measure_visual_asset_generation(
            lambda _candidate_value: _enriched_candidate(),
            _candidate(),
        )

    observer.observe_canonicalization(canonicalize, object(), _envelope())
    terminal = capture[-1][1]
    assert terminal["duration_ns"] is None
    assert terminal["reason"] == reason
    assert _measure(capture)["status"] == "not_available"


@pytest.mark.parametrize(
    "result",
    [
        NS(assets=None, renditions=()),
        _candidate(assets=(_asset("duplicate"), _asset("duplicate"))),
        _candidate(assets=(_asset("asset-1"),), renditions=(NS(rendition_id=None),)),
    ],
)
def test_invalid_result_counts_fail_closed(monkeypatch, capture, result):
    def canonicalize(_instance, _envelope_value):
        return observer.measure_visual_asset_generation(
            lambda _candidate_value: result,
            _candidate(),
        )

    observer.observe_canonicalization(canonicalize, object(), _envelope())
    assert capture[-1][1]["reason"] == "invalid_result_counts"
    assert _measure(capture)["status"] == "not_available"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda rows: rows.pop(0),
        lambda rows: rows.pop(),
        lambda rows: rows.append(copy.deepcopy(rows[0])),
        lambda rows: rows.append(copy.deepcopy(rows[-1])),
        lambda rows: rows[-1][1].update(ordinal=0),
        lambda rows: rows[-1][1].update(duration_ns=True),
        lambda rows: rows[-1][1].update(duration_ns=-1),
        lambda rows: rows[-1][1].update(generated_asset_count=0),
        lambda rows: rows[-1][1].update(generated_rendition_count=0),
        lambda rows: rows[-1][1].update(backend_revision="b" * 40),
        lambda rows: rows[-1][1].update(source_scope_id="source_" + "c" * 64),
        lambda rows: rows[-1][1].update(observation_id="vasset_" + "d" * 32),
        lambda rows: rows[-1][1].update(reason="unknown"),
        lambda rows: rows[-1][1].update(extra="private"),
    ],
)
def test_missing_duplicate_mixed_or_malformed_evidence_fails_closed(capture, mutate):
    root = observer.Root(RUN_ID, DOCUMENT_ID, SOURCE_FILE_ID, REVISION)
    root.terminal = {
        "operation_outcome": "completed",
        "clock_status": "measured",
        "duration_ns": 10,
        "generated_asset_count": 1,
        "generated_rendition_count": 1,
        "reason": "none",
    }
    rows = root.records()
    mutate(rows)
    assert _measure(rows)["status"] == "not_available"


@pytest.mark.parametrize(
    "key",
    ["filename", "path", "url", "token", "raw_storage_reference", "extra"],
)
def test_privacy_and_unknown_fields_are_rejected(key):
    root = observer.Root(RUN_ID, DOCUMENT_ID, SOURCE_FILE_ID, REVISION)
    rows = root.records()
    for index in range(2):
        candidate = copy.deepcopy(rows)
        candidate[index][1][key] = "synthetic-private-value"
        assert _measure(candidate)["status"] == "not_available"


def test_empty_incomplete_and_uninspectable_evidence():
    assert _measure([])["status"] == "not_instrumented"
    root = observer.Root(RUN_ID, DOCUMENT_ID, SOURCE_FILE_ID, REVISION)
    rows = root.records()
    assert _measure(rows, evidence_incomplete=True)["status"] == "not_available"
    assert (
        _measure(rows, uninspectable_event_names={metrics.TERMINAL})["status"]
        == "not_available"
    )


@pytest.mark.parametrize(
    "raw",
    [
        '{"ordinal":0,"ordinal":1}',
        '{"duration_ns":NaN}',
        '{"duration_ns":Infinity}',
        "[]",
        "null",
        "bad",
    ],
)
def test_strict_json_decoder(raw):
    assert metrics.decode_visual_asset_generation_payload(raw) == ({}, False)


def test_missing_staging_marker_is_a_noop(monkeypatch):
    monkeypatch.setattr(observer, "_revision", lambda: None)
    sentinel = object()
    called = []

    def delegate(_instance, _envelope_value):
        called.append(True)
        return sentinel

    monkeypatch.setattr(
        observer,
        "_persist",
        lambda *_args, **_kwargs: pytest.fail("disabled observer touched persistence"),
    )
    assert observer.observe_canonicalization(delegate, object(), _envelope()) is sentinel
    assert called == [True]


@pytest.fixture
def local_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'visual-generation.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as database:
        _seed_base(database)
    yield factory
    engine.dispose()


def test_atomic_durable_batch_identity_and_duplicate_rejection(
    local_database, monkeypatch
):
    monkeypatch.setattr(observer, "_revision", lambda: REVISION)
    root = observer.Root(RUN_ID, DOCUMENT_ID, SOURCE_FILE_ID, REVISION)
    root.terminal = {
        "operation_outcome": "completed",
        "clock_status": "measured",
        "duration_ns": 25,
        "generated_asset_count": 1,
        "generated_rendition_count": 2,
        "reason": "none",
    }
    rows = root.records()
    assert observer._persist(root, rows, session_factory=local_database)
    assert not observer._persist(root, rows, session_factory=local_database)
    with local_database() as database:
        retained = (
            database.query(ProcessingEvent)
            .filter(ProcessingEvent.event_name.in_(metrics.EVENT_NAMES))
            .all()
        )
    assert len(retained) == 2
    decoded = [
        (row.event_name, json.loads(row.payload_json))
        for row in sorted(retained, key=lambda row: json.loads(row.payload_json)["ordinal"])
    ]
    assert _measure(decoded)["status"] == "observed"


def test_persistence_rejects_wrong_identity(local_database, monkeypatch):
    monkeypatch.setattr(observer, "_revision", lambda: REVISION)
    root = observer.Root(RUN_ID, DOCUMENT_ID, "wrong-source", REVISION)
    assert not observer._persist(root, root.records(), session_factory=local_database)
    with local_database() as database:
        assert (
            database.query(ProcessingEvent)
            .filter(ProcessingEvent.event_name.in_(metrics.EVENT_NAMES))
            .count()
            == 0
        )
