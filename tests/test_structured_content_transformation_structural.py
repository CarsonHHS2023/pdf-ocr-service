from __future__ import annotations

import copy

import pytest

from app.processing.structured_result import StructuredProcessingResult
from app.processing.structured_result.models import StructuredPageStatus
from app.structured_content.enums import ContentNodeType, ContentRecoveryState, NodeRecoveryState, PageRecoveryState
from app.structured_content.serialization import serialize_structured_content_candidate
from app.structured_content.transformation import CandidateIdentityInput, TransformationContext, TransformationInvariantViolation, TransformationNotImplemented, transform_spr_to_candidate
from app.structured_content.validation import validate_content_candidate


def ctx() -> TransformationContext:
    return TransformationContext("doc-struct", CandidateIdentityInput("candidate-struct", "lineage-struct"), processing_run_ref="run-struct", source_file_ref="source-struct")


def base(nodes: list[dict], pages: list[dict] | None = None) -> dict:
    if pages is None:
        roots = [n["node_id"] for n in nodes if not n.get("parent_id")]
        pages = [{"page_id":"page-1","page_index":0,"page_number":1,"width":100,"height":200,"status":StructuredPageStatus.USABLE,"root_node_ids":roots}]
    observations=[]; evidence=[]
    for i,n in enumerate(nodes):
        oid=f"obs-{n['node_id']}"; eid=f"ev-{n['node_id']}"
        n.setdefault("page_ids", [pages[0]["page_id"]])
        n.setdefault("observation_ids", [oid]); n.setdefault("evidence_link_ids", [eid]); n.setdefault("ordinal", i)
        observations.append({"observation_id":oid,"page_id":n["page_ids"][0],"observation_type":n["node_type"],"content":{"text":n.get("text", n["node_id"])},"evidence_link_ids":[eid]})
        evidence.append({"evidence_link_id":eid,"target_kind":"observation","target_id":oid,"source_page_index":next(p["page_index"] for p in pages if p["page_id"] == n["page_ids"][0])})
    state = "partial" if any(p["status"] is StructuredPageStatus.NO_USABLE_SEMANTIC_CONTENT for p in pages) else "complete"
    data={"schema_id":"atlas.structured-processing-result","schema_version":1,"result_id":"spr-struct","state":state,"raw_result":{"raw_result_id":"raw-struct"},"pages":pages,"nodes":nodes,"normalized_observations":observations,"evidence_links":evidence,"warnings":[],"diagnostics":[],"quality_summary":{"page_coverage":{"missing_page_indices":[p["page_index"] for p in pages if p["status"] is StructuredPageStatus.NO_USABLE_SEMANTIC_CONTENT]},"degraded_block_count": int(any(p["status"] is StructuredPageStatus.NO_USABLE_SEMANTIC_CONTENT for p in pages)),"warning_counts":{}}}
    return StructuredProcessingResult(data).to_dict()


def transform(data: dict):
    return transform_spr_to_candidate(StructuredProcessingResult(copy.deepcopy(data)), context=ctx())


def test_list_with_items_preserves_explicit_hierarchy_and_attributes_deterministically() -> None:
    data = base([
        {"node_id":"list-1","node_type":"list","text":"","child_ids":["item-1","item-2"],"extensions":{"ordered":True,"marker_style":"decimal"}},
        {"node_id":"item-1","node_type":"list_item","text":"First","parent_id":"list-1","extensions":{"marker":"1.","ordinal":1}},
        {"node_id":"item-2","node_type":"list_item","text":"Second","parent_id":"list-1","extensions":{"marker":"2.","ordinal":2}},
    ])
    a = transform(data); b = transform(data)
    assert a == b
    assert serialize_structured_content_candidate(a) == serialize_structured_content_candidate(b)
    assert [n.node_type for n in a.nodes] == [ContentNodeType.LIST, ContentNodeType.LIST_ITEM, ContentNodeType.LIST_ITEM]
    assert a.nodes[1].parent_id == a.nodes[0].node_id and a.nodes[2].parent_id == a.nodes[0].node_id
    assert a.nodes[0].attributes.ordered is True and a.nodes[1].attributes.ordinal == 1
    assert a.pages[0].root_node_ids == (a.nodes[0].node_id,)
    assert validate_content_candidate(a).is_valid


def test_nested_list_uses_only_explicit_source_hierarchy() -> None:
    data = base([
        {"node_id":"list-1","node_type":"list","text":"","child_ids":["item-1"]},
        {"node_id":"item-1","node_type":"list_item","text":"Parent","parent_id":"list-1","child_ids":["list-2"]},
        {"node_id":"list-2","node_type":"list","text":"","parent_id":"item-1","child_ids":["item-2"]},
        {"node_id":"item-2","node_type":"list_item","text":"Child","parent_id":"list-2"},
    ])
    c = transform(data)
    assert [n.parent_id for n in c.nodes] == [None, c.nodes[0].node_id, c.nodes[1].node_id, c.nodes[2].node_id]
    assert validate_content_candidate(c).is_valid


def test_list_item_without_parent_recovers_to_root_with_warning_and_degraded_page() -> None:
    data = base([{"node_id":"item-1","node_type":"list_item","text":"Orphan"}])
    c = transform(data)
    assert c.nodes[0].parent_id is None
    assert c.nodes[0].recovery_state is NodeRecoveryState.RECOVERED
    assert c.warnings[0].code == "MISSING_PARENT"
    assert c.pages[0].recovery_state is PageRecoveryState.DEGRADED
    assert c.recovery_summary.state is ContentRecoveryState.DEGRADED
    assert validate_content_candidate(c).is_valid


def test_caption_formula_header_footer_and_other_structural_text_are_preserved() -> None:
    data = base([
        {"node_id":"h","node_type":"header","text":"Running head"},
        {"node_id":"cap","node_type":"caption","text":"Figure caption","extensions":{"target_ref":"figure-1"}},
        {"node_id":"f","node_type":"formula","text":"E = mc^2","formula":{"latex":"E = mc^2","role":"display"}},
        {"node_id":"fn","node_type":"footnote","text":"Footnote text"},
        {"node_id":"foot","node_type":"footer","text":"Footer"},
    ])
    c = transform(data)
    assert [n.node_type for n in c.nodes] == [ContentNodeType.HEADER, ContentNodeType.CAPTION, ContentNodeType.FORMULA, ContentNodeType.FOOTNOTE, ContentNodeType.FOOTER]
    assert c.nodes[1].text == "Figure caption" and c.nodes[2].attributes.notation == "latex"
    assert c.warnings[0].code == "UNRESOLVED_CAPTION_ASSOCIATION"
    assert not c.assets
    assert validate_content_candidate(c).is_valid


def test_unknown_and_reference_like_kinds_preserve_source_kind_as_generic_content() -> None:
    data = base([
        {"node_id":"u","node_type":"mystery_box","text":"Mystery"},
        {"node_id":"q","node_type":"quote","text":"Quote"},
        {"node_id":"code","node_type":"code","text":"print(1)"},
        {"node_id":"ref","node_type":"reference","text":"[1]"},
        {"node_id":"pn","node_type":"page_number","text":"7"},
    ])
    c = transform(data)
    assert [n.node_type for n in c.nodes] == [ContentNodeType.UNKNOWN] * 5
    assert [n.extensions["org.atlas.transform.source_kind"] for n in c.nodes] == ["mystery_box", "quote", "code", "reference", "page_number"]
    assert [w.code for w in c.warnings] == ["UNKNOWN_ELEMENT_KIND"] * 5
    assert "payload" not in str(c.warnings)
    assert validate_content_candidate(c).is_valid


def test_no_usable_page_contributes_to_recovery_summary_without_semantic_nodes() -> None:
    pages=[{"page_id":"page-1","page_index":0,"width":100,"height":200,"status":StructuredPageStatus.USABLE,"root_node_ids":["p"]},{"page_id":"page-2","page_index":1,"width":100,"height":200,"status":StructuredPageStatus.NO_USABLE_SEMANTIC_CONTENT,"root_node_ids":[]}]
    data = base([{"node_id":"p","node_type":"paragraph","text":"Usable"}], pages)
    c = transform(data)
    assert [p.recovery_state for p in c.pages] == [PageRecoveryState.COMPLETE, PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT]
    assert c.recovery_summary.no_usable_semantic_content_pages == 1
    assert validate_content_candidate(c).is_valid


def test_cross_page_and_cycle_hierarchy_fail_boundedly_without_partial_candidate() -> None:
    pages=[{"page_id":"page-1","page_index":0,"width":100,"height":200,"status":StructuredPageStatus.USABLE,"root_node_ids":["a"]},{"page_id":"page-2","page_index":1,"width":100,"height":200,"status":StructuredPageStatus.USABLE,"root_node_ids":["b"]}]
    data = base([{"node_id":"a","node_type":"paragraph","text":"A","child_ids":["b"],"page_ids":["page-1"]},{"node_id":"b","node_type":"paragraph","text":"B","parent_id":"a","page_ids":["page-2"]}], pages)
    spr = object.__new__(StructuredProcessingResult); object.__setattr__(spr, "data", data)
    with pytest.raises(TransformationInvariantViolation):
        transform_spr_to_candidate(spr, context=ctx())


def test_slice_3d_table_image_and_mixed_inputs_remain_atomic_bounded_failures() -> None:
    for node_type in ("table_cell", "diagram", "rendered_table_image", "image_crop"):
        data = base([{"node_id":"p","node_type":"paragraph","text":"Before"},{"node_id":"x","node_type":node_type,"text":"Unsupported"}])
        before = copy.deepcopy(data)
        with pytest.raises(TransformationNotImplemented):
            transform(data)
        assert data == before
