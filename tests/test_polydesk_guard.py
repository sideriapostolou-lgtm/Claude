"""The Polymarket desk's risk manager (nightcrawler.polydesk + nightcrawler.deskguard): the pause and its
lifecycle (a losing record stops new buys, open positions still settle, a changed rule or the owner's switch lifts
it), the rule id (theta and hours are part of the rule), events (a game's markets are one draw), the early stop and
the small book while a rule is unproven, the winning flag (never a candidate while lab 4 has not passed the rule),
the real book in live mode, the per-settlement record it judges and its size, the panel's shape, each sport's
practice record and its flag (a way back for a blocked sport that never lets real money bet it), and the proof that
the guard never touches real money (mode, client, live settings). No network, no keys."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from nightcrawler import deskguard
from nightcrawler import polydesk as P
from nightcrawler.config import Settings
from tests.test_polydesk import NOW, Gateway, _event, _market, _open, _row
from tests.test_polydesk_live import KEY, FakeExchange, FakeLedger, _live_settings

#: Nine +$0.40 settlements then a -$20 one, six times: 90 % won and losing money (deskguard: losing).
LOSING = ([0.40] * 9 + [-20.0]) * 6
#: Nine +$1 then a -$3, ten times: +$0.60 a settlement over 100 settlements (deskguard: winning).
WINNING = ([1.0] * 9 + [-3.0]) * 10
#: Forty settlements that prove nothing either way (deskguard: unclear).
UNCLEAR = [1.0] * 9 + [-3.0] + [0.1] * 30


@pytest.fixture
def gw(monkeypatch: pytest.MonkeyPatch) -> Gateway:
    g = Gateway()
    monkeypatch.setattr(P, "_get", g.get)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    return g


def _settings(tmp_path: Any, **env: str) -> Settings:
    return Settings.from_env({"DATA_DIR": str(tmp_path), **env})


def _record(pnls: list[float], stake: float = 20.0) -> dict[str, Any]:
    """A book's record as the desk keeps it: every settlement its own event (``keys``), ``stake`` at risk each."""
    return {"settled": len(pnls), "won": sum(x > 0 for x in pnls), "pnl_usd": sum(pnls), "pnls": list(pnls),
            "costs": [stake] * len(pnls), "keys": [f"k{i}" for i in range(len(pnls))]}


def _seed(settings: Settings, paper: list[float] | None = None, real: list[float] | None = None,
          **extra: Any) -> None:
    """A state file whose CURRENT rule (polydesk.rule_id) has these per-settlement records (paper and real apart;
    a real settlement risks a $0.98 contract)."""
    st = P.empty_state()
    rec: dict[str, Any] = {}
    if paper is not None:
        rec["paper"] = _record(paper)
    if real is not None:
        rec["real"] = _record(real, stake=0.98)
    st["by_rule"] = {P.rule_id(settings): rec}
    st.update(extra)
    P.save_state(P.state_path(settings), st)


def _said(desk: P.PolyDesk, start: str) -> list[dict[str, Any]]:
    return [e for e in desk.state["events"] if e["text"].startswith(start)]


def _hhmm(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%H:%M UTC")


# --------------------------------------------------------------------------- the pause, end to end


def test_a_losing_record_pauses_new_buys_and_open_positions_still_settle(gw: Gateway, tmp_path,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """Built through real rounds (N = 10 here, the small book widened to 20): 14 paper buys, 12 settle with 10
    losses, the risk manager pauses the desk in that same round; the 2 still open settle normally while paused; no
    new market is bought; said once; the line says since when, what the record said then and what it says now."""
    monkeypatch.setattr(P, "PAPER_LEARNING_OPEN", 20)
    settings = _settings(tmp_path, POLYDESK_GUARD_MIN_N="10")
    gw.markets = [_market(f"m{i}", "crypto", 1800 + i) for i in range(12)] + [_market(f"late{i}", "crypto", 3000 + i)
                                                                               for i in range(2)]
    gw.quotes = {m["slug"]: (0.97, 0.98) for m in gw.markets}
    desk = P.PolyDesk(settings)
    assert desk.poll(NOW)["bought"] == 14 and desk.state["paused"] is None
    assert desk.state["guard"]["paper"]["verdict"] == "learning"
    gw.markets = [m for m in gw.markets if m["slug"].startswith("late")]
    gw.settlements = {f"m{i}": (1.0 if i < 2 else 0.0) for i in range(12)}
    r = desk.poll(NOW + 1900)
    assert r["settled"] == 12 and len(desk.state["positions"]) == 2
    paused = desk.state["paused"]
    assert paused is not None and paused["at"] == NOW + 1900 and paused["rule"] == P.rule_id(settings)
    assert paused["reason"].startswith("12 events (12 settled), 10 lost, -$") and "even at best" in paused["reason"]
    assert "% of the stake an event (95 % sure)" in paused["reason"]  # judged per dollar at risk, per event
    said = _said(desk, "Risk manager paused the desk: ")
    assert len(said) == 1 and said[0]["tone"] == "bad" and said[0]["text"].endswith(paused["reason"])
    rec = desk.state["by_rule"][P.rule_id(settings)]["paper"]
    assert len(rec["pnls"]) == len(rec["costs"]) == len(rec["keys"]) == 12 == rec["settled"]
    assert sum(rec["pnls"]) == pytest.approx(rec["pnl_usd"], abs=1e-3) and set(rec["costs"]) == {20.0}
    # paused: a new near-certain market is not bought (and not marked tried), the open ones settle normally
    gw.markets = [_market("late0", "crypto", 3000 - 2000), _market("late1", "crypto", 3001 - 2000),
                  _market("n1", "crypto", 1800)]
    gw.quotes["n1"] = (0.97, 0.98)
    assert desk.poll(NOW + 2000)["bought"] == 0
    assert "n1" not in desk.state["positions"] and "n1" not in desk.state["tried"]
    gw.markets = [_market("n1", "crypto", 1800 - 1200)]
    gw.settlements.update({"late0": 1.0, "late1": 1.0})
    r = desk.poll(NOW + 3200)
    assert (r["bought"], r["settled"]) == (0, 2) and not desk.state["positions"]
    assert desk.state["counters"]["settled"] == 14 and desk.state["paused"] == paused  # it sticks for its rule
    assert len(_said(desk, "Risk manager paused")) == 1  # said once
    d = P.panel_state(settings, NOW + 3200)
    g = d["guard"]
    assert g["on"] and g["paused"] == paused and g["paused_real"] is None and g["real"] is None
    assert g["paper"]["paused"] and g["paper"]["n"] == 14 and g["paper"]["paused_at"] == NOW + 1900
    assert g["paper"]["paused_since"] == _hhmm(NOW + 1900)
    now_reason = g["paper"]["reason"]
    assert now_reason.startswith("14 events (14 settled), 10 lost") and now_reason != paused["reason"]
    assert g["paper"]["line"] == (f"Paused by the risk manager since {_hhmm(NOW + 1900)} (paper buys stopped; then: "
                                  f"{paused['reason']}); the paper record now: {now_reason}.")
    # a day later the time carries its date
    assert P.panel_state(settings, NOW + 86400)["guard"]["paper"]["paused_since"] == datetime.fromtimestamp(
        NOW + 1900, UTC).strftime("%Y-%m-%d %H:%M UTC")
    json.dumps(d, allow_nan=False)


def test_a_new_rule_version_starts_a_fresh_record_and_lifts_the_pause(gw: Gateway, tmp_path,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    _seed(settings, paper=LOSING)
    gw.markets = [_market("n1", "crypto", 1800)]
    gw.quotes = {"n1": (0.97, 0.98)}
    desk = P.PolyDesk(settings)
    old = P.rule_id(settings)
    assert desk.poll(NOW)["bought"] == 0 and desk.state["paused"]["rule"] == old
    monkeypatch.setattr(P, "RULE_VERSION", "2026-10-11a")  # the rule's code changed
    new = P.rule_id(settings)
    assert new != old and new.startswith("2026-10-11a|t0.970|")
    assert desk.poll(NOW + 60)["bought"] == 1 and desk.state["paused"] is None
    assert desk.state["positions"]["n1"]["rule"] == new
    lifted = _said(desk, "Risk manager lifted the pause on the desk")
    assert len(lifted) == 1 and lifted[0]["text"].endswith("the rule changed, its record starts from zero")
    assert desk.state["guard"]["paper"]["verdict"] == "learning" and desk.state["guard"]["paper"]["n"] == 0
    assert len(desk.state["by_rule"][old]["paper"]["pnls"]) == 60  # the old rule's record is kept, not judged
    # a stale pause of an older rule in a file is never shown as a pause
    st = P.load_state(P.state_path(settings))
    st["paused"] = {"at": NOW, "reason": "old", "rule": old}
    P.save_state(P.state_path(settings), st)
    assert P.panel_state(settings, NOW + 60)["guard"]["paused"] is None


def test_a_changed_theta_or_hours_is_a_new_rule_with_its_own_record_and_pause(gw: Gateway, tmp_path) -> None:
    """The owner sets POLYDESK_THETA=0.99 after the 0.97 rule was paused: a different rule, so it starts its own
    record and is not held by the 0.97 rule's pause (nor credited with its results). A ticket change is the same
    rule (judged per dollar at risk). Rows stamped with the bare version (before the rule id) are an older rule."""
    base = _settings(tmp_path)
    _seed(base, paper=LOSING)
    gw.markets = [_market("n1", "crypto", 1800)]
    gw.quotes = {"n1": (0.99, 0.995)}
    desk = P.PolyDesk(base)
    assert desk.poll(NOW)["bought"] == 0 and desk.state["paused"]["rule"] == "2026-10-10a|t0.970|h1|s0.03"
    bigger = P.PolyDesk(_settings(tmp_path, POLYDESK_TICKET_USD="50"))  # the same rule, a bigger ticket
    assert bigger.rule == desk.rule and bigger.poll(NOW + 30)["bought"] == 0 and bigger.state["paused"] is not None
    strict = _settings(tmp_path, POLYDESK_THETA="0.99")
    assert P.rule_id(strict) == "2026-10-10a|t0.990|h1|s0.03" != P.rule_id(_settings(tmp_path, POLYDESK_HOURS="2"))
    desk2 = P.PolyDesk(strict)
    r = desk2.poll(NOW + 60)
    assert r["bought"] == 1 and desk2.state["paused"] is None and desk2.state["rule"]["id"] == P.rule_id(strict)
    assert desk2.state["positions"]["n1"]["rule"] == P.rule_id(strict)
    assert len(_said(desk2, "Risk manager lifted the pause on the desk: the rule changed")) == 1
    d = P.panel_state(strict, NOW + 60)
    assert d["since_fix"]["rule"] == P.rule_id(strict) and d["since_fix"]["paper"]["open"] == 1
    assert d["since_fix"]["paper"]["settled_total"] == 0 and d["guard"]["paper"]["n"] == 0  # not the 0.97 rule's
    assert d["before_fix"]["paper"]["settled_total"] == 0  # the counters hold no settlement in this seeded file
    # a file from before the rule id: its pause and record carry the bare version, an older rule
    legacy = _settings(tmp_path / "legacy")
    st = P.empty_state()
    st["by_rule"] = {P.RULE_VERSION: {"paper": _record(LOSING)}}
    st["paused"] = {"at": NOW, "reason": "old", "rule": P.RULE_VERSION}
    P.save_state(P.state_path(legacy), st)
    g = P.panel_state(legacy, NOW)["guard"]
    assert g["paused"] is None and g["paper"]["n"] == 0 and g["rule"] == P.rule_id(legacy)


def test_the_owners_switch_turns_the_guard_off(gw: Gateway, tmp_path) -> None:
    on = _settings(tmp_path)
    _seed(on, paper=LOSING)
    gw.markets = [_market("n1", "crypto", 1800)]
    gw.quotes = {"n1": (0.97, 0.98)}
    desk = P.PolyDesk(on)
    desk.poll(NOW)
    assert desk.state["paused"] is not None and "n1" not in desk.state["positions"]
    off = _settings(tmp_path, POLYDESK_GUARD="off")
    assert off.polydesk_guard is False
    desk2 = P.PolyDesk(off)  # the same state file, the owner's switch set
    assert desk2.poll(NOW + 60)["bought"] == 1 and desk2.state["paused"] is None
    said = _said(desk2, "Risk manager switched off by the owner")
    assert len(said) == 1 and said[0]["text"] == "Risk manager switched off by the owner: the pause on the desk is lifted"
    desk2.poll(NOW + 120)
    assert len(_said(desk2, "Risk manager switched off")) == 1
    assert desk2._paper_cap() == P.PAPER_MAX_OPEN  # off: no small book either
    g = P.panel_state(off, NOW + 120)["guard"]
    assert g["on"] is False and g["paused"] is None and not g["paper"]["paused"] and g["paper_cap"] == 60
    assert g["paper"]["verdict"] == "losing"  # the verdict is still shown, it just stops nothing
    assert g["paper"]["line"].startswith("Risk manager off (the owner's switch); the paper record is losing: 60 events")
    # with the guard off from the start, a losing record says nothing and stops nothing
    fresh = _settings(tmp_path / "f", POLYDESK_GUARD="false")
    _seed(fresh, paper=LOSING)
    desk3 = P.PolyDesk(fresh)
    assert desk3.poll(NOW)["bought"] == 1 and not _said(desk3, "Risk manager")


# --------------------------------------------------------------------------- size follows evidence


def test_a_disaster_rule_is_stopped_early_and_an_unproven_rule_keeps_a_small_book(gw: Gateway, tmp_path) -> None:
    """29 straight -$20 settlements are not "still learning" any more (the early stop), so that round buys nothing;
    a rule with no record buys at most PAPER_LEARNING_OPEN; a winning one (or the guard off) fills PAPER_MAX_OPEN."""
    gw.markets = [_market(f"x{i}", "crypto", 1800 + i) for i in range(80)]
    gw.quotes = {m["slug"]: (0.97, 0.98) for m in gw.markets}
    disaster = _settings(tmp_path / "d")
    _seed(disaster, paper=[-20.0] * 29)
    desk = P.PolyDesk(disaster)
    assert desk.poll(NOW)["bought"] == 0 and not desk.state["positions"]
    v = desk.state["guard"]["paper"]
    assert v["verdict"] == "losing" and v["early"] and v["n"] == 29
    assert desk.state["paused"]["reason"].endswith("(99 % sure, early stop)")
    fresh = P.PolyDesk(_settings(tmp_path / "f"))
    assert fresh.poll(NOW)["bought"] == P.PAPER_LEARNING_OPEN == 10
    full = _said(fresh, "Paper book full")
    assert [e["text"] for e in full] == [("Paper book full (10 open, the most until the rule's paper record is "
                                          "winning): no new paper buys until some settle.")]
    assert P.panel_state(fresh.settings, NOW)["guard"]["paper_cap"] == 10
    proven = _settings(tmp_path / "w")
    _seed(proven, paper=WINNING)
    assert P.PolyDesk(proven).poll(NOW)["bought"] == P.PAPER_MAX_OPEN == 60
    assert P.panel_state(proven, NOW)["guard"]["paper_cap"] == 60
    unclear = _settings(tmp_path / "u")
    _seed(unclear, paper=UNCLEAR)
    assert P.PolyDesk(unclear).poll(NOW)["bought"] == 10  # not proven yet: still small
    assert P.PolyDesk(_settings(tmp_path / "o", POLYDESK_GUARD="off")).poll(NOW)["bought"] == 60


# --------------------------------------------------------------------------- the winning flag


def test_a_winning_record_is_not_a_candidate_while_lab4_has_not_passed_the_rule(gw: Gateway, tmp_path) -> None:
    settings = _settings(tmp_path)
    _seed(settings, paper=WINNING)
    gw.markets = [_market("n1", "crypto", 1800)]
    gw.quotes = {"n1": (0.97, 0.98)}

    def no_client(*args: Any) -> Any:
        raise AssertionError("the guard must never open a real-money client")

    ledger = FakeLedger()
    desk = P.PolyDesk(settings, ledger=ledger, client_factory=no_client)
    assert P.RULE_LAB_PASSED is False
    assert desk.poll(NOW)["bought"] == 1  # nothing is paused
    flag = desk.state["candidate"]
    assert flag == {"at": NOW, "reason": flag["reason"], "rule": P.rule_id(settings), "lab_passed": False}
    assert flag["reason"].startswith("100 events (100 settled), 10 lost, +$60.00 in all; at worst")
    said = _said(desk, "Paper record clears the risk manager's bar (lab 4 has not passed this rule: no real money): ")
    assert len(said) == 1 and said[0]["tone"] == "good"
    assert said[0]["text"].endswith("100 events (100 settled), 10 lost, +$60.00 in all")  # not clipped
    assert not _said(desk, "Candidate for real money")  # never called a candidate
    assert [p for k, p in ledger.receipts if k == "polydesk_candidate"] == [
        {"rule": P.rule_id(settings), "n": 100, "total_usd": 60.0, "lab_passed": False, "cleared": False}]
    assert desk.state["mode"] == "paper" and desk.client is None and desk.reader is None
    desk.poll(NOW + 60)
    assert len(_said(desk, "Paper record clears")) == 1 and desk.state["candidate"]["at"] == NOW  # said once
    g = P.panel_state(settings, NOW + 60)["guard"]
    assert g["candidate"] is None and g["clears_bar"] is True and g["paper"]["verdict"] == "winning"
    assert g["paper"]["line"].startswith("Risk manager (paper, winning): the record clears the bar, but lab 4 has not "
                                         "passed this rule, so no real money. 100 events")
    assert P.panel_state(settings, NOW + 60)["label"] == "Paper money (pretend)"
    # the record falls back below the bar: one event, a receipt, and the flag is gone
    rec = desk.state["by_rule"][P.rule_id(settings)]["paper"]
    for i in range(6):
        P._tally(desk.state["by_rule"], {"rule": desk.rule, "live": False, "cost_usd": 20.0, "category": "crypto",
                                         "end_ts": NOW + i}, -20.0, False)
    desk.poll(NOW + 120)
    assert desk.state["candidate"] is None and desk.state["candidate_said"] is None
    gone = _said(desk, "No longer clears the risk manager's bar: the paper record is ")
    assert len(gone) == 1 and "106 events (106 settled), 16 lost" in gone[0]["text"]
    assert [p for k, p in ledger.receipts if k == "polydesk_candidate"][-1] == {
        "rule": P.rule_id(settings), "n": 106, "total_usd": pytest.approx(-60.0), "lab_passed": False, "cleared": True}
    # it clears the bar again later: said again
    del rec["pnls"][-6:], rec["costs"][-6:], rec["keys"][-6:]
    desk.poll(NOW + 180)
    again: Any = desk.state["candidate"]
    assert len(_said(desk, "Paper record clears")) == 2 and again["at"] == NOW + 180


def test_a_rule_that_passed_lab4_is_called_a_candidate_and_the_owner_decides(gw: Gateway, tmp_path,
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(P, "RULE_LAB_PASSED", True)  # only once a rule passes lab 4 TEST
    settings = _settings(tmp_path)
    _seed(settings, paper=WINNING)
    desk = P.PolyDesk(settings)
    desk.poll(NOW)
    assert len(_said(desk, "Candidate for real money (owner decides): 100 events")) == 1
    g = P.panel_state(settings, NOW)["guard"]
    assert g["candidate"]["lab_passed"] is True and g["paper"]["line"].startswith(
        "Risk manager (paper, winning): a candidate for real money, the owner decides.")
    assert desk.state["mode"] == "paper"  # a candidate is a flag: the owner decides, nothing switches
    off = P.PolyDesk(_settings(tmp_path, POLYDESK_GUARD="off"))
    off.poll(NOW + 60)
    assert [e["text"] for e in _said(off, "No longer a candidate")] == ["No longer a candidate: the risk manager is off"]


# --------------------------------------------------------------------------- real money: stops, never starts


@pytest.mark.parametrize("record", [LOSING, WINNING, UNCLEAR, []], ids=["losing", "winning", "unclear", "learning"])
@pytest.mark.parametrize("guard", ["on", "off"])
@pytest.mark.parametrize("mode", ["paper", "paper_with_key", "live"])
def test_the_guard_never_alters_mode_or_live_settings(gw: Gateway, tmp_path, record: list[float], guard: str,
                                                      mode: str) -> None:
    env = {"POLYDESK_GUARD": guard}
    if mode == "live":
        settings = _live_settings(tmp_path, **env)
    else:
        settings = _settings(tmp_path, **env, **(KEY if mode == "paper_with_key" else {}))
    _seed(settings, paper=record, real=record)
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(settings, ledger=FakeLedger(), client_factory=ex)
    public = settings.public_dict()

    def snapshot() -> tuple[Any, ...]:
        st = desk.state
        return (st["mode"], st["live_halted"], st["live_status"], st["live_pnl_total_usd"], st["live_days"],
                desk.client, desk.reader, desk.live_requested, desk.contracts, settings.public_dict())

    before = snapshot()
    for t in (NOW, NOW + 60):
        desk._guard(t)
        desk.poll(t)  # no market to buy: only the guard and the books move
    assert snapshot() == before and settings.public_dict() == public
    assert not ex.orders
    assert desk.state["mode"] == ("live" if mode == "live" else "paper")


def test_the_guards_code_writes_nothing_but_its_own_keys() -> None:
    """The source itself: the guard's methods write only their keys, and deskguard has no way to reach money."""
    for method in (P.PolyDesk._guard, P.PolyDesk._flag, P.PolyDesk._paper_cap, P.PolyDesk._paused,
                   P.PolyDesk._sport_flags):
        src = inspect.getsource(method)
        for forbidden in ('"mode"', "self.client", '"live_halted"', '"live_status"', "settings.replace", "_connect",
                          "buy_long_ioc", "setattr", "os.environ", "REAL_SPORTS_ALLOWED =", "global "):
            assert forbidden not in src, (method.__name__, forbidden)
    pure = inspect.getsource(deskguard)
    for forbidden in ("import requests", "polymarket", "Settings", "open(", "time.time"):
        assert forbidden not in pure, forbidden


def test_live_a_losing_real_record_stops_real_buys_and_never_starts_any(gw: Gateway, tmp_path) -> None:
    settings = _live_settings(tmp_path, POLYDESK_GUARD_MIN_N="10")
    _seed(settings, real=[-0.98] * 8 + [0.02] * 4)  # 12 real settlements of the current rule: losing
    gw.markets = [_market("w1", "crypto", 1800)]
    gw.quotes = {"w1": (0.97, 0.98)}
    ledger = FakeLedger()
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(settings, ledger=ledger, client_factory=ex)
    assert desk.state["mode"] == "live"
    # no real order; the practice book (not paused) takes the pick instead, so the rule keeps being watched
    assert desk.poll(NOW)["bought"] == 1 and not ex.orders and desk.state["positions"]["w1"]["live"] is False
    assert desk.state["paused_real"]["rule"] == P.rule_id(settings) and desk.state["paused"] is None
    said = _said(desk, "Risk manager paused real buys: 12 events (12 settled), 8 lost, -$7.76 in all")
    assert len(said) == 1
    guard_receipts = [p for k, p in ledger.receipts if k == "polydesk_guard"]
    assert guard_receipts == [{"book": "real", "paused": True, "rule": P.rule_id(settings), "verdict": "losing",
                               "n": 12, "total_usd": pytest.approx(-7.76)}]
    assert desk.state["mode"] == "live" and desk.client is ex  # stopped buying; nothing else changed
    g = P.panel_state(settings, NOW)["guard"]
    assert g["real"]["paused"] and g["real"]["verdict"] == "losing" and not g["paper"]["paused"]
    assert g["real"]["line"] == (f"Paused by the risk manager since {_hhmm(NOW)} (real buys stopped): "
                                 f"{g['real']['reason']}.")
    assert g["real"]["reason"].startswith("12 events (12 settled), 8 lost, -$7.76 in all; even at best -")


def test_live_a_losing_paper_record_stops_real_buys_too(gw: Gateway, tmp_path) -> None:
    """Real money never follows a rule its own paper record shows losing."""
    settings = _live_settings(tmp_path)
    _seed(settings, paper=LOSING)
    gw.markets = [_market("w1", "crypto", 1800)]
    gw.quotes = {"w1": (0.97, 0.98)}
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(settings, ledger=FakeLedger(), client_factory=ex)
    assert desk.poll(NOW)["bought"] == 0 and not ex.orders
    assert desk.state["paused"] is not None and desk.state["paused_real"] is None and desk.state["mode"] == "live"
    g = P.panel_state(settings, NOW)["guard"]
    assert g["paper"]["paused"] and g["real"]["paused"]  # shown on the real line too
    assert g["real"]["line"] == (f"Paused by the risk manager since {_hhmm(NOW)} (real buys stopped; then: the paper "
                                 f"record was losing, {desk.state['paused']['reason']}); the real record now: "
                                 f"{g['real']['reason']}.")
    # the owner's switch lets the live desk buy again (the caps still apply)
    desk2 = P.PolyDesk(_live_settings(tmp_path, POLYDESK_GUARD="off"), ledger=FakeLedger(), client_factory=ex)
    assert desk2.poll(NOW + 60)["bought"] == 1 and [o["slug"] for o in ex.orders] == ["w1"]


# --------------------------------------------------------------------------- the record it judges


def test_a_games_markets_and_a_ladder_ending_together_are_one_event_each() -> None:
    """The desk can be long the leader and short the draw and the trailer of one game: one result settles all three.
    A crypto ladder's markets end together on one price. Each is one draw; two games of the same name on different
    days are two."""
    by_rule: dict[str, Any] = {}
    game = {"rule": "r", "live": False, "cost_usd": 20.0, "category": "sports", "event": "Ajax vs PSV",
            "end_ts": NOW + 21600}
    rows = [(game, 0.5), (game, 0.4), (game, 0.3),  # one game, three markets
            ({**game, "end_ts": NOW + 86400 + 21600}, -20.0),  # the same names a day later: another game
            ({**game, "event": None, "category": "crypto", "end_ts": NOW + 3600}, 0.4),  # a ladder ...
            ({**game, "event": None, "category": "crypto", "end_ts": NOW + 3600}, -20.0),  # ... ending together
            ({**game, "event": None, "category": "crypto", "end_ts": NOW + 7200}, 0.4)]  # another hour: apart
    for row, pnl in rows:
        P._tally(by_rule, row, pnl, pnl > 0)
    keys = by_rule["r"]["paper"]["keys"]
    assert keys[0] == keys[1] == keys[2] != keys[3] and keys[4] == keys[5] != keys[6]
    assert keys[0].startswith("e") and len(keys[0]) < 24 and keys[4] == f"crypto:{int(NOW + 3600)}"  # short keys
    settings = Settings.from_env({})
    v = P.judge_book(settings, {P.rule_id(settings): by_rule["r"]}, "paper")
    assert (v.n, v.settled, v.losses) == (4, 7, 2) and v.unit == "stake" and v.per == "event"
    assert v.reason.startswith("4 of 30 events needed before judging")


def test_every_settlement_is_kept_per_rule_and_book_and_older_files_are_backfilled(tmp_path,
                                                                                  monkeypatch: pytest.MonkeyPatch
                                                                                  ) -> None:
    settings = _settings(tmp_path)
    rule = P.rule_id(settings)
    # closed rows are newest first; the per-settlement lists are oldest first
    closed = [_row("c3", "crypto", 0.98, False, -20.0, rule=rule),
              _row("old", "crypto", 0.98, True, 0.5),  # before the fix: another rule's row
              {**_row("u1", "crypto", 0.98, False, 0.0, rule=rule), "won": None, "pnl_usd": None},
              _row("c2", "crypto", 0.98, True, 0.3, rule=rule, end_left=3600.0),
              _row("r1", "crypto", 0.97, True, 0.02, rule=rule, live=True),
              _row("c1", "crypto", 0.98, True, 0.4, rule=rule)]
    st = P.empty_state()
    st["closed"] = closed
    st["by_rule"] = {rule: {"paper": {"settled": 3, "won": 2, "pnl_usd": -19.3},
                            "real": {"settled": 1, "won": 1, "pnl_usd": 0.02}}}
    P.save_state(P.state_path(settings), st)
    loaded = P.load_state(P.state_path(settings))["by_rule"][rule]
    assert loaded["paper"]["pnls"] == [0.4, 0.3, -20.0] and loaded["paper"]["costs"] == [20.0] * 3
    assert loaded["paper"]["keys"] == [f"crypto:{int(NOW + 1800)}", f"crypto:{int(NOW + 3600)}",
                                       f"crypto:{int(NOW + 1800)}"]
    assert loaded["real"] == {"settled": 1, "won": 1, "pnl_usd": 0.02, "pnls": [0.02], "costs": [0.97],
                              "keys": [f"crypto:{int(NOW + 1800)}"]}
    # a record whose lists are out of line (an older build added P&Ls only) is rebuilt from the kept rows
    st["by_rule"] = {rule: {"paper": {"settled": 9, "won": 8, "pnl_usd": 1.0, "pnls": [0.1] * 9}}}
    P.save_state(P.state_path(settings), st)
    rebuilt = P.load_state(P.state_path(settings))["by_rule"][rule]["paper"]
    assert rebuilt["pnls"] == [0.4, 0.3, -20.0] and len(rebuilt["keys"]) == len(rebuilt["costs"]) == 3
    assert rebuilt["settled"] == 9  # the totals stay the desk's own
    st["by_rule"] = {}  # a file from before the per-rule record: rebuilt, with the lists
    P.save_state(P.state_path(settings), st)
    by_rule = P.load_state(P.state_path(settings))["by_rule"]
    assert by_rule[rule]["paper"]["pnls"] == [0.4, 0.3, -20.0] and by_rule["before the fix"]["paper"]["pnls"] == [0.5]
    # the lists keep the newest GUARD_KEEP, in line; P&Ls are kept to 1e-4
    monkeypatch.setattr(P, "GUARD_KEEP", 3)
    fresh: dict[str, Any] = {}
    for i in range(5):
        P._tally(fresh, {"rule": "r", "live": False, "cost_usd": 20.0, "category": "crypto", "end_ts": NOW + i},
                 i + 0.123456789, True)
    rec = fresh["r"]["paper"]
    assert rec["pnls"] == [2.1235, 3.1235, 4.1235] and rec["settled"] == 5
    assert rec["keys"] == [f"crypto:{int(NOW) + i}" for i in (2, 3, 4)] and rec["costs"] == [20.0] * 3
    assert rec["pnl_usd"] == pytest.approx(sum(i + 0.123456789 for i in range(5)))  # the total stays exact
    # a record whose lists lost their line (a hand-edited file) is still judged on the newest settlements
    odd = {"pnls": [-20.0] * 12, "costs": [20.0] * 3, "keys": ["a"] * 20}
    v = P.judge_book(settings, {rule: {"paper": odd}}, "paper")
    assert v.settled == 3 and v.n == 1  # the 9 P&Ls without a known stake are dropped; the rest is one event


def test_older_rules_keep_only_their_newest_settlements(gw: Gateway, tmp_path) -> None:
    """Only the current rule is judged, so an older rule's lists are trimmed to GUARD_KEEP_OLD when the desk saves;
    its settled / won / P&L totals stay whole. The state file stays small (it is rewritten every round)."""
    settings = _settings(tmp_path)
    st = P.empty_state()
    big = _record([0.4] * 999 + [-20.0])
    st["by_rule"] = {"2026-10-09b": {"paper": dict(big)}, P.rule_id(settings): {"paper": _record([0.4] * 999 + [-20.0])}}
    P.save_state(P.state_path(settings), st)
    desk = P.PolyDesk(settings)  # the desk saves once it starts
    saved = P.load_state(P.state_path(settings))["by_rule"]
    old = saved["2026-10-09b"]["paper"]
    assert len(old["pnls"]) == len(old["costs"]) == len(old["keys"]) == P.GUARD_KEEP_OLD == 200
    assert old["pnls"][-1] == -20.0 and old["settled"] == 1000 and old["pnl_usd"] == pytest.approx(big["pnl_usd"])
    assert len(saved[desk.rule]["paper"]["pnls"]) == 1000  # the current rule keeps its record
    size = P.state_path(settings).stat().st_size
    assert size < 60_000, size


def test_the_panel_carries_the_guard_view(tmp_path) -> None:
    settings = _settings(tmp_path)
    fresh = P.panel_state(settings, NOW)["guard"]
    assert set(fresh) == {"on", "rule", "paper", "real", "paused", "paused_real", "candidate", "clears_bar",
                          "paper_cap"}
    assert fresh["on"] and fresh["rule"] == P.rule_id(settings) and fresh["real"] is None
    assert (fresh["paused"], fresh["paused_real"], fresh["candidate"], fresh["clears_bar"]) == (None, None, None, False)
    paper = fresh["paper"]
    assert paper["verdict"] == "learning" and paper["paused"] is False and paper["n"] == 0 and paper["min_n"] == 30
    assert paper["line"] == ("Risk manager (paper, still learning): 0 of 30 events needed before judging; so far "
                             "$0.00, 0 lost.")
    assert {"verdict", "reason", "n", "losses", "total", "mean", "lower", "upper", "win_lower", "stressed",
            "loss_rate_hi", "benchmark", "min_n", "win_n", "settled", "summary", "unit", "per", "early", "phrase",
            "paused", "paused_at", "paused_since", "line"} == set(paper)
    _seed(settings, paper=UNCLEAR, real=[0.02] * 3)
    g = P.panel_state(settings, NOW)["guard"]
    assert g["paper"]["verdict"] == "unclear" and g["paper"]["line"].startswith("Risk manager (paper, not proven yet): ")
    assert g["real"]["verdict"] == "learning" and g["real"]["n"] == 3  # a real record of the current rule: shown
    json.dumps(g, allow_nan=False)
    custom = _settings(tmp_path, POLYDESK_GUARD_MIN_N="50", POLYDESK_GUARD_WIN_N="200")
    assert P.panel_state(custom, NOW)["guard"]["paper"]["verdict"] == "learning"  # 40 settled < 50
    # MIN_N above WIN_N no longer stops the bot from booting: WIN_N is raised to MIN_N
    odd = _settings(tmp_path, POLYDESK_GUARD_MIN_N="150", POLYDESK_GUARD_WIN_N="100")
    assert (odd.polydesk_guard_min_n, odd.polydesk_guard_win_n) == (150, 100)
    assert P.panel_state(odd, NOW)["guard"]["paper"]["win_n"] == 150


# --------------------------------------------------------------------------- per sport: the way back, never real money


#: 150 practice games of one sport: +$2 on 146 of them, -$20 on 4 (a record deskguard.judge calls winning).
SPORT_WINNING = [2.0] * 36 + [-20.0] + [2.0] * 36 + [-20.0] + [2.0] * 37 + [-20.0] + [2.0] * 37 + [-20.0]


def _seed_sports(settings: Settings, sports: dict[str, list[float]], **extra: Any) -> None:
    """A state file whose CURRENT rule has these per-sport PRACTICE records (each game its own event, $20 a game)."""
    st = P.empty_state()
    st["by_sport"] = {P.rule_id(settings): {sport: {"paper": _record(pnls)} for sport, pnls in sports.items()}}
    st.update(extra)
    P.save_state(P.state_path(settings), st)


def _soccer_game(slug: str = "epl-ars-che-2026-10-10") -> dict[str, Any]:
    """An English Premier League game in play (league code epl: soccer in lab 4's map), one match-winner market."""
    return _event(slug, -3600, "2H")


def test_settlements_are_kept_per_sport(gw: Gateway, tmp_path) -> None:
    settings = _settings(tmp_path)
    rule = P.rule_id(settings)
    st = P.empty_state()
    st["positions"] = {
        "t1": {**_open("t1", "sports", 0.97, spread=0.01, rule=rule), "sport": "tennis", "event": "A vs B"},
        "s1": {**_open("s1", "sports", 0.97, spread=0.01, rule=rule), "sport": "soccer", "event": "C vs D"},
        "c1": _open("c1", "crypto", 0.97, spread=0.01, rule=rule, live=True),
    }
    P.save_state(P.state_path(settings), st)
    desk = P.PolyDesk(settings)
    gw.settlements = {"t1": 0.0, "s1": 1.0, "c1": 1.0}
    assert desk.poll(NOW + 4000)["settled"] == 3
    by_sport = desk.state["by_sport"][rule]
    assert set(by_sport) == {"tennis", "soccer"}  # sports only: the crypto bet is no sport's
    assert by_sport["tennis"]["paper"]["settled"] == 1 and by_sport["tennis"]["paper"]["won"] == 0
    assert by_sport["soccer"]["paper"]["settled"] == 1 and by_sport["soccer"]["paper"]["won"] == 1
    rec = by_sport["tennis"]["paper"]
    assert len(rec["pnls"]) == len(rec["costs"]) == len(rec["keys"]) == 1 and rec["costs"] == [20.0]
    assert desk.state["by_rule"][rule]["paper"]["settled"] == 2  # the rule's own record is unchanged by the split
    # the panel: every sport in the history's order, real money blocked for each, the practice record beside it
    sports = P.panel_state(settings, NOW + 4000)["sports"]
    assert [s["sport"] for s in sports] == list(P.SPORT_HISTORY) and {s["real"] for s in sports} == {"blocked"}
    tennis = next(s for s in sports if s["sport"] == "tennis")
    assert tennis["history"] == "proven loser" and tennis["why"] == P.SPORT_HISTORY["tennis"][1]
    assert tennis["paper"] == {"settled": 1, "won": 0, "pnl_usd": pytest.approx(rec["pnl_usd"]),
                               "verdict": "learning", "phrase": "still learning"}
    assert next(s for s in sports if s["sport"] == "cricket")["paper"] is None  # no practice game yet
    assert P.panel_state(settings, NOW)["real_sports_allowed"] == []


def test_a_winning_practice_sport_is_flagged_but_gets_no_real_order(gw: Gateway, tmp_path) -> None:
    """A blocked sport's practice record clears the risk manager's bar: a flag for the owner (one event, one
    receipt), and the next qualifying game of that sport still gets no real order."""
    assert deskguard.judge(SPORT_WINNING, groups=[f"g{i}" for i in range(150)], stakes=[20.0] * 150).verdict == "winning"
    settings = _live_settings(tmp_path)
    _seed_sports(settings, {"soccer": SPORT_WINNING})
    gw.events = [_soccer_game()]
    gw.quotes = {"epl-ars-che-2026-10-10-ml": (0.97, 0.98)}
    ledger = FakeLedger()
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(settings, ledger=ledger, client_factory=ex)
    desk.poll(NOW)
    assert ex.orders == [] and desk.state["mode"] == "live"
    pos = desk.state["positions"]["epl-ars-che-2026-10-10-ml"]
    assert pos["live"] is False and pos["sport"] == "soccer"  # practised, never real
    flag = desk.state["sport_flags"]["soccer"]
    assert flag["rule"] == P.rule_id(settings) and flag["at"] == NOW and flag["reason"].startswith("150 events")
    said = _said(desk, "Practice record for soccer clears the risk manager's bar (150 events (150 settled), 4 lost")
    assert len(said) == 1 and said[0]["tone"] == "good"
    assert [p for k, p in ledger.receipts if k == "polydesk_sport_flag"] == [
        {"sport": "soccer", "rule": P.rule_id(settings), "n": 150, "total_usd": pytest.approx(212.0), "cleared": False}]
    assert P.REAL_SPORTS_ALLOWED == frozenset()  # the flag never lets real money bet the sport
    desk.poll(NOW + 60)
    assert len(_said(desk, "Practice record for soccer")) == 1 and ex.orders == []  # said once
    soccer = next(s for s in P.panel_state(settings, NOW + 60)["sports"] if s["sport"] == "soccer")
    assert soccer["flagged"] is True and soccer["real"] == "blocked" and soccer["paper"]["verdict"] == "winning"


def test_tennis_and_esports_are_never_flagged(gw: Gateway, tmp_path) -> None:
    settings = _settings(tmp_path)
    _seed_sports(settings, {"tennis": SPORT_WINNING, "esports": SPORT_WINNING, "other": SPORT_WINNING})
    desk = P.PolyDesk(settings, ledger=FakeLedger())
    desk.poll(NOW)
    assert desk.state["sport_flags"] == {} and not _said(desk, "Practice record for")
    assert P.PROVEN_LOSERS == {"tennis", "esports"}
    assert not any(s["flagged"] for s in P.panel_state(settings, NOW)["sports"])


def test_the_flag_clears_when_the_record_falls_back(gw: Gateway, tmp_path) -> None:
    settings = _settings(tmp_path)
    _seed_sports(settings, {"table tennis": SPORT_WINNING})
    ledger = FakeLedger()
    desk = P.PolyDesk(settings, ledger=ledger)
    desk.poll(NOW)
    assert "table tennis" in desk.state["sport_flags"]
    rule = P.rule_id(settings)
    for i in range(8):  # eight more lost practice games: the record falls back
        P._tally(desk.state["by_rule"], {"rule": rule, "live": False, "cost_usd": 20.0, "category": "sports",
                                         "sport": "table tennis", "event": f"x{i}", "end_ts": NOW + i}, -20.0, False,
                 desk.state["by_sport"])
    desk.poll(NOW + 60)
    assert desk.state["sport_flags"] == {}
    gone = _said(desk, "No longer clears the risk manager's bar for table tennis: its practice record is ")
    assert len(gone) == 1 and "158 events (158 settled), 12 lost" in gone[0]["text"]
    assert [p["cleared"] for k, p in ledger.receipts if k == "polydesk_sport_flag"] == [False, True]
    desk.poll(NOW + 120)
    assert len(_said(desk, "No longer clears the risk manager's bar for table tennis")) == 1  # said once
    # the guard switched off clears a flag too, and says why
    _seed_sports(_settings(tmp_path / "off"), {"hockey": SPORT_WINNING})
    on = P.PolyDesk(_settings(tmp_path / "off"))
    on.poll(NOW)
    assert "hockey" in on.state["sport_flags"]
    off = P.PolyDesk(_settings(tmp_path / "off", POLYDESK_GUARD="off"))
    off.poll(NOW + 60)
    assert off.state["sport_flags"] == {}
    assert [e["text"] for e in _said(off, "No longer clears the risk manager's bar for hockey")] == [
        "No longer clears the risk manager's bar for hockey: the risk manager is off"]


def test_older_rules_sport_lists_are_trimmed(gw: Gateway, tmp_path) -> None:
    settings = _settings(tmp_path)
    st = P.empty_state()
    big = _record([0.4] * 999 + [-20.0])
    st["by_sport"] = {"2026-10-09b|t0.970|h1|s0.03": {"tennis": {"paper": dict(big)}},
                      P.rule_id(settings): {"tennis": {"paper": _record([0.4] * 999 + [-20.0])}}}
    P.save_state(P.state_path(settings), st)
    P.PolyDesk(settings)  # the desk saves once it starts
    saved = P.load_state(P.state_path(settings))["by_sport"]
    old = saved["2026-10-09b|t0.970|h1|s0.03"]["tennis"]["paper"]
    assert len(old["pnls"]) == len(old["costs"]) == len(old["keys"]) == P.GUARD_KEEP_OLD
    assert old["settled"] == 1000 and old["pnl_usd"] == pytest.approx(big["pnl_usd"])  # the totals stay whole
    assert len(saved[P.rule_id(settings)]["tennis"]["paper"]["pnls"]) == 1000  # the current rule keeps its record
