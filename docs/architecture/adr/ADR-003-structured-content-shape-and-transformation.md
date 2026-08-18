# ADR-003 — Structured Content Shape and SPR Transformation Boundary

| Field | Value |
|---|---|
| Document Type | Architecture Decision Record |
| Decision Status | Accepted |
| Lifecycle Status | Active |
| Decision Date | 2026-07-21 |
| Effective Date | 2026-07-21 |
| Authority Domain | M4 minimum Structured Content shape, page/node identity, hierarchy and reading order, validated SPR transformation boundary, content validation boundary, and recovery-state propagation |
| Related Milestone | M4 — Structured Content / Structured Document Foundation |
| Related Roadmap | Roadmap v3 |
| Depends On | ADR-002 — Structured Content Lifecycle and Accepted/Current Selection |
| Supersedes | None |
| Implementation Status | Not authorized / Not implemented by this ADR |

## Context

M3 produces validated provider-independent Structured Processing Result (SPR). SPR is a provider-independent processing output and interchange boundary, but it is noncanonical processing output rather than accepted Structured Content. [ADR-002](ADR-002-structured-content-lifecycle-and-selection.md) established immutable Structured Content versions and explicit accepted/current selection. This D2 decision defines the minimum candidate content graph created before persistence and acceptance.

The current repository has SPR runtime nodes, pages, observations, evidence links, assets, warnings, diagnostics, validation, deterministic fixture serialization, and Paddle-VL normalization. It also has legacy Reader entities and routes. However, it has no durable Structured Content model. Legacy `ContentBlock`, `MineruResult`, `PdfPage`, and `BookImage` records do not define the new core model because they are coupled to existing Reader/provider compatibility paths and lack the immutable lifecycle and selection semantics selected by ADR-002.

A deterministic application-independent content shape is required before M4 domain types, fixtures, persistence, or transformation implementation can begin. The governing flow is:

```text
Validated SPR
→ pure transformation policy
→ candidate Structured Content graph
→ content validation
→ candidate persistence/acceptance under ADR-002
→ Structured Document assembly
→ derived projections
```

This ADR resolves:

- M4-DEC-003 — Structured Content storage shape.
- M4-DEC-005 — deterministic node identity.
- M4-DEC-006 — hierarchy/order representation.
- M4-DEC-007 — SPR-to-content transformation boundary.
- M4-DEC-013 — recovery-state model.

## Decision drivers

- Provider independence.
- Immutable-version semantics from ADR-002.
- Deterministic transformation.
- Stable lineage across retry/rebuild.
- Explicit document/page/node identity.
- Hierarchy validation.
- Stable reading order.
- Partial and degraded document preservation.
- No fabricated semantic content.
- Evidence and asset references without deciding D3 schemas.
- Projection eligibility.
- Relational integrity and queryability.
- Optional extension support.
- SQLite/PostgreSQL portability.
- Additive migration feasibility.
- Bounded M4 complexity.
- Deterministic fixtures.
- Future M5 projection.
- Future M6 citations.
- Future M7 document history.
- Avoiding a second canonical store.

## Options considered — content storage shape

### Option A — Relational minimum

Conceptually persist content versions, pages, and nodes as individually addressable records with relationships and constraints.

Advantages:

- Strong referential integrity for version/page/node ownership.
- Queryability for page, node, hierarchy, recovery, and projection eligibility.
- Direct hierarchy/order validation.
- Better support for additive migration and portable constraints.

Disadvantages:

- More tables and write complexity than a single artifact.
- Large documents can create high row counts.
- Deterministic serialization needs an explicit derived process.

### Option B — Single JSON content graph

Persist the whole version as one JSON object or artifact.

Advantages:

- Natural deterministic snapshots for fixtures and rebuild comparison.
- Simpler initial writes.
- Fewer physical persistence structures.

Disadvantages:

- Weaker relational constraints.
- Expensive partial querying and indexing.
- Whole-document rewrite for localized changes or migration.
- Object size, concurrency, and indexing concerns.
- Higher risk that an artifact becomes a second canonical store without explicit lifecycle controls.

### Option C — Hybrid relational core plus optional snapshot artifact

Persist relational identity/hierarchy/order and core content fields, while allowing deterministic serialized snapshots and namespaced extension data.

Advantages:

- Balances integrity and reproducibility.
- Keeps page/node identity queryable while allowing fixture/export/cache artifacts.
- Supports deterministic rebuild validation without making snapshots canonical.
- Allows bounded extension data without redefining core semantics.

Disadvantages:

- Optional artifact lifecycle adds implementation complexity.
- Duplication/staleness risk if the artifact is misclassified as canonical.
- Requires clear invalidation/rebuild policy.

### Option D — Legacy-table extension

Reuse `ContentBlock`, `PdfPage`, `MineruResult`, and `BookImage` as the primary target content model.

Advantages:

- Simpler migration from existing Reader-compatible storage.
- Lower immediate implementation cost.

Disadvantages:

- Provider and Reader coupling.
- Ambiguous canonicality.
- Inadequate immutable content-version lifecycle semantics.
- Insufficient page/node identity and hierarchy invariants.

## Accepted storage-shape decision

Option C is accepted: a relationally addressable core with optional deterministic snapshots and namespaced extensions.

### Relationally addressable core

The minimum Structured Content aggregate consists conceptually of:

- one immutable content version selected under ADR-002;
- zero or more content pages;
- zero or more content nodes;
- page-to-version ownership;
- node-to-version ownership;
- node-to-page association where applicable;
- node hierarchy/order relationships;
- core content fields;
- recovery state;
- references to provenance, evidence, and assets whose detailed persistence is deferred to D3.

This ADR defines the conceptual shape, not physical SQL, Alembic, or ORM classes.

### Optional deterministic snapshot

A content version may later have a deterministic serialized snapshot/artifact for fixture comparison, export, rebuild validation, or cache/performance use. That artifact must identify its source content version, identify serialization/schema version, be reproducible, be invalidatable/rebuildable, not replace relational content identity, and not become a second canonical store. Whether the artifact is persisted is deferred.

### Namespaced extensions

Structured Content may allow namespaced extension metadata for content not represented by the core model. Extensions must not redefine identity, hierarchy, order, recovery, or accepted/current selection; must not expose unsafe provider payloads by default; must remain subordinate to the core model; must be schema/version identifiable; and must survive deterministic serialization if retained. This ADR does not decide JSON column types.

## Minimum Structured Content concepts

### Content version

A content version references:

- Document identity.
- Immutable version identity.
- Lineage/idempotency identity.
- Transformer/policy version.
- Lifecycle and selection governed by ADR-002.

Exact provenance fields are deferred to D3.

### Content page

A content page has these minimum conceptual properties:

- version-scoped page identity;
- source page index;
- optional human-facing page number/label;
- page order;
- dimensions when known;
- rotation when known;
- coordinate space/frame when geometry exists;
- recovery state;
- optional page-level warnings/references;
- ordered root nodes.

Physical nullable rules are deferred.

### Content node

A content node has these minimum conceptual properties:

- version-scoped immutable node identity;
- node type;
- page association where applicable;
- parent relation where applicable;
- sibling/order position;
- normalized text where applicable;
- structured attributes appropriate to type;
- source span/geometry references where available;
- recovery/degraded state;
- evidence and asset references;
- optional namespaced extensions.

Physical nullable rules are deferred.

## Core node vocabulary

M4 accepts a bounded provider-independent core vocabulary sufficient for initial transformation. Conceptual categories include:

- document/root, only if needed by the chosen graph model;
- section;
- heading;
- paragraph;
- list;
- list item;
- table;
- table row/cell or table-structure reference;
- figure/image;
- caption;
- formula;
- header;
- footer;
- footnote;
- page break or structural boundary, only if needed;
- unknown.

Exact enum spelling is deferred. Unsupported or provider-specific types map through an explicit policy. `unknown` is valid when evidence exists but semantic classification is not safely supported. Provider type names must not become canonical node types automatically. Node vocabulary may evolve by versioned contract, not arbitrary provider leakage. Full table-cell and asset schemas remain D3/deferred work.

## Node identity decision

### Immutable business identity

Each persisted page/node receives a version-scoped immutable identity. The exact identifier technology remains deferred. Identity:

- is not a provider block ID;
- is not inferred from mutable text alone;
- is unique within the content version or repository scope according to a later schema decision;
- never changes after stable candidate persistence.

### Deterministic lineage key

Transformation must also calculate or preserve a deterministic lineage key sufficient to recognize equivalent output and support fixtures, retry, comparison, and rebuild. The lineage input may include approved stable components such as:

- content version lineage;
- source page index;
- normalized source region;
- SPR node identity within the validated SPR;
- normalized structural path;
- node type;
- transformer version/policy.

Exact hashing/encoding is deferred. Lineage keys support duplicate/equivalence detection. A lineage key is not automatically the database primary key. Provider-native IDs may be provenance inputs but not business identity. Text-only hashes are insufficient because duplicate text can exist. Geometry-only identity is insufficient because geometry can be missing or can change.

### Fixture identity

Golden fixtures must use stable deterministic identifiers or canonical placeholder identities so equivalent transformation output can be compared without dependence on random production IDs.

## Hierarchy and reading-order decision

### Parent plus sibling order

The primary hierarchy representation is conceptually:

- nullable parent node within the same content version;
- sibling/order position under the parent;
- page-level ordered root nodes;
- validation of same-version ownership;
- validation of acyclic hierarchy;
- uniqueness or deterministic ordering among siblings.

Column names and zero/one-based indexing are deferred.

### Page and document order

Reading order is primarily derived from:

1. content page order;
2. ordered page roots;
3. recursive sibling order.

Cross-page continuation may be represented by explicit lineage/continuation metadata when ordinary page order and hierarchy are insufficient.

### Optional explicit reading-order edges

Explicit reading-order edges may be introduced only when evidence demonstrates that parent/sibling/page order cannot represent required layout flow. If later used, they must remain within one content version, not contradict the primary hierarchy without explicit policy, be validated for cycles and dangling targets, and be versioned. This ADR does not require a general graph database or arbitrary edge model.

### Hierarchy invariants

Structured Content requires:

- no dangling parents;
- no cross-version parent relation;
- no hierarchy cycles;
- no duplicate sibling positions under the same parent after normalization;
- page roots belong to the page/version;
- node page association is consistent with hierarchy policy;
- deterministic traversal order;
- invalid hierarchy blocks acceptance.

## Structured attributes

Node-specific structured attributes may include conceptual data such as:

- heading level;
- list kind/start/marker;
- table dimensions and structure reference;
- figure/caption relationship;
- formula representation;
- language;
- confidence where provider-independent and useful;
- source geometry;
- continuation relationship.

Exact typed models remain deferred to domain-contract/schema work. Provider-native payload must not be copied wholesale. Essential semantics should use core typed fields where accepted. Optional unsupported metadata belongs in namespaced extensions. Attributes must serialize deterministically.

## SPR-to-content transformation boundary

M4 accepts a pure transformer after SPR validation.

### Input

The transformer consumes:

- a fully validated Structured Processing Result;
- an explicit transformer version;
- an explicit transformation policy/configuration;
- necessary immutable context/reference identities.

The transformer must not accept unvalidated provider payload as its canonical input.

### Output

The transformer returns an in-memory candidate Structured Content graph containing:

- version-level candidate data;
- pages;
- nodes;
- hierarchy/order;
- recovery state;
- evidence/asset references or unresolved typed references;
- warnings generated by transformation;
- lineage/idempotency material;
- projection-eligibility result or inputs for later validation.

It does not return accepted/current selection.

### Prohibited transformer responsibilities

The transformer must not:

- call a processing provider;
- parse provider-native JSON directly except through an explicitly separate pre-SPR compatibility adapter;
- write a database;
- write object storage as a required side effect;
- select accepted/current content;
- mutate a prior content version;
- update Document current selection;
- build Reader UI;
- implement M5 presentation behavior;
- decide retention/deletion;
- perform network calls;
- depend on the current Reader serialization as its domain model.

### Determinism

For the same validated SPR content, transformer version, transformation policy/configuration, and relevant immutable context, the transformer must produce semantically identical candidate output. If generated runtime IDs differ, canonical fixture serialization must remain stable.

## Content validation boundary

M4 accepts a separate Structured Content validator. The validator checks at minimum:

- content version identity/context;
- page identity and page order;
- node identity uniqueness;
- page/node ownership;
- hierarchy acyclicity;
- parent/child consistency where represented;
- stable sibling ordering;
- no dangling evidence/asset references at the level required by the selected validation phase;
- valid node vocabulary;
- safe extensions;
- recovery-state consistency;
- no fabricated semantic nodes on unusable pages;
- projection eligibility requirements;
- deterministic serialization requirements.

SPR validation and content validation are separate. Valid SPR does not guarantee valid candidate content. Invalid candidate content must not be accepted/current. A failed candidate may be retained only if later lifecycle/schema policy explicitly allows it. The validator does not update accepted/current selection.

## Recovery-state options

### Option A — Recovery only in SPR

Content drops most recovery state and relies on resolving upstream SPR. This is rejected because projections and downstream applications need stable, application-independent recovery semantics.

### Option B — Page-level recovery only

Persist recovery state on content pages and derive document state. This is simple but limits node/asset-specific degradation when retained content, evidence, assets, or projection eligibility are affected.

### Option C — Document and page recovery with selective node-level degradation

Preserve document/page state and record node-level degradation only when it affects a retained node, evidence, asset, or projection. This preserves M3 recovery facts that are relevant to Structured Content without turning every processing diagnostic into content.

### Option D — Full diagnostic duplication

Copy all SPR warnings and diagnostics into content. This is rejected due to duplication and risk of making processing diagnostics canonical content.

## Accepted recovery-state model

Option C is accepted.

### Ownership

- M3 owns normalized recovery facts and diagnostics in SPR.
- M4 preserves application-relevant recovery state in Structured Content.
- M5 owns user-facing Recovery Presentation.
- M4 content must not duplicate all provider or SPR diagnostics.

### Required levels

Structured Content must support:

- version/document-level recovery summary;
- page-level recovery state;
- selective node/asset-level degraded or unavailable state when required.

Exact enum and storage fields are deferred.

### Minimum semantic distinctions

Structured Content preserves distinctions equivalent to:

- complete;
- partial;
- degraded;
- no usable semantic content;
- unavailable/failed source page or processing result where applicable;
- recovered/selected through recovery policy;
- unsupported content;
- missing/degraded asset;
- invalid candidate topology, which prevents acceptance.

Final enum spelling is not invented here where the SPR contract already provides authoritative terminology; later work maps explicitly to it.

### No fabrication

For a page with no usable semantic content, Structured Content must preserve page identity/topology and recovery/evidence references, must not fabricate headings, paragraphs, or other semantic children, may have zero semantic root nodes, may carry projection-ready recovery metadata, and must not convert absence into processing success.

### Partial documents

A document may have accepted content containing usable pages plus explicitly degraded/unavailable pages when the accepted recovery policy permits it. Acceptance policy must be explicit and later implementation must not infer `complete` merely because some nodes exist.

### Invalid topology

Invalid hierarchy or dangling core references are candidate-validation failures, not merely user-facing warnings. Such candidate content cannot become accepted/current.

## Unsupported types and transformation warnings

M4 accepts that safely supported node types map to the core vocabulary. Unsupported but evidenced content may map to `unknown` with a warning and source/evidence reference. A node may be skipped only under explicit transformation policy. Skipped content must produce diagnostics/traceability sufficient for later review. Provider-native type names may be retained only as provenance or namespaced extension metadata. Unsafe or malformed provider metadata is not copied into core content. Warnings do not automatically make a candidate unacceptable unless policy or validation says so.

## Projection eligibility

Projection eligibility is a content-validation result, not a projection itself. A candidate may be:

- structurally valid and eligible;
- structurally valid but degraded;
- structurally valid but ineligible for a specific projection due to missing assets or unsupported semantics;
- invalid and ineligible for acceptance.

Projection eligibility does not make a candidate accepted/current. Accepted selection remains governed by ADR-002. D4 will decide projection DTO and compatibility rules. User-facing Recovery Presentation remains M5.

## Consequences

Positive consequences:

- Stable provider-independent domain boundary.
- Deterministic transformer and fixtures.
- Queryable page/node identity.
- Validated hierarchy and reading order.
- Explicit recovery propagation.
- Safe retries and rebuild comparison.
- Clear separation of transformer, validator, and persistence.
- Future projection/citation/archive support.

Costs:

- More domain structures than a single JSON blob.
- Hierarchy/order constraints.
- Deterministic lineage design.
- Migration complexity.
- Additional recovery fixtures.
- Possible row volume for large documents.
- Need for versioned contracts/serialization.

Neutral consequences:

- Exact ORM/schema remains open.
- D3 must provide provenance/evidence/assets.
- D4 must provide projections/migration.
- Current Reader path remains unchanged.

## Rejected alternatives

The following are rejected as primary architecture:

- one mutable JSON graph with no addressable page/node identity;
- legacy `ContentBlock`/`MineruResult`/`PdfPage`/`BookImage` as canonical target model;
- provider block IDs as content business IDs;
- text hash alone as node identity;
- geometry alone as node identity;
- arbitrary graph model for all relationships;
- direct provider JSON-to-content transformation in the M4 target path;
- transformer that writes DB or selects current content;
- SPR and content validation as one indistinguishable step;
- recovery state only in Reader projection;
- duplicating all raw/provider diagnostics into Structured Content;
- fabricating placeholder semantic nodes for unusable pages;
- direct Reader cutover in this ADR.

## Normative invariants

Within this ADR authority domain:

1. Structured Content must belong to exactly one immutable content version.
2. Each content page must belong to exactly one content version.
3. Each content node must belong to exactly one content version.
4. Provider IDs must not be canonical page/node business identity.
5. Stable persisted node identity must be immutable.
6. Deterministic lineage identity must be distinct from physical primary-key choice.
7. Core parent relations must never cross content versions.
8. Core hierarchy must be acyclic.
9. Traversal order must be deterministic.
10. Invalid hierarchy must prevent acceptance.
11. Transformer input must be validated SPR, not provider JSON.
12. Transformer must be deterministic for equivalent approved inputs.
13. Transformer must not persist or select accepted/current content.
14. Content validation must be distinct from SPR validation.
15. No-usable-content pages must retain topology but gain no fabricated semantic children.
16. Application-relevant recovery state must survive SPR-to-content transformation.
17. Structured Content must not duplicate all provider-native diagnostics.
18. Optional snapshots/extensions must not replace core identity/hierarchy.
19. Projection eligibility must not imply accepted/current selection.
20. Implementation must remain unauthorized by this ADR alone.

## Deferred decisions

This ADR defers:

- exact table and ORM class names;
- column types;
- relational normalization details;
- JSON extension column strategy;
- persisted snapshot/artifact decision;
- primary-key technology;
- exact lineage-key algorithm;
- exact core node enum spelling/version;
- complete node-specific attribute schemas;
- explicit reading-order edge schema;
- cross-page continuation representation;
- evidence-anchor schema;
- asset/rendition schema;
- ProcessingRun;
- Observation;
- exact recovery enum/storage fields;
- acceptance eligibility policy for degraded content;
- projection DTO/cache;
- Reader Content Stream mapping;
- public API;
- backfill/migration;
- deletion/retention;
- performance SLOs;
- Reader cutover.

D3 and D4 topics are not decided here.

## Implementation guidance — non-normative and not authorized

Likely future components may include Structured Content in-memory domain types, a canonical fixture serializer, `StructuredContentTransformer`, `StructuredContentValidator`, node-type mapping policy, hierarchy/order builder, recovery-state mapper, and deterministic lineage-key builder. These names are illustrative only. No implementation is authorized by this ADR.

## Validation and future evidence expectations

Later implementation must demonstrate:

- same SPR + transformer version + policy produces equivalent candidate graph;
- provider-specific IDs do not leak into canonical identity;
- duplicate text nodes remain distinct where structure/source differs;
- missing geometry does not prevent stable identity;
- hierarchy cycles are rejected;
- dangling parents are rejected;
- cross-version links are rejected;
- sibling traversal is deterministic;
- page traversal is deterministic;
- unsupported types become controlled unknown/skipped results with warnings;
- complete-page fixture transforms correctly;
- partial-page fixture preserves usable content and state;
- no-semantic-content page preserves topology without fabricated nodes;
- mixed multi-page recovery preserves usable and degraded pages;
- invalid topology prevents acceptance;
- transformer has no DB/provider/Reader side effects;
- legacy Reader route remains unchanged until separately authorized.

These tests are future evidence expectations; this ADR does not state that they already pass.

## Relationship to other decisions

### ADR-002 / D1

This ADR conforms to immutable versions, explicit accepted/current selection, atomic acceptance, Structured Document assembled view, and noncanonical projection.

### D3

D3 will decide provenance/evidence minimum, asset identity and rendition boundary, ProcessingRun, and Observation. D3 references must attach to the version/page/node concepts defined here.

### D4

D4 will decide projection strategy and DTO, Reader Content Stream role, legacy migration, backfill/rebuild, and deletion/retention details. D4 must preserve deterministic source-version binding and noncanonical projection.

### Later schema implementation

Later schema implementation may choose physical relational/hybrid structures only within this ADR's invariants.

## References

- [Documentation governance](../../project/document-governance.md)
- [Roadmap v3 decision](../../roadmap/roadmap-v3-decision.md)
- [Current roadmap](../../roadmap/roadmap.md)
- [M3 milestone](../../milestones/M3.md)
- [M4 milestone](../../milestones/M4.md)
- [M5 milestone](../../milestones/M5.md)
- [ADR-002 — Structured Content Lifecycle and Accepted/Current Selection](ADR-002-structured-content-lifecycle-and-selection.md)
- [Canonical data flow](../canonical-data-flow.md)
- [Document-core information model](../document-core-information-model.md)
- [Document-core Structured Content architecture](../document-core-structured-content-architecture.md)
- [Document processing contract](../document-processing-contract.md)
- [Recovery presentation architecture](../recovery-presentation-architecture.md)
- [Atlas block recovery contract v1](../atlas-block-recovery-contract-v1.md)
- [Atlas provider conformance profile v1](../atlas-provider-conformance-profile-v1.md)
- [Structured Processing Result v1 contract](../../contracts/structured-processing-result-v1.md)
- [Reader Content Stream v2 contract](../../contracts/reader-content-stream-v2.md)
- [Mixed multi-page recovery ADR](../../adr/ADR-0001-mixed-multi-page-recovery-policy.md)
- [ADR-001 — Service Boundaries](ADR-001-service-boundaries.md)
