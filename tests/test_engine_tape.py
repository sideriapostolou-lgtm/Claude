"""PR-E: what the engine tapes for the Coach and the experience team (EXPERIENCE.md §4.2, §11). Emits only:

* ``_decide`` tapes ``watch``, ``unwatch``, ``exit`` and ``exit_partial`` too (``hold`` stays untaped), and a
  decision row carries ``sizing {equity_usd, free_sol, size_usd}``;
* the equity ``lag`` row carries ``equity_usd``;
* at boot one ``lag`` row ``kind="versions"`` with the 7 member hashes (and ``team_hash``);
* compact ``lag`` rows ``kind="seen"`` ``{source, mints[]}`` per crawler poll with coins the tape has not seen yet;
* all through ``put_nowait``: emits on or off, or a full recorder queue, never change a decision.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from nightcrawler.engine import MEMBERS, LearnStage, member_hashes
from nightcrawler.learn.recorder import Recorder
from test_engine import Rig, fresh_rig, recorder_thread, stop_learning, trading, walk
from world import GARY, RISKY, jupiter_token

#: Every decision row has exactly these keys (``v`` and ``variant_hash`` are added by the learn stage).
DECISION_KEYS = {"v", "variant_hash", "ts", "mint", "decision", "reason", "signal", "snapshot", "candle_source",
                 "safety", "verdict", "sizing"}
TAPED = ("enter", "watch", "unwatch", "exit", "exit_partial")


class TapeSpy:
    """A recorder thread stand-in whose recorder keeps every row (``accept=False``: a full queue)."""

    def __init__(self, accept: bool = True) -> None:
        self.accept = accept
        self.rows: list[tuple[str, dict[str, Any]]] = []
        self.recorder = self
        self.stats: dict[str, int] = {}

    def emit(self, stream: str, row: dict[str, Any]) -> bool:
        if self.accept:
            self.rows.append((stream, json.loads(json.dumps(row, allow_nan=False))))
        return self.accept

    def is_alive(self) -> bool:
        return True

    def stop(self) -> None:
        pass

    def stream(self, name: str, **match: Any) -> list[dict[str, Any]]:
        return [r for s, r in self.rows if s == name and all(r.get(k) == v for k, v in match.items())]


def spying(spy: TapeSpy) -> Any:
    return lambda settings, ledger, clock: LearnStage(settings, ledger, start_recorder=lambda: spy,
                                                      spawn=lambda: None)


@pytest.fixture
def taped(tmp_path, make_settings):
    spy = TapeSpy()
    rig = fresh_rig(tmp_path, make_settings, "taped", learning=spying(spy))
    yield rig, spy
    stop_learning(rig)


def decision_rows(spy: TapeSpy) -> list[dict[str, Any]]:
    return [r for r in spy.stream("evals") if "decision" in r]


def test_every_decision_that_moves_a_coin_is_taped_with_a_pinned_shape(taped) -> None:
    rig, spy = taped
    walk(rig)
    rows = decision_rows(spy)
    recorded = [d.action for d in reversed(rig.ledger.decisions(limit=1000))
                if d.action in TAPED or d.action.startswith("reject_")]
    assert [r["decision"] for r in rows] == recorded == ["reject_cocoon", "watch", "enter", "exit_partial", "exit",
                                                         "reject_risk", "reject_risk"]  # (the setup, in cooldown)
    assert all(set(r) == DECISION_KEYS for r in rows)
    watch = rows[1]
    assert watch["mint"] == GARY and watch["safety"]["passed"] is True and watch["sizing"] is None
    assert rows[0]["mint"] == RISKY and rows[0]["safety"]["hard_fail_reasons"]
    assert [r["reason"] for r in rows[3:5]] == ["take_profit_partial", "trailing_stop"]
    assert rows[5]["reason"].startswith("[cooldown]") and rows[5]["sizing"]["equity_usd"] > 0


def test_an_enter_row_carries_its_sizing(taped) -> None:
    rig, spy = taped
    walk(rig)
    [enter] = rig.ledger.decisions(actions=["enter"])
    sizing = enter.inputs["sizing"]
    [row] = [r for r in decision_rows(spy) if r["decision"] == "enter"]
    assert row["sizing"] == {"equity_usd": pytest.approx(sizing["equity_lamports"] / 1e9 * sizing["sol_usd"]),
                             "free_sol": pytest.approx(sizing["free_lamports"] / 1e9),
                             "size_usd": pytest.approx(sizing["size_usd"])}
    assert row["sizing"]["equity_usd"] == pytest.approx(100.0) and row["sizing"]["size_usd"] == pytest.approx(
        15.789, abs=1e-3)


def test_the_equity_row_carries_equity_usd(taped) -> None:
    rig, spy = taped
    walk(rig)
    rows = spy.stream("lag", kind="equity")
    points = rig.ledger.equity_series()
    assert rows and [r["equity_usd"] for r in rows] == pytest.approx([p.equity_usd for p in points])
    assert all(r["sol_usd"] == 100.0 for r in rows)


def test_hold_decisions_are_not_taped(taped) -> None:
    rig, spy = taped
    rig.engine.learning.start(rig.clock.now())
    rig.tick()
    rig.world.http.register(f"inputMint={GARY}", {"errorMessage": "No routes found"})  # every sell fails
    rig.world.price = 0.30e-3  # stop-loss: the sell cannot be quoted -> hold
    rig.tick(10)
    assert rig.ledger.decisions(actions=["hold"]) and "hold" not in [r["decision"] for r in decision_rows(spy)]


def test_an_unwatch_is_taped(taped) -> None:
    rig, spy = taped
    rig.engine.learning.start(rig.clock.now())
    rig.world.liquidity = 10_000.0  # below MIN_LIQUIDITY_USD / 2 at the first refresh
    rig.tick()
    [row] = [r for r in decision_rows(spy) if r["decision"] == "unwatch"]
    assert row["mint"] == GARY and row["reason"].startswith("liquidity fell")


# --------------------------------------------------------------------------- seen rows (crawler coverage)


def test_each_poll_tapes_the_coins_it_saw_for_the_first_time_per_source(taped) -> None:
    rig, spy = taped
    rig.engine.learning.start(rig.clock.now())
    rig.tick()
    assert spy.stream("lag", kind="seen") == [{"v": 1, "ts": rig.clock.now(), "kind": "seen",
                                               "source": "jupiter_trending_1h", "mints": sorted([GARY, RISKY])}]
    rig.tick(30)  # the next poll sees the same coins: nothing new to tape
    assert len(spy.stream("lag", kind="seen")) == 1
    new = "NewCoin11111111111111111111111111111111pump"
    rig.world.trending.append(jupiter_token(new, "NEW", "Pool111111111111111111111111111111111111111",
                                            rig.clock.now() - 2 * 3600, rig.world.price, "Dev2222222222222222222222"))
    rig.tick(30)
    [first, second] = spy.stream("lag", kind="seen")
    assert second["mints"] == [new] and second["source"] == "jupiter_trending_1h"


# --------------------------------------------------------------------------- versions row at boot


def test_boot_tapes_one_versions_row_with_the_seven_member_hashes(taped) -> None:
    rig, spy = taped
    rig.engine.stop()
    rig.engine.run_forever()
    [row] = spy.stream("lag", kind="versions")
    assert set(row["members"]) == set(MEMBERS) == {"crawler", "cocoon", "radar", "strategy", "judge", "risk",
                                                   "broker"}
    assert all(len(h) == 64 and int(h, 16) >= 0 for h in row["members"].values())
    team = hashlib.sha256(json.dumps(row["members"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert row["team_hash"] == team and row["ts"] == rig.ledger.receipts()[0].ts


def test_a_member_hash_changes_with_its_own_settings_only(make_settings, tmp_path) -> None:
    base = member_hashes(make_settings())
    assert member_hashes(make_settings()) == base  # deterministic
    risk = member_hashes(make_settings(DAILY_RISK_BUDGET_PCT=0.10))
    assert {k for k in base if base[k] != risk[k]} == {"risk"}
    strategy = member_hashes(make_settings(STOP_LOSS_PCT=0.25))
    assert {k for k in base if base[k] != strategy[k]} == {"strategy"}
    broker = member_hashes(make_settings(PAPER_SLIPPAGE_BPS=50))
    assert {k for k in base if base[k] != broker[k]} == {"broker"}
    judge = member_hashes(make_settings(JUDGE_MODEL="another-model"))
    assert {k for k in base if base[k] != judge[k]} == {"judge"}
    cocoon = member_hashes(make_settings(COCOON_TOP10_MAX_PCT=25))
    assert {k for k in base if base[k] != cocoon[k]} == {"cocoon"}
    radar = member_hashes(make_settings(RADAR_INTERVAL_S=120))
    assert {k for k in base if base[k] != radar[k]} == {"radar"}
    crawler = member_hashes(make_settings(MIN_ORGANIC_SCORE=10))
    assert {k for k in base if base[k] != crawler[k]} == {"crawler"}
    window = member_hashes(make_settings(MIN_LIQUIDITY_USD=40_000))  # the universe anchors: both use them
    assert {k for k in base if base[k] != window[k]} == {"crawler", "strategy"}
    assert member_hashes(make_settings(KILL_SWITCH="stop")) == base  # a control, not a version
    assert set(base) == set(MEMBERS) and str(tmp_path) not in json.dumps(base)


# --------------------------------------------------------------------------- engine identity


def test_emits_on_off_or_dropped_never_change_a_decision(tmp_path: Path, make_settings) -> None:
    """Engine identity on tests/world.py: no learning, a recorder that keeps every row, one whose queue is
    always full (``accept=False``), and a real recorder whose bounded queue is never drained."""
    def full_queue(settings: Any) -> Any:
        thread = recorder_thread(settings)
        thread.recorder = Recorder(thread.recorder.store, thread.recorder.tape, thread.recorder.http,
                                   clock=thread.recorder.clock, emit_maxsize=1)
        return thread  # never started: nothing drains the queue

    rigs: list[Rig] = []
    try:
        off = fresh_rig(tmp_path, make_settings, "off")
        rigs.append(off)
        baseline = trading(off, walk(off))
        kept, dropped = TapeSpy(), TapeSpy(accept=False)
        variants = [("kept", spying(kept)), ("dropped", spying(dropped)),
                    ("full", lambda s, ledger, clock: LearnStage(s, ledger, start_recorder=lambda: full_queue(s),
                                                                 spawn=lambda: None))]
        for name, learning in variants:
            rig = fresh_rig(tmp_path, make_settings, name, learning=learning)
            rigs.append(rig)
            assert trading(rig, walk(rig)) == baseline, name
        assert decision_rows(kept) and dropped.rows == []
        counters = rigs[2].engine.learning.counters
        assert counters["emits_dropped"] > 0 and counters["emit_failed"] == 0
        assert rigs[3].engine.learning.counters["emits_dropped"] > 0
    finally:
        for rig in rigs:
            stop_learning(rig)  # (a recorder thread that never started closes its store when stopped)
