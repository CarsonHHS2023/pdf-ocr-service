"""Retain every crop-level OpenCV background candidate for inspection.

The semantic gate may accept, reject, or skip LLM review for an OpenCV candidate.
Regardless of that decision, this test-only layer captures the deterministic
background-normalization output in a private ContextVar and persists it as a
durable diagnostic artifact during visual-asset persistence. If the candidate is
already the selected NORMALIZED rendition, no duplicate artifact is written;
otherwise a diagnostic rendition is appended.

Candidate bytes and durable storage locators never enter public crop metadata.
Public diagnostic metadata contains only status, checksum, rendition identity,
and whether the candidate is selected for Reader. Persistence is best-effort and
never changes Reader selection or PDF processing failure behavior.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace
import hashlib
import threading

import cv2

from app.processing import pdf_opencv_modal_bridge as opencv_bridge
from app.processing import pdf_opencv_quality_pipeline as v4

_CURRENT_CANDIDATES: ContextVar[list[bytes] | None] = ContextVar(
    "pdf_crop_opencv_diagnostic_candidates", default=None
)
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _encode_png(image) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("OpenCV diagnostic candidate could not be encoded")
    return encoded.tobytes()


def _install_canonicalization_context() -> None:
    from app.processing import pdf_canonicalization as canonicalization

    original = canonicalization.PdfCanonicalizationService.canonicalize
    if getattr(original, "_pdf_crop_opencv_candidate_context", False):
        return

    def canonicalize_with_opencv_candidate_context(self, envelope):
        token = _CURRENT_CANDIDATES.set([])
        try:
            return original(self, envelope)
        finally:
            _CURRENT_CANDIDATES.reset(token)

    canonicalize_with_opencv_candidate_context._pdf_crop_opencv_candidate_context = True  # type: ignore[attr-defined]
    canonicalization.PdfCanonicalizationService.canonicalize = canonicalize_with_opencv_candidate_context


def _install_candidate_capture() -> None:
    original = v4._normalize_background
    if getattr(original, "_pdf_crop_opencv_candidate_capture", False):
        return

    def normalize_background_with_candidate_capture(image):
        candidate = original(image)
        pending = _CURRENT_CANDIDATES.get()
        if pending is not None:
            pending.append(_encode_png(candidate))
        return candidate

    normalize_background_with_candidate_capture._pdf_crop_opencv_candidate_capture = True  # type: ignore[attr-defined]
    v4._normalize_background = normalize_background_with_candidate_capture


def _install_persistence() -> None:
    from app.processing import pdf_visual_assets as visual_assets
    from app.structured_content_v2.model import (
        AssetRecoveryStateV2,
        AssetRenditionReferenceV2,
        AssetRenditionRoleV2,
    )

    original = visual_assets._persist_visual_asset_renditions
    if getattr(original, "_pdf_crop_opencv_candidate_persistence", False):
        return

    def persist_with_opencv_candidate(**kwargs):
        pending = _CURRENT_CANDIDATES.get()
        candidate_png = pending.pop(0) if pending else None
        asset, renditions = original(**kwargs)
        if candidate_png is None:
            return asset, renditions

        node = kwargs["node"]
        asset_id = kwargs["asset_id"]
        selected_png = kwargs["png"]
        candidate_checksum = hashlib.sha256(candidate_png).hexdigest()
        selected_checksum = hashlib.sha256(selected_png).hexdigest()
        updated_renditions = list(renditions)
        diagnostic: dict[str, object]

        try:
            if candidate_checksum == selected_checksum:
                selected_rendition = next(
                    (
                        item
                        for item in updated_renditions
                        if item.role is AssetRenditionRoleV2.NORMALIZED
                    ),
                    None,
                )
                diagnostic = {
                    "status": "available",
                    "selected_for_reader": True,
                    "checksum": candidate_checksum,
                    "rendition_id": (
                        selected_rendition.rendition_id
                        if selected_rendition is not None
                        else None
                    ),
                }
            else:
                put = kwargs["storage"].put(
                    candidate_png,
                    visual_assets._rendition_reference(
                        "visual-opencv-candidate", candidate_checksum
                    ),
                    expected_size=len(candidate_png),
                    expected_sha256=candidate_checksum,
                )
                rendition = AssetRenditionReferenceV2(
                    rendition_id=f"rendition:{asset_id}:opencv_candidate",
                    asset_id=asset_id,
                    # Reuse an existing role without changing the public contract;
                    # rendition_id + asset metadata identify this as diagnostic.
                    role=AssetRenditionRoleV2.ORIGINAL,
                    artifact_ref=str(put.reference),
                    media_type="image/png",
                    checksum=put.checksum_sha256,
                    recovery_state=AssetRecoveryStateV2.AVAILABLE,
                    rebuildable=True,
                )
                if all(item.rendition_id != rendition.rendition_id for item in updated_renditions):
                    updated_renditions.append(rendition)
                diagnostic = {
                    "status": "available",
                    "selected_for_reader": False,
                    "checksum": candidate_checksum,
                    "rendition_id": rendition.rendition_id,
                }
        except Exception as exc:
            diagnostic = {
                "status": "persistence_failed",
                "selected_for_reader": candidate_checksum == selected_checksum,
                "checksum": candidate_checksum,
                "error_type": type(exc).__name__,
            }

        asset_metadata = dict(asset.metadata or {})
        asset_metadata["diagnostic_opencv_candidate"] = diagnostic
        asset = replace(
            asset,
            metadata=asset_metadata,
            rendition_ids=tuple(item.rendition_id for item in updated_renditions),
        )

        crop_records = opencv_bridge._CURRENT_CROPS.get()
        node_id = getattr(node, "node_id", None)
        if crop_records is not None and isinstance(node_id, str):
            crop_metadata = crop_records.get(node_id)
            if isinstance(crop_metadata, dict):
                crop_metadata["diagnostic_opencv_candidate"] = dict(diagnostic)

        return asset, tuple(updated_renditions)

    persist_with_opencv_candidate._pdf_crop_opencv_candidate_persistence = True  # type: ignore[attr-defined]
    visual_assets._persist_visual_asset_renditions = persist_with_opencv_candidate


def install_pdf_crop_opencv_candidate_persistence_compat() -> None:
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _install_canonicalization_context()
        _install_candidate_capture()
        _install_persistence()
        _INSTALLED = True


__all__ = ["install_pdf_crop_opencv_candidate_persistence_compat"]
