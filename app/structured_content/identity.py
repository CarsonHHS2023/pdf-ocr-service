from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class _StringRef:
    value: str
    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError(f"{type(self).__name__} requires a nonempty string")
    def __str__(self) -> str: return self.value

class DocumentRef(_StringRef): pass
class SourceFileRef(_StringRef): pass
class ContentCandidateId(_StringRef): pass
class ContentPageId(_StringRef): pass
class ContentNodeId(_StringRef): pass
class ContentLineageKey(_StringRef): pass
class EvidenceReferenceId(_StringRef): pass
class AssetId(_StringRef): pass
class AssetRenditionId(_StringRef): pass
class StructuredProcessingResultRef(_StringRef): pass
class RawResultRef(_StringRef): pass
class ProcessingRunRef(_StringRef): pass
class TransformerRef(_StringRef): pass
class TransformationPolicyRef(_StringRef): pass

__all__ = ["DocumentRef","SourceFileRef","ContentCandidateId","ContentPageId","ContentNodeId","ContentLineageKey","EvidenceReferenceId","AssetId","AssetRenditionId","StructuredProcessingResultRef","RawResultRef","ProcessingRunRef","TransformerRef","TransformationPolicyRef"]
