# Engineering Principles

Atlas is one Document Intelligence Platform. Smart Reading OS and Smart Archive are peer applications over a shared Document Intelligence Core: Smart Reading OS helps people read faster, understand deeper, and remember longer; Smart Archive organizes documents, connects facts with evidence, and keeps needed information within reach.

## 1. Architecture Before Implementation

Important durable decisions should be understood before production-code work begins. Architecture discussions and ADRs reduce accidental coupling and keep implementation aligned with accepted boundaries.

## 2. One PR = One Independent Problem

Each PR should solve one independently reviewable problem. Small, scoped PRs make review, validation, rollback, and traceability easier.

## 3. Backward Compatibility First

Existing users, APIs, data, and workflows should continue to work while the platform evolves. Compatibility layers are preferred over disruptive changes when migrating toward new architecture.

## 4. Documentation Is Part of the Product

Markdown documentation in the repositories is the source of truth. Documentation should be updated when decisions, workflows, terminology, or contracts change.

## 5. Incremental Delivery

Large platform changes should be delivered through milestones and small tasks. Each merge should leave the repository buildable and deployable.

## 6. Protocols Are Stable

Public contracts and cross-service protocols should be treated as stable interfaces. Changes require explicit compatibility planning and validation.

## 7. Stateless Compute Does Not Own Business Data

ADR-001 establishes that `paddle-vl-api` is durable-business-stateless OCR compute, `pdf-ocr-service` is the durable business system of record, and `speed-reading-trainer` owns the reading presentation layer. OCR compute may manage temporary job state and artifacts, but it must not own durable documents, facts, learning records, or business workflows.

## 8. Evidence Over Assumptions

Engineering decisions should be grounded in observed code, documented contracts, test results, and explicit human decisions. If facts are unclear, mark them as pending instead of silently assuming.

## 9. Test Before Refactor

Before refactoring behavior, establish tests or validation that describe the current public contract. Refactors should preserve behavior unless a deliberate product decision changes it.

## 10. Preserve Public Contracts

APIs, reader behavior, OCR behavior, deployment behavior, and documented contracts should not change accidentally. Contract changes require clear scope, migration notes, and validation.

## 11. AI Work Meets Human Engineering Standards

AI-generated work must satisfy the same standards as human-written work. It must be reviewed, validated, documented, traceable to a task, and tested where appropriate.

## 12. Human Decision Authority

Codex may recommend. Humans decide.

If architecture, governance, naming, release, workflow, ownership, documentation, or engineering decisions are ambiguous, mark them as **TODO — Pending Decision**. Recommendations may be documented separately as **Codex Recommendation**, but recommendations are not accepted decisions.
