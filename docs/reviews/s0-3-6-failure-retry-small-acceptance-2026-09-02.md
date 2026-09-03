# S0.3.6 Failure/Retry Small Acceptance — 2026-09-02

| Field | Value |
|---|---|
| Document Type | Staging Acceptance Evidence |
| Scope | One newly completed `pdf-small-v1` backend PDF invocation |
| Result | **Small success-path PASS; S0 and M5 remain In Progress** |
| Backend / runtime revision | `7435aa3fa7ba0766d8cc2584bcacfd735c5ce74c` |
| Implementation | [PR #41](https://github.com/CarsonHHS2023/pdf-ocr-service/pull/41), reviewed head `828ff77feb79a7f1419391faece0141e5ff7f6f3` |
| Contract | [Backend-owned failure/retry observability](../testing/s0-failure-retry-observability-v1.md) |
| Fixture Registry | [S0 Benchmark Fixture Registry v1](../testing/s0-benchmark-fixtures-v1.md) |
| Current Plan | [S0 Observability Closure Plan](../plans/s0-observability-closure-plan-2026-08-25.md) |

## 1. Decision and provenance

The fresh one-page Staging run succeeded after deployment of the exact revision
above. Its durable start, Provider-scope terminal and logical-run terminal support
`failure_retry_counts = observed`, including explicit zero failures and zero
retries. This is not an inference from a green processing status or absent logs.

All five implementation PR workflows passed on the reviewed head: S0 Baseline,
Durable Processing Events, Staging Backend Integration, Provider Transport
Sharding and Provider 20 MiB Staging. The [PR Integration run](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/33653006975)
passed integration and artifact verification; its deploy job was **skipped**.

After merge to Staging, [Integration run 33665600758](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/33665600758)
passed integration, [artifact verification](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/33665600758/job/100366843842)
and [deploy job 100366911066](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/33665600758/job/100366911066).
Deployment included exact tested-artifact upload, exact HF runtime-revision
verification and pre/post-upload Staging-head guards. The [post-merge sharding CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/33665600782)
also passed. During evidence collection, live health returned `healthy` with the
same revision, and the current GitHub Staging head matched before and after replay.
The documentation head is not substituted for this observed runtime revision.

**Collector provenance:** one bounded, atomic, read-only Neon SQL export was
replayed into a local SQLite projection using the unchanged baseline CLI and
collector composed from the exact merged SHA with its 15 Staging CI overlays.
The export's event count and payload digest matched PostgreSQL and remained
unchanged on the post-replay query. This is exact-source/CI-composition replay,
not collector execution inside HF and not a downloaded artifact byte comparison.
The private record retains the full run/document/source identities, source
checksum, scope identities, UTC timestamps, module hashes, events and output.
These identifiers, fixture filenames and raw payloads are not copied into this
repository report.

## 2. Observed method-call counters

Measurement scope: `backend_pdf_invocation_attempts_v1`. These are actual entries
into backend Provider methods, not wire packets or remote execution attempts.

| Operation | Attempts | Succeeded | Failed | Dispatched retries |
|---|---:|---:|---:|---:|
| submit | 1 | 1 | 0 | 0 |
| status | 12 | 12 | 0 | 0 |
| result | 1 | 1 | 0 | 0 |
| artifact | 0 | 0 | 0 | 0 |
| Total, same method-call layer | **14** | **14** | **0** | **0** |

Cancellation, result-not-ready and retryable-failure counters are also explicitly
zero. The 12 successful status checks are normal polling, not 12 processing
retries. Zero artifact-method calls does not mean no artifact was generated.

Independent outcomes, which must not be added to method-call failures:

- one orchestration invocation completed; zero failed/cancelled;
- one Provider terminal observation was `provider_completed`; no unknown,
  partial-failed, failed or expired terminal observation;
- one logical backend PDF invocation completed.

Provider-internal retries, durable queue redelivery, unrelated HTTP/LLM calls and
attempts across separate processing runs remain outside this metric contract.

## 3. Durable evidence and privacy checks

| Check | Result |
|---|---|
| Run status / page count | `succeeded` / 1 |
| Failure/retry event closure | 1 start + 1 scope terminal + 1 run terminal |
| Terminal manifest | `complete=true`, `scope_count=1`, `outcome=completed` |
| Ordinal continuity | `[1]`, matching the declared scope count |
| Duplicate start/terminal, Provider scopes or ordinals | 0 |
| Revision and run/document/source association | Exact agreement |
| Complete exported event count | 41, including 3 failure/retry events |
| Largest event payload | 820 bytes, below the 8,192-byte bound |
| Malformed / oversized / truncated evidence | None |
| Sensitive filenames, paths, URLs, token values or raw storage references in event payloads | None found |
| Collector required metric and scope breakdown | Both `observed` |

The failure/retry start precedes ProcessingRun initialization, as allowed by the
contract. ProcessingRun's completion timestamp precedes final cleanup and the
failure/retry terminal publication. These are distinct lifecycle boundaries;
ProcessingRun completion alone does not establish durable invocation closure or
upload-to-Reader-ready latency.

## 4. Separate byte boundaries

| Metric | Value | Meaning |
|---|---:|---|
| Retained source bytes | 784,772 | Original retained source object |
| `backend_to_modal_transport_bytes` | 982,161 (`observed`) | Completed Backend fallback ASGI source-body sends |
| `provider_source_download_bytes` | 982,161 (`observed`) | Bytes actually read by Provider compute |
| `modal_download_seconds` | 2.020431 (`observed`) | Provider source-download operation duration |

The two transport/download byte totals happen to match for this single-download
path. Their semantics remain independent, and neither equals the retained source
size. Download duration is not Provider integration time or end-to-end latency.

## 5. Coverage limits and next decision

**Later same-day follow-up:** [Medium acceptance](s0-3-6-failure-retry-medium-acceptance-2026-09-02.md)
subsequently passed with two sequential Provider scopes. The small-only limits
and proposed next run below describe this earlier checkpoint, not current work.

This result accepts only the fresh **small, single-scope success path** for
S0.3.6. It does not claim runtime multi-scope/sharding acceptance, observed nonzero
retries, crash recovery, real fault injection or Provider-internal retry coverage.
Existing synthetic CI tests cover failure/retry/cancellation and concurrent-scope
contracts; they are not relabeled as real Staging failure runs.

The next useful runtime evidence, if separately authorized, is one fresh existing
11-page medium fixture on the pinned Staging revision to check multi-scope
aggregation and ordinal coverage. Earlier medium sharding acceptance predates
S0.3.6 and cannot prove these new counters. A medium run must actually enter more
than one Provider scope to satisfy that target; page count alone is insufficient.
No 100-page/528-page run or real fault injection is requested by this record.

The fresh small collector has four remaining `not_instrumented` required metrics:

- `backend_upload_peak_memory_mb`;
- `preprocessing_cpu_seconds`;
- `visual_asset_generation_seconds`;
- `upload_to_reader_ready_seconds`.

Those gaps are not waived. Reader-specific representative coverage, TXT ingestion
timing, the deferred large baseline decision and final S0 closure review remain
tracked separately in the current closure plan. This update authorizes no runtime
change, deployment, PR merge, Production rollout or S1/S2 work.
