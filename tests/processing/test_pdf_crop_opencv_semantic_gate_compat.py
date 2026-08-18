from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from app.processing import pdf_crop_opencv_candidate_persistence_compat as persistence
from app.processing import pdf_crop_opencv_semantic_gate_compat as gate
from app.processing import pdf_opencv_modal_bridge as opencv_bridge
from app.processing import pdf_opencv_quality_pipeline as v4
from app.structured_content_v2.model import (
    AssetRecoveryStateV2,
    AssetReferenceV2,
    AssetRenditionReferenceV2,
    AssetRenditionRoleV2,
    AssetRoleV2,
)


def _png() -> bytes:
    image = np.full((100, 180, 3), 205, dtype=np.uint8)
    cv2.line(image, (8, 25), (172, 25), (70, 70, 70), 1)
    cv2.putText(
        image,
        "15,000",
        (45, 62),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (45, 45, 45),
        1,
        cv2.LINE_AA,
    )
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _lighten(image: np.ndarray, amount: int, ceiling: int) -> np.ndarray:
    work = image.astype(np.int16)
    mask = work > 170
    work[mask] = np.minimum(work[mask] + amount, ceiling)
    return work.astype(np.uint8)


def _diagnostic() -> v4._GeometryDiagnostic:
    return v4._GeometryDiagnostic(
        perspective_applied=False,
        perspective_confidence=0.0,
        perspective_distortion=0.0,
        deskew_applied=False,
        deskew_angle_degrees=0.0,
        deskew_confidence=0.0,
        residual_angle_degrees=0.0,
        residual_confidence=0.0,
    )


@dataclass
class _Reviewer:
    judgment: dict[str, object]
    calls: int = 0
    model_id: str = "fake-gpt-5.6"

    def judge(self, **kwargs):
        self.calls += 1
        assert kwargs["baseline_png"].startswith(b"\x89PNG")
        assert kwargs["candidate_png"].startswith(b"\x89PNG")
        assert kwargs["difference_png"].startswith(b"\x89PNG")
        return dict(self.judgment)


def _judgment(decision: str) -> dict[str, object]:
    accepted = decision == "accept"
    return {
        "decision": decision,
        "confidence": 0.99,
        "background_improved": True,
        "content_preserved": accepted,
        "unexpected_added_content": False,
        "unexpected_removed_content": not accepted,
        "geometry_changed": False,
        "color_or_fill_changed": False,
        "expected_cleanup_changes": ["paper background normalized"],
        "suspected_content_changes": (
            [] if accepted else ["faint line may be weakened"]
        ),
        "reason": "synthetic test judgment",
    }


def _patch_common(monkeypatch, candidate_builder) -> None:
    monkeypatch.setenv("PDF_CROP_OPENCV_SEMANTIC_GATE_ENABLED", "1")
    monkeypatch.setattr(opencv_bridge, "_whole_page_rejected", lambda manifest: True)
    monkeypatch.setattr(
        v4,
        "_color_features",
        lambda image: v4._ColorFeatures(0.0, 0.0, 0.0, False),
    )
    monkeypatch.setattr(
        v4,
        "_build_geometry_candidate",
        lambda image: (image, _diagnostic()),
    )
    monkeypatch.setattr(
        v4,
        "_gate_geometry_candidate",
        lambda original, candidate, diagnostic: (
            False,
            "geometry_not_required",
            {},
        ),
    )
    monkeypatch.setattr(v4, "_normalize_background", candidate_builder)
    monkeypatch.setattr(
        v4,
        "_gate_background_candidate",
        lambda baseline, candidate: (
            False,
            "content_guard_rejected",
            {"edge_retention": 0.61, "long_lines_safe": False},
        ),
    )


def test_llm_accepts_opencv_candidate_even_when_legacy_gate_rejects(monkeypatch) -> None:
    source = _png()
    _patch_common(monkeypatch, lambda image: _lighten(image, 25, 245))
    reviewer = _Reviewer(_judgment("accept"))

    selected, metadata = gate.process_visual_crop_opencv_semantic_gate(
        source,
        page_manifest={"route": "quality_gate_original"},
        reviewer_factory=lambda: reviewer,
    )

    assert reviewer.calls == 1
    assert selected != source
    assert metadata["selected"] == "background"
    assert metadata["background"]["accepted"] is True
    assert metadata["background"]["gate"]["decision_role"] == "diagnostic_only"
    assert metadata["background"]["gate"]["accepted"] is False
    assert metadata["semantic_gate"]["status"] == "accepted"
    assert metadata["foreground_lock_used"] is False
    assert metadata["gpt_image_used"] is False
    assert metadata["legacy_generated_image_path"] == "retired_not_installed"
    assert metadata["opencv_candidate_sha256"] == hashlib.sha256(selected).hexdigest()
    assert all(not isinstance(value, bytes) for value in metadata.values())


def test_llm_rejection_keeps_original_even_when_legacy_gate_would_accept(monkeypatch) -> None:
    source = _png()
    _patch_common(monkeypatch, lambda image: _lighten(image, 20, 240))
    monkeypatch.setattr(
        v4,
        "_gate_background_candidate",
        lambda baseline, candidate: (
            True,
            "accepted",
            {"edge_retention": 0.95},
        ),
    )
    reviewer = _Reviewer(_judgment("reject"))

    selected, metadata = gate.process_visual_crop_opencv_semantic_gate(
        source,
        page_manifest={"route": "quality_gate_original"},
        reviewer_factory=lambda: reviewer,
    )

    assert reviewer.calls == 1
    assert selected == source
    assert metadata["selected"] == "original"
    assert metadata["background"]["accepted"] is False
    assert metadata["background"]["gate"]["accepted"] is True
    assert metadata["background"]["gate"]["decision_role"] == "diagnostic_only"
    assert metadata["semantic_gate"]["status"] == "rejected"
    assert isinstance(metadata["opencv_candidate_sha256"], str)


def test_legacy_gate_diagnostic_failure_does_not_block_llm(monkeypatch) -> None:
    source = _png()
    _patch_common(monkeypatch, lambda image: _lighten(image, 20, 240))

    def fail_legacy_gate(*args, **kwargs):
        raise RuntimeError("diagnostic failure")

    monkeypatch.setattr(v4, "_gate_background_candidate", fail_legacy_gate)
    reviewer = _Reviewer(_judgment("accept"))

    selected, metadata = gate.process_visual_crop_opencv_semantic_gate(
        source,
        page_manifest={"route": "quality_gate_original"},
        reviewer_factory=lambda: reviewer,
    )

    assert reviewer.calls == 1
    assert selected != source
    assert metadata["background"]["gate"] == {
        "decision_role": "diagnostic_only",
        "status": "diagnostic_failed",
        "error_type": "RuntimeError",
    }


def test_catastrophic_candidate_skips_llm(monkeypatch) -> None:
    source = _png()
    _patch_common(monkeypatch, lambda image: np.full_like(image, 255))
    reviewer = _Reviewer(_judgment("accept"))

    selected, metadata = gate.process_visual_crop_opencv_semantic_gate(
        source,
        page_manifest={"route": "quality_gate_original"},
        reviewer_factory=lambda: reviewer,
    )

    assert reviewer.calls == 0
    assert selected == source
    semantic = metadata["semantic_gate"]
    assert semantic["invoked"] is False
    assert semantic["status"] == "catastrophic_rejected_without_llm"
    catastrophic = metadata["background"]["catastrophic_gate"]
    assert catastrophic["passed"] is False
    assert catastrophic["near_solid_output"] is True
    assert isinstance(metadata["opencv_candidate_sha256"], str)


def test_high_mean_sparse_candidate_is_not_catastrophic_just_for_being_white() -> None:
    baseline = np.full((200, 300, 3), 245, dtype=np.uint8)
    candidate = np.full((200, 300, 3), 255, dtype=np.uint8)
    cv2.line(candidate, (20, 80), (280, 80), (90, 90, 90), 1)
    cv2.putText(
        candidate,
        "1",
        (145, 120),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (40, 40, 40),
        1,
        cv2.LINE_AA,
    )
    cv2.line(baseline, (20, 80), (280, 80), (90, 90, 90), 1)
    cv2.putText(
        baseline,
        "1",
        (145, 120),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (40, 40, 40),
        1,
        cv2.LINE_AA,
    )

    assert float(np.mean(cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY))) > 253.8
    passed, reason, metrics = gate._catastrophic_gate(baseline, candidate)
    assert passed is True
    assert reason == "catastrophic_gate_passed"
    assert metrics["near_solid_output"] is False


def test_active_gate_has_no_legacy_generated_image_runtime_dependency() -> None:
    source = Path(gate.__file__).read_text(encoding="utf-8")
    assert "pdf_crop_llm_semantic_v2" not in source
    assert "pdf_crop_llm_background_cleanup" not in source
    assert "gpt-image-2" not in source
    assert "foreground_lock" not in source.lower().replace("foreground_lock_used", "")


def test_change_evidence_is_local_and_bounded() -> None:
    baseline = _png()
    image = cv2.imdecode(np.frombuffer(baseline, np.uint8), cv2.IMREAD_COLOR)
    candidate = _lighten(image, 18, 235)
    candidate_png = gate._encode_png(candidate)

    difference_png, panels, metrics = gate._change_evidence(
        baseline,
        candidate_png,
    )

    assert difference_png.startswith(b"\x89PNG")
    assert len(panels) <= gate._DEFAULT_MAX_CHANGE_ROIS
    assert metrics["changed_pixel_count"] > 0
    assert metrics["roi_count"] == len(panels)


def test_candidate_capture_uses_private_context_not_public_metadata(monkeypatch) -> None:
    source = cv2.imdecode(np.frombuffer(_png(), np.uint8), cv2.IMREAD_COLOR)
    original = v4._normalize_background
    monkeypatch.setattr(v4, "_normalize_background", lambda image: _lighten(image, 10, 230))
    try:
        persistence._install_candidate_capture()
        token = persistence._CURRENT_CANDIDATES.set([])
        try:
            candidate = v4._normalize_background(source)
            pending = persistence._CURRENT_CANDIDATES.get()
            assert pending is not None and len(pending) == 1
            assert pending[0].startswith(b"\x89PNG")
            assert candidate.shape == source.shape
        finally:
            persistence._CURRENT_CANDIDATES.reset(token)
    finally:
        v4._normalize_background = original


def test_rejected_candidate_is_persisted_as_extra_downloadable_rendition() -> None:
    from app.processing import pdf_visual_assets as visual_assets

    source = _png()
    candidate = cv2.imdecode(np.frombuffer(source, np.uint8), cv2.IMREAD_COLOR)
    candidate = _lighten(candidate, 25, 240)
    ok, encoded = cv2.imencode(".png", candidate)
    assert ok
    candidate_png = encoded.tobytes()

    asset_id = "asset:test"
    base_rendition = AssetRenditionReferenceV2(
        rendition_id=f"rendition:{asset_id}:normalized",
        asset_id=asset_id,
        role=AssetRenditionRoleV2.NORMALIZED,
        artifact_ref="storage://selected",
        media_type="image/png",
        checksum="selected",
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
        rebuildable=True,
    )
    base_asset = AssetReferenceV2(
        asset_id=asset_id,
        role=AssetRoleV2.TABLE_RENDERING,
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
        source_unit_ids=("pdf-page:000001",),
        rendition_ids=(base_rendition.rendition_id,),
        metadata={},
    )

    class Storage:
        def put(self, data, reference, **kwargs):
            return SimpleNamespace(
                reference=reference,
                checksum_sha256=hashlib.sha256(data).hexdigest(),
            )

    original_persist = visual_assets._persist_visual_asset_renditions

    def fake_persist(**kwargs):
        return base_asset, (base_rendition,)

    token_candidates = persistence._CURRENT_CANDIDATES.set([candidate_png])
    token_crops = opencv_bridge._CURRENT_CROPS.set(
        {"node-1": {"selected": "original"}}
    )
    try:
        visual_assets._persist_visual_asset_renditions = fake_persist
        persistence._install_persistence()
        asset, renditions = visual_assets._persist_visual_asset_renditions(
            asset_id=asset_id,
            role=AssetRoleV2.TABLE_RENDERING,
            node=SimpleNamespace(node_id="node-1"),
            anchor=SimpleNamespace(source_unit_id="pdf-page:000001"),
            png=source,
            storage=Storage(),
            source_kind="test",
            enhancer=None,
        )
        assert len(renditions) == 2
        diagnostic = asset.metadata["diagnostic_opencv_candidate"]
        assert diagnostic["status"] == "available"
        assert diagnostic["selected_for_reader"] is False
        assert diagnostic["rendition_id"].endswith(":opencv_candidate")
        assert "artifact_ref" not in diagnostic
        diagnostic_rendition = next(
            item for item in renditions if item.rendition_id == diagnostic["rendition_id"]
        )
        assert diagnostic_rendition.artifact_ref
        assert (
            opencv_bridge._CURRENT_CROPS.get()["node-1"][
                "diagnostic_opencv_candidate"
            ]
            == diagnostic
        )
    finally:
        visual_assets._persist_visual_asset_renditions = original_persist
        opencv_bridge._CURRENT_CROPS.reset(token_crops)
        persistence._CURRENT_CANDIDATES.reset(token_candidates)
