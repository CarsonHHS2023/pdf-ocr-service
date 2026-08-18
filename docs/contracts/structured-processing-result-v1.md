# Atlas Structured Processing Result Contract v1

| Field | Value |
|---|---|
| Document Type | Contract |
| Approval Status | Proposed |
| Version | 1 |
| Date | 2026-07-17 |
| Authority Domain | Structured Processing Result representation, validation, compatibility, and provider-independent behavior |
| Applies To | Raw Processing Result normalization into Structured Processing Result v1 before later canonicalization |

## Status

**State:** Proposed provider-independent M3 contract.

| Field | Value |
| --- | --- |
| Schema ID | `atlas.structured-processing-result` |
| Schema version | `1` |
| Architecture source | [Document Core & Structured Content Architecture](../architecture/document-core-structured-content-architecture.md) |
| Atlas commit inspected | `0b5499a2451b349e799b2cc74cdd87e44b13b40c` |
| Provider reference commit | `3a790e3e4c0ececef316bd2ca5aa03d84f6c6159` |
| Fixture-inventory provider implementation revision | `20b9ec9` |
| Design date | 2026-07-17 |

No private Raw Processing Result was retrieved. No provider was called, no operator route or job was invoked, and no runtime behavior changed. The read-only provider reference was clean before this design work and remains unmodified.

## Contract role

```text
Raw Processing Result
        -> Provider-specific normalizer
        -> Structured Processing Result (SPR) v1
        -> later canonicalization
        -> Structured Content
```

SPR is Atlas-owned, provider-independent, schema-versioned, rebuildable from retained Raw Processing Result evidence, partial-capable, and noncanonical. It is **not** Raw Result (exact provider evidence), `ProcessingRun` (execution lifecycle), canonical Structured Content, a Reader projection, or a presentation/export format. Provider adapters retain evidence; normalizers interpret it; later canonicalization selects or creates Structured Content under a separate contract.

## Design goals

SPR v1 provides provider independence, complete evidence traceability, deterministic serialization, partial-result support, schema evolution, stable ordering, and normalized geometry. It supports text, tables, figures/images, formulas, lists, and document metadata without provider field-name leakage, application formatting, or SQL coupling.

## Non-goals

SPR v1 does not define canonical selection, user editing, Reader formatting, Markdown/HTML output, a final persistence schema or database tables, search/vector indexing, provider job control or HTTP protocol, Raw Result retention mechanics, or a final universal quality score.

## Root object

The conceptual root is `StructuredProcessingResult`. Required fields are `schema_id`, `schema_version`, `result_id`, `processing_run_id`, `document_id`, `source_file_id`, `source`, `raw_result`, `provenance`, `created_at`, `state`, `pages`, `nodes`, `evidence_links`, `assets`, `warnings`, and `quality_summary`. `reading_order_edges`, `normalized_observations`, `alternative_groups`, and `extensions` are required as arrays/objects but may be empty. Optional fields are only information that is genuinely unavailable, such as source display version, provider job/request IDs, page number, geometry, confidence, language, source coordinates, and asset storage reference. This avoids an untyped metadata blob as the primary contract.

| Field | Meaning |
| --- | --- |
| `source` | Source checksum (SHA-256 required) and optional source version/media type. |
| `raw_result` | Retained Raw Result identity, evidence source, payload checksum, schema/revision, and opaque `storage_reference` where retained. |
| `provenance` | Provider and normalizer provenance, not provider payload. |
| `pages`, `nodes`, `reading_order_edges` | Page containers, normalized structure, and exceptional reading-order relationships. |
| `normalized_observations` | Provider-independent assertions assembled into nodes. |
| `evidence_links`, `assets`, `warnings`, `quality_summary` | Traceability, binary/structured rendition references, diagnostics, and non-universal quality facts. |

Authority is deliberately singular where values overlap: Page roots define page-local entry points; strict reciprocal parent/child fields define semantic hierarchy; node/observation geometry is its own assertion and neither silently overwrites the other; centralized evidence records are authoritative (embedded IDs are references only); sibling ordinals define ordinary local order while edges add only cross-parent/cross-page/alternative relations; and node geometry locates content while asset geometry locates that rendition.

## Identity model

All IDs are Atlas-owned opaque UUID-like lowercase strings (recommended `spr_<32 lowercase hex>` for result and `<kind>_<32 lowercase hex>` for result-scoped entities). They are immutable within an SPR and are not provider IDs, Storage paths, or mutable text hashes. `result_id` is globally unique. `page_id`, `observation_id`, `node_id`, `order_edge_id`, `asset_id`, `evidence_link_id`, `warning_id`, and `alternative_group_id` are unique within `result_id`; implementations may make them globally unique as well. Cross-version reuse is neither required nor implied; lineage is established through evidence, not reused identifiers.

## Processing provenance

`processing_run_id` identifies the execution record outside SPR. `provenance` records `provider_name`, optional provider request/job IDs (provenance only, and absent for synchronous/no-job providers), optional profile, build/model/pipeline versions, and normalizer name, implementation version, configuration hash/version, and normalization timestamp. `raw_result.schema_revision` is the authoritative Raw Result schema/revision value; provenance must not repeat it. `source` records checksum and optional source version. Credentials, bearer tokens, temporary URLs, local paths, raw exception text, and full provider payloads are forbidden; the payload remains in Raw Result.

## Result state

`state` is independent of provider job status and initially has exactly `complete`, `partial`, and `invalid`. Complete and partial results may contain usable content; partial explicitly retains usable mapped evidence despite failed or missing portions. Invalid may be retained only for diagnostics and must not be canonicalized. It is a **contract-valid envelope describing unusable semantic output**; contract-invalid bytes are not an SPR at all. A total normalization failure that cannot produce a contract-valid root produces a ProcessingRun error, **not** an SPR.

## Page model

A `Page` is a separate container, not a structural node. It has required `page_id`, zero-based `page_index` for paginated sources, `width`, `height`, `coordinate_unit`, `coordinate_origin`, `rotation_degrees`, an explicit `coordinate_frame`, and ordered `root_node_ids`; it may have `page_number`, source page range/reference, page warnings, quality, and provider page provenance. `page_number` is a source/display label and may be absent or non-sequential; it is never an alias for `page_index`. `source_page_range` records the original inclusive source-page range where a provider processed a range, while `page_index` remains the original zero-based source position; duplicate or missing indexes are hard errors except that missing expected indexes are represented by partial coverage, not invented Page objects. V1 is document/page-oriented. A later segment model may extend non-paginated sources without claiming universal media support.

## Coordinate model

V1 recommends **both** a required normalized fractional rectangle when geometry is available and optional source coordinates. `geometry.normalized_bbox` is `[left, top, right, bottom]` in `[0,1]`, with origin `top_left`, x rightward and y downward. It is normalized against the Page `width`/`height` **in the displayed, post-rotation `coordinate_frame`**. `rotation_degrees` is clockwise rotation from the unrotated source page into that frame and is limited to `0`, `90`, `180`, or `270`. Pages still require source width, height, and `coordinate_unit` (for example `pdf_point`, `pixel`, or `unknown`); `geometry.source_bbox` and `source_polygon` are optional only when reliable, are in the declared unrotated source frame, and declare their unit/origin explicitly. An optional transform descriptor maps source to displayed coordinates.

Normalizers may clip only an absolute rounding excursion of at most `0.000001` to `[0,1]` and record a warning. They must reject materially inverted (`left >= right` or `top >= bottom`), non-finite, or out-of-range geometry rather than silently changing it. Coordinates are finite JSON decimal strings with at most six fractional digits when exact serialization matters; implementations must not checksum binary floats. Polygons use the same displayed normalized basis, contain at least three points, and are optional because providers need not emit them.

## Normalized observation model

A `NormalizedObservation` is a provider-independent normalization assertion with `observation_id`, `observation_type`, `status`, page reference, optional content/geometry/order hint/confidence/language, evidence links, warning references, and optional `alternative_group_id`. ProviderObservation remains a logical evidence layer: it is not duplicated in SPR when durable Raw Result evidence links suffice.

V1 chooses **observations as evidence assertions and nodes as assembled structure**. A content-bearing node references one or more observation IDs; observations can support several nodes, and evidence links can target either. A synthetic grouping node (`section` or `list`) may have an empty `observation_ids` only when it has children and a `NORMALIZER_INFERRED_STRUCTURE` evidence link/warning; an inferred leaf must have direct evidence. Multiple observations may merge into one node, and one observation may contribute to multiple nodes. This preserves M3-001A's ProviderObservation/NormalizedObservation distinction without requiring immediate SQL tables. `status` is `accepted`, `alternative`, or `rejected`; rejected assertions remain evidence and are never presented as selected structure.

## Node/block model

A node has `node_id`, `node_type`, optional `semantic_role`, `parent_id`, ordered `child_ids`, page references, optional geometry/text/content, `observation_ids`, `evidence_link_ids`, `asset_ids`, language, confidence, sibling `ordinal`, warning IDs, optional alternative group ID, and namespaced extensions. Nodes are normalized blocks, not canonical ContentNodes.

The minimal extensible v1 vocabulary is `section`, `heading`, `paragraph`, `list`, `list_item`, `table`, `figure`, `formula`, `caption`, `header`, `footer`, `footnote`, and `unknown`. `text_block` and `image` are semantic roles (not structural types); table rows/cells are dedicated nested table structures, not generic nodes. `document`, `page`, and `page_break` are excluded: the root and Page containers express them. Provider class labels map to this vocabulary; unmapped labels become `unknown` with a safe namespaced extension and evidence link.

## Text model

Text-bearing nodes use both `text` (the exact normalized string) and optional `text_segments`. Text segments carry character ranges, geometry, confidence, language, and evidence references when available. The string is the contiguous interpretation; segments enable non-destructive comparison. Normalize Unicode to NFC, preserve meaningful line breaks in `text`, and apply only documented whitespace repairs (for example, converted line endings). Do not collapse all whitespace or overwrite provider text; source/provider text is referenced through evidence excerpts/spans. Language and confidence are optional. A cross-page paragraph is one node with multiple page anchors and explicit continuation/order evidence.

## Hierarchy model

Pages contain ordered root node IDs; node hierarchy expresses semantic containment and may cross pages. Each node has at most one structural parent; Page containment is separate from semantic parentage. Both `parent_id` and `child_ids` are required for non-root relationships and are strict reciprocal validation fields: neither overrides the other, and disagreement is a hard error. Nodes cannot cycle, and an orphan is allowed only when it is a listed page root. A section may contain headings and content, but headings do not automatically create a section. Cross-page nodes list all page references and continuation edges.

## Ordering model

`ordinal` is a non-negative integer unique among siblings or within a page's roots. `reading_order_edges` are centrally stored directed edges for cross-parent, cross-page, or ambiguous relations; each has `order_edge_id`, `from_node_id`, `to_node_id`, `relation` (`precedes` or `continues`), optional confidence, and optional alternative group. Arrays serialize pages by `page_index`, roots/children by ordinal then ID, nodes/observations/assets/evidence/warnings by ID, and edges by `(from_node_id, to_node_id, order_edge_id)`. Duplicate or missing ordinals, missing references, cycles, and incompatible page/order claims are validation errors. Edges are directed and optional, are secondary to hierarchy for ordinary sibling order, and must be acyclic within each non-alternative candidate. An edge that conflicts with parent/ordinal order must be placed in an alternative group or rejected; it cannot silently override hierarchy. They are normalized structural order only, never Reader-specific order.

## Evidence model

Evidence links are centralized in `evidence_links` and referenced by IDs from targets. This permits one-to-many and many-to-one evidence without copying sensitive excerpts. An `EvidenceLink` has exactly one `target_kind`/`target_id` pair, `evidence_link_id`, `raw_result_id`, optional provider observation/block ID (absent when a source exposes none), source page index/number, optional normalized and source geometry, controlled source text excerpt or character span with its declared text coordinate space, source checksum/version, `role`, transformation step, and optional confidence. `target_kind` is `page`, `observation`, `node`, `asset`, or `warning`. A link records a Raw Result identity and payload checksum, never a temporary artifact URL; its source geometry may retain the provider coordinate declaration.

## Table model

A table node owns one dedicated `table` content object. Its `cells` array is authoritative for structured tables: every cell has a table-local row/column index, optional row/column span (default `1`), header role, text, geometry, confidence, and evidence IDs. Rows and cells are **not** generic nodes, avoiding duplicate hierarchy/order representation. `row_count`/`column_count` bound cell indexes; merged cells occupy their declared spans, and missing cells remain absent with a warning rather than fabricated. A table may be structured cells, a rendered image, both, or an `unknown`/unstructured table region with an explanatory warning. The table node's asset IDs carry rendered/source crop links.

## Figure/image model

`figure` means a document-semantic visual region that may have caption relationships; `image` means an image object or image-only region. Both record page anchors, geometry, evidence, optional controlled alt/description, and source-crop or derived-rendition asset IDs. Provider artifact URLs are forbidden. If a crop is unavailable, keep the node/evidence, omit the asset, and add a structured warning.

## Formula model

A formula node has optional provider-neutral `formula` content with `text`, `latex`, and/or `mathml`, plus `role` (`inline` or `display`), geometry, evidence, confidence, and rendered asset IDs. No encoding is mandatory; unrecognized material is retained as `unknown` content with evidence and warning rather than coerced into LaTeX.

## List model

A list has `list_kind` (`ordered` or `unordered`) and list-item children. Item content is represented by child nodes (including multiple paragraph children), not duplicated list text. Items may retain `marker`, nesting by hierarchy, continuation via order edges, and geometry/evidence. A normalizer must not infer orderedness solely from visual alignment when the retained evidence is ambiguous.

## Asset reference model

An asset has `asset_id`, `role`, media type, optional SHA-256 checksum/byte size, optional opaque `storage_reference`, state (`source`, `derived`, `rebuildable`, `missing`, or `unavailable`), page/geometry anchors, provenance/evidence IDs, and optional `rendition_of_asset_id`. `asset_id` is semantic contract identity; `StorageReference` is only retained-byte mechanics (compatible with the current opaque StorageReference value object). External/provider URLs are forbidden. Missing/unavailable assets retain their identity and reason through a warning.

## Warnings and diagnostics

Warnings are centralized structured records: `warning_id`, stable `code`, severity (`info`, `warning`, `error`), scope kind/ID, internal-safe message, affected IDs/pages, evidence IDs, `recoverable`, and `canonicalization_blocking`. Diagnostics must not expose secrets, temporary URLs, paths, or raw exception text. Error severity informs diagnosis; only the blocking hint informs the default promotion gate.

## Quality summary

`quality_summary` reports facts rather than a universal score: page coverage, mapping validity, content completeness, optional text/layout/reading-order confidence summaries, table/figure/formula completeness, warning counts, and schema validation state. Missing confidence remains absent, not `0` or `null`; when reported, a confidence is a finite decimal in `[0,1]` with its subject and provenance stated. Confidences from different providers are not assumed comparable.

## Partial-result semantics

`partial` requires an explicit `coverage` record identifying expected, mapped, missing, and failed page indices and page-level failure warnings. Valid mapped nodes/evidence remain available. Ordering may be incomplete and must be marked by warnings/quality. Invalid mappings cause `invalid` unless the unmapped material is isolated and the retained mapped subset is explicitly partial-valid. Partial results are blocked from automatic canonical promotion by default, but may be reviewed later; no usable evidence is discarded merely because another page failed.

## Alternatives and conflicts

V1 uses narrow `alternative_groups`: each has an ID, `kind` (`text`, `reading_order`, `hierarchy`, `table`, or `overlap`), member observation/node/edge IDs, optional selected member, and a safe rationale. It represents title alternatives, OCR versus embedded text, overlaps, competing tables, hierarchy, and order without asserting canonical truth. A selected member is the normalizer's working choice only; it is not canonicalization. Rejected candidates stay in observations/evidence. Dedicated conflict records are deferred unless fixture evidence proves they are needed.

## Extensions model

Extensions are namespaced objects, for example `"extensions": {"com.atlas.provider.paddle-vl": {...}}`; namespace keys use reverse-DNS lowercase labels (`[a-z0-9]+(\.[a-z0-9-]+)+`). There is no unbounded top-level metadata dictionary. Extensions must be JSON values, must not contain secrets/URLs/paths/raw payloads, and must not redefine core fields. Consumers ignore unknown namespaces safely; canonical consumers must not depend on provider extensions.

## Deterministic serialization

The contract's test/fixture serialization is UTF-8 JSON emitted with Python-compatible `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)`. Strings are NFC before serialization; timestamps are UTC RFC 3339 with `Z` and second or greater precision. Arrays follow the ordering rules above; maps use lexicographic Unicode code-point key ordering. Integers are JSON integers; finite decimal quantities are serialized as JSON strings where exact decimal semantics matter (including coordinates); binary floats are not used for checksums. Omit unavailable optional fields rather than emit `null`; use `null` only when a required nullable field has a defined “known absent” meaning. A serialized checksum is SHA-256 over the exact resulting bytes. This is a project convention, not a claim of full RFC canonical JSON.

## Validation rules

Hard errors include unknown schema ID/version; missing/duplicate identities; invalid references; hierarchy/order cycles; duplicate page indexes or ordinals; nonpositive page dimensions; invalid geometry; invalid SHA-256; invalid asset/warning/evidence targets; partial-state inconsistency; and credentials, URLs, paths, or unsafe metadata. Soft warnings include clipped geometry, absent confidence, unknown type, incomplete optional provenance, or unstructured table. Quality warnings describe coverage, confidence, and completeness without invalidating the object.

## Privacy and security

SPR inherits document-level access control. Text and excerpts are sensitive evidence and are limited to necessary, access-controlled slices; full raw payloads stay retained separately. No credentials, temporary source URLs, bearer tokens, local paths, arbitrary logs, provider payload duplication, or secret/private StorageReference values are allowed. Deletion/retention must account for dependent SPR text, evidence excerpts, and assets; safe diagnostics use stable codes and sanitized messages.

## Versioning and compatibility

`schema_id` is `atlas.structured-processing-result` and `schema_version` is `1`. Additive optional fields and new ignored extension namespaces are backward compatible; semantic removal, changed meanings, or required fields require a new schema version and adapters/migration policy. Provider revision, Raw Result schema revision, normalizer implementation/configuration version, Structured Content schema version, and application projection version remain independent. Readers reject an unknown major/schema version, tolerate unknown optional fields/extensions as specified, and may rebuild a supported SPR from retained Raw Result. Future persistence migration must preserve the recorded schema/version and exact artifact checksum.

## Persistence-neutral representation

This contract can later map to relational rows, one versioned JSON artifact, relational metadata plus artifact, or event/observation records. It selects none. M3-002A must evaluate query/audit needs, atomicity, large payload and asset handling, immutable version retention, evidence link fan-out, rebuild costs, access/deletion policy, and fixture/checksum verification before selecting a shape.

## Provider mapping examples

These are conceptual mappings, not provider field names or protocol commitments:

| Retained provider evidence | Normalizer output |
| --- | --- |
| Text region with text, box, and confidence | `NormalizedObservation(type=text)` plus heading/paragraph/text-block node, normalized geometry, and evidence link. |
| Table-like region/cells | Table node; structured cells when evidence supports them; otherwise unstructured table region plus rendered asset/warning. |
| Figure or image region | Figure/image node, caption relation if detected, crop/rendition asset only if Atlas retained it, and evidence link. |
| Formula-like region | Formula node with any available neutral representation and/or rendered asset; otherwise `unknown` with evidence. |
| Unrecognized provider class | `unknown` node/observation, safe namespaced original classification detail, and evidence. |
| Failed page in otherwise mapped result | `partial` result with coverage/failure warning; no invented page/node, usable pages retained. |

## Example document

The following is fully synthetic and uses only placeholder opaque references. It follows the deterministic field-ordering convention and is internally valid under this proposal.

```json
{
  "alternative_groups": [],
  "assets": [
    {
      "asset_id": "asset_00000000000000000000000000000001",
      "evidence_link_ids": ["evidence_00000000000000000000000000000004"],
      "media_type": "image/png",
      "role": "rendered_table",
      "state": "derived",
      "storage_reference": "src_00000000000000000000000000000001"
    }
  ],
  "created_at": "2026-07-17T00:00:00Z",
  "document_id": "doc_synthetic_01",
  "evidence_links": [
    {"evidence_link_id":"evidence_00000000000000000000000000000001","raw_result_id":"raw_synthetic_01","role":"text_source","source_checksum_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","source_page_index":0,"target_id":"obs_00000000000000000000000000000001","target_kind":"observation"},
    {"evidence_link_id":"evidence_00000000000000000000000000000002","raw_result_id":"raw_synthetic_01","role":"text_source","source_checksum_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","source_page_index":0,"target_id":"obs_00000000000000000000000000000002","target_kind":"observation"},
    {"evidence_link_id":"evidence_00000000000000000000000000000003","raw_result_id":"raw_synthetic_01","role":"table_structure","source_checksum_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","source_page_index":0,"target_id":"obs_00000000000000000000000000000003","target_kind":"observation"},
    {"evidence_link_id":"evidence_00000000000000000000000000000004","raw_result_id":"raw_synthetic_01","role":"rendered_rendition","source_checksum_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","source_page_index":0,"target_id":"asset_00000000000000000000000000000001","target_kind":"asset"}
  ],
  "extensions": {},
  "nodes": [
    {"child_ids":[],"evidence_link_ids":["evidence_00000000000000000000000000000001"],"node_id":"node_00000000000000000000000000000001","node_type":"heading","observation_ids":["obs_00000000000000000000000000000001"],"ordinal":0,"page_ids":["page_00000000000000000000000000000001"],"text":"Synthetic report"},
    {"child_ids":[],"evidence_link_ids":["evidence_00000000000000000000000000000002"],"node_id":"node_00000000000000000000000000000002","node_type":"paragraph","observation_ids":["obs_00000000000000000000000000000002"],"ordinal":1,"page_ids":["page_00000000000000000000000000000001"],"text":"This paragraph is synthetic evidence."},
    {"asset_ids":["asset_00000000000000000000000000000001"],"child_ids":[],"evidence_link_ids":["evidence_00000000000000000000000000000003"],"node_id":"node_00000000000000000000000000000003","node_type":"table","observation_ids":["obs_00000000000000000000000000000003"],"ordinal":2,"page_ids":["page_00000000000000000000000000000001"],"table":{"column_count":2,"row_count":1,"structure_state":"unstructured"}}
  ],
  "normalized_observations": [
    {"evidence_link_ids":["evidence_00000000000000000000000000000001"],"observation_id":"obs_00000000000000000000000000000001","observation_type":"text","page_id":"page_00000000000000000000000000000001","status":"accepted"},
    {"evidence_link_ids":["evidence_00000000000000000000000000000002"],"observation_id":"obs_00000000000000000000000000000002","observation_type":"text","page_id":"page_00000000000000000000000000000001","status":"accepted"},
    {"evidence_link_ids":["evidence_00000000000000000000000000000003"],"observation_id":"obs_00000000000000000000000000000003","observation_type":"table","page_id":"page_00000000000000000000000000000001","status":"accepted"}
  ],
  "pages": [
    {"coordinate_frame":"displayed_post_rotation","coordinate_origin":"top_left","coordinate_unit":"pdf_point","height":792,"page_id":"page_00000000000000000000000000000001","page_index":0,"page_number":1,"root_node_ids":["node_00000000000000000000000000000001","node_00000000000000000000000000000002","node_00000000000000000000000000000003"],"rotation_degrees":0,"width":612}
  ],
  "processing_run_id": "run_synthetic_01",
  "provenance": {"normalization_timestamp":"2026-07-17T00:00:00Z","normalizer_configuration_hash":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","normalizer_implementation_version":"example-1","normalizer_name":"synthetic-normalizer","provider_name":"synthetic-provider"},
  "quality_summary": {"content_completeness":"complete","mapping_valid":true,"page_coverage":{"expected_page_count":1,"mapped_page_indices":[0]},"schema_validation_state":"valid","warning_counts":{"warning":1}},
  "raw_result": {"payload_checksum_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","raw_result_id":"raw_synthetic_01","schema_revision":"synthetic-1","storage_reference":"src_00000000000000000000000000000002"},
  "reading_order_edges": [],
  "result_id": "spr_00000000000000000000000000000001",
  "schema_id": "atlas.structured-processing-result",
  "schema_version": 1,
  "source": {"checksum_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
  "source_file_id": "source_synthetic_01",
  "state": "complete",
  "warnings": [
    {"affected_ids":["node_00000000000000000000000000000003"],"canonicalization_blocking":false,"code":"TABLE_CELLS_UNAVAILABLE","message":"Structured table cells were not retained in this synthetic result.","recoverable":true,"scope_id":"node_00000000000000000000000000000003","scope_kind":"node","severity":"warning","warning_id":"warning_00000000000000000000000000000001"}
  ]
}
```

## Open questions and deferred decisions

Final persistence shape, physical ProviderObservation storage, canonicalization thresholds, final ContentNode vocabulary, user correction, retention, production authorization, and Reader projection remain later decisions. They do not block this information contract.

## M3-001C fixture requirements

M3-001C must cover complete single-page text; multipage ordering; original-page remapping and range processing; partial failure; explicit missing and duplicate pages; table (including merged/missing cells); figure/image; formula; header/footer; unknown provider class; missing confidence; no bounding box; conflicting order; alternatives/conflicts; Unicode; rotated pages; clipped and out-of-bounds coordinates; malformed result rejection; artifact-backed Raw Result; provider profile/revision differences; and unsafe metadata rejection. Each fixture must declare whether it is source-derived or synthetic, provider revision, result profile, expected mapping, limitations, and must exclude secrets and private customer data. Source-derived evidence must preserve the retained Raw Result checksum/revision where safe; synthetic fixtures must state what behavior they cannot prove.

## Acceptance criteria

M3-001B is complete when boundaries and schema identity are explicit; root/page/node/evidence/asset/warning models, ordering, geometry, partial/conflict behavior, serialization, provider isolation, valid synthetic example, and M3-001C fixture requirements are defined; and no SQL schema or canonical Structured Content is introduced. This document satisfies those contract-definition criteria only; it does not implement a normalizer or persistence.

## Human decisions required

The following recommendations require confirmation before M3-001C or M3-001D; they are not silently accepted:

1. Keep v1 page-oriented while leaving room for future segments.
2. Store required normalized fractional geometry plus optional source geometry.
3. Store observations as assertions and nodes as assembled structure.
4. Adopt the minimal node vocabulary listed above.
5. Store evidence centrally and reference it by ID.
6. Use text string plus optional segments.
7. Keep Page as a separate container, not a node.
8. Use narrow alternative groups rather than generalized conflict records.
9. Adopt the Python-compatible deterministic JSON policy above.
10. Ignore unknown namespaced extensions; forbid core redefinition.
11. Block automatic canonical promotion for partial results by default.
12. Carry artifact-versus-row evaluation, rather than a selection, into M3-002A.

## Decision summary

| Decision | Options | Recommendation | Evidence | Human confirmation required | Blocking task |
| --- | --- | --- | --- | --- | --- |
| V1 scope | Page-oriented; generic segments | Page-oriented with extension path | M3 architecture requires page index/number | Yes | M3-001C/D |
| Coordinates | Source; normalized; both | Normalized plus optional source | Provider units vary; evidence needs source basis | Yes | M3-001D |
| Observation/node | Same; assertion + node; blocks only | Assertion + assembled node | M3-001A distinction | Yes | M3-001D |
| Node vocabulary | Broad; minimal extensible | Minimal listed vocabulary | Provider isolation and safe unknowns | Yes | M3-001C/D |
| Evidence storage | Embedded; central | Central IDs | Many-to-many provenance | Yes | M3-002A |
| Text form | String; segments; both | Both, segments optional | Traceability without forced segmentation | Yes | M3-001D |
| Page representation | Node; container | Separate container | Avoids conflating page/semantic hierarchy | Yes | M3-001D |
| Conflicts | Groups; records; extensions | Narrow alternative groups | Preserve ambiguity without canonical truth | Yes | M3-001C/D |
| Serialization | Ad hoc; RFC claim; defined Python JSON | Defined Python-compatible JSON | Fixtures/checksums need repeatability | Yes | M3-001C |
| Unknown extensions | Reject; namespaced-ignore; arbitrary | Namespaced-ignore | Provider detail without core leakage | Yes | M3-001D |
| Partial promotion | Allow; block; discard | Block automatic promotion, retain evidence | Architecture partial-result rule | Yes | M3-003A |
| Persistence direction | Artifact; rows; hybrid; defer | Evaluate all in M3-002A | No premature SQL coupling | Yes | M3-002A |
