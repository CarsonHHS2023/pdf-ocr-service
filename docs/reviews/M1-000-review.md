# M1-000 Review — Project Engineering Foundation

## Status

Completed

## Review date

2026-07-12

## Objective

Establish Atlas's engineering governance, roadmap, terminology, and development
workflow before production-code infrastructure work begins.

## Deliverables completed

M1-000 completed the documentation foundation needed before M1 production
infrastructure work:

- [Roadmap](../roadmap/roadmap.md)
- [Engineering principles](../engineering/engineering-principles.md)
- [Development workflow](../engineering/development-workflow.md)
- [Repository conventions](../engineering/repository-conventions.md)
- [Project governance](../project/project-governance.md)
- [Project glossary](../project/project-glossary.md)
- [README documentation index](../../README.md#engineering-documentation)

## Confirmed decisions

The following decisions were already accepted in the project documentation and
are recorded here without adding new decisions:

- Product name: **Atlas**.
- Product descriptor: **Smart Reading OS**.
- Technical category: **Document Intelligence Platform**.
- Repository responsibilities follow
  [ADR-001 Service Boundaries](../architecture/adr/ADR-001-service-boundaries.md).
- Development workflow uses GitHub Flow.
- Preferred merge strategy is Squash Merge.
- Versioning direction is Semantic Versioning.
- Release preference is milestone-based releases.
- ADR lifecycle statuses are Proposed, Accepted, Superseded, Deprecated, and
  Rejected.
- Markdown documentation in the repositories is the source of truth for project
  documentation, architecture, workflow, and terminology.
- The project is currently maintained by one person.
- AI-generated work must meet the same standards as human-written work.
- Codex may recommend, but humans decide.

## Lessons learned

- Engineering documentation should precede infrastructure changes.
- Shared terminology reduces ambiguity across repositories.
- Current-state review should rely on inspected evidence rather than assumed
  repository behavior.
- Cross-repository contracts must be identified before backend refactoring.
- AI recommendations must remain separate from accepted decisions.
- Small, independently verifiable tasks are safer than large rewrites.

## What went well

- Platform identity was clarified.
- Service boundaries were formalized through ADR-001.
- Current and target architecture were separated.
- Repository responsibilities became explicit.
- A milestone/task naming system was established.
- Existing reader compatibility was elevated into a formal engineering concern.

## What could be improved

- Cross-repository access should be verified earlier in future review tasks.
- Documentation PRs should include snapshot dates and inspected revisions where
  applicable.
- Project status updates should be kept synchronized with merged work.
- Tool availability such as markdownlint should be defined in CI later rather
  than assumed locally.

These observations are not new accepted policy unless they are already captured
in the project governance, workflow, or engineering principles.

## Remaining technical debt

Known next foundation items for M1 are:

- no migration framework;
- insufficient API contract regression coverage;
- no storage abstraction;
- original uploaded PDFs are not durably retained;
- no compatibility-safe Document / SourceFile foundation;
- page/image blobs remain coupled to the current persistence model.

Later OCR integration work remains outside M1 foundation closeout:

- OCR remains coupled to the existing in-process path until a later milestone.

## Roadmap impact

No milestone restructuring is required.

## Next recommended task

M1-001 Introduce Alembic Migration Framework

Schema evolution is required for future Document Core work. The current
`create_all` pattern is not sufficient as the long-term production migration
strategy, and migration tooling should exist before adding durable models such as
Document, SourceFile, ProcessingRun, Node, Fact, or related records.

## Closure statement

M1-000 is complete. Atlas may proceed to M1-001 Introduce Alembic Migration
Framework.
