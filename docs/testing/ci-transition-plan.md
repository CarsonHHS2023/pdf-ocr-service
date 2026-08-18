# M1-001A CI Transition Plan

Status: Proposal only. This document contains Codex recommendations, not accepted decisions. No workflow, test, dependency, production-code, or schema changes were made.

## Target properties for future required CI

Future required pull-request CI should:

- complete without GPU;
- avoid model downloads;
- avoid real PaddleOCR/PaddleOCR-VL inference;
- avoid real `paddle-vl-api` calls;
- be deterministic and secret-free;
- protect current Reader contracts;
- fail on real lint, format, import-order, and test errors;
- run on every pull request, including untrusted forks;
- remain useful during Alembic, storage, and Document Core changes.

## Proposed CI layers

### Layer 1 — Required PR checks

Purpose: fast deterministic checks for every PR.

Proposed contents:

- Import/collection smoke: `python -m pytest --collect-only -q` or a narrower collection command after dependencies are split.
- Unit tests that do not import or instantiate local OCR models.
- Reader API contract tests for:
  - `POST /api/v1/upload` TXT behavior and fake-provider PDF behavior;
  - `GET /api/v1/books` Bookshelf-shaped list responses;
  - `GET /api/v1/books/{book_id}` detail responses;
  - `GET /api/v1/books/{book_id}/content` TXT and fake PDF content;
  - `DELETE /api/v1/books/{book_id}` public behavior;
  - `GET /api/v1/images/{image_id}` success and missing-image behavior.
- Mocked service tests for image marker and content assembly contracts.
- Ruff/Black/isort or current lint equivalents, configured to fail on real errors.
- After Alembic exists: migration checks that validate heads, upgrade, and current schema creation through migrations instead of `Base.metadata.create_all`.

Proposed time budget: 5 to 8 minutes on a standard GitHub Ubuntu CPU runner after dependency split. Pending Decision: final budget should be confirmed after measuring the first lightweight workflow.

### Layer 2 — Mocked integration

Purpose: verify `pdf-ocr-service` orchestration without loading a real OCR model.

Recommended design:

- Introduce an OCR provider seam in a later implementation task.
- Use a fake provider returning deterministic page/block outputs, including text, title, toc, image, table, and failure cases.
- Verify PDF upload status transitions, page persistence, content assembly, `image_id` marker generation, image retrieval, and deletion cleanup.
- Keep these tests CPU-only, no network, no secrets, no model downloads.
- Run on PRs if the layer remains within the Layer 1 time budget; otherwise run as a separate but still deterministic check.

### Layer 3 — External `paddle-vl-api` smoke

Purpose: verify compatibility with the future remote OCR compute service.

Recommended workflow properties:

- `workflow_dispatch` only at first, or trusted protected branches only.
- Use a tiny deterministic test PDF fixture.
- Authenticate with GitHub Secrets; do not expose secrets to fork PRs.
- Submit a job, poll with a strict timeout, validate minimal structured result fields, and fail on contract drift.
- Use low concurrency and explicit timeout controls.
- Do not run for untrusted fork pull requests.
- Do not add secrets in this documentation task.

### Layer 4 — Legacy local OCR

Purpose: retain diagnostic coverage for the old local PaddleOCR/PaddleOCR-VL/MinerU/PaddleX architecture while it remains useful.

Recommended treatment:

- Keep legacy tests available via explicit marker commands such as `pytest -m slow` or a manual workflow.
- Do not block normal PRs unless a human explicitly approves local OCR as a required gate.
- Archive or move tests only after fake-provider and remote-smoke replacements exist.
- Clearly label tests that require GPU, local model availability, large downloads, or sample PDFs.

## Proposed staged transition

### Stage 0 — Document and classify current tests

This M1-001A review creates the baseline classification and transition plan.

### Stage 1 — Fix workflow syntax and establish minimal reliable PR checks

Smallest safe implementation PR:

- Fix duplicate `workflow_dispatch` in `.github/workflows/backend-tests.yml` or create a new minimal required workflow while leaving the legacy workflow intact/manual.
- Configure lint checks to fail only after the repository is made compliant or the lint scope is intentionally narrowed.
- Remove heavyweight local OCR tests from default triggers only after human confirmation.
- Add job timeout, least-privilege permissions, and pip cache if dependencies remain manageable.

### Stage 2 — Strengthen Reader API contract tests

- Formalize tests for Bookshelf-shaped list/detail responses.
- Add deterministic success/404 tests for `GET /api/v1/images/{image_id}`.
- Preserve `book_id`, `image_id`, status, content, and marker contracts through future Document Core changes.
- Mark original-file retention expectations as pending until M1 storage/source-file decisions are accepted.

### Stage 3 — Introduce OCR provider seam and fake-provider tests

- Add a provider abstraction in a later production-code task.
- Replace local-model orchestration assertions with fake-provider integration tests.
- Keep `paddle-vl-api` network calls out of required PR CI.

### Stage 4 — Add trusted external `paddle-vl-api` smoke workflow

- Add a manual/trusted workflow using secrets, a tiny PDF, job polling, strict timeout, and result validation.
- Confirm fork PR safety before enabling any secret-backed workflow.

### Stage 5 — Retire or relocate superseded local OCR tests

- Move old local OCR tests to legacy/manual directories or marker groups after replacements are accepted.
- Retire only tests whose contracts are covered by fake-provider or external smoke tests.
- Preserve pure formatting and protocol tests that remain provider-independent.

## Roadmap recommendation

Codex Recommendation — Human Confirmation Required:

The evidence supports inserting a CI/test baseline before Alembic implementation because current tests and workflows rely heavily on `Base.metadata.create_all`, heavyweight local OCR dependencies, and non-failing lint checks. A proposed M1 mapping is:

| Current task | Proposed task | Notes |
| --- | --- | --- |
| M1-001 Introduce Alembic Migration Framework | M1-002 Introduce Alembic Migration Framework | Alembic should follow a reliable baseline so migration checks can become meaningful. |
| M1-002 API Contract Regression Tests | M1-003 API Contract Regression Tests | Reader API contracts can be strengthened after minimal CI is reliable, or partially included in M1-001. |
| New prerequisite | M1-001 Test and CI Baseline | Fix CI syntax, dependency/test split decisions, markers, and minimal required checks. |

No task renumbering was performed. Human confirmation is required before roadmap numbers are changed.

## Recommended first implementation PR

Codex Recommendation — Human Confirmation Required:

The smallest safe implementation PR after this review should focus on workflow correctness and minimal reliable checks, not test rewrites:

1. Fix the duplicate `workflow_dispatch` key in `.github/workflows/backend-tests.yml`.
2. Add workflow timeout, permissions, concurrency cancellation, and dependency cache.
3. Make lint behavior explicit. Either keep lint advisory with clear naming or make a narrowly scoped lint job fail CI after confirming current violations.
4. Stop running heavyweight local OCR tests on default main pushes or move them behind manual input only, if humans approve that trigger change.
5. Do not change production OCR behavior, dependencies, schemas, or tests in the same PR.

## Pending decisions

- Whether to preserve or renumber M1 task IDs.
- Whether to patch the existing workflow or create a new minimal required workflow while preserving the legacy workflow.
- Official Python version support matrix.
- Future dependency file names and ownership.
- Whether local MinerU-Popo remains inside `pdf-ocr-service` after remote OCR migration.
- Exact source-file/original-PDF retention compatibility contract.

## Next Recommended Task

Implement a narrowly scoped CI baseline PR: fix the existing workflow syntax, add safe workflow controls, and establish one lightweight required PR check that collects and runs deterministic Reader/API unit tests without running heavyweight local OCR tests by default.
