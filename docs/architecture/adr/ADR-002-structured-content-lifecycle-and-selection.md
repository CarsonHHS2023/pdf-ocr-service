# ADR-002 — Structured Content Lifecycle and Accepted/Current Selection

| Field | Value |
|---|---|
| Document Type | Architecture Decision Record |
| Decision Status | Accepted |
| Lifecycle Status | Active |
| Decision Date | 2026-07-21 |
| Effective Date | 2026-07-21 |
| Authority Domain | M4 Structured Content lifecycle, accepted/current identity, Structured Document assembly role, and acceptance transaction semantics |
| Related Milestone | M4 — Structured Content / Structured Document Foundation |
| Related Roadmap | Roadmap v3 |
| Supersedes | None |
| Implementation Status | Not authorized / Not implemented by this ADR |

## Context

Atlas document-content flow is:

```text
Source Evidence / SourceFile
→ Storage
→ Processing Provider
→ Raw Processing Result
→ Structured Processing Result
→ Structured Content / Structured Document
→ derived projections
→ downstream applications
```

M3 ends at provider-independent Structured Processing Result (SPR). SPR is a provider-independent processing output and interchange boundary, but it is noncanonical document content. M4 must introduce the application-independent accepted/current content boundary that downstream projections and applications can consume without treating provider output, Raw Processing Result, SPR, or legacy Reader serialization as canonical content.

The current implementation contains durable `Document` and `SourceFile` foundation records, compatibility `ContentBlock`, `MineruResult`, `PdfPage`, and `BookImage` records, provider-independent Raw Processing Result envelope code, SPR runtime models and fixtures, an Alembic foundation migration, Reader content routes, delete behavior, and migration/model tests. Those structures are repository constraints and compatibility evidence, not proof that the target M4 Structured Content lifecycle already exists. Current legacy Reader entities are compatibility structures, not the target canonical model.

Retries, rebuilds, future reprocessing, future transformer changes, and later migration from Reader-compatible structures require explicit lifecycle and selection semantics. Without an accepted decision, a later schema or domain-type implementation could accidentally infer current content from newest rows, latest successful processing, Reader serialization, or mutable snapshots. The repository currently has no durable Structured Content lifecycle, so an explicit ADR is required before M4 domain types or persistence schema are implemented.

This ADR resolves:

- M4-DEC-001 — Structured Content lifecycle.
- M4-DEC-002 — canonical/accepted/current identity.
- M4-DEC-004 — Structured Document role.
- M4-DEC-008 — transaction/acceptance behavior.

## Decision drivers

- Deterministic retry/rebuild behavior.
- No silent overwrite of accepted content.
- Provenance and evidence preservation.
- Explicit current content identity.
- Rollback and comparison support.
- Future M6 citation/history requirements.
- Future M7 archive/version requirements.
- Projection regeneration.
- Legacy Reader migration.
- Additive migration safety.
- Bounded M4 complexity.
- Testability.
- Provider independence.
- No duplicate canonical stores.

## Options considered

### Option A — Mutable accepted snapshot

One mutable current content graph per Document.

Advantages:

- Simple conceptual and physical model.
- Lower storage requirements.
- Easy current reads because there is only one graph to query.

Disadvantages:

- High overwrite and retry risk.
- Weaker history, rollback, and comparison behavior.
- Requires a separate audit log to reconstruct prior accepted content.
- Makes rebuild behavior more likely to become nondeterministic because a successful rebuild can mutate the only accepted graph.

### Option B — Immutable Structured Content versions with explicit selection

Each candidate content version is immutable after stable persistence. A Document has one explicit accepted/current selection.

Advantages:

- Strong provenance and evidence preservation.
- Safe rebuild and retry behavior because new work creates candidates rather than mutating selected content.
- Natural rollback/history by selecting a prior valid version.
- Future citation, archive, comparison, and M6/M7 lifecycle value.

Disadvantages:

- Higher schema and storage complexity.
- Requires cleanup, retention, and deselection policies.
- Requires explicit acceptance transaction handling and deterministic duplicate detection.

### Option C — Immutable candidates plus mutable accepted snapshot

Candidate versions are retained, but accepted content is copied into a mutable snapshot for current reads.

Advantages:

- Current reads can remain simple.
- Candidate history may still be retained for comparison and audit.

Disadvantages:

- Creates duplicate stores for the same content.
- Introduces synchronization and divergence risk between immutable candidates and mutable accepted snapshot.
- Complicates acceptance semantics because promotion must update both history and snapshot without making either ambiguous.

### Option D — Artifact-first immutable content manifest

Store immutable accepted/candidate content manifests in object storage with relational identity and selection metadata.

Advantages:

- Suitable for large documents.
- Supports deterministic artifact comparisons.
- Can reduce relational model size.

Disadvantages:

- Weaker direct relational constraints and querying.
- Higher operational complexity around object lifecycle, manifest validation, and cache invalidation.
- Still requires accepted relational identity/selection metadata to avoid ambiguous current content.

## Accepted decision

Atlas accepts Option B as the minimal conceptual lifecycle model for M4: immutable Structured Content versions or candidates with an explicit accepted/current selection per Document. The exact physical schema, table names, class names, node model, asset model, and projection DTOs remain deferred.

Allowed candidate terminology includes `StructuredContentVersion` and `DocumentContentVersion`. This ADR does not finalize the physical name.

## Lifecycle model

A Document may have zero or more immutable Structured Content versions. A persisted content version must not be edited in place after it becomes a stable candidate record. Corrections, rebuilds, retries using a new transformation policy, or transformations from different SPR input produce a new version/candidate unless deterministic duplicate detection resolves them to an existing equivalent candidate.

Acceptance is an explicit lifecycle action. Later implementations may represent lifecycle through states, roles, events, pointers, or another reviewed schema shape, but the conceptual model distinguishes at least:

- candidate/generated;
- validated;
- accepted/current;
- superseded or no longer selected;
- rejected/invalid, if persisted;
- failed transformation, which may remain outside content persistence.

This ADR does not require every implementation to persist all states as enum values. Exact state representation belongs to a later schema decision.

## Accepted/current selection

A Document has zero or one selected accepted/current Structured Content version at a time. The selection must be explicit. The selected version is the authoritative application-independent document content for downstream projection.

The following distinctions are normative within this ADR authority domain:

- Candidate version is not the same thing as accepted/current version.
- SPR is not accepted/current Structured Content.
- Latest-created version is not automatically accepted.
- Most recent ProcessingRun is not automatically current.
- Successful transformation is not automatically accepted unless the acceptance policy explicitly performs selection.
- Provider IDs are not business content identity.

## Acceptance transaction

Candidate/version persistence and accepted/current selection must obey an atomic acceptance boundary.

Required guarantees:

- No partially persisted accepted graph is exposed.
- The accepted/current pointer never references an incomplete version.
- Retry does not create duplicate accepted selection.
- Selection update is transactional where persistence supports transactions.
- Failed selection leaves the prior accepted/current version unchanged.
- Replacing current content records the prior selection and new selection relationship or acceptance event sufficiently for audit and rollback.

This ADR does not finalize SQL constraints, transaction APIs, public endpoints, or migration shape.

## Idempotency identity

Later implementation must define an idempotency or lineage key that supports deterministic duplicate detection and avoids provider IDs as business identity. The key shape is deferred, but approved input concepts include combinations of:

- Document;
- SourceFile/source checksum;
- Raw Processing Result identity/checksum;
- SPR identity/schema version;
- transformer version;
- transformation policy/config hash.

The storage/schema decision must define the exact key and duplicate-resolution behavior.

## Structured Document role

Structured Document is initially a service-layer assembled, application-independent view over one selected Structured Content version and its pages, nodes, assets, evidence, provenance, and recovery state.

Structured Document is not initially a second independently mutable canonical store. This ADR does not require a `StructuredDocument` database table.

Structured Document may later be serialized or cached as a deterministic derived artifact if performance evidence justifies it. Any such cache or artifact must:

- identify its source content version;
- identify assembler/serialization version;
- be invalidatable and rebuildable;
- remain noncanonical.

## Projection relationship

Derived projections consume the selected Structured Content / Structured Document boundary.

Projection constraints:

- Reader projection is noncanonical.
- Reader Content Stream v2 is a compatibility/projection serialization.
- Projection cache, if added later, is derived.
- Projection generation must identify the source content version.
- Projection failure must not change accepted/current content.
- Direct provider JSON, Raw Result, SPR, MineruResult, ContentBlock, or Reader serialization cannot silently become the accepted/current content source.

## Rebuild and retry semantics

- Rebuild produces a new candidate/version unless it resolves to an existing deterministic equivalent.
- Rebuild does not automatically replace current content.
- Acceptance/promotion is explicit.
- Retry after failure cannot partially mutate the selected version.
- Reprocessing with a newer transformer can coexist with prior accepted content.
- Rollback selects a prior valid version rather than editing history in place.

This ADR does not define public endpoints.

## Deletion and retention principle

This ADR establishes only the minimum deletion and retention principle:

- Content-version deletion and source/raw/SPR evidence retention are separate policy concerns.
- Deleting a candidate must not corrupt the selected version.
- Deleting the selected version requires explicit policy and safe reselection, tombstone, or document deletion behavior.
- Projections/caches referencing deleted or deselected content must be invalidated.
- Exact retention periods and cascade behavior remain deferred.

This ADR does not choose legal-hold, commercial retention, archive, purge, or production deletion requirements.

## Consequences

Positive consequences:

- Clear accepted/current identity.
- Safe rebuilds and retries.
- Rollback/history support.
- Future evidence and citation support.
- Projection regeneration from a known source version.
- Compatibility migration without destructive cutover.

Costs:

- Additional version/selection persistence.
- Retention and cleanup complexity.
- More explicit transaction handling.
- Possible storage growth.
- Backfill considerations.
- More extensive deterministic tests.

Neutral consequences:

- Current Reader path remains unchanged.
- Implementation must be additive first.
- Legacy tables remain compatibility only until separately retired.

## Rejected alternatives

- Mutable accepted snapshot as the primary model is rejected because it weakens history, rollback, and retry safety.
- Dual canonical stores are rejected because they create synchronization and authority ambiguity.
- Reader Content Stream as canonical content is rejected because it is a compatibility/projection serialization.
- SPR as canonical content is rejected because M3 ends at provider-independent processing output, not accepted/current Structured Content.
- “Latest successful run wins” without explicit acceptance is rejected because it silently changes current content identity.
- Direct Reader migration in this ADR is rejected because migration and cutover belong to later decisions.
- Full event-sourced content lifecycle is rejected for M4 because it exceeds bounded M4 complexity.
- Artifact-only storage without accepted relational identity is rejected because current selection still requires durable, queryable identity.
- Rich versioning/collaboration features beyond M4 are rejected because they belong to later M6/M7 or product decisions.

## Deferred decisions

D1 does not decide D2–D4 topics. Deferred decisions include:

- Exact table/class names.
- Relational vs hybrid JSON details.
- Content node schema.
- Deterministic node ID algorithm.
- Hierarchy/order schema.
- Acceptance event storage shape.
- ProcessingRun persistence.
- Observation persistence.
- Evidence-anchor persistence.
- Asset model.
- Exact recovery-state fields.
- Retention periods.
- Deletion/cascade behavior.
- Backfill algorithm.
- Projection DTO schema.
- Projection cache.
- Public API.
- UI.
- Reader cutover.
- M6/M7 lifecycle extensions.

## Invariants

1. SPR is never accepted/current Structured Content.
2. A candidate version is immutable after stable persistence.
3. A Document has at most one selected accepted/current version at a time.
4. The selected version is explicit, not inferred from creation time.
5. Acceptance must not expose a partial graph.
6. Retry/rebuild must not silently overwrite selected content.
7. Structured Document does not create a second canonical store.
8. Projections are derived and noncanonical.
9. Projection failure does not alter accepted/current selection.
10. Legacy Reader entities are not target canonical content.
11. Provider-native identifiers do not become business content identity.
12. Implementation remains unauthorized until a separate implementation batch.

## Implementation guidance — non-normative and not authorized

Likely later components include:

- Immutable content-version identity.
- Accepted/current selection record or pointer.
- Acceptance transaction/service.
- Structured Document assembler.
- Deterministic idempotency/lineage key.
- Projection source-version binding.

This guidance is non-normative and does not authorize implementation.

## Validation and evidence expectations

Later implementation must demonstrate:

- Duplicate retry does not duplicate accepted content.
- Failed candidate persistence does not change current selection.
- Failed selection transaction rolls back.
- Rebuild creates candidate without automatic promotion.
- Explicit promotion changes current selection.
- Rollback reselects prior valid version.
- Projection identifies source content version.
- Projection failure does not alter selection.
- Deletion/deselection invalidates derived projections.
- Current legacy Reader route remains unaffected before authorized cutover.

These are expectations for later implementation evidence. They are not marked as already passing by this ADR.

## Relationship to future decisions

Future D2–D4 decisions must conform to this ADR.

### D2 — Core content shape

D2 will decide:

- Content storage shape.
- Node identity.
- Hierarchy/order.
- Transformer boundary.
- Recovery-state representation.

### D3 — Provenance, assets, ProcessingRun, Observation

D3 will decide:

- Evidence minimum.
- Asset identity.
- ProcessingRun.
- Observation.

### D4 — Projection, compatibility, migration, deletion

D4 will decide:

- Projection strategy.
- Reader Content Stream role.
- Legacy migration.
- Backfill/rebuild.
- Deletion/retention details.

## References

- [Documentation governance](../../project/document-governance.md)
- [Roadmap v3 decision](../../roadmap/roadmap-v3-decision.md)
- [Current roadmap](../../roadmap/roadmap.md)
- [M3](../../milestones/M3.md)
- [M4](../../milestones/M4.md)
- [M5](../../milestones/M5.md)
- [Canonical data flow](../canonical-data-flow.md)
- [Document Core information model](../document-core-information-model.md)
- [Structured Content architecture](../document-core-structured-content-architecture.md)
- [Document processing contract](../document-processing-contract.md)
- [Structured Processing Result v1 contract](../../contracts/structured-processing-result-v1.md)
- [Reader Content Stream Protocol v2](../../contracts/reader-content-stream-v2.md)
- [ADR-001 — Service Boundaries](ADR-001-service-boundaries.md)
