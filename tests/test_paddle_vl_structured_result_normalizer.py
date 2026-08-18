from __future__ import annotations
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
import pytest
from app.processing.raw_result import *
from app.processing.paddle_vl.normalizer import normalize_paddle_vl_raw_result
from app.processing.structured_result import PAGE_HAS_NO_USABLE_SEMANTIC_CONTENT, PARTIAL_DOCUMENT_RECOVERY, StructuredPageStatus, StructuredProcessingResult, serialize_structured_processing_result
from app.processing.structured_result.validation import StructuredResultValidationError
from app.storage.models import StorageReference

BASE=Path('tests/fixtures/processing/structured_processing_result_v1')
def fixture(name): return json.loads((BASE/'raw_results'/f'{name}.json').read_text())
def envelope(value):
 r=value['raw_result']; i=r['identity']; g=r['ingestion']; s=r['source']; p=r.get('provider',{})
 return RawProcessingResultEnvelope(RawResultIdentity(**i),RawResultSourceProvenance(**s),RawResultProviderProvenance(**p),RawResultIngestionMetadata(datetime.fromisoformat(g['ingested_at'].replace('Z','+00:00')),g['payload_media_type'],g.get('payload_encoding'),g.get('payload_compression'),g['payload_size_bytes'],g['payload_sha256'],StorageReference(g['storage_reference']),RawResultEvidenceSource(g['evidence_source']),page_summary=RawResultPageSummary(**g['page_summary'])))
def payload(value): return json.dumps(value['retained_payload'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def ids(kind,*parts): return '_'.join([{'result':'spr','processing_run':'run','raw_result':'raw','page':'page','observation':'obs','node':'node','node_item':'node_item','evidence':'evidence','warning':'warning'}[kind],*map(str,parts)])
def clock(): return datetime(2026,7,17,tzinfo=timezone.utc)
@pytest.mark.parametrize('name', ['complete_single_page_text','complete_multipage_mixed','no_confidence','no_geometry','unknown_block_type','rotated_page','partial_failed_page'])
def test_supported_fixtures_map_offline(name):
 v=fixture(name); out=normalize_paddle_vl_raw_result(envelope(v),payload(v),id_factory=ids,clock=clock)
 assert out.result is not None, out.diagnostics
 result=out.result.to_dict(); assert result['state']==('partial' if name=='partial_failed_page' else 'complete')
 assert serialize_structured_processing_result(out.result).endswith(b'\n')
 assert len(result['pages']) and all(x['target_id'] in {o['observation_id'] for o in result['normalized_observations']} for x in result['evidence_links'])

def test_structured_page_status_is_explicit_and_defaults_to_usable():
 v=fixture('complete_single_page_text'); out=normalize_paddle_vl_raw_result(envelope(v),payload(v),id_factory=ids,clock=clock)
 assert out.result is not None, out.diagnostics
 page=out.result.to_dict()['pages'][0]
 assert page['status'] is StructuredPageStatus.USABLE
 assert page['page_id']=='page_0' and page['root_node_ids']==['node_0_0','node_0_1']
 assert all(item['status'] is StructuredPageStatus.USABLE for item in out.result.to_dict()['pages'])
 serialized=serialize_structured_processing_result(out.result)
 assert b'"status":"usable"' in serialized
 assert b'StructuredPageStatus.USABLE' not in serialized
 assert out.result.to_dict()['state']=='complete'
 assert out.result.to_dict()['diagnostics']==[]
 result=out.result.to_dict(); invalid={**result,"pages":[{**page,"status":"unknown"},*result['pages'][1:]]}
 with pytest.raises(StructuredResultValidationError): StructuredProcessingResult(invalid)

def test_mixed_page_statuses_emit_partial_document_recovery_diagnostic():
 pages=[
  {"local_page_index":0,"page_index":0,"source_page_range":{"page_start":1,"page_end":3},"width":100,"height":100,"blocks":[{"id":"first","type":"text","text":"first semantic page","bbox":[1,1,20,20]}]},
  {"local_page_index":1,"page_index":1,"source_page_range":{"page_start":1,"page_end":3},"width":100,"height":100,"blocks":[{"id":"missing","type":"text","text":None},{"id":"blank","type":"paragraph","text":"   "}]},
  {"local_page_index":2,"page_index":2,"source_page_range":{"page_start":1,"page_end":3},"width":100,"height":100,"blocks":[{"id":"last","type":"text","text":"last semantic page","bbox":[2,2,30,30]}]},
 ]
 retained={"profile":"full","status":"completed","documents":[{"status":"completed","pages":pages}]}; data=json.dumps(retained,sort_keys=True,separators=(',',':')).encode()
 raw=RawProcessingResultEnvelope(RawResultIdentity("attempt",None,"doc","file","paddle-vl-api","job",provider_result_profile="full",provider_result_status="completed"),RawResultSourceProvenance("a"*64),RawResultProviderProvenance(pipeline_version="v1.6"),RawResultIngestionMetadata(clock(),"application/json","utf-8",None,len(data),hashlib.sha256(data).hexdigest(),StorageReference("src_00000000000000000000000000000001"),RawResultEvidenceSource.INLINE_JSON,page_summary=RawResultPageSummary(3)))
 warning_ordinal=[0]
 def mixed_ids(kind,*parts):
  if kind=="warning":
   warning_ordinal[0]+=1; return f"warning_{warning_ordinal[0]}"
  return ids(kind,*parts)
 out=normalize_paddle_vl_raw_result(raw,data,id_factory=mixed_ids,clock=clock); assert out.result is not None,out.diagnostics
 result=out.result.to_dict(); mapped_pages=result['pages']; assert result['state']=='partial' and [page['page_index'] for page in mapped_pages]==[0,1,2] and [page['page_id'] for page in mapped_pages]==['page_0','page_1','page_2']
 assert [page['status'] for page in mapped_pages]==[StructuredPageStatus.USABLE,StructuredPageStatus.NO_USABLE_SEMANTIC_CONTENT,StructuredPageStatus.USABLE]
 assert mapped_pages[1]['diagnostics']==[PAGE_HAS_NO_USABLE_SEMANTIC_CONTENT] and mapped_pages[0]['diagnostics']==[] and mapped_pages[2]['diagnostics']==[]
 assert result['diagnostics']==[PARTIAL_DOCUMENT_RECOVERY]
 assert mapped_pages[1]['root_node_ids']==[] and all(item['page_id']!='page_1' for item in result['normalized_observations']) and all('page_1' not in item['page_ids'] for item in result['nodes']) and all(item['spr_page_id']!='page_1' for item in result['evidence_links'])
 assert [node['node_id'] for node in result['nodes']]==['node_0_0','node_2_0'] and [item['source_page_index'] for item in result['evidence_links']]==[0,2]
 assert not any(warning['code']=='PAGE_HAS_NO_USABLE_SEMANTIC_CONTENT' for warning in result['warnings']) and not {'page_degraded_count','page_semantic_loss_count','empty_page_count'} & result['quality_summary'].keys()
 serialized=json.loads(serialize_structured_processing_result(out.result)); assert [page['status'] for page in serialized['pages']]==['usable','no_usable_semantic_content','usable'] and serialized['pages'][1]['diagnostics']==[PAGE_HAS_NO_USABLE_SEMANTIC_CONTENT] and serialized['pages'][1]['root_node_ids']==[] and serialized['diagnostics']==[PARTIAL_DOCUMENT_RECOVERY]
 assert serialize_structured_processing_result(out.result)==serialize_structured_processing_result(out.result)
@pytest.mark.parametrize('name,code',[('duplicate_page_mapping','INVALID_PAGE_MAPPING'),('missing_page','INVALID_PAGE_MAPPING'),('unsafe_metadata','UNSAFE_METADATA')])
def test_rejection_fixtures_produce_diagnostics(name,code):
 v=fixture(name); out=normalize_paddle_vl_raw_result(envelope(v),payload(v),id_factory=ids,clock=clock)
 assert out.result is None and out.diagnostics[0].code==code
def test_checksum_size_malformed_and_revision_rejected():
 v=fixture('complete_single_page_text'); e=envelope(v); data=payload(v)
 assert normalize_paddle_vl_raw_result(e,data+b' ',id_factory=ids,clock=clock).diagnostics[0].code=='PAYLOAD_SIZE_MISMATCH'
 assert normalize_paddle_vl_raw_result(e,b'{' + b' '* (len(data)-1),id_factory=ids,clock=clock).result is None
 bad=RawProcessingResultEnvelope(e.identity,e.source,RawResultProviderProvenance(pipeline_version='future'),e.ingestion)
 assert normalize_paddle_vl_raw_result(bad,data,id_factory=ids,clock=clock).diagnostics[0].code=='UNSUPPORTED_REVISION'
def test_nonfinite_and_geometry_failures_are_safe():
 v=fixture('complete_single_page_text'); v['retained_payload']['documents'][0]['pages'][0]['blocks'][0]['bbox']=[0,0,9999,2]; data=payload(v); e=envelope(v)
 # adjust exact retained metadata so the geometry validation layer is reached
 e=RawProcessingResultEnvelope(e.identity,e.source,e.provider,RawResultIngestionMetadata(e.ingestion.ingested_at,e.ingestion.payload_media_type,e.ingestion.payload_encoding,e.ingestion.payload_compression,len(data),hashlib.sha256(data).hexdigest(),e.ingestion.storage_reference,e.ingestion.evidence_source,page_summary=e.ingestion.page_summary))
 assert normalize_paddle_vl_raw_result(e,data,id_factory=ids,clock=clock).diagnostics[0].code=='INVALID_GEOMETRY'

def test_nonzero_subset_missing_source_page_index_is_rejected():
    retained = {"profile":"full","status":"completed","documents":[{"status":"completed","pages":[{"local_page_index":0,"page_index":0,"page_number":51,"source_page_range":{"page_start":51,"page_end":51},"width":100,"height":100,"blocks":[{"id":"subset","type":"text","text":"sensitive subset text","bbox":[1,1,2,2]}]}]}]}
    data = json.dumps(retained, sort_keys=True, separators=(",", ":")).encode()
    raw = RawProcessingResultEnvelope(
        RawResultIdentity("attempt", None, "doc", "file", "paddle-vl-api", "job", provider_result_profile="full", provider_result_status="completed"),
        RawResultSourceProvenance("a" * 64), RawResultProviderProvenance(pipeline_version="v1.6"),
        RawResultIngestionMetadata(clock(), "application/json", "utf-8", None, len(data), hashlib.sha256(data).hexdigest(), StorageReference("src_00000000000000000000000000000001"), RawResultEvidenceSource.INLINE_JSON, page_summary=RawResultPageSummary(1, first_source_page=51, last_source_page=51, source_ranges_represented=((51, 51),))),
    )
    outcome = normalize_paddle_vl_raw_result(raw, data, id_factory=ids, clock=clock)
    assert outcome.result is None
    assert outcome.diagnostics[0].code == "INVALID_PAGE_MAPPING"
    assert "sensitive subset text" not in outcome.diagnostics[0].message

def test_nonzero_single_page_subset_mapping():
    retained={"profile":"full","status":"completed","documents":[{"status":"completed","pages":[{"local_page_index":0,"page_index":0,"source_page_index":50,"page_number":51,"source_page_range":{"page_start":51,"page_end":51},"width":100,"height":100,"blocks":[{"id":"explicit","type":"text","text":"explicit source subset text","bbox":[1,1,2,2]}]}]}]}
    data=json.dumps(retained,sort_keys=True,separators=(',',':')).encode()
    raw=RawProcessingResultEnvelope(RawResultIdentity("attempt",None,"doc","file","paddle-vl-api","job",provider_result_profile="full",provider_result_status="completed"),RawResultSourceProvenance("a"*64),RawResultProviderProvenance(pipeline_version="v1.6"),RawResultIngestionMetadata(clock(),"application/json","utf-8",None,len(data),hashlib.sha256(data).hexdigest(),StorageReference("src_00000000000000000000000000000001"),RawResultEvidenceSource.INLINE_JSON,page_summary=RawResultPageSummary(1,first_source_page=51,last_source_page=51,source_ranges_represented=((51,51),))))
    outcome=normalize_paddle_vl_raw_result(raw,data,id_factory=ids,clock=clock)
    assert outcome.result is not None, outcome.diagnostics
    result=outcome.result.to_dict(); assert result['state']=='complete' and len(result['pages'])==1
    page=result['pages'][0]; assert page['page_index']==0 and page['page_number']==51 and page['page_id']=='page_0'; assert page['page_index'] not in {50,51}
    mapping=result['extensions']['org.atlas.page-source-mapping']; assert mapping==[{"page_id":"page_0","provider_local_page_index":0,"source_page_index":50,"display_page_number":51,"source_page_range":[50,50]}]
    page_ids={page['page_id']}; nodes={n['node_id']:n for n in result['nodes']}; obs=result['normalized_observations']; evidence=result['evidence_links']
    assert all(o['page_id'] in page_ids for o in obs); assert all(n['page_ids']==['page_0'] for n in nodes.values()); assert all(root in nodes and nodes[root]['page_ids']==['page_0'] for root in page['root_node_ids']); assert all(e['spr_page_id']=='page_0' and e['source_page_index']==50 for e in evidence)

def test_nonzero_multipage_subset_mapping():
    pages=[{"local_page_index":n,"page_index":n,"source_page_index":50+n,"page_number":51+n,"source_page_range":{"page_start":51,"page_end":53},"width":100,"height":100,"blocks":[{"id":f"b{n}","type":"text","text":f"explicit subset page {51+n}","bbox":[1,1,2,2]}]} for n in range(3)]
    retained={"profile":"full","status":"completed","documents":[{"status":"completed","pages":pages}]}; data=json.dumps(retained,sort_keys=True,separators=(',',':')).encode()
    raw=RawProcessingResultEnvelope(RawResultIdentity("attempt",None,"doc","file","paddle-vl-api","job",provider_result_profile="full",provider_result_status="completed"),RawResultSourceProvenance("a"*64),RawResultProviderProvenance(pipeline_version="v1.6"),RawResultIngestionMetadata(clock(),"application/json","utf-8",None,len(data),hashlib.sha256(data).hexdigest(),StorageReference("src_00000000000000000000000000000001"),RawResultEvidenceSource.INLINE_JSON,page_summary=RawResultPageSummary(3,first_source_page=51,last_source_page=53,source_ranges_represented=((51,53),))))
    out=normalize_paddle_vl_raw_result(raw,data,id_factory=ids,clock=clock); assert out.result is not None,out.diagnostics
    r=out.result.to_dict(); assert r['state']=='complete'; assert [p['page_index'] for p in r['pages']]==[0,1,2]; assert [p['page_number'] for p in r['pages']]==[51,52,53]
    pids=[p['page_id'] for p in r['pages']]; assert pids==['page_0','page_1','page_2']
    mappings=r['extensions']['org.atlas.page-source-mapping']; assert [(x['provider_local_page_index'],x['source_page_index'],x['display_page_number'],x['source_page_range'],x['page_id']) for x in mappings]==[(0,50,51,[50,52],'page_0'),(1,51,52,[50,52],'page_1'),(2,52,53,[50,52],'page_2')]
    for n in range(3):
        oid=f'observation_{n}_0'; nid=f'node_{n}_0'; eid=f'evidence_{n}_0'; assert r['normalized_observations'][n]['page_id']==pids[n]; assert r['nodes'][n]['page_ids']==[pids[n]]; assert r['pages'][n]['root_node_ids']==[nid]; assert r['evidence_links'][n]['spr_page_id']==pids[n] and r['evidence_links'][n]['source_page_index']==50+n

def test_duplicate_explicit_source_page_identity_is_rejected():
    pages=[{"local_page_index":n,"page_index":n,"source_page_index":50,"page_number":51,"source_page_range":{"page_start":51,"page_end":51},"width":100,"height":100,"blocks":[{"id":f"dup{n}","type":"text","text":f"duplicate source {'first' if n==0 else 'second'} block","bbox":[1,1,2,2]}]} for n in range(2)]
    retained={"profile":"full","status":"completed","documents":[{"status":"completed","pages":pages}]}; data=json.dumps(retained,sort_keys=True,separators=(',',':')).encode()
    raw=RawProcessingResultEnvelope(RawResultIdentity("attempt",None,"doc","file","paddle-vl-api","job",provider_result_profile="full",provider_result_status="completed"),RawResultSourceProvenance("a"*64),RawResultProviderProvenance(pipeline_version="v1.6"),RawResultIngestionMetadata(clock(),"application/json","utf-8",None,len(data),hashlib.sha256(data).hexdigest(),StorageReference("src_00000000000000000000000000000001"),RawResultEvidenceSource.INLINE_JSON,page_summary=RawResultPageSummary(2,first_source_page=51,last_source_page=51,source_ranges_represented=((51,51),))))
    out=normalize_paddle_vl_raw_result(raw,data,id_factory=ids,clock=clock)
    assert out.result is None and out.diagnostics[0].code=='INVALID_PAGE_MAPPING'
    message=' '.join(x.message for x in out.diagnostics); assert 'duplicate source first block' not in message and 'duplicate source second block' not in message and '/workspace' not in message

def test_explicit_nonzero_source_mapping_without_page_number():
    page={"local_page_index":0,"page_index":0,"source_page_index":50,"source_page_range":{"page_start":51,"page_end":51},"width":100,"height":100,"blocks":[{"id":"nodisplay","type":"text","text":"source range without display page","bbox":[1,1,2,2]}]}; retained={"profile":"full","status":"completed","documents":[{"status":"completed","pages":[page]}]}; data=json.dumps(retained,sort_keys=True,separators=(',',':')).encode()
    raw=RawProcessingResultEnvelope(RawResultIdentity("attempt",None,"doc","file","paddle-vl-api","job",provider_result_profile="full",provider_result_status="completed"),RawResultSourceProvenance("a"*64),RawResultProviderProvenance(pipeline_version="v1.6"),RawResultIngestionMetadata(clock(),"application/json","utf-8",None,len(data),hashlib.sha256(data).hexdigest(),StorageReference("src_00000000000000000000000000000001"),RawResultEvidenceSource.INLINE_JSON,page_summary=RawResultPageSummary(1)))
    out=normalize_paddle_vl_raw_result(raw,data,id_factory=ids,clock=clock); assert out.result is not None,out.diagnostics
    r=out.result.to_dict(); p=r['pages'][0]; assert r['state']=='complete' and p['page_index']==0 and p['page_number'] is None and p['page_index']!=50
    assert r['extensions']['org.atlas.page-source-mapping']==[{"page_id":"page_0","provider_local_page_index":0,"source_page_index":50,"display_page_number":None,"source_page_range":[50,50]}]
    assert all(o['page_id']=='page_0' for o in r['normalized_observations']) and all(n['page_ids']==['page_0'] for n in r['nodes']) and all(e['spr_page_id']=='page_0' and e['source_page_index']==50 for e in r['evidence_links'])

def test_completed_summary_count_greater_than_mapped_pages_is_rejected():
    pages=[{"local_page_index":n,"page_index":n,"source_page_index":50+n,"page_number":51+n,"source_page_range":{"page_start":51,"page_end":52},"width":100,"height":100,"blocks":[{"id":f"sum{n}","type":"text","text":f"summary mismatch {'first' if n==0 else 'second'} page","bbox":[1,1,2,2]}]} for n in range(2)]; retained={"profile":"full","status":"completed","documents":[{"status":"completed","pages":pages}]}; data=json.dumps(retained,sort_keys=True,separators=(',',':')).encode()
    raw=RawProcessingResultEnvelope(RawResultIdentity("attempt",None,"doc","file","paddle-vl-api","job",provider_result_profile="full",provider_result_status="completed"),RawResultSourceProvenance("a"*64),RawResultProviderProvenance(pipeline_version="v1.6"),RawResultIngestionMetadata(clock(),"application/json","utf-8",None,len(data),hashlib.sha256(data).hexdigest(),StorageReference("src_00000000000000000000000000000001"),RawResultEvidenceSource.INLINE_JSON,page_summary=RawResultPageSummary(3)))
    out=normalize_paddle_vl_raw_result(raw,data,id_factory=ids,clock=clock); assert out.result is None and out.diagnostics[0].code=='INVALID_PAGE_MAPPING'; assert 'summary mismatch first page' not in out.diagnostics[0].message and 'summary mismatch second page' not in out.diagnostics[0].message

def test_valid_text_with_invalid_figure_geometry_is_retained_as_partial_without_geometry():
    blocks=[{"id":"text","type":"text","text":"retained valid text marker","bbox":[1,1,20,20]},{"id":"figure","type":"image","bbox":[1,2,3]}]; retained={"profile":"full","status":"completed","documents":[{"status":"completed","pages":[{"local_page_index":0,"page_index":0,"source_page_range":{"page_start":1,"page_end":1},"width":100,"height":100,"blocks":blocks}]}]}; data=json.dumps(retained,sort_keys=True,separators=(',',':')).encode()
    raw=RawProcessingResultEnvelope(RawResultIdentity("attempt",None,"doc","file","paddle-vl-api","job",provider_result_profile="full",provider_result_status="completed"),RawResultSourceProvenance("a"*64),RawResultProviderProvenance(pipeline_version="v1.6"),RawResultIngestionMetadata(clock(),"application/json","utf-8",None,len(data),hashlib.sha256(data).hexdigest(),StorageReference("src_00000000000000000000000000000001"),RawResultEvidenceSource.INLINE_JSON,page_summary=RawResultPageSummary(1)))
    out=normalize_paddle_vl_raw_result(raw,data,id_factory=ids,clock=clock); assert out.result is not None,out.diagnostics
    r=out.result.to_dict(); assert r['state']=='partial'; assert any(o.get('content',{}).get('text')=='retained valid text marker' for o in r['normalized_observations']); figure=[n for n in r['nodes'] if n['node_type']=='figure'][0]; assert 'geometry' not in figure; assert 'geometry' not in [o for o in r['normalized_observations'] if o['observation_id']==figure['observation_ids'][0]][0]; assert 'geometry' not in [e for e in r['evidence_links'] if e['target_id']==figure['observation_ids'][0]][0]; assert any(w['code']=='BLOCK_GEOMETRY_UNAVAILABLE' for w in r['warnings']); assert all('retained valid text marker' not in w['message'] for w in r['warnings'])

def test_table_with_unavailable_structured_cells_retains_text_as_partial():
    retained={"profile":"full","status":"completed","documents":[{"status":"completed","pages":[{"local_page_index":0,"page_index":0,"source_page_range":{"page_start":1,"page_end":1},"width":100,"height":100,"blocks":[{"id":"table","type":"table","text":"A | B","bbox":[1,1,90,90],"order":0}]}]}]}; data=json.dumps(retained,sort_keys=True,separators=(',',':')).encode()
    raw=RawProcessingResultEnvelope(RawResultIdentity("attempt",None,"doc","file","paddle-vl-api","job",provider_result_profile="full",provider_result_status="completed"),RawResultSourceProvenance("a"*64),RawResultProviderProvenance(pipeline_version="v1.6"),RawResultIngestionMetadata(clock(),"application/json","utf-8",None,len(data),hashlib.sha256(data).hexdigest(),StorageReference("src_00000000000000000000000000000001"),RawResultEvidenceSource.INLINE_JSON,page_summary=RawResultPageSummary(1)))
    out=normalize_paddle_vl_raw_result(raw,data,id_factory=ids,clock=clock); assert out.result is not None,out.diagnostics
    r=out.result.to_dict(); node=r['nodes'][0]; obs=r['normalized_observations'][0]; assert r['state']=='partial' and node['node_type']=='table' and node['text']=='A | B' and obs['content']['text']=='A | B'; assert node['table']=={'structure_state':'unstructured','row_count':0,'column_count':0}; assert any(w['code']=='TABLE_CELLS_UNAVAILABLE' for w in r['warnings']); assert r['quality_summary']['degraded_block_count']==1; assert node['observation_ids']==[obs['observation_id']] and node['evidence_link_ids']==[r['evidence_links'][0]['evidence_link_id']]

def test_formula_with_unavailable_secondary_representation_retains_text_as_partial():
    retained={"profile":"full","status":"completed","documents":[{"status":"completed","pages":[{"local_page_index":0,"page_index":0,"source_page_range":{"page_start":1,"page_end":1},"width":100,"height":100,"blocks":[{"id":"formula","type":"formula","text":"x² + y²","metadata":{"latex":123},"order":0}]}]}]}; data=json.dumps(retained,sort_keys=True,separators=(',',':')).encode()
    raw=RawProcessingResultEnvelope(RawResultIdentity("attempt",None,"doc","file","paddle-vl-api","job",provider_result_profile="full",provider_result_status="completed"),RawResultSourceProvenance("a"*64),RawResultProviderProvenance(pipeline_version="v1.6"),RawResultIngestionMetadata(clock(),"application/json","utf-8",None,len(data),hashlib.sha256(data).hexdigest(),StorageReference("src_00000000000000000000000000000001"),RawResultEvidenceSource.INLINE_JSON,page_summary=RawResultPageSummary(1)))
    out=normalize_paddle_vl_raw_result(raw,data,id_factory=ids,clock=clock); assert out.result is not None,out.diagnostics
    r=out.result.to_dict(); n=r['nodes'][0]; o=r['normalized_observations'][0]; assert r['state']=='partial' and n['node_type']=='formula' and n['text']=='x² + y²' and o['content']['text']=='x² + y²'; assert n['formula']=={'role':'display','text':'x² + y²'}; assert r['quality_summary']['degraded_block_count']==1 and any(w['code']=='FORMULA_REPRESENTATION_UNAVAILABLE' for w in r['warnings']); assert n['observation_ids']==[o['observation_id']] and n['evidence_link_ids']==[r['evidence_links'][0]['evidence_link_id']]

def test_text_with_unavailable_optional_metadata_retains_text_as_partial():
    retained={"profile":"full","status":"completed","documents":[{"status":"completed","pages":[{"local_page_index":0,"page_index":0,"source_page_range":{"page_start":1,"page_end":1},"width":100,"height":100,"blocks":[{"id":"text","type":"text","text":"semantic text survives","confidence":"invalid","bbox":[1,1,20,20],"order":0}]}]}]}; data=json.dumps(retained,sort_keys=True,separators=(',',':')).encode()
    raw=RawProcessingResultEnvelope(RawResultIdentity("attempt",None,"doc","file","paddle-vl-api","job",provider_result_profile="full",provider_result_status="completed"),RawResultSourceProvenance("a"*64),RawResultProviderProvenance(pipeline_version="v1.6"),RawResultIngestionMetadata(clock(),"application/json","utf-8",None,len(data),hashlib.sha256(data).hexdigest(),StorageReference("src_00000000000000000000000000000001"),RawResultEvidenceSource.INLINE_JSON,page_summary=RawResultPageSummary(1)))
    out=normalize_paddle_vl_raw_result(raw,data,id_factory=ids,clock=clock); assert out.result is not None,out.diagnostics
    r=out.result.to_dict(); o=r['normalized_observations'][0]; n=r['nodes'][0]; assert r['state']=='partial' and o['content']['text']=='semantic text survives' and 'confidence' not in o and 'confidence' not in n; assert any(w['code']=='OPTIONAL_METADATA_UNAVAILABLE' for w in r['warnings']); assert r['quality_summary']['degraded_block_count']==1 and n['observation_ids']==[o['observation_id']] and n['evidence_link_ids']==[r['evidence_links'][0]['evidence_link_id']]

def test_malformed_text_block_is_skipped_without_renumbering_later_blocks():
    blocks=[{"id":"first","type":"text","text":"first","bbox":[1,1,2,2],"order":0},{"id":"bad","type":"text","text":None,"order":1},{"id":"last","type":"text","text":"last","bbox":[3,3,4,4],"order":2}]; retained={"profile":"full","status":"completed","documents":[{"status":"completed","pages":[{"local_page_index":0,"page_index":0,"source_page_range":{"page_start":1,"page_end":1},"width":100,"height":100,"blocks":blocks}]}]}; data=json.dumps(retained,sort_keys=True,separators=(',',':')).encode()
    raw=RawProcessingResultEnvelope(RawResultIdentity("attempt",None,"doc","file","paddle-vl-api","job",provider_result_profile="full",provider_result_status="completed"),RawResultSourceProvenance("a"*64),RawResultProviderProvenance(pipeline_version="v1.6"),RawResultIngestionMetadata(clock(),"application/json","utf-8",None,len(data),hashlib.sha256(data).hexdigest(),StorageReference("src_00000000000000000000000000000001"),RawResultEvidenceSource.INLINE_JSON,page_summary=RawResultPageSummary(1)))
    out=normalize_paddle_vl_raw_result(raw,data,id_factory=ids,clock=clock); assert out.result is not None,out.diagnostics
    r=out.result.to_dict(); assert r['state']=='partial'; assert [n['node_id'] for n in r['nodes']]==['node_0_0','node_0_2']; assert [n['ordinal'] for n in r['nodes']]==[0,2]; assert [o['content']['text'] for o in r['normalized_observations']]==['first','last']; assert r['quality_summary']['skipped_block_count']==1 and any(w['code']=='MALFORMED_REQUIRED_SEMANTIC_TEXT' for w in r['warnings'])

def test_all_unusable_semantic_blocks_return_no_spr():
    blocks=[{"id":"missing","type":"text","text":None,"order":0},{"id":"blank","type":"paragraph","text":"   ","order":1}]; retained={"profile":"full","status":"completed","documents":[{"status":"completed","pages":[{"local_page_index":0,"page_index":0,"source_page_range":{"page_start":1,"page_end":1},"width":100,"height":100,"blocks":blocks}]}]}; data=json.dumps(retained,sort_keys=True,separators=(',',':')).encode()
    raw=RawProcessingResultEnvelope(RawResultIdentity("attempt",None,"doc","file","paddle-vl-api","job",provider_result_profile="full",provider_result_status="completed"),RawResultSourceProvenance("a"*64),RawResultProviderProvenance(pipeline_version="v1.6"),RawResultIngestionMetadata(clock(),"application/json","utf-8",None,len(data),hashlib.sha256(data).hexdigest(),StorageReference("src_00000000000000000000000000000001"),RawResultEvidenceSource.INLINE_JSON,page_summary=RawResultPageSummary(1)))
    out=normalize_paddle_vl_raw_result(raw,data,id_factory=ids,clock=clock); assert out.result is None and out.diagnostics[0].code=='NO_USABLE_OUTPUT'
