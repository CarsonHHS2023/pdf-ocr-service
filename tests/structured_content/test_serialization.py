import json, math
from pathlib import Path
import pytest
from app.structured_content import *

BASE=Path('tests/fixtures/structured_content/v1')

def candidate_one():
    page_id=ContentPageId('page-b')
    e2=EvidenceReference(EvidenceReferenceId('evidence-b'), EvidenceKind.SOURCE_LOCATION, source_file_ref=SourceFileRef('source-file'), source_page_index=0, source_location=SourceLocation(0, NormalizedBoundingBox(.1,.1,.9,.2)))
    e1=EvidenceReference(EvidenceReferenceId('evidence-a'), EvidenceKind.SOURCE_LOCATION, source_file_ref=SourceFileRef('source-file'), source_page_index=0)
    h=ContentNode(ContentNodeId('node-b'),ContentLineageKey('line-heading'),ContentNodeType.HEADING,page_id,0,NodeRecoveryState.COMPLETE,text='Cafe\u0301',attributes=HeadingAttributes(1),evidence_ids=(e2.evidence_id,))
    p=ContentNode(ContentNodeId('node-a'),ContentLineageKey('line-paragraph'),ContentNodeType.PARAGRAPH,page_id,1,NodeRecoveryState.COMPLETE,text='Paragraph',evidence_ids=(e1.evidence_id,))
    page=ContentPage(page_id,0,0,PageRecoveryState.COMPLETE,(h.node_id,p.node_id),page_label='1',evidence_ids=(e2.evidence_id,e1.evidence_id),extensions={'org.z':'z','org.a':'a'})
    return StructuredContentCandidate(SCHEMA_ID,1,DocumentRef('doc'),ContentCandidateId('cand'),ContentLineageKey('line-cand'),ContentRecoverySummary(ContentRecoveryState.COMPLETE,1,complete_pages=1), (page,), (h,p), (e2,e1), (), (), {'org.z':'z','org.a':'a'})

def test_repeated_serialization_trailing_newline_utf8_nfc_and_optional_omission():
    b1=serialize_structured_content_candidate(candidate_one()); b2=serialize_structured_content_candidate(candidate_one())
    assert b1 == b2 and b1.endswith(b'\n') and 'Café'.encode() in b1
    data=json.loads(b1)
    assert data['nodes'][1]['text']=='Café' and 'transformer_ref' not in data and 'parent_id' not in data['nodes'][0]

def test_sorted_registries_and_semantic_page_root_order_preserved_and_enums_identity():
    data=to_canonical_dict(candidate_one())
    assert [n['node_id'] for n in data['nodes']] == ['node-a','node-b']
    assert [e['evidence_id'] for e in data['evidence']] == ['evidence-a','evidence-b']
    assert data['pages'][0]['root_node_ids'] == ['node-b','node-a']
    assert data['pages'][0]['recovery_state'] == 'complete' and data['candidate_id'] == 'cand'

def test_extension_key_ordering_and_nonfinite_rejected():
    text=serialize_structured_content_candidate(candidate_one()).decode()
    assert text.index('org.a') < text.index('org.z')
    with pytest.raises(ValueError):
        StructuredContentCandidate(SCHEMA_ID,1,DocumentRef('doc'),ContentCandidateId('cand'),ContentLineageKey('line'),ContentRecoverySummary(ContentRecoveryState.COMPLETE,0),(),(),(),(),(), {'org.atlas.nan': math.nan})
    with pytest.raises(ValueError):
        StructuredContentCandidate(SCHEMA_ID,1,DocumentRef('doc'),ContentCandidateId('cand'),ContentLineageKey('line'),ContentRecoverySummary(ContentRecoveryState.COMPLETE,0),(),(),(),(),(), {'identity':'bad'})

def from_dict(d):
    ev=tuple(EvidenceReference(EvidenceReferenceId(e['evidence_id']), EvidenceKind(e['kind']), source_file_ref=SourceFileRef(e['source_file_ref']) if 'source_file_ref' in e else None, source_page_index=e.get('source_page_index'), source_location=SourceLocation(e['source_location']['source_page_index'], NormalizedBoundingBox(**e['source_location']['bounding_box'])) if 'source_location' in e else None, raw_result_ref=RawResultRef(e['raw_result_ref']) if 'raw_result_ref' in e else None, structured_processing_result_ref=StructuredProcessingResultRef(e['structured_processing_result_ref']) if 'structured_processing_result_ref' in e else None) for e in d['evidence'])
    pages=tuple(ContentPage(ContentPageId(p['page_id']),p['source_page_index'],p['page_order'],PageRecoveryState(p['recovery_state']),tuple(ContentNodeId(x) for x in p['root_node_ids']),page_label=p.get('page_label'),evidence_ids=tuple(EvidenceReferenceId(x) for x in p.get('evidence_ids',())),extensions=p.get('extensions',{})) for p in d['pages'])
    nodes=[]
    for n in d['nodes']:
        attrs=HeadingAttributes(**n['attributes']) if n.get('node_type')=='heading' and 'attributes' in n else None
        nodes.append(ContentNode(ContentNodeId(n['node_id']),ContentLineageKey(n['lineage_key']),ContentNodeType(n['node_type']),ContentPageId(n['page_id']),n['sibling_order'],NodeRecoveryState(n['recovery_state']),text=n.get('text'),attributes=attrs,source_locations=tuple(SourceLocation(x['source_page_index'], NormalizedBoundingBox(**x['bounding_box']) if 'bounding_box' in x else None) for x in n.get('source_locations',())),evidence_ids=tuple(EvidenceReferenceId(x) for x in n.get('evidence_ids',()))))
    rs=d['recovery_summary']
    return StructuredContentCandidate(d['schema_id'],d['schema_version'],DocumentRef(d['document_ref']),ContentCandidateId(d['candidate_id']),ContentLineageKey(d['lineage_key']),ContentRecoverySummary(ContentRecoveryState(rs['state']),rs['total_pages'],rs.get('complete_pages',0),rs.get('partial_pages',0),rs.get('degraded_pages',0),rs.get('unavailable_pages',0),rs.get('no_usable_semantic_content_pages',0)),pages,tuple(nodes),ev,(),(),d.get('extensions',{}), raw_result_ref=RawResultRef(d['raw_result_ref']) if 'raw_result_ref' in d else None, structured_processing_result_ref=StructuredProcessingResultRef(d['structured_processing_result_ref']) if 'structured_processing_result_ref' in d else None)

@pytest.mark.parametrize('rel', ['valid/minimal_empty_candidate/candidate.json','valid/one_page_heading_paragraph/candidate.json'])
def test_fixtures_match_canonical_serialization(rel):
    path=BASE/rel
    data=json.loads(path.read_text())
    assert serialize_structured_content_candidate(from_dict(data)) == path.read_bytes()

def test_manifest_lists_valid_fixtures_without_transformer_dependency():
    m=json.loads((BASE/'manifest.json').read_text())
    valid_cases = [
        case for case in m['cases']
        if case['expected_validity'] == 'valid'
    ]
    assert [case['name'] for case in valid_cases[:2]] == [
        'minimal_empty_candidate',
        'one_page_heading_paragraph',
    ]
    assert [case['candidate_path'] for case in valid_cases[:2]] == [
        'valid/minimal_empty_candidate/candidate.json',
        'valid/one_page_heading_paragraph/candidate.json',
    ]
    assert [case['canonical_path'] for case in valid_cases[:2]] == [
        'valid/minimal_empty_candidate/canonical.json',
        'valid/one_page_heading_paragraph/canonical.json',
    ]
    assert all(case['purpose'] for case in valid_cases)
    assert len(valid_cases) >= 2
    assert all(case['transformer_input_dependency'] is None for case in m['cases'])
