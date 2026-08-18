# ADR-0001: Mixed Multi-Page Recovery Policy

| Field | Value |
|---|---|
| Document Type | ADR |
| Approval Status | Accepted |
| Date | 2026-07-17 |
| Authority Domain | Mixed multi-page recovery policy |
| Applies To | Atlas Raw Result to Structured Processing Result normalization |
| Related Contracts | [SPR contract](../contracts/structured-processing-result-v1.md) |

**Status:** Accepted  
**Decision date:** 2026-07-17  
**Scope:** Atlas Raw Result to Structured Processing Result normalization

## Context

A document may contain usable semantic content on Page 0 and Page 2 while Page 1 has no usable semantic blocks. The Raw Result remains viable, but removing Page 1 damages source identity, topology, citations, annotations, pagination, provenance, reprocessing comparisons, and knowledge references. An apparently normal empty page would hide recovery failure.

## Decision

Atlas adopts **Topology-Preserving Explicit Degradation**. When a structurally valid source page has no usable semantic blocks but usable output survives elsewhere, Atlas preserves the page, source-page identity, and ordering; emits no fabricated semantic children; records page-level semantic coverage loss; adds a safe provider-independent warning; retains safe evidence references; and marks the overall SPR partial.

## Required Page Status

The page model requires a first-class semantic status for this decision: `no_usable_semantic_content`. Status is not inferred solely from empty children, warnings, or quality counters. Status describes processing state; quality records measurable loss; warnings explain the condition safely; evidence references permit inspection; children contain recovered semantics only. Future statuses require contract evolution.

## Required Warning

`PAGE_HAS_NO_USABLE_SEMANTIC_CONTENT` is the required provider-independent warning concept. Its fixed safe wording is: “No usable semantic content was recovered for this page.” It identifies the affected stable Atlas page identity and MUST NOT contain retained text, payload excerpts, secrets, paths, private URLs, or provider field names.

## Original Page and Block Inspection

Applications may offer **View original page**, or **View original block** when independently retained source-region evidence and reliable geometry exist. An evidence reference identifies evidence; it is not an access grant. The SPR MUST NOT embed PDF/image bytes, payloads, permanent URLs, storage paths, bucket names, or credentials. An authorized Atlas service resolves stable evidence identities into temporary access outside the SPR. Missing geometry MUST NOT create fabricated crops; page-level inspection remains available when block inspection is impossible.

Conceptually, Reader behavior is: page exists; no usable semantic content was recovered; View original page. This ADR does not specify UI.

## Mixed Multi-Page Behavior

```text
Page 0  status: usable                       semantic children: retained
Page 1  status: no_usable_semantic_content   semantic children: []
        warning: PAGE_HAS_NO_USABLE_SEMANTIC_CONTENT
        original-page evidence reference: retained
Page 2  status: usable                       semantic children: retained
```

Source identities and ordering remain stable: source page 2 is never renumbered as page 1.

## Result Viability Boundary

If at least one usable semantic object survives anywhere, emit an SPR, preserve unusable pages as explicit degraded topology, and mark the SPR partial. If none survives anywhere, emit no SPR. Atlas MUST NOT create warning-only, quality-only, provenance-only, or page-shell-only SPRs.

## Page versus Block Evidence

A page may survive topologically with zero semantic children. An unusable block does not become a fabricated node. Safe skipped-block identifiers may exist only where existing contracts support them. Original-block viewing is optional and geometry-dependent; original-page viewing is the required fallback.

## Coverage and Quality

Retaining a page preserves topology, not semantic success. Loss of all semantic content on that page is page-level coverage loss; the page is not complete and the viable document SPR is partial. No numeric quality score is defined here.

## Consequences

Positive consequences include stable identity, transparent recovery disclosure, stable citations/annotations, inspectable original evidence, and downstream systems that need not infer failure from empty children. Costs include page-status support, topology-only degraded-page validation, page-level warning/quality aggregation, Reader/API disclosure, and authorization-aware evidence resolution.

## Rejected Alternatives

1. **Remove the unusable page:** rejected because it destroys topology and destabilizes references.
2. **Keep an empty page without status:** rejected because it hides failure.
3. **Fabricate placeholder semantics:** rejected because Atlas never fabricates semantics.
4. **Embed original images or permanent URLs:** rejected because evidence access is not semantic processing and creates security/lifecycle problems.
5. **Return no SPR whenever any page fails:** rejected because useful semantics on other pages remain valuable.

## Relationship to Existing Contracts

The [processing overview](../architecture/atlas-processing-architecture-overview.md) explains layer ownership. The [Block Recovery Contract](../architecture/atlas-block-recovery-contract-v1.md) owns recovery ladder and viability principles; the [SPR contract](../contracts/structured-processing-result-v1.md) owns normalized representation; the [Provider Conformance Profile](../architecture/atlas-provider-conformance-profile-v1.md) governs provider behavior; and the [Document Core architecture](../architecture/document-core-structured-content-architecture.md) consumes processing results without interpreting provider payloads. This ADR selects page-topology policy without redefining those contracts.

## Implementation Follow-up

1. Add minimum first-class page-status representation.
2. Permit a topology-only degraded page when semantics survive elsewhere.
3. Add page-level warning and quality accounting.
4. Preserve stable original-page evidence identity.
5. Add focused mixed multi-page regression.
6. Add later authorized evidence-resolution support.
7. Add later Reader disclosure: “No usable semantic content was recovered for this page. View original page.” Block crops remain optional and require reliable geometry.

## Non-Goals

This ADR does not implement the policy, modify SPR schema, define storage APIs, signed URLs, authorization details, Reader UI, PDF rendering, block cropping, provider routing, capability negotiation, every future page status, or the zero-usable-output no-SPR boundary.

## Architecture Principles

Atlas preserves topology when semantic recovery fails locally; exposes failure explicitly; separates page existence from semantic success; never fabricates nodes to fill topology; treats evidence references as non-grants; preserves original evidence through authorized resolution; uses page inspection when block geometry is unavailable; and requires applications to depend on Atlas status/evidence contracts rather than provider payloads.
