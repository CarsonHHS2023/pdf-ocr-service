from argparse import Namespace

import pytest

from scripts import report_s0_baseline


def _args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "processing_run_ids": ["pdf-ingest-run-a", "pdf-ingest-run-b"],
        "fixture_ids": ["pdf-small-v1", "pdf-medium-v1"],
        "fixture_registry_version": "v1",
        "backend_git_revision": "80e43fb4651a388806779b33ab42156c5483d0e3",
        "staging_runtime_revision": "staging-2026.08.23-r1",
    }
    values.update(overrides)
    return Namespace(**values)


def test_benchmark_record_metadata_pairs_fixture_and_run_identity() -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(_args())

    assert metadata["fixture_registry_version"] == "v1"
    assert metadata["backend_git_revision"] == "80e43fb4651a388806779b33ab42156c5483d0e3"
    assert metadata["staging_runtime_revision"] == "staging-2026.08.23-r1"
    assert metadata["runs"] == [
        {"processing_run_id": "pdf-ingest-run-a", "fixture_id": "pdf-small-v1"},
        {"processing_run_id": "pdf-ingest-run-b", "fixture_id": "pdf-medium-v1"},
    ]


def test_benchmark_record_requires_one_fixture_per_processing_run() -> None:
    with pytest.raises(SystemExit, match="exactly one --fixture-id"):
        report_s0_baseline._benchmark_record_metadata(
            _args(fixture_ids=["pdf-small-v1"])
        )


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("fixture_ids", ["pdf-small-v1\nprivate.pdf", "pdf-medium-v1"]),
        ("fixture_registry_version", "v1` injected"),
        ("backend_git_revision", "sha <script>"),
        ("staging_runtime_revision", "staging revision with spaces"),
    ],
)
def test_benchmark_record_rejects_unsafe_operator_metadata(
    field: str, unsafe_value: object
) -> None:
    with pytest.raises(SystemExit, match="privacy-safe token"):
        report_s0_baseline._benchmark_record_metadata(_args(**{field: unsafe_value}))


def test_benchmark_record_markdown_contains_required_fixture_and_runtime_identity() -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(_args())

    markdown = report_s0_baseline._render_benchmark_record_markdown(metadata)

    assert "fixture registry version: `v1`" in markdown
    assert "backend Git revision: `80e43fb4651a388806779b33ab42156c5483d0e3`" in markdown
    assert "Staging runtime revision: `staging-2026.08.23-r1`" in markdown
    assert "| `pdf-ingest-run-a` | `pdf-small-v1` |" in markdown
    assert "| `pdf-ingest-run-b` | `pdf-medium-v1` |" in markdown
