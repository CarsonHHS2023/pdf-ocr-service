# Atlas Block Recovery Contract v1.0

| Field | Value |
|---|---|
| Document Type | Recovery Contract |
| Approval Status | Draft |
| Version | v1.0 |
| Authority Domain | Provider-independent block recovery behavior and Structured Processing Result semantics for Atlas Processing Core |
| Applies To | All Raw Result → Structured Processing Result (SPR) normalizers |
| Related Contracts | [SPR v1 contract](../contracts/structured-processing-result-v1.md) |

| Metadata | Value |
| --- | --- |
| Status | Draft v1.0 |
| Scope | Provider-independent Atlas Processing Core contract |
| Applies to | All Raw Result → Structured Processing Result (SPR) normalizers |
| Milestone origin | M3 |
| Normative keywords | RFC 2119-style usage |

## Normative Language

**MUST** and **MUST NOT** state mandatory conformance requirements. **SHOULD** and **SHOULD NOT** state strong recommendations with documented exceptions. **MAY** states a permitted option. These keywords apply to Atlas provider normalizers.

## Purpose

This contract governs truthful recovery while transforming retained provider-specific results into Atlas Structured Processing Results (SPR). It prioritizes trustworthy semantic preservation over maximizing apparent output.

## Scope

It covers provider normalization, field/block/page/result recovery, SPR state selection, warnings, diagnostics, quality, provenance, and deterministic identity. It excludes Structured Content canonicalization, Reader rendering, enrichment, reconstruction of tables/formulas, cross-page reconciliation, provider retries, and transport.

## Design Goals

Normalizers MUST preserve trustworthy semantics and provenance, distinguish optional-field loss from semantic loss, retain bounded unknown evidence, fail safely on structural contradictions, preserve deterministic identity, prevent content leakage in errors, and keep provider lifecycle independent from Atlas semantic state.

## Core Semantic Model

Provider lifecycle state describes execution. Atlas semantic state describes normalized trustworthiness: **provider completed does not imply Atlas complete**. Semantic identity is the minimum retained information that truthfully establishes a block. Optional representation refines it. Recoverable degradation loses representation while retaining trustworthy semantics. A fatal contradiction makes page/result trust impossible. Usable semantic output is at least one truthfully normalized semantic block with valid page/provenance linkage.

## Recovery Ladder

```text
Field → Block → Page → Result
omit invalid optional field → retain/omit semantic block → retain/omit usable page → complete/partial/no SPR
```

At each boundary a normalizer MUST recover only when the lower boundary remains truthful. It MUST escalate when page structure, mapping, provenance, or usable output is insufficient.

## Field-Level Recovery

Optional invalid fields MAY be omitted. Required semantic fields MUST NOT be fabricated. Missing harmless optional fields do not automatically make an SPR partial; material loss of retained supported semantics does. Geometry, confidence, and rich representations MUST NOT be repaired, coerced, or invented.

## Block-Level Recovery

A block MUST be retained when its minimum semantic identity remains truthful. A block MUST be omitted when required semantic identity is unavailable. A safe fallback MAY be retained only when directly present in retained provider data. Omission of supported retained semantics MUST produce partial when useful output remains. Skipped blocks MUST create no synthetic nodes, observations, or evidence.

## Page-Level Recovery

Valid page identity, mapping, dimensions, and rotation are prerequisites. A page is semantically usable only if at least one usable block remains. Empty semantic pages MUST NOT be emitted merely to preserve page count. An unusable page MAY be omitted only when partial coverage/provenance represents that omission truthfully; otherwise no SPR is allowed.

## Result-Level Recovery

`complete` means no material supported-semantic loss. `partial` means useful trustworthy output exists with explicit degradation. No SPR means trust boundaries, page structure, mapping, or usable output are insufficient. `invalid` MAY be used only where already supported by the SPR contract.

## Required and Optional Fields

Each provider mapping MUST classify fields by block family. Required fields establish semantic identity. Optional fields refine geometry, confidence, presentation, provenance, or alternate representations. The same field MAY be required for one semantic family and optional for another.

## Unknown Provider Blocks

Bounded unknown blocks SHOULD be retained as provider-independent unknown evidence with a safe warning and minimal namespaced provenance. Raw provider payload MUST NOT be copied. Unbounded or structurally unsafe unknown content MUST NOT be normalized.

## Data Fabrication Policy

Normalizers MUST NOT fabricate OCR text, geometry, confidence, table cells, spans, header roles, list items/markers, formula LaTeX/MathML, captions/relationships, crops/assets, provider IDs, or provider metadata. They MAY normalize directly supplied values through Unicode normalization, validated coordinate conversion, source-page-number normalization, provider-type mapping, and serialization canonicalization. Normalization changes representation; fabrication creates unsupported meaning.

## Deterministic Identity and Ordering

Mappings MUST use stable original provider page/block identity or ordinal. Skipping an earlier block MUST NOT renumber later valid blocks. Page roots MUST contain only accepted node IDs in stable provider order, and evidence ordering MUST remain deterministic. Identical retained bytes plus identical normalization inputs MUST produce identical mapping and ordering decisions; test contexts MAY inject deterministic ID factories and clocks.

## Warning and Diagnostic Model

Warnings describe recoverable degradation; diagnostics describe failure preventing or qualifying SPR production. They MAY include safe page identity, local ordinal, controlled category, field category, and reason code. They MUST NOT include OCR text, raw JSON, HTML/Markdown, URLs, secrets, tokens, absolute paths, or raw exception text. Fixed codes/messages SHOULD be preferred.

## Provenance Model

Accepted blocks produce observations, nodes, and evidence. Field-degraded accepted blocks retain provenance but omit invalid fields. Skipped blocks produce no fabricated semantic objects; safe warnings, quality facts, and permitted extensions record degradation. Bounded unknown blocks MAY retain minimal namespaced classification.

## Coverage and Fidelity Model

**Coverage** is whether expected semantic content was retained and represented. **Fidelity** is how accurately retained semantics preserve provider evidence and intended structure. SPR complete/partial expresses material coverage/degradation; quality records fidelity and warnings. Numeric fidelity scores MAY evolve later without redefining complete/partial. Retaining provider table text without unavailable cells preserves some coverage, but loss of retained supported table structure is material and therefore partial in v1.0.

## Unified Recovery Matrix

| Condition | Required action | SPR outcome | Warning/diagnostic | Provenance treatment |
| --- | --- | --- | --- | --- |
| Harmless optional field missing | Omit field | Complete | Optional warning | Accepted evidence without field |
| Optional field invalid, identity retained | Omit field | Partial if material | Field warning | Evidence without invalid field |
| Supported block degraded with fallback | Retain direct fallback | Partial | Block warning | Accepted fallback evidence |
| Supported block unavailable | Omit block | Partial/no SPR | Block warning/diagnostic | No synthetic objects |
| Bounded unknown block | Retain as unknown | Complete if no supported loss | Unknown warning | Minimal extension/evidence |
| Page has usable blocks | Retain page | Complete/partial | As applicable | Normal page roots |
| Page has no usable blocks | Omit only with explicit coverage | Partial/no SPR | Page warning/diagnostic | No empty semantic page |
| Page structural contradiction | Stop | No SPR | Diagnostic | No output |
| Mapping/source contradiction | Stop | No SPR | Diagnostic | No output |
| One unusable page among valid pages | Retain valid pages only if coverage is explicit | Partial | Page warning | Explicit omission provenance |
| No usable semantic output | Stop | No SPR | Diagnostic | No fabricated content |
| Provider completed, Atlas degraded | Preserve truth | Partial | Warning/quality | Provider lifecycle remains provenance |

## Architecture Principles

1. Atlas MUST never fabricate semantic content.
2. Optional field loss is distinct from semantic loss.
3. Normalizers MUST recover safely when trustworthy output remains.
4. Unknown bounded evidence is preferable to silent loss.
5. Provider lifecycle and Atlas semantic state are independent.
6. Deterministic identity and order are invariants.
7. Warnings describe recovery; diagnostics describe failure.
8. Page Mapping is orthogonal to Block Recovery.
9. Recovery MUST preserve safe provenance.
10. Truthfulness is more important than apparent completeness.
11. Coverage and fidelity are distinct.
12. Recovery MUST NOT leak retained content through error records.

## Provider Conformance Requirements

Each provider normalizer MUST document supported block families, required and optional fields, direct fallbacks, recoverable field/block failures, fatal page/result failures, warning codes, state effects, deterministic identity policy, provenance behavior, and fixture/test coverage. Provider rules MAY be stricter but MUST NOT violate this contract.

## Milestone Ownership

**M3-001D** owns provider-specific interpretation/recovery, warning production, semantic fallback, and mapper state/quality facts. **M3-001E** owns generic SPR schema/reference/state, warning/extension, and geometry/confidence validation. **M3-001F** owns fixture/oracle/mutation hardening, warning-safety, deterministic-order, and recovery-matrix coverage. Later Structured Content owns canonical reconstruction, table cells, cross-page relations, reader semantics, and enrichment.

## Non-Goals

This contract does not reconstruct missing semantics, repair invalid provider data, choose retries, define storage policy, define Reader presentation or canonical Structured Content, define numeric OCR accuracy, or guarantee equivalent fidelity across providers.

## Examples

*Non-normative.* A figure with invalid bbox retains figure semantics, omits geometry, becomes partial, and emits a warning. A table with malformed rich structure but retained text keeps an unstructured table without invented cells and is partial. A formula retains a valid directly supplied representation while omitting an invalid secondary representation; it is complete only when no material supported semantics were lost. A bounded unknown block remains unknown with warning and minimal extension. A page with only unusable blocks is not an empty semantic page; it is partial only with explicit omission coverage, otherwise no SPR. Provider completion with Atlas degradation yields partial.

## Future Evolution

Future versions MAY add richer fidelity models, numeric confidence aggregation, cross-provider conformance profiles, block-family companion contracts, page-omission provenance, and table/formula/list fidelity levels.

## Versioning and Change Control

v1.0 is the initial normative recovery contract. Incompatible semantic changes require a major version. Clarifications that do not change outcomes MAY use minor documentation revisions. Provider normalizers SHOULD reference the contract version they implement; deviations MUST be documented and tested.

See the [SPR v1 contract](../contracts/structured-processing-result-v1.md) and the [Document Core architecture](document-core-structured-content-architecture.md).
