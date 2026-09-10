# S0 visual asset generation small acceptance — 2026-09-09

| Field | Value |
|---|---|
| Document Type | Historical Record / Staging acceptance |
| Approval Status | Proposed |
| Lifecycle Status | Historical |
| Evidence Date | 2026-09-09 |
| Scope | Fresh one-page PDF visual-generation observation; related transport control |
| Result | **Small visual-generation acceptance PASS; S0 and M5 remain In Progress** |
| Backend Git / runtime revision | `a640cf07c0b3db8e0cade4950e4cc74af2ac0cfc` |
| Hugging Face deployment commit | `45619ffe5e04af1fd1aa5e7c2642b2c875edc256` |
| Processing run | `pdf-ingest-04e6acc7b65f4e38b1b9026409f836cf` |
| Document | `0d47ded0-38d2-4d34-8337-03a085096e06` |
| Source file | `6233b252-4527-4ff0-9620-8396f1007493` |
| Run result | `succeeded`; one PDF page; retained source `784772` bytes |
| Started / completed (UTC) | `2026-09-09T12:00:29.507Z` / `2026-09-09T12:03:18.207Z` |
| Related contract | [Visual asset generation observability v1](../testing/s0-visual-asset-generation-observability-v1.md) |

The observed PASS above and the proposed repository record are separate: this
document records the completed acceptance and awaits documentation review.

## Deployment and collector provenance

[PR #44](https://github.com/CarsonHHS2023/pdf-ocr-service/pull/44) was merged before this observation.
[Staging Backend Integration CI run 33913264949](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/33913264949)
passed on the exact Backend revision above:

| Job | Result |
|---|---|
| [Integration, 101154482940](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/33913264949/job/101154482940) | success |
| [Artifact verification, 101154927199](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/33913264949/job/101154927199) | success |
| [Deploy, 101154954544](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/33913264949/job/101154954544) | success; not skipped |

The deployment verified the exact tested artifact, HF runtime revision and
pre/post Staging-head guards. During acceptance, the GitHub staging HEAD was
freshly checked before and after collection; the healthy runtime and both
visual-event revisions agreed with that SHA.

Read-only Staging Neon queries locked the run and exported the collector-required
projections of its run, document, source and all 47 associated events. Private
source identity/checksum remains in the private projection, outside this record.

The original CI artifact download returned HTTP 410 (expired). This acceptance
does not claim a fresh download/checksum verification of that ZIP. Instead,
247 files (application Python files and the baseline CLI) were checked against
Git blob identities from the immutable
[deployed HF revision](https://huggingface.co/spaces/carsonhhs/pdf-ocr-service-staging/tree/45619ffe5e04af1fd1aa5e7c2642b2c875edc256).
An isolated source copy matched them; all 18 repository modules imported by the
replay were also verified. The unchanged deployed `collect_s0_run_snapshot`
executed against an in-memory SQLite projection of the exported columns.

This was collector replay of durable Staging evidence, not execution inside HF
or a direct collector connection to Neon. No new processing, fixture upload or
Staging database initialization was performed. The later documentation candidate
does not change the observed revision.

## Visual-generation result and durable audit

| Metric / evidence | Status | Value |
|---|---|---:|
| `visual_asset_generation_seconds` | `observed` | `0.253639226 s` |
| Terminal `duration_ns` | measured | `253639226` |
| Newly generated assets | completed | `2` |
| Newly generated renditions | completed | `2` |
| Candidate assets / renditions with artifact references | persisted | `2 / 2` |

Candidate `scv2_pdf_17ee7f9f5561a5567f37a0c6` belongs to the exact document and
run above. Its two assets and two referenced renditions agree with producer counts.

The pair is `S0_VISUAL_ASSET_GENERATION_RUN_STARTED` at ordinal `0`, then
`S0_VISUAL_ASSET_GENERATION_RUN_TERMINAL` at ordinal `1`, with one observation
`vasset_0c638563972d4ea1b96dfecb6457552b`, the exact hashed SourceFile scope and
the same Backend revision. The terminal has `operation_outcome=completed`,
`clock_status=measured`, `reason=none`, method
`pdf_canonicalization_visual_enrichment_wall_v1` and scope
`candidate_visual_enrichment`.

- Exactly two visual events, unique scope/ordinal pairs and contiguous `0,1`.
- Visual payloads are 391 and 545 UTF-8 bytes and pass the strict field allowlist.
- All 47 events use `atlas.processing.event.v1`. No malformed JSON, duplicate JSON
  field or nonfinite constant was found; the maximum payload is 820 bytes, below
  8192, and none is oversized.
- Collector truncation, decode-incomplete and oversized-incomplete flags are all
  false. The exported event count equals the database count.
- The retained payload audit found no privacy-sensitive filename, title, content,
  path, URL, token or raw storage-reference field/value. It does not audit
  unrelated logs or database content.

Both visual rows were persisted at `2026-09-09T12:03:23.987Z`, after the logical
run terminal. The producer publishes the pair together after canonicalization
settles. The duration is the captured monotonic nanosecond delta, not a difference
between database event timestamps.

## Independent transport control

| Boundary | Collector status | Value |
|---|---|---:|
| Retained source size | `observed` | `784772 bytes` |
| `backend_to_modal_transport_bytes` | `observed` | `982161 bytes` |
| Provider source download bytes | `observed` | `982161 bytes` |
| `modal_download_seconds` | `observed` | `0.812768 s` |

Route `atlas_source_transport_fallback` uses transport scope
`transport_4f06b9be64cd9dbf`, one ASGI body measurement at scope ordinal `1` and
terminal retrieval count `1`. Provider scope `provider_7e2a16e2bec9579d` records
one matching download and one successful OCR batch terminal.

These three byte meanings remain independent. ASGI-body and Provider-download
bytes happen to agree for this one-download route; neither equals the retained
original source size. This is a same-run regression control, not a replacement
for earlier small/medium S0.3.3 acceptance.

## Remaining scope

The full replay has 16 of 19 required metric rows `observed`. Three remain
`not_instrumented`: `backend_upload_peak_memory_mb`,
`preprocessing_cpu_seconds` and `upload_to_reader_ready_seconds`. None is waived.

Visual duration covers the final composed candidate enrichment call. It excludes
earlier source read, structure refinement, SPR persistence, candidate database
commit and Reader work. The separate containing canonicalization measurement is
`12.910429 s`; do not add the two durations.

This is one-page, one-invocation success-path acceptance. It does not claim
multi-page visual performance, concurrent execution or newly audited Reader
acceptance. The observed first-open Reader rows do not supply a missing
upload-start clock.

No medium rerun is required for this operation-scoped target. S0 and M5 remain
In Progress. Production, processing behavior and historical observation SHAs
remain unchanged. S1/S2, new fixtures, 100-page/528-page execution and final S0
closure are not authorized by this record.
