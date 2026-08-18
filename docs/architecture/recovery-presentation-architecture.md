# Recovery Presentation Architecture

| Field | Value |
|---|---|
| Document Type | Architecture |
| Authority Domain | Recovery evidence, inspection, presentation, and degraded content behavior at the Recovery Presentation Layer boundary |
| Applies To | Recovery Presentation Layer, Structured Processing Result (SPR), Processing Core, Readers, APIs, downstream applications, recovery diagnostics, quality context, evidence references, and presentation contract |
| Implementation Status | Architecture boundary only; no reader/UI implementation, milestone-completion, delivery, or release authorization |
| Model Boundary | Presentation explains Processing Core recovery facts and does not replace SPR or establish semantic truth |
| Presentation Boundary | Provider-independent recovery explanation only; no concrete UI, schema, database, API, serialization, or rendering behavior |

**Status:** M4 architecture

## Purpose

The Recovery Presentation Layer communicates the outcome of recovery to its consumers without changing the semantic meaning established by the Atlas Processing Core and propagated through M4 Structured Content / Structured Document and derived projections. It makes the condition, quality, and evidence identity of recovered output understandable at the presentation boundary while preserving the distinction between complete, partial, degraded, unavailable, and failed trustworthy results.

Presentation is an explanation layer, not a semantic-processing layer. It does not add, remove, repair, select, reinterpret, or otherwise change semantic truth.

## Scope

The target Recovery Presentation boundary sits after provider-independent SPR facts have been carried through the M4 Structured Content / Structured Document boundary and into derived projections. It consumes approved recovery outcome and related provider-independent facts already established by the Processing Core and propagated by content/projection layers, then presents a stable explanation of those facts for Reader/API use.

Within this boundary, the layer is responsible for expressing recovery diagnostics, quality context, evidence references, and a presentation contract. These responsibilities describe what consumers may understand about an outcome; they do not create a new source of semantic truth, a replacement for SPR, or canonical persistence.

## Layering

```text
Processing Provider
  ↓
Raw Processing Result
  ↓
SPR with recovery/diagnostic facts
  ↓
Structured Content / Structured Document carrying recovery state
  ↓
derived projection carrying presentation-safe recovery information
  ↓
M5 Reader/API Recovery Presentation
```

Providers supply input to the Processing Core. The Processing Core normalizes provider output, preserves topology and deterministic identity, validates it, and performs truthful recovery into an SPR. M4 propagates applicable recovery facts into Structured Content / Structured Document and projection-ready forms without owning the full Reader product. M5 Reader/API Recovery Presentation consumes the projection boundary rather than deriving recovery interpretation from provider output or raw diagnostics.

The Recovery Presentation Layer never changes SPR or Structured Content / Structured Document. In particular, it does not alter semantic content, recovery state, provenance, identity, ordering, or topology established by the Processing Core and carried forward by M4. When approved recovery facts cannot truthfully establish an outcome, Presentation communicates that limitation; it does not compensate for it.

## Architectural Principles

### Semantic Truth Is Immutable

Semantic truth is established by the Processing Core. Presentation may explain the result of recovery, but it must not repair, enrich, suppress, or reinterpret that result into a different semantic claim.

### Presentation Is Provider-Independent

The presentation boundary is expressed in Atlas terms, not provider terms. Provider-specific behavior remains below the Processing Core boundary; downstream consumers receive a consistent explanation regardless of the provider that supplied the retained evidence.

### Diagnostics Describe, Not Decide

Diagnostics communicate recovery conditions and their significance. They do not make recovery decisions, determine semantic validity, or authorize a consumer to infer semantics that the Processing Core did not establish.

### Evidence References Are Identity, Not Access

Presentation may identify the evidence associated with an outcome so that it remains traceable. An evidence reference establishes identity and relationship only; it is not a retrieval mechanism, an authorization decision, or access to original material.

### Presentation Remains Deterministic

Equivalent SPR inputs must lead to equivalent presentation meaning. Presentation must not introduce nondeterministic interpretation, ordering, or outcome changes that obscure the deterministic identity and recovery decisions of the Processing Core.

### Explanation Preserves Recovery Boundaries

Presentation preserves the Processing Core's distinction between recoverable degradation, qualifying conditions, and the absence of trustworthy output. It must not make a degraded outcome appear complete or an unavailable outcome appear semantically usable.

## Major Responsibilities

### Diagnostics

Presentation communicates the diagnostics and recovery conditions already established by the Processing Core in terms suitable for consumer understanding. It preserves their role as explanations of degradation, qualification, or unavailable output, without turning them into new recovery policy or semantic decisions.

### Quality

Presentation communicates the quality context associated with the recovered outcome. This includes the Processing Core's distinction between coverage and fidelity and the significance of partial recovery. Presentation does not calculate OCR confidence, establish quality thresholds, or redefine the Processing Core's quality assessment.

### Evidence References

Presentation maintains the association between an explained outcome and its evidence identity. This supports traceability across future consumers while keeping evidence identity separate from evidence access, retrieval, display, or authorization.

### Presentation Contract

Presentation defines the provider-independent boundary through which Readers, APIs, and downstream applications understand recovery outcomes. The contract preserves semantic state, recovery explanation, quality context, and evidence identity as distinct concerns. It does not prescribe concrete representations, transport, serialization, or consumer interface behavior.

## Out of Scope

The Recovery Presentation Layer does not define or own:

- Reader UI.
- Storage.
- Authorization.
- Signed URLs.
- Evidence Resolver.
- Original Page Viewer.
- Original Block Viewer.
- Provider-specific presentation.
- OCR confidence algorithms.
- Layout repair.

It also does not define JSON schemas, programming-language classes, database tables, APIs, field-level serialization, validation rules, or field names.

## Roadmap v3 ownership

### M3

M3 establishes normalized recovery facts, diagnostics, warning semantics, partial/no-usable-content distinctions, evidence, semantic normalization, deterministic identity, validation, topology preservation, provider conformance, and the SPR. The Processing Core therefore establishes processing truth in a noncanonical SPR.

### M4

M4 propagates applicable recovery facts into Structured Content / Structured Document and projection-ready forms. It preserves absence-versus-failure and degraded/partial semantics, but it does not own the full Reader product or user-facing Recovery Presentation.

### M5

M5 maps approved recovery facts into user-facing Reader/API Recovery Presentation. It communicates complete, partial, degraded, unavailable, and failed states. It must not fabricate content or expose raw provider diagnostics without an approved mapping.

### Temporary bridge

Any direct SPR-to-Reader path is temporary, noncanonical, isolated through an adapter/projection boundary, not canonical persistence, migration/removal governed, and insufficient by itself for M4 or M5 completion. The final target architecture is Structured Content / Structured Document → projection → Recovery Presentation, not direct Reader dependence on SPR.

## Future Evolution

Later milestones may build on this boundary with an Evidence Resolver, Reader, authorized original-page access, analytics, and telemetry. Those systems may use presentation's provider-independent explanations and evidence identities, but their design, access policy, user behavior, aggregation, and operational concerns are outside this architecture.

Future evolution must preserve the boundary defined here: Processing Core establishes semantic truth; Recovery Presentation explains it; consumer systems act on the explanation without gaining authority to modify it.
