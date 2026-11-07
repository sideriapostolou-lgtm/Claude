"""Offline synthetic fixtures only; never inspect /data or application state."""

import errno
import importlib.util
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location("inventory_metadata", Path(__file__).with_name("inventory_metadata.py"))
inventory_metadata = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = inventory_metadata
SPEC.loader.exec_module(inventory_metadata)
Limits = inventory_metadata.Limits


@pytest.fixture
def volume(tmp_path, monkeypatch):
    root = tmp_path / "volume"
    root.mkdir()
    mountinfo = tmp_path / "mountinfo"
    device = f"{os.major(root.stat().st_dev)}:{os.minor(root.stat().st_dev)}"
    mountinfo.write_text(f"1 0 {device} / / rw - ext4 none rw\n")
    monkeypatch.setattr(inventory_metadata, "MOUNTINFO", str(mountinfo))
    return root, mountinfo


def inspect(root, **limits):
    return inventory_metadata.inventory(str(root), Limits(**limits))


def test_metadata_json_and_financial_samples_without_content_opens(volume, monkeypatch):
    root, mountinfo = volume
    (root / "polydesk").mkdir()
    (root / "polydesk" / "state.json").write_text("not parsed: private fixture")
    (root / "nightcrawler.db").write_bytes(b"not a sqlite database")
    (root / "speeddesk" / "kalshi_live").mkdir(parents=True)
    for name in ("state.json", "receipts.db", "receipts.db-wal", "receipts.db-shm"):
        (root / "speeddesk" / "kalshi_live" / name).touch()
    original = os.open
    calls = []

    def metadata_open(path, flags, *args, **kwargs):
        calls.append((path, flags))
        assert flags & os.O_NOFOLLOW
        assert flags & os.O_ACCMODE == os.O_RDONLY
        assert path == str(mountinfo) or flags & os.O_DIRECTORY
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", metadata_open)
    result = inspect(root)
    assert result["stop_reason"] is None
    assert result["partial"] is False
    assert result["counts"]["entries"] == 9
    assert result["counts"]["directories"] == 4
    assert {row["path"] for row in result["samples"]} == {
        "polydesk/state.json", "nightcrawler.db", "speeddesk/kalshi_live/state.json",
        "speeddesk/kalshi_live/receipts.db", "speeddesk/kalshi_live/receipts.db-wal",
        "speeddesk/kalshi_live/receipts.db-shm",
    }
    assert result["root"]["inode"] == root.stat().st_ino
    assert result["filesystem"]["free_bytes"] >= result["filesystem"]["available_bytes"]
    assert result["started_at_utc"].endswith("+00:00")
    assert result["ended_at_utc"] >= result["started_at_utc"]
    assert calls
    serialized = json.dumps(result)
    assert "private fixture" not in serialized
    assert "not a sqlite" not in serialized
    assert json.loads(serialized)["schema_version"] == 1


@pytest.mark.parametrize("parent", [False, True])
def test_symlink_root_or_parent_is_refused_before_fstatvfs(volume, monkeypatch, parent):
    root, _ = volume
    link = root.parent / "alias"
    link.symlink_to(root, target_is_directory=True)
    if parent:
        (root / "child").mkdir()
        link = link / "child"
    monkeypatch.setattr(os, "fstatvfs", lambda fd: pytest.fail("refused root reached fstatvfs"))
    result = inspect(link)
    assert result["stop_reason"] == "refused"
    assert result["counts"]["entries"] == 0
    assert result["filesystem"] is None


def test_child_symlink_and_special_file_are_not_opened(volume, monkeypatch):
    root, _ = volume
    external = root.parent / "external"
    external.mkdir()
    (external / "unseen").touch()
    (root / "escape").symlink_to(external, target_is_directory=True)
    os.mkfifo(root / "fifo")
    result = inspect(root)
    assert result["skips"]["symlink"] == 1
    assert result["skips"]["special"] == 1
    assert result["counts"]["entries"] == 2
    assert result["counts"]["unique_regular_files"] == 0
    assert result["partial"]


def test_same_device_nested_mount_with_octal_path_is_excluded(volume):
    root, mountinfo = volume
    child = root / "mounted child"
    child.mkdir()
    (child / "unseen").touch()
    escaped = str(child).replace(" ", "\\040")
    device = f"{os.major(root.stat().st_dev)}:{os.minor(root.stat().st_dev)}"
    mountinfo.write_text(f"1 0 {device} / / rw - ext4 none rw\n2 1 {device} / {escaped} rw - ext4 none rw\n")
    result = inspect(root)
    assert result["mount_snapshot"]["records"] == 2
    assert result["mount_snapshot"]["nested_boundaries"] == 1
    assert result["skips"]["mount_boundary"] == 1
    assert result["counts"]["directories"] == 1
    assert result["counts"]["entries"] == 1


def test_containing_mount_summary_selects_longest_parent_without_source_or_options(volume):
    root, mountinfo = volume
    device = f"{os.major(root.stat().st_dev)}:{os.minor(root.stat().st_dev)}"
    mountinfo.write_text(f"1 0 {device} / / rw - ext4 private-source private-options\n"
                        f"2 1 {device} / {root.parent} rw - ext4 private-source private-options\n")
    result = inspect(root)
    assert result["require_exact_mount"] is False
    assert result["mount_snapshot"]["containing_mount"] == {
        "mount_id": 2, "parent_id": 1, "device_major_minor": device,
        "mount_point": str(root.parent), "exact_root_mount": False, "device_matches_root": True,
    }
    assert "private-source" not in json.dumps(result)
    assert "private-options" not in json.dumps(result)


@pytest.mark.parametrize("condition", ["exact", "parent_only", "missing", "mismatch"])
def test_exact_root_mount_gate_before_enumeration(volume, condition):
    root, mountinfo = volume
    (root / "observed_only_if_exact").touch()
    device = f"{os.major(root.stat().st_dev)}:{os.minor(root.stat().st_dev)}"
    mount = root
    if condition == "parent_only":
        mount = root.parent
    elif condition == "missing":
        mount = root.parent / "unrelated"
    elif condition == "mismatch":
        device = f"{os.major(root.stat().st_dev)}:{os.minor(root.stat().st_dev) + 1}"
    mountinfo.write_text(f"3 1 {device} / {mount} rw - ext4 none rw\n")
    result = inventory_metadata.inventory(str(root), require_exact_mount=True)
    assert result["require_exact_mount"] is True
    assert result["filesystem"] is not None  # This alone does not prove the intended volume.
    if condition == "exact":
        assert result["stop_reason"] is None
        assert result["counts"]["entries"] == 1
        assert result["mount_snapshot"]["containing_mount"]["exact_root_mount"] is True
    else:
        assert result["stop_reason"] == "refused"
        assert result["counts"]["entries"] == 0
        assert result["partial"]


@pytest.mark.parametrize("condition", ["same_device_exact", "other_device_exact",
                                       "ambiguous_parent", "unique_deeper_root"])
def test_duplicate_longest_mount_identity_refuses_but_unique_deeper_mount_wins(volume, condition):
    root, mountinfo = volume
    (root / "observed_only_if_unique").touch()
    device = f"{os.major(root.stat().st_dev)}:{os.minor(root.stat().st_dev)}"
    other_device = f"{os.major(root.stat().st_dev)}:{os.minor(root.stat().st_dev) + 1}"
    mount = root.parent if condition in ("ambiguous_parent", "unique_deeper_root") else root
    second_device = other_device if condition == "other_device_exact" else device
    rows = [f"1 0 {device} / {mount} rw - ext4 none rw\n",
            f"2 1 {second_device} / {mount} rw - ext4 none rw\n"]
    if condition == "unique_deeper_root":
        rows.append(f"3 2 {device} / {root} rw - ext4 none rw\n")
    mountinfo.write_text("".join(rows))
    result = inventory_metadata.inventory(str(root), require_exact_mount=condition != "ambiguous_parent")
    if condition == "unique_deeper_root":
        assert result["stop_reason"] is None
        assert result["counts"]["entries"] == 1
        assert result["mount_snapshot"]["containing_mount"]["mount_id"] == 3
    else:
        assert result["stop_reason"] == "refused"
        assert result["counts"]["entries"] == 0


def test_cross_device_entry_is_excluded(volume, monkeypatch):
    root, _ = volume
    (root / "foreign").mkdir()
    original = os.stat

    def different_device(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == "foreign":
            return SimpleNamespace(st_mode=info.st_mode, st_dev=info.st_dev + 1)
        return info

    monkeypatch.setattr(os, "stat", different_device)
    result = inspect(root)
    assert result["skips"]["cross_device"] == 1
    assert result["counts"]["directories"] == 1


@pytest.mark.parametrize("kind", ["files", "directories", "symlinks"])
def test_all_entry_kinds_consume_entry_budget(volume, kind):
    root, _ = volume
    for index in range(9):
        path = root / str(index)
        if kind == "files":
            path.touch()
        elif kind == "directories":
            path.mkdir()
        else:
            path.symlink_to("missing")
    result = inspect(root, max_entries=3)
    assert result["counts"]["entries"] == 3
    assert result["stop_reason"] == "entry_limit"
    assert result["partial"]


def test_directory_and_depth_caps(volume):
    root, _ = volume
    (root / "child" / "grandchild").mkdir(parents=True)
    (root / "child" / "grandchild" / "unseen").touch()
    result = inspect(root, max_directories=1)
    assert result["stop_reason"] == "directory_limit"
    assert result["counts"]["directories"] == 1
    result = inspect(root, max_depth=2)
    assert result["counts"]["directories"] == 2
    assert result["skips"]["depth"] == 1
    assert result["counts"]["unique_regular_files"] == 0
    assert result["partial"]


def test_elapsed_budget_uses_cooperative_clock(volume):
    root, _ = volume
    for index in range(100):
        (root / str(index)).touch()
    ticks = iter(index / 100 for index in range(1000))
    result = inventory_metadata.inventory(str(root), Limits(max_seconds=0.3), monotonic=lambda: next(ticks))
    assert result["stop_reason"] == "elapsed_budget"
    assert result["counts"]["entries"] < 100
    assert result["deadline_semantics"] == "cooperative_not_a_hard_timeout"


def test_error_budget_is_bounded_and_exception_messages_are_not_exposed(volume, monkeypatch):
    root, _ = volume
    for index in range(5):
        (root / f"err{index}").touch()
    original = os.stat

    def denied(path, *args, **kwargs):
        if isinstance(path, str) and path.startswith("err"):
            raise PermissionError(errno.EACCES, "private fixture error message")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", denied)
    result = inspect(root, max_errors=2)
    assert result["stop_reason"] == "error_limit"
    assert len(result["errors"]) == 2
    assert all(row["errno"] == errno.EACCES for row in result["errors"])
    assert "private fixture" not in json.dumps(result)


def test_root_replacement_is_detected_before_fstatvfs(volume, monkeypatch):
    root, _ = volume
    original = os.open
    swapped = False

    def replacing_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == root.name and not swapped:
            root.rename(root.with_name("old_volume"))
            root.mkdir()
            swapped = True
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replacing_open)
    monkeypatch.setattr(os, "fstatvfs", lambda fd: pytest.fail("replaced root reached fstatvfs"))
    result = inspect(root)
    assert swapped
    assert result["stop_reason"] == "refused"


@pytest.mark.parametrize("swap_after_open", [False, True])
def test_child_replacement_during_open_is_not_traversed(volume, monkeypatch, swap_after_open):
    root, _ = volume
    (root / "child").mkdir()
    original = os.open
    swapped = False

    def replace_child():
        (root / "child").rename(root / "old_child")
        (root / "child").mkdir()
        (root / "child" / "unseen").touch()

    def replacing_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "child" and not swapped:
            swapped = True
            if swap_after_open:
                fd = original(path, flags, *args, **kwargs)
                replace_child()
                return fd
            replace_child()
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replacing_open)
    result = inspect(root)
    assert swapped
    assert result["counts"]["directories"] == 1
    assert result["errors"][0]["type"] == "InventoryRefused"
    assert result["counts"]["unique_regular_files"] == 0


def test_hardlinks_do_not_inflate_aggregates(volume):
    root, _ = volume
    (root / "group").mkdir()
    path = root / "group" / "first"
    path.write_bytes(b"12345")
    os.link(path, root / "group" / "alias")
    result = inspect(root)
    assert result["counts"]["regular_paths"] == 2
    assert result["counts"]["unique_regular_files"] == 1
    assert result["skips"]["hardlink_alias"] == 1
    assert result["groups"][0]["apparent_bytes"] == 5
    assert len(result["largest"]) == 1


def test_top20_and_shared_result_row_budget(volume):
    root, _ = volume
    (root / "group").mkdir()
    for index in range(30):
        (root / "group" / str(index)).write_bytes(bytes(index))
    result = inspect(root)
    assert len(result["largest"]) == 20
    assert [row["apparent_bytes"] for row in result["largest"]] == list(range(29, 9, -1))
    bounded = inspect(root, max_result_rows=3)
    assert bounded["stop_reason"] == "result_row_limit"
    assert bounded["counts"]["result_rows"] == 3
    assert sum(len(bounded[key]) for key in ("groups", "largest", "samples", "errors")) == 3


@pytest.mark.parametrize("payload", [b"", b"bad\n", b"1 0 x / / rw - ext4 none rw\n",
                                     b"1 0 0:1 / /bad\\q rw - ext4 none rw\n",
                                     b"1 0 0:1 / / rw - ext4 none rw"])
def test_malformed_mount_metadata_fails_closed(volume, payload):
    root, mountinfo = volume
    (root / "unseen").touch()
    mountinfo.write_bytes(payload)
    result = inspect(root)
    assert result["stop_reason"] == "refused"
    assert result["counts"]["entries"] == 0
    assert result["errors"][0]["type"] == "InventoryRefused"


@pytest.mark.parametrize("condition", ["missing", "oversize", "symlink"])
def test_unavailable_or_oversize_mount_metadata_fails_closed(volume, condition):
    root, mountinfo = volume
    if condition == "missing":
        mountinfo.unlink()
    elif condition == "symlink":
        mountinfo.unlink()
        mountinfo.symlink_to(root / "unseen")
    result = inspect(root, max_mountinfo_bytes=8 if condition == "oversize" else 1024)
    assert result["stop_reason"] == "refused"
    assert result["counts"]["entries"] == 0


@pytest.mark.parametrize("value", [0, -1, True, "5", 1.5])
def test_integer_limits_reject_invalid_values(value):
    for name in Limits.__dataclass_fields__:
        if name != "max_seconds":
            with pytest.raises(ValueError):
                replace(Limits(), **{name: value})


@pytest.mark.parametrize("value", [0, -1, True, "5", float("nan"), float("inf")])
def test_time_limit_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        Limits(max_seconds=value)


def test_cli_calls_only_default_root_and_emits_json(monkeypatch, capsys):
    def default_only(*, require_exact_mount):
        assert require_exact_mount is True
        return {"fixture": True}

    monkeypatch.setattr(inventory_metadata, "inventory", default_only)
    inventory_metadata.main()
    assert json.loads(capsys.readouterr().out) == {"fixture": True}
