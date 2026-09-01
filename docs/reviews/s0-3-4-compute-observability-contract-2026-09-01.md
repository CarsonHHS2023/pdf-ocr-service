# S0.3.4 compute observability contract

Status: implementation under review; Staging fixture acceptance pending. S0 remains In Progress. S1/S2 are not started.

This extends the accepted S0.3.3 producer → durable event → collector path. It does not reinterpret earlier fixture runs as having compute evidence.

## Measurement boundaries

| Required metric | Producer boundary | Collector value |
| --- | --- | --- |
| `ocr_batch_duration_seconds` | Monotonic time around worker `pipeline.predict`, including consuming its generator | Sum across every validated batch and Provider shard; per-batch durations remain in `provider_compute_breakdown` |
| `raw_result_shard_bytes` | Per-Provider-document sanitized raw page-list JSON, UTF-8, `ensure_ascii=False`, default JSON separators, before result-profile image slimming | Sum of per-shard byte counts, with individual counts retained in the breakdown |
| `gpu_busy_idle_proxy` | NVML device utilization samples taken during each predict invocation at a requested one-second interval | Sample-count-weighted mean utilization percent and nonzero sample fraction; unavailable unless every batch has at least two valid samples |

OCR time excludes source download, worker queueing, model initialization, result restructuring/serialization, Backend polling, and telemetry teardown. A sum of overlapping operations is not an end-to-end critical path. The pipeline may include CPU work; this is not kernel-only duration.

Raw JSON bytes exclude HTTP envelopes, gzip compression, artifact wrappers, and Backend canonicalization. They are independent of source bytes, transport/download bytes, normalized result bytes, and the historical aggregate `raw_result_size_bytes` metric. The measurement survives summary/standard/full projections and artifact offload.

NVML utilization describes kernel activity over the device's own recent sample window. It is not spatial occupancy, process attribution, exact GPU active seconds, or between-job idle time. Windows may overlap the predict boundary; the sampler is a bounded proxy. Only a single NVML-visible device is accepted to avoid assuming that NVML and CUDA indices match. Probe errors, ambiguous devices, fewer than two samples, a 4,096-sample cap, or a sampler shutdown timeout leave GPU unavailable. OCR and raw-result measurements remain independently usable. No device identifiers are emitted.

Primary semantics: [NVIDIA utilization structure](https://docs.nvidia.com/deploy/nvml-api/structnvmlUtilization__t.html) and [NVML device queries](https://docs.nvidia.com/deploy/nvml-api/group__nvmlDeviceQueries.html).

## Durable contract and closure

Provider emits `ocr_compute` with scope `provider_ocr_document_v1`, complete page/batch counts, at most 128 ordered batches, and raw-size scope `sanitized_raw_page_list_json_utf8_v1`. Each batch includes its shard-local page range, ordinal, predict seconds, and an allowlisted GPU summary or unavailable reason. Exceeding the batch bound omits the contract rather than truncating it into apparent completeness.

Backend writes one `S0_PROVIDER_OCR_BATCH_MEASURED` per batch, then one `S0_PROVIDER_OCR_SCOPE_TERMINAL`. It validates the entire contract before writing and stops on persistence failure without emitting terminal proof. Failures never change processing or result-retrieval outcomes. Persistence remains gated by the exact Staging revision marker.

The collector requires:

- one compute terminal and complete batch evidence for every validated S0.3.3 Provider download scope;
- unique, contiguous batch ordinals and complete non-overlapping shard-local page ranges;
- total measured pages equal the durable Provider-selected input page count;
- valid finite durations and positive per-shard raw byte counts;
- inspectable bounded payloads and unambiguous scope identity.

Missing/duplicate/invalid compute evidence is `not_available`; unrelated bounded-snapshot incompleteness is `partial`. Missing GPU evidence does not demote valid OCR/raw bytes. No filename, title, source URL, credential, raw storage reference, source/result content, or device identity is included in these events. Provider job IDs are represented only by the existing hashed Provider scope IDs.

## Composition and validation

Backend's authoritative Staging composition applies the new overlay after S0.3.3. Focused baseline CI and integration CI test the mapping, and artifact verification checks the retrieval hook and collector marker in the exact tested artifact.

The companion `CarsonHHS2023/paddle-vl-api` change adds a separate overlay and standard-library sampler module. Only the isolated S0 Staging app imports it. Production `modal_app.py` and its deploy workflow remain unchanged. Preview deploys use the exact same-repository PR head, verify that head before deployment, and serialize access to the shared S0 Staging app.

Contract tests cover multi-shard and out-of-order evidence, persistence failure, missing/duplicate terminal and batch events, invalid duration/coverage, oversized durable payloads, missing GPU, bounded sampling, privacy projection, UTF-8 raw-size semantics, artifact offload, and idempotent composition. No expensive benchmark is required for these tests.

Runtime acceptance remains pending on an exact Backend Staging revision paired with the isolated Provider revision. After the implementation is reviewed and deployed, collect a newly completed small run and inspect the three required metrics plus the complete per-batch/shard breakdown. Do not reuse pre-instrumentation runs. Keep private run identifiers and fixture identity in private evidence, and decide on a medium rerun only after small acceptance.
