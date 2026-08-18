"""Harden retained OpenCV crop diagnostics.

The first persistence compatibility layer captured the right bytes but saved the
candidate only after normal Reader rendition persistence had succeeded. This
layer moves the diagnostic write in front of normal persistence so a rejected or
catastrophic OpenCV candidate remains inspectable even when Reader asset
persistence fails.

Diagnostic candidates are storage artifacts, not semantic Reader renditions. The
layer removes the legacy pseudo-ORIGINAL diagnostic rendition on successful
persistence and exposes the artifact through a checksum-derived inspection
handle. Normal Reader fallback therefore cannot select a rejected candidate.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace
import hashlib
import sys
import threading
from typing import Mapping

from app.processing import pdf_crop_opencv_candidate_persistence_compat as persistence
from app.processing import pdf_opencv_modal_bridge as opencv_bridge

_CURRENT_DIAGNOSTICS: ContextVar[dict[str, dict[str, object]] | None] = ContextVar(
    "pdf_crop_opencv_independent_diagnostics", default=None
)
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _public_diagnostic(value: Mapping[str, object]) -> dict[str, object]:
    allowed = {
        "status",
        "checksum",
        "diagnostic_id",
        "selected_for_reader",
        "reader_persistence_status",
        "reader_persistence_error_type",
        "error_type",
    }
    return {key: value[key] for key in allowed if key in value}


def _diagnostic_reference(checksum: str):
    from app.processing import pdf_visual_assets as visual_assets

    return visual_assets._rendition_reference("visual-opencv-candidate", checksum)


def _install_context() -> None:
    from app.processing import pdf_canonicalization as canonicalization

    original = canonicalization.PdfCanonicalizationService.canonicalize
    if getattr(original, "_opencv_candidate_independent_diagnostic_context", False):
        return

    def canonicalize_with_independent_diagnostics(self, envelope):
        token = _CURRENT_DIAGNOSTICS.set({})
        try:
            return original(self, envelope)
        finally:
            _CURRENT_DIAGNOSTICS.reset(token)

    canonicalize_with_independent_diagnostics._opencv_candidate_independent_diagnostic_context = True  # type: ignore[attr-defined]
    canonicalization.PdfCanonicalizationService.canonicalize = (
        canonicalize_with_independent_diagnostics
    )


def _install_persistence() -> None:
    from app.processing import pdf_visual_assets as visual_assets

    original = visual_assets._persist_visual_asset_renditions
    if getattr(original, "_opencv_candidate_independent_diagnostic_persistence", False):
        return

    def persist_with_independent_diagnostic(**kwargs):
        pending = persistence._CURRENT_CANDIDATES.get()
        candidate_png = pending[0] if pending else None
        asset_id = kwargs["asset_id"]
        selected_png = kwargs["png"]
        diagnostics = _CURRENT_DIAGNOSTICS.get()
        diagnostic: dict[str, object] | None = None

        if candidate_png is not None:
            checksum = hashlib.sha256(candidate_png).hexdigest()
            selected_checksum = hashlib.sha256(selected_png).hexdigest()
            diagnostic = {
                "status": "pending",
                "checksum": checksum,
                "diagnostic_id": f"opencvdiag:{checksum[:24]}",
                "selected_for_reader": checksum == selected_checksum,
                "reader_persistence_status": "pending",
            }
            try:
                put = kwargs["storage"].put(
                    candidate_png,
                    _diagnostic_reference(checksum),
                    expected_size=len(candidate_png),
                    expected_sha256=checksum,
                )
                if put.checksum_sha256 != checksum:
                    raise RuntimeError("OpenCV diagnostic checksum mismatch")
            except Exception as exc:
                diagnostic.update(
                    {
                        "status": "persistence_failed",
                        "error_type": type(exc).__name__,
                    }
                )
            else:
                diagnostic["status"] = "available"
            if diagnostics is not None:
                diagnostics[asset_id] = dict(diagnostic)

        try:
            asset, renditions = original(**kwargs)
        except Exception as exc:
            if diagnostic is not None:
                diagnostic.update(
                    {
                        "reader_persistence_status": "failed",
                        "reader_persistence_error_type": type(exc).__name__,
                    }
                )
                if diagnostics is not None:
                    diagnostics[asset_id] = dict(diagnostic)
            raise

        if diagnostic is None:
            return asset, renditions

        diagnostic["reader_persistence_status"] = "succeeded"
        if diagnostics is not None:
            diagnostics[asset_id] = dict(diagnostic)

        # Remove only the legacy rejected-candidate pseudo-rendition. Accepted
        # candidates use the real NORMALIZED rendition and must remain untouched.
        legacy_id = f"rendition:{asset_id}:opencv_candidate"
        cleaned_renditions = tuple(
            item for item in renditions if item.rendition_id != legacy_id
        )
        asset_metadata = dict(asset.metadata or {})
        asset_metadata["diagnostic_opencv_candidate"] = _public_diagnostic(diagnostic)
        asset = replace(
            asset,
            metadata=asset_metadata,
            rendition_ids=tuple(
                rendition_id
                for rendition_id in asset.rendition_ids
                if rendition_id != legacy_id
            ),
        )

        crop_records = opencv_bridge._CURRENT_CROPS.get()
        node = kwargs.get("node")
        node_id = getattr(node, "node_id", None)
        if crop_records is not None and isinstance(node_id, str):
            crop_metadata = crop_records.get(node_id)
            if isinstance(crop_metadata, dict):
                crop_metadata["diagnostic_opencv_candidate"] = _public_diagnostic(
                    diagnostic
                )

        return asset, cleaned_renditions

    persist_with_independent_diagnostic._opencv_candidate_independent_diagnostic_persistence = True  # type: ignore[attr-defined]
    visual_assets._persist_visual_asset_renditions = persist_with_independent_diagnostic


def _install_enrichment_attachment() -> None:
    from app.processing import pdf_canonicalization as canonicalization

    original = canonicalization.enrich_candidate_with_pdf_visual_assets
    if getattr(original, "_opencv_candidate_independent_diagnostic_attachment", False):
        return

    def enrich_with_independent_diagnostics(*args, **kwargs):
        enriched = original(*args, **kwargs)
        diagnostics = _CURRENT_DIAGNOSTICS.get() or {}
        if not diagnostics:
            return enriched
        assets = []
        for asset in enriched.assets:
            diagnostic = diagnostics.get(asset.asset_id)
            if diagnostic is None:
                assets.append(asset)
                continue
            metadata = dict(asset.metadata or {})
            metadata["diagnostic_opencv_candidate"] = _public_diagnostic(diagnostic)
            assets.append(replace(asset, metadata=metadata))
        return replace(enriched, assets=tuple(assets))

    enrich_with_independent_diagnostics._opencv_candidate_independent_diagnostic_attachment = True  # type: ignore[attr-defined]
    canonicalization.enrich_candidate_with_pdf_visual_assets = enrich_with_independent_diagnostics


def _candidate_for_document(
    *,
    session,
    document_ref: str,
    candidate_id: str,
    candidates,
):
    candidate = candidates.get_candidate(session, candidate_id)
    if candidate.document_ref != document_ref:
        from app.reader_v2.assets import ReaderV2AssetNotFound

        raise ReaderV2AssetNotFound(
            f"diagnostic candidate does not belong to document: {candidate_id}"
        )
    return candidate


def _install_reader_diagnostic_lookup() -> None:
    from app.reader_v2 import assets as reader_assets
    from app.structured_content_v2.repository import StructuredContentCandidateV2Repository

    original = reader_assets.build_selected_reader_v2_opencv_diagnostic
    if getattr(original, "_opencv_candidate_checksum_diagnostic_lookup", False):
        return

    def build_opencv_diagnostic(
        *,
        session,
        document_ref: str,
        candidate_id: str,
        asset_id: str,
        candidates=None,
        selections=None,
    ):
        candidates = candidates or StructuredContentCandidateV2Repository()
        candidate = _candidate_for_document(
            session=session,
            document_ref=document_ref,
            candidate_id=candidate_id,
            candidates=candidates,
        )
        asset = next(
            (item for item in candidate.assets if item.asset_id == asset_id),
            None,
        )
        if asset is None:
            raise reader_assets.ReaderV2AssetNotFound(
                f"asset is not part of candidate: {asset_id}"
            )
        metadata = asset.metadata if isinstance(asset.metadata, Mapping) else {}
        diagnostic = metadata.get("diagnostic_opencv_candidate")
        if not isinstance(diagnostic, Mapping) or diagnostic.get("status") != "available":
            raise reader_assets.ReaderV2AssetNotFound(
                f"OpenCV diagnostic candidate is not available for asset: {asset_id}"
            )
        checksum = diagnostic.get("checksum")
        if isinstance(checksum, str) and len(checksum) == 64:
            return reader_assets.ReaderV2AssetDelivery(
                document_ref=candidate.document_ref,
                candidate_id=candidate.candidate_id,
                candidate_schema_id=candidate.schema_id,
                candidate_schema_version=candidate.schema_version,
                asset_id=asset.asset_id,
                role=asset.role.value,
                recovery_state=asset.recovery_state.value,
                source_unit_ids=asset.source_unit_ids,
                source_anchors=asset.source_anchors,
                caption=asset.caption,
                alt_text=asset.alt_text,
                delivery_state="available",
                rendition_id=str(diagnostic.get("diagnostic_id") or "opencv-diagnostic"),
                rendition_role="diagnostic",
                rendition_media_type="image/png",
                rendition_recovery_state="available",
                storage_ref=str(_diagnostic_reference(checksum)),
            )

        # Backward compatibility for candidates persisted before this hardening
        # layer: they stored a diagnostic rendition_id but no checksum-derived
        # diagnostic handle. Keep the old selected-candidate resolver only for
        # that legacy shape; new diagnostics never depend on Reader selection.
        legacy_rendition_id = diagnostic.get("rendition_id")
        if isinstance(legacy_rendition_id, str) and legacy_rendition_id.strip():
            return original(
                session=session,
                document_ref=document_ref,
                candidate_id=candidate_id,
                asset_id=asset_id,
                candidates=candidates,
                selections=selections,
            )
        raise reader_assets.ReaderV2AssetNotFound(
            f"OpenCV diagnostic checksum is invalid for asset: {asset_id}"
        )

    build_opencv_diagnostic._opencv_candidate_checksum_diagnostic_lookup = True  # type: ignore[attr-defined]
    reader_assets.build_selected_reader_v2_opencv_diagnostic = build_opencv_diagnostic
    router_module = sys.modules.get("app.routers.reader_v2")
    if router_module is not None:
        setattr(
            router_module,
            "build_selected_reader_v2_opencv_diagnostic",
            build_opencv_diagnostic,
        )


def install_pdf_crop_opencv_candidate_persistence_hardening_compat() -> None:
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _install_context()
        _install_persistence()
        _install_enrichment_attachment()
        _install_reader_diagnostic_lookup()
        _INSTALLED = True


__all__ = [
    "install_pdf_crop_opencv_candidate_persistence_hardening_compat",
]
