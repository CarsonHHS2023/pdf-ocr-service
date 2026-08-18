"""M4 Slice 2A Structured Content ORM schema tests."""
from __future__ import annotations

import math

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    Base, Document, StructuredContentAsset, StructuredContentAssetEvidence, StructuredContentAssetRendition,
    StructuredContentCandidate, StructuredContentEvidence, StructuredContentNode, StructuredContentNodeAsset,
    StructuredContentNodeEvidence, StructuredContentNodeWarning, StructuredContentPage, StructuredContentPageEvidence,
    StructuredContentPageRoot, StructuredContentPageWarning, StructuredContentSelection, StructuredContentTableCell,
    StructuredContentWarning, StructuredContentWarningEvidence, decode_json_text, encode_json_text,
)


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


@pytest.fixture()
def db():
    session, engine = _session()
    try:
        yield session, engine
    finally:
        session.close(); engine.dispose()


def doc(session, id="doc-1"):
    d = Document(id=id, title=id, file_type="pdf")
    session.add(d); session.flush(); return d


def cand(session, id="cand-row", candidate_id="cand-1", document_id="doc-1", lineage="lineage"):
    c = StructuredContentCandidate(id=id, candidate_id=candidate_id, document_id=document_id, lineage_key=lineage, schema_id="atlas.structured-content-candidate", schema_version=1, recovery_state="complete", total_page_count=1, complete_page_count=1, degraded_page_count=0, no_usable_page_count=0, unavailable_page_count=0, unsupported_page_count=0)
    session.add(c); session.flush(); return c


def page(session, c, id="page-row", page_id="page-1", order=0):
    p = StructuredContentPage(id=id, candidate_id=c.id, page_id=page_id, page_order=order, source_page_index=0, recovery_state="complete")
    session.add(p); session.flush(); return p


def node(session, c, p, id="node-row", node_id="node-1", sibling=0, parent=None, attr=None):
    n = StructuredContentNode(id=id, candidate_id=c.id, page_id=p.id, node_id=node_id, lineage_key=f"{node_id}-lineage", node_type=attr or "paragraph", parent_node_id=parent.id if parent else None, sibling_order=sibling, recovery_state="complete", attribute_type=attr, attribute_json=encode_json_text({"kind": attr}) if attr else None)
    session.add(n); session.flush(); return n


def test_json_text_helper_is_deterministic_unicode_strict_and_decodes_errors():
    assert encode_json_text({"b": 1, "a": 2}) == encode_json_text({"a": 2, "b": 1}) == '{"a":2,"b":1}'
    assert decode_json_text(encode_json_text({"emoji": "📄"})) == {"emoji": "📄"}
    assert encode_json_text(None) is None and decode_json_text(None) is None
    with pytest.raises(ValueError): encode_json_text({"nan": math.nan})
    with pytest.raises(ValueError): encode_json_text({"inf": math.inf})
    with pytest.raises(Exception): decode_json_text("{")


def test_candidate_constraints_and_selection_absence(db):
    s, e = db; doc(s); c = cand(s); s.commit()
    assert s.query(StructuredContentSelection).count() == 0
    assert {col["name"] for col in inspect(e).get_columns("structured_content_candidates")}.isdisjoint({"current", "accepted", "selected", "updated_at"})
    cand(s, id="cand-row-2", candidate_id="cand-2", lineage="lineage"); s.commit()  # duplicate lineage allowed
    s.add(StructuredContentCandidate(id="bad", candidate_id="cand-3", document_id="doc-1", lineage_key="l", schema_id="s", schema_version=-1, recovery_state="complete", total_page_count=0, complete_page_count=0, degraded_page_count=0, no_usable_page_count=0, unavailable_page_count=0, unsupported_page_count=0))
    with pytest.raises(IntegrityError): s.commit()


def test_duplicate_candidate_and_missing_document_rejected(db):
    s, _ = db; doc(s); cand(s); s.commit()
    with pytest.raises(IntegrityError): cand(s, id="dupe", candidate_id="cand-1")
    s.rollback()
    with pytest.raises(IntegrityError): cand(s, id="orphan", candidate_id="orphan", document_id="missing")


def test_page_node_roots_and_cross_candidate_integrity(db):
    s, e = db; doc(s); c = cand(s); p = page(s, c); n1 = node(s, c, p); n2 = node(s, c, p, id="node-row-2", node_id="node-2", sibling=1, parent=n1)
    s.add_all([StructuredContentPageRoot(candidate_id=c.id, page_id=p.id, node_id=n1.id, root_order=0), StructuredContentPageRoot(candidate_id=c.id, page_id=p.id, node_id=n2.id, root_order=1)]); s.commit()
    assert [r.node_id for r in p.roots] == [n1.id, n2.id]
    assert n2.parent is n1 and n1.page is p
    assert "ix_sc_nodes_candidate_page_sibling" in {ix["name"] for ix in inspect(e).get_indexes("structured_content_nodes")}
    assert not any("cycle" in c["name"] for c in inspect(e).get_check_constraints("structured_content_nodes"))
    with pytest.raises(IntegrityError): page(s, c, id="p2", page_id="page-2", order=0)
    s.rollback()
    with pytest.raises(IntegrityError):
        page(s, c, id="pneg", page_id="neg", order=-1)


def test_same_page_and_node_identity_allowed_in_another_candidate(db):
    s, _ = db; doc(s); c1 = cand(s, id="c1", candidate_id="candidate-1"); c2 = cand(s, id="c2", candidate_id="candidate-2")
    p1 = page(s, c1, id="p1", page_id="same"); p2 = page(s, c2, id="p2", page_id="same")
    node(s, c1, p1, id="n1", node_id="same"); node(s, c2, p2, id="n2", node_id="same"); s.commit()


def test_evidence_warnings_assets_renditions_associations_and_no_payload_columns(db):
    s, e = db; doc(s); c = cand(s); p = page(s, c); n = node(s, c, p)
    ev = StructuredContentEvidence(id="ev", candidate_id=c.id, evidence_id="ev-1", kind="source_location")
    w = StructuredContentWarning(id="warn", candidate_id=c.id, warning_id="w-1", code="code", severity="warning", scope_path="/", safe_summary="safe")
    a = StructuredContentAsset(id="asset", candidate_id=c.id, asset_id="a-1", role="figure", recovery_state="available", storage_ref="opaque")
    s.add_all([ev, w, a]); s.flush()
    r = StructuredContentAssetRendition(id="rend", asset_id=a.id, rendition_id="r-1", rendition_order=0, storage_ref="opaque-r", rebuildable=False)
    s.add_all([r, StructuredContentPageEvidence(page_id=p.id, evidence_id=ev.id), StructuredContentPageWarning(page_id=p.id, warning_id=w.id), StructuredContentNodeEvidence(node_id=n.id, evidence_id=ev.id), StructuredContentNodeAsset(node_id=n.id, asset_id=a.id), StructuredContentNodeWarning(node_id=n.id, warning_id=w.id), StructuredContentAssetEvidence(asset_id=a.id, evidence_id=ev.id), StructuredContentWarningEvidence(warning_id=w.id, evidence_id=ev.id)]); s.commit()
    assert {col["name"] for table in ["structured_content_evidence", "structured_content_warnings", "structured_content_assets"] for col in inspect(e).get_columns(table)}.isdisjoint({"provider_payload", "payload", "asset_bytes", "image_data"})
    with pytest.raises(IntegrityError):
        s.add(StructuredContentAssetRendition(asset_id=a.id, rendition_id="r-2", rendition_order=0, rebuildable=False)); s.commit()
    s.rollback()
    with pytest.raises(IntegrityError):
        s.add(StructuredContentNodeAsset(node_id=n.id, asset_id=a.id)); s.commit()


def test_typed_attributes_and_table_cells(db):
    s, _ = db; doc(s); c = cand(s); p = page(s, c)
    for i, attr in enumerate(["heading", "list", "list_item", "table", "figure", "caption", "formula"]):
        node(s, c, p, id=f"node-{attr}", node_id=f"node-{attr}", sibling=i, attr=attr)
    table = s.query(StructuredContentNode).filter_by(attribute_type="table").one()
    s.add_all([StructuredContentTableCell(table_node_id=table.id, row_index=0, column_index=1, text="b"), StructuredContentTableCell(table_node_id=table.id, row_index=0, column_index=0, text="a")]); s.commit()
    assert [cell.text for cell in table.table_cells] == ["a", "b"]
    with pytest.raises(IntegrityError):
        s.add(StructuredContentTableCell(table_node_id=table.id, row_index=-1, column_index=0)); s.commit()
    s.rollback()
    with pytest.raises(IntegrityError):
        s.add(StructuredContentTableCell(table_node_id=table.id, row_index=1, column_index=0, row_span=0)); s.commit()


def test_selection_zero_one_version_and_document_ownership(db):
    s, _ = db; doc(s, "doc-1"); doc(s, "doc-2"); c1 = cand(s, document_id="doc-1"); c2 = cand(s, id="c2", candidate_id="cand-2", document_id="doc-2")
    s.commit(); assert s.query(StructuredContentSelection).count() == 0
    s.add(StructuredContentSelection(document_id="doc-1", candidate_id=c1.id, selection_version=0)); s.commit()
    with pytest.raises(IntegrityError):
        s.add(StructuredContentSelection(document_id="doc-1", candidate_id=c1.id, selection_version=1)); s.commit()
    s.rollback()
    with pytest.raises(IntegrityError):
        s.add(StructuredContentSelection(document_id="doc-2", candidate_id=c1.id, selection_version=0)); s.commit()
    s.rollback()
    with pytest.raises(IntegrityError):
        s.add(StructuredContentSelection(document_id="doc-2", candidate_id=c2.id, selection_version=-1)); s.commit()
