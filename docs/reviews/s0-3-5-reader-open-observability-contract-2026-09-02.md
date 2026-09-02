# S0.3.5 Reader core-open observability contract

Status: implementation under review; Staging runtime acceptance pending. S0 and M5 remain In Progress. This instrumentation does not start S1/S2 or authorize Production rollout.

## Measured boundary

The inspected Backend base is `c5817070b85e6778db3dbdf558cd8fd756ffb904`; the inspected Reader base is `a3ca1c861a513ec0997eaa89be9419a7659ca68a`. The frontend's existing `ReaderV2Controller.openBook` requests metadata, navigation and one 150-node window for a fresh open. A valid saved `node_order` restores the target window and, when present, its next window. The Backend currently reconstructs the whole selected candidate before producing bounded HTTP content. A bounded node response does **not** establish a bounded database row/byte footprint; this slice records actual statement counts without changing that behavior.

| Metric | Meaning |
|---|---|
| `reader_open_latency_seconds` | Client-reported monotonic time inside core `openBook`, after reset/document selection through initial semantic rendering, navigation re-enable and synchronous page-change notification. Per-mode mean and sample count; only observed modes appear. |
| `reader_bounded_query_count` | Actual SQLAlchemy `before_cursor_execute` statement attempts on the Backend engine across the correlated metadata/navigation/content requests, grouped by completed open and mode. Not HTTP request count or a claim of bounded rows. |
| `reader_open_breakdown` | Each random open scope, mode, frontend/backend revision, client duration, statement count, request count and sum of server request durations. |

The client boundary excludes book-list selection/reset overhead before its timer, browser paint, asynchronous formula/layout enhancements, binary image/asset completion, surrounding Reader UI wrappers and subsequent interactions. The label is a **core semantic-open** baseline, not complete visible-page readiness or upload-to-Reader-ready latency. Server request seconds run from the ASGI middleware through final body-send completion; they include routing, service work and serialization. They are auxiliary, not substituted for client duration.

Binary asset requests are excluded by route. Telemetry POSTs and candidate/run association queries run outside the measured SQL context. Counts include attempted statements even if a service catches a database error; only completed HTTP 200 responses can produce successful request events. SQL text, parameters, results and connection identifiers are never retained.

## Staging gates and request correlation

Only the `s0-reader-open-observability` frontend PR Preview build receives the explicit S0 meta marker. Runtime requires that marker, a PR Preview pathname, exact frontend revision meta and the fixed Backend Staging origin. Ordinary Preview keeps its existing test backend, and Production remains inert. Preview checkout uses the exact candidate SHA; branch guards and public asset-byte verification cover the four S0-relevant scripts and marker.

The Backend overlay adds the observer/terminal endpoint only when `staging-revision.txt` contains a valid exact SHA. Raw Production route/main sources and Production deployment workflow are unchanged. Requests carry an opaque `reader_<32 hex>` operation scope and ordinal headers; the Backend exposes its exact revision in a response header. The client requires consistent revision and candidate responses before sending its terminal. Client timing/frontend revision are reported by the authenticated client, not independently attested browser performance data.

First-open coverage is exactly metadata → navigation → content at window start zero, limit 150. Reopen coverage is metadata → navigation → target content, optionally followed by its adjacent 150-node window. Maximum four requests. Existing legacy node-id-only resume can scan, so it is excluded; no scan or loading behavior is rewritten. Empty semantic results, failed/overlapping opens, revision/candidate changes or unsupported request sequences do not report a successful client terminal.

## Durable evidence and collector rules

`S0_READER_OPEN_REQUEST_MEASURED` records scope, ordinal, route, backend revision, hashed candidate identity, window start/limit, server duration and statement count. `S0_READER_OPEN_TERMINAL` records scope, client/frontend/backend revision, mode, duration and request count. Both use `reader_v2_core_open_v1`.

The already-built view supplies candidate identity without another query in the measured path. Persistence runs in a worker thread that owns session creation, association lookup, commit/rollback and close. It joins that immutable candidate's `processing_run_ref` to a succeeded run belonging to the same document. It never guesses the latest run. Missing legacy provenance produces no measurement. Raw candidate IDs are hashed before event persistence; content, filename, URL, storage ref and credentials are not event fields. The terminal body accepts only its seven fields, with a 2,048-byte streaming limit, bounded identities and finite duration up to 3,600 seconds.

The client sends its terminal without awaiting or retrying it. Request event persistence can finish after the client receives the body; collect only after durable writes settle. A persistence exception cannot change a delivered Reader response or block the event loop. Missing evidence remains unavailable.

Collector admission requires exact allowlisted fields, one terminal per open, contiguous ordinals, the correct request sequence, aligned/adjacent windows, stable candidate/backend revision, finite times and valid nonnegative counts. Up to 32 opens may be summarized per ProcessingRun; modes remain separate. All summarized opens must share frontend/backend revisions. Duplicate, missing, malformed, oversized, over-bound or mixed-revision evidence is `not_available`; unrelated snapshot incompleteness is `partial`. A successful first-open sample does not claim reopen coverage.

An abandoned partial open remains incomplete evidence for that run and prevents `observed`; it is not silently dropped. Operator acceptance must retain this limitation and use a fresh isolated processing run when prior incomplete or differently versioned opens contaminate the evidence. This does not justify automatically uploading or reprocessing a PDF.

## Verification and acceptance

Contract tests cover real SQL counting through the sync route worker, concurrent request isolation, disconnects, blocked/failed persistence, exact candidate/run association, field privacy, body limits, malformed/duplicate/incomplete/mixed-revision evidence, and composition reruns. Frontend tests preserve existing request counts, first/reopen behavior, gating, candidate/revision checks and detached no-retry submission.

After explicit Backend merge and exact Staging deployment verification, use this PR's exact Preview with an already processed small fixture that has durable candidate/run provenance. Collect first-open evidence; save a valid position, close/reopen and collect reopen evidence. Match immutable candidate/run IDs, both runtime revisions, unique scopes/ordinals, statement counts and the two separate timing boundaries. A later nonzero target-window test may use an already processed document with enough nodes; no new 100-page or 528-page benchmark is authorized. No runtime PASS is claimed by this implementation document.
