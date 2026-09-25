# S0.3.7 event schema and candidate association review — 2026-09-20

Status: **Unsupported-schema admission reproduced and fixed in PR #50; candidate not deployed. Scoped identity checks passed; full S0.3.7 remains open.**

## Source and scope

Inspected deployed Staging `593d65199c6e21571e0094014d41dc30269f9adc`.
TXT persistence/contract and Reader persistence/contract modules were compared
byte-for-byte with that revision. Local tests use the composed runtime plus
PR #50's earlier numeric guards and this schema fix. All fixtures are synthetic;
there was no live database access, upload, Provider request or deployment.

## P2 — Unsupported event versions were interpreted as the current schema

The baseline's SQL projection bounded event payload bytes but did not check
`ProcessingEvent.schema_version`. Upload/Reader had a later family-specific
envelope check; Provider and generic resource paths did not get that protection.

With an otherwise valid single-scope Provider download fixture, changing only
the download event's schema from `atlas.processing.event.v1` to
`atlas.processing.event.v999` still produced an **observed 0.25-second**
download measurement, with no incomplete-payload flag. This is synthetic
evidence of incorrect admission, not a claim that accepted live runs used v999.

[PR #50](https://github.com/CarsonHHS2023/pdf-ocr-service/pull/50), current head
`d9f608b5223b0d600b33c23e3042a7788e077664`, corrects the
[checked-in baseline projection](https://github.com/CarsonHHS2023/pdf-ocr-service/blob/d9f608b5223b0d600b33c23e3042a7788e077664/app/processing/s0_baseline.py).
The SQL CASE projects payload text only when its byte length is bounded and
the event schema exactly matches the supported producer schema constant.
Otherwise it projects NULL. The row is retained in the event window and
counts; existing decode-incomplete and uninspectable-family handling rejects
affected evidence. Filtering the row out in WHERE would hide contradictory
evidence and is deliberately avoided.

This uses the existing incomplete-payload flag for a payload that cannot be
interpreted under the supported schema. It does not add a schema migration,
new metric, version negotiation or a family-specific payload-format rewrite.
Source metadata remains independently usable; unrelated event measurements
may become partial under the existing snapshot-incompleteness policy.

## Verification

Twenty-two new composed collector cases cover:

- Exact v1, future v999, empty and trailing-space schemas across Provider
  completion, sharding decision, source route, transport terminal and download.
- A valid download alongside an unsupported-version shadow event: the latter
  remains visible and prevents a misleading complete measurement.
- A future-version resource heartbeat: its numeric payload cannot become generic
  peak-RSS evidence.
- SQL projection cardinality, suppressed payload text, incomplete/oversize flags,
  independent source bytes and strict JSON output.

The local targeted run finished **170 passed, 2 skipped** across baseline,
Provider download, Reader, upload/Reader and real TXT-worker suites. The skipped
cases require isolated PostgreSQL: upload/Reader concurrent slots and lock
timeout, and TXT repeatable-read projection. CI supplies the database gates.
Existing composition idempotence tests passed.

All five exact-head workflows passed on attempt 1:

- [Durable Processing Events CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35537644045): success.
- [S0 Baseline CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35537644056): success.
- [Provider 20 MiB Staging CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35537644026): success.
- [Provider Transport Sharding CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35537644037): success.
- [Staging Backend Integration CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35537644029): success.

The integration and artifact-verification jobs succeeded; deployment was skipped.
The PostgreSQL-backed CI gates passed. No retry was needed for this head.
This candidate remains unmerged and undeployed.

## Candidate and revision checks

| Path | Verified checks | Retained boundary |
|---|---|---|
| Reader publication | Exact candidate ID and document join to its processing-run reference; same document and succeeded run; no latest-run guess | Writer establishes relational provenance |
| Reader collection | Stable candidate hash and backend revision within an open; matching frontend/backend revisions across accepted opens; request/terminal completeness | It compares retained event identities; it does not independently rejoin candidate/source-unit tables |
| Upload/Reader join | Exact open, candidate hash, source hash and revisions; initial-open coverage and containing duration | Browser timing/frontend revision remain client-reported |
| TXT collection | One dispatch and one candidate for exact run; document/source ownership, matching structured-result reference, eligible source and terminal states | Complete semantic-content correctness is not established by timing evidence |
| TXT source units | At least one unit, with no foreign source or non-text-flow unit | This is source ownership, not a new content/recovery completeness audit |
| TXT envelope/revision | Fixed slots, event schema, run/document, severity/page fields, common identity, terminal candidate hash, current revision and unchanged revision during collection | Current-revision eligibility does not relabel historical evidence |

The [Reader contract](s0-3-5-reader-open-observability-contract-2026-09-02.md)
explicitly assigns the candidate/run association to its writer. Existing tests
cover missing/wrong-document candidates, candidate/revision changes within an
open, and TXT source/dispatch/candidate/revision conflicts. This review does not
claim that a mutually consistent set of forged retained Reader rows has been
independently matched against candidate tables by the offline collector.

## Subsequent field-type pass — 2026-09-25

The [field-type review](s0-3-7-field-type-review-2026-09-25.md) records two
additional retained enum-field crashes and their fix in PR #50 at
`6fc4809592166d4695bd8450ec24ef38a441b130`. Its CI describes that later candidate. The schema
reproduction and exact-head results above remain the earlier checkpoint.

## Remaining work and provenance

- Full event-family severity/page/unknown-name policy and cross-family revision
  semantics are not signed off by the generic schema check.
- Reader offline relational revalidation and full cross-family snapshot
  consistency remain distinct from the currently documented writer guarantee.
- The [earlier numeric review](s0-3-7-provider-numeric-review-2026-09-20.md)
  retains its exact-head measurements and the previous CI retry record. Its
  local allocation probes are not upload peak-memory evidence.
- S0/M5 remain In Progress at **17/19**. Complete upload peak memory and full
  preprocessing CPU remain unimplemented. Historical PDF/TXT acceptance,
  frontend preview and the deferred large fixture remain unchanged.
