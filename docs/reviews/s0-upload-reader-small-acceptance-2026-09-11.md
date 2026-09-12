# S0 upload to initial Reader render — small acceptance

| Field | Value |
|---|---|
| Document Type | Historical Record / Staging acceptance |
| Approval Status | Proposed repository record of verified evidence |
| Lifecycle Status | Historical |
| Evidence / verification date | 2026-09-10 / 2026-09-11 UTC |
| Result | **Scoped small acceptance PASS; S0 and M5 remain In Progress** |
| Backend Staging / runtime | `f3b7af8122d5e5fe946614c6e1ddd0047877d504` |
| Frontend PR Preview | `086cda854c24680ea4ce1c414844f10af2c14dcf` |
| Processing run | `pdf-ingest-16c3f2af977740adb0a608089b0b67aa` |
| Document | `6ad2e24a-83c2-4bd0-bd8b-c758ca2c4ad5` |
| Source file | `dc9cd123-bc2a-4f52-b836-f0927f81a2af` |
| Candidate | `scv2_pdf_bac258ea728adfd8548385fc` |
| Run status / pages / retained source bytes | `succeeded` / `1` / `784772` |
| Processing start / completion (UTC) | `2026-09-10T19:32:05.989194` / `2026-09-10T19:34:33.637168` |

## Exact evidence and collector provenance

[Backend PR #46](https://github.com/CarsonHHS2023/pdf-ocr-service/pull/46)
was merged and deployed before this run. Its
[Staging Integration run 34474820122](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/34474820122)
completed integration, artifact verification and deployment successfully. Deploy
job `102863358294` verified the tested artifact's exact HF runtime revision and
the pre/post deployment Staging-head guards. GitHub Staging HEAD was checked
again during collection and still matched the revision above.

[Frontend PR #87](https://github.com/CarsonHHS2023/speed-reading-trainer/pull/87)
remains Draft with base `main`; it is not merged or a Production acceptance target.
[Reader CI](https://github.com/CarsonHHS2023/speed-reading-trainer/actions/runs/34520573273)
and [Preview verification](https://github.com/CarsonHHS2023/speed-reading-trainer/actions/runs/34520573261)
passed for the exact frontend revision. The latter checked the Staging marker,
11 script hashes, public head marker and branch guards.

A read-only Staging Neon SQL snapshot captured the exact run/document/source
projections required by the collector, candidate association, all 49 associated
events and the database event count. Private fixture filename and source checksum
are excluded from this record. No source binary was downloaded or processed.

The exact Backend Git commit was exported into a fresh local directory and its
own Staging CI overlay sequence was applied. The unchanged
`collect_s0_run_snapshot` then read an isolated in-memory SQLite projection of
the observed SQL columns. The source checksum was omitted from report output.
No live database writes, initialization or guessed metric values were used.

This is a source-rebuilt collector replay of durable Staging evidence, not a
collector invocation inside HF, a fresh downloaded-artifact hash check, or a new
direct runtime health request. Deployment/runtime verification comes from the
successful deployment job and matching durable event revisions.

## Accepted boundary and numbers

| Metric | Status | Value |
|---|---|---:|
| `upload_to_reader_ready_seconds` | `observed` | `170.5072 s` |
| `reader_open_latency_seconds`, first open | `observed` | `4.6543 s` |
| `reader_bounded_query_count`, first open | `observed` | `57` SQL statement attempts |
| Reader data requests | complete | `3` |
| `backend_to_modal_transport_bytes` | `observed` | `982161 bytes` |
| Provider downloaded bytes | measured | `982161 bytes` |
| `modal_download_seconds` | `observed` | `0.793008 s` |

The upload interval uses one client-reported same-page clock from canonical
single-PDF dispatch to automatic initial core semantic render, including
synchronous final page-change notification. It excludes binary-asset completion,
asynchronous enhancements and browser paint. It is not a sum of stage durations
or a difference between persistence timestamps. Reader latency is a separate
contained interval; the two values must not be added.

Retained source bytes (`784772`), Backend ASGI body bytes (`982161`) and Provider
download bytes (`982161`) have independent meanings. The latter two happen to
match on this single-download `atlas_source_transport_fallback` route; neither
equals the original source size. This is a same-run control, not a replacement
for the earlier medium/presigned transport acceptance.

## Durable audit

- Upload scope `upr_64cd1e119a907422beebb6dee43bf9ca`: one accepted event at
  ordinal `0`, one terminal at `1`, no invalidation or duplicate slot. Deterministic
  event IDs match the protocol/run/ordinal calculation.
- Reader scope `reader_c26376effa63340f47576c34ec4bba5c`: metadata, navigation and
  content request ordinals `1,2,3`, then exactly one first-open terminal. The
  bounded content request uses limit `150`, window start `0`.
- The six events agree on run/document association and the exact source,
  candidate and frontend/Backend revisions. Strict payload field allowlists and
  ID patterns pass; no private filename, path, URL, token or raw storage reference
  is present in those upload/Reader payloads. Maximum payload: `612` UTF-8 bytes.
- All 49 event payloads decode strictly, with no duplicate JSON fields or
  nonfinite constants. No oversized payload or event-window truncation was found;
  collector decode-incomplete and oversized-incomplete flags are false.
- Acceptance was persisted at `19:32:03.412904` UTC, upload terminal at
  `19:34:49.975667`, and Reader terminal at `19:34:50.066858`, all on 2026-09-10.
  The collector correctly admits the complete snapshot despite the upload
  terminal being persisted before the Reader terminal.

Browser diagnostics independently reported acknowledged upload, Reader binding,
terminal dispatch and HTTP `204`. These observations alone were not treated as
acceptance. The KaTeX Unicode warning did not prevent these terminal records;
formula visual correctness is outside this acceptance scope.

## Earlier failed attempt and remaining work

Run `pdf-ingest-961305298d774832a776796bb352234a` on the same Backend and frontend
`23484b0e2398c19aaf32f9b263a412582694b282` remains a failed evidence attempt:
upload acceptance and Reader first-open evidence exist, but its upload terminal
is absent and the collector returns `not_available`. Its cause is unresolved.
The user reported no background transition. Do not attribute that failure to
tab switching or retroactively replace its missing clock with this successful run.
The frontend follow-up adds diagnostics; this success does not prove a specific
root-cause fix for the earlier failure.

The complete new snapshot has **17 of 19 required metrics observed**. Required
`backend_upload_peak_memory_mb` and `preprocessing_cpu_seconds` remain
`not_instrumented`. No limitation is accepted or waived by this record.

No further small or medium upload is needed for this already accepted target.
TXT ingestion timing, full memory/CPU attribution, final mapping/privacy review
and the final S0 closure decision remain separately gated. S0 and M5 are In
Progress; S1/S2 and 100/528-page execution have not begun.
