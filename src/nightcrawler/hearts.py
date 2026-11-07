"""The team's hearts (the 3D world's cast as people who care about the town): ``/api/page`` -> ``plain.hearts``.

The owner asked for a team with a heart, a brain and a personality: not patterns and strategies, but six characters who
want to support the town and work to keep it running. Each cast member has a fixed TEMPERAMENT and a fixed sentence on
WHY THEY CARE (the town's lights: the bill that keeps it running), and a MOOD chosen from the page's own figures only:

* the town's real money today (``town.goal``: the real result, the goal's own mood, the newest real settlement today
  and whether it won or lost, from ``plain.finished``),
* the room left under the real-money stops (``town.goal.floor`` for the day, ``town.goal.lifeline`` for good) against
  what one miss costs at the desk's own bet size (its contracts a bet times its price),
* the member's own status (``plain.team``) and, for Mote, the record check (``receipts``).

The heart line is a FIXED template per (member, mood) (:data:`TEMPLATES`) filled only with those figures. Rules: never a
made-up number (a template whose figure is missing gives no line), never real and pretend money added together, never a
promise of profit, never a nudge toward bigger bets (the bet size is the owner's choice; Rook may say what it is), and
the practice members (Pip, Nyx, Jet: the Solana bot, on pretend money) say "practice" or "pretend" whenever they speak
of their money. While the Solana bot trades real money their practice words would not be true, so they say nothing.

DISPLAY ONLY: nothing here changes a bet size, a limit or a rule, and no desk reads it. This module imports the standard
library only (a test checks it) and its functions are pure: :mod:`nightcrawler.pagestate` gathers the inputs
(:func:`nightcrawler.pagestate.hearts_inputs`, after ``plain.goal``), passes its own money formatters and inserts the
result as data; the world shows the words as text only.
"""

from __future__ import annotations

import math
import string
from collections.abc import Callable, Mapping
from typing import Any

__all__ = ["CAST", "HUDDLE_TEMPLATES", "MOODS", "TEMPLATES", "team_hearts"]

Fmt = Callable[[float], str]

#: The moods, in the order the world's key lists them.
MOODS = ("proud", "determined", "worried", "hurting", "hopeful", "calm", "relieved")
LABEL = "The team's hearts"

#: The cast: name, temperament and why they care (fixed copy), and which money they handle.
CAST: dict[str, dict[str, str]] = {
    "voss": {"name": "Voss", "money": "real money",
             "temperament": "Proud and steady; carries the town's real money.",
             "why": "Every real dollar Voss brings home helps pay the bill that keeps the town's lights on."},
    "rook": {"name": "Rook", "money": "real money",
             "temperament": "The protective guardian; loves the town too much to gamble it.",
             "why": "If the town's savings go, its lights go too, so Rook guards every limit."},
    "pip": {"name": "Pip", "money": "pretend money",
            "temperament": "Hungry and hopeful; always scouting.",
            "why": "Pip hunts for the find that could one day help keep the town's lights on."},
    "nyx": {"name": "Nyx", "money": "pretend money",
            "temperament": "Sharp and suspicious; guards the town from scams.",
            "why": "Every scam Nyx stops is money the town keeps for its lights."},
    "jet": {"name": "Jet", "money": "pretend money",
            "temperament": "Loyal and quick; delivers every trade.",
            "why": "Jet runs every trade on time, because the town's lights depend on the whole team."},
    "mote": {"name": "Mote", "money": "real money",
             "temperament": "Calm; keeps the town's honest record.",
             "why": "Honest books show whether the town's lights are paid for, so Mote writes everything down."},
}
#: The practice members: the Solana bot's crew, on pretend money while it is not live.
PRACTICE = ("pip", "nyx", "jet")

#: The heart lines: one fixed template per (member, mood, situation), filled with the page's own figures only.
#: Tokens: today (real today, signed), won (real today, a gain), gap (to the owner's goal), target (the goal), loss (the
#: newest real settlement's loss), lost (lost in total), loss_max (one miss at the desk's size), room (left under
#: today's stop), used and stop (today's stop), left (room left before real money stops for good), per (the bet size),
#: practice (the practice result today, pretend), count (sealed records).
TEMPLATES: dict[tuple[str, str, str], str] = {
    ("voss", "proud", "goal"): "Brought home {won} for the town today: the owner's {target} goal is met. Same size, "
                               "same rule.",
    ("voss", "proud", "up"): "Brought home {won} for the town today. {gap} to go to the owner's {target} goal.",
    ("voss", "hurting", "hit"): "That miss cost the town {loss}. I owe it steadier hands.",
    ("voss", "hurting", "day"): "The daily stop ended my day at {today} in real money. It hurts. The stop is the rule, "
                                "and I keep it.",
    ("voss", "hurting", "stopped"): "Real money stopped for good after {lost} lost. I let the town down; only the "
                                    "owner can start it again.",
    ("voss", "worried", "risk"): "The risk manager paused my real bets. I wait, and the town's money stays where it is.",
    ("voss", "determined", "down"): "Real money today: {today}. The town is counting on me, so I keep to the rule, one "
                                    "careful bet at a time.",
    ("voss", "determined", "flat"): "No real bet has finished today yet. The owner's goal is {target} a day; I work for "
                                    "it by the rule.",
    ("voss", "calm", "off"): "Real money is off today. I keep my eyes on the markets so the team is ready when it is on.",
    ("voss", "calm", "unknown"): "Today's real result is not known yet. I wait for the books before I say more.",
    ("rook", "hurting", "stopped"): "We lost {lost}, all the room the owner gave real money. I hold the line now; only "
                                    "the owner can open it.",
    ("rook", "relieved", "day"): "The {stop} daily stop held. It stings, but {left} of the town's room is kept for "
                                 "another day.",
    ("rook", "relieved", "day_plain"): "The {stop} daily stop held. It stings, but it kept the rest of the town's "
                                       "savings safe today.",
    ("rook", "relieved", "goal"): "Goal day, and my limits never moved: every bet {per}, a stop at {stop} a day. That "
                                  "is how the town stays safe.",
    ("rook", "worried", "room"): "One miss now costs about {loss_max}; {room} is left under today's stop. I won't let "
                                 "us spend the town's savings chasing it.",
    ("rook", "worried", "plain"): "One miss now costs about {loss_max}. I won't let us spend the town's savings chasing "
                                  "it.",
    ("rook", "calm", "risk"): "Real bets are paused until the rule proves itself. Rules first; the town's savings stay "
                              "put.",
    ("rook", "calm", "live"): "Every bet stays at {per}, the owner's choice. Today's stop: {used} used of {stop}. I "
                              "guard the town's savings.",
    ("rook", "calm", "off"): "Real money is off. {left} of the owner's room is kept safe for the town.",
    ("rook", "calm", "watch"): "My limits stay where the owner set them. I keep watch over the town's savings.",
    ("pip", "hopeful", "practice"): "Scouting for the town all day. Practice today: {practice} (pretend money). One "
                                    "proven find could help keep the lights on.",
    ("pip", "hopeful", "plain"): "Scouting for the town all day (practice, pretend money). One proven find could help "
                                 "keep the lights on.",
    ("pip", "determined", "plain"): "The town took a hit, so I scout harder. Practice only (pretend money) until a "
                                    "find proves itself.",
    ("pip", "worried", "plain"): "I'm stuck, and the town is waiting on me. Practice only (pretend money); I'm on it.",
    ("nyx", "determined", "plain"): "Every scam I stop is money the town keeps. Practice for now (pretend money), but "
                                    "I watch like it's real.",
    ("nyx", "worried", "plain"): "Something is stuck on my desk. Nothing gets past me while I sort it out (practice, "
                                 "pretend money).",
    ("nyx", "calm", "plain"): "Quiet on the scam watch. I keep looking anyway (practice, pretend money).",
    ("jet", "proud", "plain"): "The town is up {won} in real money today. I deliver every trade on time; mine are "
                               "practice (pretend money).",
    ("jet", "determined", "plain"): "The town took a hit; I run my practice trades fast and clean (pretend money).",
    ("jet", "worried", "plain"): "A trade is stuck with me. I don't rest until it's delivered (practice, pretend "
                                 "money).",
    ("jet", "calm", "practice"): "Practice trades today: {practice} (pretend money). Ready to run the moment the town "
                                 "needs me.",
    ("jet", "calm", "plain"): "Ready to run the moment the town needs me (practice, pretend money).",
    ("mote", "proud", "count"): "Goal day, written down for good: {count} sealed records, nothing edited. The town can "
                                "trust its books.",
    ("mote", "calm", "count"): "I write down every real result, good or bad: {count} sealed records, nothing edited.",
    ("mote", "calm", "plain"): "I write down every real result, good or bad, so the town always knows where it stands.",
    ("mote", "worried", "plain"): "The record check found a changed entry. The town's books need checking.",
}
#: The huddle's line: a real settlement (or a real closed trade) new today, in the page's own figures.
HUDDLE_TEMPLATES: dict[tuple[str, str], str] = {
    ("bet", "won"): "A real bet just settled: won {usd} (real money). The team gathers at the goal tower.",
    ("bet", "lost"): "A real bet just settled: lost {usd} (real money). The team gathers at the goal tower.",
    ("bet", "even"): "A real bet just settled, even (real money). The team gathers at the goal tower.",
    ("trade", "won"): "A real trade just closed: won {usd} (real money). The team gathers at the goal tower.",
    ("trade", "lost"): "A real trade just closed: lost {usd} (real money). The team gathers at the goal tower.",
    ("trade", "even"): "A real trade just closed, even (real money). The team gathers at the goal tower.",
}
#: The town's day in one word (first match wins): the signal every mood is chosen from.
SIGNALS = ("stopped", "off", "unknown", "stand_day", "stand_risk", "hit", "goal", "up", "down", "flat")
_HURT = ("stopped", "stand_day", "stand_risk", "hit", "down")


def _num(value: Any) -> float | None:
    """A finite number (bool is not one), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _cents(value: float) -> float:
    cents = round(value, 2)
    return 0.0 if cents == 0 else cents


def _fields(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def _fill(key: tuple[str, str, str], tokens: Mapping[str, str | None]) -> str | None:
    """The template filled, or None when one of its figures is missing (never "$0.00" for an unknown)."""
    template = TEMPLATES[key]
    names = _fields(template)
    if any(tokens.get(name) is None for name in names):
        return None
    return template.format(**{name: tokens[name] for name in names})


def _newest_real(finished: Any, day_start: float | None) -> dict[str, Any] | None:
    """The newest real settlement (or real closed trade) today from ``plain.finished`` (newest first), else None."""
    if day_start is None or not isinstance(finished, list):
        return None
    for row in finished:
        item = _map(row)
        ts = _num(item.get("ts"))
        if item.get("real") is not True or ts is None or ts < day_start:
            continue
        if item.get("result") not in ("won", "lost", "even") or not isinstance(item.get("id"), str):
            continue
        return {"id": item["id"], "ts": ts, "result": item["result"], "usd": _num(item.get("usd")),
                "kind": "trade" if item.get("who") == "jet" else "bet"}
    return None


def _signal(goal: Mapping[str, Any], newest: Mapping[str, Any] | None) -> str:
    mood, today, target = goal.get("mood"), _num(goal.get("real_today_usd")), _num(goal.get("target_usd"))
    if mood == "stopped_for_good":
        return "stopped"
    if mood == "off":
        return "off"
    if mood == "unknown" or today is None:
        return "unknown"
    if mood == "stand_down":
        return "stand_day" if goal.get("stand_down") == "day" else "stand_risk"
    if newest is not None and newest["result"] == "lost":
        return "hit"
    if target is not None and today >= target:
        return "goal"
    if today > 0:
        return "up"
    return "down" if today < 0 else "flat"


def _status(team: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in team if isinstance(team, list) else []:
        item = _map(row)
        if isinstance(item.get("id"), str) and isinstance(item.get("status_word"), str):
            out[item["id"]] = item["status_word"]
    return out


def _pick(key: str, sig: str, status: str | None, tight: bool, verified: Any) -> tuple[str, str]:
    """``(mood, situation)`` for one member: the town's day first, then the member's own status (first match wins)."""
    if key == "voss":
        return {"stopped": ("hurting", "stopped"), "off": ("calm", "off"), "unknown": ("calm", "unknown"),
                "stand_day": ("hurting", "day"), "stand_risk": ("worried", "risk"), "hit": ("hurting", "hit"),
                "goal": ("proud", "goal"), "up": ("proud", "up"), "down": ("determined", "down"),
                "flat": ("determined", "flat")}[sig]
    if key == "rook":
        if sig == "stopped":
            return "hurting", "stopped"
        if sig == "stand_day":
            return "relieved", "day"
        if sig == "stand_risk":
            return "calm", "risk"
        if sig == "off":
            return "calm", "off"
        if sig == "unknown":
            return "calm", "watch"
        if sig == "hit" or tight:
            return "worried", "room"
        if sig == "goal":
            return "relieved", "goal"
        return "calm", "live"
    if key == "mote":
        if verified is False:
            return "worried", "plain"
        return ("proud", "count") if sig == "goal" else ("calm", "count")
    if status == "stuck":
        return "worried", "plain"
    hurt = sig in _HURT
    if key == "pip":
        return ("determined", "plain") if hurt else ("hopeful", "practice")
    if key == "nyx":
        return ("determined", "plain") if hurt or status == "working" else ("calm", "plain")
    # jet
    if hurt:
        return "determined", "plain"
    return ("proud", "plain") if sig in ("goal", "up") else ("calm", "practice")


# fallbacks when a situation's figure is missing (the same mood, fewer figures)
_FALLBACK = {("rook", "relieved", "day"): ("rook", "relieved", "day_plain"),
             ("rook", "worried", "room"): ("rook", "worried", "plain"), ("rook", "calm", "off"): ("rook", "calm", "watch"),
             ("rook", "calm", "live"): ("rook", "calm", "watch"), ("pip", "hopeful", "practice"): ("pip", "hopeful", "plain"),
             ("jet", "calm", "practice"): ("jet", "calm", "plain"), ("mote", "proud", "count"): ("mote", "calm", "plain"),
             ("mote", "calm", "count"): ("mote", "calm", "plain")}


def team_hearts(inp: Mapping[str, Any], *, dollars: Fmt, signed: Fmt, limit: Fmt) -> dict[str, Any] | None:
    """``plain.hearts``: each cast member's temperament, why they care, mood and heart line, and the huddle (the newest
    real settlement today), from :func:`nightcrawler.pagestate.hearts_inputs`. None when the page has no town goal (the
    real result cannot be told). Pure."""
    goal = inp.get("goal")
    if not isinstance(goal, Mapping):
        return None
    newest = _newest_real(inp.get("finished"), _num(goal.get("day_start")))
    sig = _signal(goal, newest)
    today, target = _num(goal.get("real_today_usd")), _num(goal.get("target_usd"))
    floor, lifeline = _map(goal.get("floor")), _map(goal.get("lifeline"))
    contracts, theta = _num(inp.get("contracts")), _num(inp.get("theta"))
    loss_max = _cents(contracts * theta) if contracts is not None and contracts > 0 and theta is not None and 0 < theta < 1 else None
    day_used, day_max = _num(floor.get("day_loss_usd")), _num(floor.get("day_max_usd"))
    room = max(0.0, _cents(day_max - day_used)) if day_used is not None and day_max is not None and day_max > 0 else None
    left, lost = _num(lifeline.get("left_usd")), _num(lifeline.get("lost_usd"))
    tight = loss_max is not None and any(v is not None and v < 2 * loss_max for v in (room, left))
    practice = _num(_map(goal.get("practice")).get("solana_today_usd"))
    parts = goal.get("parts")
    solana_live = isinstance(parts, list) and any(_map(p).get("id") == "solana" for p in parts)
    receipts = _map(inp.get("receipts"))
    count = _num(receipts.get("count"))
    verified = receipts.get("verified")
    loss = newest["usd"] if newest is not None and newest["result"] == "lost" else None
    per = None
    if contracts is not None and contracts > 0:
        per = "1 contract" if contracts == 1 else f"{contracts:g} contracts"
    tokens: dict[str, str | None] = {
        "today": signed(today) if today is not None else None,
        "won": dollars(today) if today is not None and today > 0 else None,
        "gap": dollars(_cents(target - today)) if today is not None and target is not None and today < target else None,
        "target": limit(target) if target is not None else None,
        "loss": dollars(loss) if loss is not None else None,
        "lost": dollars(lost) if lost is not None else None,
        "loss_max": dollars(loss_max) if loss_max is not None else None,
        "room": dollars(room) if room is not None else None,
        "used": dollars(day_used) if day_used is not None else None,
        "stop": limit(day_max) if day_max is not None and day_max > 0 else None,
        "left": dollars(left) if left is not None else None,
        "per": per,
        # (the practice crew's own result today: pretend money, never added to the real figures above)
        "practice": signed(practice) if practice is not None else None,
        "count": f"{int(count):,}" if count is not None and verified is True else None,
    }
    status = _status(inp.get("team"))
    members = []
    for key, spec in CAST.items():
        mood, situation = _pick(key, sig, status.get(key), tight, verified)
        line: str | None = None
        if not (key in PRACTICE and solana_live):  # (the practice words would not be true: say nothing)
            want: tuple[str, str, str] | None = (key, mood, situation)
            while want is not None and line is None:
                line = _fill(want, tokens)
                want = _FALLBACK.get(want)
        members.append({"id": key, "name": spec["name"], "temperament": spec["temperament"], "why": spec["why"],
                        "money": "real money" if key in PRACTICE and solana_live else spec["money"],
                        "mood": mood, "line": line})
    huddle = None
    if newest is not None:
        usd = newest["usd"]
        template = HUDDLE_TEMPLATES[(newest["kind"], newest["result"])]
        if "{usd}" not in template or usd is not None:
            huddle = {"id": newest["id"], "ts": newest["ts"], "result": newest["result"], "usd": usd,
                      "line": template.format(usd=dollars(usd)) if "{usd}" in template and usd is not None
                      else template}
    return {"label": LABEL, "signal": sig, "members": members, "huddle": huddle}
