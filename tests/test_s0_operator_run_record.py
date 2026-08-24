from argparse import Namespace
from types import SimpleNamespace

import pytest

from scripts import report_s0_baseline


RUN_A = "pdf-ingest-" + ("a" * 32)
RUN_B = "pdf-ingest-" + ("b" * 32)
TXT_RUN = "txt-ingest-" + ("c" * 32)
BACKEND_SHA = "80e43fb4651a388806779b33ab42156c5483d0e3"
STAGING_REVISION = "staging-release_20260823-r1"


class _OneRowResult:
    def __init__(self, row):
        self._row = row

    def one_or_none(self):
        return self._row


class _AssociationSession:
    def __init__(
        self,
        source_file_id: str | None,
        source_file_type: str | None = None,
        *,
        run_exists: bool = True,
        source_exists: bool = True,
    ):
        self.source_file_id = source_file_id
        self.source_file_type = source_file_type
        self.run_exists = run_exists
        self.source_exists = source_exists
        self.execute_count = 0

    def execute(self, _statement):
        self.execute_count += 1
        if self.execute_count == 1:
            row = (
                SimpleNamespace(source_file_id=self.source_file_id)
                if self.run_exists
                else None
            )
            return _OneRowResult(row)
        if self.execute_count == 2:
            row = (
                SimpleNamespace(file_type=self.source_file_type)
                if self.source_exists
                else None
            )
            return _OneRowResult(row)
        raise AssertionError("unexpected extra query")


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


def _snapshot(
    run_id: str,
    *,
    file_type: str | None,
    source_file_id: str | None = "source-1",
    document_id: str = "doc-1",
):
    return SimpleNamespace(
        processing_run_id=run_id,
        file_type=file_type,
        source_file_id=source_file_id,
        document_id=document_id,
    )


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
    ("processing_run_id", "fixture_id"),
    [
        (TXT_RUN, "pdf-small-v1"),
        (RUN_A, "txt-small-v1"),
    ],
)
def test_benchmark_record_rejects_cross_type_run_fixture_assignments(
    processing_run_id: str, fixture_id: str
) -> None:
    with pytest.raises(SystemExit, match="matching pdf/txt media types"):
        report_s0_baseline._benchmark_record_metadata(
            _args(
                processing_run_ids=[processing_run_id],
                fixture_ids=[fixture_id],
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


def test_snapshot_assignments_accept_matching_collected_media_type() -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(_args())
    snapshots = [
        _snapshot(RUN_A, file_type="pdf", source_file_id=None),
        _snapshot(RUN_B, file_type="pdf", source_file_id=None),
    ]

    report_s0_baseline._validate_snapshot_assignments(metadata, snapshots)


def test_snapshot_assignments_reject_collected_media_mismatch() -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(
        _args(processing_run_ids=[RUN_A], fixture_ids=["pdf-small-v1"])
    )

    with pytest.raises(SystemExit, match="does not match"):
        report_s0_baseline._validate_snapshot_assignments(
            metadata,
            [_snapshot(RUN_A, file_type="txt")],
        )


def test_snapshot_assignments_reject_unavailable_collected_media_type() -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(
        _args(processing_run_ids=[RUN_A], fixture_ids=["pdf-small-v1"])
    )

    with pytest.raises(SystemExit, match="file type is unavailable"):
        report_s0_baseline._validate_snapshot_assignments(
            metadata,
            [_snapshot(RUN_A, file_type=None)],
        )


def test_attached_source_assignments_accept_matching_source_media_type() -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(
        _args(processing_run_ids=[RUN_A], fixture_ids=["pdf-small-v1"])
    )
    snapshots = [_snapshot(RUN_A, file_type="pdf")]

    report_s0_baseline._validate_attached_source_assignments(
        _AssociationSession("source-1", "pdf"), metadata, snapshots
    )


@pytest.mark.parametrize(
    ("processing_run_id", "fixture_id", "document_type", "source_type"),
    [
        (RUN_A, "pdf-small-v1", "pdf", "txt"),
        (TXT_RUN, "txt-small-v1", "txt", "pdf"),
    ],
)
def test_attached_source_assignments_reject_cross_media_source(
    processing_run_id: str,
    fixture_id: str,
    document_type: str,
    source_type: str,
) -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(
        _args(processing_run_ids=[processing_run_id], fixture_ids=[fixture_id])
    )
    snapshots = [_snapshot(processing_run_id, file_type=document_type)]

    with pytest.raises(SystemExit, match="attached source file type does not match"):
        report_s0_baseline._validate_attached_source_assignments(
            _AssociationSession("source-1", source_type), metadata, snapshots
        )


@pytest.mark.parametrize("source_type", ["secret.pdf", "pdf`\nprivate.pdf"])
def test_attached_source_assignments_reject_unsafe_source_media_without_echo(
    source_type: str,
) -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(
        _args(processing_run_ids=[RUN_A], fixture_ids=["pdf-small-v1"])
    )
    snapshots = [_snapshot(RUN_A, file_type="pdf")]

    with pytest.raises(SystemExit, match="source file type is unavailable") as exc_info:
        report_s0_baseline._validate_attached_source_assignments(
            _AssociationSession("source-1", source_type), metadata, snapshots
        )
    assert source_type not in str(exc_info.value)


def test_explicit_source_hidden_by_collector_is_rejected_as_association_mismatch() -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(
        _args(processing_run_ids=[RUN_A], fixture_ids=["pdf-small-v1"])
    )
    # Real collector shape for an explicitly associated source that cannot resolve:
    # snapshot fails closed to None while ProcessingRun still retains the source id.
    snapshots = [_snapshot(RUN_A, file_type="pdf", source_file_id=None)]
    session = _AssociationSession("missing-source", source_exists=False)

    with pytest.raises(SystemExit, match="collected source association does not match"):
        report_s0_baseline._validate_attached_source_assignments(
            session, metadata, snapshots
        )
    assert session.execute_count == 1


def test_attached_source_assignments_reject_missing_source_row_when_identity_agrees() -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(
        _args(processing_run_ids=[RUN_A], fixture_ids=["pdf-small-v1"])
    )
    snapshots = [_snapshot(RUN_A, file_type="pdf", source_file_id="missing-source")]

    with pytest.raises(SystemExit, match="source file identity is unavailable"):
        report_s0_baseline._validate_attached_source_assignments(
            _AssociationSession("missing-source", source_exists=False),
            metadata,
            snapshots,
        )


def test_attached_source_assignments_reject_collector_run_source_disagreement() -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(
        _args(processing_run_ids=[RUN_A], fixture_ids=["pdf-small-v1"])
    )
    snapshots = [_snapshot(RUN_A, file_type="pdf", source_file_id="source-other")]

    with pytest.raises(SystemExit, match="collected source association does not match"):
        report_s0_baseline._validate_attached_source_assignments(
            _AssociationSession("source-1", "pdf"), metadata, snapshots
        )


def test_source_detached_after_collection_is_rejected() -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(
        _args(processing_run_ids=[RUN_A], fixture_ids=["pdf-small-v1"])
    )
    snapshots = [_snapshot(RUN_A, file_type="pdf", source_file_id="source-1")]
    session = _AssociationSession(None)

    with pytest.raises(SystemExit, match="collected source association does not match"):
        report_s0_baseline._validate_attached_source_assignments(
            session, metadata, snapshots
        )
    assert session.execute_count == 1


def test_source_attached_after_collection_is_rejected() -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(
        _args(processing_run_ids=[RUN_A], fixture_ids=["pdf-small-v1"])
    )
    snapshots = [_snapshot(RUN_A, file_type="pdf", source_file_id=None)]
    session = _AssociationSession("source-1", "pdf")

    with pytest.raises(SystemExit, match="collected source association does not match"):
        report_s0_baseline._validate_attached_source_assignments(
            session, metadata, snapshots
        )
    assert session.execute_count == 1


def test_attached_source_assignments_leave_true_legacy_unattached_run_unchanged() -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(
        _args(processing_run_ids=[RUN_A], fixture_ids=["pdf-small-v1"])
    )
    snapshots = [_snapshot(RUN_A, file_type="pdf", source_file_id=None)]
    session = _AssociationSession(None)

    report_s0_baseline._validate_attached_source_assignments(
        session, metadata, snapshots
    )
    assert session.execute_count == 1


def test_attached_source_assignments_reject_missing_processing_run_association_row() -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(
        _args(processing_run_ids=[RUN_A], fixture_ids=["pdf-small-v1"])
    )
    snapshots = [_snapshot(RUN_A, file_type="pdf", source_file_id=None)]

    with pytest.raises(SystemExit, match="processing run source association is unavailable"):
        report_s0_baseline._validate_attached_source_assignments(
            _AssociationSession(None, run_exists=False), metadata, snapshots
        )


def test_benchmark_record_markdown_contains_required_fixture_and_runtime_identity() -> None:
    metadata = report_s0_baseline._benchmark_record_metadata(_args())

    markdown = report_s0_baseline._render_benchmark_record_markdown(metadata)

    assert "fixture registry version: `v1`" in markdown
    assert f"backend Git revision: `{BACKEND_SHA}`" in markdown
    assert f"Staging runtime revision: `{STAGING_REVISION}`" in markdown
    assert f"| `{RUN_A}` | `pdf-small-v1` |" in markdown
    assert f"| `{RUN_B}` | `pdf-medium-v1` |" in markdown
