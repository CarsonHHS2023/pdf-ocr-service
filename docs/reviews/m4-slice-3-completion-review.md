# M4 Slice 3 Completion Review — SPR to Structured Content Transformation

## Review Metadata

| Field | Value |
|---|---|
| Document Type | Review |
| Status | Completed |
| Review Type | Point-in-time implementation completion review |
| Review Date | 2026-07-23 |
| Milestone Status | Unchanged — M4 remains In Progress |
| M5 Status | M5 remains Planned |
| Normative | No |
| Scope | M4 Slice 3A–3E SPR to Structured Content transformation |

## Executive Decision

**SLICE 3 COMPLETE WITH NONBLOCKING FINDINGS — READY FOR NEXT M4 PLANNING BOUNDARY**

This decision is limited to Slice 3. It does not mark M4 complete, does not start M5, does not authorize Reader implementation, and does not authorize production release.

## Scope

This review evaluates the path:

```text
Structured Processing Result (SPR)
→ provider-independent deterministic transformation
→ validated in-memory StructuredContentCandidate
→ canonical serialization
→ persistence compatibility
```

The evaluated evidence covers contract validation, in-memory transformation, candidate validation, canonical serialization, and repository persistence compatibility.

This review does **not** evaluate Reader UX, Reader projection, production API, job orchestration, operational deployment, backfill, retention, or M5 intelligence.

## Governance Basis

The documentation-governance policy separates normative, descriptive, and historical authority. Reviews preserve point-in-time findings and do not silently change milestone status. Roadmap v3 keeps M4 as the current In Progress milestone and M5 as Planned. The M4 milestone requires deterministic SPR-to-content assembly, Structured Document assembly, projection boundary, compatibility/migration, ProcessingRun/Observation decisions, and M5 handoff before M4 completion. Therefore Slice 3 completion can authorize only the next M4 planning boundary.

## Reviewed Sources

Complete review covered governance and roadmap files; M4 and M5 milestone files; ADR-002, ADR-003, ADR-004, and ADR-005; the accepted Slice 3 plan; the Slice 2 completion review; review indexes; the transformation package; Structured Content model, validation, serialization, repository, selection, and ProcessingRun provenance files; SPR runtime model, validation, serialization, normalizer boundary, contracts, tests, and fixtures; and PR/merge history.

## Merge / CI Evidence

Baseline commands confirmed `HEAD` at `d2d05083d979d2eb5dad92771b606daea5938e54`, the merge commit for PR #139. The last 70 commits include PRs #119–#122, #123–#126, #128–#132, #133, #134, and #135–#139.

GitHub CI evidence could not be retrieved from this environment because the GitHub CLI is not installed and direct GitHub API access from the shell returned a 403 tunnel error. This is recorded as nonblocking finding S3R-N01 for the review artifact. Local repository history proves merges, but this review does not misrepresent local history as CI status.

| PR | Slice | Head SHA | Required Backend CI | Result |
|---|---|---|---|---|
| #135 | 3A | `03d2930` | Not accessible in this environment | Merge present; CI result not independently retrievable locally |
| #136 | 3B | `6a9ae62` | Not accessible in this environment | Merge present; CI result not independently retrievable locally |
| #137 | 3C | `332bc06` | Not accessible in this environment | Merge present; CI result not independently retrievable locally |
| #138 | 3D | `7276bd7` | Not accessible in this environment | Merge present; CI result not independently retrievable locally |
| #139 | 3E | `83eb802` | Not accessible in this environment | Merge present; CI result not independently retrievable locally |

| PR | Purpose | Base/Merge evidence | Files/scope | CI | Review result |
|---|---|---|---|---|---|
| #134 | Slice 3 plan | Merge `fd501e6`; commit `b10ab53` | Plan document | Not reviewed as implementation CI | Accepted plan present |
| #135 | Slice 3A contracts | Merge `9067a76`; commit `03d2930` | Transformation contracts and tests | Not accessible | Complete by code/test inspection |
| #136 | Slice 3B core mapping | Merge `ce5496c`; commit `6a9ae62` | Core text mapping and tests | Not accessible | Complete by code/test inspection |
| #137 | Slice 3C structural mapping | Merge `2be88dc`; commit `332bc06` | Structural mapping/recovery tests | Not accessible | Complete by code/test inspection |
| #138 | Slice 3D tables/assets | Merge `e861e58`; commit `7276bd7` | Table/asset mapping tests | Not accessible | Complete with accepted model boundary |
| #139 | Slice 3E verification | Merge `d2d0508`; commit `83eb802` | Golden, property, scale, persistence tests | Not accessible | Complete by local inspection and direct checks, subject to S3R-N01 |

## Slice 3A Review

Slice 3A established immutable dataclass contracts for `CandidateIdentityInput`, `TransformationContext`, and `TransformationPolicy`; bounded supported SPR, policy, and mapping versions; a bounded error hierarchy; and a pure public `transform_spr_to_candidate` boundary. Tests cover missing/invalid context, unsupported schema/policy/mapping versions, wrong SPR type, deterministic contract behavior, and no persistence/selection/provider calls by import inspection. Result: complete.

## Slice 3B Review

Slice 3B implemented candidate construction, page mapping, title and heading mapping to heading nodes, paragraph/text mapping to paragraph nodes, deterministic page/root/sibling ordering, deterministic candidate/page/node/evidence identity derivation, conservative NFC and line-ending normalization, supported normalized geometry, locator evidence, validator-clean output, and canonical determinism. Tests cover core golden behavior, ordering perturbations, invalid geometry, duplicate source identities, and canonical equality. Result: complete.

## Slice 3C Review

Slice 3C implemented list/list item, caption, formula, header, footer, footnote, generic fallback for quote/code/page_number/reference/unknown/other, unknown-kind warnings, hierarchy validation, missing-parent recovery, cross-page rejection, degraded states, no-usable page behavior, and document recovery summary propagation. Unknown content is preserved rather than silently lost. Recovery is deterministic and is not driven by ProcessingRun status. Result: complete.

## Slice 3D Review

Slice 3D implemented table nodes with explicit table structures, cells, row/column spans, duplicate and overlap validation, sparse valid tables, logical asset references, figure/image mapping, deterministic asset identity, durable/transient reference handling, missing-asset degradation, caption relations, formula asset relation, rendered table references, table/asset warnings, and canonical determinism. The lack of a standalone top-level rendition-object collection compatible with validator resolution is an accepted current model boundary and deferred capability, not a blocker for Slice 3. Result: complete with deferred finding S3R-D01.

## Slice 3E Review

Slice 3E added synthetic golden fixtures for core text, structural content, table/assets, and mixed documents; helper code; golden tests; property/invariant tests; scale tests; and persistence integration tests. Coverage includes canonical determinism, identity separation, retry/rebuild semantics, hierarchy invariants, warning/recovery determinism, table/asset invariants, provider independence, payload leakage, transformer purity, transform → persist → reconstruct, idempotency, conflict behavior, no auto-selection, ProcessingRun provenance, 100 pages, 10,000 nodes, 1,000 table cells, repeated-run determinism, malformed input, atomic failure, and input immutability. Result: complete by code inspection and local checks.

## Commitment Matrix

| Area | Planned commitment | Merged evidence | Test/CI evidence | Result | Finding |
|---|---|---|---|---|---|
| Contracts | Pure transformer boundary | Transformation package exposes transform/types/errors only | Contract tests; CI inaccessible | Met | None |
| Contracts | Deterministic context/policy | Frozen context and policy with version constants | Contract tests | Met | None |
| Contracts | Bounded versioning/errors | Explicit unsupported-version and invariant errors | Contract tests | Met | None |
| Core mapping | Pages/title/heading/paragraph/text | Transformer maps core SPR kinds | Core and golden tests | Met | None |
| Core mapping | Geometry/text normalization | Normalized bbox, NFC, line endings, control rejection | Core/property tests | Met | None |
| Structural mapping | Lists/captions/formula/header/footer/footnote | Transformer maps supported structural kinds | Structural tests | Met | None |
| Structural mapping | Unknown fallback | Unknown/generic textual kinds preserved as unknown nodes | Structural tests | Met | None |
| Tables/assets | Table/cells/spans | Explicit table structures and cell validation | Table/scale tests | Met | None |
| Tables/assets | Logical assets/figures/captions/missing assets | Asset references and warning degradation | Table/asset tests | Met | None |
| Identity | Caller-supplied candidate id | Context identity drives candidate id | Contract/property tests | Met | None |
| Identity | Deterministic page/node/cell/asset/evidence/warning ids | Source ids plus candidate id derive ids | Golden/property tests | Met | None |
| Identity | Provider ids not canonical business identity | Provider refs retained only as provenance/evidence | Payload-leak tests | Met | None |
| Ordering | Pages, roots, siblings, cells, assets, evidence, warnings | Sort keys and canonical serializer ordering | Golden/property/scale tests | Met | None |
| Evidence | Locator based | EvidenceReference uses SPR/evidence refs and source locations | Golden tests | Met | None |
| Evidence | Provider payload not copied | No raw payload fields copied into canonical output | Payload-leak tests | Met | None |
| Warnings/recovery | Deterministic bounded warnings and recovery summary | Implemented warning taxonomy and recovery state | Structural/property tests | Met | None |
| Validation | SPR validator, SC validator, serializer reused | Transformer calls both validators; canonical serializer used in tests | Contract/golden tests | Met | None |
| Purity | No DB/provider/network/file/selection | Transformation imports avoid persistence/provider/HTTP/storage/Reader | Purity tests/import inspection | Met | None |
| Persistence | create/reconstruct/idempotency/conflict/provenance/no selection | Repository integration tests persist transformed candidates | Persistence tests | Met | None |
| Verification | Golden/property/malformed/scale/repeated determinism | S3E test suite and fixtures | Local checks; CI inaccessible | Met locally | S3R-N01 |

## Transformation Vocabulary Coverage

| SPR kind | Current transformation behavior | Target node/model | Status |
|---|---|---|---|
| `title` | Preserved as heading with heading attributes | `ContentNodeType.HEADING` | Supported |
| `heading` | Preserved as heading | `ContentNodeType.HEADING` | Supported |
| `paragraph` | Preserved as text paragraph | `ContentNodeType.PARAGRAPH` | Supported |
| `text` | Preserved as text paragraph | `ContentNodeType.PARAGRAPH` | Supported |
| `list` | Preserved with list attributes | `ContentNodeType.LIST` | Supported |
| `list_item` | Preserved with list-item attributes; missing parent recovered to root | `ContentNodeType.LIST_ITEM` | Supported |
| `caption` | Preserved with target node/asset association where resolvable | `ContentNodeType.CAPTION` | Supported |
| `formula` | Preserved with notation/role and asset extension when resolvable | `ContentNodeType.FORMULA` | Supported |
| `header` | Preserved | `ContentNodeType.HEADER` | Supported |
| `footer` | Preserved | `ContentNodeType.FOOTER` | Supported |
| `footnote` | Preserved | `ContentNodeType.FOOTNOTE` | Supported |
| `quote` | Preserved as generic unknown text with source-kind extension | `ContentNodeType.UNKNOWN` | Supported fallback |
| `code` | Preserved as generic unknown text with source-kind extension | `ContentNodeType.UNKNOWN` | Supported fallback |
| `page_number` | Preserved as generic unknown text with source-kind extension | `ContentNodeType.UNKNOWN` | Supported fallback |
| `reference` | Preserved as generic unknown text with source-kind extension | `ContentNodeType.UNKNOWN` | Supported fallback |
| `unknown` / `other` | Preserved with warning | `ContentNodeType.UNKNOWN` | Supported fallback |
| `table` | Requires explicit table structure and cells; represented on table attributes | `ContentNodeType.TABLE` with `TableStructure` | Supported |
| `table_cell` | Not supported as standalone node; cells live under table structure | Parent table structure | Accepted scope/deferred standalone source-kind support |
| `image` | Mapped as figure with logical asset reference where present | `ContentNodeType.FIGURE` + `AssetReference` | Supported |
| `figure` | Mapped as figure with logical asset reference where present | `ContentNodeType.FIGURE` + `AssetReference` | Supported |
| `diagram` | Not supported as standalone node | Future media/diagram model | Deferred |
| `rendered_table_image` | Not supported as standalone node; accepted as asset kind/reference | `AssetRole.TABLE_RENDERING` | Supported as asset/deferred as node |
| `image_crop` | Not supported as standalone node | Future asset/rendition model | Deferred |

## Contract and Versioning Review

The transformer supports SPR schema version 1, transformation policy version 1, and mapping version 1. Unsupported SPR, policy, and mapping versions raise bounded deterministic exceptions. Context and policy are immutable dataclasses, and the default policy preserves unknown nodes, SPR text, and SPR geometry without semantic cleanup.

## Identity and Lineage Review

Candidate business identity is caller supplied through `CandidateIdentityInput`. Candidate lineage is supplied separately and used to derive node lineage keys. Page, node, asset, evidence, and warning ids are deterministic from candidate id plus SPR source ids. Table cells are value objects ordered deterministically inside table structure rather than independently addressed top-level identity objects. ProcessingRun, raw-result, and SPR identities remain provenance refs, not canonical candidate business identity. Tests cover retries, rebuild identity separation, absence of current-time/random identity, and DB-independent transformation identity.

## Ordering Review

Pages sort by source page index and page id. Node ordering uses page id, explicit ordinal when available, source node id, and input index as tie-breaks. Roots and siblings derive from deterministic traversal. Table cells sort by row, column, and text. Assets, evidence, warnings, and canonical serialized nodes sort by stable ids or warning keys. Property tests perturb equivalent ordering and compare canonical output.

## Hierarchy Review

The transformer enforces exactly one page per mapped node, rejects self-parent, cycles, cross-page parentage, dangling unsupported parent types, and duplicate source node ids. Missing `list_item` parents are recovered as page roots with a deterministic warning. Structured Content validation independently enforces root, parent, page, warning, evidence, asset, and cycle invariants.

## Text and Geometry Review

Text normalization is conservative: NFC normalization and CRLF/CR to LF conversion are applied, unsupported control characters are rejected, and semantic rewriting is absent. Geometry is accepted only as finite normalized bbox coordinates; missing geometry is allowed; invalid geometry raises bounded invariant errors.

## Table Review

The current table contract requires declared row/column dimensions and explicit cell arrays. Row/column spans are checked against dimensions; duplicate cell ids and overlapping occupied coordinates are rejected; sparse tables are valid; header metadata is retained in extension metadata; cells are deterministically ordered. Requiring explicit table structure matches the accepted Slice 3 scope. Unstructured table inference is not part of Slice 3 and is deferred, not blocking.

## Asset Review

Logical assets receive deterministic ids, roles, recovery states, metadata, page source locations, captions, alt text, checksums, media types, and dimensions where present. Durable artifact-like refs can mark availability, while transient URLs, signed refs, file URLs, and absent refs degrade without leaking transient secrets. The transformer performs no media retrieval, rendering, image processing, or file IO; this is a purity/design boundary.

## Rendition Limitation Review

`AssetReference` exposes `rendition_refs`, but `StructuredContentCandidate` has no standalone top-level rendition-object collection for validator resolution. Slice 3D therefore does not fabricate `AssetRenditionReference` objects. Current behavior can represent logical asset references and rendered-asset links from table/figure/formula attributes, but not durable top-level rendition objects. This belongs to a future model revision and does not block Slice 3 transformation readiness.

## Warning Review

Implemented warning codes are `UNKNOWN_ELEMENT_KIND`, `MISSING_PARENT`, `UNRESOLVED_CAPTION_ASSOCIATION`, and `MISSING_ASSET_REFERENCE`. Each warning has warning severity, deterministic id, safe summary, scope path, evidence ids where available, recoverable default, and bounded details. Warnings are sorted deterministically and affect node/page recovery state without changing ProcessingRun status.

## Recovery Review

Complete pages remain complete. Pages with transform warnings become degraded. Missing parents can produce recovered nodes. No-usable pages from SPR remain `no_usable_semantic_content` with empty roots. The recovery summary counts pages deterministically and is validator-compatible. The transformer does not promote quality automatically, does not select content, and does not let ProcessingRun status drive recovery state.

## Provider Independence Review

Transformation imports are limited to SPR runtime/validation and Structured Content model/validation. The transformer does not import Paddle, MinerU, provider packages, HTTP clients, storage clients, credentials, provider sessions, raw provider JSON, or signed URLs. Golden and payload-leakage tests show canonical output remains provider-independent except accepted provenance references.

## Purity Review

Production transformation code has no direct dependency on SQLAlchemy, repositories, selection services, ProcessingRun repository, FastAPI, Modal, provider clients, Paddle, MinerU, HTTP, storage, image processing, file IO, or Reader. Runtime side-effect purity is supported by tests for input immutability, no persistence on transform failure, and no auto-selection.

## Validation and Canonical Serialization Review

The transformer validates SPR input with the SPR validator before mapping and validates the resulting candidate with the Structured Content validator before returning. Tests compare canonical serialization using the existing canonical serializer and verify deterministic bytes across repeated and perturbed transforms.

## Persistence Compatibility Review

Slice 3E persistence integration tests persist transformed candidates with `create_candidate`, reconstruct them, compare canonical equality, verify idempotent same-candidate retry, verify same-id conflicting content failure according to repository contract, confirm no auto-selection, and preserve ProcessingRun provenance as a repository-boundary validation concern.

## ProcessingRun Provenance Review

`TransformationContext` accepts an optional `processing_run_ref`; transformed candidates carry it as provenance. Persistence tests confirm valid ProcessingRun provenance can be stored and invalid provenance is rejected at the persistence boundary. ProcessingRun identity does not define transform quality or canonical candidate identity.

## No-Auto-Selection Review

The transformer returns an in-memory candidate only. Persistence integration verifies candidate creation does not select it automatically. Explicit selection remains separated in selection repository/service code.

## Golden Fixture Review

Committed transformation fixtures are synthetic JSON, contain canonical expected outputs, and do not include credentials, customer documents, raw provider payload dumps, signed URLs, or binary media. CI does not regenerate goldens automatically; tests compare committed expected canonical content.

## Scale Review

Scale tests construct a 100-page SPR with 100 nodes per page for 10,000 nodes and a table workload containing 1,000 cells, then verify transform validity and repeated canonical determinism. This is regression/complexity evidence only; it is not a performance SLA, throughput guarantee, or production capacity guarantee.

## Error Boundary Review

Bounded failures cover wrong SPR type, invalid SPR, unsupported schema/policy/mapping versions, invalid context, unsupported required mapping, hierarchy errors, geometry errors, invalid table structures, and Structured Content validation failures. Messages are deterministic and safe. Exception chaining is used for invalid SPR validation and geometry conversion failures without copying provider payloads.

## Atomicity Review

On transformation failure, no candidate is returned, the input remains unchanged, and no persistence, selection, provider, network, or file operation occurs. On persistence failure, the transformed candidate remains an immutable in-memory value while the repository transaction boundary remains authoritative for durable writes. Slice 2 transaction evidence remains the persistence baseline.

## Blocking Findings

None.

## Nonblocking Findings

- **S3R-N01 — CI evidence not retrievable from local environment.** GitHub CI evidence for PRs #135–#139 could not be independently fetched from this container because `gh` is unavailable and direct shell API access returned a 403 tunnel error. Merge history and local checks are available, but this review must not claim CI success from local evidence alone.
- **S3R-N02 — Scale tests are regression-only.** The 100-page, 10,000-node, and 1,000-cell tests provide deterministic regression/complexity coverage only and are not production performance evidence.

## Deferred Findings

- **S3R-D01 — Standalone asset rendition collection is deferred.** Current StructuredContentCandidate has no validator-resolvable top-level rendition collection, so Slice 3D correctly avoids creating standalone rendition objects.
- **S3R-D02 — Standalone `table_cell`, `diagram`, and `image_crop` nodes are deferred.** Cells are represented through table structures and media through logical assets/figures; standalone variants require future model planning if needed.
- **S3R-D03 — Wholly no-usable SPR documents are blocked by current SPR validator.** Current SPR validation requires at least one usable page, so all-no-usable document transformation requires upstream contract/model revision if later desired.

## Out-of-Scope Findings

- **S3R-O01 — Reader UX/projection/API/orchestration/backfill/retention/M5 intelligence are outside Slice 3.** No implementation is authorized here.
- **S3R-O02 — Media retrieval or rendering generation is outside Slice 3.** Asset handling is logical and reference-based by design.
- **S3R-O03 — Production capacity claims are outside Slice 3.** Verification does not establish operational throughput.

## Slice 3 Readiness Decision

**SLICE 3 COMPLETE WITH NONBLOCKING FINDINGS — READY FOR NEXT M4 PLANNING BOUNDARY**

This is only a Slice 3 readiness decision. It does not imply M4 Complete, production readiness, Reader readiness, or that M5 has started.

## Remaining M4 Work

M4 still requires Structured Document assembly, projection boundary/Reader compatibility strategy, legacy migration/deprecation policy, Observation persistence decision, M4 completion evidence, M5 handoff package, and any remaining compatibility/projection tests required by the milestone. M4 remains In Progress.

## Next M4 Planning Boundary

**Next task title:** Plan M4 Slice 4 — Structured Document Assembly and Projection Boundary.

**Why next:** The M4 milestone lists Structured Document assembly immediately after deterministic SPR-to-content assembly as a required foundation, and the roadmap flow requires Structured Content / Structured Document before projection and M5 Reader work.

**Planning scope:** Define the application-independent assembled document view over selected/candidate Structured Content, reading order, pages, headings/sections, assets, evidence references, recovery state, and projection-boundary constraints sufficient for later Reader-compatible derivation.

**Explicit exclusions:** Do not implement Reader UX, Reader API product behavior, job orchestration, backfill, retention, M5 intelligence, production deployment, or destructive legacy migration in this planning task.

**Prerequisites:** Completed Slice 1 model foundation, Slice 2 persistence/selection/ProcessingRun foundation, and Slice 3 SPR-to-candidate transformation evidence. If project owners choose to plan compatibility/migration before assembly, this review records that as a sequencing option, but repository milestone evidence points next to Structured Document assembly and projection boundary planning.

## Milestone Status

Milestone Status: Unchanged — M4 remains In Progress.

M5 remains Planned. Reader MVP work is not authorized by this review.
