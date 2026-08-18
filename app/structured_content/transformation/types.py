from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from app.structured_content.identity import (
    ContentCandidateId,
    ContentLineageKey,
    DocumentRef,
    ProcessingRunRef,
    SourceFileRef,
)

SUPPORTED_SPR_SCHEMA_VERSION = 1
SUPPORTED_TRANSFORMATION_POLICY_VERSION = 1
SUPPORTED_MAPPING_VERSION = 1


def _nonempty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} requires a nonempty string")
    return value


@dataclass(frozen=True, slots=True)
class CandidateIdentityInput:
    candidate_id: str
    candidate_lineage_seed: str

    def __post_init__(self) -> None:
        _nonempty(self.candidate_id, "candidate_id")
        _nonempty(self.candidate_lineage_seed, "candidate_lineage_seed")
        ContentCandidateId(self.candidate_id)
        ContentLineageKey(self.candidate_lineage_seed)


@dataclass(frozen=True, slots=True)
class TransformationContext:
    document_ref: str
    identity: CandidateIdentityInput
    processing_run_ref: str | None = None
    source_file_ref: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.document_ref, "document_ref")
        DocumentRef(self.document_ref)
        if not isinstance(self.identity, CandidateIdentityInput):
            raise ValueError("identity must be CandidateIdentityInput")
        if self.processing_run_ref is not None:
            _nonempty(self.processing_run_ref, "processing_run_ref")
            ProcessingRunRef(self.processing_run_ref)
        if self.source_file_ref is not None:
            _nonempty(self.source_file_ref, "source_file_ref")
            SourceFileRef(self.source_file_ref)

    @property
    def candidate_id(self) -> str:
        return self.identity.candidate_id

    @property
    def candidate_lineage_seed(self) -> str:
        return self.identity.candidate_lineage_seed


class UnknownNodePolicy(str, Enum):
    PRESERVE = "preserve"


class TextNormalizationPolicy(str, Enum):
    PRESERVE_SPR_TEXT = "preserve_spr_text"


class GeometryPolicy(str, Enum):
    PRESERVE_SPR_GEOMETRY = "preserve_spr_geometry"


@dataclass(frozen=True, slots=True)
class TransformationPolicy:
    spr_schema_version: int = SUPPORTED_SPR_SCHEMA_VERSION
    transformation_policy_version: int = SUPPORTED_TRANSFORMATION_POLICY_VERSION
    mapping_version: int = SUPPORTED_MAPPING_VERSION
    unknown_node_policy: UnknownNodePolicy = UnknownNodePolicy.PRESERVE
    text_normalization_policy: TextNormalizationPolicy = TextNormalizationPolicy.PRESERVE_SPR_TEXT
    geometry_policy: GeometryPolicy = GeometryPolicy.PRESERVE_SPR_GEOMETRY
    extensions: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "unknown_node_policy", UnknownNodePolicy(self.unknown_node_policy))
        object.__setattr__(self, "text_normalization_policy", TextNormalizationPolicy(self.text_normalization_policy))
        object.__setattr__(self, "geometry_policy", GeometryPolicy(self.geometry_policy))
        object.__setattr__(self, "extensions", MappingProxyType(dict(self.extensions)))


DEFAULT_TRANSFORMATION_POLICY = TransformationPolicy()
