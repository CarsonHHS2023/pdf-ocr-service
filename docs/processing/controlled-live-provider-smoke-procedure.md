# M2-003H-E Controlled Live Provider Smoke Procedure

| Field | Value |
|---|---|
| Document Type | Smoke Procedure |
| Lifecycle Status | Historical |
| Authority Domain | controlled one-job live-provider smoke execution |
| Applies To | disposable test deployment; `POST /internal/operator/process-once`; `paddle-vl`; retained fixed fixture `test-only-source-transport.pdf`; result retrieval; cleanup; redacted result recording |
| Execution Scope | One controlled job against a disposable test deployment |
| Related Result | [controlled-live-provider-smoke-result.md](controlled-live-provider-smoke-result.md) |

## Status

Completed for the disposable test deployment; this procedure is retained as the
historical one-job execution record.

## Result

The one permitted controlled smoke completed **PASS** on 2026-07-16. See the
[redacted closeout result](controlled-live-provider-smoke-result.md); no
additional invocation is authorized by this procedure.

- Atlas commit inspected: `b8cca832c7c5b5c80e14dda9b8b47c86455f28d6`.
- Provider reference commit inspected: `3a790e3e4c0ececef316bd2ca5aa03d84f6c6159`.
- Provider implementation revision from inventory: provider async protocol inventory is the current contract at the provider reference commit above; runtime responses expose build tag but not a stable top-level API revision.
- Preparation date: 2026-07-16 UTC.
- Accepted deployment facts: Required Backend CI green; operator route deployed; operator, provider, and trusted public-origin settings configured; fixture preparation route deployed; fixed fixture retained with SHA-256 `fb084e43d06e039118d2a72a40353eebcec09abdbe732cf30917608723126420`, byte size `605`, and media type `application/pdf`; operator-visible HF logs remained clean; Carson privately captured the opaque StorageReference.
- Provider reference remained read-only and clean before and after procedure preparation.
- No live provider call, OCR job submission, deployed process-once invocation, Transport Grant creation, source URL construction, or secret inspection occurred during this verification.

## Objective

Execute exactly one controlled Atlas -> `paddle-vl-api` async processing attempt using the retained fixed fixture.

Stop before:

- MinerU-Popo;
- Structured Processing Output;
- M3 canonical content;
- Reader;
- any user-facing integration.

## Preconditions

All of the following must be true immediately before Carson executes the smoke:

- latest merged `main` is deployed;
- Required Backend CI is green;
- operator route is enabled;
- independent operator token is configured and is not the provider bearer token;
- trusted Atlas public origin is configured as HTTPS with no path, query, fragment, userinfo, whitespace, or control characters;
- provider base URL is configured;
- provider bearer token is configured;
- one worker/process/replica posture is accepted for the in-memory grant service;
- visible HF logs are clean;
- fixed fixture is retained;
- private StorageReference is captured privately;
- fixture is disposable, non-sensitive test data only;
- human owner/approver Carson is available;
- no customer data is involved;
- no concurrent smoke attempt is running.

## Exact request schema

The production operator request model forbids unknown fields. `provider_options` must be omitted for this smoke. Although `null` or `{}` is accepted by the validator, omission is the canonical no-options request and avoids implying provider tuning. `expected_page_count` is accepted when non-negative, but omit it unless Carson has independently verified the expected page count for the retained fixture.

Field constraints from code:

- `processing_attempt_id`: required non-blank string.
- `correlation_id`: optional string; if supplied, downstream orchestration rejects blank strings.
- `retained_source`: required object.
- `retained_source.document_id`: required non-blank string.
- `retained_source.source_file_id`: required non-blank string.
- `retained_source.storage_reference`: required string matching the opaque StorageReference format `src_` plus 32 lowercase hex characters; use only the private retained value.
- `retained_source.retained`: required `true`.
- `retained_source.sha256`: required 64-character SHA-256 hex digest; for this fixture it must be `fb084e43d06e039118d2a72a40353eebcec09abdbe732cf30917608723126420`.
- `retained_source.byte_size`: required positive integer; for this fixture it must be `605`.
- `retained_source.media_type`: required exactly `application/pdf`.
- `retained_source.etag`: optional string or `null`.
- `retained_source.filename`: optional string or `null`.
- `provider_name`: required non-blank string; use `paddle-vl`.
- `provider_job_id`: required non-blank string.
- `provider_request_id`: optional non-blank string.
- `result_profile`: required exactly `standard` for this operator entry.
- `expected_page_count`: optional non-negative integer; omit for the controlled smoke unless independently verified.
- `test_fixture_only`: required/effective `true`; when true, checksum, size, and media type must match the committed fixture evidence.

Canonical JSON template, with placeholders only:

```json
{
  "processing_attempt_id": "smoke_attempt_<suffix>",
  "correlation_id": "smoke_corr_<suffix>",
  "retained_source": {
    "document_id": "smoke_doc_<suffix>",
    "source_file_id": "smoke_source_<suffix>",
    "storage_reference": "<PRIVATE_STORAGE_REFERENCE>",
    "retained": true,
    "sha256": "fb084e43d06e039118d2a72a40353eebcec09abdbe732cf30917608723126420",
    "byte_size": 605,
    "media_type": "application/pdf",
    "etag": null,
    "filename": "test-only-source-transport.pdf"
  },
  "provider_name": "paddle-vl",
  "provider_job_id": "smoke_job_<suffix>",
  "provider_request_id": "smoke_req_<suffix>",
  "result_profile": "standard",
  "test_fixture_only": true
}
```

Do not include any real token, provider secret, complete source transport URL, or real StorageReference in committed files, PR comments, or public evidence.

## ID generation

Use one locally generated suffix. This does not expose secrets and keeps all IDs correlated without reusing any prior job identity:

```powershell
$suffix = [guid]::NewGuid().ToString("N").Substring(0, 12)
$attemptId = "smoke_attempt_$suffix"
$correlationId = "smoke_corr_$suffix"
$documentId = "smoke_doc_$suffix"
$sourceFileId = "smoke_source_$suffix"
$providerJobId = "smoke_job_$suffix"
$providerRequestId = "smoke_req_$suffix"
```

The production request model requires non-blank strings for IDs and rejects blank optional provider/correlation IDs downstream. No maximum ID length or character class is imposed by Atlas for these fields, but provider path usage validates the job ID as a safe path segment; use only ASCII letters, digits, and underscores as shown.

## PowerShell setup

Run the setup in a fresh PowerShell session. Do not paste tokens into command history as literals.

```powershell
$OperatorTokenSecure = Read-Host -Prompt "Operator token" -AsSecureString
$OperatorToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
  [Runtime.InteropServices.Marshal]::SecureStringToBSTR($OperatorTokenSecure)
)
$PrivateStorageReference = Read-Host -Prompt "Private StorageReference"

$suffix = [guid]::NewGuid().ToString("N").Substring(0, 12)
$attemptId = "smoke_attempt_$suffix"
$correlationId = "smoke_corr_$suffix"
$documentId = "smoke_doc_$suffix"
$sourceFileId = "smoke_source_$suffix"
$providerJobId = "smoke_job_$suffix"
$providerRequestId = "smoke_req_$suffix"

$BodyObject = [ordered]@{
  processing_attempt_id = $attemptId
  correlation_id = $correlationId
  retained_source = [ordered]@{
    document_id = $documentId
    source_file_id = $sourceFileId
    storage_reference = $PrivateStorageReference
    retained = $true
    sha256 = "fb084e43d06e039118d2a72a40353eebcec09abdbe732cf30917608723126420"
    byte_size = 605
    media_type = "application/pdf"
    etag = $null
    filename = "test-only-source-transport.pdf"
  }
  provider_name = "paddle-vl"
  provider_job_id = $providerJobId
  provider_request_id = $providerRequestId
  result_profile = "standard"
  test_fixture_only = $true
}

$JsonBody = $BodyObject | ConvertTo-Json -Depth 6
$RedactedPreview = $BodyObject.PSObject.Copy()
$RedactedPreview.retained_source.storage_reference = "<PRIVATE_STORAGE_REFERENCE>"
$RedactedPreview | ConvertTo-Json -Depth 6
```

The preview redacts the StorageReference. Do not print `$OperatorToken`, the complete Authorization header, provider token, transport token, complete source URL, or raw response bodies containing unexpected secrets.

## Request invocation

Invoke exactly once:

```powershell
$Uri = "https://carsonhhs-pdf-ocr-service.hf.space/internal/operator/process-once"
$Headers = @{ Authorization = "Bearer $OperatorToken" }
$Submitted = $false
$HttpStatus = $null
$ResponseBody = $null

if ($Submitted) { throw "Already submitted in this session; do not run again." }
$Submitted = $true
try {
  $ResponseBody = Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -ContentType "application/json" -Body $JsonBody -ErrorAction Stop
  $HttpStatus = 200
} catch {
  if ($_.Exception.Response) {
    $HttpStatus = [int]$_.Exception.Response.StatusCode
    try {
      $reader = [System.IO.StreamReader]::new($_.Exception.Response.GetResponseStream())
      $ResponseBody = $reader.ReadToEnd()
    } catch {
      $ResponseBody = "<unreadable error body>"
    }
  } else {
    $HttpStatus = "client/proxy exception before response"
    $ResponseBody = $_.Exception.Message
  }
}

[pscustomobject]@{
  http_status = $HttpStatus
  attempt_id = $attemptId
  provider_job_id_redacted = ("smoke_job_..." + $providerJobId.Substring($providerJobId.Length - 4))
  provider_request_id_redacted = ("smoke_req_..." + $providerRequestId.Substring($providerRequestId.Length - 4))
  response_received = ($null -ne $ResponseBody)
}
```

There is no retry, no loop, no automatic rerun after timeout, and no second submission after uncertainty. The Authorization header exists only in memory.

## Pre-submit checklist

Immediately before the call, Carson verifies:

- no second terminal/window will run the same command;
- provider Modal app is deployed and healthy;
- HF Space is running;
- no new deploy/restart is in progress;
- fixture StorageReference was obtained after latest deployment;
- exact fixture hash and size are inserted;
- result profile is `standard`;
- provider options are omitted;
- IDs are unique;
- operator token is not echoed;
- logs are open in a separate window;
- stop conditions are understood.

## Phase 0 - source transport expectation

`process-once` creates the in-memory Transport Grant and temporary source URL. The human must not call a grant API and must not construct the source URL manually.

Expected observable evidence:

- provider attempts source retrieval;
- transport endpoint retrieval count changes internally;
- visible HF logs do not reveal token or full URL;
- no separate grant API is called.

## Phase 1 - provider submission

Expected outcomes:

- exactly one async job is accepted;
- provider job identity equals the supplied `provider_job_id`;
- no automatic resubmission occurs;
- provider auth failure produces a safe failed operator response;
- submission uncertainty requires stopping and reconciliation, not rerunning.

## Phase 2 - polling

Atlas waits approximately five minutes maximum with initial poll interval two seconds, maximum poll interval ten seconds, and backoff factor 1.5. A client/proxy disconnect may occur before processing ends. A disconnect does not authorize resubmission; the provider may continue. On timeout or submission uncertainty, the transport grant remains expiry-managed rather than being immediately revoked.

## Phase 3 - result retrieval and Raw Result retention

Expected success evidence:

- provider reaches terminal `completed` or terminal `partial_failed` state;
- `standard` result is retrieved;
- Raw Processing Result is retained in Atlas-controlled Storage;
- operator response includes safe Raw Result storage reference, checksum, and size;
- no source URL or token is included;
- original source remains retained.

## Phase 4 - grant finalization

Expected:

- success or definite terminal failure revokes the grant;
- timeout or submission uncertainty does not revoke immediately;
- later endpoint access follows the grant state (`revoked`, `expired`, or still active until TTL);
- source object is not deleted.

## Safe response fields

Production response fields are: `status`, `processing_attempt_id`, `provider_name`, `provider_job_id`, `provider_request_id`, `provider_terminal_status`, `integration_terminal_phase`, `raw_result_storage_reference`, `raw_result_sha256`, `raw_result_byte_size`, `poll_count`, `elapsed_seconds`, `grant_id`, `grant_final_state`, `revocation_succeeded`, `error_category`, `error_phase`, `retry_guidance`, and `warnings`.

Classification:

| Field | Classification | Handling |
| --- | --- | --- |
| `status`, `provider_name`, `provider_terminal_status`, `integration_terminal_phase`, `raw_result_sha256`, `raw_result_byte_size`, `poll_count`, `elapsed_seconds`, `grant_final_state`, `revocation_succeeded`, `error_category`, `error_phase`, `retry_guidance`, `warnings` | Safe to record | Record if warnings contain no secrets. |
| `processing_attempt_id` | Safe to record for this disposable smoke | Redact to prefix plus final four characters in public evidence if desired. |
| `provider_job_id`, `provider_request_id`, `grant_id` | Must redact before PR/comment | Operator already redacts known underscore IDs; public evidence must retain only prefix plus final four characters. |
| `raw_result_storage_reference` | Safe only privately | May be retained privately; do not post publicly unless explicitly approved as non-sensitive. |
| StorageReference for the source fixture | Safe only privately | Never place full value in public evidence. |
| Operator token, provider token, transport token, full source transport URL, complete Authorization header, raw source bytes, raw result body | Forbidden to record | Do not capture or post. |

## Response interpretation matrix

| Outcome | Stop/continue | Resubmit allowed? | Grant expectation | Evidence to capture | Next action |
| --- | --- | --- | --- | --- | --- |
| Success | Stop as PASS | No | Revoked | Redacted IDs, terminal state, poll count, elapsed time, raw result checksum/size, revocation state | Preserve redacted evidence and retained Raw Result through H closeout. |
| Partial | Stop for review | No | Revoked if terminal partial result returned | Redacted IDs, partial state, warnings/errors, raw result checksum/size if retained | Review partial output privately; decide later task. |
| Provider auth failure | Stop | No | Revoked for definite failure if grant was created | HTTP/status body without secrets, error category/phase | Fix configuration after review; create new deliberate attempt only if approved. |
| Provider failed | Stop | No | Revoked | Provider terminal state, safe provider error code, redacted IDs | Inspect provider job safely by supplied ID. |
| Provider expired | Stop | No | Revoked | Terminal expired state, elapsed time, poll count | Review TTL/timing; new attempt only after explicit decision. |
| Timeout | Stop | No | Expiry-managed, not immediately revoked | Timeout category, poll count, elapsed time, grant state | Reconcile provider job and wait for TTL where needed. |
| Submission uncertain | Stop | No | Expiry-managed if grant exists | Submission uncertainty category and client/proxy details | Reconcile provider job before any future attempt. |
| Invalid retained source | Stop | No | No grant or revoked depending failure point | Validation message only | Correct private StorageReference/evidence; do not rerun without review. |
| Source transport unavailable | Stop | No | Revoked for definite provider failure, or expiry-managed if uncertain | HTTP category, provider download error, HF logs without URL/token | Diagnose HF/source transport; no automatic rerun. |
| Checksum mismatch | Stop | No | Revoked or failed retrieval | Mismatch category without bytes | Treat as integrity incident; do not reuse source. |
| Raw Result ingestion failure | Stop | No | Revoked | Error category, provider terminal state, no raw body | Preserve provider evidence privately; fix ingestion separately. |
| Unexpected failure | Stop | No | Revoked unless uncertainty path says otherwise | Error category/phase and safe warnings | Triage logs; no second invocation. |
| HTTP proxy/client timeout with unknown server outcome | Stop | No | Unknown from client; possible active grant until TTL | Client timeout timestamp, generated IDs, logs | Reconcile server/provider state; do not rerun. |

## No-resubmit rule

**Do not invoke process-once a second time after any ambiguous outcome.**

A second submission is permitted only after explicit review proves the first provider job was not accepted and a new attempt/job ID is deliberately created.

## Stop conditions

Stop immediately if any of the following occurs:

- token/full URL appears in visible logs;
- provider authentication unexpectedly fails;
- source checksum mismatch;
- source transport 404/500/503 occurs during provider retrieval;
- multiple provider jobs appear;
- job identity mismatch;
- provider protocol response differs materially;
- Raw Result cannot be retained safely;
- customer data appears;
- HF restart occurs after submission;
- operator response contains a secret/full URL;
- proxy timeout leaves server outcome unknown.

## Safe evidence capture

Redacted evidence record may contain only:

- execution timestamp;
- Atlas commit;
- provider deployment revision if safely available;
- fixture SHA-256 and size;
- redacted attempt/job/request IDs;
- response category;
- provider terminal state;
- poll count;
- elapsed time;
- Raw Result checksum/size;
- grant final state;
- revocation state;
- PASS/FAIL;
- notes.

Do not record:

- operator token;
- provider token;
- transport token;
- full transport URL;
- complete Authorization header;
- raw source bytes;
- raw result body;
- full StorageReference in public evidence;
- full provider job/request IDs.

## Cleanup

After success:

- keep the first successful Raw Result through H closeout;
- keep the original fixture retained until H closeout;
- disable the operator route after smoke if no additional test is planned;
- preserve only redacted evidence;
- do not delete source automatically.

After failure:

- do not rerun automatically;
- inspect provider job by supplied job ID;
- wait for TTL where required;
- disable operator if leakage/security issue occurred;
- document the failure safely.

## Human confirmation block

Carson can paste this into the PR or private execution record before execution:

```text
M2-003H-E controlled live provider smoke confirmation
- One-job rule accepted: yes/no
- Synchronous timeout risk accepted: yes/no
- No-resubmit rule accepted: yes/no
- Test-only fixture confirmed: yes/no
- Logs monitored: yes/no
- Private StorageReference ready: yes/no
- Secrets configured: yes/no
- Stop conditions accepted: yes/no
- Owner/approver confirmed: Carson
```

## Definition of success

Success requires all:

1. one operator invocation;
2. one provider job;
3. provider retrieves Atlas source;
4. source integrity accepted;
5. terminal provider result reached;
6. standard result retrieved;
7. Raw Result retained;
8. original source remains;
9. grant finalized by policy;
10. no secrets/full URL leaked;
11. no duplicate submission;
12. redacted evidence captured.

## Non-goals

No code implementation, no provider call, no job submission, no additional API, no queue, no database persistence, no MinerU-Popo, no Structured Content, no Reader integration.
