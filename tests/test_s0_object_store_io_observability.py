from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import s0_object_store_io_observability as io
from app.models import Base, Document, ProcessingRun, SourceFile, encode_json_text
from app.processing.processing_event_model import ProcessingEvent
from app.processing.s0_baseline import MAX_EVENT_PAYLOAD_BYTES, collect_s0_run_snapshot
from app.storage.models import PutResult, StorageReference

RUN_ID = "pdf-ingest-" + "4" * 32
DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
SOURCE_FILE_ID = "22222222-2222-4222-8222-222222222222"
SOURCE_REF = "src_" + "a" * 32


class _Storage:
    def __init__(self):
        self.values = {SOURCE_REF: b"source"}

    def put(self, data, reference=None, *, expected_size=None, expected_sha256=None):
        ref = StorageReference.parse(str(reference or ("src_" + "b" * 32)))
        self.values[str(ref)] = bytes(data)
        return PutResult(ref, len(data), "c" * 64)

    def get(self, reference):
        return self.values[str(reference)]

    def delete(self, reference):
        self.values.pop(str(reference), None)

    def exists(self, reference):
        return str(reference) in self.values


def test_observed_storage_counts_source_and_generated_operations() -> None:
    tracker = io._RunTracker(RUN_ID, DOCUMENT_ID, SOURCE_REF)
    storage = io._ObservedStorageProvider(_Storage(), tracker)
    assert storage.get(SOURCE_REF) == b"source"
    generated_ref = "src_" + "b" * 32
    storage.put(b"artifact", generated_ref)
    assert storage.get(generated_ref) == b"artifact"
    source = tracker.stages[io.STAGE_PROCESSING_SOURCE]
    assert (source.read_bytes, source.read_operations) == (6, 1)
    generated = tracker.stages[io.STAGE_GENERATED_ARTIFACT]
    assert (generated.write_bytes, generated.write_operations) == (8, 1)
    assert (generated.read_bytes, generated.read_operations) == (8, 1)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _metric(snapshot, key):
    return next(metric for metric in snapshot.required_metrics if metric.key == key)


def _event(event_id, stage, *, read_bytes=0, write_bytes=0, read_ops=0, write_ops=0, scope_id="processing_run", ordinal=1):
    return ProcessingEvent(
        id=event_id,
        processing_run_id=RUN_ID,
        document_id=DOCUMENT_ID,
        schema_version="atlas.processing.event.v1",
        event_name=io.STORAGE_IO_EVENT,
        severity="info",
        payload_json=encode_json_text({
            "succeeded": True,
            "measurement_scope": io.STORAGE_IO_SCOPE,
            "stage": stage,
            "scope_id": scope_id,
            "scope_ordinal": ordinal,
            "read_bytes": read_bytes,
            "write_bytes": write_bytes,
            "read_operations": read_ops,
            "write_operations": write_ops,
        }),
        created_at=datetime(2026, 8, 26, 10, 0, ordinal),
    )


def _uninspectable_event(event_id: str, payload_json: str, *, second: int) -> ProcessingEvent:
    return ProcessingEvent(
        id=event_id,
        processing_run_id=RUN_ID,
        document_id=DOCUMENT_ID,
        schema_version="atlas.processing.event.v1",
        event_name=io.STORAGE_IO_EVENT,
        severity="info",
        payload_json=payload_json,
        created_at=datetime(2026, 8, 26, 10, 1, second),
    )


def _seed(db):
    started = datetime(2026, 8, 26, 10, 0, 0)
    db.add(Document(id=DOCUMENT_ID, title="private", file_type="pdf", pages_count=1, status="completed", created_at=started, updated_at=started))
    db.add(SourceFile(id=SOURCE_FILE_ID, document_id=DOCUMENT_ID, original_filename="private.pdf", file_type="pdf", byte_size=456, checksum_sha256="d" * 64, retained=1, is_primary=1, created_at=started))
    db.add(ProcessingRun(id="row", processing_run_id=RUN_ID, document_id=DOCUMENT_ID, source_file_id=SOURCE_FILE_ID, status="succeeded", started_at=started, completed_at=started + timedelta(seconds=10), created_at=started))
    db.add_all([
        _event("io-upload", io.STAGE_UPLOAD_SOURCE_RETENTION, write_bytes=456, write_ops=1, scope_id="upload_acceptance"),
        _event("io-source", io.STAGE_PROCESSING_SOURCE, read_bytes=456, read_ops=1),
        _event("io-generated", io.STAGE_GENERATED_ARTIFACT, read_bytes=900, write_bytes=1000, read_ops=1, write_ops=1),
        _event("io-transport", io.STAGE_PROVIDER_SOURCE_TRANSPORT, read_bytes=1000, read_ops=1, scope_id="transport_0123456789abcdef"),
    ])
    db.commit()


def test_collector_maps_total_and_stage_io_without_calling_it_network_bytes() -> None:
    db = _session()
    _seed(db)
    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    total = _metric(snapshot, "backend_object_store_bytes")
    assert total.status == "observed"
    assert total.value == 3812
    assert "not unique object size or network transport" in (total.note or "")
    stages = _metric(snapshot, "object_store_stage_io")
    assert stages.status == "observed"
    assert stages.value["total_read_bytes"] == 2356
    assert stages.value["total_write_bytes"] == 1456
    assert stages.value["stages"][io.STAGE_UPLOAD_SOURCE_RETENTION]["write_bytes"] == 456
    assert stages.value["stages"][io.STAGE_PROVIDER_SOURCE_TRANSPORT]["read_bytes"] == 1000


def test_collector_fails_closed_for_duplicate_stage_scope() -> None:
    db = _session()
    _seed(db)
    db.add(_event("io-source-duplicate", io.STAGE_PROCESSING_SOURCE, read_bytes=456, read_ops=1))
    db.commit()
    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    assert _metric(snapshot, "backend_object_store_bytes").status == "not_available"
    assert "duplicate" in (_metric(snapshot, "object_store_stage_io").note or "").lower()


def test_collector_fails_closed_when_source_retention_does_not_match() -> None:
    db = _session()
    _seed(db)
    event = db.get(ProcessingEvent, "io-upload")
    event.payload_json = encode_json_text({
        "succeeded": True,
        "measurement_scope": io.STORAGE_IO_SCOPE,
        "stage": io.STAGE_UPLOAD_SOURCE_RETENTION,
        "scope_id": "upload_acceptance",
        "scope_ordinal": 1,
        "read_bytes": 0,
        "write_bytes": 455,
        "read_operations": 0,
        "write_operations": 1,
    })
    db.commit()
    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    assert _metric(snapshot, "backend_object_store_bytes").status == "not_available"
    assert "does not match" in (_metric(snapshot, "backend_object_store_bytes").note or "").lower()


def test_collector_fails_closed_for_malformed_same_name_payload() -> None:
    db = _session()
    _seed(db)
    db.add(_uninspectable_event("io-malformed", "{", second=1))
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    for key in ("backend_object_store_bytes", "object_store_stage_io"):
        metric = _metric(snapshot, key)
        assert metric.status == "not_available"
        assert "payload could not be inspected" in (metric.note or "")


def test_collector_fails_closed_for_oversized_same_name_payload() -> None:
    db = _session()
    _seed(db)
    db.add(
        _uninspectable_event(
            "io-oversized",
            "x" * (MAX_EVENT_PAYLOAD_BYTES + 1),
            second=2,
        )
    )
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    for key in ("backend_object_store_bytes", "object_store_stage_io"):
        metric = _metric(snapshot, key)
        assert metric.status == "not_available"
        assert "payload could not be inspected" in (metric.note or "")


def test_transport_event_uses_hashed_scope_and_retrieval_ordinal(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(io, "staging_storage_io_observability_enabled", lambda: True)
    monkeypatch.setattr(io, "_record_stage_event", lambda **kwargs: captured.update(kwargs) or True)
    grant = SimpleNamespace(atlas_attempt_id=RUN_ID, document_id=DOCUMENT_ID, grant_id="tg_private")
    assert io.record_provider_source_transport_read(grant, 99, 3) is True
    assert captured["stage"] == io.STAGE_PROVIDER_SOURCE_TRANSPORT
    assert captured["read_bytes"] == 99
    assert captured["scope_ordinal"] == 3
    assert captured["scope_id"].startswith("transport_")
    assert "tg_private" not in captured["scope_id"]


def test_dynamic_storage_dependency_observes_active_pdf_tracker() -> None:
    tracker = io._RunTracker(RUN_ID, DOCUMENT_ID, SOURCE_REF)
    delegate = _Storage()
    dependency = io._wrap_storage_dependency(lambda: delegate)

    assert dependency() is delegate
    token = io._CURRENT_TRACKER.set(tracker)
    try:
        observed = dependency()
        assert isinstance(observed, io._ObservedStorageProvider)
        observed.put(b"subset", "src_" + "e" * 32)
    finally:
        io._CURRENT_TRACKER.reset(token)

    generated = tracker.stages[io.STAGE_GENERATED_ARTIFACT]
    assert (generated.write_bytes, generated.write_operations) == (6, 1)


def test_storage_for_tracker_does_not_stack_same_tracker_observer() -> None:
    tracker = io._RunTracker(RUN_ID, DOCUMENT_ID, SOURCE_REF)
    observed = io._ObservedStorageProvider(_Storage(), tracker)
    assert io._storage_for_tracker(observed, tracker) is observed


def test_federated_storage_keeps_outer_type_and_observes_leaves(monkeypatch) -> None:
    from app.storage.federated import FederatedStorageProvider
    from app.storage import visual_assets

    tracker = io._RunTracker(RUN_ID, DOCUMENT_ID, SOURCE_REF)
    primary = _Storage()
    secondary = _Storage()
    federated = FederatedStorageProvider(primary, secondary)

    observed = io._storage_for_tracker(federated, tracker)
    assert observed is federated
    assert isinstance(observed, FederatedStorageProvider)
    assert isinstance(observed.primary, io._ObservedStorageProvider)
    assert isinstance(observed.secondary, io._ObservedStorageProvider)

    monkeypatch.setattr(visual_assets, "_staging_artifact_is_active", lambda: True)
    selected = visual_assets.select_visual_asset_storage(observed)
    assert selected is observed.secondary

    selected.put(b"visual", "src_" + "f" * 32)
    generated = tracker.stages[io.STAGE_GENERATED_ARTIFACT]
    assert (generated.write_bytes, generated.write_operations) == (6, 1)


def test_federated_provider_input_secondary_remains_observable() -> None:
    from app.storage.federated import FederatedStorageProvider
    from app.storage.provider_input_access import ProviderInputStorageRouter

    class _Client:
        def generate_presigned_url(self, *args, **kwargs):
            return "https://example.invalid/object"

    class _PresignStorage(_Storage):
        bucket = "bucket"
        client = _Client()

        def object_key(self, reference):
            return str(reference)

    tracker = io._RunTracker(RUN_ID, DOCUMENT_ID, SOURCE_REF)
    federated = FederatedStorageProvider(_Storage(), _PresignStorage())
    observed = io._storage_for_tracker(federated, tracker)

    # ProviderInputStorageRouter must still choose the durable secondary, but
    # that leaf remains observed so the real write is counted.
    router = ProviderInputStorageRouter(observed)
    assert router.remote is observed.secondary
    router.put(b"subset", "src_" + "9" * 32)
    generated = tracker.stages[io.STAGE_GENERATED_ARTIFACT]
    assert (generated.write_bytes, generated.write_operations) == (6, 1)
