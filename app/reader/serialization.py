from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import TypeAlias

from app.structured_content.identity import _StringRef

from .contracts import ReaderContentChunk, ReaderContinuation, ReaderDocumentView, ReaderLocation

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


def _value(value: object) -> JsonValue:
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, _StringRef):
        return value.value
    if isinstance(value, tuple):
        return [_value(item) for item in value]
    if is_dataclass(value):
        return {field.name: _value(getattr(value, field.name)) for field in fields(value)}
    raise TypeError("unsupported Reader contract value")


def to_reader_contract_dict(value: ReaderDocumentView | ReaderContentChunk | ReaderContinuation | ReaderLocation) -> dict[str, JsonValue]:
    result = _value(value)
    if not isinstance(result, dict):
        raise TypeError("expected Reader contract")
    return result


def serialize_reader_contract(value: ReaderDocumentView | ReaderContentChunk | ReaderContinuation | ReaderLocation) -> bytes:
    return json.dumps(to_reader_contract_dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
