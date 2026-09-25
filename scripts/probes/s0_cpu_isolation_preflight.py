"""Read-only cgroup v2 gate; never reports CPU attribution or verified delegation.

Run on the intended worker host. Exit 2 means blocked, 3 means active verification
is still required. No subprocess, cgroup creation, migration, or mount changes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

MAX_FILE_BYTES = 8192
MAX_MOUNTINFO_BYTES = 1024 * 1024
MAX_COUNTER = (1 << 64) - 1


def _read(path: Path, limit: int) -> str:
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError("oversized input")
    return data.decode("utf-8", errors="strict")


def _unescape(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)


def mount_for(directory: Path, mountinfo: str) -> tuple[str, bool]:
    """Use the most specific mount, including non-cgroup overmounts."""
    candidates = []
    for line in mountinfo.splitlines():
        left, separator, right = line.partition(" - ")
        fields, trailing = left.split(), right.split()
        if not separator or len(fields) < 6 or len(trailing) < 3:
            raise ValueError("invalid mountinfo")
        point = Path(_unescape(fields[4]))
        if not point.is_absolute():
            raise ValueError("relative mount")
        flags = set(fields[5].split(","))
        super_flags = set(trailing[2].split(","))
        if (("ro" in flags) == ("rw" in flags)
                or ("ro" in super_flags) == ("rw" in super_flags)):
            raise ValueError("ambiguous mount mode")
        if directory == point or point in directory.parents:
            candidates.append((len(point.parts), trailing[0],
                               "ro" in flags or "ro" in super_flags))
    if not candidates:
        raise ValueError("mount unavailable")
    depth = max(item[0] for item in candidates)
    closest = [item for item in candidates if item[0] == depth]
    if len(closest) != 1:
        raise ValueError("ambiguous mount")
    return closest[0][1:]


def valid_cpu_stat(value: str) -> bool:
    fields = {}
    for line in value.splitlines():
        pair = line.split()
        if len(pair) != 2 or pair[0] in fields:
            return False
        number = pair[1]
        if re.fullmatch(r"[0-9]{1,20}", number) is None:
            return False
        fields[pair[0]] = int(number)
        if fields[pair[0]] > MAX_COUNTER:
            return False
    return all(key in fields for key in ("usage_usec", "user_usec", "system_usec"))


def inspect(directory: Path, *, mountinfo_path: Path = Path("/proc/self/mountinfo"),
            platform: str = sys.platform) -> dict:
    report = {
        "version": "s0_cpu_isolation_preflight_v1",
        "status": "blocked",
        "reason": "unsupported_platform",
        "checks": {},
        "delegation_verified": False,
        "cpu_attribution_verified": False,
    }
    if platform != "linux":
        return report
    try:
        directory = directory.resolve(strict=True)
        if not directory.is_dir():
            raise ValueError("not a directory")
        fs_type, readonly = mount_for(
            directory, _read(mountinfo_path, MAX_MOUNTINFO_BYTES))
    except (OSError, ValueError, RuntimeError):
        report["reason"] = "mount_uninspectable"
        return report
    checks = report["checks"]
    checks["cgroup_v2_mount"] = fs_type == "cgroup2"
    if not checks["cgroup_v2_mount"]:
        report["reason"] = "not_cgroup_v2"
        return report
    checks["mount_readonly"] = readonly
    try:
        checks["cpu_stat_valid"] = valid_cpu_stat(_read(directory / "cpu.stat", MAX_FILE_BYTES))
    except (OSError, ValueError):
        checks["cpu_stat_valid"] = False
    # These are permission hints, never proof of delegation or membership rights.
    checks["directory_write_hint"] = os.access(directory, os.W_OK | os.X_OK)
    checks["membership_write_hint"] = os.access(directory / "cgroup.procs", os.W_OK)
    if readonly:
        report["reason"] = "readonly_mount"
    elif not checks["cpu_stat_valid"]:
        report["reason"] = "cpu_stat_uninspectable"
    elif not (checks["directory_write_hint"] and checks["membership_write_hint"]):
        report["reason"] = "write_access_unavailable"
    else:
        report["status"] = "needs_active_verification"
        report["reason"] = "delegation_and_ownership_unverified"
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cgroup-dir", type=Path, default=Path("/sys/fs/cgroup"),
                        help="Existing candidate delegation directory on this host")
    args = parser.parse_args(argv)
    report = inspect(args.cgroup_dir)
    # No host paths, PIDs, raw counters, environment or exception messages.
    print(json.dumps(report, sort_keys=True))
    return 2 if report["status"] == "blocked" else 3


if __name__ == "__main__":
    raise SystemExit(main())
