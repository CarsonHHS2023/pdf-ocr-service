# Development Workflow

## Required Development Workflow

Every task should follow the documented repository workflow:

```text
Task
↓
Feature branch
↓
Codex implementation
↓
Commit
↓
Pull Request
↓
Required Backend CI
↓
Review
↓
Squash Merge
↓
Delete branch
```

This workflow is mandatory even though GitHub cannot technically enforce required
status checks for the current GitHub Free private repository. Atlas relies on
engineering discipline rather than platform enforcement at this stage.

## Git Flow

Use GitHub Flow:

```text
main
→ feature branch
→ pull request
→ Required Backend CI
→ review
→ squash merge
→ delete branch
```

Preferred merge strategy: **Squash Merge**.

## Engineering Discipline

- Never develop directly on `main`.
- Every production change uses its own feature branch.
- Every production change requires a Pull Request.
- Never merge with failing CI.
- Prefer Squash Merge.
- Delete merged branches.
- Documentation changes should normally also use Pull Requests.
- Small, independently reviewable PRs are preferred.

## Task and PR Requirements

Every task and PR should define:

- Milestone
- Task ID
- Problem
- Context
- Scope
- Non-goals
- Acceptance Criteria
- Validation
- Compatibility
- Rollback (when applicable)

## Validation Expectations

Production PRs must pass CI. Documentation-only PRs need documentation validation.

Every merge should leave the repository buildable and deployable.

## Issue Lifecycle

```text
Roadmap
→ Milestone
→ Issue
→ PR
→ Merge
→ Milestone Review
```

## Ambiguous Decisions

Codex must not invent project decisions. If a decision is ambiguous, document it as **TODO — Pending Decision** and keep any **Codex Recommendation** clearly separate from accepted decisions.

## Evidence-driven PR workflow

Use evidence-driven review for implementation, design, and closeout PRs:

1. Give Codex a scoped implementation/design instruction.
2. Review the Codex Summary.
3. Issue an independent verification instruction.
4. Review verification evidence; repeat if defects remain.
5. Confirm Required CI and any necessary human checks.
6. Merge deliberately.

Summary is a claim. Evidence earns approval.

Implement confidently. Verify independently. Merge deliberately.

Documentation-only PRs may use proportionate verification, but Summary alone is
still not acceptance.

## Merge Gate checklist

Before merge, confirm:

- Scoped task completed.
- Summary reviewed.
- Independent verification completed.
- Defects resolved.
- Documentation accurate.
- Required CI green.
- Human checks completed.
- Squash Merge.
- Feature branch deleted.
