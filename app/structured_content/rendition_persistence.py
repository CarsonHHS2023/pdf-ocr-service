from __future__ import annotations

from dataclasses import replace

from sqlalchemy import select

from app.models import (
    StructuredContentAsset as AssetRow,
    StructuredContentAssetRendition as RenditionRow,
    StructuredContentCandidate as CandidateRow,
)

from .enums import AssetRecoveryState, AssetRenditionRole
from .errors import CandidatePersistenceError, PersistedCandidateCorrupt
from .identity import AssetId, AssetRenditionId
from .model import AssetRenditionReference, PageDimensions, StructuredContentCandidate
from .persistence_mapping import _dump, _load, sval


def persist_rendition_metadata(session, candidate: StructuredContentCandidate) -> None:
    """Fill the pre-existing rendition rows with canonical rendition metadata."""
    if not candidate.renditions:
        return
    candidate_row = session.execute(
        select(CandidateRow).where(CandidateRow.candidate_id == sval(candidate.candidate_id))
    ).scalar_one_or_none()
    if candidate_row is None:
        raise CandidatePersistenceError("candidate row missing while persisting renditions")

    asset_rows = session.execute(
        select(AssetRow).where(AssetRow.candidate_id == candidate_row.id)
    ).scalars().all()
    asset_by_public_id = {row.asset_id: row for row in asset_rows}
    rendition_by_id = {sval(r.rendition_id): r for r in candidate.renditions}

    for asset in candidate.assets:
        asset_row = asset_by_public_id.get(sval(asset.asset_id))
        if asset_row is None:
            raise CandidatePersistenceError("asset row missing while persisting renditions")
        rows = session.execute(
            select(RenditionRow).where(RenditionRow.asset_id == asset_row.id)
        ).scalars().all()
        row_by_id = {row.rendition_id: row for row in rows}
        for rendition_id in asset.rendition_refs:
            public_rendition_id = sval(rendition_id)
            rendition = rendition_by_id.get(public_rendition_id)
            row = row_by_id.get(public_rendition_id)
            if rendition is None or row is None:
                raise CandidatePersistenceError("rendition registry does not match asset references")
            if sval(rendition.asset_id) != sval(asset.asset_id):
                raise CandidatePersistenceError("rendition belongs to another asset")
            dimensions = rendition.dimensions
            row.role = rendition.role.value
            row.media_type = rendition.media_type
            row.storage_ref = rendition.artifact_ref
            row.checksum = rendition.checksum
            row.width = dimensions.width if dimensions else None
            row.height = dimensions.height if dimensions else None
            row.dimension_unit = dimensions.unit if dimensions else None
            row.recovery_state = rendition.recovery_state.value
            row.rebuildable = rendition.rebuildable
            row.extensions_json = _dump(rendition.extensions)
    session.flush()


def reconstruct_rendition_registry(session, candidate: StructuredContentCandidate) -> StructuredContentCandidate:
    """Rebuild canonical AssetRenditionReference values from persisted rendition rows."""
    candidate_row = session.execute(
        select(CandidateRow).where(CandidateRow.candidate_id == sval(candidate.candidate_id))
    ).scalar_one_or_none()
    if candidate_row is None:
        raise PersistedCandidateCorrupt(["candidate row missing while reconstructing renditions"])

    asset_rows = session.execute(
        select(AssetRow).where(AssetRow.candidate_id == candidate_row.id)
    ).scalars().all()
    public_asset_by_row_id = {row.id: row.asset_id for row in asset_rows}
    if not public_asset_by_row_id:
        return replace(candidate, renditions=())

    rows = session.execute(
        select(RenditionRow)
        .where(RenditionRow.asset_id.in_(tuple(public_asset_by_row_id)))
        .order_by(RenditionRow.rendition_id)
    ).scalars().all()
    renditions: list[AssetRenditionReference] = []
    for row in rows:
        public_asset_id = public_asset_by_row_id.get(row.asset_id)
        if public_asset_id is None:
            raise PersistedCandidateCorrupt(["rendition references missing asset"])
        # Legacy rows only stored a rendition id/order. They remain valid as
        # unresolved references and are not fabricated into canonical objects.
        if row.role is None or row.recovery_state is None:
            continue
        dimensions = None
        if row.width is not None or row.height is not None:
            if row.width is None or row.height is None:
                raise PersistedCandidateCorrupt(["rendition dimensions are incomplete"])
            dimensions = PageDimensions(row.width, row.height, row.dimension_unit or "point")
        try:
            renditions.append(
                AssetRenditionReference(
                    rendition_id=AssetRenditionId(row.rendition_id),
                    asset_id=AssetId(public_asset_id),
                    role=AssetRenditionRole(row.role),
                    media_type=row.media_type,
                    checksum=row.checksum,
                    dimensions=dimensions,
                    artifact_ref=row.storage_ref,
                    recovery_state=AssetRecoveryState(row.recovery_state),
                    rebuildable=row.rebuildable,
                    extensions=_load(row.extensions_json, "asset_rendition.extensions_json"),
                )
            )
        except ValueError as exc:
            raise PersistedCandidateCorrupt(["invalid persisted rendition metadata"]) from exc
    return replace(candidate, renditions=tuple(renditions))


__all__ = ["persist_rendition_metadata", "reconstruct_rendition_registry"]
