# S0.3.7 retained field-type review — 2026-09-25

Status: **Two enum-field crashes reproduced and fixed in PR #50; unmerged and undeployed. Full S0.3.7 remains open.**

## Source and reproduction

Staging remains `593d65199c6e21571e0094014d41dc30269f9adc`.
This pass starts from PR #50 head
`d9f608b5223b0d600b33c23e3042a7788e077664`, which includes the previous
numeric and schema guards. The four edited files were compared byte-for-byte
with that exact head before editing. No live database, upload or Provider call
was used.

Two collector membership checks admit JSON values before establishing that
they are strings:

- Storage I/O: `stage not in _S0_STORAGE_IO_STAGES`, in the helper owned by
  `scripts/apply_s0_transport_terminal_collector.py`.
- Provider source route: `route not in SOURCE_ROUTES`, in
  `app/s0_transport_download_observability.py`.

Both allowed sets are frozensets. A valid bounded JSON payload can supply an
array or object in either field. All four synthetic combinations raised
`TypeError: unhashable type` from the public composed
`collect_s0_run_snapshot`, aborting the report rather than withholding just
the affected measurement. The earlier schema guard cannot prevent malformed
field types inside a supported v1 envelope.

## Fix and tests

[PR #50](https://github.com/CarsonHHS2023/pdf-ocr-service/pull/50), current head
`6fc4809592166d4695bd8450ec24ef38a441b130`, now checks `isinstance(value, str)` before either
membership operation. Unsupported strings and non-strings return the existing
unavailable result. The set of valid stages/routes and metric definitions do
not change.

The storage fix is applied through its owning composition script, including
the existing installed-helper refresh. No generated composed baseline file
is published. This follow-up changes two guard expressions and two existing
test files; the whole PR still changes seven files.

Nineteen parameterized regressions exercise the public composed collector:

| Input | Storage stage | Transport route |
|---|---|---|
| Empty/populated array or object | unavailable, report survives | unavailable, report survives |
| Null, boolean or number | unavailable | unavailable |
| Unknown string | unavailable | unavailable |
| Valid processing-source stage | observed | not applicable |
| Valid presigned/fallback route | not applicable | observed, correct 0/120-byte controls |

Tests also check unavailable values, independent source-byte metadata and
strict JSON serialization. **163 local tests passed, no skips** across storage,
transport, Provider download/compute and baseline suites. This is a different
targeted suite from the earlier 170-test schema/identity pass; those historical
counts are not relabeled.

All five exact-head workflows passed on attempt 1:

- [Provider 20 MiB Staging CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/36157655210): success.
- [S0 Baseline CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/36157655238): success.
- [Durable Processing Events CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/36157655224): success.
- [Provider Transport Sharding CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/36157655249): success.
- [Staging Backend Integration CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/36157655314): success.

Integration and artifact verification succeeded; deployment was skipped.
The candidate remains unmerged and undeployed.

## Review boundaries

The adjacent preprocessing-CPU and visual-generation enum checks establish
string types before set membership; TXT validates reason strings and uses
safe tuple comparison for outcome selection. Failure/retry outcome choices
also use tuples. This source inspection is not an exhaustive proof of every
malformed nested JSON shape.

This fix covers retained event fields at collector admission. Producer APIs,
full per-family severity/page contracts, unknown event-name policy, and
cross-family revision/relational guarantees are not newly signed off here.
The [schema/identity review](s0-3-7-schema-identity-review-2026-09-20.md)
retains its explicit Reader writer-provenance boundary; the
[numeric review](s0-3-7-provider-numeric-review-2026-09-20.md) retains its own
measurements and exact-head checks.

S0/M5 remain In Progress at **17/19**. Complete upload peak-memory and full
preprocessing CPU attribution remain unimplemented. Existing accepted live
measurements retain their original revisions and scopes.
