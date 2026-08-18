from __future__ import annotations

from sqlalchemy import select

from app.models import (
    StructuredContentAsset as AssetRow,
    StructuredContentAssetRendition as AssetRenditionRow,
    StructuredContentCandidate as CandidateRow,
)
from app.reader.asset_contracts import (
    ReaderAssetDelivery,
    ReaderAssetNotFound,
    ReaderSelectionChanged,
    ReaderTableDelivery,
    ReaderTableNotFound,
)
from app.reader.contracts import ReaderContentState
from app.reader.service import NoSelectedReaderContent, SelectedReaderCandidateDocumentMismatch
from app.storage.errors import InvalidReference
from app.storage.models import StorageReference
from app.structured_content.enums import AssetRecoveryState, ContentNodeType, NodeRecoveryState
from app.structured_content.identity import AssetId, ContentNodeId, DocumentRef
from app.structured_content.model import TableAttributes
from app.structured_content.persistence_mapping import sval
from app.structured_content.repository import StructuredContentCandidateRepository
from app.structured_content.selection_repository import StructuredContentSelectionRepository

_SAFE_READER_ASSET_MEDIA_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif", "image/avif"}
)


def _selected_candidate(
    *,
    session,
    document_ref: DocumentRef | str,
    expected_candidate_id: str,
    candidate_repository: StructuredContentCandidateRepository | None = None,
    selection_repository: StructuredContentSelectionRepository | None = None,
):
    document_id = sval(document_ref)
    candidates = candidate_repository or StructuredContentCandidateRepository()
    selections = selection_repository or StructuredContentSelectionRepository(candidates)
    selection = selections.get_selection(session, document_id)
    if selection is None:
        raise NoSelectedReaderContent(f"no selected structured content candidate for document {document_id}")
    if selection.candidate_id != expected_candidate_id:
        raise ReaderSelectionChanged(
            f"Reader candidate {expected_candidate_id} is no longer selected for document {document_id}"
        )
    candidate = candidates.get_candidate(session, selection.candidate_id)
    if sval(candidate.document_ref) != document_id:
        raise SelectedReaderCandidateDocumentMismatch(
            f"selected candidate {selection.candidate_id} does not belong to document {document_id}"
        )
    return candidate


def _legacy_delivery_locator(session, *, candidate_id: str, asset_id: str) -> tuple[str | None, str | None, int | None]:
    candidate_row = session.execute(
        select(CandidateRow).where(CandidateRow.candidate_id == candidate_id)
    ).scalar_one_or_none()
    if candidate_row is None:
        return None, None, None
    asset_row = session.execute(
        select(AssetRow).where(
            AssetRow.candidate_id == candidate_row.id,
            AssetRow.asset_id == asset_id,
        )
    ).scalar_one_or_none()
    if asset_row is None:
        return None, None, None
    if asset_row.storage_ref:
        return asset_row.storage_ref, asset_row.media_type, asset_row.byte_size
    rendition = session.execute(
        select(AssetRenditionRow)
        .where(AssetRenditionRow.asset_id == asset_row.id, AssetRenditionRow.storage_ref.is_not(None))
        .order_by(AssetRenditionRow.rendition_order, AssetRenditionRow.rendition_id)
    ).scalars().first()
    if rendition is None:
        return None, None, None
    return rendition.storage_ref, rendition.media_type or asset_row.media_type, None


def _canonical_delivery_locator(candidate, asset) -> tuple[str | None, str | None, int | None]:
    if not candidate.renditions:
        return None, None, None
    registry = {rendition.rendition_id: rendition for rendition in candidate.renditions}
    for rendition_id in asset.rendition_refs:
        rendition = registry.get(rendition_id)
        if (
            rendition is None
            or rendition.recovery_state is not AssetRecoveryState.AVAILABLE
            or not rendition.artifact_ref
        ):
            continue
        try:
            StorageReference.parse(rendition.artifact_ref)
        except InvalidReference:
            continue
        return rendition.artifact_ref, rendition.media_type or asset.media_type, None
    return None, None, None


def build_selected_reader_asset(
    *,
    session,
    document_ref: DocumentRef | str,
    candidate_id: str,
    asset_id: AssetId | str,
    candidate_repository: StructuredContentCandidateRepository | None = None,
    selection_repository: StructuredContentSelectionRepository | None = None,
) -> ReaderAssetDelivery:
    candidate = _selected_candidate(
        session=session,
        document_ref=document_ref,
        expected_candidate_id=candidate_id,
        candidate_repository=candidate_repository,
        selection_repository=selection_repository,
    )
    public_asset_id = sval(asset_id)
    asset = next((item for item in candidate.assets if sval(item.asset_id) == public_asset_id), None)
    if asset is None:
        raise ReaderAssetNotFound(f"asset is not part of selected Reader content: {public_asset_id}")

    if candidate.renditions:
        storage_ref, media_type, byte_size = _canonical_delivery_locator(candidate, asset)
    else:
        storage_ref, media_type, byte_size = _legacy_delivery_locator(
            session,
            candidate_id=sval(candidate.candidate_id),
            asset_id=public_asset_id,
        )
    delivery_media_type = media_type or asset.media_type
    if asset.recovery_state in {AssetRecoveryState.MISSING, AssetRecoveryState.UNAVAILABLE}:
        delivery_state = "unavailable"
        storage_ref = None
    elif storage_ref is not None and delivery_media_type in _SAFE_READER_ASSET_MEDIA_TYPES:
        delivery_state = "available"
    elif asset.recovery_state is AssetRecoveryState.REBUILDABLE and storage_ref is None:
        delivery_state = "rebuildable"
    else:
        delivery_state = "degraded"
        storage_ref = None

    return ReaderAssetDelivery(
        document_ref=sval(candidate.document_ref),
        candidate_id=sval(candidate.candidate_id),
        candidate_schema_id=candidate.schema_id,
        candidate_schema_version=candidate.schema_version,
        asset=asset,
        delivery_state=delivery_state,
        storage_ref=storage_ref,
        delivery_media_type=delivery_media_type,
        delivery_byte_size=byte_size if byte_size is not None else asset.byte_size,
    )


def _node_state(state: NodeRecoveryState) -> ReaderContentState:
    return {
        NodeRecoveryState.COMPLETE: ReaderContentState.READY,
        NodeRecoveryState.PARTIAL: ReaderContentState.PARTIAL,
        NodeRecoveryState.DEGRADED: ReaderContentState.DEGRADED,
        NodeRecoveryState.RECOVERED: ReaderContentState.DEGRADED,
        NodeRecoveryState.UNSUPPORTED: ReaderContentState.UNAVAILABLE,
    }[state]


def build_selected_reader_table(
    *,
    session,
    document_ref: DocumentRef | str,
    candidate_id: str,
    node_id: ContentNodeId | str,
    candidate_repository: StructuredContentCandidateRepository | None = None,
    selection_repository: StructuredContentSelectionRepository | None = None,
) -> ReaderTableDelivery:
    candidate = _selected_candidate(
        session=session,
        document_ref=document_ref,
        expected_candidate_id=candidate_id,
        candidate_repository=candidate_repository,
        selection_repository=selection_repository,
    )
    public_node_id = sval(node_id)
    node = next((item for item in candidate.nodes if sval(item.node_id) == public_node_id), None)
    if (
        node is None
        or node.node_type is not ContentNodeType.TABLE
        or not isinstance(node.attributes, TableAttributes)
    ):
        raise ReaderTableNotFound(f"structured table is not part of selected Reader content: {public_node_id}")
    return ReaderTableDelivery(
        document_ref=sval(candidate.document_ref),
        candidate_id=sval(candidate.candidate_id),
        candidate_schema_id=candidate.schema_id,
        candidate_schema_version=candidate.schema_version,
        page_id=sval(node.page_id),
        node_id=sval(node.node_id),
        content_state=_node_state(node.recovery_state),
        attributes=node.attributes,
    )


__all__ = ["build_selected_reader_asset", "build_selected_reader_table"]
