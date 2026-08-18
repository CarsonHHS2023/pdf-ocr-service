from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.source_units import SourceAnchor
from app.storage.errors import InvalidReference
from app.storage.models import StorageReference
from app.structured_content_v2.model import (
    AssetRecoveryStateV2,
    AssetRenditionReferenceV2,
    AssetRenditionRoleV2,
    AssetReferenceV2,
)
from app.structured_content_v2.repository import StructuredContentCandidateV2Repository
from app.structured_content_v2.selection import (
    StructuredContentV2SelectionNotFound,
    StructuredContentV2SelectionRepository,
)

_SAFE_READER_ASSET_MEDIA_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif", "image/avif"}
)
_READER_RENDITION_ROLE_PRIORITY = {
    AssetRenditionRoleV2.NORMALIZED: 0,
    AssetRenditionRoleV2.ORIGINAL: 1,
    AssetRenditionRoleV2.OCR_SOURCE: 2,
    AssetRenditionRoleV2.THUMBNAIL: 3,
}


class ReaderV2AssetError(RuntimeError):
    pass


class ReaderV2AssetNotFound(ReaderV2AssetError):
    pass


class ReaderV2SelectionChanged(ReaderV2AssetError):
    pass


@dataclass(frozen=True, slots=True)
class ReaderV2AssetDelivery:
    document_ref: str
    candidate_id: str
    candidate_schema_id: str
    candidate_schema_version: int
    asset_id: str
    role: str
    recovery_state: str
    source_unit_ids: tuple[str, ...]
    source_anchors: tuple[SourceAnchor, ...]
    caption: str | None
    alt_text: str | None
    delivery_state: str
    rendition_id: str | None = None
    rendition_role: str | None = None
    rendition_media_type: str | None = None
    rendition_recovery_state: str | None = None
    storage_ref: str | None = None


def _opencv_diagnostic_metadata(asset: AssetReferenceV2) -> Mapping[str, object] | None:
    metadata = asset.metadata if isinstance(asset.metadata, Mapping) else {}
    diagnostic = metadata.get("diagnostic_opencv_candidate")
    return diagnostic if isinstance(diagnostic, Mapping) else None


def _opencv_diagnostic_rendition_id(asset: AssetReferenceV2) -> str | None:
    diagnostic = _opencv_diagnostic_metadata(asset)
    if diagnostic is None:
        return None
    rendition_id = diagnostic.get("rendition_id")
    if not isinstance(rendition_id, str) or not rendition_id.strip():
        return None
    return rendition_id


def _non_reader_diagnostic_rendition_ids(asset: AssetReferenceV2) -> frozenset[str]:
    """Return rejected/catastrophic diagnostics that must never enter Reader fallback."""
    diagnostic = _opencv_diagnostic_metadata(asset)
    if diagnostic is None or diagnostic.get("selected_for_reader") is not False:
        return frozenset()
    rendition_id = _opencv_diagnostic_rendition_id(asset)
    return frozenset({rendition_id}) if rendition_id is not None else frozenset()


def _ordered_renditions(
    candidate,
    asset: AssetReferenceV2,
) -> tuple[AssetRenditionReferenceV2, ...]:
    registry = {item.rendition_id: item for item in candidate.renditions}
    excluded_diagnostics = _non_reader_diagnostic_rendition_ids(asset)
    eligible: list[tuple[int, int, str, AssetRenditionReferenceV2]] = []
    for declared_order, rendition_id in enumerate(asset.rendition_ids):
        # Rejected/catastrophic OpenCV candidates are inspectable only through the
        # explicit diagnostic endpoint. If the candidate was accepted, its
        # selected_for_reader flag is true and the NORMALIZED rendition remains a
        # normal Reader choice.
        if rendition_id in excluded_diagnostics:
            continue
        rendition = registry.get(rendition_id)
        if rendition is None or rendition.asset_id != asset.asset_id:
            continue
        if rendition.recovery_state is not AssetRecoveryStateV2.AVAILABLE:
            continue
        if not rendition.media_type or rendition.media_type not in _SAFE_READER_ASSET_MEDIA_TYPES:
            continue
        try:
            StorageReference.parse(rendition.artifact_ref)
        except InvalidReference:
            continue
        eligible.append(
            (
                _READER_RENDITION_ROLE_PRIORITY.get(rendition.role, 99),
                declared_order,
                rendition.rendition_id,
                rendition,
            )
        )
    return tuple(item[3] for item in sorted(eligible, key=lambda item: item[:3]))


def _select_rendition(candidate, asset: AssetReferenceV2) -> AssetRenditionReferenceV2 | None:
    """Return the highest-priority eligible non-rejected-diagnostic rendition."""
    ordered = _ordered_renditions(candidate, asset)
    return ordered[0] if ordered else None


def _delivery(
    candidate,
    asset: AssetReferenceV2,
    *,
    delivery_state: str,
    rendition: AssetRenditionReferenceV2 | None = None,
) -> ReaderV2AssetDelivery:
    return ReaderV2AssetDelivery(
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
        delivery_state=delivery_state,
        rendition_id=rendition.rendition_id if rendition else None,
        rendition_role=rendition.role.value if rendition else None,
        rendition_media_type=rendition.media_type if rendition else None,
        rendition_recovery_state=rendition.recovery_state.value if rendition else None,
        storage_ref=rendition.artifact_ref if rendition else None,
    )


def _selected_candidate_and_asset(
    *,
    session,
    document_ref: str,
    candidate_id: str,
    asset_id: str,
    candidates: StructuredContentCandidateV2Repository | None = None,
    selections: StructuredContentV2SelectionRepository | None = None,
):
    candidates = candidates or StructuredContentCandidateV2Repository()
    selections = selections or StructuredContentV2SelectionRepository(candidates)
    try:
        selection = selections.get_selection(session, document_ref)
    except StructuredContentV2SelectionNotFound:
        raise
    if selection.candidate_id != candidate_id:
        raise ReaderV2SelectionChanged(
            f"Reader candidate {candidate_id} is no longer selected for document {document_ref}"
        )

    candidate = candidates.get_candidate(session, selection.candidate_id)
    if candidate.document_ref != document_ref:
        raise ReaderV2AssetError("selected candidate belongs to a different document")

    asset = next((item for item in candidate.assets if item.asset_id == asset_id), None)
    if asset is None:
        raise ReaderV2AssetNotFound(
            f"asset is not part of selected Reader v2 content: {asset_id}"
        )
    return candidate, asset


def build_selected_reader_v2_asset_deliveries(
    *,
    session,
    document_ref: str,
    candidate_id: str,
    asset_id: str,
    candidates: StructuredContentCandidateV2Repository | None = None,
    selections: StructuredContentV2SelectionRepository | None = None,
) -> tuple[ReaderV2AssetDelivery, ...]:
    """Return preferred and fallback renditions, excluding rejected diagnostics."""
    candidate, asset = _selected_candidate_and_asset(
        session=session,
        document_ref=document_ref,
        candidate_id=candidate_id,
        asset_id=asset_id,
        candidates=candidates,
        selections=selections,
    )

    if asset.recovery_state in {
        AssetRecoveryStateV2.MISSING,
        AssetRecoveryStateV2.UNAVAILABLE,
    }:
        return (_delivery(candidate, asset, delivery_state="unavailable"),)
    if asset.recovery_state is AssetRecoveryStateV2.REBUILDABLE:
        return (_delivery(candidate, asset, delivery_state="rebuildable"),)

    renditions = _ordered_renditions(candidate, asset)
    if not renditions:
        return (_delivery(candidate, asset, delivery_state="degraded"),)
    return tuple(
        _delivery(candidate, asset, delivery_state="available", rendition=rendition)
        for rendition in renditions
    )


def build_selected_reader_v2_asset(
    *,
    session,
    document_ref: str,
    candidate_id: str,
    asset_id: str,
    candidates: StructuredContentCandidateV2Repository | None = None,
    selections: StructuredContentV2SelectionRepository | None = None,
) -> ReaderV2AssetDelivery:
    """Return the preferred Reader rendition metadata."""
    return build_selected_reader_v2_asset_deliveries(
        session=session,
        document_ref=document_ref,
        candidate_id=candidate_id,
        asset_id=asset_id,
        candidates=candidates,
        selections=selections,
    )[0]


def build_selected_reader_v2_opencv_diagnostic(
    *,
    session,
    document_ref: str,
    candidate_id: str,
    asset_id: str,
    candidates: StructuredContentCandidateV2Repository | None = None,
    selections: StructuredContentV2SelectionRepository | None = None,
) -> ReaderV2AssetDelivery:
    """Return the explicitly retained OpenCV candidate for inspection/download."""
    candidate, asset = _selected_candidate_and_asset(
        session=session,
        document_ref=document_ref,
        candidate_id=candidate_id,
        asset_id=asset_id,
        candidates=candidates,
        selections=selections,
    )
    rendition_id = _opencv_diagnostic_rendition_id(asset)
    if rendition_id is None:
        raise ReaderV2AssetNotFound(
            f"OpenCV diagnostic candidate is not available for asset: {asset_id}"
        )
    rendition = next(
        (
            item
            for item in candidate.renditions
            if item.rendition_id == rendition_id and item.asset_id == asset.asset_id
        ),
        None,
    )
    if rendition is None:
        raise ReaderV2AssetNotFound(
            f"OpenCV diagnostic rendition is not part of selected Reader content: {rendition_id}"
        )
    if (
        rendition.recovery_state is not AssetRecoveryStateV2.AVAILABLE
        or not rendition.media_type
        or rendition.media_type not in _SAFE_READER_ASSET_MEDIA_TYPES
    ):
        return _delivery(candidate, asset, delivery_state="unavailable")
    try:
        StorageReference.parse(rendition.artifact_ref)
    except InvalidReference:
        return _delivery(candidate, asset, delivery_state="unavailable")
    return _delivery(
        candidate,
        asset,
        delivery_state="available",
        rendition=rendition,
    )


__all__ = [
    "ReaderV2AssetDelivery",
    "ReaderV2AssetError",
    "ReaderV2AssetNotFound",
    "ReaderV2SelectionChanged",
    "build_selected_reader_v2_asset",
    "build_selected_reader_v2_asset_deliveries",
    "build_selected_reader_v2_opencv_diagnostic",
]
