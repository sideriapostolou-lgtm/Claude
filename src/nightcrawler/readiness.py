""""Is it ready for my real $100 yet?" - the checklist on the one page (owner: O6).

Every item is computed from REAL state and is never optimistic: an item is done only when the fact is
known to be true; unknown counts as not done. Steps 1-5 can all be done while the bot still trades paper
money (docs/GOING_LIVE.md creates, funds and adds the bot wallet before the switch), so the answer is
computed over steps 1-5; step 6, the real-money switch, is the action the owner takes once they are done.

1. ``edge`` - the learning card names a promoted champion that is not ``CASH`` (doing nothing) AND
   reports ``champion_passed_locked_test: true`` (it beat trading costs on data it never saw).
2. ``paper_match`` - item 1 is done AND the Coach's stage 2 passed (card ``state`` ``live_ready`` or ``live``:
   at least ``S2_MIN_N`` paper trades over ``S2_MIN_DAYS`` days with an anytime-valid lower bound on the mean
   net result above 0, docs/LEARNING.md §5.4 and docs/GOING_LIVE.md §0; "positive over 20-30 trades" is not
   proof - a strategy with no edge passes it about half the time) AND the card reports
   ``paper_matches_backtest: true``.
3. ``wallet`` - a bot wallet is set up (``BOT_WALLET_MODE=generated``, the bot's own, or ``BOT_WALLET_SECRET``;
   one is required in live mode) with a known address and a recently read SOL balance above 0 (its SOL, not
   the value of the coins it holds).
4. ``keys`` - ``KEYS_ROTATED_ON`` is a real date (``YYYY-MM-DD``), not in the future.
5. ``locked`` - ``DASHBOARD_TOKEN`` is a strong password (:func:`nightcrawler.config.dashboard_token_problem`).
6. ``live`` - ``TRADING_MODE=live`` with the exact ``LIVE_CONFIRM`` phrase.

Headline: ``"Not ready yet — N of 5 done"`` until steps 1-5 are done; then ``"Ready to switch on"`` (paper)
or ``"Ready — real money is on"`` (live), unless the bot is ``stopped`` (any banner on the page: kill
switch, halt, silent engine, wallet drift, safe mode, an unknown trade), which reads ``"Set up, but stopped
right now: see the banners at the top"``. Only a ``Ready`` answer is ever green. A learning card whose
``source`` is ``"error"`` makes steps 1-2 unknown; ``"missing"`` says the learning system is not installed.
``warning`` is set when real money is ON before steps 1-5 are all done.
"""

from __future__ import annotations

import datetime
import time
from collections.abc import Mapping
from typing import Any

from nightcrawler.botwallet import wallet_configured
from nightcrawler.config import (
    DASHBOARD_TOKEN_MIN_LEN,
    LIVE_CONFIRM_PHRASE,
    Settings,
    dashboard_token_problem,
    parse_rotation_date,
)
from nightcrawler.learn.gate import S2_MIN_DAYS, S2_MIN_N

__all__ = ["CHECK_IDS", "CHECK_LABELS", "STAGE2_STATES", "STEPS", "readiness"]

CHECK_LABELS: dict[str, str] = {
    "edge": "A strategy proved an edge on unseen data",
    "paper_match": f"Paper trades proved it ({S2_MIN_N}+ trades, {S2_MIN_DAYS}+ days)",
    "wallet": "Bot wallet set up and funded",
    "keys": "Keys shared in chat replaced",
    "locked": "Dashboard locked with a password link",
    "live": "Real-money switch",
}
CHECK_IDS = tuple(CHECK_LABELS)
#: The steps the answer is computed over (the last item, the switch itself, is the action).
STEPS = 5
#: A champion with this name means "do nothing": no strategy is better than holding cash.
CASH = "CASH"
#: Learning card states that mean the Coach's stage 2 passed (a ``live_ready`` receipt, LEARNING §5.4).
STAGE2_STATES = frozenset({"live_ready", "live"})
_STAGE2_MISSING = (f"Not yet — real money needs {S2_MIN_N}+ paper trades over {S2_MIN_DAYS}+ days whose always-valid "
                   "lower bound on the average result is above 0.")
REASON_MAX = 160
#: KEYS_ROTATED_ON may be "tomorrow" in UTC for an owner in a time zone ahead of UTC.
_DATE_SLACK = datetime.timedelta(days=1)
_LEARNING_ERROR = "Unknown (learning system error): see the logs."


def _champion(card: Mapping[str, Any]) -> str | None:
    """The promoted champion's name (a string or ``{"name": ...}``), or None."""
    champion = card.get("champion")
    if isinstance(champion, Mapping):
        champion = champion.get("name")
    if not isinstance(champion, str) or not champion.strip():
        return None
    return champion.strip()


def _short(address: str) -> str:
    return f"{address[:4]}…{address[-4:]}" if len(address) > 12 else address


def _item(cid: str, done: bool, reason: str) -> dict[str, Any]:
    text = reason if len(reason) <= REASON_MAX else reason[:REASON_MAX - 1] + "…"
    return {"id": cid, "label": CHECK_LABELS[cid], "done": done, "reason": text}


def _learning(card: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Steps 1 and 2."""
    if card.get("source") == "error":
        return _item("edge", False, _LEARNING_ERROR), _item("paper_match", False, _LEARNING_ERROR)
    champion = _champion(card)
    proven = (champion is not None and champion.upper() != CASH
              and card.get("champion_passed_locked_test") is True)
    if proven:
        edge = _item("edge", True, f"{champion} beat trading costs on data it never saw.")
    elif champion is not None and champion.upper() != CASH:
        edge = _item("edge", False, f"Not yet — {champion} has not passed the test on unseen data.")
    elif card.get("source") == "missing":
        edge = _item("edge", False, "Can't be checked yet: the self-learning system that tests strategies is "
                                    "not installed.")
    else:
        edge = _item("edge", False, "Not yet — no strategy has beaten trading costs on unseen data so far.")

    stage2 = card.get("state") in STAGE2_STATES
    if proven and stage2 and card.get("paper_matches_backtest") is True:
        paper = _item("paper_match", True, "Passed stage 2 on real quotes, and paper trades behave like the test.")
    elif not proven:
        paper = _item("paper_match", False, "Needs a proven strategy first")
    elif not stage2:
        paper = _item("paper_match", False, _STAGE2_MISSING)
    else:
        why = card.get("paper_matches_backtest_reason")
        paper = _item("paper_match", False, why.strip() if isinstance(why, str) and why.strip()
                      else "Not yet — paper trades don't match the test results yet.")
    return edge, paper


def _wallet(settings: Settings, address: str | None, sol: float | None) -> dict[str, Any]:
    """Step 3: live, or paper with a bot wallet set up (GOING_LIVE steps 1-3 happen in paper mode)."""
    if not settings.is_live and not wallet_configured(settings):
        return _item("wallet", False, "No bot wallet yet — you create it when you're ready (docs/GOING_LIVE.md).")
    if not address:
        if settings.is_live:
            return _item("wallet", False, "Real-money mode is on, but the bot wallet's address is not known yet.")
        return _item("wallet", False, "Bot wallet added; the bot has not read it yet (it checks every 10 minutes).")
    if sol is None:
        return _item("wallet", False, f"Wallet {_short(address)} found; its balance has not been read recently.")
    if sol <= 0:
        return _item("wallet", False, f"Wallet {_short(address)} is empty — send it SOL first.")
    return _item("wallet", True, f"Wallet {_short(address)} holds {sol:.4g} SOL.")


def _keys(settings: Settings, now: float) -> dict[str, Any]:
    """Step 4. Only a real date counts, and a value that is not one is never shown (it may be a key)."""
    if not settings.keys_rotated_on.strip():
        return _item("keys", False, "Replace the keys you pasted in chat, then set KEYS_ROTATED_ON in Railway.")
    day = parse_rotation_date(settings.keys_rotated_on)
    if day is None:
        return _item("keys", False, "KEYS_ROTATED_ON must be a date like 2026-10-09.")
    today = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).date()
    if day > today + _DATE_SLACK:
        return _item("keys", False, "KEYS_ROTATED_ON is a date in the future: use the day you replaced the keys.")
    return _item("keys", True, f"Done on {day.isoformat()}.")


def _locked(settings: Settings) -> dict[str, Any]:
    """Step 5: a password nobody can guess (the reason never shows it)."""
    if not settings.dashboard_token:
        return _item("locked", False, "Set DASHBOARD_TOKEN in Railway to a long random password.")
    weak = dashboard_token_problem(settings.dashboard_token.reveal())
    if weak:
        return _item("locked", False, f"DASHBOARD_TOKEN is set, but {weak}: use a long random password "
                                      f"(at least {DASHBOARD_TOKEN_MIN_LEN} characters).")
    return _item("locked", True, "Only someone with your link can open this page.")


def readiness(settings: Settings, card: Mapping[str, Any], *, wallet_address: str | None,
              wallet_sol: float | None, stopped: bool = False, now: float | None = None) -> dict[str, Any]:
    """The checklist: ``{"ready", "done", "total", "headline", "warning", "items": [{"id", "label", "done",
    "reason"}]}``; ``done`` and ``total`` count steps 1-5. ``card`` is the (sanitized) learning card;
    ``wallet_*`` what the page knows about the bot wallet (address, recently read SOL balance; None when
    unknown); ``stopped`` is True while any banner is up; ``now`` defaults to the wall clock."""
    now = time.time() if now is None else now
    edge, paper = _learning(card)
    steps = [edge, paper, _wallet(settings, wallet_address, wallet_sol), _keys(settings, now), _locked(settings)]
    done = sum(i["done"] for i in steps)
    set_up = done == STEPS
    live_on = settings.trading_mode == "live" and settings.live_confirm == LIVE_CONFIRM_PHRASE
    if live_on:
        live = _item("live", True, "On: the bot trades real money.")
    elif set_up:
        live = _item("live", False, "Steps 1–5 are done: switch it on when you want (docs/GOING_LIVE.md, step 4).")
    else:
        live = _item("live", False, "Last step, only after 1–5.")
    if not set_up:
        headline = f"Not ready yet — {done} of {STEPS} done"
    elif stopped:
        headline = "Set up, but stopped right now: see the banners at the top"
    else:
        headline = "Ready — real money is on" if live_on else "Ready to switch on"
    warning = None
    if live_on and not set_up:
        warning = "Real money is ON before every step above is done. Think about switching back to paper."
    return {"ready": set_up and not stopped, "done": done, "total": STEPS, "headline": headline,
            "warning": warning, "items": [*steps, live]}
