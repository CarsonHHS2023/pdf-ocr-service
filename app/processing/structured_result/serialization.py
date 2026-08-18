"""Deterministic JSON serialization for SPR v1."""
from __future__ import annotations
import json, unicodedata
from .models import StructuredProcessingResult

def _nfc(value):
    if isinstance(value, str): return unicodedata.normalize("NFC", value)
    if isinstance(value, list): return [_nfc(v) for v in value]
    if isinstance(value, dict): return {k: _nfc(v) for k, v in value.items()}
    return value

def serialize_structured_processing_result(result: StructuredProcessingResult) -> bytes:
    return json.dumps(_nfc(result.to_dict()), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
