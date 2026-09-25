# S0 CPU isolation preflight — 2026-09-25

Status: **Local capability blocked; experiment authorized, not deployed**.
Parent: [CPU isolation design](../plans/s0-preprocessing-cpu-isolation-decision-2026-09-25.md).
Source baseline: Backend Staging `8110784a5061641fd6229045a6f51b2fb89db7dd`.
User approval: 2026-09-25, 18:43 America/Chicago; experiment only, no deployment.

## Outcome

The current Codex execution container exposes cgroup v2 through a read-only
mount. Its aggregate CPU counters are readable; directory and membership write
permission hints are false. This blocks creating an operation-owned accounting
domain here. No child workload, cgroup mutation, migration, privilege escalation
or mount change was attempted. This result says nothing about HF Staging's
delegation capabilities.

The design's capability gate says to stop this route when delegation is
unavailable. Consequently, native helper accounting, worker IPC, cancellation
and cleanup are **not implemented or validated** by this change. A generic child
process benchmark would not repair this missing accounting boundary.

S0 remains **17/19** and required `preprocessing_cpu_seconds` remains
`not_instrumented`. Container CPU counters are not a per-document measurement.

## Reusable preflight

[s0_cpu_isolation_preflight.py](../../scripts/probes/s0_cpu_isolation_preflight.py)
is stdlib-only and reads existing mount metadata and counter files. It is not
imported by the application and has no workflow/deployment hook.

Run on the intended worker host, from a checkout containing the script:

```bash
python scripts/probes/s0_cpu_isolation_preflight.py
```

The default candidate directory is `/sys/fs/cgroup`. Where the host operator
has already provided a delegated directory, select it explicitly with
`--cgroup-dir /absolute/delegated/directory`. The script does not create one,
change permissions, or automatically locate the calling process's membership.
If the default is unsuitable, a blocked result concerns that directory only.

| Exit / status | Meaning |
|---|---|
| 2 / blocked | Necessary readable/mount/permission conditions are absent or uninspectable. |
| 3 / needs_active_verification | Read-only checks did not find a blocker; creation, membership, cleanup, containment and ownership are still unproved. |

There is deliberately no success exit or `supported` result. Writable access
checks are hints, not proof: cross-directory migration rights, host policy,
permission races and containment still require actual verification on an
authorized runner. The preflight does not enable the CPU controller or require
its quota settings to be changed.

Input reads are bounded (8 KiB counters, 1 MiB mount metadata), duplicate fields
and invalid/oversized numbers are rejected, and the most specific mount is used.
Both per-mount and superblock read-only flags block admission. Unknown numeric
CPU stat fields are accepted for forward compatibility. The JSON report excludes
host paths, PIDs, raw counters, environment contents and exception messages.

## Actual local result

Python 3.12.14, current Codex execution container, 2026-09-25:

```json
{
  "version": "s0_cpu_isolation_preflight_v1",
  "status": "blocked",
  "reason": "readonly_mount",
  "checks": {
    "cgroup_v2_mount": true,
    "mount_readonly": true,
    "cpu_stat_valid": true,
    "directory_write_hint": false,
    "membership_write_hint": false
  },
  "delegation_verified": false,
  "cpu_attribution_verified": false
}
```

The actual CLI returned exit 2. No counter delta was calculated or recorded.

## Tests and limits

[29 tests](../../tests/test_s0_cpu_isolation_preflight.py) passed locally:

```bash
python -m pytest -q tests/test_s0_cpu_isolation_preflight.py
```

Controls cover read-only mount/superblock combinations, non-cgroup overmounts,
escaped mount paths, ambiguous/missing/oversized metadata, permission denial,
malformed/duplicate/oversized counters, zero counters, bounded UTF-8 reads,
unsupported platforms, output privacy, non-success CLI exit codes, and unchanged
test-fixture files after inspection. Filesystem fixtures are parser controls,
not actual delegated cgroups or native ownership evidence. These tests do not
run the application pipeline; no existing CI workflow was expanded to invoke
this new test explicitly. Attached CI results must be tracked separately.

## Next actionable gate

Obtain this preflight's report from the intended worker host without deploying
an application change. If the host offers an authorized delegated subtree, then
verify creation/membership/cleanup there and implement the approved worker
experiment. If the host cannot offer it, retain the gap and evaluate a suitable
isolated runner before making an infrastructure decision. Do not infer HF access
from local or GitHub Actions permissions, and do not rerun private fixtures to
resolve a permission limitation. No renewed experiment approval is needed.

Rollback: remove the standalone script/tests and revert the documentation;
normal Staging processing is unaffected.
