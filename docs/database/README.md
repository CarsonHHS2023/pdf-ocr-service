# Database Documentation

This directory collects Database documentation for reviews, foundation schema design, Alembic strategy, and migration operations. This README is an index for navigation only.

## Navigational Authority Note

Child-document metadata and explicit body evidence control each document's role, status, and boundary. This README does not create approval, lifecycle, release, implementation, policy, Contract, or normative architecture authority. Reviews remain bounded to their evidence scope and explicit assessment boundary where present. Architecture, ADR, Contract, and governance documents retain authority only within their own domains.

## Database Reviews and Current-State Evidence

| Document | Type | Status / Version | Role and Boundary |
|---|---|---|---|
| [current-database-review.md](current-database-review.md) | Current-State Review | — | Point-in-time database review; records observed persistence-layer evidence and review findings at its assessment boundary, while recommendations are not accepted architecture decisions. |

## Database Designs and Migration Guidance

| Document | Type | Status / Version | Role and Boundary |
|---|---|---|---|
| [alembic-strategy.md](alembic-strategy.md) | Alembic Strategy | — | Strategy baseline for Alembic and future database work; separates accepted project decisions from recommendations and documentation-only boundaries. |
| [foundation-schema-design.md](foundation-schema-design.md) | Foundation Schema Design | — | Documentation-only implementation design for the first foundation schema; identifies `Document`, `SourceFile`, relationship, and open implementation questions without changing code or creating release status. |
| [migration-operations.md](migration-operations.md) | Migration Operations | Revision: `0001_foundation_schema` | Operational guidance for Alembic commands, startup behavior, test strategy, SQLite foreign-key notes, and future production-data warnings; it is not governance policy or a database Contract. |

## Architecture-facing References

These links are provided only for navigation and do not transfer architecture, Contract, or governance authority into this Database README:

- [Persistence and Processing Foundation](../architecture/persistence-processing-foundation.md)
- [Document Core Information Model](../architecture/document-core-information-model.md)
- [Document Processing Contract](../architecture/document-processing-contract.md)
- [Documentation Governance](../project/document-governance.md)

## Database Navigation Boundary

Use this README to find Database documents and understand their high-confidence roles. Do not treat this index as schema authority, approval evidence, release authorization, production readiness, or a substitute for child-document metadata and explicit body evidence.
