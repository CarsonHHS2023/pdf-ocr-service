from dataclasses import FrozenInstanceError
import pytest
from app.structured_content.enums import ContentNodeType, ContentRecoveryState, NodeRecoveryState, PageRecoveryState
from app.structured_content.identity import *
from app.structured_content.model import SCHEMA_ID, SCHEMA_VERSION, ContentNode, ContentPage, ContentRecoverySummary, HeadingAttributes, StructuredContentCandidate
from app.structured_document.assembler import assemble_structured_document
from app.structured_document.projection import *
from app.structured_document.projection.errors import ProjectionSourceMismatch, UnsupportedProjectionType, UnsupportedProjectionVersion

def nid(v): return ContentNodeId(v)
def pid(v): return ContentPageId(v)
def node(v,p,o,t=ContentNodeType.PARAGRAPH,text=None,attrs=None,parent=None):
    return ContentNode(nid(v), ContentLineageKey('line-'+v), t, pid(p), o, NodeRecoveryState.COMPLETE, parent_id=nid(parent) if parent else None, text=text, attributes=attrs)
def cand(nodes, pages=None, doc='doc', cid='cand'):
    pages=pages or [ContentPage(pid('p1'),0,0,PageRecoveryState.COMPLETE, tuple(n.node_id for n in nodes if n.parent_id is None))]
    return StructuredContentCandidate(SCHEMA_ID, SCHEMA_VERSION, DocumentRef(doc), ContentCandidateId(cid), ContentLineageKey('lineage'), ContentRecoverySummary(ContentRecoveryState.COMPLETE,len(pages),complete_pages=len(pages)), tuple(pages), tuple(nodes), (), (), (), {})

def test_projection_contracts_are_immutable_and_versioned():
    c=cand([node('h','p1',0,ContentNodeType.HEADING,'Title',HeadingAttributes(1))]); d=assemble_structured_document(c); p=project_structured_document(d,candidate=c)
    assert p.projection_type is ProjectionType.READER_CONTENT_STREAM_V2
    assert p.projection_schema_version == SUPPORTED_PROJECTION_SCHEMA_VERSION
    assert p.projection_version == SUPPORTED_READER_CONTENT_STREAM_V2_PROJECTION_VERSION
    with pytest.raises(FrozenInstanceError): p.payload='x'
    with pytest.raises(FrozenInstanceError): p.projection_policy.include_headers_footers=True

def test_unsupported_projection_type_and_version_are_bounded():
    c=cand([node('p','p1',0,text='x')]); d=assemble_structured_document(c)
    with pytest.raises(UnsupportedProjectionType): validate_projection_input(d,c,'bad',1)
    with pytest.raises(UnsupportedProjectionVersion): validate_projection_input(d,c,ProjectionType.READER_CONTENT_STREAM_V2,99)

def test_source_candidate_and_document_mismatch_rejected():
    c=cand([node('p','p1',0,text='x')]); d=assemble_structured_document(c); other=cand([node('p','p1',0,text='x')], doc='other', cid='other')
    with pytest.raises(ProjectionSourceMismatch): project_structured_document(d,candidate=other)

def test_projection_has_no_random_or_reader_dependencies():
    c=cand([node('p','p1',0,text='x')]); d=assemble_structured_document(c)
    assert project_structured_document(d,candidate=c) == project_structured_document(d,candidate=c)
    import app.structured_document.projection.projector as projector
    names=set(projector.__dict__)
    assert 'Session' not in names and 'MineruResult' not in names
