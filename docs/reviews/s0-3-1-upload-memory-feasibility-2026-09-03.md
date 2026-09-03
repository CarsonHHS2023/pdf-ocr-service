# S0.3.1 local upload-memory feasibility checkpoint

| Field | Value |
| --- | --- |
| Document Type | Local feasibility evidence / point-in-time review |
| Date | 2026-09-03 |
| Proposal examined | [Upload-memory boundary and admission contract](../testing/s0-upload-memory-observability-v1.md) |
| Starting proposal revision | `67f51c01a928fa49c9458ac5f3185338f56b8fba` |
| Unchanged Backend Staging | `300b1d4e83a44aa6723a6143a9d82176e800d50b` |
| Local test outcome | 15 tests passed on each of CPython 3.11.15 and 3.12.13 |
| Full-memory producer decision | **NO-GO for deriving it from the inspected read/receive counters or a weak-reference-only release scheme** |
| Staging memory acceptance | Not performed; required metric remains `not_instrumented` |

## 1. Result and decision scope

The local experiments establish concrete counterexamples, not a new memory
measurement. **No complete upload-memory producer or live-buffer ledger was
implemented.** A peak cannot be reconstructed from the existing largest-read and
total-read counters: two different caller-controlled buffer lifetimes produce
identical evidence. Weak references to ordinary read-result bytes also cannot
provide the missing release callbacks in the tested CPython versions.

This rejects the inspected shortcuts; it does not establish that all possible
instrumentation methods are impossible. Context separation and arithmetic over
explicitly known buffers remain feasible building blocks, but complete lifecycle,
allocator and native/SDK coverage are not supplied by them. The single-payload
case still provides no incremental coverage beyond the existing auxiliary metric.

Keep `backend_upload_peak_memory_mb = not_instrumented`. This checkpoint is **not
a waiver**, does not reduce the four required gaps, and does not authorize
execution-model changes, another PDF, Production changes, or S1/S2. S0/M5 remain
In Progress. The next decision is whether to retain this explicitly open gap while
designing another S0 metric, or separately authorize a different attribution method
or limitation review; neither decision is made automatically here.

## 2. Reproducibility and provenance

The [standalone verification script](../../scripts/probes/s0_upload_memory_feasibility.py)
uses `unittest`, synthetic buffers of at most 8192 bytes per generated payload,
in-process Starlette parsing and automatically closed temporary spools. It invokes
the existing wrapper functions locally, without calling their global installer.
It does not start a server, make an HTTP request, parse a PDF, call a Provider,
instantiate a database session or invoke a real storage adapter. The fake storage
call tests argument identity only. Every test checks that installation remains
off and `UploadFile.read` itself remains unpatched.

This is **not** a replay of the composed HF artifact, a resolved HF dependency
inventory, an ASGI end-to-end upload, a database/durable-event test, an allocator
profiler or a throughput/memory benchmark. In particular, setting `finalized` in a
test is not evidence of durable acceptance. Neither the frozen-counter tests nor
the parser tests satisfy the full producer verification gate in the proposal.

Both local environments used Linux x86_64 CPython, with these resolved packages:

```text
fastapi==0.115.0
starlette==0.38.6
python-multipart==0.0.9
anyio==4.15.0
idna==3.19
typing-extensions==4.16.0
pydantic==2.13.5
pydantic-core==2.46.5
annotated-types==0.8.0
typing-inspection==0.4.4
```

The FastAPI and multipart versions match repository requirements; Starlette and
the other transitive versions above are the **local selection**, not a claim
about HF's installed packages. No dependency file or workflow was changed.
Reference-count and immediate weak-reference callback assertions are specifically
CPython observations, not portable guarantees for every Python implementation.

From the repository root, create disposable environments for each interpreter,
install the exact packages listed above, and run:

```bash
PYTHONPATH=. /path/to/cpython-3.11.15-venv/bin/python scripts/probes/s0_upload_memory_feasibility.py
PYTHONPATH=. /path/to/cpython-3.12.13-venv/bin/python scripts/probes/s0_upload_memory_feasibility.py
```

Each command reports its interpreter and core package versions, runs 15 cases and
exits nonzero if an assertion fails. These probes are explicitly local commands;
the existing named PR workflows do **not** automatically run this new script.
An ordinary CI success must not be relabeled as a probe run. The script may be
syntax-checked by the existing broad compilation step.

Content hashes bind the reproduced experiment without a self-referential commit:

| File | SHA-256 |
| --- | --- |
| `scripts/probes/s0_upload_memory_feasibility.py` | `da89031b73d5a16e72c8103ab709c804e291476c6d9568a9010f93dc9862e4ec` |
| `app/s0_upload_boundary_observability.py` | `0736752b8b6928a2030168169339858b1aaf002429c5ee0ee61ea18117f09a09` |

## 3. Observed counterexamples and positive controls

All sizes below are **synthetic logical payload lengths**, not measured RAM,
resident memory, allocation capacity, or values admitted to the baseline.

| Experiment | Observed result in both local environments | Consequence |
| --- | --- | --- |
| Read 4096 then 8192 bytes; retain both | Largest read 8192; total 12288; declared simultaneously held payload 12288 | Counterexample to largest-read-as-peak |
| Same reads; release the first before the second | Largest read 8192; total 12288; declared held-payload maximum 8192 | Identical telemetry does not determine liveness; summing reads is also wrong |
| Keep first ASGI message while receiving the next | Both bodies remain usable; total 12288 and largest chunk 8192 | The next receive is not a release boundary |
| Borrow a payload into a fake storage call, versus explicitly copy it | Borrowed argument/alias is the same object; synthetic copy is distinct | Counting call layers duplicates shared payload; actual SDK copies remain unknown |
| Weak-reference ordinary `bytes` and `bytearray` | Both raise `TypeError` | Weak-reference-only release tracking cannot attach to these payloads |
| Weak-reference a `memoryview`, then destroy that view | View callback fires while original bytearray is still usable | A view's end is not its backing allocation's end |
| Typed/sliced view | Element count, view byte count and backing byte count differ | Generic `len(view)` and summing views cannot establish allocation size |
| Existing read wrapper on a synthetic bytes result | Returns the same object; tested reference count returns to baseline after caller release | Positive control for this wrapper's lack of extra retained payload; not a full upload on/off audit |
| Real `UploadFile` with memory and rolled-to-disk spools | Both return the entire requested payload; closing spool leaves caller result usable | Disk spool does not make the handler's unsized read memory-free |
| Real multipart parser before the explicit handler read | Parser has populated the file while read counter remains zero | Existing read-result counter does not cover parser allocation/lifetime |
| Two overlapping tasks with separately created observations | Totals stay 4096 and 8192 independently | Explicit context separation works for these wrapper calls |
| Child task / shallow copied context | Both see the same mutable observation/value | Context copying is not an independent memory ledger |
| `asyncio.to_thread` versus an ordinary new thread | First inherits observation; second sees default `None` | Propagation must be proved for the actual worker mechanism |
| A synthetic child read straddles finalization | Returns 4096 bytes but finalized observer records zero additional bytes | Suppression of late writes is not proof of complete in-window accounting |
| Failed/cancelled read and no-context read | Original exceptions/results preserved; no false successful read counts | Narrow failure/no-context positive controls, not durable terminal validation |

The spool tests deliberately override the threshold to **1024 bytes** and exercise
512-byte and 8192-byte payloads. This is a local test setting, not a reported HF
threshold or a proposal to change application spooling. The late-read case creates
a synthetic concurrent child; it does not claim the current canonical handler
actually dispatches parallel reads or has a measured cutoff bug.

Python documents that not all objects support weak references and that copied
contexts are shallow. The concrete payload/type results above are from the script,
not inferred from a generic API description. [Weak references](https://docs.python.org/3.11/library/weakref.html),
[Context variables](https://docs.python.org/3.11/library/contextvars.html),
[Memoryview byte counts](https://docs.python.org/3.11/library/stdtypes.html#memoryview.nbytes).

## 4. Review outcome and retained limits

Local probe assertions pass; **upload-memory acceptance does not** follow. The
review found no production code change, installer invocation, collector promotion,
private fixture identity, or external data mutation in the probe. All document
buffer copies in the script are explicitly synthetic test inputs or ordinary
framework reads; they are not a proposed runtime observation strategy.

Not covered: full parser transient memory, local/S3 SDK internals, PDF native
allocation, database-client memory, synchronization of a future shared ledger,
ledger overflow/underflow, actual allocation release callbacks, persistence
rollback, source/run association admission, disabled-runtime startup composition,
crash recovery and complete upload on/off comparison. Those remain separate
implementation gates. No full-memory ledger was built and no passing arithmetic
example is presented as proof of a deployable method.

Retain earlier small/medium acceptance on its original SHA. Review this negative
feasibility finding before proposing a producer; do not repeat a fixture or rename
read/RSS evidence to make the missing required row disappear.
