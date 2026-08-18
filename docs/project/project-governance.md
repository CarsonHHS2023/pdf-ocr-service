# Project Governance

| Field | Value |
|---|---|
| Document Type | Project Governance |
| Authority Domain | Project development and repository workflow governance |
| Applies To | Product identity, repository changes, pull requests, protected branches, CI gates, merge workflow, release policy, ADR lifecycle, documentation ownership, and AI-assisted development within this repository |
| Related Governance | Documentation governance remains governed separately by `docs/project/document-governance.md` |

## Product Identity

- Product name: **Atlas**
- Product descriptor: **Document Intelligence Platform**
- Accepted applications: **Smart Reading OS** and **Smart Archive**

Atlas is one Document Intelligence Platform. Smart Reading OS and Smart Archive are peer applications over a shared Document Intelligence Core: Smart Reading OS helps people read faster, understand deeper, and remember longer; Smart Archive organizes documents, connects facts with evidence, and keeps needed information within reach.

## Current Governance Model

The project is currently maintained by one person.

## Public Repository and Archive

The canonical development repository is public. The pre-public repository history is retained separately as a private archive and is not part of the public source history.

The public repository must never contain active credentials, private keys, production database exports, user-uploaded documents, runtime output, or private diagnostic artifacts.

## License

No open-source license has been selected yet. Public visibility does not by itself grant permission to copy, modify, redistribute, or commercially use the code beyond rights provided by applicable law.

Do not create or change a `LICENSE` file without an explicit project decision.

## GitHub Flow

Use:

```text
main
→ feature branch
→ pull request
→ CI
→ merge
```

Preferred merge strategy: **Squash Merge**.

## Repository Protection Policy

- The canonical repository is **Public**.
- `main` and `staging` must be protected with GitHub rulesets.
- Direct development on `main` is prohibited.
- Production changes require a Pull Request and passing required Backend CI.
- `staging` changes should use Pull Requests and must pass the relevant staging/integration checks before promotion.
- Force pushes and branch deletion must be disabled for protected branches.
- Secrets used by CI/deployment must be stored in GitHub Secrets or an external secret manager, never in source files.
- Pull requests from untrusted forks must not receive production or staging credentials.

## Engineering Discipline

- Never develop directly on `main`.
- Every production change uses its own feature branch.
- Every production change requires a Pull Request.
- Never merge with failing CI.
- Prefer Squash Merge.
- Delete merged branches when they are no longer needed.
- Documentation changes should normally also use Pull Requests.
- Small, independently reviewable PRs are preferred.

## CI Expectations

Production PRs must pass CI. Documentation-only PRs need documentation validation.

Every merge should leave the repository buildable and deployable.

## Secret and Data Hygiene

- Never commit `.env` files, service-account JSON, tokens, passwords, DSNs containing credentials, private keys, database snapshots, or object-storage credentials.
- Never commit user-uploaded source documents or generated runtime output.
- If a credential is accidentally committed, revoke or rotate it immediately; deleting it from the latest tree is not sufficient.
- Public test fixtures must be synthetic, generated, or explicitly approved for redistribution.

## Versioning

Use **Semantic Versioning**.

## Release Policy

Prefer milestone-based releases. The current canonical roadmap is Atlas Roadmap v2 and currently spans M1 through M5; future milestones may be added by explicit decision.

## ADR Lifecycle

Use these ADR statuses:

- Proposed
- Accepted
- Superseded
- Deprecated
- Rejected

Do not delete obsolete ADRs.

## Documentation Ownership

Markdown files inside the repositories are the source of truth for project documentation, architecture, workflow, and terminology.

## AI-assisted Development

This project uses AI extensively. AI-generated code must satisfy the same engineering standards as human-written code.

AI-generated work must be:

- reviewed
- validated
- documented
- traceable to a task
- tested where appropriate

Codex may recommend. Humans decide.

## Pending Governance Decisions

The following are **TODO — Pending Decision** items:

- future public license
- future contributor model
- future multi-maintainer governance
- release automation

## Codex Recommendations

No Codex recommendations are accepted decisions. Any future recommendation should be explicitly labeled **Codex Recommendation** and reviewed by a human before adoption.
