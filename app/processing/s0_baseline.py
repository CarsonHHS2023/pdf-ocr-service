"""Read-only S0 baseline extraction from durable Atlas processing state.

This module deliberately does not add runtime instrumentation or mutate processing
state. It turns already-persisted Document/SourceFile/ProcessingRun/ProcessingEvent
records into a stable, explicit baseline snapshot and marks missing or partial S0
measurements honestly instead of inferring them from unrelated signals.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import math
import re
from typing import Any, Iterable

from sqlalchemy import LargeBinary, case, cast, func, select

from app.models import Document, ProcessingRun, SourceFile, decode_json_text
from app.processing.processing_event_model import ProcessingEvent
from app.processing.processing_events import MAX_EVENT_PAYLOAD_BYTES


S0_BASELINE_SCHEMA_VERSION = "atlas.s0.baseline.v1"
DEFAULT_MAX_EVENTS = 5000
MAX_EVENTS_HARD_LIMIT = 5000
_METRIC_STATUSES = frozenset(
    {"observed", "partial", "not_available", "not_instrumented"}
)
_SHA256_HEX_RE = re.compile(r"[0-9a-fA-F]{64}")
_SAFE_FILE_TYPES = frozenset({"pdf", "txt"})

# Event metadata is operator-visible output. Keep it fail-closed even though the
# current producer sanitizes/bounds payloads: retained legacy or abnormal rows may
# still contain arbitrary event names, payload keys, malformed JSON, or oversized
# Text values.
_SAFE_EVENT_NAMES = frozenset(
    {
        "PDF_DOCUMENT_TERMINAL_STATE",
        "PDF_INGESTION_UNHANDLED_FAILURE",
        "PDF_PROVIDER_DELIVERY_READY",
        "PDF_PROVIDER_REQUEST_STARTED",
        "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION",
        "PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL",
        "PDF_S0_RESOURCE_HEARTBEAT",
    }
)
_SAFE_NUMERIC_EVENT_FIELDS = frozenset(
    {
        "byte_size",
        "elapsed_seconds",
        "page_count",
        "page_number",
        "peak_rss_mb",
        "poll_count",
        "provider_http_status",
        "rss_mb",
        "shard_count",
        "shard_index",
        "size_bytes",
    }
)


@dataclass(frozen=True, slots=True)
class MetricReading:
    key: str
    label: str
    unit: str | None
    status: str
    value: object | None
    source: str
    note: str | None = None


@dataclass(frozen=True, slots=True)
class S0RunSnapshot:
    schema_version: str
    processing_run_id: str
    document_id: str
    run_status: str
    file_type: str | None
    source_file_id: str | None
    source_checksum_sha256: str | None
    started_at: str | None
    terminal_at: str | None
    event_window_truncated: bool
    event_payload_decode_incomplete: bool
    event_payload_oversized_incomplete: bool
    required_metrics: tuple[MetricReading, ...]
    auxiliary_metrics: tuple[MetricReading, ...]
    observed_event_names: tuple[str, ...]
    observed_numeric_event_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _BaselineRunRow:
    """Only the bounded ProcessingRun columns required by the S0 collector."""

    processing_run_id: str
    document_id: str
    source_file_id: str | None
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None


@dataclass(frozen=True, slots=True)
class _BaselineDocumentRow:
    """Only the Document columns required by the S0 collector."""

    id: str
    file_type: str | None
    pages_count: int | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class _BaselineSourceRow:
    """Only the SourceFile columns required by the S0 collector."""

    id: str
    document_id: str
    byte_size: int | None
    checksum_sha256: str | None


@dataclass(frozen=True, slots=True)
class _BoundedEventRow:
    """Only the small event fields S0 may materialize in the operator process."""

    event_name: str
    severity: str
    created_at: datetime
    payload_json: str | None
    payload_oversized: bool


_REQUIRED_METRIC_META: tuple[tuple[str, str, str | None], ...] = (
    ("source_byte_size", "Source byte size", "bytes"),
    ("page_count", "Source page count", "pages"),
    ("backend_upload_peak_memory_mb", "Backend upload peak memory", "MiB"),
    ("upload_duration_seconds", "Upload duration", "seconds"),
    (
        "backend_object_store_bytes",
        "Backend source/object-store bytes read/written",
        "bytes",
    ),
    ("preprocessing_wall_seconds", "Preprocessing wall time", "seconds"),
    ("preprocessing_cpu_seconds", "Preprocessing CPU time", "seconds"),
    (
        "backend_to_modal_transport_bytes",
        "Backend to Modal source transport",
        "bytes",
    ),
    ("modal_download_seconds", "Modal source download time", "seconds"),
    ("ocr_batch_duration_seconds", "OCR page/batch duration", "seconds"),
    ("gpu_busy_idle_proxy", "GPU busy/idle or bounded proxy", None),
    ("raw_result_shard_bytes", "Raw result/shard size", "bytes"),
    (
        "canonicalization_duration_seconds",
        "Canonicalization duration",
        "seconds",
    ),
    (
        "visual_asset_generation_seconds",
        "Visual asset generation duration",
        "seconds",
    ),
    ("object_store_stage_io", "Object-store reads/writes by stage", None),
    ("reader_open_latency_seconds", "Reader-open latency", "seconds"),
    ("reader_bounded_query_count", "Reader bounded query count", "queries"),
    (
        "upload_to_reader_ready_seconds",
        "Upload-to-Reader-ready latency",
        "seconds",
    ),
    ("failure_retry_counts", "Failure/retry counts", "count"),
)
_REQUIRED_META_BY_KEY = {key: (label, unit) for key, label, unit in _REQUIRED_METRIC_META}


def _metric(
    key: str,
    *,
    value: object | None,
    status: str,
    source: str,
    note: str | None = None,
) -> MetricReading:
    if status not in _METRIC_STATUSES:
        raise ValueError(f"unsupported S0 metric status: {status}")
    label, unit = _REQUIRED_META_BY_KEY[key]
    return MetricReading(
        key=key,
        label=label,
        unit=unit,
        status=status,
        value=value,
        source=source,
        note=note,
    )


def _missing_metric(key: str, *, source: str, note: str) -> MetricReading:
    return _metric(
        key,
        value=None,
        status="not_instrumented",
        source=source,
        note=note,
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    value = (end - start).total_seconds()
    # Equal timestamps are retained in some legacy lifecycle rows that are
    # explicitly not suitable timing evidence. Never promote zero/negative
    # lifecycle intervals to observed.
    return round(value, 6) if value > 0 else None


def _event_span_seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    value = (end - start).total_seconds()
    # Unlike lifecycle durations, a retained event window with one event (or
    # multiple events at the same persisted timestamp) has a legitimate zero span.
    return round(value, 6) if value >= 0 else None


def _terminal_at(run: _BaselineRunRow) -> datetime | None:
    """Return only the timestamp that matches the run's authoritative status."""
    if run.status == "succeeded":
        return run.completed_at
    if run.status == "failed":
        return run.failed_at
    return None


def _decode_event_payload(value: str | None) -> tuple[dict[str, Any], bool]:
    """Return a decoded mapping plus whether this bounded payload was usable."""
    if value is None:
        return {}, False
    try:
        decoded = decode_json_text(value)
    except Exception:
        return {}, False
    if not isinstance(decoded, dict):
        return {}, False
    return decoded, True


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _usable_numeric_event_value(field: str, value: object) -> float | None:
    number = _finite_number(value)
    if number is None:
        return None
    # Peak RSS is an absolute memory measurement. Legacy negative values are
    # invalid evidence even though they are mathematically finite.
    if field == "peak_rss_mb" and number < 0:
        return None
    return number


def _numeric_field_has_unusable_value(
    decoded_payloads: Iterable[dict[str, Any]],
    field: str,
) -> bool:
    """Return whether a retained decoded payload carries unusable numeric evidence."""
    for payload in decoded_payloads:
        if field not in payload:
            continue
        if _usable_numeric_event_value(field, payload[field]) is None:
            return True
    return False


def _max_numeric_field(
    decoded_payloads: Iterable[dict[str, Any]],
    field: str,
) -> float | None:
    values = [
        number
        for payload in decoded_payloads
        if (number := _usable_numeric_event_value(field, payload.get(field))) is not None
    ]
    return max(values) if values else None


def _retryable_field_has_unusable_value(
    decoded_payloads: Iterable[dict[str, Any]],
) -> bool:
    """Return whether any decoded payload carries a non-Boolean retryable value."""
    return any(
        "retryable" in payload and not isinstance(payload["retryable"], bool)
        for payload in decoded_payloads
    )


def _retryable_evidence_available(
    decoded_payloads: Iterable[dict[str, Any]],
) -> bool:
    """Return whether any decoded payload provides usable retryability evidence."""
    return any(
        "retryable" not in payload or isinstance(payload["retryable"], bool)
        for payload in decoded_payloads
    )


def _validated_sha256(value: object) -> str | None:
    """Return a strict SHA-256 hex identity or fail closed for retained metadata."""
    if not isinstance(value, str) or _SHA256_HEX_RE.fullmatch(value) is None:
        return None
    return value


def _validated_file_type(value: object) -> str | None:
    """Return only the bounded Atlas file-type identity used by S0 output."""
    if not isinstance(value, str) or value not in _SAFE_FILE_TYPES:
        return None
    return value


def _load_run_row(session, processing_run_id: str) -> _BaselineRunRow | None:
    """Load only S0-required run columns, excluding unconstrained legacy Text."""
    row = session.execute(
        select(
            ProcessingRun.processing_run_id.label("processing_run_id"),
            ProcessingRun.document_id.label("document_id"),
            ProcessingRun.source_file_id.label("source_file_id"),
            ProcessingRun.status.label("status"),
            ProcessingRun.started_at.label("started_at"),
            ProcessingRun.completed_at.label("completed_at"),
            ProcessingRun.failed_at.label("failed_at"),
        ).where(ProcessingRun.processing_run_id == processing_run_id)
    ).one_or_none()
    if row is None:
        return None
    return _BaselineRunRow(
        processing_run_id=row.processing_run_id,
        document_id=row.document_id,
        source_file_id=row.source_file_id,
        status=row.status,
        started_at=row.started_at,
        completed_at=row.completed_at,
        failed_at=row.failed_at,
    )


def _document_for_run(session, run: _BaselineRunRow) -> _BaselineDocumentRow | None:
    """Load only S0-required document fields; omit unrelated legacy Text columns."""
    row = session.execute(
        select(
            Document.id.label("id"),
            Document.file_type.label("file_type"),
            Document.pages_count.label("pages_count"),
            Document.created_at.label("created_at"),
        ).where(Document.id == run.document_id)
    ).one_or_none()
    if row is None:
        return None
    return _BaselineDocumentRow(
        id=row.id,
        file_type=row.file_type,
        pages_count=row.pages_count,
        created_at=row.created_at,
    )


def _source_file_for_run(session, run: _BaselineRunRow) -> _BaselineSourceRow | None:
    """Return only a source that the ProcessingRun explicitly identifies.

    A nullable legacy ``source_file_id`` is absence of durable association evidence;
    do not guess from another SourceFile belonging to the same Document. Only the
    bounded metadata required by S0 is projected.
    """
    if not run.source_file_id:
        return None
    row = session.execute(
        select(
            SourceFile.id.label("id"),
            SourceFile.document_id.label("document_id"),
            SourceFile.byte_size.label("byte_size"),
            SourceFile.checksum_sha256.label("checksum_sha256"),
        ).where(SourceFile.id == run.source_file_id)
    ).one_or_none()
    if row is None or row.document_id != run.document_id:
        return None
    return _BaselineSourceRow(
        id=row.id,
        document_id=row.document_id,
        byte_size=row.byte_size,
        checksum_sha256=row.checksum_sha256,
    )


def _event_aggregate_status(*, available: bool, incomplete: bool) -> str:
    if not available:
        return "not_available"
    return "partial" if incomplete else "observed"


def _validate_event_limit(max_events: int) -> None:
    if max_events <= 0:
        raise ValueError("max_events must be positive")
    if max_events > MAX_EVENTS_HARD_LIMIT:
        raise ValueError(
            f"max_events must be <= service hard limit {MAX_EVENTS_HARD_LIMIT}"
        )


def _payload_byte_length_expression(session):
    """Return a DB-side UTF-8 byte-length expression for supported S0 databases."""
    bind = session.get_bind()
    dialect_name = getattr(getattr(bind, "dialect", None), "name", None)
    if dialect_name == "postgresql":
        return func.octet_length(ProcessingEvent.payload_json)
    if dialect_name == "sqlite":
        # SQLite length(TEXT) counts characters, not bytes. CAST AS BLOB makes the
        # bound use encoded bytes, matching the producer's 8192-byte contract.
        return func.length(cast(ProcessingEvent.payload_json, LargeBinary))
    raise RuntimeError(
        f"S0 bounded event payload reads do not support database dialect: {dialect_name!r}"
    )


def _load_bounded_event_rows(
    session,
    *,
    processing_run_id: str,
    document_id: str,
    max_events: int,
) -> tuple[tuple[_BoundedEventRow, ...], bool]:
    """Load a bounded event window without materializing oversized Text payloads."""
    payload_bytes = _payload_byte_length_expression(session)
    payload_within_limit = payload_bytes <= MAX_EVENT_PAYLOAD_BYTES
    bounded_payload = case(
        (payload_within_limit, ProcessingEvent.payload_json),
        else_=None,
    ).label("bounded_payload_json")
    payload_oversized = case(
        (payload_bytes > MAX_EVENT_PAYLOAD_BYTES, True),
        else_=False,
    ).label("payload_oversized")

    # Do not select ProcessingEvent ORM entities here: doing so would materialize
    # the unconstrained Text column before Python could enforce a size check.
    result_rows = session.execute(
        select(
            ProcessingEvent.event_name.label("event_name"),
            ProcessingEvent.severity.label("severity"),
            ProcessingEvent.created_at.label("created_at"),
            bounded_payload,
            payload_oversized,
        )
        .where(
            ProcessingEvent.processing_run_id == processing_run_id,
            ProcessingEvent.document_id == document_id,
        )
        .order_by(ProcessingEvent.created_at.asc(), ProcessingEvent.id.asc())
        .limit(max_events + 1)
    ).all()

    event_window_truncated = len(result_rows) > max_events
    retained_rows = result_rows[:max_events]
    rows = tuple(
        _BoundedEventRow(
            event_name=row.event_name,
            severity=row.severity,
            created_at=row.created_at,
            payload_json=row.bounded_payload_json,
            payload_oversized=bool(row.payload_oversized),
        )
        for row in retained_rows
    )
    return rows, event_window_truncated


def collect_s0_run_snapshot(
    session,
    *,
    processing_run_id: str,
    max_events: int = DEFAULT_MAX_EVENTS,
) -> S0RunSnapshot:
    """Collect one read-only S0 snapshot for an existing ProcessingRun."""
    normalized_run_id = str(processing_run_id).strip()
    if not normalized_run_id:
        raise ValueError("processing_run_id is required")
    _validate_event_limit(max_events)

    run = _load_run_row(session, normalized_run_id)
    if run is None:
        raise LookupError(f"ProcessingRun not found: {normalized_run_id}")

    document = _document_for_run(session, run)
    if document is None:
        raise LookupError(f"Document not found for ProcessingRun: {normalized_run_id}")
    source = _source_file_for_run(session, run)

    rows, event_window_truncated = _load_bounded_event_rows(
        session,
        processing_run_id=normalized_run_id,
        document_id=run.document_id,
        max_events=max_events,
    )

    decoded_payloads: list[dict[str, Any]] = []
    event_payload_decode_incomplete = False
    event_payload_oversized_incomplete = False
    for row in rows:
        if row.payload_oversized:
            event_payload_oversized_incomplete = True
            continue
        payload, decode_valid = _decode_event_payload(row.payload_json)
        if not decode_valid:
            event_payload_decode_incomplete = True
            continue
        decoded_payloads.append(payload)
    decoded_payloads_tuple = tuple(decoded_payloads)

    event_names = tuple(
        sorted({row.event_name for row in rows if row.event_name in _SAFE_EVENT_NAMES})
    )
    numeric_fields = tuple(
        sorted(
            {
                key
                for payload in decoded_payloads_tuple
                for key, value in payload.items()
                if key in _SAFE_NUMERIC_EVENT_FIELDS
                and _usable_numeric_event_value(key, value) is not None
            }
        )
    )

    source_size = source.byte_size if source is not None else None
    source_size_available = (
        isinstance(source_size, int)
        and not isinstance(source_size, bool)
        and source_size > 0
    )
    source_checksum = _validated_sha256(
        source.checksum_sha256 if source is not None else None
    )
    page_count = document.pages_count
    page_count_available = (
        isinstance(page_count, int)
        and not isinstance(page_count, bool)
        and page_count > 0
    )
    error_count = sum(1 for row in rows if row.severity == "error")
    retryable_signal_count = sum(
        1 for payload in decoded_payloads_tuple if payload.get("retryable") is True
    )
    retryable_field_incomplete = _retryable_field_has_unusable_value(
        decoded_payloads_tuple
    )
    retryable_evidence_available = _retryable_evidence_available(
        decoded_payloads_tuple
    )
    peak_rss = _max_numeric_field(decoded_payloads_tuple, "peak_rss_mb")
    peak_rss_numeric_incomplete = _numeric_field_has_unusable_value(
        decoded_payloads_tuple,
        "peak_rss_mb",
    )

    required: list[MetricReading] = [
        _metric(
            "source_byte_size",
            value=source_size if source_size_available else None,
            status="observed" if source_size_available else "not_available",
            source="ProcessingRun.source_file_id -> SourceFile.byte_size",
            note=(
                None
                if source_size_available
                else "No positive source byte size is durably associated with this ProcessingRun."
            ),
        ),
        _metric(
            "page_count",
            value=page_count if page_count_available else None,
            status="observed" if page_count_available else "not_available",
            source="Document.pages_count",
            note=(
                None
                if page_count_available
                else "No positive page count is persisted for this document/run."
            ),
        ),
    ]

    for key, source_name, note in (
        (
            "backend_upload_peak_memory_mb",
            "upload instrumentation",
            "Generic processing RSS must not be substituted for upload-specific peak memory.",
        ),
        (
            "upload_duration_seconds",
            "upload instrumentation",
            "Upload start/end timing is not durably persisted.",
        ),
        (
            "backend_object_store_bytes",
            "object-store instrumentation",
            "Per-stage backend object-store byte counters are not durably persisted.",
        ),
        (
            "preprocessing_wall_seconds",
            "preprocessing instrumentation",
            "A dedicated durable preprocessing wall-time metric is not yet persisted.",
        ),
        (
            "preprocessing_cpu_seconds",
            "preprocessing instrumentation",
            "A dedicated durable preprocessing CPU-time metric is not yet persisted.",
        ),
        (
            "backend_to_modal_transport_bytes",
            "transport instrumentation",
            "Backend-to-Modal bytes are not durably separated from other provider/source routes.",
        ),
        (
            "modal_download_seconds",
            "Modal instrumentation",
            "Modal download timing is not available in backend durable state.",
        ),
        (
            "ocr_batch_duration_seconds",
            "OCR instrumentation",
            "OCR page/batch duration is not yet normalized into a durable S0 metric.",
        ),
        (
            "gpu_busy_idle_proxy",
            "GPU instrumentation",
            "No durable GPU busy/idle proxy is currently available.",
        ),
        (
            "raw_result_shard_bytes",
            "artifact instrumentation",
            "Raw-result/shard sizes are not normalized into a durable S0 metric.",
        ),
        (
            "canonicalization_duration_seconds",
            "canonicalization instrumentation",
            "Canonicalization duration is not durably normalized.",
        ),
        (
            "visual_asset_generation_seconds",
            "visual instrumentation",
            "Visual asset generation duration is not durably normalized.",
        ),
        (
            "object_store_stage_io",
            "object-store instrumentation",
            "Stage-specific object-store read/write counters are not durably normalized.",
        ),
        (
            "reader_open_latency_seconds",
            "Reader instrumentation",
            "Reader-open latency is outside ProcessingRun durable state today.",
        ),
        (
            "reader_bounded_query_count",
            "Reader instrumentation",
            "Reader query count is outside ProcessingRun durable state today.",
        ),
        (
            "upload_to_reader_ready_seconds",
            "cross-stage instrumentation",
            "Document acceptance/processing timestamps are not equivalent to upload-start -> Reader-ready latency.",
        ),
        (
            "failure_retry_counts",
            "retry instrumentation",
            "Durable error/retryable diagnostic signals may exist, but Atlas does not yet persist an explicit failure/retry-attempt counter contract.",
        ),
    ):
        required.append(_missing_metric(key, source=source_name, note=note))

    terminal = _terminal_at(run)
    processing_wall = _seconds(run.started_at, terminal)
    acceptance_to_terminal = _seconds(document.created_at, terminal)
    event_span = (
        _event_span_seconds(rows[0].created_at, rows[-1].created_at)
        if rows
        else None
    )
    row_aggregate_incomplete = event_window_truncated
    payload_evidence_incomplete = (
        event_window_truncated
        or event_payload_decode_incomplete
        or event_payload_oversized_incomplete
    )
    event_signal_status = _event_aggregate_status(
        available=bool(rows),
        incomplete=row_aggregate_incomplete,
    )
    retryable_signal_status = _event_aggregate_status(
        available=retryable_evidence_available,
        incomplete=payload_evidence_incomplete or retryable_field_incomplete,
    )
    peak_rss_status = _event_aggregate_status(
        available=peak_rss is not None,
        incomplete=payload_evidence_incomplete or peak_rss_numeric_incomplete,
    )

    retryable_signal_note = (
        "Retryability signal only; it does not prove that a retry attempt occurred."
    )
    if event_payload_decode_incomplete:
        retryable_signal_note += (
            " Payload-derived aggregate is incomplete because at least one retained "
            "bounded event payload could not be decoded."
        )
    if event_payload_oversized_incomplete:
        retryable_signal_note += (
            " At least one retained payload exceeded the service-owned byte limit and "
            "was omitted by the database projection before materialization."
        )
    if retryable_field_incomplete:
        retryable_signal_note += (
            " At least one retained bounded payload carried a non-Boolean retryable "
            "value, so retryability evidence is incomplete."
        )
    if event_window_truncated:
        retryable_signal_note += " Snapshot event window is also truncated."

    peak_rss_note = "Generic processing signal only; not promoted to upload peak memory."
    if event_payload_decode_incomplete:
        peak_rss_note += (
            " Maximum is incomplete because at least one retained bounded event payload "
            "could not be decoded."
        )
    if event_payload_oversized_incomplete:
        peak_rss_note += (
            " Maximum is incomplete because at least one retained payload exceeded the "
            "service-owned byte limit and was omitted before materialization."
        )
    if peak_rss_numeric_incomplete:
        peak_rss_note += (
            " Maximum is incomplete because at least one retained bounded payload "
            "carried an unusable peak_rss_mb numeric value."
        )
    if peak_rss is not None and event_window_truncated:
        peak_rss_note += " Maximum is partial because the durable event window is truncated."

    auxiliary: list[MetricReading] = [
        MetricReading(
            key="processing_run_wall_seconds",
            label="ProcessingRun start-to-terminal wall time",
            unit="seconds",
            status="observed" if processing_wall is not None else "not_available",
            value=processing_wall,
            source="ProcessingRun.started_at -> status-selected terminal timestamp",
            note="Useful lifecycle baseline; not equivalent to upload-to-Reader-ready latency.",
        ),
        MetricReading(
            key="document_acceptance_to_terminal_seconds",
            label="Document acceptance-to-processing-terminal wall time",
            unit="seconds",
            status="observed" if acceptance_to_terminal is not None else "not_available",
            value=acceptance_to_terminal,
            source="Document.created_at -> status-selected ProcessingRun terminal timestamp",
            note="A lower-bound lifecycle proxy, not upload-start timing.",
        ),
        MetricReading(
            key="durable_event_count",
            label="Durable event count in snapshot window",
            unit="events",
            status="observed",
            value=len(rows),
            source="processing_events",
            note=(
                "Window count only; total run event count is larger."
                if event_window_truncated
                else None
            ),
        ),
        MetricReading(
            key="durable_event_span_seconds",
            label="Durable event span in snapshot window",
            unit="seconds",
            status="observed" if event_span is not None else "not_available",
            value=event_span,
            source="processing_events.created_at",
            note=(
                "Window span only; it is not the complete durable event span."
                if event_window_truncated and event_span is not None
                else None
            ),
        ),
        MetricReading(
            key="durable_error_event_count",
            label="Durable error-severity event count in snapshot window",
            unit="events",
            status=event_signal_status,
            value=error_count if rows else None,
            source="processing_events.severity",
            note="Diagnostic signal only; not promoted to the required failure/retry counter.",
        ),
        MetricReading(
            key="durable_retryable_signal_count",
            label="Durable retryable=true signal count in snapshot window",
            unit="signals",
            status=retryable_signal_status,
            value=retryable_signal_count if retryable_evidence_available else None,
            source="processing_events.payload.retryable",
            note=retryable_signal_note,
        ),
        MetricReading(
            key="max_observed_peak_rss_mb",
            label="Maximum observed generic peak RSS signal",
            unit="MiB",
            status=peak_rss_status,
            value=peak_rss,
            source="processing_events.payload.peak_rss_mb",
            note=peak_rss_note,
        ),
    ]

    return S0RunSnapshot(
        schema_version=S0_BASELINE_SCHEMA_VERSION,
        processing_run_id=run.processing_run_id,
        document_id=run.document_id,
        run_status=run.status,
        file_type=_validated_file_type(document.file_type),
        source_file_id=source.id if source is not None else None,
        source_checksum_sha256=source_checksum,
        started_at=_iso(run.started_at),
        terminal_at=_iso(terminal),
        event_window_truncated=event_window_truncated,
        event_payload_decode_incomplete=event_payload_decode_incomplete,
        event_payload_oversized_incomplete=event_payload_oversized_incomplete,
        required_metrics=tuple(required),
        auxiliary_metrics=tuple(auxiliary),
        observed_event_names=event_names,
        observed_numeric_event_fields=numeric_fields,
    )


def render_s0_markdown(snapshots: Iterable[S0RunSnapshot]) -> str:
    """Render deterministic operator-facing Markdown for one or more snapshots."""
    items = tuple(snapshots)
    lines = [
        "# Atlas S0 Baseline Snapshot",
        "",
        f"Schema: `{S0_BASELINE_SCHEMA_VERSION}`",
        "",
        "This report is read-only. `not_instrumented` means Atlas does not yet persist a durable metric that can support the S0 claim; `partial` means its bounded source window or retained payload evidence is incomplete. Neither may be promoted to a complete measurement.",
        "",
    ]
    for snapshot in items:
        checksum = snapshot.source_checksum_sha256 or "unavailable"
        file_type = snapshot.file_type or "unavailable"
        lines.extend(
            [
                f"## `{snapshot.processing_run_id}`",
                "",
                f"- document ID: `{snapshot.document_id}`",
                f"- status: `{snapshot.run_status}`",
                f"- file type: `{file_type}`",
                f"- source checksum SHA-256: `{checksum}`",
                f"- event window truncated: `{str(snapshot.event_window_truncated).lower()}`",
                f"- event payload decode incomplete: `{str(snapshot.event_payload_decode_incomplete).lower()}`",
                f"- event payload oversized/incomplete: `{str(snapshot.event_payload_oversized_incomplete).lower()}`",
                "",
                "### Required S0 metrics",
                "",
                "| Metric | Status | Value | Unit | Source | Note |",
                "|---|---|---:|---|---|---|",
            ]
        )
        for metric in snapshot.required_metrics:
            value = "—" if metric.value is None else str(metric.value)
            note = (metric.note or "").replace("|", "\\|")
            source = metric.source.replace("|", "\\|")
            lines.append(
                f"| {metric.label} | `{metric.status}` | {value} | {metric.unit or '—'} | `{source}` | {note} |"
            )
        lines.extend(
            [
                "",
                "### Auxiliary lifecycle/observability metrics",
                "",
                "| Metric | Status | Value | Unit | Source | Note |",
                "|---|---|---:|---|---|---|",
            ]
        )
        for metric in snapshot.auxiliary_metrics:
            value = "—" if metric.value is None else str(metric.value)
            note = (metric.note or "").replace("|", "\\|")
            source = metric.source.replace("|", "\\|")
            lines.append(
                f"| {metric.label} | `{metric.status}` | {value} | {metric.unit or '—'} | `{source}` | {note} |"
            )
        lines.extend(
            [
                "",
                "Allowlisted observed durable event names: "
                + (", ".join(f"`{name}`" for name in snapshot.observed_event_names) or "none"),
                "",
                "Allowlisted observed numeric event fields from bounded decodable payloads: "
                + (", ".join(f"`{name}`" for name in snapshot.observed_numeric_event_fields) or "none"),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "DEFAULT_MAX_EVENTS",
    "MAX_EVENTS_HARD_LIMIT",
    "MetricReading",
    "S0_BASELINE_SCHEMA_VERSION",
    "S0RunSnapshot",
    "collect_s0_run_snapshot",
    "render_s0_markdown",
]
