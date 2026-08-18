"""Offline-only Paddle-VL final-result to SPR v1 normalizer."""
from __future__ import annotations
import hashlib, json, math, unicodedata, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from app.processing.raw_result import RawProcessingResultEnvelope, unsafe_metadata_keys
from app.processing.structured_result import StructuredPageStatus, StructuredProcessingResult

SUPPORTED_PROFILE = "full"
SUPPORTED_PIPELINE_VERSION = "v1.6"

@dataclass(frozen=True)
class NormalizationDiagnostic:
    code: str
    message: str

@dataclass(frozen=True)
class NormalizationOutcome:
    result: StructuredProcessingResult | None
    diagnostics: tuple[NormalizationDiagnostic, ...] = ()

@dataclass(frozen=True)
class PageMapping:
    provider_local_index: int
    source_page_index: int
    display_page_number: int | None
    source_range: tuple[int, int]
    spr_page_index: int

def _default_id(kind: str, *parts: object) -> str: return f"{kind}_{uuid.uuid4().hex}"
def _utc_now() -> datetime: return datetime.now(timezone.utc)
def _fail(code: str, message: str) -> NormalizationOutcome: return NormalizationOutcome(None, (NormalizationDiagnostic(code, message),))
def _time(clock):
    v = clock()
    return v.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
def _id(factory, kind, *parts): return factory(kind, *parts)
def _finite(value): return isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value)
def _bbox(raw, width, height):
    if not isinstance(raw, list) or len(raw) != 4 or not all(_finite(v) for v in raw): raise ValueError("invalid geometry")
    x1,y1,x2,y2 = map(float, raw)
    if x2 <= x1 or y2 <= y1: raise ValueError("degenerate geometry")
    vals = [x1/width,y1/height,x2/width,y2/height]
    if any(v < -0.000001 or v > 1.000001 for v in vals): raise ValueError("material geometry overflow")
    return {"normalized_bbox": [f"{min(1,max(0,v)):.6f}" for v in vals]}

_TYPES = {"title":"heading", "heading":"heading", "text":"paragraph", "paragraph":"paragraph", "list":"list", "table":"table", "image":"figure", "figure":"figure", "formula":"formula", "caption":"caption", "header":"header", "footer":"footer", "footnote":"footnote"}

def normalize_paddle_vl_raw_result(raw_result: RawProcessingResultEnvelope, retained_payload: bytes, *, id_factory: Callable[..., str]=_default_id, clock: Callable[[],datetime]=_utc_now) -> NormalizationOutcome:
    """Return a result or safe diagnostics; never retrieves artifacts or calls a provider."""
    i, ing = raw_result.identity, raw_result.ingestion
    if i.provider_name != "paddle-vl-api": return _fail("PROVIDER_IDENTITY", "raw result is not Paddle-VL")
    if i.provider_result_profile != SUPPORTED_PROFILE: return _fail("UNSUPPORTED_PROFILE", "unsupported retained result profile")
    if unsafe_metadata_keys(raw_result.provider.configuration) or unsafe_metadata_keys(ing.artifact_metadata.provider_metadata if ing.artifact_metadata else {}): return _fail("UNSAFE_METADATA", "unsafe metadata is not normalizable")
    if len(retained_payload) != ing.payload_size_bytes: return _fail("PAYLOAD_SIZE_MISMATCH", "retained payload size mismatch")
    if hashlib.sha256(retained_payload).hexdigest() != ing.payload_sha256: return _fail("PAYLOAD_CHECKSUM_MISMATCH", "retained payload checksum mismatch")
    try:
        payload = json.loads(retained_payload.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")), object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError): return _fail("MALFORMED_JSON", "retained payload is not finite UTF-8 JSON")
    if not isinstance(payload, dict) or payload.get("profile") != SUPPORTED_PROFILE or not isinstance(payload.get("documents"), list) or len(payload["documents"]) != 1: return _fail("UNSUPPORTED_PAYLOAD", "unsupported Paddle-VL result shape/profile")
    if raw_result.provider.pipeline_version != SUPPORTED_PIPELINE_VERSION: return _fail("UNSUPPORTED_REVISION", "unsupported Paddle-VL pipeline revision")
    doc = payload["documents"][0]
    if payload.get("status") not in {"completed", "partial_failed"} or doc.get("status", payload.get("status")) not in {"completed", "partial_failed"}: return _fail("NONTERMINAL_RESULT", "result is not terminal")
    pages = doc.get("pages")
    if not isinstance(pages, list) or not pages: return _fail("NO_USABLE_PAGES", "result has no mapped pages")
    expected = ing.page_summary.page_count_observed if ing.page_summary else len(pages)
    try:
        seen_local=set(); seen_source=set(); mapped=[]
        for page in pages:
            local = page.get("local_page_index", page.get("page_index"))
            source_explicit = page.get("source_page_index")
            source = source_explicit if source_explicit is not None else page.get("page_index")
            page_number = page.get("page_number")
            raw_range = page.get("source_page_range")
            if isinstance(raw_range, dict): begin, finish = raw_range["page_start"], raw_range["page_end"]
            elif isinstance(raw_range, (list, tuple)) and len(raw_range) == 2: begin, finish = raw_range
            else: raise ValueError("malformed source range")
            if not all(isinstance(v, int) for v in (begin, finish)) or begin < 1 or finish < begin:
                raise ValueError("malformed source range")
            if source_explicit is None and begin > 1:
                raise ValueError("nonzero subset requires source page identity")
            begin, finish = begin - 1, finish - 1
            if not all(isinstance(v, int) for v in (local, source, begin, finish)) or local < 0 or source < 0 or begin < 0 or finish < begin or source not in range(begin, finish + 1) or local in seen_local or source in seen_source: raise ValueError("invalid page mapping")
            if not _finite(page.get("width")) or not _finite(page.get("height")) or page["width"] <= 0 or page["height"] <= 0: raise ValueError("invalid page dimensions")
            if page.get("rotation_degrees",0) not in {0,90,180,270}: raise ValueError("invalid rotation")
            seen_local.add(local); seen_source.add(source); mapped.append((page, PageMapping(local, source, page_number if isinstance(page_number, int) else None, (begin, finish), 0)))
        mapped.sort(key=lambda pair: pair[1].provider_local_index)
        if [m.provider_local_index for _,m in mapped] != list(range(len(mapped))): raise ValueError("noncontiguous provider local mapping")
        mapped=[(page, PageMapping(m.provider_local_index,m.source_page_index,m.display_page_number,m.source_range,index)) for index,(page,m) in enumerate(mapped)]
        if payload.get("status") == "completed" and ing.page_summary is not None and len(mapped) != expected: raise ValueError("invalid page coverage")
        if len(mapped) > expected: raise ValueError("invalid page coverage")
    except (KeyError, ValueError): return _fail("INVALID_PAGE_MAPPING", "invalid or duplicate page mapping")
    raw_id = i.atlas_attempt_id; result_id=_id(id_factory,"result"); run_id=i.atlas_attempt_id; timestamp = _time(clock)
    out_pages=[]; observations=[]; nodes=[]; evidence=[]; warnings=[]; degraded=False; skipped_blocks=0; extensions={"org.atlas.page-source-mapping": []}; declared_source_pages = set().union(*(set(range(m.source_range[0], m.source_range[1] + 1)) for _, m in mapped))
    missing=sorted(declared_source_pages-set(m.source_page_index for _, m in mapped))
    for page, mapping in mapped:
        pi=mapping.spr_page_index; page_id=_id(id_factory,"page",pi); roots=[]
        page_observation_count = len(observations)
        blocks=page.get("blocks",[])
        if not isinstance(blocks,list): return _fail("INVALID_BLOCK_MAPPING", "page blocks are malformed")
        for ordinal, block in enumerate(sorted(blocks, key=lambda b: b.get("order", 0) if isinstance(b, dict) else 0)):
            if not isinstance(block,dict) or not isinstance(block.get("id"),str): return _fail("INVALID_BLOCK_MAPPING", "block identity is malformed")
            try: geometry=_bbox(block["bbox"],page["width"],page["height"]) if "bbox" in block else None
            except ValueError:
                if block.get("type") not in {"image", "figure"}: return _fail("INVALID_GEOMETRY", "block geometry is invalid")
                geometry=None; degraded=True
            bi=ordinal; obs_id=_id(id_factory,"observation",pi,bi); node_id=_id(id_factory,"node",pi,bi); ev_id=_id(id_factory,"evidence",pi,bi)
            text=block.get("text"); text=unicodedata.normalize("NFC",text) if isinstance(text,str) else None
            typ=block.get("type"); node_type=_TYPES.get(typ,"unknown")
            if typ in {"text", "paragraph", "title", "heading", "caption", "header", "footer", "footnote"} and (not isinstance(text, str) or not text.strip()):
                degraded=True; skipped_blocks += 1; warnings.append(_warning(id_factory,"MALFORMED_REQUIRED_SEMANTIC_TEXT",f"page_{pi}_block_{ordinal}",[])); continue
            obs={"observation_id":obs_id,"observation_type":typ if typ in _TYPES else "unknown","page_id":page_id,"status":"accepted","evidence_link_ids":[ev_id]}
            if text is not None: obs["content"]={"text":text}
            if geometry: obs["geometry"]=geometry
            if "confidence" in block:
                if _finite(block.get("confidence")): obs["confidence"]=f"{float(block['confidence']):g}"
                elif text is not None:
                    degraded=True; warnings.append(_warning(id_factory,"OPTIONAL_METADATA_UNAVAILABLE",node_id,[]))
            link={"evidence_link_id":ev_id,"target_kind":"observation","target_id":obs_id,"raw_result_id":raw_id,"provider_block_id":block["id"],"source_checksum_sha256":raw_result.source.source_checksum_sha256,"source_page_index":mapping.source_page_index,"spr_page_id":page_id,"role":"provider_block"}
            if geometry: link["geometry"]=geometry
            node={"node_id":node_id,"node_type":node_type,"page_ids":[page_id],"observation_ids":[obs_id],"evidence_link_ids":[ev_id],"child_ids":[],"ordinal":ordinal}
            if text is not None: node["text"]=text
            if geometry: node["geometry"]=geometry
            if "confidence" in obs: node["confidence"]=obs["confidence"]
            if typ == "table":
                node["table"]={"structure_state":"unstructured","row_count":0,"column_count":0}
                warnings.append(_warning(id_factory,"TABLE_CELLS_UNAVAILABLE",node_id,[]))
                if text is not None: degraded=True
            if typ in {"image","figure"}:
                warnings.append(_warning(id_factory,"FIGURE_CROP_UNAVAILABLE",node_id,[]))
                if "bbox" in block and geometry is None: warnings.append(_warning(id_factory,"BLOCK_GEOMETRY_UNAVAILABLE",node_id,[]))
            if typ == "formula":
                formula={"role":"display"}
                if text is not None: formula["text"]=text
                if isinstance(block.get("metadata"),dict) and "latex" in block["metadata"]:
                    if isinstance(block["metadata"].get("latex"),str): formula["latex"]=block["metadata"]["latex"]
                    elif text is not None:
                        degraded=True; warnings.append(_warning(id_factory,"FORMULA_REPRESENTATION_UNAVAILABLE",node_id,[]))
                node["formula"]=formula
            if node_type == "unknown":
                extensions.setdefault("com.atlas.provider.paddle-vl", {}).setdefault("unknown_blocks", []).append({"provider_block_id": block["id"], "original_block_type": typ if isinstance(typ,str) else "unknown", "node_id": node_id})
                warnings.append(_warning(id_factory,"UNKNOWN_PROVIDER_BLOCK_TYPE",node_id,[]))
            observations.append(obs); nodes.append(node); evidence.append(link); roots.append(node_id)
        extensions["org.atlas.page-source-mapping"].append({"page_id":page_id,"provider_local_page_index":mapping.provider_local_index,"source_page_index":mapping.source_page_index,"display_page_number":mapping.display_page_number,"source_page_range":[mapping.source_range[0],mapping.source_range[1]]})
        page_status = StructuredPageStatus.USABLE if len(observations) > page_observation_count else StructuredPageStatus.NO_USABLE_SEMANTIC_CONTENT
        out_pages.append({"page_id":page_id,"page_index":pi,"page_number":mapping.display_page_number,"width":page["width"],"height":page["height"],"rotation_degrees":page.get("rotation_degrees",0),"coordinate_frame":"displayed_post_rotation","coordinate_origin":"top_left","coordinate_unit":"pdf_point","root_node_ids":roots,"status":page_status})
    if not observations: return _fail("NO_USABLE_OUTPUT", "no usable blocks were mapped")
    partial = payload.get("status") == "partial_failed" or bool(missing) or degraded
    if partial:
        for idx in missing: warnings.append(_warning(id_factory,"PAGE_PROCESSING_FAILED",f"page_missing_{idx}",[]))
    state="partial" if partial else "complete"
    data={"schema_id":"atlas.structured-processing-result","schema_version":1,"result_id":result_id,"processing_run_id":run_id,"document_id":i.document_id,"source_file_id":i.source_file_id,"created_at":timestamp,"state":state,"source":{"checksum_sha256":raw_result.source.source_checksum_sha256},"raw_result":{"raw_result_id":raw_id,"storage_reference":str(ing.storage_reference),"payload_checksum_sha256":ing.payload_sha256,"schema_revision":"2026-07-10"},"provenance":{"provider_name":"paddle-vl-api","normalizer_name":"paddle-vl-raw-result-normalizer","normalizer_implementation_version":"1","normalizer_configuration_hash":"0"*64,"normalization_timestamp":timestamp},"pages":out_pages,"normalized_observations":observations,"nodes":nodes,"evidence_links":evidence,"assets":[],"warnings":warnings,"quality_summary":{"mapping_valid":True,"schema_validation_state":"valid","content_completeness":state,"page_coverage":{"expected_page_count":expected,"mapped_page_indices":[m.spr_page_index for _,m in mapped], **({"missing_page_indices":missing,"failed_page_indices":missing} if partial else {})},"warning_counts":{"warning":len(warnings)}, **({"degraded_block_count":1,"skipped_block_count":skipped_blocks} if degraded else {})},"reading_order_edges":[],"alternative_groups":[],"extensions":extensions}
    try: return NormalizationOutcome(StructuredProcessingResult(data))
    except ValueError: return _fail("SPR_VALIDATION_FAILED", "mapped result failed SPR validation")

def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("duplicate JSON key")
        result[key] = value
    return result

def _warning(factory, code, scope, evidence):
    messages={"TABLE_CELLS_UNAVAILABLE":"Structured cells were not retained.","FIGURE_CROP_UNAVAILABLE":"Crop metadata is not a retained asset.","UNKNOWN_PROVIDER_BLOCK_TYPE":"Provider class mapped to unknown.","BLOCK_GEOMETRY_UNAVAILABLE":"Block geometry was unavailable.","FORMULA_REPRESENTATION_UNAVAILABLE":"Formula representation was unavailable.","OPTIONAL_METADATA_UNAVAILABLE":"Optional metadata was unavailable.","MALFORMED_REQUIRED_SEMANTIC_TEXT":"Required semantic text was unavailable.","PAGE_PROCESSING_FAILED":"A source page failed processing."}
    return {"warning_id":_id(factory,"warning",code),"severity":"warning","code":code,"message":messages[code],"scope_kind":"page" if code=="PAGE_PROCESSING_FAILED" else "node","scope_id":scope,"affected_ids":[] if code=="PAGE_PROCESSING_FAILED" else [scope],"evidence_link_ids":evidence,"recoverable":True,"canonicalization_blocking":code=="PAGE_PROCESSING_FAILED"}
