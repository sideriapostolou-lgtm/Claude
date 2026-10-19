"""Independent adversarial metadata fixtures; synthetic temporary paths only."""

import errno
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).with_name("inventory_metadata.py")
spec = importlib.util.spec_from_file_location("inventory_metadata_independent", SOURCE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    mi = tmp_path / "mounts"
    mi.write_text(f"1 0 {device(root)} / / rw - ext4 none rw\n")
    monkeypatch.setattr(m, "MOUNTINFO", str(mi))
    return root, mi


def device(root):
    info = root.stat()
    return f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}"


def inspect(root, **kwargs):
    return m.inventory(str(root), m.Limits(**kwargs))


def test_raw_nonutf8_name_and_no_secret_bytes(fixture):
    root, _ = fixture
    p = os.fsencode(root) + b"/\xffsecretname"
    fd = os.open(p, os.O_CREAT | os.O_WRONLY, 0o600)
    os.write(fd, b"SECRET-CONTENTS")
    os.close(fd)
    r = inspect(root)
    encoded = json.dumps(r, ensure_ascii=True)
    assert "SECRET-CONTENTS" not in encoded
    assert r["counts"]["unique_regular_files"] == 1
    assert json.loads(encoded)["largest"][0]["path"] == os.fsdecode(b"\xffsecretname")


def test_component_boundary_mount_not_false_positive(fixture):
    root, mi = fixture
    (root / "a").mkdir()
    (root / "a" / "present").touch()
    mi.write_text(
        f"1 0 {device(root)} / / rw - ext4 none rw\n2 1 {device(root)} / {root}notourroot/a rw - ext4 none rw\n"
    )
    r = inspect(root)
    assert r["mount_snapshot"]["nested_boundaries"] == 0
    assert r["counts"]["unique_regular_files"] == 1


def test_nested_mount_file_not_opened_or_counted(fixture):
    root, mi = fixture
    (root / "mounted-file").write_bytes(b"metadata only")
    mi.write_text(
        f"1 0 {device(root)} / / rw - ext4 none rw\n2 1 {device(root)} / {root}/mounted-file rw - ext4 none rw\n"
    )
    r = inspect(root)
    assert r["skips"]["mount_boundary"] == 1
    assert r["counts"]["regular_paths"] == 0


def test_mountinfo_interrupted_read_refuses_without_scan(fixture, monkeypatch):
    root, _ = fixture
    (root / "unseen").touch()
    orig = os.read
    calls = 0

    def interrupted(fd, size):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError(errno.EIO, "DO-NOT-EMIT")
        return orig(fd, 8)

    monkeypatch.setattr(os, "read", interrupted)
    r = inspect(root)
    assert r["stop_reason"] == "refused"
    assert r["counts"]["entries"] == 0
    assert "DO-NOT-EMIT" not in json.dumps(r)


@pytest.mark.parametrize("root_swap", [True, False])
def test_directory_swapped_to_symlink_not_opened(fixture, monkeypatch, root_swap):
    root, _ = fixture
    child = root if root_swap else root / "child"
    if not root_swap:
        child.mkdir()
    outside = root.parent / "outside"
    outside.mkdir()
    (outside / "forbidden").touch()
    original = os.open
    target = child.name
    changed = False

    def swap(path, flags, *a, **k):
        nonlocal changed
        if path == target and not changed:
            changed = True
            child.rename(child.with_name(child.name + "-old"))
            child.symlink_to(outside, target_is_directory=True)
        return original(path, flags, *a, **k)

    monkeypatch.setattr(os, "open", swap)
    r = inspect(root)
    assert changed
    assert r["counts"]["unique_regular_files"] == 0
    assert r["partial"]
    assert r["errors"]
    if root_swap:
        assert r["filesystem"] is None


def test_hardlinks_across_groups_first_observed_only(fixture):
    root, _ = fixture
    (root / "a").mkdir()
    (root / "b").mkdir()
    (root / "a" / "x").write_bytes(b"x" * 5500)
    os.link(root / "a" / "x", root / "b" / "y")
    r = inspect(root)
    assert r["counts"]["regular_paths"] == 2
    assert r["counts"]["unique_regular_files"] == 1
    assert sum(g["files"] for g in r["groups"]) == 1
    assert sum(g["apparent_bytes"] for g in r["groups"]) == 5500
    assert r["skips"]["hardlink_alias"] == 1
    assert len(r["groups"]) == 1
    assert "first_observed_path" in r["hardlink_semantics"]


def test_error_rows_exhaust_shared_budget(fixture, monkeypatch):
    root, _ = fixture
    for i in range(6):
        (root / f"bad{i}").touch()
    orig = os.stat

    def fail(path, *a, **k):
        if isinstance(path, str) and path.startswith("bad"):
            raise OSError(errno.EACCES, "HIDDEN")
        return orig(path, *a, **k)

    monkeypatch.setattr(os, "stat", fail)
    r = inspect(root, max_result_rows=2, max_errors=5)
    assert len(r["errors"]) == 2
    assert r["stop_reason"] == "result_row_limit"
    assert r["counts"]["entries"] == 3
    assert r["partial"]


def test_deep_long_unicode_paths_bounded_by_rows(fixture):
    root, _ = fixture
    p = root
    for i in range(5):
        p = p / ("é" * 100)
        p.mkdir()
    for i in range(12):
        (p / (str(i) + "é" * 100)).touch()
    r = inspect(root, max_result_rows=5)
    assert r["counts"]["result_rows"] == 5
    assert sum(len(r[k]) for k in ["groups", "largest", "samples", "errors"]) == 5
    assert r["stop_reason"] == "result_row_limit"
    assert len(json.dumps(r, ensure_ascii=True).encode()) < 40000


def test_mountinfo_symlink_fails_before_any_directory_iteration(fixture, monkeypatch):
    root, mi = fixture
    actual = mi.with_suffix(".real")
    mi.rename(actual)
    mi.symlink_to(actual)
    monkeypatch.setattr(
        os, "scandir", lambda fd: pytest.fail("no scan after mount refusal")
    )
    r = inspect(root)
    assert r["stop_reason"] == "refused"
    assert r["counts"]["entries"] == 0


@pytest.mark.parametrize("stage", ["root_scandir", "child_scandir", "mount_read"])
def test_file_descriptors_closed_on_failure(fixture, monkeypatch, stage):
    root, _mi = fixture
    (root / "child").mkdir()
    before = set(os.listdir("/proc/self/fd"))
    origscan = os.scandir
    origread = os.read
    calls = 0

    def scan(fd):
        nonlocal calls
        calls += 1
        if (stage == "root_scandir" and calls == 1) or (
            stage == "child_scandir" and calls == 2
        ):
            raise OSError(errno.EIO, "hidden")
        return origscan(fd)

    def read(fd, n):
        if stage == "mount_read":
            raise OSError(errno.EIO, "hidden")
        return origread(fd, n)

    monkeypatch.setattr(os, "scandir", scan)
    monkeypatch.setattr(os, "read", read)
    r = inspect(root)
    assert r["partial"]
    assert before == set(os.listdir("/proc/self/fd"))


def test_parent_mount_only_exact_gate(fixture, monkeypatch):
    root, _ = fixture
    (root / "seen").touch()
    assert (
        m.inventory(str(root), require_exact_mount=False)["counts"][
            "unique_regular_files"
        ]
        == 1
    )
    monkeypatch.setattr(
        os, "scandir", lambda fd: pytest.fail("no scan after exact-mount refusal")
    )
    r = m.inventory(str(root), require_exact_mount=True)
    assert r["stop_reason"] == "refused"
    assert r["counts"]["entries"] == 0
    assert not r["mount_snapshot"]["containing_mount"]["exact_root_mount"]


def test_exact_root_matching_device_and_no_mount_secrets(fixture):
    root, mi = fixture
    (root / "seen").touch()
    mi.write_text(
        f"1 0 {device(root)} / / rw - ext4 HIDDEN_SOURCE HIDDEN_OPTIONS\n2 1 {device(root)} / {root} HIDDEN_OPTIONS - ext4 HIDDEN_SOURCE HIDDEN_OPTIONS\n"
    )
    r = m.inventory(str(root), require_exact_mount=True)
    assert r["counts"]["unique_regular_files"] == 1
    assert r["mount_snapshot"]["containing_mount"]["mount_id"] == 2
    assert "HIDDEN" not in json.dumps(r)


def test_ambiguous_stacked_exact_mount_refuses(fixture, monkeypatch):
    root, mi = fixture
    mi.write_text(
        f"1 0 {device(root)} / / rw - ext4 none rw\n2 1 {device(root)} / {root} rw - ext4 none rw\n3 2 {device(root)} / {root} rw - ext4 none rw\n"
    )
    monkeypatch.setattr(
        os,
        "scandir",
        lambda fd: pytest.fail("ambiguous root mount must refuse before scan"),
    )
    r = m.inventory(str(root), require_exact_mount=True)
    assert r["stop_reason"] == "refused"
    assert r["counts"]["entries"] == 0
