# Atlas Processing Documentation

| Field | Value |
|---|---|
| Document Type | Reference / Index |
| Approval Status | Accepted |
| Lifecycle Status | Active |
| Date | 2026-07-18 |
| Authority Domain | Navigation and discovery only |
| Applies To | `docs/processing` designs, procedures, reviews, and evidence |
| Related Governance | [Atlas Documentation Governance](../project/document-governance.md) |

## Purpose

This directory contains processing designs, transport and adapter designs, operational guidance, fixture guidance, reviews, analyses, results, and point-in-time evidence.

## Navigational Authority Note

This index is navigational. Child-document metadata and body evidence control each document's role, status, result, lifecycle, implementation state, and evidence boundary. This index does not promote approval, lifecycle, release, implementation, production-readiness, provider-certification, or conformance status. Point-in-time evidence remains bounded to its recorded dates, revisions, and scope. Contracts, ADRs, and Architecture documents retain authority only within their own declared domains.

## Architecture-facing Contracts and Cross-Layer References

| Document | Type | Status / Result | Role and Boundary |
|---|---|---|---|
| [Document Processing Contract](../architecture/document-processing-contract.md) | Architecture reference | See document metadata | External architecture-facing reference for processing behavior boundaries. |
| [Atlas Block Recovery Contract v1](../architecture/atlas-block-recovery-contract-v1.md) | Architecture reference | See document metadata | External recovery contract reference; authority remains in its declared domain. |
| [Atlas Provider Conformance Profile v1](../architecture/atlas-provider-conformance-profile-v1.md) | Architecture reference | See document metadata | External provider-profile reference; does not certify Processing documents. |
| [Structured Processing Result v1](../contracts/structured-processing-result-v1.md) | Contract reference | See document metadata | External SPR contract reference for structured-result boundaries. |
| [ADR-0001 Mixed Multi-page Recovery Policy](../adr/ADR-0001-mixed-multi-page-recovery-policy.md) | ADR reference | See document metadata | External ADR reference for recovery-policy navigation. |

## Processing Designs and Foundations

| Document | Type | Status / Result | Role and Boundary |
|---|---|---|---|
| [end-to-end-processing-integration-plan](end-to-end-processing-integration-plan.md) | Integration Plan | Implementation planning approved; no live provider call performed | Planning and responsibility sequencing for retained source, source transport, provider polling, and raw-result retention. |
| [end-to-end-processing-integration-service](end-to-end-processing-integration-service.md) | Integration Service Design | — | In-process coordinator design; no public routes, persistence, background workers, or live provider calls added by the document. |
| [non-persistent-processing-orchestration](non-persistent-processing-orchestration.md) | Orchestration Design | Component remains unused pending independent verification and a later integration task | One-attempt in-memory orchestration ending at Raw Processing Result retention. |
| [paddle-vl-structured-result-normalizer](paddle-vl-structured-result-normalizer.md) | Normalizer Design | — | Paddle-VL Raw Result normalization into provider-independent structured processing output. |
| [raw-processing-result-ingestion](raw-processing-result-ingestion.md) | Ingestion Design | — | Atlas-owned intake, validation, provenance, Storage retention, and handoff boundary for raw provider output. |

## Source Transport and Adapter Designs

| Document | Type | Status / Result | Role and Boundary |
|---|---|---|---|
| [paddle-vl-api-adapter-foundation](paddle-vl-api-adapter-foundation.md) | Provider Adapter Foundation | Adapter foundation implemented without production route integration, orchestration, persistence, storage ingestion, or production provider calls | Paddle-VL adapter foundation and provider protocol isolation boundary. |
| [private-source-transport-endpoint](private-source-transport-endpoint.md) | Private Endpoint Design | Endpoint implemented as a temporary M2 bridge for disposable Local/HF test deployment, not the final production source transport architecture | Provider-only byte-delivery endpoint; not a public download API. |
| [provider-reachable-source-transport](provider-reachable-source-transport.md) | Provider-Reachable Transport Design | Proposed; implementation not authorized | Proposed temporary provider-reachable transport architecture; no production durability claimed for current HF test posture. |
| [source-transport-grant-service](source-transport-grant-service.md) | Grant Service Design | Provider-independent in-memory transport grant domain implemented with no HTTPS route, Storage access, orchestration integration, persistence, or provider client behavior changes | Short-lived source-transport grant creation, validation, retrieval accounting, expiry, revocation, inspection, and cleanup boundaries. |

## Procedures and Operator Guidance

| Document | Type | Status / Result | Role and Boundary |
|---|---|---|---|
| [controlled-live-provider-smoke-procedure](controlled-live-provider-smoke-procedure.md) | Smoke Procedure | Historical | Historical one-job live-provider smoke procedure for a disposable test deployment. |
| [safe-processing-operator-entry](safe-processing-operator-entry.md) | Operator Guidance | — | Disposable M2 operator-only entry guidance; not a public product API. |
| [smoke-fixture-preparation](smoke-fixture-preparation.md) | Fixture Preparation Procedure | — | Controlled preparation of the smoke-test source fixture for the temporary H-E smoke workflow. |

## Results, Reviews, Analyses, and Preflight Evidence

See also the [Reviews index](../reviews/README.md).

| Document | Type | Status / Result | Role and Boundary |
|---|---|---|---|
| [controlled-live-provider-smoke-result](controlled-live-provider-smoke-result.md) | Smoke Result | PASS | Point-in-time controlled live-provider execution evidence for one disposable test-deployment smoke. |
| [paddle-vl-api-compatibility-review](paddle-vl-api-compatibility-review.md) | Compatibility Review | — | Point-in-time provider-protocol compatibility review between inspected Atlas adapter assumptions and inspected provider protocol. |
| [paddle-vl-api-fixture-analysis](paddle-vl-api-fixture-analysis.md) | Fixture Analysis | — | Offline provider-fixture analysis evidence; static fixtures only. |
| [source-transport-deployment-preflight](source-transport-deployment-preflight.md) | Deployment Preflight | PASS WITH BLOCKERS; later GO FOR M2-003H | Point-in-time deployment-preflight evidence; original result and later status remain distinct. |

## Fixture Inventories and Preparation Guidance

| Document | Type | Status / Result | Role and Boundary |
|---|---|---|---|
| [structured-processing-normalization-fixture-inventory](structured-processing-normalization-fixture-inventory.md) | Test Fixture Inventory | — | Synthetic fixture provenance, safety boundaries, coverage roles, mapping expectations, and non-implementation limits. |

## Processing Navigation Boundary

This index does not:

- define runtime behavior;
- change child-document metadata;
- infer approval, lifecycle, or release status;
- approve implementation;
- convert evidence into current normative authority;
- classify procedures as production runbooks;
- classify private endpoints as public APIs;
- claim provider certification, production readiness, release, or full conformance;
- move, rename, or reclassify documents outside their documented metadata and body evidence.
