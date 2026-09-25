"""Admission/parser controls, not evidence of native CPU ownership or HF access."""
import json
from pathlib import Path

import pytest

from scripts.probes import s0_cpu_isolation_preflight as probe


STAT = "usage_usec 17\nuser_usec 10\nsystem_usec 7\nnr_periods 4\n"


def mount(point, flags="rw", fs_type="cgroup2", super_flags="rw"):
    escaped = str(point).replace(" ", r"\040")
    return f"10 9 0:24 / {escaped} {flags},nosuid - {fs_type} cgroup {super_flags}\n"


@pytest.fixture
def candidate(tmp_path):
    directory = tmp_path / "candidate with space"
    directory.mkdir()
    (directory / "cpu.stat").write_text(STAT)
    (directory / "cgroup.procs").write_text("")
    mounts = tmp_path / "mountinfo"
    mounts.write_text(mount(directory))
    return directory, mounts


def inspect(candidate):
    directory, mounts = candidate
    return probe.inspect(directory, mountinfo_path=mounts, platform="linux")


def test_readonly_view_over_rw_superblock_blocks(candidate, monkeypatch):
    directory, mounts = candidate
    mounts.write_text(mount(directory, "ro"))
    monkeypatch.setattr(probe.os, "access", lambda *args: True)
    report = inspect(candidate)
    assert report["reason"] == "readonly_mount"
    assert report["checks"]["cpu_stat_valid"]
    assert not report["delegation_verified"]


def test_readonly_superblock_blocks(candidate):
    directory, mounts = candidate
    mounts.write_text(mount(directory, super_flags="ro"))
    assert inspect(candidate)["reason"] == "readonly_mount"


def test_writable_hints_never_prove_delegation(candidate, monkeypatch):
    monkeypatch.setattr(probe.os, "access", lambda *args: True)
    report = inspect(candidate)
    assert report["status"] == "needs_active_verification"
    assert not report["delegation_verified"]
    assert not report["cpu_attribution_verified"]


def test_permission_denial_blocks(candidate, monkeypatch):
    monkeypatch.setattr(probe.os, "access", lambda *args: False)
    assert inspect(candidate)["reason"] == "write_access_unavailable"


def test_longest_mount_blocks_overmount(candidate):
    directory, mounts = candidate
    mounts.write_text(mount(directory.parent) + mount(directory, fs_type="tmpfs"))
    assert inspect(candidate)["reason"] == "not_cgroup_v2"


@pytest.mark.parametrize("bad", ["", "malformed\n", "duplicate", "ambiguous"])
def test_bad_or_ambiguous_mounts_block(candidate, bad):
    directory, mounts = candidate
    if bad == "duplicate":
        bad = mount(directory) * 2
    elif bad == "ambiguous":
        bad = mount(directory, "ro,rw")
    mounts.write_text(bad)
    assert inspect(candidate)["reason"] == "mount_uninspectable"


@pytest.mark.parametrize("value", ["-1", "True", "NaN", "1.5", "1e3",
                                   "9" * 5000, str(1 << 64)])
def test_bad_counter_samples_block(value):
    assert not probe.valid_cpu_stat(STAT.replace("usage_usec 17", "usage_usec " + value))


@pytest.mark.parametrize("value", ["", "usage_usec 0\n", STAT + "usage_usec 18\n",
                                   STAT + "unexpected\n"])
def test_missing_or_duplicate_stat_fields_block(value):
    assert not probe.valid_cpu_stat(value)


def test_zero_and_extended_numeric_fields_are_supported():
    assert probe.valid_cpu_stat("usage_usec 0\nuser_usec 0\nsystem_usec 0\nfuture_field 9\n")


@pytest.mark.parametrize("payload", [b"x" * (probe.MAX_FILE_BYTES + 1), b"\xff"])
def test_bounded_and_utf8_stat_reads(candidate, payload):
    (candidate[0] / "cpu.stat").write_bytes(payload)
    assert inspect(candidate)["reason"] == "cpu_stat_uninspectable"


def test_oversized_mountinfo_blocks(candidate):
    candidate[1].write_bytes(b"x" * (probe.MAX_MOUNTINFO_BYTES + 1))
    assert inspect(candidate)["reason"] == "mount_uninspectable"


def test_missing_directory_and_unsupported_platform_are_explicit(tmp_path):
    assert probe.inspect(tmp_path / "missing", platform="linux")["reason"] == "mount_uninspectable"
    assert probe.inspect(tmp_path, platform="win32")["reason"] == "unsupported_platform"


def test_report_does_not_disclose_paths_counters_or_exceptions(candidate):
    directory, _ = candidate
    (directory / "cpu.stat").unlink()
    encoded = json.dumps(inspect(candidate))
    assert str(directory) not in encoded
    assert "usage_usec" not in encoded
    assert "No such file" not in encoded


@pytest.mark.parametrize("status,code", [("blocked", 2), ("needs_active_verification", 3)])
def test_cli_never_exits_success_for_unverified_capability(monkeypatch, capsys, status, code):
    monkeypatch.setattr(probe, "inspect", lambda path: {"status": status})
    assert probe.main([]) == code
    assert json.loads(capsys.readouterr().out) == {"status": status}


def test_inspection_does_not_modify_candidate(candidate):
    directory, _ = candidate
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    inspect(candidate)
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before
