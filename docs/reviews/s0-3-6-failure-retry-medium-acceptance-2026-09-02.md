# S0.3.6 Failure/Retry Medium Acceptance — 2026-09-02

| Field | Value |
|---|---|
| Document Type | Staging Acceptance Evidence |
| Scope | Fresh `pdf-medium-v1`; 11 pages; two sequential Provider scopes |
| Result | **Medium success-path PASS; S0 and M5 remain In Progress** |
| Backend / runtime revision | `7435aa3fa7ba0766d8cc2584bcacfd735c5ce74c` |
| Contract | [Backend-owned failure/retry observability](../testing/s0-failure-retry-observability-v1.md) |
| Prior checkpoint | [Small success-path acceptance](s0-3-6-failure-retry-small-acceptance-2026-09-02.md) |
| Current Plan | [S0 Observability Closure Plan](../plans/s0-observability-closure-plan-2026-08-25.md) |

## 1. Decision and exact provenance

The newly completed 11-page run succeeded and actually entered **two Provider
orchestration scopes**, not merely a multi-page input. Seven pages went to the
Provider in sequential shards of three and four pages; four pages contributed
local results. Both `failure_retry_counts` and `failure_retry_breakdown` are
`observed`. This closes the representative sequential multi-scope success-path
target left open at the small checkpoint; it does not establish concurrent
runtime execution or real nonzero-retry acceptance.

The same [Staging Integration deployment](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/33665600758)
used for small acceptance remains the provenance: [artifact verification](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/33665600758/job/100366843842)
and [deploy job 100366911066](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/33665600758/job/100366911066)
succeeded for the exact SHA above, including the tested-artifact upload, runtime
revision verification and Staging-head guards. Live health again returned
`healthy` and that exact revision. GitHub Staging head was unchanged before and
after medium evidence collection. The new documentation SHA is not a runtime
acceptance revision, and no documentation PR deployment is implied.

**Collector provenance:** a fresh atomic, read-only Neon export was replayed into
a local SQLite projection through the unchanged exact-source/15-CI-overlay
collector used for small acceptance. Its collector, failure/retry validator and
CLI hashes were rechecked against the retained small evidence. This is not
collector execution inside HF or a downloaded artifact byte comparison. Export
count and payload digest matched PostgreSQL and remained unchanged on re-read.
Private evidence retains the full identities, timestamps, source checksum, module
hashes, events and output; no private filename, run/document/source/scope identity
or raw payload is copied into this repository report.

## 2. Independent method-call and lifecycle outcomes

Measurement scope: `backend_pdf_invocation_attempts_v1`.

| Scope ordinal | Provider pages | Submit | Status | Result | Artifact | Successful calls | Failed | Retries |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 3 | 1 | 13 | 1 | 0 | 15 | 0 | 0 |
| 2 | 4 | 1 | 7 | 1 | 0 | 9 | 0 | 0 |
| Total, same method-call layer | 7 | 2 | 20 | 2 | 0 | **24** | **0** | **0** |

All 24 actual backend Provider method entries succeeded. Cancellation,
result-not-ready and retryable-failure counters are explicitly zero. Twenty normal
status polls are not processing retries. No artifact-method call does not mean
that no artifacts were produced. These counts are not wire-packet counts or
Provider-internal execution attempts.

The two orchestration invocations completed, the two Provider terminal
observations were `provider_completed`, and one logical PDF invocation completed.
Keep these three layers separate from method-call failures; do not add them into
one scalar attempt/failure count.

## 3. Multi-scope closure and privacy audit

| Check | Result |
|---|---|
| Durable failure/retry closure | 1 start + 2 scope terminals + 1 run terminal |
| Manifest | `complete=true`, `scope_count=2`, `outcome=completed` |
| Scope ordinals | `[1, 2]`, contiguous and unique |
| Duplicate Provider scope, start or terminal | 0 |
| Scope-to-OCR/download identity | Both scopes match this run's respective OCR and source-download evidence |
| Sharding consistency | Two scopes match the successful two-shard terminal; 3 + 4 Provider pages plus 4 local pages equal 11 |
| Closure transaction | Both scope terminals and the run terminal share one PostgreSQL row-version transaction ID (`xmin`) |
| Revision and source/document/run association | Exact agreement |
| All exported events / failure-retry events | 50 / 4 |
| Largest payload | 820 bytes, below the 8,192-byte bound |
| Malformed, oversized or truncated evidence | None |
| Sensitive filenames, paths, URLs, token values or raw storage references in event payloads | None found |

The start precedes ProcessingRun initialization. ProcessingRun completion precedes
final cleanup and failure/retry terminal publication. Retain those separate
lifecycle boundaries; neither timestamp supplies upload-to-Reader-ready latency.

## 4. Presigned transport: zero Backend body bytes is observed

Both transport scopes selected `presigned_object_get`, and both successful
transport terminals declare zero Backend retrievals. Their source object sizes
match the Provider download byte counts as a multiset. Thus the collector's zero
Backend ASGI source-body bytes has complete route/terminal evidence, rather than
being inferred only from the absence of Backend-send events.

| Independent boundary | Value |
|---|---:|
| Retained source bytes | 4,558,903 |
| `backend_to_modal_transport_bytes` | 0 (`observed`) |
| Provider scope 1 download bytes | 20,066,861 |
| Provider scope 2 download bytes | 8,361,977 |
| `provider_source_download_bytes` | 28,428,838 (`observed`) |
| Scope 1 / scope 2 download seconds | 2.615950 / 1.116940 |
| `modal_download_seconds` | 3.732890 (`observed`) |

Zero Backend ASGI body bytes does not mean zero Backend network traffic: upload,
object-store operations and other requests are different boundaries. Provider
download bytes are not retained source bytes, and summed download durations are
not the logical integration wall clock. The auxiliary
`provider_selected_payload_bytes` remains `not_available` in this collector
snapshot; its diagnostic input-size field is not promoted to an observed metric.

## 5. Coverage decision and remaining S0 work

S0.3.6 now has representative **small single-scope and medium sequential
multi-scope success-path PASS** on the same pinned revision. No further PDF run
is requested for this success-path target. Concurrent runtime scopes, multiple
OCR batches within a scope, crash recovery and real nonzero retries were not
exercised; synthetic failure/retry/cancellation tests remain separate evidence.
Provider-internal retries, queue redelivery and other HTTP/LLM clients remain
outside the contract rather than being declared observed zero.

Both fresh small and medium collectors still have four `not_instrumented`
required metrics: `backend_upload_peak_memory_mb`, `preprocessing_cpu_seconds`,
`visual_asset_generation_seconds`, and `upload_to_reader_ready_seconds`. These
are not accepted waivers. The next proposed instrumentation design is the
upload-owned memory boundary under S0.3.1, followed by the remaining boundaries
in the closure plan. Reader-specific representative acceptance, TXT ingestion
timing, the deferred large-baseline decision and final S0/M5 reviews remain
separate. This documentation update starts no implementation, merges no PR,
deploys nothing, changes no Production resource and authorizes no S1/S2 work,
real fault injection or 100-page/528-page benchmark.
