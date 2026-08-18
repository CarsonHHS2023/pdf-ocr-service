from __future__ import annotations
import json, unicodedata
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any
from .identity import _StringRef
from .model import StructuredContentCandidate

def _nfc(value: Any) -> Any:
    if isinstance(value, str): return unicodedata.normalize("NFC", value)
    if isinstance(value, tuple): return [_nfc(v) for v in value]
    if isinstance(value, list): return [_nfc(v) for v in value]
    if isinstance(value, dict): return {unicodedata.normalize("NFC", str(k)): _nfc(v) for k,v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    return value

def _as_json(value: Any) -> Any:
    if value is None: return None
    if isinstance(value, _StringRef): return value.value
    if isinstance(value, Enum): return value.value
    if isinstance(value, tuple): return [_as_json(v) for v in value]
    if isinstance(value, list): return [_as_json(v) for v in value]
    if isinstance(value, dict): return {str(k): _as_json(v) for k,v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if is_dataclass(value):
        out={}
        for f in fields(value):
            item=_as_json(getattr(value, f.name))
            if item is None: continue
            if item == [] and f.default == (): continue
            if item == {} and getattr(f.default_factory, '__name__', '') == 'dict': continue
            out[f.name]=item
        return out
    return value

def to_canonical_dict(candidate: StructuredContentCandidate) -> dict[str, Any]:
    data=_as_json(candidate)
    data["pages"]=[_as_json(p) for p in candidate.pages]
    data["nodes"]=[_as_json(n) for n in sorted(candidate.nodes, key=lambda n: n.node_id.value)]
    data["evidence"]=[_as_json(e) for e in sorted(candidate.evidence, key=lambda e: e.evidence_id.value)]
    data["assets"]=[_as_json(a) for a in sorted(candidate.assets, key=lambda a: a.asset_id.value)]
    if candidate.renditions:
        data["renditions"]=[_as_json(r) for r in sorted(candidate.renditions, key=lambda r: r.rendition_id.value)]
    data["warnings"]=[_as_json(w) for w in sorted(candidate.warnings, key=lambda w: w.warning_id)]
    return _nfc(data)

def serialize_structured_content_candidate(candidate: StructuredContentCandidate) -> bytes:
    return json.dumps(to_canonical_dict(candidate), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
