from __future__ import annotations

from datetime import datetime

from app.models import encode_json_text
from app.processing.processing_event_model import ProcessingEvent
from app.processing.s0_baseline import collect_s0_run_snapshot
from tests.test_s0_object_store_io_observability import (
    DOCUMENT_ID,
    RUN_ID,
    _metric,
    _provider_measurement,
    _seed,
    _session,
    _sharding_terminal,
)


def _sharding_decision(
    required: bool,
    *,
    event_id: str = "provider-sharding-decision",
    second: int = 32,
) -> ProcessingEvent:
    return ProcessingEvent(
        id=event_id,
        processing_run_id=RUN_ID,
        document_id=DOCUMENT_ID,
        schema_version="atlas.processing.event.v1",
        event_name="PDF_PROVIDER_TRANSPORT_SHARDING_DECISION",
        severity="info",
        payload_json=encode_json_text(
            {
                "recognized_provider_input": True,
                "sharding_required": required,
            }
        ),
        created_at=datetime(2026, 8, 26, 10, 1, second),
    )


def test_successful_provider_without_sharding_proof_fails_closed() -> None:
    """Absence of sharding evidence must never be treated as one-scope proof."""
    db = _session()
    _seed(db)
    # The one retained transport scope is internally complete. This simulates a
    # sharded run where another shard's read+terminal evidence and the sharding
    # terminal diagnostic were both lost fail-open.
    db.add(_provider_measurement())
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    metric = _metric(snapshot, "backend_object_store_bytes")
    assert metric.status == "not_available"
    assert "absence cannot prove" in (metric.note or "").lower()


def test_explicit_nonsharded_decision_proves_one_terminal_scope() -> None:
    db = _session()
    _seed(db)
    db.add_all([_provider_measurement(), _sharding_decision(False)])
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    assert _metric(snapshot, "backend_object_store_bytes").status == "observed"
    assert _metric(snapshot, "object_store_stage_io").status == "observed"


def test_sharding_required_without_terminal_shard_count_fails_closed() -> None:
    db = _session()
    _seed(db)
    db.add_all([_provider_measurement(), _sharding_decision(True)])
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    metric = _metric(snapshot, "backend_object_store_bytes")
    assert metric.status == "not_available"
    assert "no successful terminal shard-count" in (metric.note or "").lower()


def test_sharding_terminal_can_prove_count_if_decision_event_was_lost() -> None:
    """A successful shard-count terminal is independently sufficient sharded proof."""
    db = _session()
    _seed(db)
    from tests.test_s0_object_store_io_observability import _terminal_event

    other_scope = "transport_fedcba9876543210"
    db.add_all(
        [
            _provider_measurement(),
            _sharding_terminal(2),
            _terminal_event("second-terminal", other_scope, 0, second=22),
        ]
    )
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    assert _metric(snapshot, "backend_object_store_bytes").status == "observed"


def test_nonsharded_decision_conflicting_with_sharding_terminal_fails_closed() -> None:
    db = _session()
    _seed(db)
    db.add_all(
        [
            _provider_measurement(),
            _sharding_decision(False),
            _sharding_terminal(1),
        ]
    )
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    metric = _metric(snapshot, "backend_object_store_bytes")
    assert metric.status == "not_available"
    assert "disagree" in (metric.note or "").lower()


def test_duplicate_sharding_decisions_fail_closed() -> None:
    db = _session()
    _seed(db)
    db.add_all(
        [
            _provider_measurement(),
            _sharding_decision(False),
            _sharding_decision(
                False,
                event_id="provider-sharding-decision-duplicate",
                second=33,
            ),
        ]
    )
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    metric = _metric(snapshot, "object_store_stage_io")
    assert metric.status == "not_available"
    assert "multiple provider sharding decision" in (metric.note or "").lower()


def test_invalid_sharding_decision_value_fails_closed() -> None:
    db = _session()
    _seed(db)
    invalid = _sharding_decision(False)
    invalid.payload_json = encode_json_text(
        {
            "recognized_provider_input": True,
            "sharding_required": "false",
        }
    )
    db.add_all([_provider_measurement(), invalid])
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    metric = _metric(snapshot, "backend_object_store_bytes")
    assert metric.status == "not_available"
    assert "invalid sharding_required" in (metric.note or "").lower()
