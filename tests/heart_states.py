"""The team hearts' shared states (tests and screenshots): :data:`HEART_STATES` and :func:`apply_heart_state`.

Each is a goal state (tests/goal_states.py, built the same way) at the owner's real-money size (10 contracts a bet, a $30
daily stop, $40 in total), with today's real settlements in their order and the newest one in ``plain.finished`` as the
server lists it; then ``town.goal``, ``plain.goal`` and ``plain.hearts`` are recomputed with the server's own functions.

    python -m tests.heart_states <dir>    # one JSON page per state (the screenshot harness serves them)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__":  # python -m tests.heart_states: this checkout's own code, never an installed copy
    _ROOT = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(_ROOT / "src"), str(_ROOT / "tests")]

from nightcrawler import pagestate
from tests import goal_states as GS

#: The owner's real-money size since 2026-10-11 (the desk's settings on Railway).
TEN = {"POLYDESK_LIVE_CONTRACTS": "10", "POLYDESK_LIVE_MAX_OPEN_USD": "30", "POLYDESK_LIVE_DAILY_LOSS_USD": "30",
       "POLYDESK_LIVE_TOTAL_LOSS_USD": "40"}
QUESTION = "Will the Fed hold rates at the November 2026 meeting?"
#: name -> a goal state (GS.STATES' keys) plus today's real results in order (``pnls``) and the newest real settlement
#: (``last``: won or lost, its dollars, seconds before the snapshot), as the desk's receipts and plain.finished hold them.
HEART_STATES: dict[str, dict[str, Any]] = {
    "winning_pre": {"today": 1.27, "settled": 5, "won": 5, "live": True, "practice": 2.4, "env": TEN,
                    "pnls": [0.25, 0.26, 0.24, 0.27, 0.25], "last": ("won", 0.25, 900.0),
                    "about": "a winning real day, five bets won (the poll before the sixth settles)"},
    "winning": {"today": 1.52, "settled": 6, "won": 6, "live": True, "practice": 2.4, "env": TEN,
                "pnls": [0.25, 0.26, 0.24, 0.27, 0.25, 0.25], "last": ("won", 0.25, 40.0),
                "about": "a winning real day: six of six won at 10 contracts a bet"},
    "losing_big": {"today": -8.82, "settled": 5, "won": 4, "live": True, "practice": -1.1, "env": TEN,
                   "pnls": [0.25, 0.26, 0.24, 0.23, -9.80], "last": ("lost", 9.80, 30.0),
                   "about": "a losing real day: four small wins, then one miss cost $9.80"},
}


def apply_heart_state(page: dict[str, Any], name: str, now: float = GS.SNAPSHOT_AT) -> dict[str, Any]:
    """A copy of ``page`` in the heart state ``name`` at ``now`` (the goal state's books, today's real settlements in
    order, the newest in ``plain.finished``), with ``town.goal``, ``plain.goal`` and ``plain.hearts`` recomputed. Pure."""
    spec = HEART_STATES[name]
    GS.STATES[name] = {k: v for k, v in spec.items() if k not in ("pnls", "last")}
    try:
        settings = GS.state_settings(name)
        out = GS.apply_state(page, name, now, settings)
        live_days, _ = GS.state_books(name, now)
    finally:
        del GS.STATES[name]
    result, usd, ago = spec["last"]
    ts = now - ago
    pnl = usd if result == "won" else -usd
    out["money"]["polymarket"]["settled_real"] = [
        {"ts": ts, "text": f"Settled: {QUESTION} · {result} {pnl:+.2f} $ (real)"}]
    plain = out["plain"]
    plain["finished"] = pagestate.plain_finished(out["trades"]["closed"], out["money"]["polymarket"]["settled_real"],
                                                 live=settings.is_live)
    out["town"]["goal"], plain["goal"] = pagestate.town_goal_block(settings, out, now, live_days=live_days,
                                                                   today_pnls=list(spec["pnls"]))
    plain["hearts"] = pagestate.hearts_block(settings, out)
    return out


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path("heart_states")
    target.mkdir(parents=True, exist_ok=True)
    base = GS.base_page()
    for name in HEART_STATES:
        page = apply_heart_state(base, name)
        (target / f"{name}.json").write_text(json.dumps(page, allow_nan=False), encoding="utf-8")
        print(name, page["plain"]["goal"]["strip"])
        for m in page["plain"]["hearts"]["members"]:
            print("   ", m["id"], m["mood"], "|", m["line"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
