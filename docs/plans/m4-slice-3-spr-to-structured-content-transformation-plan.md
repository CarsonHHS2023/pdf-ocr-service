# M4 Slice 3 SPR to Structured Content Transformation Plan

| Field | Value |
|---|---|
| Title | M4 Slice 3 SPR to Structured Content Transformation Plan |
| Document Type | Implementation Plan |
| Status | Proposed |
| Plan Type | M4 implementation plan |
| Milestone | M4 |
| Milestone Status | Unchanged — M4 remains In Progress |
| M5 Status | Unchanged — M5 remains Planned |
| Scope | Planning only for deterministic SPR → Structured Content candidate transformation |
| Effective Date | 2026-07-23 |
| Implementation Authorized | No |
| Transformer Implemented | No |
| Reader Cutover Authorized | No |
| Production Release Authorized | No |
| Baseline | PR #133 merge commit `864be384738e4dcf1d5afab955051d44282e398d` |

This plan is documentation and planning only. It does not implement a transformer, alter runtime models, modify persistence, change selection, alter `ProcessingRun` behavior, authorize Reader cutover, mark M4 complete, begin M5, or make a production-readiness claim. Accepted ADRs remain authoritative where this plan summarizes them.

## 1. Status, Scope, and Planning Basis

### 1.1 Status

Status is **Proposed**. Merge of this document records an implementation plan only. It does not authorize implementation. M4 remains In Progress. M5 remains Planned.

### 1.2 Scope

The planned future work is a deterministic transformation from one validated Structured Processing Result (SPR) v1 into one validated in-memory `StructuredContentCandidate`. The transformation is provider-independent, side-effect free, persistence free, selection free, API free, orchestration free, and Reader free.

### 1.3 Planning basis

The repository baseline contains:

- SPR v1 runtime model, validation, and deterministic serialization in `app/processing/structured_result/`.
- Paddle-VL Raw Processing Result → SPR v1 normalization in `app/processing/paddle_vl/normalizer.py`.
- Structured Content v1 in-memory dataclasses, bounded enums, identity refs, canonical serializer, validator, persistence mapping, candidate repository, selection repository/service, and ProcessingRun provenance integration.
- Structured Content golden, invalid, regression, scale, repository, selection, and provenance tests.
- Governance and roadmap documents preserving orthogonal document, milestone, implementation, review, and test statuses.

## 2. Authoritative Sources Reviewed

Authoritative or directly relevant sources reviewed for this plan:

- `docs/project/document-governance.md`
- `docs/roadmap/roadmap.md`
- `docs/roadmap/roadmap-v3-decision.md`
- `docs/milestones/README.md`
- `docs/milestones/M4.md`
- `docs/milestones/M5.md`
- `docs/architecture/README.md`
- `docs/contracts/README.md`
- `docs/contracts/structured-processing-result-v1.md`
- `docs/architecture/adr/ADR-002-structured-content-lifecycle-and-selection.md`
- `docs/architecture/adr/ADR-003-structured-content-shape-and-transformation.md`
- `docs/architecture/adr/ADR-004-provenance-evidence-assets-and-processing-runs.md`
- `docs/architecture/adr/ADR-005-projection-compatibility-migration-and-retention.md`
- `docs/plans/m4-slice-2-structured-content-persistence-plan.md`
- `docs/reviews/m4-slice-2-completion-review.md`
- `app/processing/structured_result/models.py`
- `app/processing/structured_result/validation.py`
- `app/processing/structured_result/serialization.py`
- `app/processing/paddle_vl/normalizer.py`
- `app/processing_runs/types.py`
- `app/processing_runs/repository.py`
- `app/structured_content/model.py`
- `app/structured_content/enums.py`
- `app/structured_content/identity.py`
- `app/structured_content/serialization.py`
- `app/structured_content/validation.py`
- `app/structured_content/persistence_mapping.py`
- `app/structured_content/repository.py`
- `app/structured_content/selection_repository.py`
- `app/structured_content/selection_service.py`
- Structured Content fixtures under `tests/fixtures/structured_content/v1/`
- SPR and Paddle-VL normalization tests including `tests/test_structured_processing_result_v1_fixtures.py` and `tests/test_paddle_vl_structured_result_normalizer.py`

## 3. Implementation Prerequisites

Before implementation begins:

1. This plan must be reviewed and accepted as planning evidence.
2. No blocking open decision in Section 31 may remain unresolved.
3. The exact SPR v1 contract in Section 6 must remain current or be amended by a separate planning update.
4. Future Slice 3A must add only contracts/context/errors/function boundary unless separately authorized.
5. No schema migration is assumed by this plan.
6. The transformer implementation must use the existing Structured Content validator rather than duplicating it.

## 4. Transformation Boundary

The planned pure boundary is equivalent to:

```python
transform_spr_to_candidate(
    spr,
    *,
    document_ref,
    candidate_identity_input,
    processing_run_ref=None,
    transformation_policy,
) -> StructuredContentCandidate
```

Exact API names and type shapes are implementation details for Slice 3A. Required boundary properties:

| Property | Rule |
|---|---|
| Input | One already validated SPR v1 plus explicit document, identity, provenance, and policy context. |
| Output | One in-memory `StructuredContentCandidate` or one bounded transformation failure. |
| Side effects | None. No database session, commit, network call, provider call, file fetch, OCR call, queue action, or Reader call. |
| Persistence | Not performed. Candidate repository persistence is caller responsibility. |
| Selection | Not performed. Selection/promotion is a separate explicit operation. |
| ProcessingRun | `processing_run_ref` may be copied if supplied; no lookup, creation, or state transition occurs. |
| Mutability | SPR input is not mutated. Structured Content output is immutable dataclass state. |
| Validation | SPR validation precedes entry; Structured Content validation runs before returning a candidate. |

## 5. Output Contract

The output is one `StructuredContentCandidate` with:

- `schema_id = atlas.structured-content-candidate` and `schema_version = 1`.
- One caller-scoped `document_ref`.
- One caller-supplied or caller-derived `candidate_id` represented as `ContentCandidateId`.
- A deterministic candidate `lineage_key`.
- Immutable `ContentPage` rows ordered by `page_order`.
- Immutable `ContentNode` rows using the bounded `ContentNodeType` vocabulary.
- Ordered page roots and deterministic sibling order.
- Existing typed attributes only: heading, list, list item, table, figure, caption, and formula attributes.
- Evidence anchors using locator references, not copied provider payloads.
- Content warnings using safe deterministic messages.
- Recovery summary and page/node/asset recovery states derived from transformation rules.
- Logical assets and optional renditions when durable or logical references are present.
- Table structures using current `TableStructure` and `TableCell` model.
- Optional `processing_run_ref`, `raw_result_ref`, and `structured_processing_result_ref` copied from explicit context and SPR references.

The output must pass `validate_content_candidate`, be canonically serializable through the existing serializer, be suitable for candidate repository persistence, and contain no selected/current status, provider payload copy, Reader projection, or application presentation stream.

## 6. Exact Supported SPR v1 Input Contract

The accepted input is the current validated JSON-shaped `StructuredProcessingResult.data` contract. The transformer must reject structurally invalid SPR and must not repair arbitrary malformed provider payloads.

### 6.1 Top-level SPR fields

| Field | Status for transformer | Current contract and mapping rule |
|---|---|---|
| `schema_id` | Required | Must equal `atlas.structured-processing-result`; otherwise hard error. |
| `schema_version` | Required | Must equal `1`; future versions hard error until explicitly supported. |
| `result_id` | Required for production lineage/evidence | Becomes `structured_processing_result_ref` or evidence locator input when present and valid. |
| `processing_run_id` | Optional/preserved | May seed default `processing_run_ref` only if caller policy allows; explicit context wins. |
| `document_id` | Required consistency input | Must match or be reconcilable with caller `document_ref`; mismatch is hard transformation-context error. |
| `source_file_id` | Optional/preserved | Maps to `SourceFileRef` evidence/candidate source reference when nonempty. |
| `created_at` | Preserved as extension only if needed | Not canonical candidate identity by itself unless policy includes it. |
| `state` | Required | Current validator accepts `complete`, `partial`, `invalid`; transformer supports `complete` and recoverable `partial`, and treats `invalid` as untransformable unless future policy explicitly permits no-usable candidates from invalid SPR. |
| `source.checksum_sha256` | Preserved evidence/lineage | May be included in evidence extensions with safe namespaced key or lineage input; not a payload copy. |
| `raw_result.raw_result_id` | Preserved evidence/lineage | Maps to candidate `raw_result_ref` when available. |
| `raw_result.storage_reference` | Preserved as evidence locator only | Must not be dereferenced; credentials or signed URLs are disallowed. |
| `raw_result.payload_checksum_sha256` | Preserved evidence/lineage | Safe checksum metadata; no payload copy. |
| `raw_result.schema_revision` | Preserved evidence/lineage | Version locator metadata. |
| `provenance.provider_name` | Preserved extension/evidence | Provider identity is evidence, not Structured Content semantics. |
| `provenance.normalizer_*` | Preserved extension/lineage | Normalizer identity and configuration hash may affect lineage. |
| `pages` | Required collection | Maps to `ContentPage` objects. |
| `normalized_observations` | Required collection | Supplies accepted observations, content, geometry, confidence, and evidence links. |
| `nodes` | Required collection | Supplies provider-independent semantic nodes and hierarchy. |
| `evidence_links` | Required collection | Maps to `EvidenceReference`; target must be observation. |
| `assets` | Optional collection | Current normalizer emits empty list; future populated entries are mapped only when safe durable references exist. |
| `warnings` | Optional collection | Maps to `ContentWarning` with deterministic code/severity/scope. |
| `quality_summary` | Derived/preserved | Used to compute recovery summary and warning counts; not blindly copied. |
| `diagnostics` | Derived | Current model derives `PARTIAL_DOCUMENT_RECOVERY` for mixed usable/no-usable pages. |
| `reading_order_edges` | Optional/ignored initially | Current normalizer emits empty list. Future support is open/nonblocking. |
| `alternative_groups` | Optional/ignored initially | Current normalizer emits empty list; unsupported groups warn if semantically material. |
| `extensions` | Optional/preserved selectively | Namespaced safe metadata may be preserved; provider payloads and unsafe keys are not copied. |

### 6.2 SPR page contract

Current page rows require unique `page_id`, integer nonnegative `page_index`, positive `width` and `height`, valid `status`, derived `diagnostics`, and `root_node_ids` referencing existing nodes. Optional current fields include `page_number`, `rotation_degrees`, `coordinate_frame`, `coordinate_origin`, and `coordinate_unit`.

Mapping:

- `page_id` preserves source page identity in evidence/extensions but does not become canonical `ContentPageId` unless identity policy explicitly chooses it.
- `page_index` maps to `source_page_index` and participates in page ordering.
- `page_number` maps to `page_label` when present.
- `width`/`height` map to `PageDimensions` using current SPR `coordinate_unit` semantics; Paddle-VL normalization currently emits PDF/display units.
- `rotation_degrees` maps to `ContentPage.rotation_degrees` if finite.
- `coordinate_*` maps to `CoordinateFrame` with deterministic conversion to current allowed values.
- `root_node_ids` seed page root construction after node identity mapping.
- `status=usable` maps to semantic page states; `no_usable_semantic_content` maps to `PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT` and must have no semantic nodes.

### 6.3 SPR observation contract

Current observation rows require unique `observation_id`, valid `page_id`, accepted evidence links, optional `content.text`, optional `geometry.normalized_bbox`, optional `confidence`, and an `observation_type`. Observations are evidence-bearing facts, not canonical node identity.

Mapping:

- Observation IDs become locator evidence (`spr_observation_ref`) and may seed node lineage.
- `content.text` is normalized conservatively and mapped to node text only through the owning SPR node.
- `geometry.normalized_bbox` maps to `SourceLocation.bounding_box` when valid.
- `confidence` is preserved as typed extension because current Structured Content has no first-class confidence attribute.
- Multiple observations for one node create ordered source locations/evidence, not duplicate content unless explicitly modeled by the SPR node.

### 6.4 SPR node contract

Current node rows require unique `node_id`, `node_type`, `page_ids` referencing pages, `observation_ids`, `evidence_link_ids`, `child_ids`, optional reciprocal `parent_id`, optional `ordinal`, optional `text`, optional `geometry`, optional `confidence`, optional `table`, and optional `formula`.

Mapping:

- `node_id` is preserved as `spr_node_ref` and namespaced extension; it does not become canonical `ContentNodeId` by default.
- `node_type` maps through the matrix in Section 11.
- `page_ids` must be one page for initial implementation; cross-page nodes are degraded/split or rejected by policy because current `ContentNode` has exactly one `page_id`.
- `parent_id`/`child_ids` are used only when reciprocal, acyclic, same-page, and valid.
- `ordinal` participates in ordering.
- `text`, `geometry`, and `confidence` map using Sections 14, 15, and 16.
- `table` and `formula` map only to current typed attributes.

### 6.5 SPR evidence links, warnings, assets, and extensions

Evidence links currently target observations and may contain `raw_result_id`, `provider_block_id`, `source_checksum_sha256`, `source_page_index`, `spr_page_id`, `role`, and geometry. Warnings currently contain `warning_id`, `severity`, `code`, `message`, `scope_kind`, `scope_id`, `affected_ids`, `evidence_link_ids`, `recoverable`, and `canonicalization_blocking`. Assets are currently emitted as an empty list by Paddle-VL normalization.

Transformer behavior:

- Evidence maps to locator-only `EvidenceReference`; no raw JSON or retained payload is copied.
- Warnings map to deterministic `ContentWarning`; messages must be safe, bounded, and free of stack traces and provider payloads.
- Assets map only when safe stable references exist. Missing assets create warnings/degradation, not fabricated assets.
- Extensions are allowlisted and namespaced. Unsafe/reserved keys are dropped with a warning when material.

## 7. Candidate Identity and Lineage Rules

| Identity | Ownership and rule |
|---|---|
| Candidate business identity | Caller supplies candidate identity context. Transformer may format it as `ContentCandidateId` but must not query repositories or infer current/latest. |
| Candidate lineage key | Deterministically derived from document ref, candidate identity input lineage seed, SPR result/raw refs, normalizer identity/configuration, transformer ref, transformation policy ref, mapping version, and supported SPR schema version. Exact hash/encoding is a Slice 3A implementation detail. |
| Node business identity | Transformer derives deterministic `ContentNodeId` from candidate identity context plus stable source node/page/order lineage. |
| Node lineage key | Derived from source SPR node identity when present; otherwise source page index, normalized order tuple, normalized type, and final stable normalized input index. |
| Fixture identity | Test fixtures use stable fake IDs and must not be treated as production business identities. |
| SPR element identity | Preserved in evidence/extensions only; not trusted as canonical identity. |
| Provider element identity | Preserved as evidence locator such as `provider_block_id`; never canonical identity. |
| ProcessingRun identity | Optional provenance reference supplied by caller or copied from explicit validated context; no lookup. |

Equivalent retries with the same SPR, same candidate identity input, same transformer ref, and same policy ref must produce equivalent dataclasses and byte-identical canonical serialization. Rebuilds intentionally supply a new candidate identity and/or policy lineage input, producing a distinct candidate without auto-promotion. Missing SPR node IDs are a structural SPR validation failure today; if future SPR allows missing IDs, deterministic fallback identity must use source page/order/location/text summary inputs and warn.

## 8. Page Mapping

SPR pages map deterministically as follows:

1. Sort pages by explicit SPR `page_index`. The current validator rejects duplicate page indexes.
2. Assign `ContentPage.page_order` as zero-based order after sorting.
3. Preserve `source_page_index = page_index` unless future source-page mapping extension supplies a distinct validated source index.
4. Map `page_number` to `page_label` as a string when present.
5. Map positive `width`/`height` to `PageDimensions`; unit comes from `coordinate_unit` or defaults to `point`/implementation policy.
6. Map rotation only when finite and accepted by policy.
7. Map page evidence using page id, source index, raw result ref, SPR result ref, and optional geometry-free source location.
8. A no-usable page receives no semantic roots or nodes and maps to `NO_USABLE_SEMANTIC_CONTENT`.

Missing source pages represented by `quality_summary.page_coverage.missing_page_indices` become document/page warnings and recovery counts. Duplicate page numbers are allowed as labels with warnings only if they create ambiguity for presentation; duplicate page indexes are structurally invalid. Sparse source ranges are represented through warnings and recovery summary, not fabricated pages unless future policy requires unavailable placeholders.

Cross-page nodes are not directly supported by current `ContentNode`. Initial implementation must either split by validated page-specific observations or degrade/reject with `UNRESOLVED_CROSS_PAGE_STRUCTURE`; it must not create cross-page parent references.

## 9. Ordering Rules

Deterministic order precedence:

| Scope | Primary order | Tie-breakers |
|---|---|---|
| Pages | SPR `page_index` | page id, normalized input index. |
| Page roots | SPR page `root_node_ids` order when valid | node ordinal, geometry, node id, normalized input index. |
| Siblings | Explicit valid parent `child_ids` order or node `ordinal` | source page index, geometry top/left/bottom/right, SPR node id, normalized input index. |
| Table cells | `row_index`, `column_index` | row span, column span, cell source id if present, normalized input index. |
| Evidence | Source page index, target node/order, evidence link id | normalized input index. |
| Warnings | Severity rank, scope path, code, warning id | normalized input index. |
| Assets | Asset source locator/role/id | rendition order and id. |
| Associations | Attribute-contained target IDs ordered by source node order | deterministic target id. |

Duplicate or missing order values are recoverable when geometry and identity tie-breakers resolve a total order. If no deterministic total order can be produced, the transformer raises a bounded ordering error rather than relying on dict iteration or provider list nondeterminism.

## 10. Normalization Rules

### 10.1 Geometry normalization

Current SPR geometry uses `geometry.normalized_bbox` with four finite coordinates `[left, top, right, bottom]` in page-normalized coordinates. The validator requires `0 <= left < right <= 1` and `0 <= top < bottom <= 1`. The transformer maps valid boxes to `NormalizedBoundingBox` and `SourceLocation`. Polygon support is not present in the current SPR model and is unsupported for initial implementation; future polygon fields should be preserved as evidence extension only if safe and namespaced.

Geometry is optional for nodes and evidence. Missing geometry does not fail transformation. Invalid geometry should already be rejected by SPR validation; if encountered at the boundary, it is a hard transformation error. The transformer must not silently clamp, fabricate, or rotate coordinates. Precision is preserved from validated normalized values and rounded only by an explicit deterministic policy.

### 10.2 Text normalization

Text normalization is conservative:

- Normalize Unicode to NFC.
- Normalize line endings to `\n` only if encountered.
- Remove or reject null characters and unsafe controls according to policy.
- Preserve semantic whitespace where meaningful; do not editorially rewrite text.
- Do not perform cross-line word joining, cross-page paragraph joining, punctuation repair, spell correction, language inference, summarization, or LLM cleanup.
- Empty required semantic text should map to warning/degradation or skipped node according to SPR recovery evidence; it should not fabricate content.

### 10.3 Metadata normalization

Provider metadata maps only to existing typed attributes, locator evidence, warnings, or safe namespaced extensions. Confidence and language are not first-class current Structured Content attributes and should be namespaced extensions unless future models add typed support.

## 11. Node Vocabulary Mapping Matrix

| SPR `node_type` / kind | Structured Content node type | Attributes | Evidence | Warning/recovery behavior |
|---|---|---|---|---|
| `title` | `heading` | `HeadingAttributes(level=1)` unless explicit level exists in safe metadata | SPR node, observation, evidence links, page | Warn if title level is inferred; no document-level title field exists. |
| `heading` | `heading` | `HeadingAttributes(level)` if valid, otherwise implementation default/open decision | Same | Invalid/missing level warns; do not fabricate section hierarchy beyond documented rules. |
| `text` | `paragraph` | None | Same | Empty text warns/skips if semantically empty. |
| `paragraph` | `paragraph` | None | Same | Direct mapping. |
| `list` | `list` | `ListAttributes(ordered, marker_style)` from safe metadata when present | Same | If only text is present, create list or fallback paragraph based on evidence; warn on missing items. |
| `list_item` | `list_item` | `ListItemAttributes(marker, ordinal)` | Same | Parent to list when valid; otherwise page root or paragraph fallback with warning. |
| `table` | `table` | `TableAttributes(TableStructure(...))` | Table node/cell evidence | Current Paddle-VL table is unstructured with row/column 0; warn `TABLE_CELLS_UNAVAILABLE` and degrade. |
| `image` | `figure` | `FigureAttributes(rendered_asset_id)` when safe asset exists | Figure evidence/asset locator | Missing crop/asset warns; no binary fetch. |
| `figure` | `figure` | Same | Same | Direct semantic mapping. |
| `caption` | `caption` | `CaptionAttributes(target_node_id/target_asset_id)` when association resolved | Caption and target evidence | Unresolved association warns; caption remains semantic text. |
| `formula` | `formula` | `FormulaAttributes(notation, role)` from `formula.latex`/role | Formula evidence | Missing representation warns; no LLM/MathML conversion. |
| `header` | `header` | None | Same | Direct mapping; no Reader presentation behavior. |
| `footer` | `footer` | None | Same | Direct mapping. |
| `footnote` | `footnote` | None | Same | Direct mapping; unresolved references warn. |
| `code` | `unknown` or `paragraph` | None | Same | Current enum has no code type; preserve text as `unknown` with original kind extension unless policy maps to paragraph. |
| `quote` | `unknown` or `paragraph` | None | Same | Current enum has no quote type; preserve text and warn. |
| `page_number` | `footer` or `unknown` | None | Same | Current enum has no page-number type; map only if SPR semantics establish header/footer, otherwise unknown. |
| `reference` | `unknown` or `paragraph` | None | Same | Preserve text; warn unsupported semantic. |
| unknown/other | `unknown` | Safe extension with original kind | Same | Must not silently disappear; warn and mark recovered/degraded as appropriate. |

No new node type or attribute type is added by this plan. Blocking gaps are recorded in Section 31 rather than model changes.

## 12. Hierarchy Construction

Hierarchy precedence:

1. Use explicit valid reciprocal `parent_id`/`child_ids` from SPR when same-page, acyclic, and complete.
2. Use accepted structural semantics for list/list-item, table/cell, and caption associations when represented in current SPR fields or safe metadata.
3. Use heading/list/table construction rules only when deterministic and explicitly tested.
4. Fallback to page roots in page-root order.

Rules:

- Dangling parents warn and degrade; node becomes page root unless hard policy rejects.
- Cycles are hard transformation invariant errors if not already rejected by SPR validation.
- Cross-page parent relationships are not allowed by current model and must degrade/split/reject deterministically.
- Invalid nesting is corrected only by moving affected nodes to valid page roots with warnings; semantics are not fabricated.
- Geometric containment is not semantic hierarchy in the initial slice.
- Captions associate through attributes when target can be resolved deterministically; otherwise caption remains standalone.
- Page roots must contain only nodes on the same page with no parent.

## 13. Typed Attribute Mapping

| Target attribute | Source field | Conversion | Missing behavior | Invalid behavior |
|---|---|---|---|---|
| `HeadingAttributes.level` | SPR node metadata/normalized heading level; title implies level 1 | Positive integer policy range | Default/open decision with warning | Warning and fallback level or hard error if required by policy. |
| `ListAttributes.ordered` | list metadata | Boolean | `False` | Warning and default false. |
| `ListAttributes.marker_style` | list metadata marker style | String allowlist | Omit | Preserve original in extension if safe; warn. |
| `ListItemAttributes.marker` | list item metadata/text marker | String | Omit | Warn/drop unsafe. |
| `ListItemAttributes.ordinal` | list item metadata | Nonnegative/positive integer by policy | Omit | Warn/drop. |
| `TableAttributes.structure` | SPR `table` object or cells | `TableStructure(row_count,column_count,cells)` | Unstructured 0x0 only if allowed | Degraded table or fallback text; hard error for contradictory required coordinates. |
| `TableCell` | SPR table cells | Zero-based row/column, positive spans | Missing cell omitted with warning if table dimensions imply it | Duplicate/overlap warns/degrades or hard error per policy. |
| `FigureAttributes` | image/figure asset/caption refs | IDs resolved after asset/node construction | Omit refs | Warn unresolved. |
| `CaptionAttributes` | caption target metadata/proximity if accepted | Target node/asset ID | Standalone caption | Warn unresolved. |
| `FormulaAttributes` | `formula.role`, `formula.latex` | `role`, `notation='latex'` when latex present | Text-only formula | Warn unsupported/missing representation. |
| Language | SPR metadata if present | Safe extension | Omit | Warn/drop unsafe. |
| Confidence | observation/node `confidence` | Finite decimal extension | Omit | Warn/drop. |
| Geometry | `geometry.normalized_bbox` | `SourceLocation` | Omit | Hard error after validation boundary. |
| Original element type | SPR `node_type` or provider block type | Safe namespaced extension | Omit for direct mappings | Warn/drop unsafe. |
| Page label | `page_number` | String | Omit | Warn/drop invalid. |

## 14. Evidence Anchors

Evidence is locator-based. Each mapped node should receive at least one `EvidenceReference` when SPR evidence exists. Evidence may include `source_file_ref`, `source_page_index`, `SourceLocation`, `raw_result_ref`, `structured_processing_result_ref`, `processing_run_ref`, `spr_node_ref`, `spr_observation_ref`, `spr_evidence_ref`, and warning refs. Evidence IDs are deterministic from candidate lineage plus source evidence link identity/order.

Rules:

- Deduplicate identical evidence locators by deterministic key.
- Order evidence by page, node order, evidence kind, source evidence id.
- Associate page evidence with pages, node evidence with nodes, warning evidence with warnings, and asset evidence with assets.
- Missing evidence creates a warning when it reduces traceability but does not fabricate a locator.
- Malformed locators are dropped with warning or hard-fail if required for identity.
- Do not store credentials, signed URLs, transient URLs, stack traces, raw provider JSON, or full retained payloads.

## 15. Warnings and Unknown Mappings

The planned warning taxonomy uses current `ContentWarning` fields: deterministic `warning_id`, `code`, `severity`, `scope_path`, safe summary, evidence IDs, `recoverable`, optional blocking hint, details, and extensions.

| Code | Severity | Scope | Impact |
|---|---|---|---|
| `UNKNOWN_ELEMENT_KIND` | warning | node | Preserve as `unknown`, mark recovered/degraded. |
| `UNSUPPORTED_ATTRIBUTE` | info/warning | node | Drop unsupported attribute, preserve safe extension if allowed. |
| `MISSING_PARENT` | warning | node | Re-root node deterministically. |
| `INVALID_PARENT` | warning/error | node | Re-root or hard error for cycles. |
| `DUPLICATE_ELEMENT_ID` | error | document | Hard error under current SPR validator. |
| `MISSING_READING_ORDER` | warning | page/node | Use tie-breakers. |
| `DUPLICATE_READING_ORDER` | warning | page/node | Use tie-breakers. |
| `INVALID_GEOMETRY` | error | node/evidence | Hard error after validation boundary. |
| `MISSING_PAGE_DIMENSIONS` | error | page | Hard error under current SPR validator. |
| `INVALID_TABLE_COORDINATES` | warning/error | table | Degraded table or hard error. |
| `MISSING_ASSET` | warning | asset/node | Missing/degraded asset; no fabrication. |
| `UNSUPPORTED_RENDITION` | warning | asset | Drop rendition ref. |
| `EMPTY_TEXT` | warning | node | Skip or preserve empty structural node by policy. |
| `DROPPED_PROVIDER_ONLY_FIELD` | info | node/document | Safe summary only. |
| `DEGRADED_PAGE` | warning | page | Recovery count increments. |
| `NO_USABLE_PAGE` | warning | page | No semantic roots/nodes. |
| `UNRESOLVED_CAPTION_ASSOCIATION` | warning | caption | Standalone caption. |
| `UNRESOLVED_CROSS_PAGE_STRUCTURE` | warning/error | node | Split/re-root/reject. |

Warnings are deterministic, safe, and validation-clean. They do not include provider payloads or stack traces.

## 16. Recovery and Degradation

Input outcomes:

| Outcome | Candidate behavior |
|---|---|
| Fully usable | Complete document/page/node recovery states and no material warnings. |
| Usable with warnings | Complete or partial states with warning IDs. |
| Degraded | Candidate remains structurally valid; degraded page/node/asset and warning counts reflect transformation evidence. |
| No-usable page | Page has no roots/nodes and `NO_USABLE_SEMANTIC_CONTENT`. |
| No-usable document | Current SPR validator rejects result lacking usable pages; future support requires separate design. |
| Structurally invalid | Bounded transformation error; no candidate returned. |

Validation eligibility is structural, not business-quality acceptance. Degraded valid candidates may be persisted and explicitly selected later; the transformer never auto-selects. ProcessingRun status does not automatically determine recovery state.

## 17. Tables

Current Structured Content table support is `TableAttributes` with `TableStructure(row_count, column_count, cells)` and `TableCell(row_index, column_index, row_span, column_span, text, extensions)`. Future transformer rules:

- Create one table node for each SPR table node.
- Use zero-based row/column indexes and positive spans.
- Derive deterministic cell IDs only internally for lineage/evidence; current `TableCell` has no cell id field.
- Header cells map through cell extensions only if safe because no first-class cell role exists in the in-memory `TableCell` model.
- Missing cells are omitted unless table dimensions require warning.
- Duplicate coordinates violate current persistence uniqueness expectations and must degrade or hard-fail before validation/persistence.
- Overlapping spans warn/degrade or hard-fail according to policy.
- Captions associate by `CaptionAttributes`/`TableAttributes` where supported.
- Rendered table assets use `AssetRole.TABLE_RENDERING` and `TableAttributes.rendered_asset_id` when safe asset refs exist.
- Current Paddle-VL unstructured tables map to degraded table with `row_count=0`, `column_count=0`, empty cells, and warning.

## 18. Assets and Renditions

Assets map only as logical references. The transformer does not fetch, crop, copy, upload, or generate assets.

| Source | Target |
|---|---|
| Figure/image with durable locator | `AssetReference(role=FIGURE)` plus figure `asset_ids` or `FigureAttributes.rendered_asset_id`. |
| Rendered table image | `AssetReference(role=TABLE_RENDERING)` and table rendered asset id. |
| Formula rendering | `AssetReference(role=FORMULA_RENDERING)` when stable locator exists. |
| Page rendering/crop | `AssetReference(role=PAGE_RENDERING)` when stable locator exists. |
| Thumbnail/normalized/original rendition | `AssetRenditionReference` ordered by role and source id. |

Storage references must be durable and safe. Signed URLs and credentials are not canonical identifiers. Missing assets degrade the relevant node/asset and produce warnings. Checksums, byte sizes, media type, dimensions, captions, alt text, and descriptions map when present and valid.

## 19. Associations

Current model expresses associations mostly through attributes and reference tuples, not a general association table. Supported associations:

- Caption → figure/table through `CaptionAttributes.target_node_id` or target asset id.
- Figure → caption through `FigureAttributes.caption_node_id`.
- Figure/table/formula → asset through `asset_ids` and typed rendered asset fields.
- Evidence → page/node/asset/warning through `evidence_ids`.
- Warning → page/node through `warning_ids` and `scope_path`.
- List item → list through parent hierarchy.
- Table cells → table through `TableAttributes.structure.cells`.

Unsupported association categories such as general references, footnote backlinks, and formula labels are future extensions unless they can be safely represented with existing fields and deterministic warnings.

## 20. ProcessingRun Provenance

The caller supplies `processing_run_ref` for production paths. It is optional for fixtures/unit transformations. The transformer may copy the supplied ref to `StructuredContentCandidate.processing_run_ref` and evidence. It must not query, create, or transition a run. Repository persistence remains responsible for same-document and existence validation where implemented. SPR `processing_run_id`, raw result ref, and structured processing result ref may participate in evidence and lineage. Run success does not imply selection or quality.

## 21. Validation Boundary

Planned pipeline:

1. Validate SPR input through current SPR validation before or at entry.
2. Normalize transformation context and policy.
3. Map pages and source page evidence.
4. Map SPR nodes/observations/evidence to content nodes and source locations.
5. Construct hierarchy, roots, sibling order, table structures, assets, warnings, associations, and recovery summary.
6. Assemble immutable `StructuredContentCandidate`.
7. Run existing `validate_content_candidate`.
8. Return candidate or bounded transformation failure.

Validator failures from constructed output are treated as transformer defects or bounded `StructuredContentValidationFailed` errors. The transformer does not persist invalid output and does not duplicate validator logic.

## 22. Persistence Boundary

Future service flow:

```text
validated SPR
→ pure transformer
→ validated in-memory StructuredContentCandidate
→ candidate repository create_candidate
→ explicit separate selection decision
```

Persistence is caller responsibility. Candidate repository remains authoritative for idempotent persistence and conflicts. The transformer does not commit, select, call latest/current lookup, or inspect existing candidates. Equivalent output may be retried safely; conflicting candidate identity remains a repository conflict.

## 23. Error Model

Planned bounded error categories, not implemented by this PR:

| Error | Hard or recoverable |
|---|---|
| `InvalidStructuredProcessingResult` | Hard |
| `UnsupportedStructuredProcessingResultVersion` | Hard |
| `MissingTransformationContext` | Hard |
| `DuplicateSourceElementIdentity` | Hard under current SPR validator |
| `InvalidSourceHierarchy` | Hard for cycles; recoverable for dangling parent when policy permits |
| `UnresolvableOrdering` | Hard |
| `InvalidSourceGeometry` | Hard after validation boundary |
| `InvalidSourceTable` | Recoverable or hard by table policy |
| `TransformationInvariantViolation` | Hard/internal defect |
| `StructuredContentValidationFailed` | Hard |
| `UnsupportedRequiredMapping` | Hard when meaningful content cannot be represented safely |
| `TransformationFailed` | Hard catch-all with chained cause |

Public messages must be safe, deterministic, and free of credentials, provider payloads, stack traces, and unbounded details.

## 24. Versioning and Compatibility

- Supported SPR schema range: exactly `atlas.structured-processing-result` version `1` for initial implementation.
- Unsupported future versions: hard error until mapped by an accepted plan/implementation.
- Transformation policy ref and mapping version must be included in candidate lineage inputs.
- Transformer ref should identify implementation package/version.
- Mapping-rule changes create new candidates by changing policy or transformer lineage input; old candidates remain immutable.
- Golden fixtures must include SPR schema version, transformer ref, policy ref, and expected candidate schema version.
- Equivalent retries under the same versions must be deterministic.

## 25. Determinism and Idempotency

Determinism applies to transformer output; idempotent persistence applies to repository behavior. Separate rules:

- Identity: deterministic from explicit context and stable source lineage.
- Order: total ordering for pages, roots, siblings, cells, evidence, warnings, assets, and renditions.
- Text: NFC and conservative representation normalization only.
- Geometry: deterministic accepted precision; no implicit clamping.
- Extensions: sorted keys, namespaced safe values, no reserved keys.
- Warnings/recovery: deterministic codes, scope paths, counts, and ordering.
- Errors: deterministic category for same invalid input.
- Rebuilds: new candidate identity or policy lineage; never mutate old candidates.

## 26. Test Strategy

### Unit tests

Future unit tests should cover node mappings, typed attributes, geometry, text normalization, warnings, recovery, evidence anchors, table cells, assets/renditions, ordering, and identity.

### Golden tests

Add SPR fixture → Structured Content candidate fixture pairs for normal documents, headings/paragraphs, lists, tables, image/caption, formula, headers/footers, unknown types, degraded page, no-usable page, multi-page documents, duplicate/missing order, invalid parent, missing asset, and Paddle-VL realistic normalized samples.

### Property/invariant tests

Verify no cycles, no dangling refs, valid roots, deterministic output, no provider payload copying, canonical serialization validity, validator success for recoverable inputs, and stable warning/evidence order.

### Regression tests

Cover provider-specific unknown extensions, malformed tables, geometry edge cases, duplicate IDs, sparse pages, cross-page ordering, unsafe locators, and warning explosion.

### Scale tests

Planning targets: 100 pages, 10,000 elements, 1,000 table cells, 500 warnings/evidence anchors, and repeated deterministic runs. These are regression budgets, not production SLOs.

## 27. Fixture Strategy

Fixture layers:

1. Minimal hand-written SPR fixtures.
2. Realistic normalized SPR fixtures from provider-origin samples after redaction.
3. Invalid SPR fixtures for boundary rejection.
4. Expected Structured Content golden candidates.
5. Provider-origin samples normalized into SPR without retained provider payload copying.
6. Scale-generated deterministic fixtures.

Golden candidates must be canonical and validator-clean. Fixture identity is not production identity. Large binaries should not be committed unless separately approved; use stable fake asset locators.

## 28. Implementation Slices

### 28.1 Slice 3A — Transformation contracts and context

- Scope: context types, policy/version type, bounded errors, pure function boundary, feature flags for mappings.
- Intended files: new transformer module files only, plus tests for boundary contracts; no broad mapping.
- Tests: context validation, error safety, policy version lineage inputs.
- Exclusions: page/node/table/asset transformation.
- Entry: accepted plan and no blocking identity/version decisions.
- Completion: boundary compiles, errors safe, no persistence/selection imports.
- Dependencies: current SPR and Structured Content models.
- Risk: premature API shape; mitigate with minimal surface.

### 28.2 Slice 3B — Core page/text mapping

- Scope: pages, page roots, paragraphs, headings, basic ordering, evidence, deterministic node identity.
- Intended files: transformer implementation and focused fixtures/tests.
- Tests: normal one-page and multi-page golden, deterministic repeated output.
- Exclusions: lists, tables, assets, complex hierarchy.
- Entry: Slice 3A complete.
- Completion: validator-clean candidates for core text fixtures.
- Risk: heading hierarchy fabrication; mitigate by page-root fallback.

### 28.3 Slice 3C — Structural mappings

- Scope: lists, list items, captions, headers, footers, footnotes, formulas, unknown fallback, warnings/recovery.
- Tests: vocabulary golden fixtures, unknown/degraded cases.
- Exclusions: full table cells and asset renditions beyond references needed for captions.
- Entry: Slice 3B stable.
- Completion: full bounded vocabulary except tables/assets validated.
- Risk: excessive fallback; mitigate with warning metrics.

### 28.4 Slice 3D — Tables and assets

- Scope: table structures/cells, merged cells, malformed table recovery, image/figure assets, renditions, rendered table/formula assets, associations.
- Tests: table, missing asset, multiple renditions, invalid table regression.
- Exclusions: fetching/copying assets and persistence redesign.
- Entry: Slice 3C stable and table fallback decision resolved.
- Completion: validator-clean table/asset candidates and deterministic ordering.
- Risk: malformed table complexity; mitigate with conservative degradation.

### 28.5 Slice 3E — Golden, property, scale, and determinism verification

- Scope: comprehensive fixtures, invalid SPR tests, scale tests, repeated determinism, validator and candidate repository integration without automatic selection.
- Tests: golden/property/regression/scale suites.
- Exclusions: Reader/projection/API/backfill/retention.
- Entry: Slices 3A–3D complete.
- Completion: documented regression budgets and clean CI.
- Risk: fixture drift; mitigate canonical fixture generation checks.

## 29. Validation and Persistence Integration

The transformer returns an in-memory candidate. A future caller may pass it to candidate repository creation. The repository should validate persistence constraints, ProcessingRun ownership, idempotency keys, and conflicts. Selection remains an explicit separate transaction. No workflow engine is designed here.

## 30. Explicit Exclusions

This plan excludes Raw Result → SPR normalization changes, provider invocation, OCR worker coordination, queues, leases, retries, ProcessingRun orchestration, candidate persistence redesign, selection/promotion, selection history, Structured Document projection, Reader Content Stream, Reader cutover, APIs, background jobs, legacy backfill, retention/deletion, semantic enrichment, LLM cleanup, summaries, Q&A, flashcards, mind maps, M5/M6/M7 work, schema/migration changes, runtime transformer implementation, tests/fixtures in this PR, and production release.

## 31. Open Decisions

| Decision | Classification | Notes |
|---|---|---|
| Candidate ID ownership | Decided by ADR/current model direction | Caller supplies context; repository handles persistence conflicts. |
| Transformation policy version | Implementation detail | Must exist and enter lineage; exact string format open for Slice 3A. |
| Unknown node fallback type | Decided by current model | Use `ContentNodeType.UNKNOWN` when preserving meaningful unsupported content. |
| Geometry precision | Nonblocking open decision | Need exact rounding/decimal policy; current SPR uses normalized bbox strings from Paddle-VL normalizer. |
| Text normalization level | Decided for initial slice | NFC/conservative representation normalization only. |
| Cross-page paragraph handling | Deferred | Current model has one page per node; no probabilistic merge. |
| Heading hierarchy derivation | Nonblocking open decision | Use explicit hierarchy first; avoid fabrication. |
| Asset identity source | Nonblocking open decision | Stable durable locator/checksum preferred; no signed URL. |
| Table fallback policy | Nonblocking open decision | Choose degraded table versus text fallback per invalid shape. |
| Required vs optional ProcessingRun ref | Decided for boundary, implementation detail for production | Optional transformer input; production caller should supply where available. |
| SPR version compatibility | Decided for initial slice | Exactly schema version 1. |
| Source duplicate element ID policy | Decided by current SPR validator | Duplicate IDs are invalid before transformation. |

No blocking open decision is identified for planning. Slice 3A should resolve implementation-detail formats before code relying on them expands.

## 32. Risks

| Risk | Impact | Likelihood | Mitigation | Test evidence required |
|---|---|---|---|---|
| SPR contract instability | Mapping churn | Medium | Version policy and plan updates | Contract regression tests |
| Provider leakage | Canonical contamination | Medium | Locator-only evidence and extension allowlist | No-provider-payload invariant |
| Nondeterministic ordering | Non-idempotent output | High | Total tie-breakers | Repeated canonical byte tests |
| Identity instability | Duplicate/conflicting candidates | Medium | Explicit identity context and lineage rules | Retry/rebuild tests |
| Over-normalization of text | Content corruption | Medium | Conservative normalization | Golden text diffs |
| Fabricated hierarchy | False semantics | Medium | Explicit hierarchy precedence | Hierarchy regression tests |
| Excessive unknown fallback | Low-quality content | Medium | Mapping coverage metrics | Warning distribution tests |
| Warning explosion | Unusable candidates | Medium | Bounded taxonomy and aggregation policy | 500-warning scale fixture |
| Malformed table complexity | Invalid candidates | High | Conservative degraded table policy | Table corruption tests |
| Missing asset references | Broken presentation later | Medium | Missing asset warnings/recovery | Missing asset golden tests |
| Geometry inconsistency | Bad anchors | Medium | Validate and never fabricate | Geometry edge tests |
| Cross-page ambiguity | Invalid hierarchy | Medium | Split/reject/defer | Cross-page fixtures |
| Fixture drift | Brittle CI | Medium | Canonical fixture generation rules | Fixture validation CI |
| Transformer/repository overlap | Side effects in transformer | Low/Medium | Import boundaries and tests | No DB/session import tests |

## 33. Readiness Criteria for Implementation

Slice 3A may begin only when:

- Exact SPR contract is documented and still current.
- Mapping matrix is complete for current vocabulary.
- Candidate identity ownership remains caller/context owned.
- Deterministic ordering rules are complete.
- Unknown mapping, recovery, evidence, table, and asset policies are accepted enough for Slice 3A.
- No blocking open decisions remain.
- Implementation slices are defined.
- No schema migration is assumed unless separately approved.
- Plan review and documentation/CI checks are complete.

This plan does not authorize implementation.
