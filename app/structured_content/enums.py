from __future__ import annotations
from enum import Enum
class ContentNodeType(str, Enum):
    SECTION="section"; HEADING="heading"; PARAGRAPH="paragraph"; LIST="list"; LIST_ITEM="list_item"; TABLE="table"; FIGURE="figure"; CAPTION="caption"; FORMULA="formula"; HEADER="header"; FOOTER="footer"; FOOTNOTE="footnote"; UNKNOWN="unknown"
class ContentRecoveryState(str, Enum):
    COMPLETE="complete"; PARTIAL="partial"; DEGRADED="degraded"; UNAVAILABLE="unavailable"
class PageRecoveryState(str, Enum):
    COMPLETE="complete"; PARTIAL="partial"; DEGRADED="degraded"; NO_USABLE_SEMANTIC_CONTENT="no_usable_semantic_content"; UNAVAILABLE="unavailable"; UNSUPPORTED="unsupported"
class NodeRecoveryState(str, Enum):
    COMPLETE="complete"; PARTIAL="partial"; DEGRADED="degraded"; UNSUPPORTED="unsupported"; RECOVERED="recovered"
class AssetRecoveryState(str, Enum):
    AVAILABLE="available"; MISSING="missing"; DEGRADED="degraded"; UNAVAILABLE="unavailable"; REBUILDABLE="rebuildable"
class EvidenceKind(str, Enum):
    SOURCE_LOCATION="source_location"; RAW_RESULT="raw_result"; STRUCTURED_PROCESSING_RESULT="structured_processing_result"; WARNING="warning"
class AssetRole(str, Enum):
    FIGURE="figure"; TABLE_RENDERING="table_rendering"; PAGE_RENDERING="page_rendering"; FORMULA_RENDERING="formula_rendering"
class AssetRenditionRole(str, Enum):
    ORIGINAL="original"; NORMALIZED="normalized"; THUMBNAIL="thumbnail"; OCR_SOURCE="ocr_source"
class WarningSeverity(str, Enum):
    INFO="info"; WARNING="warning"; ERROR="error"
__all__=[name for name in list(globals()) if name.endswith('State') or name in {'ContentNodeType','EvidenceKind','AssetRole','AssetRenditionRole','WarningSeverity'}]
