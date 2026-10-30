"""Bounded Linux metadata inventory; CLI is fixed to /data and prints JSON only.

Never opens data-file contents. Only directory descriptors and the fixed procfs
mount table are opened. The deadline is cooperative: a blocked kernel operation
can overrun it. Mount exclusions use a bounded snapshot, not a namespace lock.
No result certifies the whole volume, financial state, or restart safety.
"""

from __future__ import annotations

import heapq
import json
import math
import os
import re
import stat
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

MOUNTINFO = "/proc/self/mountinfo"
SAMPLE_PATHS = (
    "polydesk/state.json",
    "speeddesk/kalshi_live/state.json",
    "speeddesk/kalshi_live/receipts.db",
    "speeddesk/kalshi_live/receipts.db-wal",
    "speeddesk/kalshi_live/receipts.db-shm",
    "nightcrawler.db",
)


@dataclass(frozen=True)
class Limits:
    max_entries: int = 4_000
    max_directories: int = 256  # Includes the inventory root.
    max_depth: int = 8  # Root entries have depth 1.
    max_errors: int = 20
    max_result_rows: int = 256  # Groups + largest + samples + error rows.
    max_mountinfo_bytes: int = 1_048_576
    max_seconds: float = 5.0

    def __post_init__(self) -> None:
        for key, value in asdict(self).items():
            if key == "max_seconds":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{key} must be finite and positive")
                if not math.isfinite(value) or value <= 0:
                    raise ValueError(f"{key} must be finite and positive")
            elif isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{key} must be a positive integer")


class InventoryRefused(Exception):
    """Sanitized fail-closed refusal (never includes file contents)."""


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _same_directory(before: os.stat_result, after: os.stat_result) -> bool:
    return stat.S_ISDIR(after.st_mode) and _identity(before) == _identity(after)


def _open_root(root: str, check: Callable[[], None]) -> int:
    """Reject symlinks in every component and check lstat/open identities."""
    if not isinstance(root, str) or not root.startswith("/") or len(root) > 4096:
        raise InventoryRefused("root must be a bounded absolute directory path")
    parts = root.split("/")[1:]
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise InventoryRefused("root must use canonical nonempty path components")
    check()
    original = os.lstat(root)
    if not stat.S_ISDIR(original.st_mode):
        raise InventoryRefused("root is not a real directory")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    try:
        for part in parts:
            check()
            before = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode):
                raise InventoryRefused("root component is not a real directory")
            opened = os.open(part, flags, dir_fd=descriptor)
            try:
                if not _same_directory(before, os.fstat(opened)):
                    raise InventoryRefused("root component changed during open")
                after = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                if not _same_directory(before, after):
                    raise InventoryRefused("root component replaced during open")
            except BaseException:
                os.close(opened)
                raise
            os.close(descriptor)
            descriptor = opened
        if not _same_directory(original, os.fstat(descriptor)):
            raise InventoryRefused("root changed during open")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _mount_path(encoded: str) -> str:
    # Kernel mountinfo escapes space, tab, newline and backslash as octal.
    if re.search(r"\\(?![0-7]{3})", encoded):
        raise InventoryRefused("mount metadata contains an invalid escape")
    decoded = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), encoded)
    if not decoded.startswith("/") or "\x00" in decoded:
        raise InventoryRefused("mount metadata contains an invalid path")
    if decoded != "/" and any(part in ("", ".", "..") for part in decoded[1:].split("/")):
        raise InventoryRefused("mount metadata contains a noncanonical path")
    return decoded


def _mount_boundaries(root: str, limit: int, check: Callable[[], None]) -> tuple[set[str], int, dict | None]:
    """Fail closed on unavailable, over-limit, empty or malformed mountinfo."""
    check()
    descriptor = os.open(MOUNTINFO, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        chunks = bytearray()
        while len(chunks) <= limit:
            check()
            block = os.read(descriptor, min(65_536, limit + 1 - len(chunks)))
            if not block:
                break
            chunks.extend(block)
        if len(chunks) > limit:
            raise InventoryRefused("mount metadata exceeds byte limit")
    finally:
        os.close(descriptor)
    if not chunks or not chunks.endswith(b"\n"):
        raise InventoryRefused("mount metadata is empty or incomplete")
    boundaries: set[str] = set()
    count = 0
    containing = None
    containing_count = 0
    # fsdecode preserves unusual Linux filename bytes for comparison.
    for line in os.fsdecode(bytes(chunks)).splitlines():
        check()
        fields = line.split()
        if fields.count("-") != 1:
            raise InventoryRefused("mount metadata is malformed")
        separator = fields.index("-")
        if (separator < 6 or len(fields) != separator + 4
                or not re.fullmatch(r"[0-9]{1,20}", fields[0])
                or not re.fullmatch(r"[0-9]{1,20}", fields[1])
                or not re.fullmatch(r"[0-9]{1,20}:[0-9]{1,20}", fields[2])):
            raise InventoryRefused("mount metadata is malformed")
        _mount_path(fields[3])
        mount = _mount_path(fields[4])
        count += 1
        if mount.startswith(root + "/"):
            boundaries.add(mount[len(root) + 1:])
        if mount == "/" or root == mount or root.startswith(mount + "/"):
            if containing is None or len(mount) > len(containing["mount_point"]):
                containing = {"mount_id": int(fields[0]), "parent_id": int(fields[1]),
                              "device_major_minor": fields[2], "mount_point": mount}
                containing_count = 1
            elif len(mount) == len(containing["mount_point"]):
                containing_count += 1
    if containing_count > 1:
        raise InventoryRefused("longest containing mount point has ambiguous records")
    return boundaries, count, containing


class _Stop(Exception):
    pass


def inventory(root: str = "/data", limits: Limits | None = None, *,
              monotonic: Callable[[], float] = time.monotonic,
              require_exact_mount: bool = False) -> dict:
    """Inspect metadata only. Alternate absolute roots are for offline fixtures.

    All path counts are observed entries; root is excluded from entry count and
    included in directory count. Regular-file totals deduplicate (device,inode).
    Samples are collected during bounded traversal; absence means not observed,
    never proof that a financial file does not exist. Names/metadata may still be
    private: review any output before sharing it.
    """
    limits = limits or Limits()
    started = monotonic()
    result = {
        "schema_version": 1,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "ended_at_utc": None,
        "scope": "metadata_only_no_file_contents",
        "root": {"path": root, "device": None, "inode": None},
        "require_exact_mount": require_exact_mount,
        "limits": asdict(limits),
        "filesystem": None,
        "mount_snapshot": {"records": None, "nested_boundaries": None, "containing_mount": None},
        "counts": {"entries": 0, "directories": 0, "regular_paths": 0,
                   "unique_regular_files": 0, "result_rows": 0},
        "groups": [], "largest": [], "samples": [], "errors": [],
        "sample_targets": list(SAMPLE_PATHS),
        "sample_absence_means": "not_observed_in_bounded_traversal",
        "skips": {key: 0 for key in ("symlink", "mount_boundary", "cross_device",
                                     "depth", "special", "hardlink_alias")},
        "stop_reason": None, "partial": False,
        "aggregate_semantics": "observed_unique_regular_file_sums_not_atomic_or_disk_totals",
        "hardlink_semantics": "first_observed_path_gets_inode_totals_other_aliases_are_skipped",
        "observation_semantics": "concurrent_changes_possible_not_a_consistent_filesystem_snapshot",
        "largest_semantics": "up_to_20_unique_regular_files_by_observed_allocated_bytes",
        "deadline_semantics": "cooperative_not_a_hard_timeout",
        "mount_semantics": "snapshot_no_namespace_immutability_or_Railway_volume_identity_certificate",
    }
    groups: dict[str, dict] = {}
    largest: list[tuple[int, int, str, dict]] = []
    seen: set[tuple[int, int]] = set()
    frames: list[tuple[int, object, str, int]] = []
    root_fd = None

    def check() -> None:
        if monotonic() - started >= limits.max_seconds:
            result["stop_reason"] = "elapsed_budget"
            raise _Stop

    def row() -> None:
        if result["counts"]["result_rows"] >= limits.max_result_rows:
            result["stop_reason"] = "result_row_limit"
            raise _Stop
        result["counts"]["result_rows"] += 1

    def error(operation: str, path: str, exc: Exception) -> None:
        row()
        result["errors"].append({"operation": operation, "path": path,
                                 "type": type(exc).__name__, "errno": getattr(exc, "errno", None)})
        if len(result["errors"]) >= limits.max_errors:
            result["stop_reason"] = "error_limit"
            raise _Stop

    def skipped(kind: str) -> None:
        result["skips"][kind] += 1

    try:
        root_fd = _open_root(root, check)
        root_stat = os.fstat(root_fd)
        result["root"].update(device=root_stat.st_dev, inode=root_stat.st_ino)
        check()
        vfs = os.fstatvfs(root_fd)
        result["filesystem"] = {
            "total_bytes": vfs.f_blocks * vfs.f_frsize,
            "free_bytes": vfs.f_bfree * vfs.f_frsize,
            "available_bytes": vfs.f_bavail * vfs.f_frsize,
            "inodes": vfs.f_files, "free_inodes": vfs.f_ffree,
            "available_inodes": vfs.f_favail,
        }
        boundaries, mount_count, containing = _mount_boundaries(root, limits.max_mountinfo_bytes, check)
        result["mount_snapshot"] = {"records": mount_count, "nested_boundaries": len(boundaries),
                                    "containing_mount": containing}
        if containing is None:
            raise InventoryRefused("no containing mount was identified")
        containing["exact_root_mount"] = containing["mount_point"] == root
        mount_device = tuple(int(part) for part in containing["device_major_minor"].split(":"))
        containing["device_matches_root"] = mount_device == (os.major(root_stat.st_dev), os.minor(root_stat.st_dev))
        if not containing["device_matches_root"]:
            raise InventoryRefused("containing mount device does not match root descriptor")
        if require_exact_mount and not containing["exact_root_mount"]:
            raise InventoryRefused("root is not an exact mount point")
        result["counts"]["directories"] = 1
        frames.append((root_fd, os.scandir(root_fd), "", 0))
        root_fd = None  # Frame now owns this descriptor.
        while frames:
            check()
            descriptor, iterator, relative, depth = frames[-1]
            # Check before next(): even enumeration of a directory-only tree is bounded.
            if result["counts"]["entries"] >= limits.max_entries:
                result["stop_reason"] = "entry_limit"
                raise _Stop
            try:
                entry = next(iterator)
            except StopIteration:
                iterator.close()
                os.close(descriptor)
                frames.pop()
                continue
            except OSError as exc:
                error("scandir_next", relative, exc)
                iterator.close()
                os.close(descriptor)
                frames.pop()
                continue
            result["counts"]["entries"] += 1
            path = relative + "/" + entry.name if relative else entry.name
            check()
            if path in boundaries:
                skipped("mount_boundary")
                continue
            try:
                info = os.stat(entry.name, dir_fd=descriptor, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    skipped("symlink")
                    continue
                if info.st_dev != root_stat.st_dev:
                    skipped("cross_device")
                    continue
                if stat.S_ISDIR(info.st_mode):
                    if depth + 1 >= limits.max_depth:
                        skipped("depth")
                        continue
                    if result["counts"]["directories"] >= limits.max_directories:
                        result["stop_reason"] = "directory_limit"
                        raise _Stop
                    check()
                    opened = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                                     | os.O_CLOEXEC, dir_fd=descriptor)
                    try:
                        if not _same_directory(info, os.fstat(opened)):
                            raise InventoryRefused("directory changed during open")
                        after = os.stat(entry.name, dir_fd=descriptor, follow_symlinks=False)
                        if not _same_directory(info, after):
                            raise InventoryRefused("directory replaced during open")
                        check()
                        child_iterator = os.scandir(opened)
                    except BaseException:
                        os.close(opened)
                        raise
                    result["counts"]["directories"] += 1
                    frames.append((opened, child_iterator, path, depth + 1))
                elif stat.S_ISREG(info.st_mode):
                    result["counts"]["regular_paths"] += 1
                    metadata = {"path": path, "device": info.st_dev, "inode": info.st_ino,
                                "apparent_bytes": info.st_size, "allocated_bytes": info.st_blocks * 512,
                                "modified_at_unix_ns": info.st_mtime_ns, "links": info.st_nlink}
                    if path in SAMPLE_PATHS:
                        row()
                        result["samples"].append(metadata)
                    identity = _identity(info)
                    if identity in seen:
                        skipped("hardlink_alias")
                        continue
                    seen.add(identity)
                    result["counts"]["unique_regular_files"] += 1
                    group = path.split("/", 1)[0]
                    if group not in groups:
                        row()
                        groups[group] = {"path": group, "files": 0,
                                         "apparent_bytes": 0, "allocated_bytes": 0}
                    totals = groups[group]
                    totals["files"] += 1
                    totals["apparent_bytes"] += metadata["apparent_bytes"]
                    totals["allocated_bytes"] += metadata["allocated_bytes"]
                    item = (metadata["allocated_bytes"], metadata["apparent_bytes"], path, metadata)
                    if len(largest) < 20:
                        row()
                        heapq.heappush(largest, item)
                    elif item[:3] > largest[0][:3]:
                        heapq.heapreplace(largest, item)
                else:
                    skipped("special")
            except (OSError, InventoryRefused) as exc:
                error("entry_metadata_or_directory_open", path, exc)
    except _Stop:
        pass
    except (OSError, InventoryRefused) as exc:
        result["stop_reason"] = "refused"
        try:
            error("root_or_mount_metadata", ".", exc)
        except _Stop:
            pass
    finally:
        for descriptor, iterator, _, _ in reversed(frames):
            iterator.close()
            os.close(descriptor)
        if root_fd is not None:
            os.close(root_fd)
    result["groups"] = sorted(groups.values(), key=lambda item: item["path"])
    result["largest"] = [item[3] for item in sorted(largest, reverse=True)]
    result["partial"] = bool(result["stop_reason"] or result["errors"]
                             or any(value for key, value in result["skips"].items()
                                    if key != "hardlink_alias"))
    result["ended_at_utc"] = datetime.now(UTC).isoformat()
    result["elapsed_seconds"] = max(0.0, monotonic() - started)
    return result


def main() -> None:
    # Deliberately no arbitrary CLI path, credentials, content mode or write option.
    print(json.dumps(inventory(require_exact_mount=True), ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
