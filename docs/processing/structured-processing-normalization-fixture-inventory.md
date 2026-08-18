# Structured Processing Normalization Fixture Inventory

| Field | Value |
|---|---|
| Document Type | Test Fixture Inventory |
| Authority Domain | inventory and provenance of structured-processing normalization fixtures |
| Applies To | `tests/fixtures/processing/structured_processing_result_v1/`; M2 provider fixtures; Raw Result envelopes; SPR oracles; fragments; parser and security rejection cases; M3-001D support matrix |
| Evidence Role | Records synthetic fixture provenance, safety boundaries, coverage roles, mapping expectations, and non-implementation limits |

## Scope and safety

M3-001C creates the offline corpus at
[`tests/fixtures/processing/structured_processing_result_v1/`](../../tests/fixtures/processing/structured_processing_result_v1/).
Every new value is synthetic, including opaque Atlas IDs, checksums, source metadata,
and storage references. The corpus contains no live-smoke Raw Result, customer text,
provider call, bearer token, transport URL, object key, local path, or production log.
The `unsafe_metadata` fixture uses an intentionally inert `REJECTED_TRANSPORT_URL_PLACEHOLDER` value under an
unsafe key solely as a rejection assertion; it is neither a URL nor a StorageReference.

The M2 provider fixtures remain unmodified. They are source-derived reconstructions
of the `paddle-vl-api` protocol, not captures: their manifest calls out revision
`2026-07-10`, reference commit `3a790e3`, and implementation revision `20b9ec9`.

## Existing M2 fixture inventory

| Existing fixture group | Role and terminal state | Mapping evidence | Suitability for M3 normalizer |
| --- | --- | --- | --- |
| `job_submit_request`, `job_submit_response_accepted` | Request / accepted response | No page/block result | Unsafe as input: control-plane only. |
| `job_status_{queued,running,completed,partial_failed,failed,expired}` | Status snapshots | Counters only; no retained result blocks | Status provenance only; must be wrapped and paired with retained bytes. |
| `error_*` | Error response | No result payload | Rejection/control-plane reference, not normalizer input. |
| `result_summary_completed`, `result_standard_completed` | Final result projections | Standard has page/block projection, summary lacks it | Too profile-specific and incomplete; needs Raw Result envelope. |
| `result_full_inline_completed`, `result_page_mapping_multi_range`, `result_for_mineru_popo_analysis` | Full final results | Pages, page mapping, basic blocks; range fixture has page numbers/ranges | Best shape reference, but still source-derived synthetic provider response; wrap, do not reuse as an oracle. |
| `result_partial_failed` | Partial terminal response | Partial status and counters, no retained full payload | Useful status/coverage reference only. |
| `result_full_artifact_metadata` | Artifact-backed final response | Public artifact metadata only | Provenance reference, not artifact bytes or normalizer input. |

Existing result blocks expose `type`, `text`, `bbox`, optional `confidence`, `order`,
polygon, and metadata. Geometry is provider-shaped rather than an SPR coordinate
assertion; table/image/formula pass-through fields and raw engine output remain
ambiguous. No existing fixture is a hydrated `RawProcessingResultEnvelope`, and all
normalizer candidates require that safe envelope plus exact retained bytes.

## Layered M3-001C corpus

`manifest.json` is authoritative provenance metadata for every fixture. It records
fixture ID/path/category/source type/provider revision/profile/synthetic and safety
flags/origin/pages/state/behaviors/limitations/pairing/M3-001D support/rejection
status. The layers are intentionally small:

- **Raw envelopes:** `raw_results/` represents `RawProcessingResultEnvelope` fields
  adjacent to exact canonical retained JSON. Positive cases include single-page text,
  mixed two-page content, partial failure, rotation, absent geometry/confidence, and
  unknown class. Rejection inputs include malformed bytes, duplicate/missing mapping,
  and unsafe metadata.
- **SPR oracles:** `expected/` are manually proposed, deterministic, contract-valid, synthetic-only
  test oracles for positive/partial cases. They are not output from a mapper,
  provider truth, or canonical Structured Content; M3-001D must verify them. They use schema `atlas.structured-processing-result`
  v1, separate Page containers, centralized evidence, and no provider URL.
- **Fragments:** `fragments/` isolate tables (structured and region-only), figure
  crops/no crop, formula LaTex/unencoded, headers/footers/captions/footnotes,
  alternatives/overlap/low confidence, and Unicode/cross-page text.

The manifest’s behavior tags are the M3-001D support matrix. The full documents are
mapper tests; fragments are block-policy unit tests; rejection cases are parser and
security tests. The `rejection_cases` fragment assigns each mutation to its owning validation
layer. Required future mutations, rather than copied payloads, cover wrong
profile, missing provenance, checksum/size mismatch, duplicate block IDs, non-finite
or degenerate/out-of-range geometry, unsupported revision, invalid dimensions,
invalid original-page mapping, incomplete/conflicting order, and missing artifact. The
`synchronous_provenance` fragment exposes a current envelope-model limitation:
`RawResultIdentity.provider_job_id` is required even though the SPR contract permits
synchronous/no-job provenance. This is a human boundary decision for M3-001D (use a
synthetic stable no-job ID, or make the identity optional in a later scoped change),
not a reason to change the SPR contract.

## Conceptual mapping expectations

| Case | Expected mapping and state | Warnings/extensions |
| --- | --- | --- |
| `complete_single_page_text` | Heading/paragraph observations and nodes on page 0; provider boxes normalize against displayed 612×792 page; ordinal order and evidence links retained. `complete`. | None unless whitespace repair is recorded. |
| `complete_multipage_mixed` + fragments | Pages map by original index/range. Table cells become dedicated table content; region-only table stays unstructured. Figure crop produces asset only if retained; formula uses LaTex when available; lists nest; caption/header/footer/footnote retain node roles. `complete`. | Missing crop, unencoded formula, ambiguous table/order become structured warnings. |
| `partial_failed_page` | Page 0 maps; page 1 is absent from Page array and coverage records failure. `partial`, promotion-blocking warning. | Preserve task failure code safely; do not invent a page. |
| `rotated_page` | Normalize bbox in displayed post-rotation frame, retain source geometry only when declared. `complete`. | Transform declaration/provenance as available. |
| `no_geometry` / `no_confidence` | Text node/evidence is valid without geometry/confidence. `complete`. | Absence is not zero; optional informational warning policy. |
| `unknown_block_type` | `unknown` node/observation and safe `com.atlas.provider.paddle-vl` extension; raw class is evidence-derived. `complete`. | `UNKNOWN_PROVIDER_BLOCK_TYPE`. |
| `unicode` / `alternatives` | NFC text; cross-page continuation edge. Narrow text/table/order/overlap alternatives retain unselected observations. | Low confidence and unresolved alternatives block automatic promotion if policy requires. |

## Retained Raw Result boundary recommendation

M3-001D should conceptually expose:

```python
normalize_paddle_vl_raw_result(raw_result: RawProcessingResultEnvelope, retained_payload: bytes, *, id_factory, clock) -> StructuredProcessingResult | None
```

Fixtures serialize a combined test envelope only for convenience: production retains
metadata and exact bytes separately. The payload checksum/size always cover compact,
sorted UTF-8 retained-payload JSON **without a trailing newline**, never the enclosing
fixture envelope or an expected SPR. The caller retrieves storage and validates exact
byte size/checksum before invoking the mapper; the mapper defensively rechecks the supplied bytes, validates provider
name/profile/revision, decodes JSON once, and dispatches revision support. It returns
no SPR on total failure (record a ProcessingRun error); it may return contract-valid
`partial` for isolated page failures. Production IDs should be opaque from an injected
factory; tests inject deterministic IDs and clock. Artifact retrieval remains caller/
retention responsibility, never mapper network behavior.

## Gaps and decisions for humans

No blocking SPR contract defect was found. `missing_page` and
`duplicate_page_mapping` are explicitly mapper rejection/no-SPR inputs; the former
has no usable semantic content and the latter has conflicting original-page identity. Items are policy/provider limitations, not
contract changes: mapping unknown classes to `unknown`; reject duplicate or invalid
page mappings; clip only the contract’s tiny rounding excursion; retain missing
confidence/geometry as absent; use partial by default for `partial_failed`; defer
embedded-PDF alternatives and MinerU-Popo from the first mapper; reject unsupported
provider revisions and malformed/provenance/checksum/profile failures; decide whether
the checksum check is exclusively caller-owned or defense-in-depth; and confirm
artifact retrieval ownership and production ID strategy. Provider limitations include
unstructured tables, optional crop bytes, nonuniform raw layouts, and ambiguous
reading order. The fixture limitation is that protocol behavior is source-derived,
not live captured.

## Validation and non-implementation statement

`tests/test_structured_processing_result_v1_fixtures.py` is offline-only: it checks
manifest closure, parseability, safety scans, byte checksums/sizes, opaque references,
deterministic JSON, schema/version, relationships, page dimensions/rotation, evidence,
and rejection pairing. It does not import a Provider, call network/Storage, or invoke
a normalizer. These fixtures are oracles and planning evidence only; no production
Raw Result → SPR normalizer, persistence, Structured Content, Reader output, or
MinerU-Popo integration is implemented by M3-001C.
