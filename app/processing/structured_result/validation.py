"""Focused, provider-independent cross-reference validation for SPR v1."""
from __future__ import annotations
import math
from typing import Any, Mapping
from .models import (
    PAGE_HAS_NO_USABLE_SEMANTIC_CONTENT,
    PARTIAL_DOCUMENT_RECOVERY,
    StructuredPageStatus,
)

class StructuredResultValidationError(ValueError): pass

def _ids(rows: list[Mapping[str, Any]], key: str) -> set[str]:
    if not all(isinstance(row, Mapping) and isinstance(row.get(key), str) and row[key] for row in rows):
        raise StructuredResultValidationError(f"invalid {key}")
    values = {row[key] for row in rows}
    if len(values) != len(rows): raise StructuredResultValidationError(f"duplicate {key}")
    return values

def _geometry(value: Any) -> None:
    if value is None: return
    box = value.get("normalized_bbox") if isinstance(value, Mapping) else None
    if not isinstance(box, list) or len(box) != 4: raise StructuredResultValidationError("invalid geometry")
    try: coords = [float(x) for x in box]
    except (TypeError, ValueError): raise StructuredResultValidationError("invalid geometry")
    if not all(math.isfinite(x) and 0 <= x <= 1 for x in coords) or coords[0] >= coords[2] or coords[1] >= coords[3]: raise StructuredResultValidationError("invalid geometry")

def validate_structured_processing_result(value: Mapping[str, Any]) -> None:
    if value.get("schema_id") != "atlas.structured-processing-result" or value.get("schema_version") != 1: raise StructuredResultValidationError("unsupported SPR schema")
    if value.get("state") not in {"complete", "partial", "invalid"}: raise StructuredResultValidationError("invalid result state")
    pages, nodes, observations, evidence, warnings, diagnostics = (value.get(k, []) for k in ("pages", "nodes", "normalized_observations", "evidence_links", "warnings", "diagnostics"))
    if not all(isinstance(rows, list) for rows in (pages,nodes,observations,evidence,warnings,diagnostics)): raise StructuredResultValidationError("invalid collection")
    page_ids,node_ids,observation_ids,evidence_ids,warning_ids = (_ids(rows,key) for rows,key in ((pages,"page_id"),(nodes,"node_id"),(observations,"observation_id"),(evidence,"evidence_link_id"),(warnings,"warning_id")))
    parents: dict[str, str] = {}
    for page in pages:
        if not isinstance(page.get("status"), StructuredPageStatus) or not isinstance(page.get("page_index"), int) or page["page_index"] < 0 or page.get("width",0) <= 0 or page.get("height",0) <= 0: raise StructuredResultValidationError("invalid page")
        expected_diagnostics = [PAGE_HAS_NO_USABLE_SEMANTIC_CONTENT] if page["status"] is StructuredPageStatus.NO_USABLE_SEMANTIC_CONTENT else []
        if page.get("diagnostics") != expected_diagnostics: raise StructuredResultValidationError("invalid page diagnostics")
        if not set(page.get("root_node_ids", [])) <= node_ids: raise StructuredResultValidationError("dangling page root")
    if len({p["page_index"] for p in pages}) != len(pages): raise StructuredResultValidationError("duplicate page index")
    expected_document_diagnostics = (
        [PARTIAL_DOCUMENT_RECOVERY]
        if any(page["status"] is StructuredPageStatus.USABLE for page in pages)
        and any(page["status"] is StructuredPageStatus.NO_USABLE_SEMANTIC_CONTENT for page in pages)
        else []
    )
    if diagnostics != expected_document_diagnostics: raise StructuredResultValidationError("invalid document diagnostics")
    for observation in observations:
        if observation.get("page_id") not in page_ids or not set(observation.get("evidence_link_ids", [])) <= evidence_ids: raise StructuredResultValidationError("dangling observation reference")
        _geometry(observation.get("geometry"))
    observations_by_page = {page_id: [o for o in observations if o.get("page_id") == page_id] for page_id in page_ids}
    for page in pages:
        has_semantic_content = bool(page.get("root_node_ids")) and bool(observations_by_page[page["page_id"]])
        if page["status"] is StructuredPageStatus.USABLE and not has_semantic_content: raise StructuredResultValidationError("usable page lacks semantic content")
        if page["status"] is StructuredPageStatus.NO_USABLE_SEMANTIC_CONTENT and (page.get("root_node_ids") or observations_by_page[page["page_id"]]): raise StructuredResultValidationError("degraded page has semantic content")
    if not any(page["status"] is StructuredPageStatus.USABLE for page in pages): raise StructuredResultValidationError("result lacks usable pages")
    if any(page["status"] is StructuredPageStatus.NO_USABLE_SEMANTIC_CONTENT for page in pages) and value["state"] != "partial": raise StructuredResultValidationError("degraded page requires partial result")
    node_by_id={node["node_id"]:node for node in nodes}
    for node in nodes:
        if not set(node.get("page_ids", [])) <= page_ids or not set(node.get("observation_ids", [])) <= observation_ids or not set(node.get("evidence_link_ids", [])) <= evidence_ids or not set(node.get("child_ids", [])) <= node_ids: raise StructuredResultValidationError("dangling node reference")
        _geometry(node.get("geometry"))
        for child in node.get("child_ids", []):
            if child in parents or node_by_id[child].get("parent_id") != node["node_id"]: raise StructuredResultValidationError("non-reciprocal hierarchy")
            parents[child]=node["node_id"]
    for node in nodes:
        if node.get("parent_id") and parents.get(node["node_id"]) != node["parent_id"]: raise StructuredResultValidationError("non-reciprocal hierarchy")
    for link in evidence:
        if link.get("target_kind") != "observation" or link.get("target_id") not in observation_ids: raise StructuredResultValidationError("dangling evidence target")
        _geometry(link.get("geometry"))
    for warning in warnings:
        if not set(warning.get("evidence_link_ids", [])) <= evidence_ids: raise StructuredResultValidationError("dangling warning reference")
    if value["state"] == "partial" and not (value.get("quality_summary",{}).get("page_coverage",{}).get("missing_page_indices") or value.get("quality_summary",{}).get("degraded_block_count")): raise StructuredResultValidationError("partial result lacks coverage")
