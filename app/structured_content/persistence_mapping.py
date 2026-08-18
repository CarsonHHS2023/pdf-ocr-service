from __future__ import annotations

import uuid
from dataclasses import asdict, is_dataclass
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.models import (
    decode_json_text, encode_json_text,
    StructuredContentAsset as AssetRow, StructuredContentAssetEvidence, StructuredContentAssetRendition,
    StructuredContentCandidate as CandidateRow, StructuredContentEvidence as EvidenceRow,
    StructuredContentNode as NodeRow, StructuredContentNodeAsset, StructuredContentNodeEvidence,
    StructuredContentNodeWarning, StructuredContentPage as PageRow, StructuredContentPageEvidence,
    StructuredContentPageRoot, StructuredContentPageWarning, StructuredContentTableCell,
    StructuredContentWarning as WarningRow, StructuredContentWarningEvidence,
)
from .enums import *
from .errors import PersistedCandidateCorrupt, CandidatePersistenceError
from .identity import *
from .model import *

_ATTR_TO_TYPE = {HeadingAttributes:'heading', ListAttributes:'list', ListItemAttributes:'list_item', TableAttributes:'table', FigureAttributes:'figure', CaptionAttributes:'caption', FormulaAttributes:'formula'}
_TYPE_TO_ATTR = {v:k for k,v in _ATTR_TO_TYPE.items()}
_PERSISTENCE_META_KEY = "__atlas_persistence__"
_PERSISTENCE_META_VERSION = 1


def new_id() -> str: return str(uuid.uuid4())
def sval(v): return v.value if hasattr(v, 'value') else v


def _dump(v):
    return encode_json_text(_jsonify(v))


def _load(txt, field):
    try: return decode_json_text(txt) or {}
    except Exception as exc: raise PersistedCandidateCorrupt([f"malformed {field}"]) from exc


def _jsonify(v):
    if v is None or isinstance(v, (str,int,float,bool)): return v
    if hasattr(v, 'value'): return v.value
    if isinstance(v, tuple): return [_jsonify(x) for x in v]
    if isinstance(v, list): return [_jsonify(x) for x in v]
    if isinstance(v, dict): return {str(k): _jsonify(x) for k,x in v.items()}
    if is_dataclass(v): return {f.name:_jsonify(getattr(v,f.name)) for f in v.__dataclass_fields__.values() if getattr(v,f.name) is not None and getattr(v,f.name) != () and getattr(v,f.name) != {}}
    return v


def _candidate_extensions_for_storage(c: StructuredContentCandidate) -> dict[str, Any]:
    extensions = dict(_jsonify(c.extensions))
    if _PERSISTENCE_META_KEY in extensions:
        raise CandidatePersistenceError("candidate extensions use reserved persistence metadata key")
    extensions[_PERSISTENCE_META_KEY] = {
        "version": _PERSISTENCE_META_VERSION,
        "recovery_warning_ids": [_jsonify(warning_id) for warning_id in c.recovery_summary.warning_ids],
        "recovery_policy_ref": c.recovery_summary.recovery_policy_ref,
        "node_registry_order": [sval(node.node_id) for node in c.nodes],
    }
    return extensions


def _candidate_extensions_from_storage(txt: str | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    stored = _load(txt, 'candidate.extensions_json')
    if not isinstance(stored, dict):
        raise PersistedCandidateCorrupt(["candidate extensions must be an object"])
    stored = dict(stored)
    metadata = stored.pop(_PERSISTENCE_META_KEY, None)
    if metadata is None:
        return stored, None
    if not isinstance(metadata, dict) or metadata.get("version") != _PERSISTENCE_META_VERSION:
        raise PersistedCandidateCorrupt(["unsupported candidate persistence metadata"])
    return stored, metadata


def _ordered_node_rows(nodes_r, metadata: dict[str, Any] | None):
    if metadata is None:
        return sorted(nodes_r, key=lambda row: row.node_id)
    registry_order = metadata.get("node_registry_order")
    if not isinstance(registry_order, list) or not all(isinstance(node_id, str) and node_id for node_id in registry_order):
        raise PersistedCandidateCorrupt(["invalid persisted node registry order"])
    if len(registry_order) != len(set(registry_order)):
        raise PersistedCandidateCorrupt(["duplicate persisted node registry order"])
    rows_by_id = {row.node_id: row for row in nodes_r}
    if set(registry_order) != set(rows_by_id):
        raise PersistedCandidateCorrupt(["persisted node registry order does not match node registry"])
    return [rows_by_id[node_id] for node_id in registry_order]


def _bbox_cols(loc):
    bb = loc.source_location.bounding_box if loc and loc.source_location else None
    sp = loc.source_location.text_span if loc and loc.source_location else None
    return dict(source_page_index=(loc.source_location.source_page_index if loc and loc.source_location else loc.source_page_index if loc else None), bbox_left=bb.left if bb else None, bbox_top=bb.top if bb else None, bbox_right=bb.right if bb else None, bbox_bottom=bb.bottom if bb else None, text_span_start=sp.start if sp else None, text_span_end=sp.end if sp else None)


def _loc_from(row):
    if row.source_page_index is None: return None
    bb = None if row.bbox_left is None else NormalizedBoundingBox(row.bbox_left,row.bbox_top,row.bbox_right,row.bbox_bottom)
    sp = None if row.text_span_start is None else SourceTextSpan(row.text_span_start,row.text_span_end)
    return SourceLocation(row.source_page_index, bb, sp)


def _dims(row):
    return None if row.width is None else PageDimensions(row.width,row.height,row.dimension_unit or 'point')


def _attrs_to_row(node):
    a=node.attributes
    if a is None: return None, None
    t=_ATTR_TO_TYPE.get(type(a))
    if not t: raise CandidatePersistenceError(f"unsupported attribute type for node {sval(node.node_id)}")
    return t, _dump(a)


def _attrs_from_row(row, cells):
    if row.attribute_type is None: return None
    data = _load(row.attribute_json, 'attribute_json')
    try:
        if row.attribute_type=='heading': return HeadingAttributes(**data)
        if row.attribute_type=='list': return ListAttributes(**data)
        if row.attribute_type=='list_item': return ListItemAttributes(**data)
        if row.attribute_type=='table':
            struct=data.get('structure', {})
            tcells=tuple(TableCell(c.row_index,c.column_index,c.row_span,c.column_span,c.text, _load(c.extensions_json,'table_cell.extensions_json')) for c in cells)
            return TableAttributes(TableStructure(struct.get('row_count',0), struct.get('column_count',0), tcells), rendered_asset_id=AssetId(data['rendered_asset_id']) if data.get('rendered_asset_id') else None, extensions=data.get('extensions',{}))
        if row.attribute_type=='figure': return FigureAttributes(caption_node_id=ContentNodeId(data['caption_node_id']) if data.get('caption_node_id') else None, rendered_asset_id=AssetId(data['rendered_asset_id']) if data.get('rendered_asset_id') else None, extensions=data.get('extensions',{}))
        if row.attribute_type=='caption': return CaptionAttributes(target_node_id=ContentNodeId(data['target_node_id']) if data.get('target_node_id') else None, target_asset_id=AssetId(data['target_asset_id']) if data.get('target_asset_id') else None, extensions=data.get('extensions',{}))
        if row.attribute_type=='formula': return FormulaAttributes(**data)
    except Exception as exc: raise PersistedCandidateCorrupt([f"invalid attributes for node {row.node_id}"]) from exc
    raise PersistedCandidateCorrupt([f"unsupported attribute_type {row.attribute_type}"])


def insert_graph(session, c: StructuredContentCandidate) -> None:
    try:
        cr = CandidateRow(id=new_id(), candidate_id=sval(c.candidate_id), document_id=sval(c.document_ref), lineage_key=sval(c.lineage_key), schema_id=c.schema_id, schema_version=c.schema_version, source_file_ref=None, processing_run_ref=sval(c.processing_run_ref), raw_result_ref=sval(c.raw_result_ref), structured_processing_result_ref=sval(c.structured_processing_result_ref), transformer_ref=sval(c.transformer_ref), transformation_policy_ref=sval(c.transformation_policy_ref), recovery_state=c.recovery_summary.state.value, total_page_count=c.recovery_summary.total_pages, complete_page_count=c.recovery_summary.complete_pages, degraded_page_count=c.recovery_summary.degraded_pages, no_usable_page_count=c.recovery_summary.no_usable_semantic_content_pages, unavailable_page_count=c.recovery_summary.unavailable_pages, unsupported_page_count=0, extensions_json=_dump(_candidate_extensions_for_storage(c)))
        session.add(cr); session.flush()
        pages={}
        for p in c.pages:
            d=p.dimensions; f=p.coordinate_frame
            pr=PageRow(id=new_id(), candidate_id=cr.id, page_id=sval(p.page_id), page_order=p.page_order, source_page_index=p.source_page_index, recovery_state=p.recovery_state.value, page_label=p.page_label, width=d.width if d else None, height=d.height if d else None, dimension_unit=d.unit if d else None, coordinate_origin=f.origin if f else None, coordinate_unit=f.unit if f else None, rotation_applied=f.rotation_applied if f else None, rotation_degrees=p.rotation_degrees, extensions_json=_dump(p.extensions))
            session.add(pr); pages[sval(p.page_id)]=pr
        session.flush(); nodes={}
        for n in c.nodes:
            if len(n.source_locations)>1: raise CandidatePersistenceError(f"multiple source_locations not representable for node {sval(n.node_id)}")
            at,aj=_attrs_to_row(n); loc=n.source_locations[0] if n.source_locations else None; bb=loc.bounding_box if loc else None; sp=loc.text_span if loc else None
            nr=NodeRow(id=new_id(), candidate_id=cr.id, page_id=pages[sval(n.page_id)].id, node_id=sval(n.node_id), lineage_key=sval(n.lineage_key), node_type=n.node_type.value, sibling_order=n.sibling_order, text=n.text, recovery_state=n.recovery_state.value, source_page_index=loc.source_page_index if loc else None, bbox_left=bb.left if bb else None, bbox_top=bb.top if bb else None, bbox_right=bb.right if bb else None, bbox_bottom=bb.bottom if bb else None, text_span_start=sp.start if sp else None, text_span_end=sp.end if sp else None, attribute_type=at, attribute_json=aj, extensions_json=_dump(n.extensions))
            session.add(nr); nodes[sval(n.node_id)]=nr
        session.flush()
        for n in c.nodes:
            if n.parent_id: nodes[sval(n.node_id)].parent_node_id=nodes[sval(n.parent_id)].id
        evs={}
        for e in c.evidence:
            loc=e.source_location; bb=loc.bounding_box if loc else None; sp=loc.text_span if loc else None
            er=EvidenceRow(id=new_id(), candidate_id=cr.id, evidence_id=sval(e.evidence_id), kind=e.kind.value, source_file_ref=sval(e.source_file_ref), source_page_index=e.source_page_index, raw_result_ref=sval(e.raw_result_ref), structured_processing_result_ref=sval(e.structured_processing_result_ref), processing_run_ref=None, spr_node_ref=e.spr_node_ref, spr_observation_ref=e.spr_observation_ref, spr_evidence_ref=e.spr_evidence_ref, warning_ref=e.warning_ref, bbox_left=bb.left if bb else None, bbox_top=bb.top if bb else None, bbox_right=bb.right if bb else None, bbox_bottom=bb.bottom if bb else None, text_span_start=sp.start if sp else None, text_span_end=sp.end if sp else None, extensions_json=_dump(e.extensions))
            session.add(er); evs[sval(e.evidence_id)]=er
        warns={}
        for w in c.warnings:
            wr=WarningRow(id=new_id(), candidate_id=cr.id, warning_id=w.warning_id, code=w.code, severity=w.severity.value, scope_path=w.scope_path, safe_summary=w.safe_summary, recoverable=w.recoverable, blocking_hint=w.blocking_hint, details_json=_dump(w.details), extensions_json=_dump(w.extensions)); session.add(wr); warns[w.warning_id]=wr
        assets={}
        for a in c.assets:
            loc=a.source_location; bb=loc.bounding_box if loc else None; d=a.dimensions
            ar=AssetRow(id=new_id(), candidate_id=cr.id, asset_id=sval(a.asset_id), role=a.role.value, recovery_state=a.recovery_state.value, media_type=a.media_type, checksum=a.checksum, byte_size=a.byte_size, width=d.width if d else None, height=d.height if d else None, dimension_unit=d.unit if d else None, source_page_index=loc.source_page_index if loc else None, bbox_left=bb.left if bb else None, bbox_top=bb.top if bb else None, bbox_right=bb.right if bb else None, bbox_bottom=bb.bottom if bb else None, caption=a.caption, alt_text=a.alt_text, description=a.description, extensions_json=_dump(a.extensions)); session.add(ar); assets[sval(a.asset_id)]=ar
        session.flush()
        for a in c.assets:
            ar=assets[sval(a.asset_id)]
            for i,rid in enumerate(a.rendition_refs): session.add(StructuredContentAssetRendition(id=new_id(), asset_id=ar.id, rendition_id=sval(rid), rendition_order=i, rebuildable=False))
        for p in c.pages:
            pr=pages[sval(p.page_id)]
            for i,nid in enumerate(p.root_node_ids): session.add(StructuredContentPageRoot(id=new_id(), candidate_id=cr.id, page_id=pr.id, node_id=nodes[sval(nid)].id, root_order=i))
            for i,eid in enumerate(p.evidence_ids): session.add(StructuredContentPageEvidence(id=new_id(), page_id=pr.id, evidence_id=evs[sval(eid)].id, association_order=i))
            for i,wid in enumerate(p.warning_ids): session.add(StructuredContentPageWarning(id=new_id(), page_id=pr.id, warning_id=warns[wid].id, association_order=i))
        for n in c.nodes:
            nr=nodes[sval(n.node_id)]
            for i,eid in enumerate(n.evidence_ids): session.add(StructuredContentNodeEvidence(id=new_id(), node_id=nr.id, evidence_id=evs[sval(eid)].id, association_order=i))
            for i,aid in enumerate(n.asset_ids): session.add(StructuredContentNodeAsset(id=new_id(), node_id=nr.id, asset_id=assets[sval(aid)].id, association_order=i))
            for i,wid in enumerate(n.warning_ids): session.add(StructuredContentNodeWarning(id=new_id(), node_id=nr.id, warning_id=warns[wid].id, association_order=i))
        for a in c.assets:
            for i,eid in enumerate(a.evidence_ids): session.add(StructuredContentAssetEvidence(id=new_id(), asset_id=assets[sval(a.asset_id)].id, evidence_id=evs[sval(eid)].id, association_order=i))
        for w in c.warnings:
            for i,eid in enumerate(w.evidence_ids): session.add(StructuredContentWarningEvidence(id=new_id(), warning_id=warns[w.warning_id].id, evidence_id=evs[sval(eid)].id, association_order=i))
        for n in c.nodes:
            if isinstance(n.attributes, TableAttributes):
                for cell in n.attributes.structure.cells: session.add(StructuredContentTableCell(id=new_id(), table_node_id=nodes[sval(n.node_id)].id, row_index=cell.row_index, column_index=cell.column_index, row_span=cell.row_span, column_span=cell.column_span, text=cell.text, extensions_json=_dump(cell.extensions)))
        session.flush()
    except SQLAlchemyError:
        raise
    except Exception as exc:
        raise CandidatePersistenceError(str(exc)) from exc


def reconstruct(session, candidate_id: str) -> StructuredContentCandidate:
    from sqlalchemy import select
    cr=session.execute(select(CandidateRow).where(CandidateRow.candidate_id==candidate_id)).scalar_one_or_none()
    if cr is None: raise KeyError(candidate_id)
    try:
        candidate_extensions, persistence_metadata = _candidate_extensions_from_storage(cr.extensions_json)
        pages=session.query(PageRow).filter_by(candidate_id=cr.id).order_by(PageRow.page_order, PageRow.page_id).all()
        nodes_r=session.query(NodeRow).filter_by(candidate_id=cr.id).all()
        ev_r=session.query(EvidenceRow).filter_by(candidate_id=cr.id).order_by(EvidenceRow.evidence_id).all()
        w_r=session.query(WarningRow).filter_by(candidate_id=cr.id).order_by(WarningRow.warning_id).all()
        a_r=session.query(AssetRow).filter_by(candidate_id=cr.id).order_by(AssetRow.asset_id).all()
        page_by_id={p.id:p for p in pages}; node_by_id={n.id:n for n in nodes_r}; ev_by_id={e.id:e for e in ev_r}; w_by_id={w.id:w for w in w_r}; a_by_id={a.id:a for a in a_r}
        page_ev=_assoc(session, StructuredContentPageEvidence, 'page_id', page_by_id, ev_by_id); page_w=_assoc(session, StructuredContentPageWarning, 'page_id', page_by_id, w_by_id)
        node_ev=_assoc(session, StructuredContentNodeEvidence, 'node_id', node_by_id, ev_by_id); node_a=_assoc(session, StructuredContentNodeAsset, 'node_id', node_by_id, a_by_id); node_w=_assoc(session, StructuredContentNodeWarning, 'node_id', node_by_id, w_by_id)
        asset_ev=_assoc(session, StructuredContentAssetEvidence, 'asset_id', a_by_id, ev_by_id); warn_ev=_assoc(session, StructuredContentWarningEvidence, 'warning_id', w_by_id, ev_by_id)
        roots={}
        for r in session.query(StructuredContentPageRoot).filter_by(candidate_id=cr.id).order_by(StructuredContentPageRoot.page_id, StructuredContentPageRoot.root_order).all():
            if r.node_id not in node_by_id: raise PersistedCandidateCorrupt(['root references missing node'])
            roots.setdefault(r.page_id,[]).append(node_by_id[r.node_id].node_id)
        pages_out=tuple(ContentPage(ContentPageId(p.page_id), p.source_page_index, p.page_order, PageRecoveryState(p.recovery_state), tuple(ContentNodeId(x) for x in roots.get(p.id,[])), page_label=p.page_label, dimensions=_dims(p), rotation_degrees=p.rotation_degrees, coordinate_frame=CoordinateFrame(p.coordinate_origin,p.coordinate_unit,p.rotation_applied) if p.coordinate_origin else None, evidence_ids=tuple(EvidenceReferenceId(x) for x in page_ev.get(p.id,())), warning_ids=tuple(page_w.get(p.id,())), extensions=_load(p.extensions_json,'page.extensions_json')) for p in pages)
        evidence_out=[]
        for e in ev_r:
            loc=_loc_from(e)
            evidence_out.append(EvidenceReference(EvidenceReferenceId(e.evidence_id), EvidenceKind(e.kind), source_file_ref=SourceFileRef(e.source_file_ref) if e.source_file_ref else None, source_page_index=e.source_page_index, source_location=loc, raw_result_ref=RawResultRef(e.raw_result_ref) if e.raw_result_ref else None, structured_processing_result_ref=StructuredProcessingResultRef(e.structured_processing_result_ref) if e.structured_processing_result_ref else None, spr_node_ref=e.spr_node_ref, spr_observation_ref=e.spr_observation_ref, spr_evidence_ref=e.spr_evidence_ref, warning_ref=e.warning_ref, extensions=_load(e.extensions_json,'evidence.extensions_json')))
        warn_out=tuple(ContentWarning(w.warning_id,w.code,WarningSeverity(w.severity),w.scope_path,w.safe_summary,evidence_ids=tuple(EvidenceReferenceId(x) for x in warn_ev.get(w.id,())),recoverable=w.recoverable,blocking_hint=w.blocking_hint,details=_load(w.details_json,'warning.details_json'),extensions=_load(w.extensions_json,'warning.extensions_json')) for w in w_r)
        assets_out=[]
        for a in a_r:
            rends=session.query(StructuredContentAssetRendition).filter_by(asset_id=a.id).order_by(StructuredContentAssetRendition.rendition_order).all()
            loc=None if a.source_page_index is None else SourceLocation(a.source_page_index, None if a.bbox_left is None else NormalizedBoundingBox(a.bbox_left,a.bbox_top,a.bbox_right,a.bbox_bottom))
            assets_out.append(AssetReference(AssetId(a.asset_id),AssetRole(a.role),AssetRecoveryState(a.recovery_state),source_location=loc,media_type=a.media_type,checksum=a.checksum,byte_size=a.byte_size,dimensions=_dims(a),rendition_refs=tuple(AssetRenditionId(r.rendition_id) for r in rends),evidence_ids=tuple(EvidenceReferenceId(x) for x in asset_ev.get(a.id,())),caption=a.caption,alt_text=a.alt_text,description=a.description,extensions=_load(a.extensions_json,'asset.extensions_json')))
        cells_by_node={}
        for cell in session.query(StructuredContentTableCell).filter(StructuredContentTableCell.table_node_id.in_([n.id for n in nodes_r] or [''])).order_by(StructuredContentTableCell.row_index, StructuredContentTableCell.column_index).all(): cells_by_node.setdefault(cell.table_node_id,[]).append(cell)
        nodes_out=[]
        for n in _ordered_node_rows(nodes_r, persistence_metadata):
            if n.page_id not in page_by_id: raise PersistedCandidateCorrupt(['node references missing page'])
            parent_id=node_by_id[n.parent_node_id].node_id if n.parent_node_id else None
            loc=_loc_from(n)
            nodes_out.append(ContentNode(ContentNodeId(n.node_id),ContentLineageKey(n.lineage_key),ContentNodeType(n.node_type),ContentPageId(page_by_id[n.page_id].page_id),n.sibling_order,NodeRecoveryState(n.recovery_state),parent_id=ContentNodeId(parent_id) if parent_id else None,text=n.text,attributes=_attrs_from_row(n,cells_by_node.get(n.id,[])),source_locations=(loc,) if loc else (),evidence_ids=tuple(EvidenceReferenceId(x) for x in node_ev.get(n.id,())),asset_ids=tuple(AssetId(x) for x in node_a.get(n.id,())),warning_ids=tuple(node_w.get(n.id,())),extensions=_load(n.extensions_json,'node.extensions_json')))
        partial_pages = cr.total_page_count - cr.complete_page_count - cr.degraded_page_count - cr.unavailable_page_count - cr.no_usable_page_count
        recovery_warning_ids = ()
        recovery_policy_ref = None
        if persistence_metadata is not None:
            raw_warning_ids = persistence_metadata.get("recovery_warning_ids", [])
            if not isinstance(raw_warning_ids, list):
                raise PersistedCandidateCorrupt(["invalid persisted recovery warning ids"])
            recovery_warning_ids = tuple(raw_warning_ids)
            recovery_policy_ref = persistence_metadata.get("recovery_policy_ref")
            if recovery_policy_ref is not None and not isinstance(recovery_policy_ref, str):
                raise PersistedCandidateCorrupt(["invalid persisted recovery policy ref"])
        rs=ContentRecoverySummary(ContentRecoveryState(cr.recovery_state), cr.total_page_count, cr.complete_page_count, partial_pages=partial_pages, degraded_pages=cr.degraded_page_count, unavailable_pages=cr.unavailable_page_count, no_usable_semantic_content_pages=cr.no_usable_page_count, warning_ids=recovery_warning_ids, recovery_policy_ref=recovery_policy_ref)
        return StructuredContentCandidate(cr.schema_id, cr.schema_version, DocumentRef(cr.document_id), ContentCandidateId(cr.candidate_id), ContentLineageKey(cr.lineage_key), rs, pages_out, tuple(nodes_out), tuple(evidence_out), tuple(assets_out), warn_out, candidate_extensions, transformer_ref=TransformerRef(cr.transformer_ref) if cr.transformer_ref else None, transformation_policy_ref=TransformationPolicyRef(cr.transformation_policy_ref) if cr.transformation_policy_ref else None, processing_run_ref=ProcessingRunRef(cr.processing_run_ref) if cr.processing_run_ref else None, raw_result_ref=RawResultRef(cr.raw_result_ref) if cr.raw_result_ref else None, structured_processing_result_ref=StructuredProcessingResultRef(cr.structured_processing_result_ref) if cr.structured_processing_result_ref else None)
    except PersistedCandidateCorrupt: raise
    except Exception as exc: raise PersistedCandidateCorrupt([str(exc)[:120]]) from exc


def _assoc(session, cls, left, left_map, right_map):
    out={}
    left_ids=tuple(left_map)
    if not left_ids:
        return out
    query=session.query(cls).filter(getattr(cls,left).in_(left_ids)).order_by(getattr(cls,left), cls.association_order)
    for r in query.all():
        # dynamic association right column by table shape
        val = getattr(r, 'evidence_id', None) or getattr(r, 'warning_id', None) or getattr(r, 'asset_id', None)
        if val not in right_map: raise PersistedCandidateCorrupt(['dangling association'])
        ident = getattr(right_map[val], 'evidence_id', None) or getattr(right_map[val], 'warning_id', None) or getattr(right_map[val], 'asset_id', None)
        out.setdefault(getattr(r,left),[]).append(ident)
    return out
