from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import subprocess
import sys

from app.processing import pdf_visual_crop_lifecycle_compat as lifecycle
from app.source_units import SpatialAnchor


class _NodeType(str, Enum):
    TABLE = "table"
    FIGURE = "figure"
    PARAGRAPH = "paragraph"


class _RecoveryState(str, Enum):
    AVAILABLE = "available"
    REBUILDABLE = "rebuildable"


@dataclass(frozen=True)
class _Node:
    node_id: str
    node_type: _NodeType
    source_anchors: tuple[object, ...]
    asset_ids: tuple[str, ...] = ()
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class _Asset:
    asset_id: str
    rendition_ids: tuple[str, ...]
    recovery_state: _RecoveryState


@dataclass(frozen=True)
class _Candidate:
    nodes: tuple[_Node, ...]
    assets: tuple[_Asset, ...] = ()
    renditions: tuple[object, ...] = ()


def _anchor() -> SpatialAnchor:
    return SpatialAnchor("pdf-page:000001", 0.1, 0.2, 0.8, 0.7)


def _candidate(*, metadata: dict[str, object] | None = None, state=_RecoveryState.AVAILABLE) -> _Candidate:
    node = _Node(
        node_id="table-1",
        node_type=_NodeType.TABLE,
        source_anchors=(_anchor(),),
        asset_ids=("asset-1",),
        metadata=metadata or {},
    )
    asset = _Asset(
        asset_id="asset-1",
        rendition_ids=("rendition-1",) if state is _RecoveryState.AVAILABLE else (),
        recovery_state=state,
    )
    return _Candidate(nodes=(node,), assets=(asset,))


def _attach_with_events(candidate, *, render=None, persist=None):
    render_token = lifecycle._CURRENT_RENDER_EVENTS.set(render or {})
    persist_token = lifecycle._CURRENT_PERSIST_EVENTS.set(persist or {})
    try:
        return lifecycle._attach_lifecycle(candidate)
    finally:
        lifecycle._CURRENT_PERSIST_EVENTS.reset(persist_token)
        lifecycle._CURRENT_RENDER_EVENTS.reset(render_token)


def test_deployment_revision_reads_exact_primary_commit(tmp_path, monkeypatch) -> None:
    revision = "4e09f015634871b56fba1eccd683790b7ec1b49d"
    path = tmp_path / "production-revision.txt"
    path.write_text(
        f"Application source commit: {revision}\nApplication source branch: main\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(lifecycle, "_REVISION_FILE", path)

    assert lifecycle._deployment_revision() == revision


def test_deployment_revision_falls_back_to_test_record(tmp_path, monkeypatch) -> None:
    revision = "b" * 40
    missing = tmp_path / "missing-production-revision.txt"
    fallback = tmp_path / "ocrmypdf-test-revision.txt"
    fallback.write_text(f"Application source commit: {revision}\n", encoding="utf-8")
    monkeypatch.setattr(lifecycle, "_REVISION_FILE", missing)
    monkeypatch.setattr(lifecycle, "_FALLBACK_REVISION_FILE", fallback)

    assert lifecycle._deployment_revision() == revision


def test_processed_visual_node_records_crop_metadata_and_revision(tmp_path, monkeypatch) -> None:
    revision = "a" * 40
    path = tmp_path / "revision.txt"
    path.write_text(f"Application source commit: {revision}\n", encoding="utf-8")
    monkeypatch.setattr(lifecycle, "_REVISION_FILE", path)
    candidate = _candidate(metadata={"opencv_crop_preprocessing": {"status": "quality_gate_original"}})
    key = lifecycle._anchor_key(_anchor())

    result = _attach_with_events(
        candidate,
        render={key: {"stage": "render", "status": "succeeded", "output_size_bytes": 100}},
        persist={
            "table-1": {
                "stage": "persist",
                "status": "succeeded",
                "rendition_count": 1,
                "opencv_crop_recorded": True,
            }
        },
    )

    info = result.nodes[0].metadata["visual_crop_lifecycle"]
    assert info["status"] == "processed"
    assert info["reason"] == "opencv_crop_metadata_attached"
    assert info["crop_metadata_attached"] is True
    assert info["application_source_commit"] == revision
    assert info["rendition_count"] == 1
    assert info["persist"]["opencv_crop_recorded"] is True


def test_persist_success_without_crop_metadata_is_explicit() -> None:
    candidate = _candidate()
    key = lifecycle._anchor_key(_anchor())
    result = _attach_with_events(
        candidate,
        render={key: {"stage": "render", "status": "succeeded"}},
        persist={
            "table-1": {
                "stage": "persist",
                "status": "succeeded",
                "rendition_count": 1,
                "opencv_crop_recorded": False,
            }
        },
    )

    info = result.nodes[0].metadata["visual_crop_lifecycle"]
    assert info["status"] == "persisted_without_crop_metadata"
    assert info["reason"] == "opencv_crop_record_missing_after_persistence"
    assert info["crop_metadata_attached"] is False
    assert info["persist"]["opencv_crop_recorded"] is False


def test_render_failure_is_bounded_and_does_not_need_crop_metadata() -> None:
    candidate = _candidate(state=_RecoveryState.REBUILDABLE)
    key = lifecycle._anchor_key(_anchor())
    result = _attach_with_events(
        candidate,
        render={
            key: {
                "stage": "render",
                "status": "failed",
                "error_type": "RuntimeError",
            }
        },
    )

    info = result.nodes[0].metadata["visual_crop_lifecycle"]
    assert info["status"] == "render_failed"
    assert info["reason"] == "visual_crop_render_failed"
    assert info["render"]["error_type"] == "RuntimeError"
    assert info["asset_recovery_states"] == ["rebuildable"]
    assert info["rendition_count"] == 0


def test_visual_node_without_any_probe_event_is_explicitly_not_observed() -> None:
    result = _attach_with_events(_candidate(state=_RecoveryState.REBUILDABLE))
    info = result.nodes[0].metadata["visual_crop_lifecycle"]

    assert info["status"] == "not_attempted_or_skipped"
    assert info["reason"] == "visual_crop_not_observed"
    assert info["render"]["status"] == "not_observed"
    assert info["persist"]["status"] == "not_observed"


def test_non_visual_nodes_are_untouched() -> None:
    node = _Node(
        node_id="p-1",
        node_type=_NodeType.PARAGRAPH,
        source_anchors=(_anchor(),),
        metadata={"keep": "yes"},
    )
    result = _attach_with_events(_Candidate(nodes=(node,)))

    assert result.nodes[0] is node
    assert result.nodes[0].metadata == {"keep": "yes"}


def test_contextvars_do_not_leak_between_concurrent_lifecycle_annotations() -> None:
    candidate = _candidate()
    key = lifecycle._anchor_key(_anchor())

    def run(index: int) -> tuple[str, str]:
        render_token = lifecycle._CURRENT_RENDER_EVENTS.set(
            {key: {"stage": "render", "status": "failed", "error_type": f"E{index}"}}
        )
        persist_token = lifecycle._CURRENT_PERSIST_EVENTS.set({})
        try:
            result = lifecycle._attach_lifecycle(candidate)
            info = result.nodes[0].metadata["visual_crop_lifecycle"]
            return str(info["status"]), str(info["render"]["error_type"])
        finally:
            lifecycle._CURRENT_PERSIST_EVENTS.reset(persist_token)
            lifecycle._CURRENT_RENDER_EVENTS.reset(render_token)

    with ThreadPoolExecutor(max_workers=6) as pool:
        values = list(pool.map(run, range(12)))

    assert values == [("render_failed", f"E{index}") for index in range(12)]


def test_active_crop_installer_places_lifecycle_last() -> None:
    source = Path("app/processing/pdf_ingestion.py").read_text(encoding="utf-8")
    semantic = source.index("install_pdf_crop_opencv_semantic_gate_compat()")
    consensus = source.index("install_pdf_crop_opencv_semantic_consensus_compat()")
    anchor = source.index("install_pdf_crop_dark_foreground_anchor_compat()")
    readable = source.index("install_pdf_crop_opencv_readable_diagnostics_compat()")
    lifecycle_install = source.index("install_pdf_visual_crop_lifecycle_compat()")

    assert semantic < consensus < anchor < readable < lifecycle_install


def test_fresh_process_installs_active_render_persist_and_enrichment_probes() -> None:
    script = r'''
import app.processing.pdf_ingestion  # installs the production overlay chain
from app.processing import pdf_visual_assets as visual_assets
from app.processing import pdf_canonicalization as canonicalization


def children(fn):
    return [cell.cell_contents for cell in (getattr(fn, "__closure__", None) or ())]


def contains_marker(root, marker, seen=None):
    if seen is None:
        seen = set()
    if not callable(root) or id(root) in seen:
        return False
    seen.add(id(root))
    if getattr(root, marker, False):
        return True
    return any(contains_marker(value, marker, seen) for value in children(root) if callable(value))

assert contains_marker(
    visual_assets._render_crop,
    "_pdf_visual_crop_lifecycle_probe",
), "render lifecycle probe missing from wrapper chain"
assert contains_marker(
    visual_assets._persist_visual_asset_renditions,
    "_pdf_visual_crop_lifecycle_probe",
), "persist lifecycle probe missing from wrapper chain"
assert contains_marker(
    canonicalization.enrich_candidate_with_pdf_visual_assets,
    "_pdf_visual_crop_lifecycle_annotation",
), "enrichment lifecycle annotation missing from wrapper chain"
assert contains_marker(
    canonicalization.PdfCanonicalizationService.canonicalize,
    "_pdf_crop_opencv_semantic_gate_budget",
), "semantic-gate budget context missing from wrapper chain"
assert contains_marker(
    canonicalization.PdfCanonicalizationService.canonicalize,
    "_pdf_visual_crop_lifecycle_context",
), "visual lifecycle context missing from wrapper chain"
'''
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
