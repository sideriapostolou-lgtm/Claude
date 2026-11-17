"""The town goal's shared states (tests and screenshots): :data:`STATES` and :func:`apply_state`.

Each state puts the real-money desk (and the practice books) into one situation on top of a page the server built,
the way the server itself would have built it (the desk's books in :func:`nightcrawler.pagestate.polymarket_desk`'s
shape, ``plain.real`` and the risk wall's real caps from pagestate's own functions), then recomputes ``town.goal`` and
``plain.goal`` with :mod:`nightcrawler.towngoal`. ``stopped_today`` is the live snapshot of 2026-10-10 20:28 UTC (the
daily stop after 83 real bets, 78 won; the owner's second deposit in the cash). Pure: the page passed in is copied.

    python -m tests.goal_states <dir>    # one JSON page per state (the screenshot harness serves them)
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

if __name__ == "__main__":  # python -m tests.goal_states: this checkout's own code, never an installed copy
    _ROOT = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(_ROOT / "src"), str(_ROOT / "tests")]

from nightcrawler import pagestate
from nightcrawler.config import Settings

DAY = 86_400.0
#: 2026-10-10 20:28:05 UTC: the live snapshot's own time (3 h 31 min before the desk's day resets).
SNAPSHOT_AT = 1_791_664_085.0
#: The owner's deposits less what is still out, so cash = DEPOSITS + since start (the second $25 deposit included).
DEPOSITS = 47.3132
#: The real days before today (days back, the day's book): in the live states Fri 9 Oct (UTC), 8 real bets, 6 won.
YESTERDAY_REAL = {"pnl_usd": -1.776124, "settled": 8, "won": 6}
HISTORY: tuple[tuple[int, dict[str, Any]], ...] = ((1, YESTERDAY_REAL),)
#: "off" is the next day: the snapshot's day closed (the stop), real money switched off, its cash still at the venue.
HISTORY_OFF: tuple[tuple[int, dict[str, Any]], ...] = ((1, {"pnl_usd": -3.109143229, "settled": 83, "won": 78}),
                                                       (2, YESTERDAY_REAL))
BIG = {"POLYDESK_LIVE_CONTRACTS": "100", "POLYDESK_LIVE_MAX_OPEN_USD": "1000", "POLYDESK_LIVE_DAILY_LOSS_USD": "300",
       "POLYDESK_LIVE_TOTAL_LOSS_USD": "1000"}

#: name -> the situation: the real result today (None: no real book), its bets, whether the desk is live, the
#: practice books' result today (pretend), and the settings that differ.
STATES: dict[str, dict[str, Any]] = {
    "stopped_today": {"today": -3.109143229, "settled": 83, "won": 78, "live": True, "practice": -5.26, "env": {},
                      "about": "today's live snapshot: the daily stop, 78 of 83 won, $5.11 left before real money stops"},
    "tiny": {"today": 0.03, "settled": 1, "won": 1, "live": True, "practice": 1.5, "env": {},
             "about": "up three cents: one real bet, won"},
    "losing": {"today": -0.97, "settled": 1, "won": 0, "live": True, "practice": 2.0, "env": {},
               "about": "down 97 cents, still betting"},
    "bill": {"today": 0.21, "settled": 8, "won": 8, "live": True, "practice": -3.0, "env": {},
             "about": "real money covers the town's bill"},
    "met": {"today": 100.40, "settled": 36, "won": 36, "live": True, "practice": 4.0, "env": BIG,
            "about": "the goal met (100 contracts a bet, so the reach stays consistent)"},
    "double": {"today": 212.00, "settled": 75, "won": 75, "live": True, "practice": -6.0, "env": BIG,
               "about": "more than double the goal"},
    "off": {"today": 0.0, "settled": 0, "won": 0, "live": False, "practice": 500.0, "env": {}, "history": HISTORY_OFF,
            "about": "real money off, $42.43 still in cash at the venue; practice up $500 (pretend)"},
    "practice_only": {"today": None, "settled": 0, "won": 0, "live": False, "practice": 777.77, "env": {},
                      "about": "no real book at all, the desk on paper; practice up $777.77 (pretend)"},
}


def _day(ts: float) -> str:
    return pagestate.utc_day(ts)


def state_settings(name: str, data_dir: str | None = None) -> Settings:
    """The settings the state's words quote (the desk's contracts a bet and its limits)."""
    env = {"DATA_DIR": data_dir or str(Path(tempfile.gettempdir()) / "nightcrawler-goal-states"), **STATES[name]["env"]}
    return Settings.from_env(env)


def _history(name: str) -> tuple[tuple[int, dict[str, Any]], ...]:
    history: tuple[tuple[int, dict[str, Any]], ...] = STATES[name].get("history", HISTORY)
    return history


def state_books(name: str, now: float) -> tuple[dict[str, Any] | None, list[float] | None]:
    """``(live_days, today_pnls)``: the desk's real day book and today's real settlements, in order (adding up to
    today's figure; the snapshot's run went above zero and over the bill before its five losses)."""
    s = STATES[name]
    if s["today"] is None:
        return {}, []
    days = {_day(now - back * DAY): dict(book) for back, book in _history(name)}
    if s["settled"]:
        days[_day(now)] = {"pnl_usd": s["today"], "settled": s["settled"], "won": s["won"]}
    pnls: list[float] = []
    won, lost = s["won"], s["settled"] - s["won"]
    if won and lost:  # wins of 1.9 and 2.8 cents, then the losses share the rest (one after each 20 wins)
        wins = [0.0279776 if i % 2 == 0 else 0.0186378 for i in range(won)]
        loss = (s["today"] - sum(wins)) / lost
        for i, w in enumerate(wins):
            pnls.append(w)
            if (i + 1) % 20 == 0 and len([p for p in pnls if p < 0]) < lost:
                pnls.append(loss)
        pnls += [loss] * (lost - len([p for p in pnls if p < 0]))
    elif won:
        pnls = [s["today"] / won] * won
    elif lost:
        pnls = [s["today"] / lost] * lost
    return days, pnls


def _real_book(name: str, settings: Settings, now: float) -> dict[str, Any] | None:
    s = STATES[name]
    if s["today"] is None:
        return None
    closed = [book for _, book in _history(name)]
    since = sum(float(b["pnl_usd"]) for b in closed) + s["today"]
    daily = float(settings.polydesk_live_daily_loss_usd)
    total_room = float(settings.polydesk_live_total_loss_usd) + min(0.0, since)
    day_room = daily + min(0.0, s["today"])
    return {"label": pagestate.REAL_LABEL, "open": 0, "today_usd": s["today"], "since_start_usd": since,
            "settled_today": s["settled"], "won_today": s["won"],
            "settled_total": sum(int(b["settled"]) for b in closed) + s["settled"],
            "won_total": sum(int(b["won"]) for b in closed) + s["won"],
            "at_risk_usd": 0.0, "contracts": 0.0, "cost_usd": 0.0, "value_usd": 0.0, "venue_at": now - 37,
            "cash_usd": round(DEPOSITS + since, 4), "cash_at": now - 37, "pending": 0, "pending_usd": 0.0,
            "stop_room_usd": min(day_room, total_room), "stop_room_limit": "day" if day_room <= total_room else "total"}


def _guard(live: bool) -> dict[str, Any]:
    book = {"verdict": "learning", "reason": "0 of 30 events needed before judging; so far $0.00, 0 lost",
            "paused": False, "since": None}
    return {**book, "line": "Risk manager (paper, still learning): 0 of 30 events needed before judging.", "on": True,
            "candidate": False, "real": {**book, "line": "Risk manager (real, still learning)."} if live else None}


def apply_state(page: dict[str, Any], name: str, now: float, settings: Settings | None = None) -> dict[str, Any]:
    """A copy of ``page`` in the state ``name`` at ``now``: the desk's books, the practice books, the plain real-money
    words, the risk wall's real caps and the town's bill as the server would have them, then ``town.goal`` and
    ``plain.goal`` recomputed. Pure."""
    s, out = STATES[name], copy.deepcopy(page)
    settings = settings or state_settings(name)
    out["generated_at"] = now
    money = out["money"]
    desk = money.get("polymarket") or {}
    paper = dict(desk.get("paper") or {"label": pagestate.PAPER_LABEL, "open": 0, "today_usd": 0.0,
                                       "since_start_usd": 0.0, "settled_today": 0, "won_today": 0,
                                       "settled_total": 0, "won_total": 0})
    paper["today_usd"] = s["practice"]
    real = _real_book(name, settings, now)
    desk.update({"mode": "live" if s["live"] else "paper", "label": pagestate.REAL_LABEL if s["live"]
                 else pagestate.PAPER_LABEL, "as_of": now - 37, "paper": paper, "real": real,
                 "status": "Daily loss cap reached: no more real buys today." if name == "stopped_today" else None,
                 "guard": _guard(s["live"]), "real_closed": [], "settled_real": [],
                 "skips": {"counts": {}, "sports": {}}, "sports": [], "real_sports_allowed": []})
    money["polymarket"] = desk
    money["today"] = {**(money.get("today") or {}), "usd": s["practice"]}  # the Solana bot: paper, pretend
    if money.get("trend"):
        money["trend"] = {**money["trend"], "today_usd": s["practice"] / 10}
    plain = out["plain"]
    plain["real"] = pagestate._plain_real(settings, money, desk, passed=False)
    plain["headline"] = pagestate._plain_headline(settings, desk, plain["real"])
    for t in plain.get("team") or []:  # each job says which money it handles, as the server words it
        if t.get("id") in pagestate.PLAIN_JOBS:
            t["job"] = pagestate.PLAIN_JOBS[t["id"]].format(desk=pagestate._money_word(s["live"]),
                                                            solana=pagestate._money_word(settings.is_live))
            t["plain_role"] = f"{t['name']} {t['job']}"
    for m in out["team"]["members"]:
        if m["id"] == "risk" and isinstance(m.get("risk_wall"), dict):
            m["risk_wall"]["real_caps"] = pagestate.real_caps(settings, desk)
        if m["id"] == "predict" and "label" in m:  # the desk's ticket board says which money it bets
            m["label"] = desk["label"]
    out["town"]["cost_per_day_usd"] = 5.0 / 30.0  # the real bill: the $5 hosting plan, no judge spend today
    out["town"]["polymarket"] = pagestate._desk_lines(desk)  # the town card's desk lines, paper and real apart
    summary = out["trades"]["summary"]
    summary["real"] = None if real is None else {
        "label": pagestate.REAL_LABEL, "won": real["won_total"], "lost": real["settled_total"] - real["won_total"],
        "settled": real["settled_total"], "since": now - DAY - 9000, "order": "W" * real["won_total"],
        "lines": [], "result": pagestate._change(real["since_start_usd"], real=True)}
    live_days, pnls = state_books(name, now)
    out["town"]["goal"], plain["goal"] = pagestate.town_goal_block(settings, out, now, live_days=live_days,
                                                                   today_pnls=pnls)
    return out


def base_page(now: float = SNAPSHOT_AT) -> dict[str, Any]:
    """The page the screenshot harness's server builds (tests/test_page.py's two seeded days), at its own clock."""
    from fakes import FakeClock
    from test_page import NOW, seed

    from nightcrawler.ledger import Ledger

    tmp = Path(tempfile.mkdtemp())
    settings = Settings.from_env({"DATA_DIR": str(tmp)})
    with Ledger(tmp / "nc.db", clock=FakeClock(NOW)) as ledger:
        seed(ledger)
        return pagestate.build_page_state(ledger, settings, NOW)


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path("goal_states")
    target.mkdir(parents=True, exist_ok=True)
    base = base_page()
    for name in STATES:
        page = apply_state(base, name, SNAPSHOT_AT)
        (target / f"{name}.json").write_text(json.dumps(page, allow_nan=False), encoding="utf-8")
        print(name, page["plain"]["goal"]["strip"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
