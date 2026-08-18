# Atlas Architecture Decision Records

| Field | Value |
|---|---|
| Document Type | Reference / Index |
| Approval Status | Accepted |
| Lifecycle Status | Active |
| Date | 2026-07-18 |
| Authority Domain | Navigation and discovery only |
| Applies To | `docs/adr` and `docs/architecture/adr` ADR discovery |
| Related Governance | [Atlas Documentation Governance](../project/document-governance.md) |

## Purpose

This is the preferred discovery index for Atlas Architecture Decision Records (ADRs). ADR authority comes from each ADR's declared scope and status, not from inclusion in this index.

## Governance Notice

This index provides navigation and discovery only. It does not change the status, authority, lifecycle, or meaning of any indexed document.

Acceptance of this index is limited to navigation and discovery. It does not accept, reject, or reclassify any indexed document.

## ADR Locations

New ADRs should normally be discoverable from `docs/adr`. Existing domain-local ADRs under `docs/architecture/adr` remain in place and are included here for discovery. Indexing those files here does not relocate, reclassify, accept, reject, or supersede them.

## ADR Index

| ADR | Location | Declared Status | Decision Scope | Notes |
|---|---|---|---|---|
| ADR-0001: Mixed Multi-Page Recovery Policy | [ADR-0001-mixed-multi-page-recovery-policy.md](ADR-0001-mixed-multi-page-recovery-policy.md) | `Accepted` | Selects page-topology policy for Atlas Raw Result to Structured Processing Result normalization. | Central ADR file. |
| ADR-001: Service Boundaries | [../architecture/adr/ADR-001-service-boundaries.md](../architecture/adr/ADR-001-service-boundaries.md) | `Accepted` | Records service-boundary decisions for architecture-local organization. | Domain-local ADR remains under `docs/architecture/adr`. |

## ADR Process Boundary

This index does not:

- accept or reject an ADR;
- supersede an ADR;
- define ADR numbering;
- resolve duplicate namespaces;
- move ADR files.
