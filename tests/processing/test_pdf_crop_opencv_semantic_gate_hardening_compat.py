from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.processing import pdf_crop_opencv_candidate_persistence_compat as persistence
from app.processing import pdf_crop_opencv_candidate_persistence_hardening_compat as persistence_hardening
from app.processing import pdf_crop_opencv_semantic_gate_hardening_compat as hardening
from app.processing import pdf_visual_assets as visual_assets
from app.reader_v2 import assets as reader_assets
from app.source_units import SpatialAnchor
from app.structured_content_v2.model import (
    AssetRecoveryStateV2,
    AssetReferenceV2,
    AssetRenditionReferenceV2,
    AssetRenditionRoleV2,
    AssetRoleV2,
)


def _encode(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def test_large_change_evidence_is_dimension_and_byte_bounded_and_prioritizes_structure() -> None:
    baseline = np.full((1600, 2400, 3), 205, dtype=np.uint8)
    cv2.putText(
        baseline,
        "15,000",
        (900, 760),
        cv2.FONT_HERSHEY_SIMPLEX,
        2.0,
        (45, 45, 45),
        3,
        cv2.LINE_AA,
    )
    cv2.line(baseline, (250, 900), (2150, 900), (90, 90, 90), 2)

    candidate = baseline.copy()
    # Simulate the intended page-wide background lift.
    paper = candidate > 170
    candidate[paper] = np.minimum(candidate[paper].astype(np.int16) + 35, 245).astype(
        np.uint8
    )
    # Simulate a tiny but meaningful structural loss that must not be hidden by the
    # much larger background change.
    cv2.rectangle(candidate, (1180, 885), (1240, 910), (245, 245, 245), -1)

    difference_png, panels, metrics = hardening._bounded_change_evidence(
        _encode(baseline),
        _encode(candidate),
    )

    assert difference_png.startswith(b"\x89PNG")
    assert metrics["difference_dimensions"][0] <= hardening._MAX_DIFFERENCE_SIDE
    assert metrics["difference_dimensions"][1] <= hardening._MAX_DIFFERENCE_SIDE
    assert metrics["difference_bytes"] <= hardening._MAX_DIFFERENCE_BYTES
    assert metrics["roi_payload_bytes"] <= hardening._MAX_TOTAL_PANEL_BYTES
    assert len(panels) <= 6
    assert metrics["priority_changed_pixel_count"] > 0
    assert metrics["roi_count"] == len(metrics["rois"])
    assert metrics["roi_count"] > 0
    assert metrics["rois"][0]["kind"] == "foreground_priority"
    for roi in metrics["rois"]:
        assert roi["panel_dimensions"][0] <= hardening._MAX_PANEL_WIDTH
        assert roi["panel_dimensions"][1] <= hardening._MAX_PANEL_HEIGHT
        assert roi["panel_bytes"] <= hardening._MAX_PANEL_BYTES


def test_judge_metrics_remove_legacy_verdict_but_keep_raw_measurements() -> None:
    metrics = hardening._sanitize_judge_metrics(
        {
            "catastrophic_gate": {"passed": True},
            "legacy_quality_gate": {
                "decision_role": "diagnostic_only",
                "status": "available",
                "accepted": False,
                "reason": "content_guard_rejected",
                "gate": {
                    "before": {"long_line_count": 889},
                    "after": {"long_line_count": 452},
                    "edge_retention": 0.607,
                    "edge_density_ratio": 0.558,
                    "long_lines_safe": False,
                    "background_std_improved": True,
                },
            },
        }
    )

    assert "legacy_quality_gate" not in metrics
    raw = metrics["legacy_quality_measurements"]
    assert raw["before"]["long_line_count"] == 889
    assert raw["after"]["long_line_count"] == 452
    assert raw["edge_retention"] == 0.607
    assert "accepted" not in raw
    assert "reason" not in raw
    assert "long_lines_safe" not in raw
    assert "white means unchanged" in metrics["difference_map_legend"]


def test_semantic_gate_rejects_non_https_provider_base_url() -> None:
    with pytest.raises(ValueError, match="must use HTTPS"):
        hardening._https_base_url("http://example.invalid/v1")
    assert hardening._https_base_url("https://api.openai.com/v1").startswith("https://")


def _asset(asset_id: str, *, metadata=None, rendition_ids=()):
    return AssetReferenceV2(
        asset_id=asset_id,
        role=AssetRoleV2.TABLE_RENDERING,
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
        source_unit_ids=("pdf-page:000001",),
        source_anchors=(SpatialAnchor("pdf-page:000001", 0.1, 0.1, 0.9, 0.9),),
        rendition_ids=tuple(rendition_ids),
        metadata=metadata or {},
    )


class _Storage:
    def __init__(self):
        self.puts = []

    def put(self, data, reference, **kwargs):
        self.puts.append((bytes(data), str(reference)))
        return SimpleNamespace(reference=reference, checksum_sha256=kwargs["expected_sha256"])


def test_diagnostic_candidate_is_written_before_normal_reader_persistence_failure(monkeypatch) -> None:
    candidate_png = _encode(np.full((80, 120, 3), 240, dtype=np.uint8))
    selected_png = _encode(np.full((80, 120, 3), 205, dtype=np.uint8))
    storage = _Storage()

    def fail_normal_persistence(**kwargs):
        raise TypeError("simulated Reader persistence failure")

    original = visual_assets._persist_visual_asset_renditions
    monkeypatch.setattr(visual_assets, "_persist_visual_asset_renditions", fail_normal_persistence)
    persistence_hardening._install_persistence()
    token_candidates = persistence._CURRENT_CANDIDATES.set([candidate_png])
    token_diagnostics = persistence_hardening._CURRENT_DIAGNOSTICS.set({})
    try:
        with pytest.raises(TypeError, match="simulated Reader persistence failure"):
            visual_assets._persist_visual_asset_renditions(
                asset_id="asset:test",
                role=AssetRoleV2.TABLE_RENDERING,
                node=SimpleNamespace(node_id="node-1"),
                anchor=SpatialAnchor("pdf-page:000001", 0.1, 0.1, 0.9, 0.9),
                png=selected_png,
                storage=storage,
                source_kind="test",
                enhancer=None,
            )
        assert len(storage.puts) == 1
        diagnostic = persistence_hardening._CURRENT_DIAGNOSTICS.get()["asset:test"]
        assert diagnostic["status"] == "available"
        assert diagnostic["reader_persistence_status"] == "failed"
        assert diagnostic["reader_persistence_error_type"] == "TypeError"
    finally:
        persistence_hardening._CURRENT_DIAGNOSTICS.reset(token_diagnostics)
        persistence._CURRENT_CANDIDATES.reset(token_candidates)
        visual_assets._persist_visual_asset_renditions = original


def test_successful_hardening_removes_pseudo_original_diagnostic_rendition(monkeypatch) -> None:
    candidate_png = _encode(np.full((80, 120, 3), 240, dtype=np.uint8))
    selected_png = _encode(np.full((80, 120, 3), 205, dtype=np.uint8))
    asset_id = "asset:test"
    selected = AssetRenditionReferenceV2(
        rendition_id=f"rendition:{asset_id}:normalized",
        asset_id=asset_id,
        role=AssetRenditionRoleV2.NORMALIZED,
        artifact_ref="src_11111111111111111111111111111111",
        media_type="image/png",
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
    )
    legacy_diagnostic = AssetRenditionReferenceV2(
        rendition_id=f"rendition:{asset_id}:opencv_candidate",
        asset_id=asset_id,
        role=AssetRenditionRoleV2.ORIGINAL,
        artifact_ref="src_22222222222222222222222222222222",
        media_type="image/png",
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
    )
    base_asset = _asset(
        asset_id,
        metadata={
            "diagnostic_opencv_candidate": {
                "status": "available",
                "selected_for_reader": False,
                "rendition_id": legacy_diagnostic.rendition_id,
            }
        },
        rendition_ids=(selected.rendition_id, legacy_diagnostic.rendition_id),
    )
    storage = _Storage()

    def fake_old_persistence(**kwargs):
        # Mimic the first compatibility layer having produced the pseudo-ORIGINAL
        # diagnostic rendition.
        persistence._CURRENT_CANDIDATES.get().pop(0)
        return base_asset, (selected, legacy_diagnostic)

    original = visual_assets._persist_visual_asset_renditions
    monkeypatch.setattr(visual_assets, "_persist_visual_asset_renditions", fake_old_persistence)
    persistence_hardening._install_persistence()
    token_candidates = persistence._CURRENT_CANDIDATES.set([candidate_png])
    token_diagnostics = persistence_hardening._CURRENT_DIAGNOSTICS.set({})
    try:
        asset, renditions = visual_assets._persist_visual_asset_renditions(
            asset_id=asset_id,
            role=AssetRoleV2.TABLE_RENDERING,
            node=SimpleNamespace(node_id="node-1"),
            anchor=SpatialAnchor("pdf-page:000001", 0.1, 0.1, 0.9, 0.9),
            png=selected_png,
            storage=storage,
            source_kind="test",
            enhancer=None,
        )
        assert [item.rendition_id for item in renditions] == [selected.rendition_id]
        assert asset.rendition_ids == (selected.rendition_id,)
        diagnostic = asset.metadata["diagnostic_opencv_candidate"]
        assert diagnostic["status"] == "available"
        assert diagnostic["selected_for_reader"] is False
        assert "rendition_id" not in diagnostic
    finally:
        persistence_hardening._CURRENT_DIAGNOSTICS.reset(token_diagnostics)
        persistence._CURRENT_CANDIDATES.reset(token_candidates)
        visual_assets._persist_visual_asset_renditions = original


def test_diagnostic_lookup_does_not_require_current_reader_selection(monkeypatch) -> None:
    checksum = "a" * 64
    asset = _asset(
        "asset:test",
        metadata={
            "diagnostic_opencv_candidate": {
                "status": "available",
                "checksum": checksum,
                "diagnostic_id": "opencvdiag:test",
                "selected_for_reader": False,
            }
        },
    )
    candidate = SimpleNamespace(
        document_ref="doc-1",
        candidate_id="candidate-not-selected",
        schema_id="atlas.structured-content-candidate",
        schema_version=2,
        assets=(asset,),
    )

    class Candidates:
        def get_candidate(self, session, candidate_id):
            assert candidate_id == "candidate-not-selected"
            return candidate

    original = reader_assets.build_selected_reader_v2_opencv_diagnostic
    persistence_hardening._install_reader_diagnostic_lookup()
    try:
        delivery = reader_assets.build_selected_reader_v2_opencv_diagnostic(
            session=object(),
            document_ref="doc-1",
            candidate_id="candidate-not-selected",
            asset_id="asset:test",
            candidates=Candidates(),
            selections=SimpleNamespace(
                get_selection=lambda *args, **kwargs: (_ for _ in ()).throw(
                    AssertionError("selection must not be consulted")
                )
            ),
        )
        assert delivery.delivery_state == "available"
        assert delivery.rendition_role == "diagnostic"
        assert delivery.storage_ref == str(
            visual_assets._rendition_reference("visual-opencv-candidate", checksum)
        )
    finally:
        reader_assets.build_selected_reader_v2_opencv_diagnostic = original
