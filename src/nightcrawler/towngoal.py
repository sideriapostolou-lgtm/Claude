"""The town's goal (the 3D world's goal tower): ``/api/page`` -> ``town.goal`` (numbers) and ``plain.goal`` (words).

Two true numbers on one ladder:

* The town's BILL is what really keeps the town running: ``town.cost_per_day_usd`` (the hosting plan plus the AI
  judge, :func:`nightcrawler.pagestate.town_ledger`), a whole day's rate. While real money today does not cover it the
  owner pays it, and the world shows the town on the owner's backup power; once real money covers it, on its own.
* The owner's GOAL for the team is ``TOWN_GOAL_USD`` real dollars a day (default 100), and more is better. It is always
  worded as the owner's goal for the team, never as a cost, an upkeep or what the town needs to survive.

The ladder's rungs (above zero, covers the bill, 1 %, 10 %, the goal, 1.5x, 2x, 3x of it) light on REAL money only, by
the cent: the Polymarket desk's real book (``money.polymarket.real``) and the Solana bot's own while it runs live.
Practice (pretend money) is shown apart, labelled pretend, and never counts toward the goal or powers the town; real
and pretend figures are never added. The day is the desk's own UTC day (the one its daily loss stop uses); the day
history and the streaks come from the desk's own day book (``live_days``) only when it agrees with the money card to
the cent, and the embers ("reached earlier today") from today's real settlement receipts only when they add up to
today's figure.

DISPLAY ONLY: nothing here changes a bet size, a limit or a rule, and no desk reads it. This module imports the
standard library only (a test checks it), and its functions are pure: :mod:`nightcrawler.pagestate` gathers the
inputs (:func:`nightcrawler.pagestate.goal_inputs`), passes its own money formatters and inserts the result as data;
the page shows the words as text only. Every sentence is a FIXED template below filled with the page's own figures
(or values derived from them here); a template whose figure is missing is dropped (``None``), never "$0.00".
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

__all__ = ["CHECK_IN_MAX", "DEFAULT_GOAL_USD", "GOAL_MAX_USD", "GOAL_MIN_USD", "MOODS", "PRETEND_TAG", "REAL_TAG",
           "RUNG_ORDER", "day_words", "goal_words", "parse_goal", "town_goal"]

log = logging.getLogger(__name__)

#: The goal when the setting cannot be read: the owner's own number.
DEFAULT_GOAL_USD = 100.0
GOAL_MIN_USD = 1.0
GOAL_MAX_USD = 1_000_000.0
DAY_S = 86_400.0
#: The check-in's beats at most (the tower, the power, Voss, Rook, the reach, Mote).
CHECK_IN_MAX = 6
#: Closed days kept in ``town.goal.days`` (newest first) and lines of them in words.
DAYS_MAX = 14
DAY_LINES_MAX = 7
#: Figures agree when they are this close (a cent; float noise aside).
_AGREE = 0.01 + 1e-9
LABEL = "The team's goal (real money only)"
PRACTICE_LABEL = "Practice (pretend money)"
#: The programme cards' tags: the goal's own beats are real money; the practice crew's are pretend.
REAL_TAG = "THE GOAL · REAL MONEY"
PRETEND_TAG = "PRACTICE · PRETEND MONEY"
#: The rungs, in this order where two stand at the same height.
RUNG_ORDER = ("zero", "bill", "one", "ten", "goal", "great", "double", "triple")
#: The team's mood, first match wins (``unknown``: the page cannot tell what real money did today).
MOODS = ("stopped_for_good", "unknown", "off", "stand_down", "waiting", "goal", "own_power", "climb")
_GOAL_TEXT = re.compile(r"\s*\$?\s*(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*")
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_DAY_KEY = re.compile(r"\d{4}-\d{2}-\d{2}")
#: The risk manager's verdicts in the owner's words (deskguard's own phrases; "winning" is the road's step done).
_VERDICT_WORDS = {"learning": "still learning", "losing": "losing", "unclear": "not proven yet"}
_warned: set[str] = set()
_WARN_MAX = 32

Fmt = Callable[[float], str]


# =========================================================================== the setting


def parse_goal(raw: Any) -> tuple[float, bool]:
    """``TOWN_GOAL_USD`` read leniently: ``(dollars, True)`` for "$100", "100", "1,000" or "250.50" within 1 to
    1,000,000; anything else (unreadable, out of range, empty) is ``(100.0, False)`` with one log line
    (``town_goal_bad``) per value. It never raises: the setting can never stop the bot."""
    text = raw if isinstance(raw, str) else ""
    found = _GOAL_TEXT.fullmatch(text)
    if found is not None:
        value = float(found.group(1).replace(",", "") + (found.group(2) or ""))
        if math.isfinite(value) and GOAL_MIN_USD <= value <= GOAL_MAX_USD:
            return value, True
    key = text[:60]
    if key not in _warned and len(_warned) < _WARN_MAX:
        _warned.add(key)
        log.warning("town_goal_bad value=%r using=%s", key, DEFAULT_GOAL_USD)
    return DEFAULT_GOAL_USD, False


# =========================================================================== small helpers


def _num(value: Any) -> float | None:
    """A finite number (bool is not one), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _int(value: Any) -> int:
    number = _num(value)
    return int(number) if number is not None and number >= 0 else 0


def _cents(value: float) -> float:
    cents = round(value, 2)
    return 0.0 if cents == 0 else cents


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _whole(value: float) -> str:
    """Dollars, whole when whole (``$100``, ``$1.50``): the target and the rungs it makes."""
    return f"${value:,.0f}" if abs(value - round(value)) < 0.005 else f"${value:,.2f}"


def _day_of(ts: float) -> str:
    """The UTC day of ``ts`` (the Polymarket desk's own day: its daily loss stop's)."""
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")


def _date(day: str) -> datetime:
    return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)


def day_words(day: str) -> str:
    """``2026-10-09`` as ``Fri 9 Oct`` (fixed English names: the page's words do not follow the server's locale)."""
    d = _date(day)
    return f"{_WEEKDAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]}"


def _days_between(a: str, b: str) -> int:
    return (_date(b) - _date(a)).days


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".!?:" else text + "."


# =========================================================================== town.goal (numbers)


def _rungs(target: float, bill: float, whole: Fmt) -> list[dict[str, Any]]:
    specs = [("zero", "Above zero", 0.01), ("bill", "Covers the bill", bill),
             ("one", f"{whole(target * 0.01)} a day", target * 0.01),
             ("ten", f"{whole(target * 0.10)} a day", target * 0.10),
             ("goal", f"The goal: {whole(target)} a day", target),
             ("great", f"Great day: {whole(target * 1.5)}", target * 1.5),
             ("double", f"Double the goal: {whole(target * 2)}", target * 2.0),
             ("triple", f"Triple the goal: {whole(target * 3)}", target * 3.0)]
    rows = [{"id": rid, "name": name, "usd": round(usd, 4), "lit": False, "reached": False, "above_goal": usd > target}
            for rid, name, usd in specs if rid != "bill" or bill > 0.01]
    rows.sort(key=lambda r: (r["usd"], RUNG_ORDER.index(r["id"])))
    return rows


def _day_rows(live_days: Any) -> dict[str, Mapping[str, Any]]:
    rows: dict[str, Mapping[str, Any]] = {}
    for key, row in _map(live_days).items():
        if isinstance(key, str) and _DAY_KEY.fullmatch(key) and isinstance(row, Mapping) and _num(row.get("pnl_usd")) is not None:
            rows[key] = row
    return rows


def _history(rows: Mapping[str, Mapping[str, Any]], real: Mapping[str, Any], day: str, bill: float,
             target: float) -> tuple[list[dict[str, Any]] | None, dict[str, int] | None, dict[str, Any] | None]:
    """``(days, streaks, best_day)`` from the desk's own day book, or all None unless it agrees with the money card
    (the sum of its days with the real result since start, and today's row with today's, each to the cent)."""
    since, today = _num(real.get("since_start_usd")), _num(real.get("today_usd"))
    if since is None or today is None:
        return None, None, None
    total = sum(float(r["pnl_usd"]) for r in rows.values())
    today_row = _num(_map(rows.get(day)).get("pnl_usd")) or 0.0
    if abs(total - since) > _AGREE or abs(today_row - today) > _AGREE:
        return None, None, None
    closed = sorted((k for k in rows if k < day), reverse=True)
    days: list[dict[str, Any]] = []
    for key in closed[:DAYS_MAX]:
        r = rows[key]
        usd = _cents(float(r["pnl_usd"]))
        days.append({"day": key, "real_usd": usd, "settled": _int(r.get("settled")), "won": _int(r.get("won")),
                     "bill_covered": usd >= bill if bill > 0 else None, "goal_met": usd >= target})
    streaks = {"up": 0, "bill": 0, "goal": 0}
    on = {"up": True, "bill": bill > 0, "goal": True}
    d = _date(day) - timedelta(days=1)
    for _ in range(len(rows) + 1):
        row = rows.get(d.strftime("%Y-%m-%d"))
        if row is None or not _int(row.get("settled")):  # a day without a real settlement breaks every streak
            break
        usd = _cents(float(row["pnl_usd"]))
        for name, ok in (("up", usd > 0), ("bill", bill > 0 and usd >= bill), ("goal", usd >= target)):
            if on[name] and ok:
                streaks[name] += 1
            else:
                on[name] = False
        if not any(on.values()):
            break
        d -= timedelta(days=1)
    best = max(days, key=lambda r: float(r["real_usd"]), default=None)
    best_day = ({"day": best["day"], "real_usd": best["real_usd"]} if best is not None and float(best["real_usd"]) > 0
                else None)
    return days, streaks, best_day


def _peak(pnls: Any, today: float) -> float | None:
    """The running high of today's real settlements in their order (from 0), or None unless they add up to today's
    figure to the cent."""
    if not isinstance(pnls, list):
        return None
    run = best = 0.0
    for p in pnls:
        value = _num(p)
        if value is None:
            return None
        run += value
        best = max(best, run)
    return _cents(best) if abs(run - today) <= _AGREE else None


def _crew_road(ready: Any) -> dict[str, Any] | None:
    """The Solana bot's road to real money (``ready``): its step labels and whether each is done, never a reason."""
    r = _map(ready)
    items = r.get("items")
    total, done = _num(r.get("total")), _num(r.get("done"))
    if not isinstance(items, list) or total is None or done is None:
        return None
    steps = [{"label": str(_map(i).get("label") or ""), "done": _map(i).get("done") is True} for i in items[:int(total)]]
    return {"done": int(done), "total": int(total), "steps": [s for s in steps if s["label"]]}


def town_goal(inp: Mapping[str, Any], *, whole: Fmt = _whole) -> dict[str, Any]:
    """``town.goal``: the ladder, the bill, the floor and the lifeline, the mood, the days and the road, from the
    inputs :func:`nightcrawler.pagestate.goal_inputs` gathers (the page's own figures). Pure; never a made-up figure:
    what is not known is None."""
    target, target_ok = inp["target"]
    now = float(inp["now"])
    day = str(inp.get("day") or _day_of(now))
    start = now - now % DAY_S
    real = inp.get("real") if isinstance(inp.get("real"), Mapping) else None
    solana_live = inp.get("solana_live") is True
    bill = max(0.0, _num(inp.get("bill")) or 0.0)
    real_on, reported = inp.get("real_on") is True, inp.get("reported") is not False
    paused_kind = inp.get("paused_kind") if inp.get("paused_kind") in ("risk", "day", "full", "room") else None

    parts: list[dict[str, Any]] = []
    raw: list[float | None] = []
    if real is not None:
        value = _num(real.get("today_usd"))
        raw.append(value)
        parts.append({"id": "polymarket", "label": "Polymarket desk (real money)",
                      "today_usd": _cents(value) if value is not None else None,
                      "settled": _int(real.get("settled_today")), "won": _int(real.get("won_today"))})
    if solana_live:
        value = _num(inp.get("solana_today_usd"))
        raw.append(value)
        parts.append({"id": "solana", "label": "Solana bot (real money)",
                      "today_usd": _cents(value) if value is not None else None})
    known = bool(raw) and all(v is not None for v in raw)
    today = _cents(sum(v for v in raw if v is not None)) if known else None

    caps = _map(inp.get("caps"))
    floor = lifeline = None
    if caps:
        floor = {"day_loss_usd": _num(caps.get("day_loss_usd")) or 0.0, "day_max_usd": _num(caps.get("day_max_usd")) or 0.0,
                 "hit": paused_kind == "day"}
        lost, most = _num(caps.get("total_loss_usd")) or 0.0, _num(caps.get("total_max_usd")) or 0.0
        left = max(0.0, _cents(most - lost))
        lifeline = {"lost_usd": lost, "max_usd": most, "left_usd": left,
                    "segments_lit": round(10 * left / most) if most > 0 else 0}

    if lifeline is not None and lifeline["left_usd"] <= 0:
        mood = "stopped_for_good"
    elif not reported:
        mood = "unknown"
    elif not real_on:
        mood = "off"
    elif paused_kind in ("risk", "day"):
        mood = "stand_down"
    elif paused_kind in ("full", "room"):
        mood = "waiting"
    elif today is None:
        mood = "unknown"
    elif today >= target:
        mood = "goal"
    elif bill > 0 and today >= bill:
        mood = "own_power"
    else:
        mood = "climb"
    live = mood not in ("stopped_for_good", "unknown", "off") and today is not None

    peak = None
    if real is not None and not solana_live and parts[0]["today_usd"] is not None:
        peak = _peak(inp.get("today_pnls"), float(_num(real.get("today_usd")) or 0.0))
    rungs = _rungs(target, bill, whole)
    for r in rungs:
        r["lit"] = live and today is not None and today >= r["usd"]
        r["reached"] = live and (r["lit"] or (peak is not None and peak >= r["usd"]))
    lit = [i for i, r in enumerate(rungs) if r["lit"]]

    if mood in ("stopped_for_good", "off"):
        tier: dict[str, Any] = {"id": "off", "rank": None, "name": "Real money is off"}
    elif mood == "unknown" or today is None:
        tier = {"id": "unknown", "rank": None, "name": "Not known yet"}
    elif today < 0:
        tier = {"id": "below", "rank": -1, "name": "Below zero"}
    elif not lit:
        tier = {"id": "even", "rank": 0, "name": "Even"}
    else:
        top = rungs[lit[-1]]
        tier = {"id": top["id"], "rank": lit[-1] + 1, "name": top["name"]}
    nxt = None
    if live and today is not None:
        up = next((r for r in rungs if not r["lit"]), None)
        if up is not None:
            nxt = {"id": up["id"], "name": up["name"], "usd": up["usd"], "gap_usd": _cents(up["usd"] - today)}

    # the bill is a WHOLE day's rate, compared by the cent with today's real result (the figure the page shows)
    # (only once real money reported today: an unreported figure covers nothing)
    covered = today >= bill if today is not None and bill > 0 and reported else None
    share = max(0.0, min(1.0, today / bill)) if today is not None and bill > 0 and reported else None
    if not reported or bill <= 0:
        power = None
    elif covered is True:
        power = "own"
    elif covered is False or not real_on:
        power = "backup"  # the owner pays the bill today
    else:
        power = None  # real money is on but today's result is not known: neither claim

    settled_today = parts[0]["settled"] if real is not None else 0
    contracts, theta = _num(inp.get("contracts")) or 0.0, _num(inp.get("theta")) or 0.0
    reach = None
    if settled_today > 0 and contracts > 0 and 0 < theta < 1:
        win_max = round(contracts * (1.0 - theta), 4)
        reach = {"win_max_per_bet_usd": _cents(win_max), "best_case_today_usd": _cents(settled_today * win_max),
                 "loss_min_per_bet_usd": _cents(contracts * theta)}

    rows = _day_rows(inp.get("live_days"))
    days = streaks = best_day = None
    if real is not None and inp.get("live_days") is not None:
        days, streaks, best_day = _history(rows, real, day, bill, target)
    day_n = None
    if rows:
        day_n = _days_between(min(rows), day) + 1
    elif _num(inp.get("first_real_ts")) is not None:
        day_n = _days_between(_day_of(float(inp["first_real_ts"])), day) + 1
    if day_n is not None and day_n < 1:
        day_n = None

    cash = _num(real.get("cash_usd")) if real is not None else None
    guard = _map(inp.get("guard_real"))
    practice = _map(inp.get("practice"))

    def pretend(key: str) -> float | None:
        value = _num(practice.get(key))
        return _cents(value) if value is not None else None

    return {
        "label": LABEL,
        "target_usd": target, "target_ok": bool(target_ok),
        "is_cost": False,
        "counts": "real money only",
        "day": day, "day_start": start, "day_end": start + DAY_S,
        "day_n": day_n,
        "real_on": real_on,
        "real_today_usd": today,
        "parts": parts,
        "peak_today_usd": peak,
        "bill_per_day_usd": round(bill, 4),
        "bill_covered_by_real": covered,
        "bill_share_real": share,
        "power": power,
        "rungs": rungs,
        "progress": {"lit": len(lit), "of": len(rungs)},
        "tier": tier,
        "next": nxt,
        "beyond_usd": _cents(today - target) if today is not None and today > target and live else None,
        "floor": floor,
        "lifeline": lifeline,
        "reserve": {"cash_usd": cash, "at": _num(real.get("cash_at")) if real is not None else None}
        if cash is not None else None,
        "reach": reach,
        "mood": mood,
        "stand_down": paused_kind if mood == "stand_down" else None,
        "days": days,
        "streaks": streaks,
        "best_day": best_day,
        "road": [{"id": "lab", "done": inp.get("rule_lab_passed") is True},
                 {"id": "record", "done": guard.get("verdict") == "winning"},
                 {"id": "owner", "done": None}],
        "practice": {"label": PRACTICE_LABEL, "counts_toward_goal": False,
                     "solana_today_usd": pretend("solana_today_usd") if not solana_live else None,
                     "polymarket_today_usd": pretend("polymarket_today_usd"),
                     "trend_today_usd": pretend("trend_today_usd"),
                     "crew_road": _crew_road(inp.get("ready"))},
    }


# =========================================================================== plain.goal (words)


def _per_bet(contracts: float) -> str:
    """How much one bet is, from the desk's setting: "One contract a bet", "100 contracts a bet"."""
    return "One contract a bet" if contracts == 1 else f"{contracts:g} contracts a bet"


def _lower(text: str) -> str:
    return text[:1].lower() + text[1:]


def _won_of(won: int, settled: int, noun: str = "bets") -> str:
    return f"{won} of {settled} {noun if settled != 1 else noun[:-1]} won"


def _beat(who: str, tag: str, text: str | None) -> dict[str, str] | None:
    return {"who": who, "tag": tag, "text": text} if text else None


def goal_words(goal: Mapping[str, Any], inp: Mapping[str, Any], *, dollars: Fmt, signed: Fmt,
               limit: Fmt = _whole) -> dict[str, Any]:
    """``plain.goal``: the goal in plain words for the 3D world, each a fixed template filled from ``goal``
    (:func:`town_goal`) and the same inputs, money in the page's own wording (``dollars``, ``signed``; ``limit`` a cap
    or the target, whole when whole). Pure. ``{local_reset}`` is the one token the page fills (the day's end on the
    viewer's clock)."""
    target = float(goal["target_usd"])
    T = limit(target)
    bill = float(goal["bill_per_day_usd"] or 0.0)
    bill_txt = dollars(bill)
    mood, tier, nxt = goal["mood"], goal["tier"], goal["next"]
    today = goal["real_today_usd"]
    poly = next((p for p in goal["parts"] if p["id"] == "polymarket"), None)
    settled, won = (poly["settled"], poly["won"]) if poly else (0, 0)
    contracts = _num(inp.get("contracts")) or 1.0
    per = _per_bet(contracts)
    paused = inp.get("paused") if isinstance(inp.get("paused"), str) and inp.get("paused") else None
    floor, lifeline, reach = goal["floor"], goal["lifeline"], goal["reach"]
    limits = _map(inp.get("limits"))
    solana_live = inp.get("solana_live") is True
    crew_kind = "real money" if solana_live else "pretend money"
    crew_tag = REAL_TAG if solana_live else PRETEND_TAG

    figure = signed(today) if today is not None else None
    if mood in ("off", "stopped_for_good"):
        strip_figure = strip_short = "real money is off"
    elif figure is None or mood == "unknown":
        strip_figure = strip_short = "real money: not known yet"
    else:
        strip_figure, strip_short = f"{figure} real today", f"{figure} real"
    strip_label, strip_label_short = f"Goal {T}/day", f"Goal {T}"
    if mood in ("off", "stopped_for_good"):
        aria_today = "Today: real money is off."
    elif figure is None or mood == "unknown":
        aria_today = "Today: not known yet."
    else:
        cents = float(today or 0.0)
        way = "up" if cents > 0 else "down" if cents < 0 else "even"
        aria_today = f"Today: {way} {dollars(cents)}, real money." if way != "even" else "Today: even, real money."
    today_words = f"{figure} real money today" if figure is not None and mood not in ("off", "stopped_for_good", "unknown") else None
    head = f"The owner's goal for the team: {T} a day in real money."
    next_words = f" Next light: {nxt['name']}, {dollars(nxt['gap_usd'])} away." if nxt else ""
    # the embers: rungs today's real settlements reached earlier, not lit now (the tower draws them dim amber)
    peak = goal["peak_today_usd"]
    ember_line = None
    if (peak is not None and figure is not None and peak > max(0.0, float(today or 0.0))
            and any(r["reached"] and not r["lit"] for r in goal["rungs"])):
        ember_line = (f"Earlier today real money was up to {signed(peak)}; it is {figure} now. Amber rings: reached "
                      "earlier today, not lit now. Only what real money holds now lights a ring.")

    # ---- the main line, by mood
    if mood == "off":
        line = f"{head} Real money is off right now, so the goal waits; practice never counts toward it."
    elif mood == "stopped_for_good":
        line = (f"{head} Real money has stopped for good after {dollars(lifeline['lost_usd'])} lost in total (the limit "
                f"is {limit(lifeline['max_usd'])}); only the owner can start it again." if lifeline else head)
    elif mood == "unknown" or figure is None:
        line = f"{head} Today's real result is not known yet."
    elif mood == "stand_down":
        why = ("stopped at the daily limit" if goal["stand_down"] == "day"
               else "the risk manager has paused real bets")
        # (no "next light": no bet can reach one before the stop lifts)
        line = (f"{head} Today so far: {figure} (real money), {why}. Rules first: we don't chase a loss. The rings "
                "start again at midnight UTC.")
    elif mood == "waiting":
        line = f"{head} Today so far: {figure} (real money), waiting for room under the limits. Rules first.{next_words}"
    elif mood == "goal":
        beyond = goal["beyond_usd"]
        past = f" and {dollars(beyond)} past it" if beyond else ""
        line = (f"{head} Today: {figure} in real money: the goal is met{past}. More is better; the limits stay the "
                "same.")
    elif not settled and not solana_live:
        line = f"{head} No real bet has finished today yet. First light: Above zero."
    else:
        lit = f" Lit: {tier['name']}." if (tier.get("rank") or 0) >= 1 else " No light is lit yet."
        done = f", {_won_of(won, settled, 'finished bets')}" if settled else ""
        line = f"{head} Today so far: {figure} (real money){done}.{lit}{next_words}"

    # ---- the bill, the plaque, the stops, the reserve, the reach
    covered, power = goal["bill_covered_by_real"], goal["power"]
    if bill <= 0:
        bill_line, plaque = "The town has no hosting bill right now.", "today: no hosting bill"
    else:
        lead = f"The town's bill: {bill_txt} a day to run (hosting and the AI judge, real costs)."
        if covered is True:
            bill_line, plaque = f"{lead} Real money covered it today.", "today: covered by real money"
        elif power == "backup":
            bill_line, plaque = (f"{lead} Today the owner pays it: the town runs on the owner's backup power.",
                                 "today: paid by the owner")
        else:
            bill_line, plaque = f"{lead} Whether real money covers it today is not known yet.", "today: not known yet"
    # the owner's backup generator (the bill's other half: who keeps the lights on today)
    if power == "backup":
        power_line: str | None = (f"The owner's backup generator is running: real money has not covered today's "
                                  f"{bill_txt} bill yet.")
    elif power == "own":
        power_line = (f"Real money covered today's {bill_txt} bill: the generator is off, the lights are gold and the "
                      "stalls are open.")
    else:
        power_line = None
    floor_line = None
    if floor:
        loss, most = floor["day_loss_usd"], floor["day_max_usd"]
        if not floor["hit"]:
            floor_line = f"Today's real loss stop: {dollars(loss)} used of {limit(most)}."
        elif loss > most + 0.005:  # (what the stop does: no new bet; the bets already open settled past it)
            floor_line = (f"Today's real loss stop is {limit(most)}: it ended new real bets for today, and with the "
                          f"bets already open settled, today's real loss is {dollars(loss)}.")
        else:
            floor_line = (f"Today's real loss stop is {limit(most)}: it ended new real bets for today, at "
                          f"{dollars(loss)} lost.")
    lifeline_line = (f"Real money stops for good after {limit(lifeline['max_usd'])} lost in total: "
                     f"{dollars(lifeline['lost_usd'])} lost so far, {dollars(lifeline['left_usd'])} of room left."
                     if lifeline else None)
    reserve = goal["reserve"]
    reserve_line = (f"Real cash at Polymarket: {dollars(reserve['cash_usd'])} (the owner's deposits plus the results; a "
                    "deposit is not a gain)." if reserve else None)
    reach_line = None
    if reach:
        best = dollars(reach["best_case_today_usd"])
        if won >= settled:  # (every one won: never "even if they had won")
            first = (f"Today's one real bet won: {best} is the most it could make, since" if settled == 1
                     else f"All {settled} of today's real bets won: {best} is the most they could make, since")
        else:
            first = (f"Even if today's one real bet had won, it could have made at most {best}:" if settled == 1
                     else f"Even if all {settled} of today's real bets had won, they could have made at most {best}:")
        # the rule buys at its price or above: a win pays at most the rest of a dollar a contract, a loss the price
        reach_line = (f"{first} a win pays at most {dollars(reach['win_max_per_bet_usd'])} a bet ({_lower(per)}), "
                      f"while a loss costs the whole price, {dollars(reach['loss_min_per_bet_usd'])} or more."
                      + (" More than this takes a proven edge, not bigger bets." if mood == "goal"
                         else f" Reaching the {T} goal takes a proven edge, not bigger bets."))

    # ---- the days
    day_n, days, streaks, best = goal["day_n"], goal["days"], goal["streaks"], goal["best_day"]
    streak_line = None
    if day_n is not None:
        streak_line = (f"Day {day_n} on real money. In a row (closed days, UTC): up {streaks['up']}, bill covered "
                       f"{streaks['bill']}, goal met {streaks['goal']}." if streaks is not None
                       else f"Day {day_n} on real money. History not available.")
    day_lines = [f"{day_words(d['day'])} (UTC): {signed(d['real_usd'])}, {_won_of(d['won'], d['settled'])}"
                 for d in (days or [])[:DAY_LINES_MAX]]
    best_line = f"Best real day so far: {signed(best['real_usd'])} on {day_words(best['day'])} (UTC)." if best else None
    result = None
    if days is not None and streaks is not None and day_n is not None and day_n >= 2:
        yesterday = (_date(goal["day"]) - timedelta(days=1)).strftime("%Y-%m-%d")
        title = f"Day {day_n - 1} closed · {day_words(yesterday)} (the desk's day, UTC)"
        streak = (f"In a row now: up {streaks['up']}, bill covered {streaks['bill']}, goal met {streaks['goal']}.")
        if days and days[0]["day"] == yesterday:
            y = days[0]
            bill_word = ("no hosting bill" if y["bill_covered"] is None else "yes" if y["bill_covered"] else "no")
            result = {"day": yesterday, "title": title, "figure": f"{signed(y['real_usd'])} real money",
                      "line": (f"Real money that day: {signed(y['real_usd'])}, {_won_of(y['won'], y['settled'])}. "
                               f"Bill covered: {bill_word}. Goal: {'met' if y['goal_met'] else 'not met'}."),
                      "streak": streak}
        else:
            result = {"day": yesterday, "title": title, "figure": "no real bet finished",
                      "line": "No real bet finished that day.", "streak": streak}

    # ---- the road to the goal
    road = {r["id"]: r["done"] for r in goal["road"]}
    guard = _map(inp.get("guard_real"))
    # the risk manager's count only (its first part: counts and money), on the rule in use now; never its statistics
    counted = str(guard.get("reason") or "").split(";")[0].strip().rstrip(".")
    phrase = _VERDICT_WORDS.get(str(guard.get("verdict") or ""), "")
    scope = f"{phrase} on the rule in use now" if phrase else "on the rule in use now"
    road_lines = [
        f"1. A rule passes the lab's test for a real edge: {'done' if road.get('lab') else 'not yet'}.",
        "2. Its real record is judged winning by the risk manager: "
        + ("done." if road.get("record") else f"not yet ({scope}: {counted})." if counted else "not yet."),
        "3. Only then can the owner decide on bigger limits. The goal never decides it.",
    ]

    # ---- practice (pretend money): apart, never counted; each book named for its own period
    pr = goal["practice"]
    books = [(pr["solana_today_usd"], "the Solana bot today"),
             (pr["polymarket_today_usd"], "Polymarket practice today"),
             (pr["trend_today_usd"], "the trend desk's last day")]
    named = [f"{who} {signed(v)} (pretend)" for v, who in books if v is not None]
    practice_line = "Practice (pretend money) never counts toward the goal or powers the town"
    practice_line += (": " + ", ".join(named) + ".") if named else "."
    road_crew = pr["crew_road"]
    crew_road_line = None
    if road_crew:
        unlisted = road_crew["total"] > len(road_crew["steps"])  # (the checklist's security steps stay off the world)
        crew_road_line = (f"Road to real money for the Solana bot: {road_crew['done']} of {road_crew['total']} "
                          "steps done" + (" (the security steps are not listed here)." if unlisted else "."))

    honest = (f"The {T} is the owner's goal for the team, not a cost: "
              + (f"the town costs {bill_txt} a day to run, and the owner pays it until real money does."
                 if bill > 0 else "the town has no hosting bill right now.")
              + " Only real money counts toward the goal, and the goal changes no bet size, limit or rule.")
    postcard = f"Goal {T}/day (the owner's, real money only) · {strip_figure}" + (
        f" · the town's bill {bill_txt}/day" if bill > 0 else "")

    # ---- each character's line for the current mood
    lines = {
        "voss": _voss(mood, goal, T, figure, settled, won, per, paused, nxt, dollars, limit, lifeline, solana_live),
        "rook": _rook(mood, goal, T, per, paused, floor, lifeline, limits, dollars, limit),
        "pip": _pip(inp.get("said_crawler"), crew_kind),
        "nyx": _nyx(inp.get("radar_doing"), crew_kind),
        "jet": _jet(inp, crew_kind, signed),
        "mote": _mote(_map(inp.get("receipts"))),
    }

    # the tower's beat says what amber means when it shows; the power beat films the generator while it runs, the
    # open stalls once real money covers the bill
    tower = " ".join(t for t in (line, ember_line) if t)
    power_at = "promenade" if power == "own" else "power"
    check_in = [b for b in (_beat("tower", REAL_TAG, tower), _beat(power_at, REAL_TAG, power_line),
                            _beat("voss", REAL_TAG, lines["voss"]), _beat("rook", REAL_TAG, lines["rook"]),
                            _beat("voss", REAL_TAG, reach_line), _beat("mote", REAL_TAG, lines["mote"]))
                if b][:CHECK_IN_MAX]
    vault = " ".join(t for t in (lifeline_line, floor_line, reserve_line) if t) or None
    yard = " ".join(t for t in (practice_line, crew_road_line) if t) or None
    tour = [b for b in (_beat("tower", REAL_TAG, tower), _beat("bill", REAL_TAG, bill_line),
                        _beat(power_at, REAL_TAG, power_line),
                        _beat("vault", REAL_TAG, vault), _beat("board", REAL_TAG, streak_line),
                        _beat("yard", PRETEND_TAG, yard), _beat("voss", REAL_TAG, lines["voss"]),
                        _beat("rook", REAL_TAG, lines["rook"]), _beat("pip", crew_tag, lines["pip"]),
                        _beat("nyx", crew_tag, lines["nyx"]), _beat("jet", crew_tag, lines["jet"]),
                        _beat("mote", REAL_TAG, lines["mote"])) if b]
    return {
        "label": "The team's goal",
        "target_text": T, "bill_text": bill_txt,
        "strip_label": strip_label,
        "strip_label_short": strip_label_short,
        "strip_figure": strip_figure,
        "strip_figure_short": strip_short,
        "strip": f"{strip_label} · {strip_figure}",
        "aria": " ".join(t for t in (f"The owner's goal: {T} a day in real money.", aria_today, ember_line,
                                     "Tap for details.") if t),
        "today": today_words,
        "line": line,
        "ember_line": ember_line,
        "bill_line": bill_line,
        "power_line": power_line,
        "plaque_line": plaque,
        "floor_line": floor_line,
        "lifeline_line": lifeline_line,
        "reserve_line": reserve_line,
        "reach_line": reach_line,
        "streak_line": streak_line,
        "day_lines": day_lines,
        "best_line": best_line,
        "road_lines": road_lines,
        "practice_line": practice_line,
        "crew_road_line": crew_road_line,
        "honest": honest,
        "postcard": postcard,
        "result": result,
        "lines": lines,
        "programmes": {"check_in": check_in, "tour": tour},
    }


def _voss(mood: str, goal: Mapping[str, Any], T: str, figure: str | None, settled: int, won: int, per: str,
          paused: str | None, nxt: Mapping[str, Any] | None, dollars: Fmt, limit: Fmt,
          lifeline: Mapping[str, Any] | None, solana_live: bool) -> str | None:
    """Voss (the Polymarket desk, real money): the current mood in his own words, careful and on the rules."""
    gap = f"Next light: {nxt['name']}, {dollars(nxt['gap_usd'])} away." if nxt else None
    if mood == "off":
        return f"Real money is off, so the goal waits. Practice keeps me sharp, but it never counts toward the {T} goal."
    if mood == "stopped_for_good":
        lost = dollars(lifeline["lost_usd"]) if lifeline else None
        return (f"Real money has stopped for good: {lost} lost, the limit I keep. Only the owner can start it again; "
                "the goal waits." if lost else None)
    if mood == "unknown" or figure is None:
        return f"The goal: {T} a day, real money only. Today's real result is not known yet, so I wait for the books."
    if mood == "stand_down" and goal["stand_down"] == "day":
        return (f"Real money today: {figure}, {_won_of(won, settled)}. The daily stop ended my day, and I don't chase "
                "it back. I bet again after midnight UTC ({local_reset} your time). The goal stays " + T + " a day.")
    if mood == "stand_down":
        return (f"The risk manager paused my real bets, and I wait: {_sentence(paused or 'paused for now')} I don't "
                f"chase it. The goal stays {T} a day.")
    if mood == "waiting":
        return f"Not betting for now: {_sentence(paused)}" if paused else None
    if mood == "goal":
        beyond = goal["beyond_usd"]
        if beyond:
            return (f"{figure} in real money today: {dollars(beyond)} past the owner's goal. More is better, with the "
                    "same limits.")
        return (f"Goal reached: {figure} in real money today. {per}, as on every day: I don't raise the stakes on a good "
                "day.")
    if mood == "own_power":
        return (f"Real money today: {figure}, and it covers the town's bill. Same rule, same size."
                + (f" {gap}" if gap else ""))
    if not settled and not solana_live:
        return f"No real bet has finished today yet. The goal: {T} a day, real money only. {per}, every bet: same size, same rule."
    done = f" ({won} of {settled} won)" if settled else ""
    return (f"Real money today: {figure}{done}." + (f" {gap}" if gap else "")
            + f" {per}: I don't raise the size to get there.")


def _rook(mood: str, goal: Mapping[str, Any], T: str, per: str, paused: str | None, floor: Mapping[str, Any] | None,
          lifeline: Mapping[str, Any] | None, limits: Mapping[str, Any], dollars: Fmt, limit: Fmt) -> str | None:
    """Rook (the risk manager): the limits first, the goal second."""
    if mood == "stand_down" and goal["stand_down"] == "day" and floor:
        left = (f" {dollars(lifeline['left_usd'])} left before real money stops for good." if lifeline else "")
        loss, most = floor["day_loss_usd"], floor["day_max_usd"]
        done = (f"; with the bets already open settled, today's loss is {dollars(loss)}." if loss > most + 0.005
                else f", at {dollars(loss)} lost.")
        return f"The {limit(most)} daily stop ended new real bets for today{done}{left} Rules first, goal second."
    if mood == "stand_down":
        return f"Real bets are paused: {_sentence(paused or 'paused for now')} Rules first, goal second."
    if mood in ("off", "stopped_for_good") and lifeline:
        return (f"Real money stops for good after {limit(lifeline['max_usd'])} lost in total; "
                f"{dollars(lifeline['left_usd'])} of room is left. I guard that line, not the goal.")
    open_max, day_max, total_max = (_num(limits.get(k)) for k in ("open_max_usd", "day_max_usd", "total_max_usd"))
    if open_max is None or day_max is None or total_max is None:
        return None
    return (f"The goal is {T} a day. My limits don't move for it: {_lower(per)}, {limit(open_max)} in bets at once, "
            f"stop at {limit(day_max)} lost in a day, {limit(total_max)} in total.")


def _pip(said: Any, kind: str) -> str | None:
    """Pip (finds the Solana bot's coins): his newest find, in the page's own words."""
    if not isinstance(said, str) or not said.strip():
        return None
    return (f"Practice ({kind}): {said.strip().rstrip('.')}. Nothing I find counts toward the goal until a strategy "
            "passes the lab.")


def _nyx(doing: Any, kind: str) -> str | None:
    """Nyx (the danger check): what the check did, in the team room's own words."""
    if not isinstance(doing, str) or not doing.strip():
        return None
    return f"{_sentence(doing)} Saying no keeps money (practice, {kind})."


def _jet(inp: Mapping[str, Any], kind: str, signed: Fmt) -> str | None:
    """Jet (the Solana bot's trades): the last closed trade, or the practice tally with its money."""
    last = _map(inp.get("last_closed"))
    coin, why, pnl = last.get("coin"), str(last.get("why") or ""), _num(last.get("pnl_usd"))
    if isinstance(coin, str) and coin and pnl is not None:
        if why.startswith("Stop-loss"):
            return f"{coin}: cut the loss at the stop, {signed(pnl)} ({kind}). As planned: small losses are the rule."
        if why == "Took profit":
            return f"{coin}: took the profit, {signed(pnl)} ({kind})."
    won, lost = _int(inp.get("trades_won")), _int(inp.get("trades_lost"))
    wallet = _num(inp.get("practice_wallet_usd"))
    if wallet is None:
        return f"Practice trades so far: {won + lost} finished ({kind}), each one small and with a stop."
    return (f"Practice trades so far: {won} won and {lost} lost; the practice wallet is at {signed(wallet)} since "
            f"start ({kind}). Each one small and with a stop.")


def _mote(receipts: Mapping[str, Any]) -> str | None:
    """Mote (the tamper-proof records): what the record check says."""
    count = _num(receipts.get("count"))
    if receipts.get("verified") is True and count is not None:
        return (f"Each real settlement is also sealed in the tamper-proof records ({int(count):,} records in all), "
                "and the check found nothing edited.")
    if receipts.get("verified") is False:
        bad = receipts.get("first_bad_seq")
        where = f" (#{bad})" if isinstance(bad, int) and not isinstance(bad, bool) else ""
        return f"The record check found a changed entry{where}: the tower's figures need checking."
    return "The records have not been checked yet."
