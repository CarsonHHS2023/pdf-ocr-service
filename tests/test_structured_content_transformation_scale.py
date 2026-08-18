from __future__ import annotations

from app.processing.structured_result import StructuredProcessingResult
from app.structured_content.enums import ContentNodeType
from app.structured_content.transformation import CandidateIdentityInput, TransformationContext, transform_spr_to_candidate
from tests.structured_content.transformation_s3e_helpers import assert_candidate_invariants, canonical, spr_dict, transform_fixture


def generated_spr(page_count: int, nodes_per_page: int) -> StructuredProcessingResult:
    pages=[]; nodes=[]; obs=[]; ev=[]
    for p in range(page_count):
        pid=f'p{p:03d}'; roots=[]
        pages.append({'page_id':pid,'page_index':p,'page_number':p+1,'width':100,'height':200,'status':'usable','root_node_ids':roots})
        for n in range(nodes_per_page):
            nid=f'n{p:03d}-{n:03d}'; roots.append(nid)
            kind='heading' if n == 0 else ('quote' if n % 17 == 0 else 'paragraph')
            nodes.append({'node_id':nid,'node_type':kind,'page_ids':[pid],'observation_ids':[f'o-{nid}'],'evidence_link_ids':[f'e-{nid}'],'ordinal':n,'text':f'Page {p} node {n}'})
            obs.append({'observation_id':f'o-{nid}','page_id':pid,'observation_type':kind,'content':{'text':f'Page {p} node {n}'},'evidence_link_ids':[f'e-{nid}']})
            ev.append({'evidence_link_id':f'e-{nid}','target_kind':'observation','target_id':f'o-{nid}','source_page_index':p})
    return StructuredProcessingResult({'schema_id':'atlas.structured-processing-result','schema_version':1,'result_id':f'spr-scale-{page_count}-{nodes_per_page}','state':'complete','raw_result':{'raw_result_id':'raw-scale'},'pages':pages,'nodes':nodes,'assets':[],'normalized_observations':obs,'evidence_links':ev,'warnings':[],'diagnostics':[],'quality_summary':{'page_coverage':{'mapped_page_indices':list(range(page_count))},'warning_counts':{}}})


def ctx(name: str) -> TransformationContext:
    return TransformationContext('doc-scale', CandidateIdentityInput(f'candidate-{name}', f'lineage-{name}'))


def test_scale_100_pages_is_validator_clean_and_deterministic() -> None:
    spr = generated_spr(100, 2)
    first = transform_spr_to_candidate(spr, context=ctx('100-pages'))
    second = transform_spr_to_candidate(spr, context=ctx('100-pages'))
    assert len(first.pages) == 100
    assert len(first.nodes) == 200
    assert_candidate_invariants(first)
    assert canonical(first) == canonical(second)


def test_scale_approximately_10000_nodes_is_stable() -> None:
    candidate = transform_spr_to_candidate(generated_spr(100, 100), context=ctx('10000-nodes'))
    assert len(candidate.pages) == 100
    assert len(candidate.nodes) == 10000
    assert sum(n.node_type is ContentNodeType.UNKNOWN for n in candidate.nodes) > 0
    assert_candidate_invariants(candidate)
    assert canonical(candidate) == canonical(transform_spr_to_candidate(generated_spr(100, 100), context=ctx('10000-nodes')))


def test_scale_approximately_1000_table_cells_is_stable() -> None:
    data = spr_dict('tables_assets')
    page = data['pages'][0]
    nodes=[]; obs=[]; ev=[]
    for t in range(10):
        nid=f'table-{t}'
        cells=[{'cell_id':f'c-{t}-{r}-{c}','row_index':r,'column_index':c,'text':f'{t}:{r}:{c}'} for r in range(10) for c in range(10)]
        node={'node_id':nid,'node_type':'table','page_ids':[page['page_id']],'observation_ids':[f'o-{nid}'],'evidence_link_ids':[f'e-{nid}'],'ordinal':t,'table':{'row_count':10,'column_count':10,'cells':cells}}
        nodes.append(node); obs.append({'observation_id':f'o-{nid}','page_id':page['page_id'],'observation_type':'table','content':{'text':nid},'evidence_link_ids':[f'e-{nid}']}); ev.append({'evidence_link_id':f'e-{nid}','target_kind':'observation','target_id':f'o-{nid}','source_page_index':0})
    page['root_node_ids'] = [n['node_id'] for n in nodes]
    data['nodes']=nodes; data['normalized_observations']=obs; data['evidence_links']=ev; data['assets']=[]
    candidate = transform_spr_to_candidate(StructuredProcessingResult(data), context=ctx('1000-cells'))
    assert sum(len(n.attributes.structure.cells) for n in candidate.nodes if n.node_type is ContentNodeType.TABLE) == 1000
    assert_candidate_invariants(candidate)
    assert canonical(candidate) == canonical(transform_spr_to_candidate(StructuredProcessingResult(data), context=ctx('1000-cells')))


def test_repeated_medium_fixture_runs_are_byte_identical() -> None:
    outputs = [canonical(transform_fixture('mixed_document')) for _ in range(10)]
    assert len(set(outputs)) == 1
