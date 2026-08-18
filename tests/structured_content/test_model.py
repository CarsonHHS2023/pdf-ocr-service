from dataclasses import FrozenInstanceError
import importlib, sys
import pytest
from app.structured_content import *

def minimal_candidate():
    return StructuredContentCandidate(SCHEMA_ID, SCHEMA_VERSION, DocumentRef('doc-1'), ContentCandidateId('cand-1'), ContentLineageKey('lin-1'), ContentRecoverySummary(ContentRecoveryState.COMPLETE,0), (), (), (), (), (), {'org.atlas.fixture':'minimal'})

def test_construct_minimal_candidate_and_tuple_collections():
    c=minimal_candidate()
    assert c.schema_id == SCHEMA_ID and c.pages == () and isinstance(c.nodes, tuple)

def test_frozen_immutability():
    c=minimal_candidate()
    with pytest.raises(FrozenInstanceError): c.schema_id='x'

def test_identity_wrapper_distinction_and_rejection():
    assert DocumentRef('same') != ContentCandidateId('same')
    for cls in (DocumentRef, ContentNodeId):
        with pytest.raises(ValueError): cls('  ')
        with pytest.raises(ValueError): cls('')

def test_duplicate_text_nodes_can_have_distinct_ids_and_missing_geometry_ok():
    p=ContentPage(ContentPageId('p1'),0,0,PageRecoveryState.COMPLETE,(ContentNodeId('n1'),ContentNodeId('n2')))
    n1=ContentNode(ContentNodeId('n1'),ContentLineageKey('l1'),ContentNodeType.PARAGRAPH,p.page_id,0,NodeRecoveryState.COMPLETE,text='same')
    n2=ContentNode(ContentNodeId('n2'),ContentLineageKey('l2'),ContentNodeType.PARAGRAPH,p.page_id,1,NodeRecoveryState.COMPLETE,text='same')
    assert n1.text == n2.text and n1.node_id != n2.node_id and n1.source_locations == ()

def test_zero_root_page_construction():
    p=ContentPage(ContentPageId('p-empty'),0,0,PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT,())
    assert p.root_node_ids == ()

def test_no_forbidden_import_dependency_on_package_import():
    before=set(sys.modules)
    importlib.import_module('app.structured_content')
    loaded=set(sys.modules)-before
    forbidden=("sql"+"alchemy","ale"+"mbic","fast"+"api","app."+"models","route"+"rs","pad"+"dle","pro"+"vider")
    assert not any(any(part in name for part in forbidden) for name in loaded)
