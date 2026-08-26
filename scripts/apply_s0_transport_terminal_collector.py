"""Tighten S0.3.2 collection with authoritative transport-scope terminal proof.

This overlay runs after ``apply_s0_object_store_io_observability.py``. It keeps
per-retrieval StorageProvider events as byte-count evidence, but requires a
separate post-revoke final retrieval count for every Provider transport grant.
"""
from __future__ import annotations

from pathlib import Path


BASELINE_PATH = Path("app/processing/s0_baseline.py")

_IMPORT_ANCHOR = '''from app.s0_upload_boundary_observability import (
'''
_IMPORT_BLOCK = '''from app.s0_transport_scope_terminal_observability import (
    TRANSPORT_SCOPE_TERMINAL_EVENT as _S0_TRANSPORT_SCOPE_TERMINAL_EVENT,
)
from app.s0_upload_boundary_observability import (
'''
_SAFE_EVENT_ANCHOR = '''        _S0_STORAGE_IO_EVENT,
'''
_SAFE_EVENT_BLOCK = '''        _S0_STORAGE_IO_EVENT,
        _S0_TRANSPORT_SCOPE_TERMINAL_EVENT,
'''
_NUMERIC_ANCHOR = '''        "scope_ordinal",
'''
_NUMERIC_BLOCK = '''        "scope_ordinal",
        "terminal_retrieval_count",
'''
_FINAL_MARKER = "terminal_retrieval_counts: dict[str, int] = {}"

_HELPER_BLOCK = r'''def _s0_storage_io_measurement(
    decoded_events: Iterable[_DecodedEvent],
    *,
    expected_source_size: object,
    evidence_incomplete: bool,
    uninspectable_event_names: frozenset[str],
) -> tuple[object | None, object | None, str, str | None]:
    """Aggregate complete stage/scope counters from the backend StorageProvider boundary."""
    for event_name in (
        _S0_STORAGE_IO_EVENT,
        _S0_TRANSPORT_SCOPE_TERMINAL_EVENT,
    ):
        if event_name in uninspectable_event_names:
            return None, None, "not_available", (
                f"At least one retained {event_name} payload could not be inspected; "
                "backend storage I/O cannot be aggregated safely."
            )
    if "PDF_S0_PROVIDER_INTEGRATION_MEASURED" in uninspectable_event_names:
        return None, None, "not_available", (
            "Provider integration evidence could not be inspected, so terminal "
            "transport-scope completeness cannot be established."
        )
    if "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION" in uninspectable_event_names:
        return None, None, "not_available", (
            "Provider sharding decision evidence could not be inspected, so the "
            "expected number of transport scopes cannot be established."
        )
    if "PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL" in uninspectable_event_names:
        return None, None, "not_available", (
            "Provider sharding terminal evidence could not be inspected, so the "
            "expected number of transport scopes cannot be established."
        )

    matching = [event for event in decoded_events if event.event_name == _S0_STORAGE_IO_EVENT]
    terminal_matching = [
        event
        for event in decoded_events
        if event.event_name == _S0_TRANSPORT_SCOPE_TERMINAL_EVENT
    ]
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
    transport_ordinals: dict[str, set[int]] = {}
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
        if stage == _S0_STAGE_PROVIDER_SOURCE_TRANSPORT:
            transport_ordinals.setdefault(scope_id, set()).add(ordinal)

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

    terminal_retrieval_counts: dict[str, int] = {}
    for event in terminal_matching:
        payload = event.payload
        if (
            payload.get("succeeded") is not True
            or payload.get("measurement_scope") != _S0_STORAGE_IO_SCOPE
            or payload.get("stage") != _S0_STAGE_PROVIDER_SOURCE_TRANSPORT
        ):
            return None, None, "not_available", (
                "A transport terminal event has an unsupported success/scope/stage contract."
            )
        scope_id = payload.get("scope_id")
        count = payload.get("terminal_retrieval_count")
        if not isinstance(scope_id, str) or re.fullmatch(r"transport_[0-9a-f]{16}", scope_id) is None:
            return None, None, "not_available", "A transport terminal event has an invalid scope identifier."
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            return None, None, "not_available", "A transport terminal event has an invalid final retrieval count."
        if scope_id in terminal_retrieval_counts:
            return None, None, "not_available", "Duplicate transport terminal evidence is ambiguous."
        terminal_retrieval_counts[scope_id] = count

    provider_successful = any(
        event.event_name == "PDF_S0_PROVIDER_INTEGRATION_MEASURED"
        and event.payload.get("succeeded") is True
        for event in decoded_events
    )
    expected_terminal_scope_count: int | None = None
    if provider_successful:
        sharding_decisions = [
            event
            for event in decoded_events
            if event.event_name == "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION"
        ]
        if len(sharding_decisions) > 1:
            return None, None, "not_available", (
                "Multiple Provider sharding decision events make the expected "
                "transport-scope count ambiguous."
            )
        sharding_required: bool | None = None
        if sharding_decisions:
            value = sharding_decisions[0].payload.get("sharding_required")
            if not isinstance(value, bool):
                return None, None, "not_available", (
                    "Provider sharding decision evidence has an invalid sharding_required value."
                )
            sharding_required = value

        sharding_terminal_all = [
            event
            for event in decoded_events
            if event.event_name == "PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL"
        ]
        if len(sharding_terminal_all) > 1:
            return None, None, "not_available", (
                "Multiple Provider sharding terminal events make the expected "
                "transport-scope count ambiguous."
            )
        successful_sharding_terminal = [
            event for event in sharding_terminal_all if event.payload.get("succeeded") is True
        ]
        if sharding_terminal_all and len(successful_sharding_terminal) != 1:
            return None, None, "not_available", (
                "Provider sharding terminal evidence is not a successful terminal proof."
            )

        if successful_sharding_terminal:
            if sharding_required is False:
                return None, None, "not_available", (
                    "Provider sharding decision and terminal evidence disagree about whether "
                    "the successful Provider run was sharded."
                )
            shard_count = successful_sharding_terminal[0].payload.get("shard_count")
            if not isinstance(shard_count, int) or isinstance(shard_count, bool) or shard_count < 1:
                return None, None, "not_available", (
                    "Provider sharding terminal evidence has an invalid shard count."
                )
            expected_terminal_scope_count = shard_count
        elif sharding_required is False:
            # A durable negative sharding decision is the only valid proof that
            # absence of a sharding terminal means this successful run was single-scope.
            expected_terminal_scope_count = 1
        elif sharding_required is True:
            return None, None, "not_available", (
                "Provider sharding was required but no successful terminal shard-count "
                "evidence is retained."
            )
        else:
            return None, None, "not_available", (
                "No Provider sharding decision or terminal shard-count evidence is retained; "
                "absence cannot prove that the successful run was non-sharded, so terminal "
                "proof for every expected transport scope cannot be established."
            )

        if len(terminal_retrieval_counts) != expected_terminal_scope_count:
            return None, None, "not_available", (
                "The successful Provider run does not retain terminal proof for every "
                "expected transport scope."
            )

    for scope_id, ordinals in transport_ordinals.items():
        if scope_id not in terminal_retrieval_counts:
            return None, None, "not_available", (
                "A Provider source-transport read scope has no post-revoke terminal proof."
            )

    for scope_id, terminal_count in terminal_retrieval_counts.items():
        ordinals = transport_ordinals.get(scope_id, set())
        expected_ordinals = set(range(1, terminal_count + 1))
        if ordinals != expected_ordinals:
            return None, None, "not_available", (
                "Provider source-transport retrieval evidence does not match the "
                "post-revoke terminal retrieval count; one or more successful storage "
                "reads may be missing durable evidence."
            )

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


def patch_s0_transport_terminal_collector(path: Path = BASELINE_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    if _FINAL_MARKER in source:
        return
    if "def _s0_storage_io_measurement(" not in source:
        raise RuntimeError("S0.3.2 storage collector must be installed first")

    if source.count(_IMPORT_ANCHOR) != 1:
        raise RuntimeError("Could not find unique transport-terminal import anchor")
    source = source.replace(_IMPORT_ANCHOR, _IMPORT_BLOCK, 1)

    if source.count(_SAFE_EVENT_ANCHOR) != 1:
        raise RuntimeError("Could not find unique transport-terminal safe-event anchor")
    source = source.replace(_SAFE_EVENT_ANCHOR, _SAFE_EVENT_BLOCK, 1)

    if source.count(_NUMERIC_ANCHOR) != 2:
        raise RuntimeError("Expected safe and nonnegative scope-ordinal anchors")
    source = source.replace(_NUMERIC_ANCHOR, _NUMERIC_BLOCK)

    start = source.index("def _s0_storage_io_measurement(")
    end = source.index("def _phase2_process_lifetime_peak(", start)
    source = source[:start] + _HELPER_BLOCK + source[end:]
    if _FINAL_MARKER not in source:
        raise RuntimeError("Transport-terminal collector did not reach final contract")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    patch_s0_transport_terminal_collector()


if __name__ == "__main__":
    main()