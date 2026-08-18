# Source Transport Deployment Preflight

Task ID: M2-003G.1 — Deployment Preflight and Live Smoke Preparation.

| Field | Value |
|---|---|
| Document Type | Deployment Preflight |
| Evidence Role | Point-in-time source-transport deployment-preflight evidence |
| Result Status | PASS WITH BLOCKERS |
| Later Status | Local/manual endpoint preflight moved out of deployment blockers; final verification GO FOR M2-003H |
| Authority Domain | Source-transport deployment readiness findings at the inspected environment and revision boundaries |
| Applies To | Disposable M2-003H deployment gate; public Hugging Face origin; private source transport endpoint; process-local grant service; Required Backend CI endpoint tests; provider configuration presence; deployment blockers inspected in M2-003G.1 and M2-003G.2 |

## Overall result

**PASS WITH BLOCKERS.** The source transport endpoint and grant tests are ready to run in Required Backend CI, the real app imports locally, and the Hugging Face entrypoint now disables Uvicorn access logs for the disposable test deployment. M2-003H is **not authorized** because this environment could not install CI dependencies due network/package-index blocking, no public HTTPS Atlas/HF origin was provided, platform/reverse-proxy path logging is not yet proven redacted or disabled, provider test credentials were not verified, and no manual smoke owner was identified.

No live provider call occurred. No plaintext source transport token or complete transport URL is committed in this repository.

## Repository and revision evidence

Repository preflight was performed from `/workspace/pdf-ocr-service` on branch `work`.

- Repository root: `/workspace/pdf-ocr-service`.
- Service HEAD inspected before changes: `d942169c50898880115e9b008f249096c3d43ce0`.
- Provider reference HEAD: `3a790e3e4c0ececef316bd2ca5aa03d84f6c6159`.
- Provider reference status before and after this task: clean.
- Required files were present: `app/main.py`, `app/routers/source_transport.py`, `app/processing/transport/dependencies.py`, `app/processing/transport/service.py`, `tests/test_source_transport_endpoint.py`, `tests/test_source_transport_grants.py`, `docs/processing/private-source-transport-endpoint.md`, `docs/processing/provider-reachable-source-transport.md`, `docs/milestones/M2.md`, and the provider reference repository's current protocol inventory.

Recent merged-main history included M2-003G (`Merge pull request #65`) and M2-003F/M2-003E predecessor work.

## Required Backend CI evidence

Required Backend CI installs `requirements-ci.txt` and `requirements-test.txt`. `requirements-ci.txt` includes FastAPI, Uvicorn/Starlette transitively, SQLAlchemy, HTTPX, Alembic, PyYAML, and other runtime/import dependencies needed by the real app and endpoint tests, while intentionally excluding local OCR model stacks.

Before this task, Required Backend CI used explicit compile/collection/test file lists and omitted:

- `tests/test_source_transport_grants.py`;
- `tests/test_source_transport_endpoint.py`.

This task made the smallest CI change: those two files were appended to the existing static syntax check, collect-only smoke, and lightweight required pytest command. No CI architecture, runner, dependency, or live-network behavior was broadened.

## Endpoint test execution evidence

Required focused command attempted locally:

```bash
python -m pytest -q tests/test_source_transport_grants.py tests/test_source_transport_endpoint.py
```

Result in the initial environment: **failed during test configuration**, before collection, because SQLAlchemy was not installed:

```text
ModuleNotFoundError: No module named 'sqlalchemy'
```

Repository-conventional dependency installation was attempted:

```bash
python -m pip install -r requirements-ci.txt -r requirements-test.txt
```

Result: **blocked by package-index/network policy** with `Tunnel connection failed: 403 Forbidden`, so the complete dependency environment could not be created in this Codex environment. Exact collected/passed/failed endpoint counts therefore remain unavailable locally. Required Backend CI is now configured to execute both endpoint files once dependency installation succeeds in GitHub.

## Real app startup evidence

Local direct import of `app.main:app` could not be completed in this environment for the same missing SQLAlchemy dependency. Static inspection confirms:

- `app/main.py` constructs the single FastAPI `app` and includes `source_transport.router` once.
- `app/routers/source_transport.py` defines `APIRouter(prefix="/internal/source-transport", include_in_schema=False)`.
- The endpoint has explicit `GET /{token}` and `HEAD /{token}` handlers. HEAD raises 405 and does not call `record_retrieval`.
- `get_storage_provider_factory()` returns the storage resolver callable, so Storage construction is deferred until after grant authorization.
- The process-local grant service is created at import time, but no grant configuration, provider client configuration, or source transport I/O is required at startup.
- Existing health, OCR, books, images, and root routes remain registered by `app/main.py`.

Manual confirmation still required after dependencies are available:

1. Import `app.main:app`.
2. Count `/internal/source-transport/{token}` GET routes and confirm exactly one.
3. Fetch OpenAPI and confirm `/internal/source-transport/{token}` is absent.
4. Confirm HEAD returns 405 and retrieval count is unchanged.
5. Confirm startup performs no source transport Storage read/write.

## Worker/process evidence

Deployment entrypoints inspected:

- `Dockerfile` runs `python app.py`.
- `Procfile` runs `python app.py`.
- `app.py` runs Uvicorn for Hugging Face Spaces on `0.0.0.0:7860` with `reload=False`; this task added `access_log=False`.
- `render.yaml` declares `gunicorn app:app`, but the root `app.py` does not expose an ASGI variable named `app`; this Render configuration is not treated as authoritative for the disposable HF smoke without review.
- No `WEB_CONCURRENCY` setting was found in repository deployment files.

Classification: **single process inferred but not authoritative** for HF/Docker/Procfile because `python app.py` uses one Uvicorn process by default and no reload, but the external platform must still confirm it is not wrapping the command with multiple replicas/processes. Multiple workers are **not supported** for this disposable bridge because grants are process-local and restart-losing.

GO for M2-003H requires deployment-side confirmation of exactly one effective application worker/process/replica.

## Public origin evidence

No externally reachable Atlas/HF origin was provided in the repository or task environment. M2-003H remains blocked until a human confirms a public HTTPS origin for the disposable deployment.

Future URL construction boundary must remain conceptual until orchestration integration is authorized:

```text
trusted configured public_origin
  + /internal/source-transport/
  + plaintext opaque token
```

Rules for the future builder/checklist:

- HTTPS only.
- No trailing-slash ambiguity.
- No query-token alternative.
- No StorageReference, document ID, source_file_id, or business ID in the URL.
- Constructed URL returned only to the immediate caller.
- No persistence of constructed URLs or plaintext tokens in Atlas business metadata.
- No logging of complete URL.
- No redirect-based URL construction.
- Origin must come from trusted deployment configuration, not request `Host` headers.
- Reject origin path, query, fragment, and userinfo unless a later task intentionally designs otherwise.

No URL-construction helper was added because orchestration integration and provider submission remain out of scope.

## Access-log exposure evidence

Critical secret-bearing path:

```text
/internal/source-transport/{plaintext-token}
```

Layer classification:

| Layer | Classification | Evidence / action |
| --- | --- | --- |
| Application route logging | Proven not to log full path by route code inspection | `source_transport.py` does not log token, URL, path, or grant metadata. |
| Uvicorn access logging in HF entrypoint | Configurable and disabled for disposable test entrypoint | `app.py` now passes `access_log=False`; this disables all Uvicorn access logs for that process. |
| Docker/Procfile path | Configurable and disabled through `python app.py` | Both use the modified `app.py`. |
| Render `gunicorn app:app` | Unknown / not authoritative | Needs separate review before any Render smoke. Gunicorn/proxy access logs may include paths. |
| Reverse proxy / platform logs | Unknown | HF/platform path logging must be verified disabled or redacted before live smoke. |
| Analytics/error monitoring | Unknown | No analytics/error-monitoring integration was found in deployment files, but platform add-ons must be checked. |
| GitHub/Codex logs | Avoided | This document and commands do not include plaintext tokens or full transport URLs. |

Disposable live smoke safe path selected: **disable Uvicorn access logs** via `access_log=False` in `app.py`. This does not prove platform/reverse-proxy logging is safe. If platform-level path logging cannot be verified disabled or redacted, live smoke is **NO-GO**.

## Transport URL construction decision

Design documentation only. No runtime URL builder was added. Complete transport URLs and plaintext tokens must remain in process memory only during the eventual manual smoke and must not be persisted in Atlas metadata, PR comments, screenshots, logs, database rows, or troubleshooting notes.

## Test PDF evidence

A small deterministic, non-sensitive test-only PDF fixture was added:

- File: `tests/fixtures/source_transport/test-only-source-transport.pdf`.
- Size: `605` bytes.
- SHA-256: `fb084e43d06e039118d2a72a40353eebcec09abdbe732cf30917608723126420`.
- Purpose: local/manual source transport preflight only.
- Content: synthetic one-page PDF text: `Atlas source transport test PDF`.
- Contains no customer data, personal data, or copyrighted book content.

## Local endpoint preflight evidence

A live local endpoint preflight could not be executed in this environment because repository dependencies could not be installed. The manual preflight procedure is ready and must be run before M2-003H:

1. Start from a complete dependency environment.
2. Use the real FastAPI app and real `InMemoryTransportGrantService`.
3. Use `LocalStorageProvider` or the actual configured Storage.
4. Read `tests/fixtures/source_transport/test-only-source-transport.pdf` and compute SHA-256.
5. Write/retain the bytes into Storage with expected size and SHA-256.
6. Create a short-lived grant for the StorageReference, media type `application/pdf`, exact byte size, exact SHA-256, replay allowed, and a low retrieval cap if desired.
7. Construct the local token URL only in memory.
8. GET the real `/internal/source-transport/{token}` endpoint.
9. Verify HTTP 200.
10. Verify response bytes exactly match the fixture.
11. Verify SHA-256 matches `fb084e43d06e039118d2a72a40353eebcec09abdbe732cf30917608723126420`.
12. Verify `Content-Length`, `Cache-Control: private, no-store`, `Pragma: no-cache`, `X-Content-Type-Options: nosniff`, and `application/pdf` media type.
13. Verify retrieval count increments.
14. Repeat GET within TTL if replay is intentionally allowed.
15. Revoke the grant.
16. Confirm later GET returns 404.
17. Confirm the Storage source remains present after revoke.
18. Inspect visible logs and fail the preflight if the plaintext token or full URL appears.

Do not commit the generated token or generated URL.

## Live smoke checklist

Documented only; **do not run until all GO criteria are met**.

1. Verify Required Backend CI is green on latest main.
2. Verify one effective worker/process/replica.
3. Verify access-log token redaction/disablement across application, Uvicorn, reverse proxy, platform, analytics, and troubleshooting logs.
4. Deploy latest main to a disposable HF environment.
5. Verify the health endpoint.
6. Store a non-sensitive PDF.
7. Create a short-lived grant.
8. Construct the provider-reachable HTTPS URL in memory only.
9. Submit exactly one provider async job.
10. Pass source SHA-256.
11. Confirm provider downloads source.
12. Poll status.
13. Retrieve the richest available result.
14. Ingest Raw Processing Result.
15. Compare source hash.
16. Verify transport retrieval count.
17. Revoke grant after safe completion.
18. Verify later transport GET returns 404.
19. Inspect all visible logs for token leakage.
20. Delete disposable test artifacts if appropriate.

Safety rules:

- No token in screenshots.
- No URL in PR comments.
- No bearer token in logs.
- No customer PDF.
- No repeated provider submission on uncertainty.
- Stop immediately if the path token appears in persistent logs.

## Go/No-Go checklist

GO requires all of:

- [ ] Required Backend CI green.
- [ ] Endpoint tests executed, not only statically inspected.
- [ ] Real app startup succeeds.
- [ ] One effective worker/process/replica confirmed.
- [ ] Public HTTPS origin confirmed.
- [ ] Source transport endpoint externally reachable.
- [ ] No full token path retained in accessible logs.
- [x] Non-sensitive test PDF ready.
- [x] Grant TTL/replay behavior accepted for disposable M2 bridge.
- [ ] Local endpoint preflight passed.
- [ ] Provider test credentials available.
- [ ] Manual smoke owner identified.
- [x] No production data required.

NO-GO if any of:

- [x] Endpoint tests are unexecuted locally due missing dependencies.
- [ ] Endpoint tests fail in Required Backend CI.
- [ ] Multiple workers share no registry.
- [x] Token path logging unresolved at platform/reverse-proxy layer.
- [ ] HF instance unavailable or unstable.
- [x] Public origin unknown.
- [ ] Source disappears on restart during test.
- [x] Test credentials unavailable/unverified.
- [ ] Only sensitive PDFs available.
- [ ] Provider protocol revision changed without re-verification.

## Configuration/code changes

- Required Backend CI explicit test lists now include source transport grant and endpoint tests.
- HF/Docker/Procfile Uvicorn entrypoint now sets `access_log=False` for the disposable smoke path.
- Added the test-only PDF fixture above.
- Added this preflight document and linked it from M2 documentation.

No orchestration, upload flow, OCR flow, Reader behavior, database model, Alembic migration, provider client protocol, grant persistence, object storage, presigned URL, streaming, or provider reference change was made.

## Security findings

- Current grants are opaque path credentials and process-local. They are not multi-worker safe.
- Uvicorn would normally log request paths through access logs; for the disposable `python app.py` entrypoint this task disables Uvicorn access logs.
- Platform/reverse-proxy path logging is still unresolved and is a live-smoke blocker.
- Complete transport URLs and plaintext tokens must not be persisted in Atlas metadata, logs, screenshots, PR comments, or docs.
- The endpoint remains excluded from OpenAPI by router configuration.

## Remaining blockers

- Complete dependency environment unavailable in this Codex run because package-index access returned 403.
- Required Backend CI must run and pass after this PR.
- Real app startup/TestClient checks must be rerun with dependencies installed.
- One effective worker/process/replica must be confirmed in the actual disposable deployment.
- Public HTTPS origin must be identified and verified externally reachable.
- Platform/reverse-proxy logging must be proven disabled or redacted for token-bearing paths.
- Provider test credentials and manual smoke owner must be identified.
- Local endpoint preflight must pass.

## M2-003H authorization

**M2-003H is not authorized.** The result is PASS WITH BLOCKERS, not GO. Authorization requires all GO criteria above, especially executed endpoint tests in Required Backend CI, confirmed real app startup, single process, confirmed public HTTPS origin, proven no token-bearing path retention in logs, local endpoint preflight pass, available provider test credentials, and a named manual smoke owner.


---

## M2-003G.2 Deployment Environment Verification

Date: 2026-07-15.

### Result

**GO FOR M2-003H.** Human deployment-owner evidence verifies the trusted public HTTPS origin, the current disposable one-process/one-worker posture, application/Uvicorn-visible access-log behavior for a synthetic canary path, provider deployment configuration presence, and manual smoke ownership. Required Backend CI has now passed and executed both focused source transport test files in the complete dependency environment. The local/manual endpoint preflight sequence is moved out of deployment blockers and will be executed as the first controlled end-to-end step of M2-003H using the real orchestration flow.

### Evidence gathered

- Repository preflight was run from `/workspace/pdf-ocr-service` on branch `work`.
- Service HEAD inspected for this verification: `c45e700860fdfca612f85db7798625eb1a56cbbd`.
- Provider reference HEAD inspected before documentation update: `3a790e3e4c0ececef316bd2ca5aa03d84f6c6159`.
- Provider reference status before documentation update: clean.
- Required task files were present, including `app.py`, `app/main.py`, `app/routers/source_transport.py`, `app/processing/transport/dependencies.py`, both focused source transport test files, the deterministic test PDF, and `docs/milestones/M2.md`.
- Deployment files inspected: `Dockerfile`, `Procfile`, `render.yaml`, `.github/workflows/backend-tests.yml`, repository requirements files, and the root `app.py` HF entrypoint.
- Human deployment-owner evidence was provided for the live Hugging Face Space origin, container-log process posture, canary-path log behavior, provider configuration presence, and manual smoke ownership. Secret values, bearer tokens, live grant tokens, and complete transport URLs were not requested, printed, inspected, or committed.
- Required Backend CI passed and executed `tests/test_source_transport_grants.py` and `tests/test_source_transport_endpoint.py` in the complete dependency environment.

### Required Backend CI evidence

Required Backend CI is configured to install `requirements-ci.txt` and `requirements-test.txt`, then compile, collect, and run `tests/test_source_transport_grants.py` and `tests/test_source_transport_endpoint.py` together with the existing lightweight backend tests.

Local endpoint test execution was attempted with:

```bash
python -m pytest -q tests/test_source_transport_grants.py tests/test_source_transport_endpoint.py
```

It failed before collection because `sqlalchemy` is not installed in this environment. A repository-approved dependency installation was then attempted with:

```bash
python -m pip install -r requirements-ci.txt -r requirements-test.txt
```

That installation failed because package-index access returned `Tunnel connection failed: 403 Forbidden`, so the local Codex environment still did not run the tests. Subsequent Required Backend CI evidence confirms the workflow passed and executed `tests/test_source_transport_grants.py` and `tests/test_source_transport_endpoint.py` in the complete dependency environment. Endpoint behavior and real app/TestClient runtime coverage represented by those focused tests are therefore verified for the deployment gate.

### Public HTTPS origin status

**Verified for the current disposable Hugging Face deployment.**

- Trusted public HTTPS origin: `https://carsonhhs-pdf-ocr-service.hf.space`.
- How obtained: observed as the deployed Hugging Face Space runtime origin by the deployment owner.
- Reachability: verified reachable over HTTPS by the deployment owner.
- Source transport deployment: verified deployed at the expected private endpoint path.
- Canary endpoint behavior: a synthetic invalid canary token request returned the collapsed 404 response.
- Redirect/path status: the verified origin is recorded without a trailing path, query, or fragment and is suitable for constructing `<origin>/internal/source-transport/<token>` in memory only.

No live plaintext grant token or complete transport URL is recorded here.

### Worker/process/replica status

**Classification: VERIFIED single process / one worker / one replica for the current disposable test deployment only.**

Human deployment-owner evidence reports that visible Hugging Face container logs show one Uvicorn server process, the repository entrypoint uses `reload=False`, and no multi-worker configuration was observed. This is accepted as one effective process/worker for the current disposable M2 test deployment only. It does not prove production multi-worker safety, and the current process-local in-memory grant registry remains unsuitable for multiple workers/replicas.

### Access-log result

**Application/Uvicorn-visible access logging is verified as not retaining the full token-bearing path for this deployment.**

Evidence:

- `app.py` uses `access_log=False` for the repository-controlled Uvicorn entrypoint.
- After a synthetic `LOGCANARY` token path request, visible Hugging Face Container Logs did not change and did not contain the canary token or source-transport request path.
- The synthetic canary was invalid and did not use a real grant credential.

Layer classification for M2-003G.2:

| Layer | Classification | Evidence |
| --- | --- | --- |
| Application route logging | Full path not intentionally logged by source inspection | Route code has no logging of token/path/URL. |
| Uvicorn access logs in repository entrypoint | Full path not logged for current deployment | `app.py` sets `access_log=False`; visible logs did not change after the canary request. |
| HF Space Container Logs visible to owner | Full path not logged | Visible container logs did not contain the canary token or source-transport path after the request. |
| HF internal CDN/reverse-proxy logs | Unknown/unavailable to Space owner | Not observable by the Space owner; residual risk accepted for disposable M2 testing only, not production. |
| Analytics/error monitoring | Unknown/unavailable | No attached service inventory was available in this repository run. |

This evidence is sufficient to proceed with disposable M2 testing once the remaining non-log blockers are resolved. It is **not** a production logging clearance; production requires an architecture that does not expose bearer credentials in retained paths or requires authoritative platform log controls.

### Local endpoint preflight result

**Status: moved out of deployment blockers.** The deterministic fixture remains documented with size `605` bytes and SHA-256 `fb084e43d06e039118d2a72a40353eebcec09abdbe732cf30917608723126420`.

This sequence will be executed as the first controlled end-to-end step of M2-003H using the real orchestration flow, after authorization and before any live provider OCR submission. It must verify exact body, headers, replay count, revoke-to-404 behavior, retained Storage object presence, and absence of token/full-URL output. No provider call is part of this preflight step itself.

### CI result

**Passed.** Required Backend CI has passed and executed `tests/test_source_transport_grants.py` and `tests/test_source_transport_endpoint.py`. Endpoint behavior is therefore verified in the complete dependency environment.

### Provider prerequisite status

No live provider call occurred. Provider readiness for configuration presence is improved, but authentication validity remains pending M2-003H live smoke:

- Provider base URL: `PADDLE_VL_API_BASE_URL` is configured in the Hugging Face deployment; the value is not recorded here.
- Provider bearer token secret: `PADDLE_VL_API_BEARER_TOKEN` is configured as a Hugging Face secret; the value was not printed, inspected, or validated in this task.
- Provider authentication validity: pending the M2-003H live smoke.
- Provider protocol revision: repository fixtures still reference provider reference commit `3a790e3e4c0ececef316bd2ca5aa03d84f6c6159`, matching the read-only provider reference HEAD inspected in this run.
- Provider-network reachability to the source URL: plausible in principle because the trusted HTTPS origin is publicly reachable, but actual provider download behavior remains for M2-003H.
- Non-sensitive PDF: available, deterministic test fixture only.
- Human smoke owner: Carson.
- Stop/rollback owner: Carson.

### Owner and manual smoke procedure

Manual smoke owner: Carson.

Assigned to Carson for the future live smoke:

- Deploy latest main.
- Create the grant.
- Submit one provider job only after all GO criteria are met.
- Monitor Hugging Face Container Logs and any other visible deployment logs.
- Stop immediately on token leakage.
- Revoke the grant.
- Clean test artifacts.
- Record results.

### Remaining blockers

None for the disposable M2-003H deployment gate. Hugging Face internal CDN/reverse-proxy logs remain outside the observable boundary of the Space owner and are accepted as residual risk for disposable M2 testing only, not production. The local/manual endpoint preflight is no longer treated as a deployment blocker; it is the first controlled end-to-end step of M2-003H using the real orchestration flow.

### M2-003H authorization

**AUTHORIZED.** The final result for this verification is **GO FOR M2-003H**. Required Backend CI is verified green, the focused endpoint tests executed and passed in the complete dependency environment, real app/TestClient runtime evidence is satisfied by that CI coverage, public origin/process/access-log/provider-configuration/owner evidence is recorded, and the local/manual endpoint preflight has been moved to the first controlled end-to-end step of M2-003H. No live token/full URL or provider credential may be exposed during that step.

### Confirmations

- No live provider call occurred.
- No provider OCR job was submitted.
- No real grant token or complete transport URL was committed.
- No provider bearer token or private credential was printed, inspected, or committed.
- No orchestration, database, provider client, upload, OCR, Reader, Storage semantics, CI, or legacy pipeline behavior was changed.
- The read-only `paddle-vl-api` provider reference remained clean before this documentation update.
