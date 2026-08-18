import copy
from app.structured_content.enums import *
from app.structured_content.identity import *
from app.structured_content.model import *
from app.structured_document.assembler import assemble_structured_document
from app.structured_document.projection import *

def nid(v): return ContentNodeId(v)
def pid(v): return ContentPageId(v)
def aid(v): return AssetId(v)
def ev(v): return EvidenceReferenceId(v)
def node(v,p,o,t=ContentNodeType.PARAGRAPH,text='',attrs=None,parent=None,assets=(),evidence=()):
    return ContentNode(nid(v), ContentLineageKey('line-'+v), t, pid(p), o, NodeRecoveryState.COMPLETE, parent_id=nid(parent) if parent else None, text=text, attributes=attrs, asset_ids=tuple(assets), evidence_ids=tuple(evidence))
def candidate(nodes,pages,assets=(),evidence=(),warnings=()):
    return StructuredContentCandidate(SCHEMA_ID, SCHEMA_VERSION, DocumentRef('doc-proj'), ContentCandidateId('cand-proj'), ContentLineageKey('lineage-proj'), ContentRecoverySummary(ContentRecoveryState.DEGRADED if any(p.recovery_state is not PageRecoveryState.COMPLETE for p in pages) else ContentRecoveryState.COMPLETE,len(pages),complete_pages=sum(p.recovery_state is PageRecoveryState.COMPLETE for p in pages),degraded_pages=sum(p.recovery_state is PageRecoveryState.DEGRADED for p in pages),no_usable_semantic_content_pages=sum(p.recovery_state is PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT for p in pages),warning_ids=tuple(w.warning_id for w in warnings)), tuple(pages), tuple(nodes), tuple(evidence), tuple(assets), tuple(warnings), {})
def project(c): return project_structured_document(assemble_structured_document(c), candidate=c)

def test_exact_reader_v2_golden_heading_paragraph_image():
    asset=AssetReference(aid('img-1'), AssetRole.FIGURE, AssetRecoveryState.AVAILABLE)
    nodes=[node('title','p1',0,ContentNodeType.HEADING,'Book',HeadingAttributes(1)),node('h2','p1',1,ContentNodeType.HEADING,'Part',HeadingAttributes(2)),node('p','p1',2,text='Text'),node('fig','p1',3,ContentNodeType.FIGURE,attrs=FigureAttributes(rendered_asset_id=aid('img-1')),assets=(aid('img-1'),))]
    c=candidate(nodes,[ContentPage(pid('p1'),0,0,PageRecoveryState.COMPLETE,tuple(n.node_id for n in nodes))],assets=(asset,))
    p=project(c)
    assert p.payload == '# Book\n## Part\nText\n$%$%$%img-1$%$%$%'
    assert not p.payload.endswith('\n')
    assert [e.source_node_ref.value for e in p.entries] == ['title','h2','p','fig']

def test_mixed_document_losses_and_payload():
    asset=AssetReference(aid('fig-asset'), AssetRole.FIGURE, AssetRecoveryState.AVAILABLE)
    nodes=[node('hdr','p1',0,ContentNodeType.HEADER,'H'),node('title','p1',1,ContentNodeType.HEADING,'T',HeadingAttributes(1)),node('para','p1',2,text='P'),node('list','p1',3,ContentNodeType.LIST,''),node('li','p1',4,ContentNodeType.LIST_ITEM,'Item',parent='list'),node('ftr','p1',5,ContentNodeType.FOOTER,'F'),node('h','p2',0,ContentNodeType.HEADING,'H2',HeadingAttributes(3)),node('tbl','p2',1,ContentNodeType.TABLE,attrs=TableAttributes(TableStructure(1,1,(TableCell(0,0,text='A'),)))),node('cap','p2',2,ContentNodeType.CAPTION,'Table caption'),node('fig','p3',0,ContentNodeType.FIGURE,attrs=FigureAttributes(rendered_asset_id=aid('fig-asset')),assets=(aid('fig-asset'),)),node('fcap','p3',1,ContentNodeType.CAPTION,'Figure caption'),node('formula','p3',2,ContentNodeType.FORMULA,'x=1'),node('foot','p3',3,ContentNodeType.FOOTNOTE,'note'),node('unknown','p3',4,ContentNodeType.UNKNOWN,'?')]
    pages=[ContentPage(pid('p1'),0,0,PageRecoveryState.COMPLETE,tuple(n.node_id for n in nodes if n.page_id==pid('p1') and n.parent_id is None)),ContentPage(pid('p2'),1,1,PageRecoveryState.DEGRADED,tuple(n.node_id for n in nodes if n.page_id==pid('p2'))),ContentPage(pid('p3'),2,2,PageRecoveryState.COMPLETE,tuple(n.node_id for n in nodes if n.page_id==pid('p3')))]
    p=project(candidate(nodes,pages,assets=(asset,)))
    assert p.payload == '# T\nP\nItem\n### H2\nTable caption\n$%$%$%fig-asset$%$%$%\nFigure caption\nx=1\n?'
    assert [l.code for l in p.losses] == [ProjectionLossCode.HEADER_FOOTER_OMITTED,ProjectionLossCode.STRUCTURE_DROPPED,ProjectionLossCode.HEADER_FOOTER_OMITTED,ProjectionLossCode.RECOVERY_NOT_EXPRESSIBLE_IN_STREAM,ProjectionLossCode.ASSET_UNAVAILABLE,ProjectionLossCode.TABLE_STRUCTURE_DROPPED,ProjectionLossCode.HEADER_FOOTER_OMITTED]

def test_missing_and_transient_assets_do_not_leak():
    bad=AssetReference(aid('https://signed.example/x?X-Amz-Signature=y'), AssetRole.FIGURE, AssetRecoveryState.AVAILABLE)
    nodes=[node('fig','p1',0,ContentNodeType.FIGURE,attrs=FigureAttributes(rendered_asset_id=bad.asset_id),assets=(bad.asset_id,)),node('cap','p1',1,ContentNodeType.CAPTION,'cap')]
    c=candidate(nodes,[ContentPage(pid('p1'),0,0,PageRecoveryState.COMPLETE,tuple(n.node_id for n in nodes))],assets=(bad,))
    p=project(c)
    assert p.payload == 'cap'
    assert 'https://' not in p.payload and p.losses[0].code is ProjectionLossCode.ASSET_UNAVAILABLE

def test_determinism_input_immutability_and_scale():
    nodes=[]; pages=[]
    for pno in range(100):
        ids=[]
        for i in range(100):
            n=node(f'n{pno}-{i}',f'p{pno}',i,text=f'P{pno}-{i}'); nodes.append(n); ids.append(n.node_id)
        pages.append(ContentPage(pid(f'p{pno}'),pno,pno,PageRecoveryState.COMPLETE,tuple(ids)))
    c=candidate(nodes,pages); before=copy.deepcopy(c); d=assemble_structured_document(c); dbefore=copy.deepcopy(d)
    out=[project_structured_document(d,candidate=c) for _ in range(5)]
    assert all(o == out[0] for o in out)
    assert c == before and d == dbefore
    assert len(out[0].entries) == 10000 and out[0].payload.count('\n') == 9999
