# S0 upload-to-Reader implementation candidate

| Field | Value |
|---|---|
| Document Type | Testing / Implementation candidate |
| Approval Status | Implemented via Backend #46; scoped small acceptance PASS; repository record proposed |
| Lifecycle Status | Active |
| Date | 2026-09-10 |
| Scope | Staging canonical single-PDF upload to automatic initial semantic render |
| Parent contract | [Upload/Reader v1](../contracts/s0-upload-reader-observation-v1.md) |
| Baseline | Backend Staging `a640cf07c0b3db8e0cade4950e4cc74af2ac0cfc`; frontend source `a9d470c3609a94be45c525b47038d570c1855b01` |

Following boundary review and the instruction to continue implementation, this
candidate uses initial core semantic rendering as its endpoint. Images finishing
loading, asynchronous annotations/enhancements and browser paint remain excluded.
This is not a waiver or a claim that full visible-page readiness is measured.

## Backend

- The separate Staging overlay installs an upload response observer and protected
  terminal endpoint without changing the existing upload/Reader event schemas.
- The existing upload finalizer runs first, preserving its timing boundary. A
  scalar dispatch ID crosses to the response observer, which resolves committed
  PDF dispatch/run/source identity before acknowledging durable acceptance.
- An observer-owned PostgreSQL pool has two connections, no overflow, 0.5-second
  checkout and 2-second connection timeout. Statements use a 1-second timeout,
  with a 250-ms lock timeout. These are separate bounds, not a whole-request
  network deadline. At most two publication tasks are admitted without waiting.
- Per-document row locking and deterministic per-run event slots serialize
  cooperating writers; conflicting terminal/acceptance evidence invalidates the
  run rather than replacing the original event. No business row is created or
  updated by this observer.
- Strict JSON decoding rejects duplicate keys and oversized payloads, including
  Reader JSON used by the new join. The collector requires the accepted source
  and exact complete first-open scope; delayed rows remain unavailable until a
  complete snapshot is collected.

## Companion Preview

The frontend observer uses the existing Preview routing override, separate
Staging authentication, source marker and same-page Performance object. The
single-file handler passes its local observation through automatic selection
and existing Reader wrappers. Three bounded Reader data requests are retained.
Both elapsed endpoints are captured before terminal publication; neither POST
delays Reader completion. Overlapping upload operations and pending batch polls
cannot acquire another root. No File, FormData or source body is stored in the
observer.

## Verification and acceptance boundary

Focused tests cover strict decoding, exact-source/open joins, missing and
out-of-order evidence, conflicting/idempotent delivery, pre-run acceptance,
unchanged upload response bodies and publication cleanup after waiter cancellation.
PostgreSQL CI additionally exercises simultaneous writers and lock timeout in a
fresh disposable schema on its local test service. SQLite checks do not stand
in for that concurrency gate.

Frontend tests cover immediate and polled completion through the real single-file
method, one-file delegation, manual opens, overlapping uploads/batches, lifecycle
loss, clock replacement/expiry and detached publication. Existing Reader and
application regressions must pass with the companion candidate.

Follow-up: Backend #46 is merged and deployed. The [small acceptance record](../reviews/s0-upload-reader-small-acceptance-2026-09-11.md)
pins Backend/runtime `f3b7af8122d5e5fe946614c6e1ddd0047877d504` and frontend Preview
`086cda854c24680ea4ce1c414844f10af2c14dcf`. The new run has complete durable
upload/Reader evidence and `upload_to_reader_ready_seconds = observed` at
`170.5072 s`. The earlier attempt with no upload terminal remains unavailable;
no prior run is retroactively promoted into upload-clock evidence. Frontend #87
remains Draft and unmerged; no new fixture is requested for this accepted target.

The latest accepted snapshot has 17/19 required metrics observed. Full upload-owned
memory and full preprocessing CPU remain unimplemented and are not waived. S0
and M5 remain In Progress. No Production change, further merge, fixture upload,
medium rerun or 100/528-page benchmark is authorized by this document.
