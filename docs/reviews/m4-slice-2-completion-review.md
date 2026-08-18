# M4 Slice 2 Completion Review — Persistence, Selection, ProcessingRun, and Transformation-Planning Readiness

| Field | Value |
|---|---|
| Document Type | Review |
| Status | Completed |
| Review Type | Point-in-time implementation readiness review |
| Review Date | 2026-07-23 |
| Review Status | Completed |
| Milestone Status | Unchanged — M4 remains In Progress |
| M5 Status | Unchanged — M5 remains Planned |
| Normative | No |
| Scope | M4 Slice 2A-2E completion and readiness to plan SPR to Structured Content candidate transformation |
| Baseline Commit | `59f78d63f9f6bb7d467bfdcd943ff2d9a92f2e5f` |
| Reviewed PR Range | PR #123 through PR #132; Slice 2 emphasis on PR #127 through PR #132 |

## Governance and authority boundary

This review is a point-in-time evidence record. It is not an ADR, contract,
roadmap decision, milestone-status statement, implementation plan approval, or
production-readiness claim. It preserves the orthogonality required by
`docs/project/document-governance.md`: document status, milestone status,
review status, implementation status, and test status are separate. Merged code
and tests do not automatically mark M4 complete. This task is not authorized to
issue a Milestone Status statement; therefore M4 remains In Progress and M5
remains Planned.

Authoritative sources for this review are the accepted governance, roadmap,
milestone, and ADR documents listed below. Implementation and tests are
non-normative descriptive evidence of merged behavior. PR descriptions and CI
status are non-authoritative supporting evidence.

## Scope

In scope:

- Slice 2A schema;
- Slice 2B candidate repository;
- Slice 2C explicit selection;
- Slice 2D ProcessingRun provenance;
- Slice 2E integrated verification;
- Slice 1 in-memory, validation, serialization, fixture, regression, scale,
  and determinism dependencies required by Slice 2;
- readiness to plan the SPR to Structured Content candidate transformation
  slice.

Out of scope and not authorized:

- SPR transformation implementation;
- Reader behavior or Reader cutover;
- Structured Document projection implementation;
- APIs;
- production OCR/provider orchestration;
- backfill, deletion, or retention execution;
- M5 functionality;
- production release;
- milestone-status changes.

## Reviewed sources

Authoritative governance and planning sources:

- `docs/project/document-governance.md`.
- `docs/roadmap/roadmap-v3-decision.md`.
- `docs/roadmap/roadmap.md`.
- `docs/milestones/M4.md`.
- `docs/milestones/M5.md`.
- `docs/architecture/adr/ADR-002-structured-content-lifecycle-and-selection.md`.
- `docs/architecture/adr/ADR-003-structured-content-shape-and-transformation.md`.
- `docs/architecture/adr/ADR-004-provenance-evidence-assets-and-processing-runs.md`.
- `docs/architecture/adr/ADR-005-projection-compatibility-migration-and-retention.md`.
- `docs/plans/m4-slice-2-structured-content-persistence-plan.md`.
- `docs/reviews/README.md`.

Descriptive implementation and test sources:

- `app/structured_content/model.py`, `serialization.py`, `validation.py`,
  `repository.py`, `persistence_mapping.py`, `selection_repository.py`,
  `selection_service.py`, `selection_types.py`, and `errors.py`.
- `app/processing_runs/`.
- `app/models.py`.
- `alembic/versions/0001_foundation_schema.py`,
  `0002_structured_content_persistence_schema.py`, and
  `0003_processing_runs.py`.
- `tests/fixtures/structured_content/v1/**`.
- `tests/structured_content/**`.
- `tests/test_structured_content_schema.py`,
  `tests/test_structured_content_migrations.py`,
  `tests/test_structured_content_repository.py`,
  `tests/test_structured_content_selection.py`,
  `tests/test_processing_run_schema.py`,
  `tests/test_processing_run_migrations.py`,
  `tests/test_processing_run_repository.py`,
  `tests/test_structured_content_provenance_integration.py`,
  `tests/test_structured_content_migration_chain.py`,
  `tests/test_structured_content_integrated_lifecycle.py`,
  `tests/test_structured_content_integrated_transactions.py`,
  `tests/test_structured_content_integrated_concurrency.py`, and
  `tests/test_structured_content_integrated_scale.py`.
- `.github/workflows/backend-tests.yml`.

## Baseline verification

The reviewed branch starts at `59f78d63f9f6bb7d467bfdcd943ff2d9a92f2e5f`,
which is the repository merge commit for PR #132. Repository history also shows
PR #119 through PR #132 merged in order, including the accepted M4 ADRs, Slice 1
foundation, Slice 2 plan, Slice 2A schema, Slice 2B repository, Slice 2C
selection, Slice 2D ProcessingRun, and Slice 2E integrated verification.

The working tree was clean before documentation changes. No staged or untracked
files were present. The current branch was `work`, at latest observed main
baseline in this workspace. Required Backend CI for PR #132 could not be
verified locally from an authenticated GitHub status API in this environment;
repository evidence shows the Required Backend CI workflow definition and PR
#132 merge commit, so this review records CI as supporting evidence rather than
claiming a fresh remote status verification.

## PR evidence table

| PR | Slice | Purpose | Merge commit | Result |
|---|---|---|---|---|
| #123 | M4 Slice 1A | In-memory Structured Content types | `b43b4f9` | Merged; model foundation present. |
| #124 | M4 Slice 1B | Validation/contracts | `39085e5` | Merged; validator and validation tests present. |
| #125 | M4 Slice 1C | Golden fixtures | `6a0afa6` | Merged; valid/invalid canonical fixtures present. |
| #126 | M4 Slice 1D | Regression, scale, determinism | `ba35148` | Merged; regression and scale tests present. |
| #127 | M4 Slice 2 plan | Persistence plan | `012d4d2` | Merged; plan is Proposed/non-normative and used as commitment source. |
| #128 | M4 Slice 2A | Persistence schema | `f9f5828` | Merged; ORM and Alembic 0002 present. |
| #129 | M4 Slice 2B | Candidate repository | `c433815` | Merged; repository and round-trip tests present. |
| #130 | M4 Slice 2C | Explicit selection | `48b303c` | Merged; selection repository/service and tests present. |
| #131 | M4 Slice 2D | ProcessingRun provenance | `dcc7afb` | Merged; ProcessingRun model, migration, repository, and integration tests present. |
| #132 | M4 Slice 2E | Integrated verification | `59f78d6` | Merged; lifecycle, transactions, concurrency, migration-chain, and scale tests present. |

## Slice 2A schema review

Slice 2A is satisfied for planning readiness. `app/models.py` contains
normalized relational rows for candidates, pages, nodes, root ordering,
evidence, warnings, assets, renditions, table cells, selection, and
ProcessingRun. Alembic 0002 adds the Structured Content graph and selection
schema; Alembic 0003 adds ProcessingRun. Schema tests verify absence of
candidate `current`/`accepted`/`selected` flags, indexes and ownership
constraints, provider-payload exclusion, and migration invariants. The schema is
additive and coexists with legacy rows. It does not implement Reader projection,
backfill, or retention.

## Slice 2B candidate repository review

Slice 2B is satisfied for planning readiness. The candidate repository validates
before persistence, checks document ownership, optionally validates
ProcessingRun provenance, writes the graph inside nested transaction boundaries,
reconstructs deterministically, returns idempotent equivalent retries, rejects
same-ID conflicts, and raises bounded corruption errors for invalid persisted
state. Repository tests cover canonical fixture round-trips, invalid fixture
rejection, idempotency/conflict behavior, ownership/listing, caller rollback,
corruption detection, and bounded scale. Candidate creation does not select a
candidate.

## Slice 2C selection review

Slice 2C is satisfied for planning readiness. Selection is an explicit
zero-or-one row per document. Absence of a row is valid. First selection requires
`expected_version=0`, replacement increments `selection_version`, same-candidate
selection is idempotent when the expected version matches, stale updates raise
conflicts, rollback is explicit re-selection of a prior candidate, and
cross-document candidates are rejected. Selection does not mutate candidate rows
and no select-latest helper is present. Selection history is intentionally not
implemented in Slice 2; the plan chose one mutable row and left future history to
a later slice if needed. This is nonblocking.

## Slice 2D ProcessingRun review

Slice 2D is satisfied for planning readiness. ProcessingRun is durable but
minimal: provider-independent run identity, document/source ownership, status
vocabulary, bounded transitions, idempotency key, Raw Result and SPR refs,
metrics/extensions as deterministic JSON, and safe error fields. The repository
owns no commits, checks SourceFile ownership, rejects idempotency conflicts, and
raises bounded corruption errors for malformed JSON or unsupported status.
Candidate persistence validates same-document ProcessingRun linkage and source
evidence compatibility when a run ref is present. ProcessingRun is provenance
input only; it is not content, not selection, not Reader state, not queue/lease
truth, and not automatic promotion.

## Slice 2E integrated verification review

Slice 2E is satisfied for planning readiness as CI regression characterization,
not as a production SLA. Integrated tests cover happy-path lifecycle, multiple
runs and candidates, explicit replacement and rollback, failed/cancelled run
boundaries, degraded and no-usable valid candidates, cross-document protection,
outer rollback, failure injection, stale selection conflicts, candidate/run
idempotency conflicts, migration chain, data preservation, candidate corruption,
selection corruption, ProcessingRun corruption, representative legacy value
preservation, 100-page/1,000-node candidate scale, 500-cell table scale,
evidence/assets/warnings scale, 100-run scale, query characterization,
determinism, DB-row immutability, no automatic selection, and no orchestration
expansion. These are regression budgets and characterization tests; they are not
production throughput, latency, retention, or reliability guarantees.

## Commitment matrix

| Area | Plan commitment | Merged evidence | Tests/evidence | Result | Finding |
|---|---|---|---|---|---|
| Schema | Normalized relational candidate persistence | `app/models.py`; Alembic 0002 | schema and migration tests | Satisfied | None |
| Schema | Immutable candidate versions | insert-only repository; no candidate update/delete APIs | repository, selection, integrated immutability tests | Satisfied | None |
| Schema | Complete graph persistence | candidate/page/node/root/evidence/warning/asset/rendition/table rows | repository fixture round-trips and scale tests | Satisfied | None |
| Serialization | Canonical round-trip | canonical serializer compared after reconstruction | repository and integrated tests | Satisfied | None |
| Repository | Idempotent candidate creation | existing candidate canonical comparison | repository and concurrency tests | Satisfied | None |
| Repository | Conflicting same-ID rejection | conflict errors on changed same ID | repository and concurrency tests | Satisfied | None |
| Repository | Atomic write behavior | nested transaction, caller-owned rollback | repository and integrated transaction tests | Satisfied | None |
| Repository | Deterministic reconstruction | ordered reconstruction and canonical equality | regression, repository, scale tests | Satisfied | None |
| Selection | Explicit zero-or-one selection | `structured_content_selection` row per document | selection and integrated tests | Satisfied | None |
| Selection | No automatic promotion | candidate create excludes selection | repository, selection, integrated tests | Satisfied | None |
| Selection | Optimistic selection versioning | `selection_version` and expected-version checks | selection and concurrency tests | Satisfied | None |
| Selection | Explicit rollback selection | rollback delegates to explicit set selection | selection and lifecycle tests | Satisfied | None |
| Selection | Cross-document selection rejection | repository check and composite FK | selection/lifecycle tests | Satisfied | None |
| ProcessingRun | Minimal durable ProcessingRun | model, migration 0003, repository | ProcessingRun tests | Satisfied | None |
| ProcessingRun | Provider-independent run identity | `processing_run_ref` as durable identity | repository tests | Satisfied | None |
| Provenance | Candidate/run same-Document validation | candidate repository checks run document | provenance integration tests | Satisfied | None |
| Provenance | Nullable provenance support | candidate refs nullable | model, fixture, repository tests | Satisfied | None |
| Ownership | SourceFile ownership | ProcessingRun source_file check | ProcessingRun repository tests | Satisfied | None |
| Provenance | Raw Result/SPR references | refs on candidate and run | repository/integration tests | Satisfied | None |
| Boundary | No copied provider payload | no provider payload/blob columns in SC tables | schema tests | Satisfied | None |
| Boundary | ProcessingRun not content | separated tables and APIs | ADR/plan plus tests | Satisfied | S2R-D01 tracks later orchestration out of scope |
| Boundary | ProcessingRun not selection | selection table separate; success never selects | lifecycle tests | Satisfied | None |
| Boundary | ProcessingRun not workflow truth | no queue/lease/coordinator behavior | repository review | Satisfied | S2R-D01 |
| Corruption | Corruption detection | bounded corrupt errors | repository/integrated corruption tests | Satisfied | None |
| Migration | Upgrade/downgrade | Alembic 0002/0003 | migration and chain tests | Satisfied | None |
| Coexistence | Legacy coexistence | additive tables; no legacy mutation | migration/lifecycle preservation tests | Satisfied | None |
| Transactions | Caller transaction ownership | repositories flush only; no commits | transaction tests | Satisfied | None |
| Concurrency | Candidate/run/selection race behavior | conflict paths | concurrency tests | Satisfied as characterization | None |
| Scale | Bounded scale | 100 pages/1,000 nodes, 500 cells, assets/evidence/warnings, 100 runs | scale tests | Satisfied as CI budget | S2R-N01 notes no production SLO |
| Ordering | Deterministic ordering | order columns and ordered reconstruction | regression/repository/scale tests | Satisfied | None |
| Exclusion | No Reader/projection implementation | no Reader/projection changes in Slice 2 evidence | scope inspection | Satisfied | S2R-O01 |
| Exclusion | No backfill/retention implementation | no backfill/retention changes in Slice 2 evidence | scope inspection | Satisfied | S2R-O02 |

## Schema and migration conclusion

Current Alembic head is `0003_processing_runs`. There is exactly one head by
revision-file inspection: 0001 has no predecessor, 0002 points to 0001, and 0003
points to 0002. The chain is linear: `0001_foundation_schema` to
`0002_structured_content_persistence_schema` to `0003_processing_runs`.
Migration tests cover upgrade, downgrade, and re-upgrade. Migration-chain tests
show 0002 Structured Content data and selection survive the upgrade to 0003 and
survive downgrade back from 0003 to 0002. No known migration issue blocks
transformation planning.

Transformation planning should initially reuse existing candidate persistence
and should not assume a new schema migration. Any newly discovered schema need
must be separately justified in a later authorized planning or implementation
task. This review does not authorize a migration.

## Candidate persistence conclusion

The candidate repository provides validation before persistence, complete atomic
graph persistence, canonical equivalence, equivalent retry idempotency, conflict
detection, corruption detection, deterministic reconstruction, document
ownership checks, ProcessingRun provenance validation, caller-owned transaction
behavior, bounded repository errors, scale behavior, and no automatic selection.
The remaining limitation is that persistence scale tests are regression budgets,
not production SLOs. This is nonblocking for transformation planning.

## Selection conclusion

Zero selection is valid. First selection, replacement, optimistic
`selection_version`, stale conflicts, same-candidate idempotency, explicit
rollback, cross-document protection, corruption handling, and caller-owned
transaction behavior are implemented and tested. Select-latest behavior is
absent by design. Selection history is intentionally absent from Slice 2 because
the accepted plan selected a one-row current pointer and did not require history
for Slice 2. Lack of selection history is nonblocking and remains a future
decision only if a later milestone requires it.

## ProcessingRun conclusion

ProcessingRun is sufficient provenance input for transformation planning. It
provides a minimal durable boundary, stable identity, status vocabulary,
transitions, idempotent create behavior, ownership checks, candidate linkage,
Raw Result and SPR refs, corruption handling, transaction ownership, and no
provider payload. It intentionally omits queue, lease, production orchestration,
and automatic selection behavior. Transformation planning may treat
ProcessingRun as provenance input, not as a transformation coordinator.

## Integrated verification conclusion

Slice 2E proves merged behavior under repository tests and CI-style regression
characterization. It does not prove production SLA, release readiness,
retention/deletion policy, live-provider orchestration, Reader cutover, or M4
completion. The tests are adequate to begin planning the next transformation
slice because they protect persistence, selection, provenance, migration,
corruption, concurrency, determinism, scale, and legacy coexistence boundaries.

## DEC-019

- Exact title/question: `M4-DEC-019 | Initial persistence types/backfill scope`.
- Current status: `Nonblocking for 2A` in the Slice 2 plan; ADR-005 states the
  exact initial supported list remains a later implementation-plan decision and
  that M4-DEC-019 remains open or later planning-bound.
- Source documents: `docs/plans/m4-slice-2-structured-content-persistence-plan.md`
  and `docs/architecture/adr/ADR-005-projection-compatibility-migration-and-retention.md`.
- Reason it remains open or resolved: resolved for Slice 2 only as candidate
  persistence independent of legacy backfill type support; not resolved for
  future backfill/projection supported document types.
- Impact on transformation planning: nonblocking. The next planning task may
  plan SPR-to-candidate transformation against provider-independent SPR and
  existing candidate persistence without selecting backfill document-type scope.
- Blocks transformation planning: No.
- Latest acceptable decision point: before any backfill/projection slice.

## DEC-020

- Exact title/question: `M4-DEC-020 | Performance SLOs and batch sizes`.
- Current status: `Nonblocking for 2A` in the Slice 2 plan; ADR-005 defers exact
  SLOs and batch sizes under M4-DEC-020.
- Source documents: `docs/plans/m4-slice-2-structured-content-persistence-plan.md`
  and `docs/architecture/adr/ADR-005-projection-compatibility-migration-and-retention.md`.
- Reason it remains open or resolved: deferred for production-readiness/release
  planning; Slice 2 uses bounded regression and persistence scale tests instead
  of production SLAs.
- Impact on transformation planning: nonblocking. The next planning task can
  define transformer test budgets and characterization without declaring
  production SLOs.
- Blocks transformation planning: No.
- Latest acceptable decision point: before production-readiness or release
  planning.

## Findings

### Blocking findings

None.

### Nonblocking findings

| ID | Title | Evidence | Impact | Classification | Required action | Owner/slice |
|---|---|---|---|---|---|---|
| S2R-N01 | Slice 2 scale tests are regression budgets, not production SLOs | Slice 2 plan defers M4-DEC-020; integrated scale tests characterize bounded workloads | Planning may begin, but production SLOs must not be inferred | Nonblocking | Keep DEC-020 tracked; decide before production-readiness/release planning | Later production-readiness/release planning |

### Deferred findings

| ID | Title | Evidence | Impact | Classification | Required action | Owner/slice |
|---|---|---|---|---|---|---|
| S2R-D01 | Production orchestration/queue/lease behavior remains outside ProcessingRun | ADR-004 and Slice 2 plan define ProcessingRun as minimal provenance, not workflow truth | Transformation planning must not treat ProcessingRun as coordinator | Deferred | Address only in a later authorized orchestration/reliability slice if needed | Later M4/M5+ orchestration planning |
| S2R-D02 | Selection history is not implemented | Slice 2 plan uses one current selection row; tests validate current pointer semantics | Does not block planning; future audit/history needs require separate decision | Deferred | Revisit only if later projection, audit, or product requirements require history | Later lifecycle/projection planning if needed |
| S2R-D03 | Backfill/projection document-type scope remains under DEC-019 | ADR-005 leaves initial supported list later planning-bound | Does not block transformer planning from provider-independent SPR | Deferred | Decide before backfill/projection slice | Backfill/projection planning |

### Out-of-scope findings

| ID | Title | Evidence | Impact | Classification | Required action | Owner/slice |
|---|---|---|---|---|---|---|
| S2R-O01 | Reader projection and cutover are not Slice 2 outputs | M4 and Slice 2 scope exclude Reader/projection implementation | No impact on transformation planning readiness | Out of scope | Keep excluded from next planning unless explicitly scoped later | M5/Reader or later M4 projection planning |
| S2R-O02 | Retention/deletion/backfill execution are not Slice 2 outputs | ADR-005 and Slice 2 plan exclude execution | No impact on transformation planning readiness | Out of scope | Keep excluded unless separately authorized | Later retention/backfill planning |
| S2R-O03 | Production release and M4 completion are not authorized | Governance and milestone docs require explicit status/release evidence | Prevents overclaiming; no planning blocker | Out of scope | Do not claim release readiness or M4 completion from this review | Milestone/release governance |

## Transformation planning prerequisites

| Prerequisite | Status | Evidence and limitation |
|---|---|---|
| Stable provider-independent SPR contract | Ready with limitation | M3 SPR v1 fixtures and contract exist; the next plan must map only accepted SPR vocabulary and preserve unknown/recovery behavior. |
| Stable Structured Content in-memory model | Ready | Slice 1A model and fixtures are merged. |
| Stable validator | Ready | Slice 1B validator and validation tests are merged. |
| Stable canonical serializer | Ready | Slice 1 serialization and golden fixture tests are merged. |
| Stable candidate persistence | Ready | Slice 2B repository plus integrated verification are merged. |
| Stable provenance linkage | Ready | Slice 2D ProcessingRun and candidate/run validation are merged. |
| Stable test fixtures | Ready | Structured Content and SPR fixture suites are merged. |
| Known unknown-mapping behavior | Ready with limitation | Unknown node preservation and warnings are fixture-tested; exact transformer mapping rules remain for Slice 3 planning. |
| Known recovery behavior | Ready with limitation | recovery summaries, degraded/no-usable cases, and validation are tested; transformer-specific degradation policy remains for Slice 3 planning. |
| Known asset/evidence conventions | Ready | ADR-004 plus model/schema/tests establish locator/reference conventions without provider payload bytes. |
| Deterministic identity inputs | Ready with limitation | Candidate identity/lineage/ref fields exist; exact transformer identity derivation is Slice 3 planning work. |
| Selection independence | Ready | Candidate creation and ProcessingRun success do not automatically select content. |

## Readiness decision

READY WITH NONBLOCKING FINDINGS.

Slice 2 commitments are sufficiently satisfied to begin planning the SPR to
Structured Content candidate transformation slice. No blocking finding remains.
This decision authorizes planning only. It does not authorize transformation
implementation, schema migration, automatic promotion, Reader projection,
backfill, retention, M4 completion, M5 start, production release, or production
readiness claims.

## Next planning boundary

Suggested next planning title: **M4 Slice 3 — SPR to Structured Content
Transformation Plan**.

The next planning task may address:

- deterministic SPR to in-memory candidate transformation;
- mapping rules from provider-independent SPR vocabulary;
- stable candidate identity and lineage inputs;
- page/root/node ordering;
- typed attribute construction;
- evidence-anchor creation;
- warnings and unknown mappings;
- recovery/degradation handling;
- asset and rendition references;
- table-cell mapping;
- ProcessingRun provenance input;
- validation before persistence;
- orchestration boundary between transformer and repository;
- unit, golden, property, regression, and scale test strategy;
- explicit exclusions and implementation slices.

The next planning task must not automatically include persistence redesign,
selection/promotion, Reader projection, APIs, provider execution, legacy
backfill, retention, production orchestration, or M5 features. Implementation
requires a separate approved implementation task.

## Conclusion

The merged Slice 2A-2E foundation is complete and stable enough to begin
transformation planning, with nonblocking findings tracked. M4 remains In
Progress. M5 remains Planned. This review is non-normative and point-in-time.
