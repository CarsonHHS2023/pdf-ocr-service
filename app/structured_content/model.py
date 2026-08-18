from __future__ import annotations
from dataclasses import dataclass, field
from math import isfinite
from typing import Any
from .enums import *
from .identity import *

SCHEMA_ID = "atlas.structured-content-candidate"
SCHEMA_VERSION = 1
_RESERVED_EXTENSION_KEYS={"id","identity","lineage","lineage_key","parent","parent_id","sibling_order","page_order","recovery_state","accepted","current","evidence","evidence_ids","asset","asset_ids","asset_references"}

def _tuple(v: tuple[Any,...]) -> tuple[Any,...]: return v

def _finite(n: float, name: str) -> None:
    if not isinstance(n, (int,float)) or not isfinite(n): raise ValueError(f"{name} must be finite")

def _nonnegative_int(n: int, name: str) -> None:
    if not isinstance(n,int) or n < 0: raise ValueError(f"{name} must be nonnegative")

def _json(value: Any) -> Any:
    if value is None or isinstance(value, (str,bool,int)): return value
    if isinstance(value, float):
        if not isfinite(value): raise ValueError("extensions require finite JSON numbers")
        return value
    if isinstance(value, tuple): return tuple(_json(v) for v in value)
    if isinstance(value, list): return tuple(_json(v) for v in value)
    if isinstance(value, dict):
        return {str(k): _json(v) for k,v in value.items()}
    raise ValueError("extensions/details must be JSON-compatible")

def _extensions(value: dict[str, Any]) -> dict[str, Any]:
    out=_json(value)
    for key in out:
        if "." not in key or key in _RESERVED_EXTENSION_KEYS or key.split(".")[-1] in _RESERVED_EXTENSION_KEYS:
            raise ValueError(f"unsafe extension key: {key}")
    return out

def _details(value: dict[str, Any]) -> dict[str, Any]: return _json(value)

@dataclass(frozen=True, slots=True)
class PageDimensions:
    width: float; height: float; unit: str = "point"
    def __post_init__(self):
        _finite(self.width,"width"); _finite(self.height,"height")
        if self.width <= 0 or self.height <= 0: raise ValueError("dimensions must be positive")
@dataclass(frozen=True, slots=True)
class CoordinateFrame:
    origin: str = "top_left"; unit: str = "normalized"; rotation_applied: bool = True
@dataclass(frozen=True, slots=True)
class NormalizedBoundingBox:
    left: float; top: float; right: float; bottom: float
    def __post_init__(self):
        for n in ("left","top","right","bottom"): _finite(getattr(self,n),n)
        if not (0 <= self.left < self.right <= 1 and 0 <= self.top < self.bottom <= 1): raise ValueError("invalid normalized bbox")
@dataclass(frozen=True, slots=True)
class SourceTextSpan:
    start: int; end: int
    def __post_init__(self):
        _nonnegative_int(self.start,"start"); _nonnegative_int(self.end,"end")
        if self.start > self.end: raise ValueError("span start must not exceed end")
@dataclass(frozen=True, slots=True)
class SourceLocation:
    source_page_index: int; bounding_box: NormalizedBoundingBox | None = None; text_span: SourceTextSpan | None = None
    def __post_init__(self): _nonnegative_int(self.source_page_index,"source_page_index")

@dataclass(frozen=True, slots=True)
class HeadingAttributes:
    level:int; extensions:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self): object.__setattr__(self,'extensions',_extensions(self.extensions))
@dataclass(frozen=True, slots=True)
class ListAttributes:
    ordered:bool=False; marker_style:str|None=None; extensions:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self): object.__setattr__(self,'extensions',_extensions(self.extensions))
@dataclass(frozen=True, slots=True)
class ListItemAttributes:
    marker:str|None=None; ordinal:int|None=None; extensions:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self): object.__setattr__(self,'extensions',_extensions(self.extensions))
@dataclass(frozen=True, slots=True)
class TableCell:
    row_index:int; column_index:int; row_span:int=1; column_span:int=1; text:str|None=None; extensions:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self): object.__setattr__(self,'extensions',_extensions(self.extensions))
@dataclass(frozen=True, slots=True)
class TableStructure: row_count:int; column_count:int; cells:tuple[TableCell,...]=()
@dataclass(frozen=True, slots=True)
class TableAttributes:
    structure:TableStructure; rendered_asset_id:AssetId|None=None; extensions:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self): object.__setattr__(self,'extensions',_extensions(self.extensions))
@dataclass(frozen=True, slots=True)
class FigureAttributes:
    caption_node_id:ContentNodeId|None=None; rendered_asset_id:AssetId|None=None; extensions:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self): object.__setattr__(self,'extensions',_extensions(self.extensions))
@dataclass(frozen=True, slots=True)
class CaptionAttributes:
    target_node_id:ContentNodeId|None=None; target_asset_id:AssetId|None=None; extensions:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self): object.__setattr__(self,'extensions',_extensions(self.extensions))
@dataclass(frozen=True, slots=True)
class FormulaAttributes:
    notation:str|None=None; role:str|None=None; extensions:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self): object.__setattr__(self,'extensions',_extensions(self.extensions))

@dataclass(frozen=True, slots=True)
class ContentRecoverySummary:
    state: ContentRecoveryState; total_pages:int; complete_pages:int=0; partial_pages:int=0; degraded_pages:int=0; unavailable_pages:int=0; no_usable_semantic_content_pages:int=0; warning_ids:tuple[Any,...]=(); recovery_policy_ref:str|None=None
@dataclass(frozen=True, slots=True)
class ContentWarning:
    warning_id: str; code:str; severity:WarningSeverity; scope_path:str; safe_summary:str; evidence_ids:tuple[EvidenceReferenceId,...]=(); recoverable:bool=True; blocking_hint:str|None=None; details:dict[str,Any]=field(default_factory=dict); extensions:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self): object.__setattr__(self,'details',_details(self.details)); object.__setattr__(self,'extensions',_extensions(self.extensions))
@dataclass(frozen=True, slots=True)
class EvidenceReference:
    evidence_id:EvidenceReferenceId; kind:EvidenceKind; source_file_ref:SourceFileRef|None=None; source_page_index:int|None=None; source_location:SourceLocation|None=None; raw_result_ref:RawResultRef|None=None; structured_processing_result_ref:StructuredProcessingResultRef|None=None; spr_node_ref:str|None=None; spr_observation_ref:str|None=None; spr_evidence_ref:str|None=None; warning_ref:str|None=None; extensions:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self):
        if self.source_page_index is not None: _nonnegative_int(self.source_page_index,"source_page_index")
        object.__setattr__(self,'extensions',_extensions(self.extensions))
@dataclass(frozen=True, slots=True)
class AssetRenditionReference:
    rendition_id:AssetRenditionId; asset_id:AssetId; role:AssetRenditionRole; media_type:str|None=None; checksum:str|None=None; dimensions:PageDimensions|None=None; artifact_ref:str|None=None; recovery_state:AssetRecoveryState=AssetRecoveryState.AVAILABLE; rebuildable:bool=False; extensions:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self): object.__setattr__(self,'extensions',_extensions(self.extensions))
@dataclass(frozen=True, slots=True)
class AssetReference:
    asset_id:AssetId; role:AssetRole; recovery_state:AssetRecoveryState; source_location:SourceLocation|None=None; media_type:str|None=None; checksum:str|None=None; byte_size:int|None=None; dimensions:PageDimensions|None=None; rendition_refs:tuple[AssetRenditionId,...]=(); evidence_ids:tuple[EvidenceReferenceId,...]=(); caption:str|None=None; alt_text:str|None=None; description:str|None=None; extensions:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self):
        if self.byte_size is not None: _nonnegative_int(self.byte_size,"byte_size")
        object.__setattr__(self,'extensions',_extensions(self.extensions))
@dataclass(frozen=True, slots=True)
class ContentPage:
    page_id:ContentPageId; source_page_index:int; page_order:int; recovery_state:PageRecoveryState; root_node_ids:tuple[ContentNodeId,...]; page_label:str|None=None; dimensions:PageDimensions|None=None; rotation_degrees:float|None=None; coordinate_frame:CoordinateFrame|None=None; evidence_ids:tuple[EvidenceReferenceId,...]=(); warning_ids:tuple[Any,...]=(); extensions:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self):
        _nonnegative_int(self.source_page_index,"source_page_index"); _nonnegative_int(self.page_order,"page_order")
        if self.rotation_degrees is not None: _finite(self.rotation_degrees,"rotation_degrees")
        object.__setattr__(self,'extensions',_extensions(self.extensions))
@dataclass(frozen=True, slots=True)
class ContentNode:
    node_id:ContentNodeId; lineage_key:ContentLineageKey; node_type:ContentNodeType; page_id:ContentPageId; sibling_order:int; recovery_state:NodeRecoveryState; parent_id:ContentNodeId|None=None; text:str|None=None; attributes:Any|None=None; source_locations:tuple[SourceLocation,...]=(); evidence_ids:tuple[EvidenceReferenceId,...]=(); asset_ids:tuple[AssetId,...]=(); warning_ids:tuple[Any,...]=(); extensions:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self): _nonnegative_int(self.sibling_order,"sibling_order"); object.__setattr__(self,'extensions',_extensions(self.extensions))
@dataclass(frozen=True, slots=True)
class StructuredContentCandidate:
    schema_id:str; schema_version:int; document_ref:DocumentRef; candidate_id:ContentCandidateId; lineage_key:ContentLineageKey; recovery_summary:ContentRecoverySummary; pages:tuple[ContentPage,...]; nodes:tuple[ContentNode,...]; evidence:tuple[EvidenceReference,...]; assets:tuple[AssetReference,...]; warnings:tuple[ContentWarning,...]; extensions:dict[str,Any]; transformer_ref:TransformerRef|None=None; transformation_policy_ref:TransformationPolicyRef|None=None; processing_run_ref:ProcessingRunRef|None=None; raw_result_ref:RawResultRef|None=None; structured_processing_result_ref:StructuredProcessingResultRef|None=None; renditions:tuple[AssetRenditionReference,...]=()
    def __post_init__(self): object.__setattr__(self,'extensions',_extensions(self.extensions))
