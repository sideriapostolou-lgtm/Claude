"""The practice LIP desk's process (nightcrawler.lip_practice): off by default, no order path and no network at all,
an isolated child with an empty environment, and the files it writes from the recorder's segments."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nightcrawler import lip_practice as P
from nightcrawler.lip_feed import SERIES, write_segment

SRC = Path(__file__).resolve().parents[1] / "src" / "nightcrawler"
ROOT = Path(__file__).resolve().parents[1]
T0 = 1_791_918_900.0  # 2026-10-13 19:15:00 UTC
EUR = "KXEURUSD15M-26OCT131530-30"
YES_BOOK = [["0.41", "30"], ["0.40", "50"], ["0.39", "400"]]
NO_BOOK = [["0.57", "80"], ["0.56", "400"]]


# ---------------------------------------------------------------------- no order path, no network
@pytest.mark.parametrize("path", [SRC / "lip_score.py", SRC / "lip_feed.py", SRC / "lip_desk.py",
                                  SRC / "lip_practice.py", ROOT / "research" / "kalshi_rewards" / "leadlag.py"])
def test_no_order_path_no_client_no_network(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = ("." * node.level) + (node.module or "")
            imported |= {base} | {f"{base}.{alias.name}" for alias in node.names}
    forbidden = ("requests", "urllib", "http", "socket", "ssl", "websockets", "aiohttp", "httpx", "cryptography",
                 "speeddesk", "broker", "polymarket", "polydesk", "kalshi_public", "kalshi_recorder", "marcodesk",
                 "withdraw", "botwallet", "config")
    hits = sorted(name for name in imported if any(word in name.split(".")[-1] or word in name.split(".")[0]
                                                   for word in forbidden))
    assert hits == [], hits
    for needle in ("/portfolio", "create_order", "cancel_order", "amend_order", "KALSHI-ACCESS", "Authorization",
                   "/orders", "batch_create"):
        assert needle not in source, needle


# ---------------------------------------------------------------------- settings and guards
def test_off_by_default_and_a_bad_switch_reads_off() -> None:
    assert P.LipPracticeSettings.from_env({}).enabled is False
    assert P.LipPracticeSettings.from_env({"KALSHI_LIP_PRACTICE_ENABLED": "maybe"}).enabled is False
    on = P.LipPracticeSettings.from_env({"KALSHI_LIP_PRACTICE_ENABLED": "true", "DATA_DIR": "/data"})
    assert on.enabled and on.data_dir == Path("/data") and on.recorder_dir == Path("/data/kalshi_recorder")
    assert on.directory == Path("/data/kalshi_lip_practice")
    custom = P.LipPracticeSettings.from_env({"KALSHI_LIP_PRACTICE_RECORDER_DIR": "/rec"})
    assert custom.recorder_dir == Path("/rec")


def test_trading_keys_and_live_switches_are_named_never_read() -> None:
    env = {"KALSHI_KEY_ID": "x", "POLYMARKET_US_SECRET": "y", "SPEEDDESK_KALSHI_MODE": "live",
           "POLYDESK_MODE": "paper", "PYTH_API_KEY": "z", "DATA_DIR": "/data"}
    assert P.unsafe_names(env) == ["KALSHI_KEY_ID", "POLYMARKET_US_SECRET", "SPEEDDESK_KALSHI_MODE"]
    assert P.unsafe_names({"PYTH_API_KEY": "z"}) == []  # a read-only price key is not a trading key


def test_run_refuses_next_to_trading_keys_and_does_nothing_when_off(monkeypatch: pytest.MonkeyPatch,
                                                                     tmp_path: Path) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("KALSHI_LIP_PRACTICE_ENABLED", raising=False)
    for name in list(os.environ):
        if name.endswith("_MODE") or name in P.TRADING_SECRET_NAMES or name.startswith(P.TRADING_SECRET_PREFIXES):
            monkeypatch.delenv(name, raising=False)
    assert P.main(["run"]) == 0 and not (tmp_path / "kalshi_lip_practice").exists()
    monkeypatch.setenv("KALSHI_LIP_PRACTICE_ENABLED", "true")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "never-read")
    assert P.main(["run"]) == P.EXIT_UNSAFE


def test_the_child_is_isolated() -> None:
    assert P.worker_env() == {"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"}
    command = P.worker_command(Path("/d"), Path("/r"), 7)
    assert command[0] == sys.executable and command[1:3] == ["-I", "-X"]
    boot = command[command.index("-c") + 1]
    assert boot.index("SCHED_IDLE") < boot.index("nice(19)") < boot.index("from nightcrawler")
    assert command[-3:] == ["/d", "/r", "7"]


def test_a_disabled_link_never_starts(tmp_path: Path) -> None:
    link = P.LipPracticeLink(P.LipPracticeSettings(False, tmp_path, tmp_path / "rec"))
    assert link.start() is False and link.proc is None and not link.running()
    link.close()


def test_the_real_child_runs_with_an_empty_environment_and_exits_with_its_parent(tmp_path: Path) -> None:
    settings = P.LipPracticeSettings(True, tmp_path, tmp_path / "rec")
    link = P.LipPracticeLink(settings)
    assert link.start() is True
    panel_path = tmp_path / "kalshi_lip_practice" / "panel.json"
    deadline = time.time() + 30
    while not panel_path.exists() and time.time() < deadline and link.running():
        time.sleep(0.1)
    assert panel_path.exists(), "the child never saved its panel"
    link.close(wait_s=15.0)
    assert link.proc is not None and link.proc.returncode == 0
    panel = json.loads(panel_path.read_text(encoding="utf-8"))
    assert panel["label"] == P.LABEL and panel["mode"] == "paper"
    hardening = panel["feed"]["hardening"]
    assert hardening["env_keys"] == ["LANG", "PATH", "TZ"]  # no key of any kind reached it
    assert hardening["oom_score_adj"] in (1000, None) and panel["feed"]["recorder_dir_found"] is False


# ---------------------------------------------------------------------- the desk on recorder segments
def _iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).isoformat().replace("+00:00", "Z")


def recorder(root: Path, *, result: bool = True, coverage: bool = True) -> None:
    """A recorder directory as the LIP lanes write it: programs, book calls and books, prints, coverage and the
    settlement row, for one EUR/USD window at T0."""
    seq = iter(range(1, 1_000_000))
    lip: list[dict[str, Any]] = [{"seq": next(seq), "lane": "lip", "kind": "programs", "at": T0 - 600,
                                  "status": "active", "full": True, "rows": [{
                                      "incentive_type": "liquidity", "market_ticker": EUR, "start_date": _iso(T0),
                                      "end_date": _iso(T0 + 900), "period_reward": 500000,
                                      "target_size_fp": "300.00", "discount_factor_bps": 5000, "id": "p1"}]}]
    books: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    cover: list[dict[str, Any]] = []
    at = T0 + 0.5
    while at < T0 + 900:
        number = next(seq)
        if not books:
            books.append({"seq": number, "lane": "books_lip", "kind": "book", "at": at, "ticker": EUR,
                          "requested_at": at - 0.1, "received_at": at, "sha256": "x",
                          "orderbook_fp": {"yes_dollars": YES_BOOK, "no_dollars": NO_BOOK}})
        lip.append({"seq": next(seq), "lane": "lip", "kind": "book_call", "at": at, "requested_at": at - 0.1,
                    "received_at": at, "status": 200, "tickers": [EUR], "changed": [EUR] if len(books) == 1 and
                    at == T0 + 0.5 else [], "unchanged": [] if at == T0 + 0.5 else [EUR], "missing": []})
        at += 1.0
    trades.append({"seq": next(seq), "lane": "trades_lip", "kind": "trades", "at": T0 + 10, "rows": [{
        "ticker": EUR, "trade_id": "t1", "created_time": _iso(T0 + 5), "count_fp": "7.00",
        "taker_outcome_side": "no", "yes_price_dollars": "0.3900"}]})
    if coverage:
        for start in range(int(T0 - 600), int(T0 + 1200), 60):
            cover.append({"seq": next(seq), "lane": "trade_coverage", "kind": "trade_coverage", "at": start + 61,
                          "from": start, "to": start + 60, "scope": "exchange"})
    if result:
        lip.append({"seq": next(seq), "lane": "lip", "kind": "settlement", "at": T0 + 930,
                    "rows": [{"ticker": EUR, "result": "no", "status": "finalized"}]})
    for lane, rows in (("lip", lip), ("books_lip", books), ("trades_lip", trades), ("trade_coverage", cover)):
        if not rows:
            continue
        rows.sort(key=lambda row: row["seq"])
        name = f"{lane}-20261013T180000Z-{rows[0]['seq']:012d}.jsonl.gz"
        write_segment(root / "segments" / lane / "2026-10-13" / name, rows)


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_the_desk_scores_a_window_from_the_recorders_files_and_keeps_its_accounts(tmp_path: Path) -> None:
    rec = tmp_path / "kalshi_recorder"
    recorder(rec)
    clock = Clock(T0 - 300)
    practice = P.LipPractice(tmp_path, rec, clock=clock)
    while clock.now < T0 + 1100:
        practice.step(clock.now)
        clock.now += 30.0
    practice.save(clock.now)
    rows = P.Results(tmp_path / "kalshi_lip_practice").read(["2026-10-13"])
    unfunded = [row for row in rows if row.get("account") is None]
    assert len(unfunded) == 8 and not any(row.get("void") for row in unfunded)
    ref = next(row for row in unfunded if row["policy"] == "ref_stop5" and row["model"] == "timed")
    # 7 of our 10 filled at 5 s; like the review, a partly filled order is not topped up, so the 3 left earn
    # under the $1 minimum: scored, not paid
    assert ref["through_contracts"] == 7.0 and ref["gross_raw_usd"] > 0 and ref["reward_usd"] == 0
    pull = next(row for row in unfunded if row["policy"] == "ref_pyth_pull" and row["model"] == "timed")
    assert pull["pyth_active"] is False and pull["orders_placed"] == 0  # no Pyth key yet: inactive
    panel = json.loads((tmp_path / "kalshi_lip_practice" / "panel.json").read_text(encoding="utf-8"))
    assert panel["windows"]["settled"] == 1 and panel["feed"]["recorder_dir_found"] is True
    assert "lip" in panel["feed"]["lanes"] and panel["feed"]["polls"] >= 899
    fx = [row for row in panel["scorecard"] if row["family"] == "FX" and row["policy"] == "ref_stop5"]
    assert fx and fx[0]["periods"] == 1
    a45 = next(row for row in panel["accounts"] if row["account"] == "A45:ref_stop5")
    assert a45["periods"] == 1 and a45["equity_usd"] != 45.0
    # a restart keeps the accounts' money
    again = P.LipPractice(tmp_path, rec, clock=Clock(T0 + 2000))
    restored = next(account for account in again.desk.accounts if account.name == "A45:ref_stop5")
    assert restored.equity() == pytest.approx(a45["equity_usd"]) and restored.periods == 1


def test_without_print_coverage_the_window_is_void(tmp_path: Path) -> None:
    rec = tmp_path / "kalshi_recorder"
    recorder(rec, coverage=False)
    clock = Clock(T0 - 300)
    practice = P.LipPractice(tmp_path, rec, clock=clock)
    while clock.now < T0 + 1100:
        practice.step(clock.now)
        clock.now += 30.0
    voids = [row for row in practice.recent if row.get("void")]
    assert [row["void"] for row in voids] == ["recorder_gap"]


def test_serve_halts_after_repeated_failures_and_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(self: P.LipPractice, now: float) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(P.LipPractice, "step", broken)
    code = P.serve(tmp_path, tmp_path / "rec", None, clock=lambda: T0, sleep=lambda _s: None, alarm=lambda _s: None)
    assert code == P.EXIT_HALTED
    panel = json.loads((tmp_path / "kalshi_lip_practice" / "panel.json").read_text(encoding="utf-8"))
    assert panel["problem"] == "Practice LIP desk halted after repeated errors" and panel["feed"]["errors"] == 5


def test_serve_runs_passes_and_saves(tmp_path: Path) -> None:
    code = P.serve(tmp_path, tmp_path / "rec", None, clock=lambda: T0, sleep=lambda _s: None, alarm=lambda _s: None,
                   max_passes=3)
    assert code == 0 and P.panel_state(tmp_path)["as_of"] == T0


def test_results_rotate_into_gzip_and_age_out(tmp_path: Path) -> None:
    results = P.Results(tmp_path)
    results.append([{"day": "2026-08-01", "x": 1}, {"day": "2026-10-12", "x": 2}, {"day": "2026-10-13", "x": 3}])
    results.rotate("2026-10-13")
    names = sorted(path.name for path in (tmp_path / "results").iterdir())
    assert names == ["2026-10-12.jsonl.gz", "2026-10-13.jsonl"]
    assert [row["x"] for row in results.read(["2026-10-12", "2026-10-13"])] == [2, 3]


def test_replay_command_prints_the_scorecard(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rec = tmp_path / "kalshi_recorder"
    recorder(rec)
    out = tmp_path / "replay.json"
    assert P.main(["replay", "--recorder-dir", str(rec), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "ref_stop5" in printed and "pretend money" in printed and "A45:ref_stop5" in printed
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert any(row["family"] == "FX" for row in saved["scorecard"])
    assert SERIES["KXEURUSD15M"].group == "FX"


def test_status_command(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert P.main(["status"]) == 1
    P.serve(tmp_path, tmp_path / "rec", None, clock=lambda: T0, sleep=lambda _s: None, alarm=lambda _s: None,
            max_passes=1)
    assert P.main(["status", "--data-dir", str(tmp_path)]) == 0
    assert "as_of" in capsys.readouterr().out


def test_module_runs_as_a_command() -> None:
    result = subprocess.run([sys.executable, "-m", "nightcrawler.lip_practice", "--help"], capture_output=True,
                            text=True, timeout=60, check=False, env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    assert result.returncode == 0 and "replay" in result.stdout


def test_a_book_written_just_before_the_start_still_counts_for_a_later_window(tmp_path: Path) -> None:
    """The recorder pins the next window a moment before it opens: its first (changed) book can predate the desk's
    start, and every later poll is "unchanged"."""
    rec = tmp_path / "kalshi_recorder"
    recorder(rec)
    clock = Clock(T0 + 0.6)  # starts after the window's first book (T0 + 0.5), so that window is joined late...
    practice = P.LipPractice(tmp_path, rec, clock=clock)
    practice.step(clock.now)
    assert EUR in practice.desk.books  # ...but its book is remembered, not dropped
    assert practice.desk.counters.late_records == 0


def test_nothing_is_played_before_the_print_tape_covers_it(tmp_path: Path) -> None:
    rec = tmp_path / "kalshi_recorder"
    recorder(rec, coverage=False)
    clock = Clock(T0 - 300)
    practice = P.LipPractice(tmp_path, rec, clock=clock)
    practice.step(clock.now)
    clock.now += 200.0  # under COVERAGE_WAIT_S without a coverage row: the desk waits
    practice.step(clock.now)
    assert practice.desk.watermark == practice.started_at
    clock.now += 200.0  # past it: the desk moves on, and what it lacks becomes a gap
    practice.step(clock.now)
    assert practice.desk.watermark == clock.now - P.DELAY_S and practice.desk.gaps
