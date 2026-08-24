from app.processing.s0_baseline import (
    MetricReading,
    S0_BASELINE_SCHEMA_VERSION,
    S0RunSnapshot,
    render_s0_markdown,
)


def _snapshot_with_auxiliary_metrics(
    *metrics: MetricReading,
) -> S0RunSnapshot:
    return S0RunSnapshot(
        schema_version=S0_BASELINE_SCHEMA_VERSION,
        processing_run_id="pdf-ingest-" + ("a" * 32),
        document_id="doc-safe",
        run_status="succeeded",
        file_type="pdf",
        source_file_id=None,
        source_checksum_sha256=None,
        started_at=None,
        terminal_at=None,
        event_window_truncated=False,
        event_payload_decode_incomplete=False,
        event_payload_oversized_incomplete=False,
        required_metrics=(),
        auxiliary_metrics=metrics,
        observed_event_names=(),
        observed_numeric_event_fields=(),
    )


def test_auxiliary_markdown_preserves_notes_and_escapes_table_cells() -> None:
    retryable = MetricReading(
        key="durable_retryable_signal_count",
        label="Durable retryable=true signal count in snapshot window",
        unit="signals",
        status="partial",
        value=1,
        source="processing_events.payload|retryable",
        note=(
            "Retryability signal only; it does not prove that a retry attempt occurred. "
            "At least one retained bounded payload carried a non-Boolean retryable "
            "value|so retryability evidence is incomplete."
        ),
    )
    peak_rss = MetricReading(
        key="max_observed_peak_rss_mb",
        label="Maximum observed generic peak RSS signal",
        unit="MiB",
        status="not_available",
        value=None,
        source="processing_events.payload.peak_rss_mb",
        note=(
            "Maximum is incomplete because at least one retained bounded payload "
            "carried an unusable peak_rss_mb numeric value."
        ),
    )

    markdown = render_s0_markdown(
        [_snapshot_with_auxiliary_metrics(retryable, peak_rss)]
    )

    assert "| Metric | Status | Value | Unit | Source | Note |" in markdown
    assert "does not prove that a retry attempt occurred" in markdown
    assert "non-Boolean retryable value\\|so retryability evidence is incomplete" in markdown
    assert "unusable peak_rss_mb numeric value" in markdown
    assert "`processing_events.payload\\|retryable`" in markdown
    assert "processing_events.payload|retryable" not in markdown
    assert "value|so retryability evidence is incomplete" not in markdown
