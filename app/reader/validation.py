from __future__ import annotations

from app.structured_content.enums import ContentNodeType
from app.structured_content.identity import AssetId, ContentCandidateId, ContentNodeId, ContentPageId, DocumentRef

from .contracts import (
    SUPPORTED_READER_APPLICATION_CONTRACT_VERSIONS,
    ReaderContentChunk,
    ReaderContentState,
    ReaderContinuation,
    ReaderDocumentMetadata,
    ReaderDocumentView,
    ReaderLocation,
    ReaderNavigationEntry,
    ReaderNavigationKind,
    ReaderNodeView,
    ReaderPageView,
    ReaderProcessingState,
    ReaderWarning,
    ReaderWarningCode,
)
from .errors import ReaderContractError, ReaderContractErrorCode, UnsupportedReaderContractVersion


_NON_CONTENT_BEARING_STATES = frozenset(
    {ReaderContentState.NO_USABLE_SEMANTIC_CONTENT, ReaderContentState.UNAVAILABLE}
)


def _fail(code: ReaderContractErrorCode, reason: str) -> None:
    raise ReaderContractError(code, reason)


def _version(version: object) -> None:
    if not isinstance(version, str) or version not in SUPPORTED_READER_APPLICATION_CONTRACT_VERSIONS:
        raise UnsupportedReaderContractVersion()


def _schema(schema_id: object, schema_version: object, code: ReaderContractErrorCode) -> None:
    if not isinstance(schema_id, str) or not schema_id.strip():
        _fail(code, "candidate schema id must be nonempty")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version < 1:
        _fail(code, "candidate schema version must be positive")


def validate_reader_location(location: ReaderLocation) -> None:
    if not isinstance(location, ReaderLocation):
        _fail(ReaderContractErrorCode.INVALID_LOCATION, "expected ReaderLocation")
    _version(location.contract_version)
    if not isinstance(location.document_ref, DocumentRef) or not isinstance(location.candidate_id, ContentCandidateId):
        _fail(ReaderContractErrorCode.INVALID_LOCATION, "document and candidate identities are required")
    if location.page_id is not None and not isinstance(location.page_id, ContentPageId):
        _fail(ReaderContractErrorCode.INVALID_LOCATION, "page identity must be ContentPageId")
    if location.node_id is not None and not isinstance(location.node_id, ContentNodeId):
        _fail(ReaderContractErrorCode.INVALID_LOCATION, "node identity must be ContentNodeId")
    _schema(location.candidate_schema_id, location.candidate_schema_version, ReaderContractErrorCode.INVALID_LOCATION)
    if location.node_id is not None and location.page_id is None:
        _fail(ReaderContractErrorCode.INVALID_LOCATION, "node requires page")
    if location.segment_index is not None:
        if location.node_id is None:
            _fail(ReaderContractErrorCode.INVALID_LOCATION, "segment requires node")
        if not isinstance(location.segment_index, int) or isinstance(location.segment_index, bool) or location.segment_index < 0:
            _fail(ReaderContractErrorCode.INVALID_LOCATION, "segment index must be nonnegative")


def _same_source(container: object, location: ReaderLocation, code: ReaderContractErrorCode) -> None:
    validate_reader_location(location)
    fields = ("document_ref", "candidate_id", "candidate_schema_id", "candidate_schema_version", "contract_version")
    if any(getattr(container, field) != getattr(location, field) for field in fields):
        _fail(code, "location source identity mismatch")


def _validate_warnings(warnings: tuple[ReaderWarning, ...], code: ReaderContractErrorCode) -> None:
    if not isinstance(warnings, tuple):
        _fail(code, "warnings must be an immutable tuple")
    for warning in warnings:
        if not isinstance(warning, ReaderWarning) or not isinstance(warning.code, ReaderWarningCode):
            _fail(code, "warning must use a supported warning code")


def validate_reader_node(node: ReaderNodeView, page: ReaderPageView | None = None) -> None:
    code = ReaderContractErrorCode.INVALID_NODE
    if not isinstance(node, ReaderNodeView):
        _fail(code, "expected ReaderNodeView")
    validate_reader_location(node.location)
    if not isinstance(node.node_type, ContentNodeType):
        _fail(code, "node type must be ContentNodeType")
    if not isinstance(node.content_state, ReaderContentState):
        _fail(code, "node content state must be ReaderContentState")
    if not isinstance(node.node_id, ContentNodeId):
        _fail(code, "node identity must be ContentNodeId")
    if node.text is not None and not isinstance(node.text, str):
        _fail(code, "node text must be a string")
    if node.parent_ref is not None and not isinstance(node.parent_ref, ContentNodeId):
        _fail(code, "parent reference must be ContentNodeId")
    if not isinstance(node.child_refs, tuple) or any(not isinstance(ref, ContentNodeId) for ref in node.child_refs):
        _fail(code, "child references must be an immutable tuple of ContentNodeId")
    if not isinstance(node.asset_refs, tuple) or any(not isinstance(ref, AssetId) for ref in node.asset_refs):
        _fail(code, "asset references must be an immutable tuple of AssetId")
    if node.location.node_id != node.node_id:
        _fail(code, "node identity mismatch")
    if node.location.segment_index is not None:
        _fail(code, "node location must not be segment-scoped")
    if page is not None:
        if not isinstance(page, ReaderPageView):
            _fail(code, "page context must be ReaderPageView")
        validate_reader_location(page.location)
        if node.location.page_id != page.page_id:
            _fail(code, "node page identity mismatch")
        _same_source(page.location, node.location, code)
    if not isinstance(node.order, int) or isinstance(node.order, bool) or node.order < 0:
        _fail(code, "node order must be nonnegative")
    if node.node_type is ContentNodeType.HEADING:
        if (
            not isinstance(node.heading_level, int)
            or isinstance(node.heading_level, bool)
            or not 1 <= node.heading_level <= 6
        ):
            _fail(code, "heading node requires level between 1 and 6")
    elif node.heading_level is not None:
        _fail(code, "non-heading node must not have heading level")
    if node.parent_ref == node.node_id:
        _fail(code, "node must not reference itself as parent")
    if len(set(node.child_refs)) != len(node.child_refs) or node.node_id in node.child_refs:
        _fail(code, "invalid child references")
    _validate_warnings(node.warnings, code)


def validate_reader_page(page: ReaderPageView) -> None:
    code = ReaderContractErrorCode.INVALID_PAGE
    if not isinstance(page, ReaderPageView):
        _fail(code, "expected ReaderPageView")
    validate_reader_location(page.location)
    if not isinstance(page.content_state, ReaderContentState):
        _fail(code, "page content state must be ReaderContentState")
    if not isinstance(page.nodes, tuple):
        _fail(code, "nodes must be an immutable tuple")
    if page.content_state in _NON_CONTENT_BEARING_STATES and page.nodes:
        _fail(code, "non-content-bearing page must not contain nodes")
    if page.location.page_id != page.page_id or page.location.node_id is not None:
        _fail(code, "page location identity mismatch")
    if not isinstance(page.page_order, int) or isinstance(page.page_order, bool) or page.page_order < 0:
        _fail(code, "page order must be nonnegative")
    # Validate every member before page-level code dereferences node fields.
    for node in page.nodes:
        validate_reader_node(node, page)
    ids = [node.node_id for node in page.nodes]
    orders = [node.order for node in page.nodes]
    if len(set(ids)) != len(ids) or orders != list(range(len(orders))):
        _fail(code, "node identities must be unique and order contiguous")
    for node in page.nodes:
        if node.location.document_ref != page.location.document_ref or node.location.candidate_id != page.location.candidate_id:
            _fail(code, "node source identity mismatch")
        if node.location.candidate_schema_id != page.location.candidate_schema_id or node.location.candidate_schema_version != page.location.candidate_schema_version or node.location.contract_version != page.location.contract_version:
            _fail(code, "node version identity mismatch")
    node_ids = set(ids)
    nodes_by_id = {node.node_id: node for node in page.nodes}
    for node in page.nodes:
        if node.parent_ref is not None and node.parent_ref not in node_ids:
            _fail(code, "unknown parent reference")
        if any(child not in node_ids for child in node.child_refs):
            _fail(code, "unknown child reference")
        if node.parent_ref == node.node_id:
            _fail(code, "node hierarchy contains self-parent")
        if node.parent_ref is not None and node.node_id not in nodes_by_id[node.parent_ref].child_refs:
            _fail(code, "parent/child relationship mismatch")
        for child_id in node.child_refs:
            if nodes_by_id[child_id].parent_ref != node.node_id:
                _fail(code, "parent/child relationship mismatch")

    # Walk parent chains iteratively so malformed input cannot exhaust recursion.
    completed: set[ContentNodeId] = set()
    for node in page.nodes:
        active: set[ContentNodeId] = set()
        current = node
        while current.node_id not in completed:
            if current.node_id in active:
                _fail(code, "node hierarchy contains cycle")
            active.add(current.node_id)
            if current.parent_ref is None:
                break
            current = nodes_by_id[current.parent_ref]
        completed.update(active)
    _validate_warnings(page.warnings, code)


def validate_navigation_entry(entry: ReaderNavigationEntry) -> None:
    if not isinstance(entry, ReaderNavigationEntry):
        _fail(ReaderContractErrorCode.INVALID_NAVIGATION, "expected ReaderNavigationEntry")
    validate_reader_location(entry.location)
    if not isinstance(entry.kind, ReaderNavigationKind):
        _fail(ReaderContractErrorCode.INVALID_NAVIGATION, "navigation kind must be supported")
    if entry.kind is ReaderNavigationKind.HEADING and entry.location.segment_index is not None:
        _fail(ReaderContractErrorCode.INVALID_NAVIGATION, "heading navigation must not be segment-scoped")
    if not isinstance(entry.label, str) or not entry.label.strip() or entry.location.node_id is None:
        _fail(ReaderContractErrorCode.INVALID_NAVIGATION, "navigation requires label and node location")
    if not isinstance(entry.order, int) or isinstance(entry.order, bool) or entry.order < 0:
        _fail(ReaderContractErrorCode.INVALID_NAVIGATION, "navigation order must be nonnegative")
    if not isinstance(entry.heading_level, int) or isinstance(entry.heading_level, bool) or not 1 <= entry.heading_level <= 6:
        _fail(ReaderContractErrorCode.INVALID_NAVIGATION, "heading level must be between 1 and 6")


def validate_reader_document(document: ReaderDocumentView) -> None:
    code = ReaderContractErrorCode.INVALID_DOCUMENT
    if not isinstance(document, ReaderDocumentView):
        _fail(code, "expected ReaderDocumentView")
    _version(document.contract_version)
    if not isinstance(document.document_ref, DocumentRef) or not isinstance(document.candidate_id, ContentCandidateId):
        _fail(code, "document and candidate identities are required")
    if not isinstance(document.processing_state, ReaderProcessingState):
        _fail(code, "processing state must be ReaderProcessingState")
    if not isinstance(document.content_state, ReaderContentState):
        _fail(code, "content state must be ReaderContentState")
    _schema(document.candidate_schema_id, document.candidate_schema_version, code)
    if not isinstance(document.metadata, ReaderDocumentMetadata):
        _fail(code, "metadata must be ReaderDocumentMetadata")
    if not isinstance(document.pages, tuple):
        _fail(code, "pages must be an immutable tuple")
    if not isinstance(document.navigation, tuple):
        _fail(code, "navigation must be an immutable tuple")
    if not isinstance(document.metadata.page_count, int) or isinstance(document.metadata.page_count, bool) or document.metadata.page_count < 0:
        _fail(code, "metadata page count must be nonnegative")
    if document.metadata.title is not None and not isinstance(document.metadata.title, str):
        _fail(code, "metadata title must be a string")
    if document.metadata.page_count == 0 and document.navigation:
        _fail(ReaderContractErrorCode.INVALID_NAVIGATION, "zero-page document must not contain navigation")
    # Validate every member before document-level code dereferences page fields.
    for page in document.pages:
        validate_reader_page(page)
    if (
        document.content_state in _NON_CONTENT_BEARING_STATES
        and any(page.nodes for page in document.pages)
    ):
        _fail(code, "non-content-bearing document must not contain embedded nodes")
    page_ids = [page.page_id for page in document.pages]
    page_orders = [page.page_order for page in document.pages]
    if len(set(page_ids)) != len(page_ids) or page_orders != sorted(set(page_orders)):
        _fail(code, "embedded page identities and orders must be unique and increasing")
    if any(page_order >= document.metadata.page_count for page_order in page_orders):
        _fail(code, "embedded page order exceeds document page count")
    node_ids: list[object] = []
    nodes_by_page: dict[ContentPageId, dict[ContentNodeId, ReaderNodeView]] = {}
    for page in document.pages:
        _same_source(document, page.location, code)
        node_ids.extend(node.node_id for node in page.nodes)
        nodes_by_page[page.page_id] = {node.node_id: node for node in page.nodes}
    if len(set(node_ids)) != len(node_ids):
        _fail(code, "node identities must be document-unique")
    nav_keys: list[tuple[object, object]] = []
    for index, entry in enumerate(document.navigation):
        validate_navigation_entry(entry)
        _same_source(document, entry.location, ReaderContractErrorCode.INVALID_NAVIGATION)
        page_nodes = nodes_by_page.get(entry.location.page_id) if entry.location.page_id is not None else None
        if entry.order != index:
            _fail(ReaderContractErrorCode.INVALID_NAVIGATION, "navigation order invalid")
        if page_nodes is not None:
            target_node = page_nodes.get(entry.location.node_id)
            if target_node is None:
                _fail(ReaderContractErrorCode.INVALID_NAVIGATION, "navigation target invalid on embedded page")
            if target_node.node_type is not ContentNodeType.HEADING or target_node.heading_level is None:
                _fail(ReaderContractErrorCode.INVALID_NAVIGATION, "navigation target must be a heading")
            if entry.heading_level != target_node.heading_level:
                _fail(ReaderContractErrorCode.INVALID_NAVIGATION, "navigation heading level mismatch")
        nav_keys.append((entry.location.page_id, entry.location.node_id))
    if len(set(nav_keys)) != len(nav_keys):
        _fail(ReaderContractErrorCode.INVALID_NAVIGATION, "duplicate navigation target")
    _validate_warnings(document.warnings, code)


def validate_reader_content_chunk(chunk: ReaderContentChunk) -> None:
    code = ReaderContractErrorCode.INVALID_CHUNK
    if not isinstance(chunk, ReaderContentChunk):
        _fail(code, "expected ReaderContentChunk")
    _version(chunk.contract_version)
    if not isinstance(chunk.document_ref, DocumentRef) or not isinstance(chunk.candidate_id, ContentCandidateId):
        _fail(code, "document and candidate identities are required")
    if not isinstance(chunk.has_more, bool):
        _fail(code, "has_more must be boolean")
    _schema(chunk.candidate_schema_id, chunk.candidate_schema_version, code)
    if not isinstance(chunk.pages, tuple):
        _fail(code, "pages must be an immutable tuple")
    # Chunks share the same page-member trust boundary as full documents.
    for page in chunk.pages:
        validate_reader_page(page)
    orders = [page.page_order for page in chunk.pages]
    if orders != sorted(orders) or len(set(orders)) != len(orders):
        _fail(code, "chunk page order must be unique and increasing")
    page_ids: list[ContentPageId] = []
    node_ids: list[ContentNodeId] = []
    for page in chunk.pages:
        _same_source(chunk, page.location, code)
        page_ids.append(page.page_id)
        node_ids.extend(node.node_id for node in page.nodes)
    if len(set(page_ids)) != len(page_ids):
        _fail(code, "chunk page identities must be unique")
    if len(set(node_ids)) != len(node_ids):
        _fail(code, "chunk node identities must be document-unique")
    if chunk.continuation is not None:
        if not isinstance(chunk.continuation, ReaderContinuation):
            _fail(code, "continuation must be ReaderContinuation")
        if not isinstance(chunk.continuation.page_order, int) or isinstance(chunk.continuation.page_order, bool) or chunk.continuation.page_order < 0:
            _fail(code, "continuation page order must be nonnegative")
        _same_source(chunk, chunk.continuation.location, code)
        if chunk.has_more is False:
            _fail(code, "continuation requires has_more")
        if chunk.continuation.location.page_id is None:
            _fail(code, "continuation must identify page progress")
        # Chunks contain complete pages, so continuing into a returned page
        # would repeat content rather than advance the bounded delivery range.
        if chunk.continuation.location.page_id in set(page_ids):
            _fail(code, "continuation must advance beyond returned pages")
        if orders and chunk.continuation.page_order <= orders[-1]:
            _fail(code, "continuation page order must follow returned pages")
    elif chunk.has_more is True:
        _fail(code, "has_more requires continuation")
