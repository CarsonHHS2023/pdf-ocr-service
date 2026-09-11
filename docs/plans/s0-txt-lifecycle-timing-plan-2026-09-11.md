# S0 TXT lifecycle and timing inspection — 2026-09-11

Status: **Source inspection complete; timing implementation and TXT acceptance pending**.

Product milestone: M5 support. Scalability phase: S0. This plan retains the two
unimplemented PDF attribution requirements in the
[remaining-decision record](s0-remaining-attribution-decisions-2026-09-11.md).

## 1. Pinned sources and evidence limits

Backend source: `f3b7af8122d5e5fe946614c6e1ddd0047877d504`.
The files inspected at documentation descendant
`20e19d4f86f99df2af0ec65ea512977a393389b3` have unchanged runtime source.
Frontend Preview: `086cda854c24680ea4ce1c414844f10af2c14dcf`.

This is inspection of exact Git source and overlay definitions, not a fresh
deployed-artifact execution or TXT upload. The Staging integration workflow
applies overlays; reading the uncomposed upload router alone is insufficient.
The canonical multipart replacement is
[`apply_legacy_durable_ingestion_dispatch.py`](../../scripts/apply_legacy_durable_ingestion_dispatch.py),
invoked by the durable-dispatch overlay sequence.

## 2. Actual lifecycle

| Boundary | Source / symbol | Timing meaning today |
|---|---|---|
| Canonical multipart ASGI entry | `app/s0_upload_boundary_observability.py`, `_wrap_fastapi_call` | Starts the existing upload clock |
| Source retention and durable acceptance | `scripts/apply_legacy_durable_ingestion_dispatch.py`; `commit_retained_ingestion` | Source, Document and IngestionDispatch are committed before background registration |
| Durable dispatch registration | `app/s0_upload_durable_dispatch_compat.py`, `_wrap_upload_finalize` | Freezes upload duration before observer lookups; resolves TXT identity from `txt_processing_run_ref` |
| Dispatch claim / worker invocation | `app/processing/ingestion_dispatch.py`, `run_ingestion_dispatch` | TXT processor runs through `asyncio.to_thread`; dispatch timestamps are queue/lease state |
| TXT worker | `app/processing/txt/ingestion.py`, `process_txt_document_background` | STARTED/FAILED/COMPLETED diagnostics currently log to stderr; they are not this proposed durable duration protocol |
| Retained-source read, normalization, window/outline analysis, SPR storage, candidate transform | `app/processing/txt/canonicalization.py`, `TxtCanonicalizationService.canonicalize` | Substantial work occurs before the ProcessingRun is created |
| Canonical commit | Same method, `processing_run_persistence` through `commit` | Candidate and initial selection handling are committed with run success |
| Book status update | `_set_document_terminal_state` | Separate transaction after canonical commit; failure is logged and swallowed |
| Automatic initial Reader open | Frontend `bookshelf.js` and `s0-upload-reader.js` | Upload observer explicitly admits a single PDF only; TXT is ineligible |

The upload-duration producer already understands TXT durable dispatch identity.
That capability is not evidence that a particular historical TXT run retained
a valid event. Do not infer missing upload duration from processing timestamps.

## 3. Confirmed lifecycle timestamp defect

In `TxtCanonicalizationService.canonicalize`, `now = datetime.utcnow()` is
sampled at `processing_run_persistence`, after analysis, SPR storage and candidate
transformation. A newly created run gets `started_at=now`; the success path later
sets `run.completed_at = now` using the same value before `session.commit()`.

Consequences:

- A new successful run has an exactly zero lifecycle interval, regardless of
  prior source, analyzer or storage work.
- Reusing an existing run retains its older start and sets a new completion
  value; that difference is not a proven single-execution duration either.
- Early failures can occur before a ProcessingRun exists. The existing
  run-oriented collector cannot report such failures just by looking up a run.
- Changing only `completed_at` would measure the final persistence tail rather
  than the missing worker interval.

The [TXT registry](../testing/s0-benchmark-fixtures-v1.md) already marks historical
timestamps unsuitable. Preserve those records; do not backfill guessed times.

## 4. Proposed first implementation slice

Implement a **Staging-only TXT worker wall-duration observer**, under a new,
explicitly TXT-specific auxiliary key such as
`txt_ingestion_worker_wall_seconds`. The name and full wire fields must be fixed
in a versioned contract before implementation. Do not map this containing
interval to PDF preprocessing or PDF canonicalization keys.

Recommended boundary:

- Start inside the synchronous TXT worker, before analyzer configuration and
  canonicalization work, on a monotonic clock owned by that execution.
- End on that same worker after canonicalization returns a committed outcome,
  before the separate Document terminal-state transaction and observer writes.
- Include configuration, source lookup/read/validation, normalization, all
  window/outline analyzer calls and their existing waits/retries, SPR work,
  candidate transformation and canonical persistence.
- Exclude queue wait, executor admission wait, source upload, final book-status
  publication, browser polling, Reader requests, binary completion and paint.
- A completed canonical worker interval does not prove the book became visible
  or that Reader automatically opened; those are separate observations.
- Failure and cancellation must never synthesize a successful duration or zero.
  The async waiter's cancellation does not stop an already-running worker.

Capture any future UTC lifecycle timestamps independently for audit. Correcting
business ProcessingRun timestamps is a separately reviewed lifecycle change,
not a substitute for the monotonic measurement. Keep database sessions short;
do not hold a transaction across analyzer network work.

## 5. Required contract before coding

1. Give each actual worker execution a bounded, server-generated scope and bind
   it to the exact dispatch, document, retained source and TXT run reference.
   Treat repeated execution under one logical run as ambiguous unless a complete
   execution manifest proves disjoint ownership. Do not select the newest event.
2. Fix the allowlisted success/failure terminal fields, version, method, units,
   stage codes, revision identity, event count and encoded payload byte limit.
   Do not copy existing diagnostic strings, filenames, text, provider messages,
   credentials, URLs or storage references into evidence.
3. Specify append-only bounded slots, duplicate/conflict handling, transaction
   rollback, publication failure and observer-off behavior. An evidence failure
   must not change TXT processing or retry policy.
4. Preserve original exceptions and the worker's ownership after waiter
   cancellation. Document the snapshot race and publication-loss limits; do not
   promise durable invalidation when its write itself fails.
5. Define collection when no ProcessingRun was created. Either provide a separate
   dispatch-oriented failure report with explicit unavailable metrics, or keep
   that failure outside the success-only run snapshot. Do not create fake runs
   merely to satisfy a collector join.
6. For success admission, require exact persisted candidate/run/source identity,
   positive retained-source size, complete bounded event coverage and finite
   nonnegative elapsed time. Use the current terminal run status as an additional
   check, not as proof that duration was measured.

## 6. Implementation and acceptance order

| Step | Concrete deliverable / gate |
|---|---|
| A | Versioned TXT observer contract covering sections 4–5; review before runtime edits |
| B | Minimal worker observer and collector auxiliary, feature-gated to Staging; preserve existing PDF paths |
| C | Synthetic-clock tests for slow analysis/storage/commit, configuration/analysis/selection/commit failures, missing run, duplicate execution, cancellation, privacy and malformed/oversized evidence |
| D | Verify actual durable-dispatch + worker + collector composition, observer off/on behavior, publication atomicity and bounded costs in CI |
| E | Separately reviewed exact tested Staging rollout; record source and deployed revision separately |
| F | `txt-small-v1` acceptance, then `txt-medium-v1` when additional window/outline coverage is demonstrated |

No fixture is requested before A–E. Existing TXT Reader-reopen evidence is
preserved and cannot satisfy F. The first slice does not extend the PDF-only
browser upload observer: a later TXT upload-to-Reader contract must separately
cover acknowledgement identity, book-state publication and automatic first-open
eligibility. Reusing PDF admission by changing only a filename predicate is
insufficient; Backend acceptance also explicitly requires `dispatch.kind == "pdf"`.

TXT PDF-specific rows (pages, OCR/GPU/shards, PDF preprocessing) must not be set to
observed zero. Keep current statuses until an explicit format-applicability
decision is accepted; new auxiliary timing is not an implicit waiver.

S0/M5 remain **In Progress**. This source-pinned plan adds no runtime,
database, workflow, fixture, merge, deployment or S1/S2 change.

