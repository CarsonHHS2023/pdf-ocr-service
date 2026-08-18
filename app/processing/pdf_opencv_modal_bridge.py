"""Test-branch bridge from stable OpenCV v4 preprocessing into Modal metadata and visual crops.

The bridge deliberately reuses the existing v4 candidate builders and quality gates.
It does not change any OpenCV threshold. LLM visual enhancement is disabled here;
failed crop-level quality gates are recorded as a deferred LLM fallback only.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict, replace
import hashlib
import json
import threading
from typing import Any, Mapping, Sequence

import cv2
import numpy as np

_MANIFESTS_BY_ATTEMPT: dict[tuple[str, str], dict[str, object]] = {}
_MANIFEST_LOCK = threading.Lock()
_CURRENT_MANIFEST: ContextVar[dict[str, object] | None] = ContextVar(
    "opencv_v4_current_manifest", default=None
)
_CURRENT_CROPS: ContextVar[dict[str, dict[str, object]] | None] = ContextVar(
    "opencv_v4_current_crops", default=None
)
_PENDING_CROPS: ContextVar[list[dict[str, object]] | None] = ContextVar(
    "opencv_v4_pending_crops", default=None
)
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _manifest_page_map(manifest: Mapping[str, object] | None) -> dict[int, dict[str, object]]:
    if not isinstance(manifest, Mapping):
        return {}
    pages = manifest.get("pages")
    if not isinstance(pages, (list, tuple)):
        return {}
    result: dict[int, dict[str, object]] = {}
    for item in pages:
        if not isinstance(item, Mapping):
            continue
        page_number = item.get("page_number")
        if isinstance(page_number, int) and not isinstance(page_number, bool) and page_number > 0:
            result[page_number] = _json_clone(dict(item))
    return result


def _page_number_from_source_unit_id(source_unit_id: str) -> int | None:
    prefix = "pdf-page:"
    if not isinstance(source_unit_id, str) or not source_unit_id.startswith(prefix):
        return None
    try:
        page_number = int(source_unit_id[len(prefix) :])
    except ValueError:
        return None
    return page_number if page_number > 0 else None


def _page_manifest_for_source_unit(
    manifest: Mapping[str, object] | None,
    source_unit_id: str,
) -> dict[str, object] | None:
    page_number = _page_number_from_source_unit_id(source_unit_id)
    if page_number is None:
        return None
    return _manifest_page_map(manifest).get(page_number)


def _whole_page_rejected(page_manifest: Mapping[str, object] | None) -> bool:
    """Use both v4 gate decisions, not route alone, to authorize a crop retry."""
    if not isinstance(page_manifest, Mapping):
        return False
    if page_manifest.get("route") != "quality_gate_original":
        return False
    if page_manifest.get("selected") != "original":
        return False
    geometry = page_manifest.get("geometry")
    background = page_manifest.get("background")
    if not isinstance(geometry, Mapping) or not isinstance(background, Mapping):
        return False
    return bool(
        geometry.get("accepted") is False
        and background.get("attempted") is True
        and background.get("accepted") is False
        and isinstance(geometry.get("gate"), Mapping)
        and isinstance(background.get("gate"), Mapping)
    )


def _decode_png(png_bytes: bytes) -> np.ndarray:
    if not isinstance(png_bytes, bytes) or not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("visual crop must be PNG bytes")
    decoded = cv2.imdecode(np.frombuffer(png_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None or decoded.size == 0:
        raise ValueError("visual crop PNG could not be decoded")
    return np.ascontiguousarray(decoded)


def _encode_png(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("OpenCV visual crop could not be encoded")
    return encoded.tobytes()


def _deferred_llm(required: bool) -> dict[str, object]:
    return {
        "required": required,
        "status": "deferred" if required else "not_required",
        "invoked": False,
    }


def process_visual_crop_v4(
    png_bytes: bytes,
    *,
    page_manifest: Mapping[str, object] | None,
) -> tuple[bytes, dict[str, object]]:
    """Retry stable v4 on one Modal-bounded figure/table crop when its page was rejected."""
    source_checksum = hashlib.sha256(png_bytes).hexdigest()
    base: dict[str, object] = {
        "version": "opencv_unified_quality_gate_experiment_v4",
        "scope": "modal_bbox_visual_crop",
        "source_sha256": source_checksum,
        "page_retry_eligible": _whole_page_rejected(page_manifest),
        "whole_page_route": page_manifest.get("route") if isinstance(page_manifest, Mapping) else None,
        "whole_page_selected": page_manifest.get("selected") if isinstance(page_manifest, Mapping) else None,
    }
    if not base["page_retry_eligible"]:
        base.update(
            {
                "status": "not_required",
                "selected": "original",
                "changed": False,
                "output_sha256": source_checksum,
                "llm_fallback": _deferred_llm(False),
            }
        )
        return png_bytes, base

    from app.processing import pdf_opencv_quality_pipeline as v4

    try:
        source_bgr = _decode_png(png_bytes)
        color = v4._color_features(source_bgr)
        geometry_candidate, geometry_diag = v4._build_geometry_candidate(source_bgr)
        geometry_accepted, geometry_reason, geometry_gate = v4._gate_geometry_candidate(
            source_bgr,
            geometry_candidate,
            geometry_diag,
        )
        geometry_selected = geometry_candidate if geometry_accepted else source_bgr

        background_attempted = not color.color_critical
        background_accepted = False
        background_reason = "color_critical_background_skipped"
        background_gate: dict[str, object] = {}
        selected_bgr = geometry_selected
        if background_attempted:
            background_candidate = v4._normalize_background(geometry_selected)
            background_accepted, background_reason, background_gate = v4._gate_background_candidate(
                geometry_selected,
                background_candidate,
            )
            if background_accepted:
                selected_bgr = background_candidate

        changed = bool(geometry_accepted or background_accepted)
        selected = (
            "geometry_and_background"
            if geometry_accepted and background_accepted
            else "geometry"
            if geometry_accepted
            else "background"
            if background_accepted
            else "original"
        )
        output = _encode_png(selected_bgr) if changed else png_bytes
        metadata = {
            **base,
            "status": "accepted" if changed else "quality_gate_original",
            "selected": selected,
            "changed": changed,
            "output_sha256": hashlib.sha256(output).hexdigest(),
            "color": asdict(color),
            "geometry": {
                **asdict(geometry_diag),
                "accepted": geometry_accepted,
                "reason": geometry_reason,
                "gate": geometry_gate,
            },
            "background": {
                "attempted": background_attempted,
                "accepted": background_accepted,
                "reason": background_reason,
                "gate": background_gate,
            },
            "llm_fallback": _deferred_llm(not changed),
        }
        return output, _json_clone(metadata)
    except Exception as exc:
        metadata = {
            **base,
            "status": "processing_failed",
            "selected": "original",
            "changed": False,
            "output_sha256": source_checksum,
            "error_type": type(exc).__name__,
            "llm_fallback": _deferred_llm(True),
        }
        return png_bytes, metadata


def _capture_manifest(processed: Any, processing_attempt_id: str) -> dict[str, object]:
    from app.processing import pdf_opencv_quality_pipeline as pipeline

    checksum = str(processed.checksum_sha256)
    fallback = {
        "version": processed.version,
        "output_sha256": checksum,
        "output_size_bytes": processed.byte_size,
        "changed_page_count": processed.changed_page_count,
        "pages": [],
    }
    with pipeline._DIAGNOSTIC_LOCK:
        stored = pipeline._DIAGNOSTIC_MANIFESTS.get(checksum)
        if isinstance(stored, dict):
            stored["paddle_vl_skipped"] = False
            stored["modal_processing_connected"] = True
            stored["visual_crop_retry_enabled"] = True
            manifest = _json_clone(stored)
        else:
            manifest = fallback
            manifest["paddle_vl_skipped"] = False
            manifest["modal_processing_connected"] = True
            manifest["visual_crop_retry_enabled"] = True
    with _MANIFEST_LOCK:
        key = (processing_attempt_id, checksum)
        _MANIFESTS_BY_ATTEMPT[key] = _json_clone(manifest)
        while len(_MANIFESTS_BY_ATTEMPT) > 64:
            oldest = next(iter(_MANIFESTS_BY_ATTEMPT))
            _MANIFESTS_BY_ATTEMPT.pop(oldest, None)
    return manifest


def _manifest_for_attempt(
    processing_attempt_id: str | None,
    checksum: str | None,
) -> dict[str, object] | None:
    if not processing_attempt_id or not checksum:
        return None
    with _MANIFEST_LOCK:
        manifest = _MANIFESTS_BY_ATTEMPT.get((processing_attempt_id, checksum))
        return _json_clone(manifest) if manifest is not None else None


def _merge_manifest_into_raw_pages(
    raw_result: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, object] | None,
) -> list[dict[str, Any]]:
    page_map = _manifest_page_map(manifest)
    merged: list[dict[str, Any]] = []
    for page in raw_result:
        copied = dict(page)
        page_number = copied.get("page_number")
        page_metadata = copied.get("metadata")
        metadata = dict(page_metadata) if isinstance(page_metadata, Mapping) else {}
        if isinstance(page_number, int) and page_number in page_map:
            metadata["opencv_preprocessing"] = _json_clone(page_map[page_number])
        copied["metadata"] = metadata
        merged.append(copied)
    return merged


def _attach_manifest_to_bundle(bundle: Any, manifest: Mapping[str, object] | None) -> Any:
    page_map = _manifest_page_map(manifest)
    observations = []
    for observation in bundle.observations:
        page_number = _page_number_from_source_unit_id(observation.source_unit_id)
        metadata = dict(observation.metadata or {})
        if page_number in page_map:
            metadata["page_metadata"] = {
                "opencv_preprocessing": _json_clone(page_map[page_number])
            }
        observations.append(replace(observation, metadata=metadata))

    evidence = []
    for item in bundle.evidence:
        page_number = (
            _page_number_from_source_unit_id(item.source_unit_id)
            if item.source_unit_id is not None
            else None
        )
        metadata = dict(item.metadata or {})
        if page_number in page_map:
            metadata["page_metadata"] = {
                "opencv_preprocessing": _json_clone(page_map[page_number])
            }
        evidence.append(replace(item, metadata=metadata))
    return replace(bundle, observations=tuple(observations), evidence=tuple(evidence))


def _attach_manifest_to_candidate(candidate: Any, manifest: Mapping[str, object] | None) -> Any:
    page_map = _manifest_page_map(manifest)
    nodes = []
    for node in candidate.nodes:
        entries = []
        for source_unit_id in node.source_unit_ids:
            page_number = _page_number_from_source_unit_id(source_unit_id)
            if page_number in page_map:
                entries.append(page_map[page_number])
        metadata = dict(node.metadata or {})
        if len(entries) == 1:
            metadata["opencv_page_preprocessing"] = _json_clone(entries[0])
        elif entries:
            metadata["opencv_page_preprocessing"] = _json_clone(entries)
        nodes.append(replace(node, metadata=metadata))
    return replace(candidate, nodes=tuple(nodes))


def _install_geometry_capture() -> None:
    from app.processing import pdf_geometry_integration as integration

    original_retain = integration.retain_opencv_diagnostics
    if getattr(original_retain, "_opencv_v4_bridge", False):
        return

    def retain_with_manifest(*, source_pdf_bytes, processed, processing_attempt_id):
        _capture_manifest(processed, processing_attempt_id)
        return original_retain(
            source_pdf_bytes=source_pdf_bytes,
            processed=processed,
            processing_attempt_id=processing_attempt_id,
        )

    retain_with_manifest._opencv_v4_bridge = True  # type: ignore[attr-defined]
    integration.retain_opencv_diagnostics = retain_with_manifest

    original_ingest = integration.ProviderInputAwareProcessingOrchestrator._ingest

    async def ingest_with_manifest(self, request, result, page_summary):
        envelope = await original_ingest(self, request, result, page_summary)
        manifest = _manifest_for_attempt(
            self.provider_input.processing_attempt_id,
            self.provider_input.checksum_sha256,
        )
        if manifest is None:
            return envelope
        configuration = integration._thaw_metadata(envelope.provider.configuration)
        configuration["opencv_preprocessing_manifest"] = manifest
        provider = type(envelope.provider)(
            build_tag=envelope.provider.build_tag,
            model_version=envelope.provider.model_version,
            pipeline_version=envelope.provider.pipeline_version,
            configuration=configuration,
            capabilities=integration._thaw_metadata(envelope.provider.capabilities),
            timestamps=integration._thaw_metadata(envelope.provider.timestamps),
            warnings=tuple(integration._thaw_metadata(envelope.provider.warnings)),
            errors=tuple(integration._thaw_metadata(envelope.provider.errors)),
        )
        return replace(envelope, provider=provider)

    ingest_with_manifest._opencv_v4_bridge = True  # type: ignore[attr-defined]
    integration.ProviderInputAwareProcessingOrchestrator._ingest = ingest_with_manifest


def _install_canonicalization_bridge() -> None:
    from app.processing import pdf_canonicalization as canonicalization

    original_normalize = canonicalization.normalize_paddle_pdf_raw_result
    original_transform = canonicalization.transform_spr_v2_to_candidate
    original_canonicalize = canonicalization.PdfCanonicalizationService.canonicalize

    def normalize_with_manifest(raw_result, **kwargs):
        manifest = _CURRENT_MANIFEST.get()
        merged = _merge_manifest_into_raw_pages(raw_result, manifest)
        bundle = original_normalize(merged, **kwargs)
        return _attach_manifest_to_bundle(bundle, manifest)

    def transform_with_manifest(*args, **kwargs):
        candidate = original_transform(*args, **kwargs)
        return _attach_manifest_to_candidate(candidate, _CURRENT_MANIFEST.get())

    def canonicalize_with_manifest(self, envelope):
        checksum = getattr(self, "render_pdf_checksum_sha256", None)
        processing_attempt_id = envelope.identity.atlas_attempt_id
        manifest = _manifest_for_attempt(processing_attempt_id, checksum)
        manifest_token = _CURRENT_MANIFEST.set(manifest)
        crops_token = _CURRENT_CROPS.set({})
        pending_token = _PENDING_CROPS.set([])
        try:
            return original_canonicalize(self, envelope)
        finally:
            _PENDING_CROPS.reset(pending_token)
            _CURRENT_CROPS.reset(crops_token)
            _CURRENT_MANIFEST.reset(manifest_token)
            if checksum:
                with _MANIFEST_LOCK:
                    _MANIFESTS_BY_ATTEMPT.pop((processing_attempt_id, checksum), None)

    canonicalization.normalize_paddle_pdf_raw_result = normalize_with_manifest
    canonicalization.transform_spr_v2_to_candidate = transform_with_manifest
    canonicalization.PdfCanonicalizationService.canonicalize = canonicalize_with_manifest


def _install_visual_crop_bridge() -> None:
    from app.processing import pdf_canonicalization as canonicalization
    from app.processing import pdf_visual_assets as visual_assets
    from app.structured_content_v2.model import (
        AssetRecoveryStateV2,
        AssetRenditionReferenceV2,
        AssetRenditionRoleV2,
    )

    original_render_crop = visual_assets._render_crop
    original_persist = visual_assets._persist_visual_asset_renditions
    original_enrich = visual_assets.enrich_candidate_with_pdf_visual_assets

    # This test phase explicitly defers all visual LLM calls.
    visual_assets.openai_pdf_visual_asset_enhancer_from_env = lambda: None

    def render_crop_with_v4(page, anchor):
        raw_png = original_render_crop(page, anchor)
        page_manifest = _page_manifest_for_source_unit(
            _CURRENT_MANIFEST.get(), anchor.source_unit_id
        )
        selected_png, metadata = process_visual_crop_v4(
            raw_png, page_manifest=page_manifest
        )
        pending = _PENDING_CROPS.get()
        if pending is not None:
            pending.append(
                {
                    "source_unit_id": anchor.source_unit_id,
                    "selected_sha256": hashlib.sha256(selected_png).hexdigest(),
                    "source_png": raw_png,
                    "metadata": metadata,
                }
            )
        return selected_png

    def persist_with_v4(**kwargs):
        kwargs["enhancer"] = None
        selected_png = kwargs["png"]
        anchor = kwargs["anchor"]
        node = kwargs["node"]
        pending = _PENDING_CROPS.get() or []
        selected_sha = hashlib.sha256(selected_png).hexdigest()
        record = None
        for index, item in enumerate(pending):
            if (
                item.get("source_unit_id") == anchor.source_unit_id
                and item.get("selected_sha256") == selected_sha
            ):
                record = pending.pop(index)
                break

        asset, renditions = original_persist(**kwargs)
        if record is None:
            return asset, renditions

        crop_metadata = _json_clone(record["metadata"])
        asset_metadata = dict(asset.metadata or {})
        asset_metadata["opencv_crop_preprocessing"] = crop_metadata
        updated_renditions = list(renditions)

        if crop_metadata.get("changed") is True:
            source_png = record["source_png"]
            source_checksum = hashlib.sha256(source_png).hexdigest()
            source_put = kwargs["storage"].put(
                source_png,
                visual_assets._rendition_reference("visual-opencv-source", source_checksum),
                expected_size=len(source_png),
                expected_sha256=source_checksum,
            )
            source_rendition = AssetRenditionReferenceV2(
                rendition_id=f"rendition:{kwargs['asset_id']}:ocr_source",
                asset_id=kwargs["asset_id"],
                role=AssetRenditionRoleV2.OCR_SOURCE,
                artifact_ref=str(source_put.reference),
                media_type="image/png",
                checksum=source_put.checksum_sha256,
                recovery_state=AssetRecoveryStateV2.AVAILABLE,
                rebuildable=True,
            )
            if all(item.rendition_id != source_rendition.rendition_id for item in updated_renditions):
                updated_renditions.append(source_rendition)

        asset = replace(
            asset,
            metadata=asset_metadata,
            rendition_ids=tuple(item.rendition_id for item in updated_renditions),
        )
        crop_records = _CURRENT_CROPS.get()
        if crop_records is not None:
            crop_records[node.node_id] = crop_metadata
        return asset, tuple(updated_renditions)

    def enrich_with_v4(*args, **kwargs):
        kwargs["enhancer"] = None
        enriched = original_enrich(*args, **kwargs)
        manifest = _CURRENT_MANIFEST.get()
        crop_records = _CURRENT_CROPS.get() or {}
        nodes = []
        for node in enriched.nodes:
            metadata = dict(node.metadata or {})
            page_entries = []
            for source_unit_id in node.source_unit_ids:
                entry = _page_manifest_for_source_unit(manifest, source_unit_id)
                if entry is not None:
                    page_entries.append(entry)
            if len(page_entries) == 1:
                metadata["opencv_page_preprocessing"] = page_entries[0]
            elif page_entries:
                metadata["opencv_page_preprocessing"] = page_entries
            crop_metadata = crop_records.get(node.node_id)
            if crop_metadata is not None:
                metadata["opencv_crop_preprocessing"] = crop_metadata
            nodes.append(replace(node, metadata=metadata))
        return replace(enriched, nodes=tuple(nodes))

    visual_assets._render_crop = render_crop_with_v4
    visual_assets._persist_visual_asset_renditions = persist_with_v4
    visual_assets.enrich_candidate_with_pdf_visual_assets = enrich_with_v4
    canonicalization.enrich_candidate_with_pdf_visual_assets = enrich_with_v4


def install_opencv_v4_modal_bridge() -> None:
    """Install the test-only bridge once per backend process."""
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _install_geometry_capture()
        _install_canonicalization_bridge()
        _install_visual_crop_bridge()
        _INSTALLED = True


__all__ = ["install_opencv_v4_modal_bridge", "process_visual_crop_v4"]
