# M2-003H-E Controlled Live Provider Smoke Result

| Field | Value |
|---|---|
| Document Type | Smoke Result |
| Execution Date | 2026-07-16 |
| Evidence Role | Point-in-time controlled live-provider execution evidence |
| Result Status | PASS |
| Authority Domain | Recorded outcome of one controlled Atlas-to-provider smoke execution |
| Applies To | Disposable test deployment; retained fixture; operator process-once; Transport Grant; private source transport endpoint; Modal paddle-vl-api async job; status polling; standard result retrieval; Raw Processing Result retention; grant revocation; redacted evidence boundary |

## Status

State: **PASS**

- Execution date: 2026-07-16.
- Atlas commit deployed: not safely recorded in the available repository or deployment evidence.
- Provider reference commit: `3a790e3e4c0ececef316bd2ca5aa03d84f6c6159`.
- Provider implementation revision from inventory: `20b9ec9`.
- Smoke owner/approver: Carson.
- Deployment: disposable test deployment only.

## Scope

The following path was verified:

```text
retained fixture
    ↓
operator process-once
    ↓
integration service
    ↓
Transport Grant
    ↓
private source transport endpoint
    ↓
Modal paddle-vl-api async job
    ↓
status polling
    ↓
standard result retrieval
    ↓
Raw Processing Result retention
    ↓
grant revocation
```

No later processing stage was invoked: no MinerU-Popo, Structured Processing
Output, M3, or Reader processing occurred.

## Preconditions confirmed

- HF Space was running.
- The operator was enabled for this smoke, with an independent operator token configured.
- The public source origin and provider base URL/bearer token were configured.
- The fixed fixture was prepared and retained.
- Visible logs were clean before execution.
- The one-process disposable posture was accepted.
- The smoke used no customer data.

## Execution evidence

| Evidence | Observed value | Result |
| --- | --- | --- |
| Overall result | PASS | Passed |
| Execution window | Started 2026-07-16 11:59:30 local operator time; finished 2026-07-16 12:00:05 local operator time | Passed |
| Operator invocations | Exactly one | Passed |
| Provider jobs | Exactly one | Passed |
| Result profile | `standard` | Passed |
| Fixture | SHA-256 `fb084e43d06e039118d2a72a40353eebcec09abdbe732cf30917608723126420`; 605 bytes | Passed |
| Provider job ID | `smoke_job_...3b67` | Passed; redacted |
| Provider request ID | `smoke_req_...3b67` | Passed; redacted |
| Operator status | `succeeded` | Passed |
| Provider terminal status | `provider_completed` | Passed |
| Integration terminal phase | `raw_result_retained` | Passed |
| Polling | 6 polls; 34.803 elapsed seconds | Passed |
| Grant finalization | `revoked`; revocation succeeded `true` | Passed |
| Operator error fields | `error_category`, `error_phase`, and `retry_guidance` empty | Passed |
| Modal job protocol | `POST /ocr/jobs` returned 202 Accepted; repeated `GET /ocr/jobs/{job_id}` returned 200; `GET /ocr/jobs/{job_id}/result` returned 200 | Passed |
| Modal processing | PaddleOCR-VL initialized successfully; OCR parse completed; raw output length was 1 | Passed |
| Submission safety | No duplicate submission occurred | Passed |
| Visible logging | No token or full source URL appeared in visible HF logs; HF application access logs remained silent as configured | Passed |

## Provider evidence

Modal evidence shows successful asynchronous acceptance, polling, provider
initialization, OCR parsing, and standard-result retrieval. The provider
completed without a terminal processing error.

Warnings observed separately:

- Pydantic class-based `Config` deprecation warnings.
- A blocking Modal interface was used in an async context for
  `execution_cache.commit()`.

Neither warning prevented successful completion. This smoke does not claim that
either warning is resolved.

## Source transport evidence

- Provider source retrieval succeeded, with no source checksum mismatch.
- No transport 404, 500, or 503 was observed.
- No token or full source URL was visible in HF logs.
- HF application access logs remained silent as configured.
- A retrieval count was not captured and is not inferred.

## Raw Result evidence

- Raw Processing Result retention was confirmed by
  `integration_terminal_phase = raw_result_retained`.
- The Raw Result StorageReference, SHA-256, and byte size were not captured
  from the transient PowerShell script response.
- No second submission was made to recover those fields.
- This is an evidence-capture gap, not a processing failure. Future operator
  scripts must write safe response metadata to a private local file.

## Grant evidence

- Final grant state: `revoked`.
- Revocation succeeded: `true`.
- The source fixture was not deleted and remained retained.

## Success criteria audit

The audit follows the M2-003H definition of done.

| Criterion | Result | Evidence |
| --- | --- | --- |
| Integration service implemented and independently verified | Passed | Existing M2-003H implementation and verification documentation; this closeout changed no runtime behavior. |
| Exactly one controlled provider job submitted | Passed | One operator invocation and one provider job. |
| Provider retrieved the Atlas transport URL | Passed | Source transport completed successfully. |
| Source checksum verified | Passed | No checksum mismatch observed. |
| Provider reached a terminal state | Passed | `provider_completed`. |
| Standard result retrieved | Passed | Result endpoint returned 200. |
| Raw Processing Result retained | Passed | `raw_result_retained`. |
| Raw Result checksum and size captured | Passed with evidence limitation | Retention succeeded, but checksum and byte-size metadata were not captured from the transient response. |
| Original Source remained retained | Passed | Fixture remained retained. |
| Transport grant finalized by policy | Passed | Grant revoked successfully. |
| No secrets or full URL in logs or committed evidence | Passed | Visible logs clean; this record contains only redacted evidence. |
| No automatic duplicate submission | Passed | No duplicate submission occurred. |
| Smoke evidence recorded | Passed | This redacted closeout record. |
| No MinerU-Popo, M3, or Reader integration added | Not applicable | No later processing stage was invoked by this smoke. |
| M2 documentation updated | Passed | Result, procedure status note, and milestone links updated. |

## Security audit

- No credential was committed.
- No complete token or full URL appeared in visible logs.
- No duplicate submission occurred.
- Only non-sensitive test data was used.
- The operator route should be disabled after the smoke.
- HF internal reverse-proxy logging remains an unobservable residual risk accepted
  only for disposable M2 testing.

## Operator shutdown

Status: **VERIFIED**

- `ATLAS_PROCESSING_OPERATOR_ENABLED` was changed to `false`.
- The HF Space restarted successfully.
- An authenticated `POST /internal/operator/prepare-smoke-fixture` returned
  collapsed HTTP 404 with `{"detail":"Not found"}`.
- No Provider activity occurred, no OCR job was submitted, no Transport Grant
  was created, no source transport URL was generated, and no Storage mutation
  occurred.

## Evidence-capture gap

`$Response` existed only in PowerShell script scope. After the script exited,
the Raw Result fields could not be retrieved. No retry was performed. A future
script must persist safe response metadata privately before cleanup.

## Technical debt

1. Migrate Modal Pydantic models from class-based `Config` to `ConfigDict` before Pydantic v3.
2. Replace blocking Modal commit calls in async contexts with async `.aio()` variants where supported.
3. Investigate the Provider temporary PDF size of 831 bytes versus the retained source fixture size of 605 bytes and document the normalization/page-range behavior.
4. Add private safe result metadata capture to future operator smoke scripts.
5. Evaluate durable object storage and production-grade transport grants before production use.
6. Replace synchronous operator execution with a durable background/persistent workflow before production.

## M2-003H conclusion

**M2-003H completed successfully for the disposable test deployment.** The
architecture path is proven, but production readiness is not claimed. The
in-memory, restart-losing grant posture remains test-only, and the operator
endpoint is not a production API.

## Remaining M2 work

M2 as a whole is not complete: its milestone status remains planned until M1
closes. Beyond this M2-003H closeout, the milestone still calls for MinerU-Popo
normalization, a Structured Processing Output contract, provenance/version
metadata, retry and idempotency behavior, mocked CI contract tests, and
isolation or removal of the old local PaddleOCR-VL path.

## Final decision

| Decision | Evidence | Result | Follow-up |
| --- | --- | --- | --- |
| Close M2-003H for disposable testing | One successful controlled path, raw retention, grant revocation, and verified operator shutdown including collapsed HTTP 404 after disablement | PASS | Retain redacted evidence only. |
| Treat Raw Result metadata gap as non-failure | Retention phase succeeded; transient response metadata was not captured | PASS with evidence limitation | Persist safe metadata privately in future scripts. |
| Claim production readiness | In-memory grants and synchronous operator execution are test-only | Not approved | Complete the listed technical debt and production design work. |
