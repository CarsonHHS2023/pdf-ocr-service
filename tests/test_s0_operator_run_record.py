from argparse import Namespace

import pytest

from scripts import report_s0_baseline


RUN_A = "pdf-ingest-" + ("a" * 32)
RUN_B = "pdf-ingest-" + ("b" * 32)
BACKEND_SHA = "80e43fb4651a388806779b33ab42156c5483d0e3"
STAGING_REVISION = "staging-release_20260823-r1"


def _args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "processing_run_ids": [RUN_A, RUN_B],
        "fixture_ids": ["pdf-small-v1", "pdf-medium-v1"],
        "fixture_registry_version": "v1",
        "backend_git_revision": BACKEND_SHA,
        "staging_runtime_revision": STAGING_REVISION,
    }
    values.update(overrides)
    return Namespace(**values)


def test_benchmark_record_metadata_pairs_fixture_and_run_identity() -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(_args())

    assert metadata["fixture_registry_version"] == "v1"
    assert metadata["backend_git_revision"] == BACKEND_SHA
    assert metadata["staging_runtime_revision"] == STAGING_REVISION
    assert metadata["runs"] == [
        {"processing_run_id": RUN_A, "fixture_id": "pdf-small-v1"},
        {"processing_run_id": RUN_B, "fixture_id": "pdf-medium-v1"},
    ]


def test_benchmark_record_requires_one_fixture_per_processing_run() -> None:
    with pytest.raises(SystemExit, match="exactly one --fixture-id"):
        report_s0_baseline._benchmark_record_metadata(
            _args(fixture_ids=["pdf-small-v1"])
        )


def test_benchmark_record_rejects_duplicate_processing_run_assignments() -> None:
    with pytest.raises(SystemExit, match="must be unique"):
        report_s0_baseline._benchmark_record_metadata(
            _args(
                processing_run_ids=[RUN_A, RUN_A],
                fixture_ids=["pdf-small-v1", "pdf-medium-v1"],
            )
        )


@pytest.mark.parametrize(
    ("field", "unsafe_value", "message"),
    [
        ("processing_run_ids", ["private.pdf", RUN_B], "--processing-run-id"),
        (
            "processing_run_ids",
            ["s3://private-bucket/private.pdf", RUN_B],
            "--processing-run-id",
        ),
        ("fixture_ids", ["private.pdf", "pdf-medium-v1"], "--fixture-id"),
        (
            "fixture_ids",
            ["s3://private-bucket/private.pdf", "pdf-medium-v1"],
            "--fixture-id",
        ),
        ("fixture_registry_version", "v1/private.pdf", "--fixture-registry-version"),
        ("backend_git_revision", "private.pdf", "--backend-git-revision"),
        (
            "backend_git_revision",
            "s3://private-bucket/private.pdf",
            "--backend-git-revision",
        ),
        ("staging_runtime_revision", "staging-private.pdf", "--staging-runtime-revision"),
        (
            "staging_runtime_revision",
            "s3://private-bucket/private.pdf",
            "--staging-runtime-revision",
        ),
    ],
)
def test_benchmark_record_rejects_filename_and_storage_reference_shapes(
    field: str, unsafe_value: object, message: str
) -> None:
    with pytest.raises(SystemExit, match=message):
        report_s0_baseline._benchmark_record_metadata(_args(**{field: unsafe_value}))


def test_benchmark_record_rejects_unregistered_fixture() -> None:
    with pytest.raises(SystemExit, match="registered v1 fixture"):
        report_s0_baseline._benchmark_record_metadata(
            _args(fixture_ids=["pdf-extra-v1", "pdf-medium-v1"])
        )


def test_benchmark_record_markdown_contains_required_fixture_and_runtime_identity() -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(_args())

    markdown = report_s0_baseline._render_benchmark_record_markdown(metadata)

    assert "fixture registry version: `v1`" in markdown
    assert f"backend Git revision: `{BACKEND_SHA}`" in markdown
    assert f"Staging runtime revision: `{STAGING_REVISION}`" in markdown
    assert f"| `{RUN_A}` | `pdf-small-v1` |" in markdown
    assert f"| `{RUN_B}` | `pdf-medium-v1` |" in markdown
