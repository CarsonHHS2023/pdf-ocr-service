"""Compose visual-asset wall timing into the final Staging runtime."""
from pathlib import Path


def _patch(path: Path, replacements) -> None:
    source = path.read_text(encoding="utf-8")
    installed = [new in source for _old, new in replacements]
    if all(installed):
        return
    if any(installed):
        raise RuntimeError(f"Visual-asset generation overlay partially installed: {path}")
    for old, new in replacements:
        if source.count(old) != 1:
            raise RuntimeError(
                f"Visual-asset generation overlay anchor drift: {path}"
            )
        source = source.replace(old, new, 1)
    path.write_text(source, encoding="utf-8")


def main() -> None:
    cpu_install = (
        "from app.s0_preprocessing_cpu_observability import "
        "install_preprocessing_cpu_observability\n"
        "install_preprocessing_cpu_observability()\n"
    )
    visual_install = (
        cpu_install
        + "\nfrom app.s0_visual_asset_generation_observability import "
        "install_visual_asset_generation_observability\n"
        "install_visual_asset_generation_observability()\n"
    )
    _patch(
        Path("app/processing/pdf_ingestion.py"),
        [(cpu_install, visual_install)],
    )

    import_anchor = "from __future__ import annotations\n"
    import_block = (
        import_anchor
        + "\nfrom app.s0_visual_asset_generation_metrics import (\n"
        "    EVENT_NAMES as _VISUAL_ASSET_GENERATION_EVENTS,\n"
        "    decode_visual_asset_generation_payload,\n"
        "    measure_visual_asset_generation as _measure_visual_asset_generation,\n"
        "    source_scope_id as _visual_asset_source_scope,\n"
        ")\n"
    )
    safe_event_anchor = "        *_WORKER_CPU_EVENTS,\n"
    safe_event_block = (
        "        *_VISUAL_ASSET_GENERATION_EVENTS,\n" + safe_event_anchor
    )
    decode_anchor = (
        '        if row.event_name.startswith("S0_PREPROCESS_CPU_"):\n'
        "            from app.s0_preprocessing_cpu_metrics import "
        "decode_worker_cpu_payload\n"
        "            payload, decode_valid = "
        "decode_worker_cpu_payload(row.payload_json)\n"
        "        else:\n"
        "            payload, decode_valid = _decode_event_payload(row.payload_json)\n"
    )
    decode_block = (
        '        if row.event_name.startswith("S0_VISUAL_ASSET_GENERATION_"):\n'
        "            payload, decode_valid = "
        "decode_visual_asset_generation_payload(row.payload_json)\n"
        '        elif row.event_name.startswith("S0_PREPROCESS_CPU_"):\n'
        "            from app.s0_preprocessing_cpu_metrics import "
        "decode_worker_cpu_payload\n"
        "            payload, decode_valid = "
        "decode_worker_cpu_payload(row.payload_json)\n"
        "        else:\n"
        "            payload, decode_valid = _decode_event_payload(row.payload_json)\n"
    )
    mapping_anchor = "    failure_retry = measure_failure_retry(\n"
    mapping_block = (
        "    visual_asset_generation = _measure_visual_asset_generation(\n"
        "        decoded_events_tuple,\n"
        "        expected_source_scope=_visual_asset_source_scope(run.source_file_id),\n"
        "        run_status=run.status,\n"
        "        evidence_incomplete=payload_evidence_incomplete,\n"
        "        uninspectable_event_names=uninspectable_event_names_frozen,\n"
        "    )\n"
        "    required_by_key[\"visual_asset_generation_seconds\"] = _metric(\n"
        "        \"visual_asset_generation_seconds\",\n"
        "        value=visual_asset_generation[\"value\"],\n"
        "        status=visual_asset_generation[\"status\"],\n"
        "        source=\"processing_events.S0_VISUAL_ASSET_GENERATION_*\",\n"
        "        note=visual_asset_generation[\"note\"],\n"
        "    )\n\n"
        + mapping_anchor
    )
    auxiliary_anchor = "    auxiliary: list[MetricReading] = [\n"
    auxiliary_block = (
        auxiliary_anchor
        + "        MetricReading(\n"
        "            key=\"visual_asset_generation_breakdown\",\n"
        "            label=\"Visual asset generation evidence\",\n"
        "            unit=None,\n"
        "            status=visual_asset_generation[\"status\"],\n"
        "            value=visual_asset_generation[\"breakdown\"],\n"
        "            source=\"processing_events.S0_VISUAL_ASSET_GENERATION_*\",\n"
        "            note=visual_asset_generation[\"note\"],\n"
        "        ),\n"
    )
    _patch(
        Path("app/processing/s0_baseline.py"),
        [
            (import_anchor, import_block),
            (safe_event_anchor, safe_event_block),
            (decode_anchor, decode_block),
            (mapping_anchor, mapping_block),
            (auxiliary_anchor, auxiliary_block),
        ],
    )


if __name__ == "__main__":
    main()
