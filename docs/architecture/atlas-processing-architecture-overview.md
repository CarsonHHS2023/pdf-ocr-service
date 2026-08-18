# Atlas Processing Architecture Overview

| Field | Value |
|---|---|
| Document Type | Architecture Overview |
| Approval Status | Draft |
| Version | v1.0 |
| Authority Domain | Atlas processing architecture, processing stages, and responsibility boundaries |
| Applies To | Provider, Provider Normalizer, Block Recovery, Structured Processing Result (SPR), Structured Content, Reader, Knowledge Graph, AI Applications, provider normalizers, and provider conformance declarations |

**Status:** Draft v1.0  
**Audience:** Architecture contributors, processing-engine developers, and future provider implementers.  
**Purpose:** High-level architectural guide. This document is informative and does not define new normative behavior.

## Vision

Atlas is a provider-independent semantic processing platform, not an OCR wrapper. It separates processing logic, semantic truth, provider capability, and data representation. No provider owns Atlas processing behavior; Atlas owns the contracts.

## Architecture Philosophy

Atlas favors truth before completeness, contract-driven processing, provider independence, deterministic identity, explicit degradation, stable provenance, and never fabricating semantics.

## Architecture Layers

```text
Provider
  ↓
Provider Normalizer
  ↓
Block Recovery
  ↓
Structured Processing Result (SPR)
  ↓
Structured Content
  ↓
Reader
  ↓
Knowledge Graph
  ↓
AI Applications
```

Each layer narrows provider-specific evidence into increasingly Atlas-owned representations. A downstream layer does not reinterpret retained provider payloads directly.

## Core Contracts

| Contract | Purpose | Inputs | Outputs | Consumers |
| --- | --- | --- | --- | --- |
| [Structured Processing Result Contract](../contracts/structured-processing-result-v1.md) | Defines the provider-independent normalized result representation | Normalized evidence | SPR | Persistence, later canonicalization |
| [Atlas Block Recovery Contract](atlas-block-recovery-contract-v1.md) | Defines truthful recovery across field, block, page, and result defects | Retained provider evidence | Recovery decisions, warnings, state | Provider normalizers |
| [Atlas Provider Conformance Profile](atlas-provider-conformance-profile-v1.md) | Defines how a provider declares externally observable capability | Provider capability declaration | Conformance profile | Provider implementers and reviewers |
| [Document Core Architecture](document-core-structured-content-architecture.md) | Defines the layered ownership model from Raw Result to Structured Content | Processing outputs | Architectural boundaries | All Atlas contributors |

## Information Flow

A provider produces retained Raw Result evidence. A provider-specific normalizer validates the retained boundary, maps page and semantic identities, applies Block Recovery, and emits an SPR. Later processes may derive Structured Content, Reader views, knowledge structures, and applications.

Raw Result evidence remains immutable. Provider provenance remains evidence. SPR is normalized but noncanonical. Structured Content is a later Atlas-owned semantic decision.

## Provider Model

Providers are capability providers. Atlas depends on provider capabilities, not provider implementation. This lets Paddle, MinerU, Docling, Azure Document Intelligence, Google Document AI, and future providers coexist behind the same Raw Result → SPR boundary. Capability declarations explain what a provider can preserve, recover, warn about, and prove.

## Recovery Model

Recovery is a conceptual ladder:

```text
Field
  ↓
Block
  ↓
Page
  ↓
Result
```

The ladder exists so loss of a representation does not automatically destroy trustworthy semantics, while structural contradictions cannot be hidden as successful output. The detailed rules belong to the Block Recovery Contract.

## Identity Model

Stable page, block, node, evidence, and ordering identities make normalization reproducible and auditable. Deterministic mapping ensures that equivalent retained evidence and normalization inputs lead to the same relationship decisions. Provenance connects every accepted semantic object back to retained source evidence.

## Quality Model

Coverage answers whether expected semantic content was represented. Fidelity describes how closely retained semantics preserve provider evidence and intended structure. Warnings record recoverable degradation; diagnostics explain failure that prevents or qualifies output. These dimensions remain distinct from provider lifecycle status.

## Extension Model

New providers add a conformance declaration and a provider normalizer rather than changing Atlas Core behavior. New semantic blocks evolve through the SPR and recovery contracts. New recovery rules are versioned contract decisions, not hidden adapter behavior.

## Future Architecture

Future architecture may add capability negotiation, capability discovery, provider certification, provider routing, cross-provider validation, and automatic conformance testing. These additions should strengthen contract observability without exposing provider implementation details to applications.

## Architecture Relationship Diagram

```text
Architecture Overview
  ↓
Block Recovery Contract ──→ Structured Processing Result Contract
  ↓                              ↓
Provider Conformance Profile     Document Core Architecture
  ↓                              ↓
Provider Normalizers             Structured Content
  ↓                              ↓
Providers                         Reader / Knowledge Graph / Applications
```

## Recommended Reading Order

1. **Overview** — establishes the map and ownership boundaries.
2. **Block Recovery Contract** — explains truthful recovery and degradation.
3. **SPR Contract** — defines the normalized representation.
4. **Provider Conformance Profile** — explains capability declarations.
5. **Document Core Architecture** — explains Raw Result, SPR, and Structured Content ownership.
6. **Provider-specific implementation** — applies the contracts to a concrete provider.

This order moves from architectural intent to recovery semantics, normalized data, provider capability, lifecycle ownership, and finally implementation detail.
