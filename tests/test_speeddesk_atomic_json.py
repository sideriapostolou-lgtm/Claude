"""Practice mirrors retain atomic replacement and durability while encoding off the Python iterator path."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Self

import pytest

from nightcrawler import speeddesk


@pytest.mark.parametrize("durable", [False, True])
def test_atomic_practice_mirror_preserves_compact_bytes_and_sync_before_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, durable: bool,
) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"old":true}', encoding="utf-8")
    value = {"mode": "practice", "unicode": "café", "empty": [], "nested": [{"p": .38, "n": None}]}
    expected = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
    sync, rename = os.fsync, os.replace
    calls: list[str] = []

    def synced(fd: int) -> None:
        assert path.read_text() == '{"old":true}'
        assert path.with_suffix(".tmp").read_bytes() == expected  # flush happened before fsync
        calls.append("sync")
        sync(fd)

    def replaced(source: Any, destination: Any) -> None:
        assert path.read_text() == '{"old":true}'
        assert Path(source).read_bytes() == expected
        assert calls == (["sync"] if durable else [])
        calls.append("replace")
        rename(source, destination)

    monkeypatch.setattr(speeddesk.os, "fsync", synced)
    monkeypatch.setattr(speeddesk.os, "replace", replaced)
    speeddesk._atomic_json(path, value, durable=durable)
    assert path.read_bytes() == expected and json.loads(path.read_text()) == value
    assert calls == (["sync", "replace"] if durable else ["replace"])
    assert not path.with_suffix(".tmp").exists()


@pytest.mark.parametrize("failure", ["nan", "unsupported", "write", "sync", "rename"])
def test_failed_practice_mirror_never_replaces_the_previous_committed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    path = tmp_path / "state.json"
    previous = b'{"mode":"practice","old":true}'
    path.write_bytes(previous)
    value: dict[str, Any] = {"new": True}

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("fake disk failure")

    if failure == "nan":
        value["invalid"] = float("nan")
    elif failure == "unsupported":
        value["invalid"] = object()
    elif failure == "write":
        original = Path.open

        class BrokenWriter:
            def __enter__(self) -> Self:
                return self

            def __exit__(self, *_args: object) -> None:
                pass

            def write(self, _text: str) -> None:
                raise OSError("fake short write")

        def opening(target: Path, *args: Any, **kwargs: Any) -> Any:
            return BrokenWriter() if target == path.with_suffix(".tmp") else original(target, *args, **kwargs)

        monkeypatch.setattr(Path, "open", opening)
    elif failure == "sync":
        monkeypatch.setattr(speeddesk.os, "fsync", broken)
    else:
        monkeypatch.setattr(speeddesk.os, "replace", broken)

    with pytest.raises((ValueError, TypeError, OSError)):
        speeddesk._atomic_json(path, value)
    assert path.read_bytes() == previous
