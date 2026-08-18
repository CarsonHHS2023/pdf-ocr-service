# Atlas Provider Conformance Profile v1

| Field | Value |
|---|---|
| Document Type | Conformance Profile |
| Approval Status | Draft |
| Version | v1.0 |
| Authority Domain | Provider conformance requirements for Atlas Raw Result → Structured Processing Result (SPR) providers |
| Applies To | All Atlas Raw Result → Structured Processing Result (SPR) providers |
| Related Contracts | [Atlas Block Recovery Contract v1.0](atlas-block-recovery-contract-v1.md); [SPR v1 contract](../contracts/structured-processing-result-v1.md) |
| Conformance Target | [Atlas Block Recovery Contract v1.0](atlas-block-recovery-contract-v1.md); [SPR v1 contract](../contracts/structured-processing-result-v1.md); [Document Core architecture](document-core-structured-content-architecture.md) |

**Status:** Draft v1.0  
**Scope:** Provider Capability Contract  
**Normative Language:** RFC 2119  
**Applies to:** All Atlas Raw Result → Structured Processing Result (SPR) providers.

## Purpose

This profile specifies how a document-processing provider demonstrates conformance to Atlas Processing Core. Atlas Core never depends on provider implementation; it depends only on provider conformance. Provider-specific behavior is permitted when the externally observable Atlas contract is satisfied.

## Relationship to Other Contracts

This profile requires a provider to demonstrate capabilities required by the [Atlas Block Recovery Contract v1.0](atlas-block-recovery-contract-v1.md), the [SPR v1 contract](../contracts/structured-processing-result-v1.md), and the [Document Core architecture](document-core-structured-content-architecture.md). It does not redefine their semantic, recovery, or canonicalization rules.

## Provider Capability Model

Every provider MUST advertise capabilities rather than implementation details. Capability declarations cover supported block families, metadata, geometry, confidence, formulas, tables, unknown-block preservation, recovery behavior, warnings, deterministic identity, ordering, coverage, and fidelity.

## Mandatory Conformance Areas

A provider MUST document supported semantic blocks; required and optional fields; recovery and fatal behavior; warning catalog; deterministic identity and ordering policies; provenance and coverage guarantees; known unsupported features; lossy transformations; and implemented contract version.

## Recovery Conformance

Providers MUST implement the Block Recovery Contract. They MAY be stricter where retained evidence is insufficient, but MUST NOT weaken Atlas guarantees, fabricate semantics, or hide material degradation.

## Identity Conformance

Providers MUST provide stable page identity, block identity, ordering, and evidence ordering. Skipping an earlier block MUST NOT renumber later valid blocks. Identity decisions MUST be reproducible from identical retained inputs and normalization configuration.

## Semantic Conformance

Providers MUST preserve supported semantic meaning and MUST NOT fabricate OCR text, tables, geometry, formulas, confidence, captions, or relationships. Directly retained fallback representations MAY be used only as permitted by the recovery contract.

## Coverage Conformance

Providers MUST declare expected semantic coverage, known unavoidable loss, optional-field omissions, and unknown-block preservation. They MUST distinguish missing supported semantics from harmless representational absence.

## Warning Conformance

Providers MUST publish provider-independent warning codes, meanings, recoverable situations, and diagnostic categories. Warning records MUST be safe, deterministic, and free of retained content, secrets, paths, URLs, or raw payload excerpts.

## Quality Conformance

Providers MUST describe coverage limitations, fidelity limitations, known approximation behavior, and unsupported semantic families. Quality facts MUST NOT silently redefine complete/partial state as a numeric score.

## Capability Declaration

A provider declaration MUST publish at least:

| Field | Requirement |
| --- | --- |
| Provider name and contract version | MUST |
| Supported blocks and metadata | MUST |
| Required/optional fields | MUST |
| Recovery features and fatal conditions | MUST |
| Unknown-block policy | MUST |
| Warning catalog | MUST |
| Identity and ordering policy | MUST |
| Coverage and fidelity notes | MUST |
| Known limitations | MUST |

## Conformance Matrix

| Capability | Required | Optional | Provider Declares |
| --- | --- | --- | --- |
| Recovery | Yes | Profiles | Field/block/page behavior |
| Warnings | Yes | Extended catalog | Codes and meanings |
| Identity | Yes | External identity hints | Stability policy |
| Ordering | Yes | Reading-order detail | Ordering guarantees |
| Coverage | Yes | Numeric measures | Coverage limits |
| Fidelity | Yes | Scores | Fidelity limits |
| Unknown blocks | Yes | Rich preservation | Retention policy |
| Geometry | Yes when supplied | Polygons/segments | Coordinate support |
| Tables | Yes as declared | Structured cells | Fallback policy |
| Formula | Yes as declared | Multiple encodings | Encoding support |
| Metadata | Yes when retained | Provider extensions | Safe metadata policy |

## Compliance Levels

**Level A — Basic normalization:** stable page/block mapping, declared supported blocks, and safe no-SPR failures.  
**Level B — Recovery compliant:** Level A plus Block Recovery conformance, warning catalog, unknown-block preservation, and deterministic degradation behavior.  
**Level C — Full Atlas conformance:** Level B plus complete declared coverage/fidelity behavior, conformance fixtures, deterministic evidence ordering, and externally reviewable capability declaration.

## Architecture Principles

1. Atlas depends on contracts rather than implementations.
2. Capability is more important than provider identity.
3. Unknown capability is preferable to hidden behavior.
4. Conformance MUST be externally observable.
5. Recovery behavior is contractual.
6. Providers MUST preserve safe provenance and deterministic identity.

## Future Evolution

Future versions MAY add capability negotiation, versioned provider profiles, automatic certification, conformance testing, and provider scorecards.
