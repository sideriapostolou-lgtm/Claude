"""Live display mirrors preserve checkpoint bytes and ledger recovery boundaries."""
from __future__ import annotations

import io
import json
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any, Self

import pytest

from nightcrawler.clock import FakeClock
from nightcrawler.config import Settings
from nightcrawler.speeddesk_live import (
    ARCHIVE_KEY,
    MIRROR_EVERY_S,
    STATE_KEY,
    KalshiLiveDesk,
    LiveSnapshot,
)
from nightcrawler.speeddesk_live_model import WINDOW_PARTS
from nightcrawler.speeddesk_model import Window

ACTIVE = "KXBTC15M-MIRROR-ACTIVE"
ARCHIVED = "KXBTC15M-MIRROR-ARCHIVED"


@pytest.fixture
def desk(tmp_path: Path) -> Iterator[tuple[KalshiLiveDesk, FakeClock]]:
    clock = FakeClock()
    def no_client() -> Any:
        pytest.fail("An offline mirror checkpoint attempted account access")
    live = KalshiLiveDesk(Settings(data_dir=tmp_path), tmp_path / "live", LiveSnapshot,
                          clock=clock.now, client_factory=no_client)
    live.book.add_window(Window(ACTIVE, clock.now(), clock.now() + 900, 80_000., venue="kalshi"))
    live.book.add_window(Window(ARCHIVED, clock.now() - 7200, clock.now() - 6300, 80_000., venue="kalshi"))
    clock.sleep(MIRROR_EVERY_S + 1)
    try:
        yield live, clock
    finally:
        live.close()


class ObservedStream:
    def __init__(self, stream: Any, writes: list[str], fail: bool = False) -> None:
        self.stream, self.writes, self.fail = stream, writes, fail

    def __enter__(self) -> Self:
        self.stream.__enter__()
        return self

    def __exit__(self, *args: object) -> Any:
        return self.stream.__exit__(*args)

    def write(self, text: str) -> int:
        self.writes.append(text)
        if self.fail:
            self.stream.write(text[:17])
            raise OSError("injected failure after partial mirror write")
        return self.stream.write(text)


def observe_writes(monkeypatch: Any, live: KalshiLiveDesk, *, fail: bool = False) -> list[str]:
    writes: list[str] = []
    original = Path.open
    def opening(path: Path, *args: Any, **kwargs: Any) -> Any:
        stream = original(path, *args, **kwargs)
        if path == live.path.with_suffix(".tmp") and args and args[0] == "w":
            return ObservedStream(stream, writes, fail)
        return stream
    monkeypatch.setattr(Path, "open", opening)
    return writes


def depth(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + max((depth(item) for item in value.values()), default=0)
    if isinstance(value, (list, tuple)):
        return 1 + max((depth(item) for item in value), default=0)
    return 0


def test_actual_checkpoint_one_write_matches_old_bytes_and_retains_archive_and_panel(
    desk: tuple[KalshiLiveDesk, FakeClock], monkeypatch: Any,
) -> None:
    live, clock = desk
    live.latest_events.append({"kind": "synthetic", "text": "é🚀\ud800", "numbers": [-0.0, 5e-324, 1e100]})
    last_mirror = live.last_mirror
    writes = observe_writes(monkeypatch, live)
    old_dumps = json.dumps
    full_values: list[dict[str, Any]] = []
    def capture(value: Any, *args: Any, **kwargs: Any) -> str:
        if isinstance(value, dict) and "book" in value and "panel" in value:
            full_values.append(deepcopy(value))
        return old_dumps(value, *args, **kwargs)
    monkeypatch.setattr(json, "dumps", capture)
    import nightcrawler.speeddesk_live as module
    original_replace = module.os.replace
    replaced: list[bool] = []
    def replace(source: Any, target: Any) -> None:
        assert source == live.path.with_suffix(".tmp") and target == live.path
        assert live.last_mirror == last_mirror
        assert live.ledger.get_kv(STATE_KEY)["updated_at"] == clock.now()
        assert len(writes) == 1
        original_replace(source, target)
        replaced.append(True)
    monkeypatch.setattr(module.os, "replace", replace)
    live.checkpoint()
    assert replaced == [True]
    assert live.last_mirror == clock.now()
    assert len(full_values) == len(writes) == 1
    expected = io.StringIO()
    json.dump(full_values[0], expected, allow_nan=False, separators=(",", ":"))
    assert live.path.read_bytes() == expected.getvalue().encode("utf-8")
    full = json.loads(live.path.read_text())
    saved = live.ledger.get_kv(STATE_KEY)
    assert "panel" not in saved
    assert full["panel"]["mode"] == "paper"
    assert set(full["book"]["windows"]) == {ACTIVE, ARCHIVED}
    assert set(saved["book"]["windows"]) == {ACTIVE}
    archive = live.ledger.get_kv(f"{ARCHIVE_KEY}0")
    assert set(archive["book"]["windows"]) == {ARCHIVED}
    for part in WINDOW_PARTS:
        assert full["book"][part] == {**archive["book"][part], **saved["book"][part]}
    assert live.ledger.verify_chain() == (True, None)
    # Actual supported model state is shallow. This isn't a claim that the two
    # encoders share arbitrary malformed/deep-container recursion thresholds.
    assert depth(full_values[0]) < 32


@pytest.mark.parametrize("failure", ["nan", "inf", "unsupported", "partial_write", "replace"])
def test_mirror_failure_preserves_prior_display_timestamp_and_committed_ledger(
    desk: tuple[KalshiLiveDesk, FakeClock], monkeypatch: Any, failure: str,
) -> None:
    live, clock = desk
    previous = live.path.read_bytes()
    previous_at = live.last_mirror
    original_panel = live.panel
    import nightcrawler.speeddesk_live as module
    original_replace = module.os.replace
    replaces: list[bool] = []
    def replace(source: Any, target: Any) -> None:
        replaces.append(True)
        if failure == "replace":
            raise OSError("injected atomic replacement failure")
        original_replace(source, target)
    monkeypatch.setattr(module.os, "replace", replace)
    writes = observe_writes(monkeypatch, live, fail=failure == "partial_write")
    if failure in {"nan", "inf", "unsupported"}:
        bad = {"nan": float("nan"), "inf": float("inf"), "unsupported": object()}[failure]
        monkeypatch.setattr(live, "panel", lambda: {**original_panel(), "invalid_display_only": bad})
    expected_error = TypeError if failure == "unsupported" else (ValueError if failure in {"nan", "inf"} else OSError)
    with pytest.raises(expected_error):
        live.checkpoint()
    assert live.path.read_bytes() == previous
    assert live.last_mirror == previous_at
    assert replaces == ([True] if failure == "replace" else [])
    assert len(writes) == (1 if failure in {"partial_write", "replace"} else 0)
    saved = live.ledger.get_kv(STATE_KEY)
    assert saved["updated_at"] == clock.now()
    assert set(saved["book"]["windows"]) == {ACTIVE}
    assert saved["archived_windows"] == [ARCHIVED]
    assert live.ledger.get_kv(f"{ARCHIVE_KEY}0")["windows"] == [ARCHIVED]
    assert live.ledger.verify_chain() == (True, None)
    assert "invalid_display_only" not in saved


def test_restart_recovers_committed_ledger_instead_of_stale_display(
    desk: tuple[KalshiLiveDesk, FakeClock], monkeypatch: Any,
) -> None:
    live, clock = desk
    import nightcrawler.speeddesk_live as module
    def fail_replace(*args: Any) -> None:
        raise OSError("injected mirror failure")
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "replace", fail_replace)
        with pytest.raises(OSError):
            live.checkpoint()
    assert ACTIVE not in json.loads(live.path.read_text())["book"]["windows"]
    directory, settings = live.directory, live.settings
    live.close()
    # Even a malformed display cannot replace the authoritative ledger state.
    live.path.write_text("not-json-display")
    restored = KalshiLiveDesk(settings, directory, LiveSnapshot, clock=clock.now,
                              client_factory=lambda: pytest.fail("Recovery attempted account access"))
    try:
        assert set(restored.book.windows) == {ACTIVE, ARCHIVED}
        assert restored.archive_chunks == 1
        assert restored.book.realized_pnl == 0
        assert restored.ledger.verify_chain() == (True, None)
        assert restored.client is None
    finally:
        restored.close()
