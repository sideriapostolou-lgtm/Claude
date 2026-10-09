"""The Polymarket desk's risk manager (nightcrawler.polydesk + nightcrawler.deskguard): the pause and its
lifecycle (a losing record stops new buys, open positions still settle, a changed rule or the owner's switch lifts
it), the winning flag, the real book in live mode, the per-settlement record it judges, the panel's shape, and the
proof that the guard never touches real money (mode, client, live settings). No network, no keys."""

from __future__ import annotations

import inspect
import json
from typing import Any

import pytest

from nightcrawler import deskguard
from nightcrawler import polydesk as P
from nightcrawler.config import ConfigError, Settings
from tests.test_polydesk import NOW, Gateway, _market, _row
from tests.test_polydesk_live import KEY, FakeExchange, FakeLedger, _live_settings

#: Nine +$0.40 settlements then a -$20 one, six times: 90 % won and losing money (deskguard: losing).
LOSING = ([0.40] * 9 + [-20.0]) * 6
#: Nine +$1 then a -$3, ten times: +$0.60 a settlement over 100 settlements (deskguard: winning).
WINNING = ([1.0] * 9 + [-3.0]) * 10
#: Thirty settlements that prove nothing either way (deskguard: unclear).
UNCLEAR = [1.0] * 9 + [-3.0] + [0.1] * 30


@pytest.fixture
def gw(monkeypatch: pytest.MonkeyPatch) -> Gateway:
    g = Gateway()
    monkeypatch.setattr(P, "_get", g.get)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    return g


def _settings(tmp_path: Any, **env: str) -> Settings:
    return Settings.from_env({"DATA_DIR": str(tmp_path), **env})


def _record(pnls: list[float]) -> dict[str, Any]:
    return {"settled": len(pnls), "won": sum(x > 0 for x in pnls), "pnl_usd": sum(pnls), "pnls": list(pnls)}


def _seed(settings: Settings, paper: list[float] | None = None, real: list[float] | None = None,
          **extra: Any) -> None:
    """A state file whose CURRENT rule has these per-settlement records (paper and real apart)."""
    st = P.empty_state()
    rec: dict[str, Any] = {}
    if paper is not None:
        rec["paper"] = _record(paper)
    if real is not None:
        rec["real"] = _record(real)
    st["by_rule"] = {P.RULE_VERSION: rec}
    st.update(extra)
    P.save_state(P.state_path(settings), st)


def _said(desk: P.PolyDesk, start: str) -> list[dict[str, Any]]:
    return [e for e in desk.state["events"] if e["text"].startswith(start)]


# --------------------------------------------------------------------------- the pause, end to end


def test_a_losing_record_pauses_new_buys_and_open_positions_still_settle(gw: Gateway, tmp_path) -> None:
    """Built through real rounds (N = 10 here): 14 paper buys, 12 settle with 10 losses, the risk manager pauses the
    desk in that same round; the 2 still open settle normally while paused; no new market is bought; said once."""
    settings = _settings(tmp_path, POLYDESK_GUARD_MIN_N="10")
    gw.markets = [_market(f"m{i}", "crypto", 1800) for i in range(12)] + [_market(f"late{i}", "crypto", 3000)
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
    assert paused is not None and paused["at"] == NOW + 1900 and paused["rule"] == P.RULE_VERSION
    assert paused["reason"].startswith("12 settled, 10 lost, -$") and "even at best" in paused["reason"]
    said = _said(desk, "Risk manager paused the desk: ")
    assert len(said) == 1 and said[0]["tone"] == "bad" and said[0]["text"].endswith(paused["reason"])
    rec = desk.state["by_rule"][P.RULE_VERSION]["paper"]
    assert len(rec["pnls"]) == 12 == rec["settled"] and sum(rec["pnls"]) == pytest.approx(rec["pnl_usd"])
    # paused: a new near-certain market is not bought (and not marked tried), the open ones settle normally
    gw.markets = [_market("late0", "crypto", 3000 - 2000), _market("late1", "crypto", 3000 - 2000),
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
    assert g["paper"]["paused"] and g["paper"]["n"] == 14 and g["paper"]["phrase"] in ("losing", "not proven yet")
    assert g["paper"]["line"] == f"Paused by the risk manager (paper buys stopped): {paused['reason']}."
    json.dumps(d, allow_nan=False)


def test_a_new_rule_version_starts_a_fresh_record_and_lifts_the_pause(gw: Gateway, tmp_path,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    _seed(settings, paper=LOSING)
    gw.markets = [_market("n1", "crypto", 1800)]
    gw.quotes = {"n1": (0.97, 0.98)}
    desk = P.PolyDesk(settings)
    assert desk.poll(NOW)["bought"] == 0 and desk.state["paused"]["rule"] == P.RULE_VERSION
    old = P.RULE_VERSION
    monkeypatch.setattr(P, "RULE_VERSION", "2026-10-10a")  # the rule changed
    assert desk.poll(NOW + 60)["bought"] == 1 and desk.state["paused"] is None
    assert desk.state["positions"]["n1"]["rule"] == "2026-10-10a"
    lifted = _said(desk, "Risk manager lifted the pause on the desk")
    assert len(lifted) == 1 and lifted[0]["text"].endswith("the rule changed, its record starts from zero")
    assert desk.state["guard"]["paper"]["verdict"] == "learning" and desk.state["guard"]["paper"]["n"] == 0
    assert len(desk.state["by_rule"][old]["paper"]["pnls"]) == 60  # the old rule's record is kept, not judged
    # a stale pause of an older rule in a file is never shown as a pause
    st = P.load_state(P.state_path(settings))
    st["paused"] = {"at": NOW, "reason": "old", "rule": old}
    P.save_state(P.state_path(settings), st)
    assert P.panel_state(settings, NOW + 60)["guard"]["paused"] is None


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
    g = P.panel_state(off, NOW + 120)["guard"]
    assert g["on"] is False and g["paused"] is None and not g["paper"]["paused"]
    assert g["paper"]["verdict"] == "losing"  # the verdict is still shown, it just stops nothing
    assert g["paper"]["line"].startswith("Risk manager off (the owner's switch); the paper record is losing: 60 settled")
    # with the guard off from the start, a losing record says nothing and stops nothing
    fresh = _settings(tmp_path / "f", POLYDESK_GUARD="false")
    _seed(fresh, paper=LOSING)
    desk3 = P.PolyDesk(fresh)
    assert desk3.poll(NOW)["bought"] == 1 and not _said(desk3, "Risk manager")


def test_a_winning_record_is_only_a_flag_for_the_owner(gw: Gateway, tmp_path) -> None:
    settings = _settings(tmp_path)
    _seed(settings, paper=WINNING)
    gw.markets = [_market("n1", "crypto", 1800)]
    gw.quotes = {"n1": (0.97, 0.98)}

    def no_client(*args: Any) -> Any:
        raise AssertionError("the guard must never open a real-money client")

    desk = P.PolyDesk(settings, client_factory=no_client)
    assert desk.poll(NOW)["bought"] == 1  # nothing is paused
    cand = desk.state["candidate"]
    assert cand == {"at": NOW, "reason": cand["reason"], "rule": P.RULE_VERSION}
    assert cand["reason"].startswith("100 settled, 10 lost, +$60.00 in all; at worst")
    said = _said(desk, "Candidate for real money (owner decides): ")
    assert len(said) == 1 and said[0]["tone"] == "good" and said[0]["text"].endswith(cand["reason"])  # not clipped
    assert desk.state["mode"] == "paper" and desk.client is None and desk.reader is None
    desk.poll(NOW + 60)
    assert len(_said(desk, "Candidate for real money")) == 1 and desk.state["candidate"]["at"] == NOW  # said once
    g = P.panel_state(settings, NOW + 60)["guard"]
    assert g["candidate"]["rule"] == P.RULE_VERSION and g["paper"]["verdict"] == "winning"
    assert g["paper"]["line"].startswith("Risk manager (paper, winning): a candidate for real money, the owner decides.")
    assert P.panel_state(settings, NOW + 60)["label"] == "Paper money (pretend)"


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
    """The source itself: the guard method writes only its keys, and deskguard has no way to reach money."""
    src = inspect.getsource(P.PolyDesk._guard)
    for forbidden in ('"mode"', "self.client", '"live_halted"', '"live_status"', "settings.replace", "_connect",
                      "buy_long_ioc"):
        assert forbidden not in src, forbidden
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
    assert desk.poll(NOW)["bought"] == 0 and not ex.orders and "w1" not in desk.state["tried"]
    assert desk.state["paused_real"]["rule"] == P.RULE_VERSION and desk.state["paused"] is None
    said = _said(desk, "Risk manager paused real buys: 12 settled, 8 lost, -$7.76 in all")
    assert len(said) == 1
    guard_receipts = [p for k, p in ledger.receipts if k == "polydesk_guard"]
    assert guard_receipts == [{"book": "real", "paused": True, "rule": P.RULE_VERSION, "verdict": "losing", "n": 12,
                               "total_usd": pytest.approx(-7.76)}]
    assert desk.state["mode"] == "live" and desk.client is ex  # stopped buying; nothing else changed
    g = P.panel_state(settings, NOW)["guard"]
    assert g["real"]["paused"] and g["real"]["verdict"] == "losing" and not g["paper"]["paused"]
    assert g["real"]["line"].startswith("Paused by the risk manager (real buys stopped): 12 settled, 8 lost")


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
    assert g["real"]["line"] == ("Paused by the risk manager (real buys stopped): the paper record is losing, "
                                 f"{desk.state['paused']['reason']}.")
    # the owner's switch lets the live desk buy again (the caps still apply)
    desk2 = P.PolyDesk(_live_settings(tmp_path, POLYDESK_GUARD="off"), ledger=FakeLedger(), client_factory=ex)
    assert desk2.poll(NOW + 60)["bought"] == 1 and [o["slug"] for o in ex.orders] == ["w1"]


# --------------------------------------------------------------------------- the record it judges


def test_every_settlement_is_kept_per_rule_and_book_and_older_files_are_backfilled(tmp_path,
                                                                                  monkeypatch: pytest.MonkeyPatch
                                                                                  ) -> None:
    settings = _settings(tmp_path)
    # closed rows are newest first; the per-settlement list is oldest first
    closed = [_row("c3", "crypto", 0.98, False, -20.0, rule=P.RULE_VERSION),
              _row("old", "crypto", 0.98, True, 0.5),  # before the fix: another rule's row
              {**_row("u1", "crypto", 0.98, False, 0.0, rule=P.RULE_VERSION), "won": None, "pnl_usd": None},
              _row("c2", "crypto", 0.98, True, 0.3, rule=P.RULE_VERSION),
              _row("r1", "crypto", 0.97, True, 0.02, rule=P.RULE_VERSION, live=True),
              _row("c1", "crypto", 0.98, True, 0.4, rule=P.RULE_VERSION)]
    st = P.empty_state()
    st["closed"] = closed
    st["by_rule"] = {P.RULE_VERSION: {"paper": {"settled": 3, "won": 2, "pnl_usd": -19.3},
                                      "real": {"settled": 1, "won": 1, "pnl_usd": 0.02}}}
    P.save_state(P.state_path(settings), st)
    loaded = P.load_state(P.state_path(settings))
    assert loaded["by_rule"][P.RULE_VERSION]["paper"]["pnls"] == [0.4, 0.3, -20.0]
    assert loaded["by_rule"][P.RULE_VERSION]["real"]["pnls"] == [0.02]
    st["by_rule"] = {}  # a file from before the per-rule record: rebuilt, with the lists
    P.save_state(P.state_path(settings), st)
    rebuilt = P.load_state(P.state_path(settings))["by_rule"]
    assert rebuilt[P.RULE_VERSION]["paper"]["pnls"] == [0.4, 0.3, -20.0]
    assert rebuilt["before the fix"]["paper"]["pnls"] == [0.5]
    # the list keeps the newest GUARD_KEEP
    monkeypatch.setattr(P, "GUARD_KEEP", 3)
    by_rule: dict[str, Any] = {}
    for i in range(5):
        P._tally(by_rule, {"rule": "r", "live": False}, float(i), True)
    assert by_rule["r"]["paper"]["pnls"] == [2.0, 3.0, 4.0] and by_rule["r"]["paper"]["settled"] == 5


def test_the_panel_carries_the_guard_view(tmp_path) -> None:
    settings = _settings(tmp_path)
    fresh = P.panel_state(settings, NOW)["guard"]
    assert set(fresh) == {"on", "rule", "paper", "real", "paused", "paused_real", "candidate"}
    assert fresh["on"] and fresh["rule"] == P.RULE_VERSION and fresh["real"] is None
    assert (fresh["paused"], fresh["paused_real"], fresh["candidate"]) == (None, None, None)
    paper = fresh["paper"]
    assert paper["verdict"] == "learning" and paper["paused"] is False and paper["n"] == 0 and paper["min_n"] == 30
    assert paper["line"] == ("Risk manager (paper, still learning): 0 of 30 settlements needed before judging; so far "
                             "$0.00, 0 lost.")
    assert {"verdict", "reason", "n", "losses", "total", "mean", "lower", "upper", "win_lower", "stressed",
            "loss_rate_hi", "benchmark", "min_n", "win_n", "phrase", "paused", "line"} == set(paper)
    _seed(settings, paper=UNCLEAR, real=[0.02] * 3)
    g = P.panel_state(settings, NOW)["guard"]
    assert g["paper"]["verdict"] == "unclear" and g["paper"]["line"].startswith("Risk manager (paper, not proven yet): ")
    assert g["real"]["verdict"] == "learning" and g["real"]["n"] == 3  # a real record of the current rule: shown
    json.dumps(g, allow_nan=False)
    custom = _settings(tmp_path, POLYDESK_GUARD_MIN_N="50", POLYDESK_GUARD_WIN_N="200")
    assert P.panel_state(custom, NOW)["guard"]["paper"]["verdict"] == "learning"  # 40 settled < 50
    with pytest.raises(ConfigError, match="POLYDESK_GUARD_WIN_N=50 must be at least POLYDESK_GUARD_MIN_N=60"):
        _settings(tmp_path, POLYDESK_GUARD_MIN_N="60", POLYDESK_GUARD_WIN_N="50")
