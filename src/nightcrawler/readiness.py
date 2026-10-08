""""Is it ready for my real $100 yet?" - the six-step checklist on the one page (owner: O6).

Every item is computed from REAL state and is never optimistic: an item is done only when the fact is
known to be true; unknown counts as not done. The headline is ``"Ready"`` only when all six are done,
otherwise ``"Not ready yet — N of 6 done"`` (shown in a neutral colour, never green).

1. ``edge`` - the learning card names a promoted champion that is not ``CASH`` (doing nothing) AND
   reports ``champion_passed_locked_test: true`` (it beat trading costs on data it never saw).
2. ``paper_match`` - item 1 is done AND the card reports ``paper_matches_backtest: true``.
3. ``wallet`` - live configuration with a known bot wallet address and a known SOL balance above 0.
4. ``keys`` - ``KEYS_ROTATED_ON`` is set (the owner replaced every key ever pasted into a chat).
5. ``locked`` - ``DASHBOARD_TOKEN`` is set.
6. ``live`` - ``TRADING_MODE=live`` with the exact ``LIVE_CONFIRM`` phrase.

``warning`` is set when real money is ON before items 1-5 are all done.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nightcrawler.config import LIVE_CONFIRM_PHRASE, Settings

__all__ = ["CHECK_IDS", "CHECK_LABELS", "readiness"]

CHECK_LABELS: dict[str, str] = {
    "edge": "A strategy proved an edge on unseen data",
    "paper_match": "Paper results match the test results",
    "wallet": "Bot wallet set up and funded",
    "keys": "Keys shared in chat replaced",
    "locked": "Dashboard locked with a password link",
    "live": "Real-money switch",
}
CHECK_IDS = tuple(CHECK_LABELS)
#: A champion with this name means "do nothing": no strategy is better than holding cash.
CASH = "CASH"
REASON_MAX = 160


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


def readiness(settings: Settings, card: Mapping[str, Any], *, wallet_address: str | None,
              wallet_sol: float | None) -> dict[str, Any]:
    """The checklist: ``{"ready", "done", "total", "headline", "warning", "items": [{"id", "label", "done",
    "reason"}]}``. ``card`` is the (sanitized) learning card; ``wallet_*`` what the dashboard state knows
    about the live bot wallet (address, SOL balance; None when unknown)."""
    champion = _champion(card)
    proven = (champion is not None and champion.upper() != CASH
              and card.get("champion_passed_locked_test") is True)
    if proven:
        edge = _item("edge", True, f"{champion} beat trading costs on data it never saw.")
    elif champion is not None and champion.upper() != CASH:
        edge = _item("edge", False, f"Not yet — {champion} has not passed the test on unseen data.")
    else:
        edge = _item("edge", False, "Not yet — no strategy has beaten trading costs on unseen data so far.")

    matches = proven and card.get("paper_matches_backtest") is True
    if matches:
        paper = _item("paper_match", True, "Paper trades behave like the test said they would.")
    elif not proven:
        paper = _item("paper_match", False, "Needs a proven strategy first")
    else:
        why = card.get("paper_matches_backtest_reason")
        paper = _item("paper_match", False, why.strip() if isinstance(why, str) and why.strip()
                      else "Not yet — paper trades don't match the test results yet.")

    if not settings.is_live:
        wallet = _item("wallet", False, "No bot wallet yet — you create it when you're ready (docs/GOING_LIVE.md).")
    elif not wallet_address:
        wallet = _item("wallet", False, "Real-money mode is on, but the bot wallet's address is not known yet.")
    elif wallet_sol is None:
        wallet = _item("wallet", False, f"Wallet {_short(wallet_address)} found; its balance has not been read yet.")
    elif wallet_sol <= 0:
        wallet = _item("wallet", False, f"Wallet {_short(wallet_address)} is empty — send it SOL first.")
    else:
        wallet = _item("wallet", True, f"Wallet {_short(wallet_address)} holds {wallet_sol:.4g} SOL.")

    rotated = settings.keys_rotated_on.strip()
    keys = (_item("keys", True, f"Done on {rotated}.") if rotated
            else _item("keys", False, "Replace the keys you pasted in chat, then set KEYS_ROTATED_ON in Railway."))
    locked = (_item("locked", True, "Only someone with your link can open this page.") if settings.dashboard_token
              else _item("locked", False, "Set DASHBOARD_TOKEN in Railway to a long random password."))

    live_on = settings.trading_mode == "live" and settings.live_confirm == LIVE_CONFIRM_PHRASE
    before = [edge, paper, wallet, keys, locked]
    first_five = all(i["done"] for i in before)
    live = (_item("live", True, "On: the bot trades real money.") if live_on
            else _item("live", False, "Last step, only after 1–5."))

    checks = [*before, live]
    done = sum(i["done"] for i in checks)
    ready = done == len(checks)
    warning = None
    if live_on and not first_five:
        warning = "Real money is ON before every step above is done. Think about switching back to paper."
    return {"ready": ready, "done": done, "total": len(checks),
            "headline": "Ready" if ready else f"Not ready yet — {done} of {len(checks)} done",
            "warning": warning, "items": checks}
