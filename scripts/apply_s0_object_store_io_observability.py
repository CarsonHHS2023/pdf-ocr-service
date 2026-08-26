"""Compose Staging-only S0.3.2 backend StorageProvider I/O observability."""
from __future__ import annotations

from pathlib import Path

PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")
TRANSPORT_SERVICE_PATH = Path("app/processing/transport/service.py")
SOURCE_TRANSPORT_PATH = Path("app/routers/source_transport.py")
BASELINE_PATH = Path("app/processing/s0_baseline.py")

_PDF_INSTALL = '''
# Exact-Staging-only S0.3.2 StorageProvider I/O aggregation. Import here so the
# wrapper observes the fully composed PDF ingestion function without changing
# processing ownership or storage semantics.
from app.s0_object_store_io_observability import install_s0_object_store_pdf_observability
install_s0_object_store_pdf_observability()
'''
_TRANSPORT_SERVICE_ANCHOR = '''    def record_retrieval(self, token: str) -> AuthorizedTransportGrant:
        """Atomically authorize and count one successful retrieval completion."""
        if not self._valid_token_text(token):
            raise InvalidToken()
        digest = self._digest(token)
        with self._lock:
            record = self._by_digest.get(digest)
            if record is None or not secrets.compare_digest(record.token_digest, digest):
                raise GrantNotFound()
            now = self._now()
            self._ensure_authorized(record, now)
            updated = replace(
                record,
                retrieval_count=record.retrieval_count + 1,
                first_retrieved_at=record.first_retrieved_at or now,
                last_retrieved_at=now,
            )
            self._by_digest[digest] = updated
        return self._authorized_descriptor(updated)
'''
_TRANSPORT_SERVICE_BLOCK = '''    def record_retrieval_with_ordinal(
        self,
        token: str,
    ) -> tuple[AuthorizedTransportGrant, int]:
        """Atomically count one retrieval and return that exact retrieval ordinal."""
        if not self._valid_token_text(token):
            raise InvalidToken()
        digest = self._digest(token)
        with self._lock:
            record = self._by_digest.get(digest)
            if record is None or not secrets.compare_digest(record.token_digest, digest):
                raise GrantNotFound()
            now = self._now()
            self._ensure_authorized(record, now)
            updated = replace(
                record,
                retrieval_count=record.retrieval_count + 1,
                first_retrieved_at=record.first_retrieved_at or now,
                last_retrieved_at=now,
            )
            self._by_digest[digest] = updated
            retrieval_ordinal = updated.retrieval_count
        return self._authorized_descriptor(updated), retrieval_ordinal

    def record_retrieval(self, token: str) -> AuthorizedTransportGrant:
        """Preserve the existing API while sharing the atomic retrieval update."""
        authorized, _ = self.record_retrieval_with_ordinal(token)
        return authorized
'''
_TRANSPORT_ANCHOR = '''    try:
        grants.record_retrieval(token)
    except TransportGrantError:
        _collapsed_not_found()

    return response
'''
_TRANSPORT_RACY_BLOCK = '''    try:
        grants.record_retrieval(token)
    except TransportGrantError:
        _collapsed_not_found()

    try:
        descriptor = grants.inspect(grant.grant_id)
        if descriptor is not None:
            from app.s0_object_store_io_observability import (
                record_provider_source_transport_read,
            )
            record_provider_source_transport_read(
                grant,
                len(payload),
                int(descriptor.retrieval_count),
            )
    except Exception:
        # S0 telemetry must never affect the provider source response.
        pass

    return response
'''
_TRANSPORT_BLOCK = '''    try:
        _, retrieval_ordinal = grants.record_retrieval_with_ordinal(token)
    except TransportGrantError:
        _collapsed_not_found()

    try:
        from app.s0_object_store_io_observability import (
            record_provider_source_transport_read,
        )
        record_provider_source_transport_read(
            grant,
            len(payload),
            retrieval_ordinal,
        )
    except Exception:
        # S0 telemetry must never affect the provider source response.
        pass

    return response
'''

_IMPORT_ANCHOR = '''from app.s0_upload_boundary_observability import (
'''
_IMPORT_BLOCK = '''from app.s0_object_store_io_observability import (
    STORAGE_IO_EVENT as _S0_STORAGE_IO_EVENT,
    STORAGE_IO_SCOPE as _S0_STORAGE_IO_SCOPE,
    STORAGE_IO_STAGES as _S0_STORAGE_IO_STAGES,
    STAGE_GENERATED_ARTIFACT as _S0_STAGE_GENERATED_ARTIFACT,
    STAGE_PROCESSING_SOURCE as _S0_STAGE_PROCESSING_SOURCE,
    STAGE_UPLOAD_SOURCE_RETENTION as _S0_STAGE_UPLOAD_SOURCE_RETENTION,
)
from app.s0_upload_boundary_observability import (
'''
_SAFE_EVENT_ANCHOR = '''        _S0_UPLOAD_MEASUREMENT_EVENT,
'''
_SAFE_EVENT_BLOCK = '''        _S0_UPLOAD_MEASUREMENT_EVENT,
        _S0_STORAGE_IO_EVENT,
'''
_SAFE_NUMERIC_ANCHOR = '''        "uploadfile_read_total_bytes",
    }
)
_NONNEGATIVE_EVENT_FIELDS = frozenset(
'''
_SAFE_NUMERIC_BLOCK = '''        "uploadfile_read_total_bytes",
        "read_bytes",
        "write_bytes",
        "read_operations",
        "write_operations",
        "scope_ordinal",
    }
)
_NONNEGATIVE_EVENT_FIELDS = frozenset(
'''
_NONNEGATIVE_ANCHOR = '''        "uploadfile_read_total_bytes",
    }
)


@dataclass(frozen=True, slots=True)
class MetricReading:
'''
_NONNEGATIVE_BLOCK = '''        "uploadfile_read_total_bytes",
        "read_bytes",
        "write_bytes",
        "read_operations",
        "write_operations",
        "scope_ordinal",
    }
)


@dataclass(frozen=True, slots=True)
class MetricReading:
'''
_HELPER_ANCHOR = '''def _phase2_process_lifetime_peak(
'''
_HELPER_BLOCK = r'''def _s0_storage_io_measurement(
    decoded_events: Iterable[_DecodedEvent],
    *,
    expected_source_size: object,
    evidence_incomplete: bool,
    uninspectable_event_names: frozenset[str],
) -> tuple[object | None, object | None, str, str | None]:
    """Aggregate unique stage/scope counters from the backend StorageProvider boundary."""
    if _S0_STORAGE_IO_EVENT in uninspectable_event_names:
        return None, None, "not_available", (
            f"At least one retained {_S0_STORAGE_IO_EVENT} payload could not be inspected; "
            "backend storage I/O cannot be aggregated safely."
        )
    matching = [event for event in decoded_events if event.event_name == _S0_STORAGE_IO_EVENT]
    if not matching:
        return None, None, "not_available", (
            f"No bounded {_S0_STORAGE_IO_EVENT} events are retained for this run."
        )
    if (
        not isinstance(expected_source_size, int)
        or isinstance(expected_source_size, bool)
        or expected_source_size <= 0
    ):
        return None, None, "not_available", "A positive retained source size is required."

    seen: set[tuple[str, str, int]] = set()
    stages: dict[str, dict[str, int]] = {}
    for event in matching:
        payload = event.payload
        if payload.get("succeeded") is not True or payload.get("measurement_scope") != _S0_STORAGE_IO_SCOPE:
            return None, None, "not_available", "A storage I/O event has an unsupported success/scope contract."
        stage = payload.get("stage")
        scope_id = payload.get("scope_id")
        ordinal = payload.get("scope_ordinal")
        if stage not in _S0_STORAGE_IO_STAGES:
            return None, None, "not_available", "A storage I/O event has an unsupported stage."
        if not isinstance(scope_id, str) or re.fullmatch(r"[a-z0-9_]{1,48}", scope_id) is None:
            return None, None, "not_available", "A storage I/O event has an invalid scope identifier."
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
            return None, None, "not_available", "A storage I/O event has an invalid scope ordinal."
        key = (stage, scope_id, ordinal)
        if key in seen:
            return None, None, "not_available", "Duplicate storage I/O stage/scope evidence is ambiguous."
        seen.add(key)

        values: dict[str, int] = {}
        for field in ("read_bytes", "write_bytes", "read_operations", "write_operations"):
            value = payload.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return None, None, "not_available", f"A storage I/O event has invalid {field}."
            values[field] = value
        if values["read_operations"] == 0 and values["read_bytes"] != 0:
            return None, None, "not_available", "Read bytes without a read operation are invalid."
        if values["write_operations"] == 0 and values["write_bytes"] != 0:
            return None, None, "not_available", "Write bytes without a write operation are invalid."
        if values["read_operations"] + values["write_operations"] == 0:
            return None, None, "not_available", "A storage I/O event with no operation is not evidence."

        aggregate = stages.setdefault(stage, {
            "read_bytes": 0,
            "write_bytes": 0,
            "read_operations": 0,
            "write_operations": 0,
        })
        for field, value in values.items():
            aggregate[field] += value

    required_stages = {
        _S0_STAGE_UPLOAD_SOURCE_RETENTION,
        _S0_STAGE_PROCESSING_SOURCE,
        _S0_STAGE_GENERATED_ARTIFACT,
    }
    if not required_stages.issubset(stages):
        return None, None, "not_available", (
            "The canonical PDF path is missing one or more required storage I/O stages."
        )
    upload = stages[_S0_STAGE_UPLOAD_SOURCE_RETENTION]
    if (
        upload["read_bytes"] != 0
        or upload["read_operations"] != 0
        or upload["write_operations"] != 1
        or upload["write_bytes"] != expected_source_size
    ):
        return None, None, "not_available", (
            "The source-retention storage write does not match the ProcessingRun source."
        )
    processing_source = stages[_S0_STAGE_PROCESSING_SOURCE]
    if processing_source["read_operations"] < 1 or processing_source["read_bytes"] < expected_source_size:
        return None, None, "not_available", "No complete backend processing-source read is retained."
    generated = stages[_S0_STAGE_GENERATED_ARTIFACT]
    if generated["write_operations"] < 1:
        return None, None, "not_available", "No generated-artifact storage write is retained."

    total_read = sum(stage["read_bytes"] for stage in stages.values())
    total_write = sum(stage["write_bytes"] for stage in stages.values())
    stage_value = {
        "measurement_scope": _S0_STORAGE_IO_SCOPE,
        "total_read_bytes": total_read,
        "total_write_bytes": total_write,
        "stages": {name: stages[name] for name in sorted(stages)},
    }
    status = "partial" if evidence_incomplete else "observed"
    note = (
        "The bounded event/payload evidence for this snapshot is incomplete."
        if evidence_incomplete else None
    )
    return total_read + total_write, stage_value, status, note


'''
_MEASUREMENT_ANCHOR = '''    preprocessing_wall_measurement = _event_measurement(
'''
_MEASUREMENT_BLOCK = '''    storage_io_total_bytes, storage_io_stage_value, storage_io_status, storage_io_note = _s0_storage_io_measurement(
        decoded_events_tuple,
        expected_source_size=source_size,
        evidence_incomplete=payload_evidence_incomplete,
        uninspectable_event_names=uninspectable_event_names_frozen,
    )

    preprocessing_wall_measurement = _event_measurement(
'''
_REQUIRED_ANCHOR = '''        "preprocessing_wall_seconds": _metric(
'''
_REQUIRED_BLOCK = '''        "backend_object_store_bytes": _metric(
            "backend_object_store_bytes",
            value=storage_io_total_bytes,
            status=storage_io_status,
            source="processing_events.S0_OBJECT_STORE_STAGE_IO_MEASURED",
            note=_combine_notes(
                "Sum of successful logical StorageProvider read/write bytes across the allowlisted backend stages; this is I/O volume, not unique object size or network transport bytes.",
                storage_io_note,
            ),
        ),
        "object_store_stage_io": _metric(
            "object_store_stage_io",
            value=storage_io_stage_value,
            status=storage_io_status,
            source="processing_events.S0_OBJECT_STORE_STAGE_IO_MEASURED",
            note=_combine_notes(
                "Stage-specific logical StorageProvider operation counts and byte volume; direct/presigned provider downloads remain a separate transport boundary.",
                storage_io_note,
            ),
        ),
        "preprocessing_wall_seconds": _metric(
'''
_MISSING_BACKEND = '''        "backend_object_store_bytes": (
            "object-store instrumentation",
            "Per-stage backend object-store byte counters are not durably persisted.",
        ),
'''
_MISSING_STAGE = '''        "object_store_stage_io": (
            "object-store instrumentation",
            "Stage-specific object-store read/write counters are not durably normalized.",
        ),
'''
_FINAL_MARKERS = (
    "def _s0_storage_io_measurement(",
    '"backend_object_store_bytes": _metric(',
    '"object_store_stage_io": _metric(',
    "_S0_STORAGE_IO_EVENT,",
)


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique S0.3.2 anchor: {label}")
    return source.replace(old, new, 1)


def patch_pdf_runtime(path: Path = PDF_INGESTION_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    if _PDF_INSTALL in source:
        return
    path.write_text(source.rstrip() + "\n" + _PDF_INSTALL, encoding="utf-8")


def patch_transport_service(path: Path = TRANSPORT_SERVICE_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    if "def record_retrieval_with_ordinal(" in source:
        return
    source = _replace_once(
        source,
        _TRANSPORT_SERVICE_ANCHOR,
        _TRANSPORT_SERVICE_BLOCK,
        "atomic transport retrieval ordinal",
    )
    path.write_text(source, encoding="utf-8")


def patch_source_transport(path: Path = SOURCE_TRANSPORT_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    if "record_retrieval_with_ordinal(token)" in source:
        return
    if _TRANSPORT_RACY_BLOCK in source:
        source = source.replace(_TRANSPORT_RACY_BLOCK, _TRANSPORT_BLOCK, 1)
    else:
        source = _replace_once(
            source,
            _TRANSPORT_ANCHOR,
            _TRANSPORT_BLOCK,
            "source transport completion",
        )
    path.write_text(source, encoding="utf-8")


def patch_baseline(path: Path = BASELINE_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    if all(marker in source for marker in _FINAL_MARKERS):
        return
    if any(marker in source for marker in _FINAL_MARKERS):
        raise RuntimeError("S0.3.2 baseline mapping is only partially installed")
    source = _replace_once(source, _IMPORT_ANCHOR, _IMPORT_BLOCK, "collector imports")
    source = _replace_once(source, _SAFE_EVENT_ANCHOR, _SAFE_EVENT_BLOCK, "safe event")
    source = _replace_once(source, _SAFE_NUMERIC_ANCHOR, _SAFE_NUMERIC_BLOCK, "safe numeric")
    source = _replace_once(source, _NONNEGATIVE_ANCHOR, _NONNEGATIVE_BLOCK, "nonnegative")
    source = _replace_once(source, _HELPER_ANCHOR, _HELPER_BLOCK + _HELPER_ANCHOR, "storage helper")
    source = _replace_once(source, _MEASUREMENT_ANCHOR, _MEASUREMENT_BLOCK, "storage extraction")
    source = _replace_once(source, _REQUIRED_ANCHOR, _REQUIRED_BLOCK, "required mapping")
    source = _replace_once(source, _MISSING_BACKEND, "", "obsolete backend missing")
    source = _replace_once(source, _MISSING_STAGE, "", "obsolete stage missing")
    if not all(marker in source for marker in _FINAL_MARKERS):
        raise RuntimeError("S0.3.2 baseline mapping did not reach final contract")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    patch_pdf_runtime()
    patch_transport_service()
    patch_source_transport()
    patch_baseline()


if __name__ == "__main__":
    main()
