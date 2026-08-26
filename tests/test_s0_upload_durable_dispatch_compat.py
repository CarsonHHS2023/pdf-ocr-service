from __future__ import annotations

from types import SimpleNamespace

from app import s0_upload_boundary_observability as upload
from app import s0_upload_durable_dispatch_compat as compat


RUN_ID = "pdf-ingest-" + "d" * 32
DOCUMENT_ID = "document-durable-dispatch"
SOURCE_FILE_ID = "source-durable-dispatch"
DISPATCH_ID = "dispatch-durable-upload"


def _durable_dispatch_task(*args, **kwargs):
    return None


_durable_dispatch_task.__module__ = "app.processing.ingestion_dispatch"
_durable_dispatch_task.__name__ = "run_ingestion_dispatch"


def test_durable_dispatch_finalizes_before_telemetry_db_reads(monkeypatch) -> None:
    recorded: list[dict[str, object]] = []
    diagnostics: list[tuple[str, dict[str, object]]] = []
    call_order: list[str] = []

    def measured_clock():
        call_order.append("clock")
        return 12.5

    def resolve_dispatch(dispatch_id):
        assert dispatch_id == DISPATCH_ID
        call_order.append("resolve_dispatch")
        return RUN_ID, DOCUMENT_ID, SOURCE_FILE_ID

    def load_source(source_file_id):
        assert source_file_id == SOURCE_FILE_ID
        call_order.append("load_source")
        return 456

    monkeypatch.setattr(upload, "perf_counter", measured_clock)
    monkeypatch.setattr(compat, "_load_dispatch_identity", resolve_dispatch)
    monkeypatch.setattr(upload, "_load_accepted_source_size", load_source)
    monkeypatch.setattr(
        upload,
        "_record_success",
        lambda **kwargs: recorded.append(dict(kwargs)) or True,
    )
    monkeypatch.setattr(
        upload,
        "_diagnostic",
        lambda event, **fields: diagnostics.append((event, dict(fields))),
    )

    observation = upload._UploadObservation(
        wall_started=10.0,
        http_body_bytes_received=600,
        max_asgi_receive_chunk_bytes=128,
        uploadfile_read_total_bytes=456,
        max_uploadfile_read_bytes=456,
    )
    token = upload._CURRENT_UPLOAD.set(observation)
    try:
        wrapped = compat._wrap_upload_finalize(lambda func, args, kwargs: None)
        wrapped(_durable_dispatch_task, (DISPATCH_ID,), {})
    finally:
        upload._CURRENT_UPLOAD.reset(token)

    assert call_order == ["clock", "resolve_dispatch", "load_source"]
    assert observation.finalized is True
    assert diagnostics == []
    assert len(recorded) == 1
    event = recorded[0]
    assert event["processing_run_id"] == RUN_ID
    assert event["document_id"] == DOCUMENT_ID
    fields = event["fields"]
    assert fields["upload_duration_seconds"] == 2.5
    assert fields["accepted_source_size_bytes"] == 456
    assert fields["http_body_bytes_received"] == 600
    assert fields["max_asgi_receive_chunk_bytes"] == 128
    assert fields["uploadfile_read_total_bytes"] == 456
    assert fields["max_uploadfile_read_bytes"] == 456


def test_existing_background_wrapper_uses_later_finalize_extension(monkeypatch) -> None:
    recorded: list[dict[str, object]] = []
    monkeypatch.setattr(upload, "perf_counter", lambda: 12.5)
    monkeypatch.setattr(
        compat,
        "_load_dispatch_identity",
        lambda dispatch_id: (RUN_ID, DOCUMENT_ID, SOURCE_FILE_ID),
    )
    monkeypatch.setattr(upload, "_load_accepted_source_size", lambda source_id: 456)
    monkeypatch.setattr(
        upload,
        "_record_success",
        lambda **kwargs: recorded.append(dict(kwargs)) or True,
    )

    original_finalize = upload._finalize_from_background_task
    add_task = upload._wrap_background_add_task(
        lambda background_self, func, *args, **kwargs: "queued"
    )
    monkeypatch.setattr(
        upload,
        "_finalize_from_background_task",
        compat._wrap_upload_finalize(original_finalize),
    )

    observation = upload._UploadObservation(wall_started=10.0)
    token = upload._CURRENT_UPLOAD.set(observation)
    try:
        assert add_task(object(), _durable_dispatch_task, DISPATCH_ID) == "queued"
    finally:
        upload._CURRENT_UPLOAD.reset(token)

    assert observation.finalized is True
    assert len(recorded) == 1
    assert recorded[0]["processing_run_id"] == RUN_ID
    assert recorded[0]["document_id"] == DOCUMENT_ID


def test_non_dispatch_task_delegates_to_existing_finalize() -> None:
    calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def delegate(func, args, kwargs):
        calls.append((func, args, kwargs))

    wrapped = compat._wrap_upload_finalize(delegate)
    other_task = lambda: None
    wrapped(other_task, ("x",), {"y": "z"})

    assert calls == [(other_task, ("x",), {"y": "z"})]


def test_durable_dispatch_without_upload_context_does_not_measure(monkeypatch) -> None:
    recorded: list[dict[str, object]] = []
    monkeypatch.setattr(
        upload,
        "_record_success",
        lambda **kwargs: recorded.append(dict(kwargs)) or True,
    )

    wrapped = compat._wrap_upload_finalize(lambda func, args, kwargs: None)
    wrapped(_durable_dispatch_task, (DISPATCH_ID,), {})

    assert recorded == []


def test_dispatch_identity_resolver_supports_pdf_and_txt_rows() -> None:
    class FakeSession:
        def __init__(self, row):
            self.row = row
            self.closed = False

        def get(self, model, dispatch_id):
            assert model.__name__ == "IngestionDispatch"
            assert dispatch_id == DISPATCH_ID
            return self.row

        def close(self):
            self.closed = True

    pdf_session = FakeSession(
        SimpleNamespace(
            kind="pdf",
            document_id=DOCUMENT_ID,
            source_file_id=SOURCE_FILE_ID,
            processing_attempt_id=RUN_ID,
            txt_processing_run_ref=None,
        )
    )
    assert compat._load_dispatch_identity(
        DISPATCH_ID,
        session_factory=lambda: pdf_session,
    ) == (RUN_ID, DOCUMENT_ID, SOURCE_FILE_ID)
    assert pdf_session.closed is True

    txt_run_id = "txt-ingest-" + "e" * 32
    txt_session = FakeSession(
        SimpleNamespace(
            kind="txt",
            document_id=DOCUMENT_ID,
            source_file_id=SOURCE_FILE_ID,
            processing_attempt_id=None,
            txt_processing_run_ref=txt_run_id,
        )
    )
    assert compat._load_dispatch_identity(
        DISPATCH_ID,
        session_factory=lambda: txt_session,
    ) == (txt_run_id, DOCUMENT_ID, SOURCE_FILE_ID)
    assert txt_session.closed is True


def test_missing_or_invalid_dispatch_identity_fails_closed() -> None:
    class FakeSession:
        def __init__(self, row):
            self.row = row

        def get(self, model, dispatch_id):
            return self.row

        def close(self):
            return None

    assert compat._load_dispatch_identity(
        DISPATCH_ID,
        session_factory=lambda: FakeSession(None),
    ) is None

    invalid = SimpleNamespace(
        kind="pdf",
        document_id=DOCUMENT_ID,
        source_file_id=SOURCE_FILE_ID,
        processing_attempt_id=None,
        txt_processing_run_ref=None,
    )
    assert compat._load_dispatch_identity(
        DISPATCH_ID,
        session_factory=lambda: FakeSession(invalid),
    ) is None


def test_compat_installer_is_staging_gated(monkeypatch) -> None:
    monkeypatch.setattr(compat, "_INSTALLED", False)
    monkeypatch.setattr(upload, "staging_upload_observability_enabled", lambda: False)

    assert compat.install_s0_upload_durable_dispatch_compat() is False
    assert compat._INSTALLED is False
