"""The learning card's data (docs/LEARNING.md §9): :func:`learning_card_state` for the dashboard.

A pure READ of ``DATA_DIR/learn/learn.db`` (opened read-only; a missing file is never created), cached
for 60 s, with no network calls. It NEVER raises: any problem gives a well-formed state.

States (phase 1): ``off`` (LEARN_ENABLED=false), ``collecting`` (no evidence yet: "Collecting data,
day N"), ``practice`` (variants are being scored; nothing can be promoted before phase 2) and
``unavailable`` (learn.db unreadable). Phase 2 adds ``cash | paper_champion | live_ready | live``.

Every key of :data:`EMPTY_KEYS` is always present; unknown values are None. Strings are plain words
built from this module and variant names; the dashboard still scrubs them and inserts them with
``textContent``.
"""

from __future__ import annotations

import copy
import logging
import math
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nightcrawler.learn.gate import PLACEBO_MAX_MEAN
from nightcrawler.learn.store import LearnStore, db_path, learn_dir
from nightcrawler.learn.variants import registrations_this_week

__all__ = ["CACHE_S", "EMPTY_KEYS", "learning_card_state", "clear_cache"]

log = logging.getLogger("nightcrawler.learn.card")

CACHE_S = 60.0
EMPTY_KEYS = ("state", "headline", "subline", "frozen", "updated_at", "paper_variant", "champion", "top", "placebo",
              "data", "events", "budget", "live")
_PRACTICE = "Paper practises with the default strategy (unproven). Promotions start in phase 2."
_EVENT_TEXT = {"register": "started testing {name}", "tape_seal": "sealed the {day} data ({completeness}% complete)",
               "scoreboard": "scored every idea for {day}"}
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _empty(state: str, headline: str, cap_gb: float | None) -> dict[str, Any]:
    return {
        "state": state, "headline": headline, "subline": _PRACTICE, "frozen": None, "updated_at": None,
        "paper_variant": {"name": "default strategy", "hash12": None, "label": "practice"},
        "champion": None, "top": [], "placebo": None,
        "data": {"coins_yesterday": 0, "coins_total": 0, "completeness_pct": None, "cost_gap_pp": None,
                 "fidelity_pct": None, "disk_gb": 0.0, "cap_gb": cap_gb, "day": 1},
        "events": [], "budget": {"registrations_this_week": 0, "live_attempts": 0, "trials_total": None},
        "live": {"ready": False, "armed": False, "why": "real money needs proof on real quotes and your OK (phase 2)"},
    }


def learning_card_state(settings: Any, now: float) -> dict[str, Any]:
    """The card's state (see the module docstring). Never raises."""
    try:
        cap = float(getattr(settings, "learn_disk_cap_gb", 3.0))
        if not getattr(settings, "learn_enabled", True):
            return _empty("off", "Learning is off (LEARN_ENABLED=false)", cap)
        path = db_path(settings.data_dir)
        key = str(path)
        with _lock:
            hit = _cache.get(key)
            if hit is not None and 0 <= now - hit[0] < CACHE_S:
                return copy.deepcopy(hit[1])
        state = _build(path, settings, now, cap)
        with _lock:
            _cache[key] = (now, state)
        return copy.deepcopy(state)
    except Exception as exc:  # the dashboard must always render
        log.warning("learning_card_failed error=%s", type(exc).__name__)
        return _empty("unavailable", "Learning data unavailable right now", None)


def _utc_day(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _build(path: Path, settings: Any, now: float, cap: float) -> dict[str, Any]:
    if not path.exists():
        return _empty("collecting", "Collecting data, day 1", cap)
    try:
        store = LearnStore(path, readonly=True)
    except Exception as exc:
        log.warning("learning_card_unreadable error=%s", type(exc).__name__)
        return _empty("unavailable", "Learning data unavailable right now", cap)
    with store:
        try:
            return _from_store(store, settings, now, cap)
        except Exception as exc:
            log.warning("learning_card_unreadable error=%s", type(exc).__name__)
            return _empty("unavailable", "Learning data unavailable right now", cap)


def _from_store(store: LearnStore, settings: Any, now: float, cap: float) -> dict[str, Any]:
    coins = store.coins()
    first_seen = min((c["first_seen_ts"] for c in coins), default=None)
    day_n = 1 if first_seen is None else (_utc_day(now) - _utc_day(first_seen)).days + 1
    state = _empty("collecting", f"Collecting data, day {day_n}", cap)
    yesterday = (_utc_day(now).timestamp() - 86400.0)
    y_label = datetime.fromtimestamp(yesterday, tz=timezone.utc).strftime("%Y-%m-%d")
    counts = store.day_counts(y_label)
    state["data"].update({
        "coins_yesterday": counts["coins"], "coins_total": len(coins), "day": day_n,
        "completeness_pct": round(100.0 * counts["closed"] / counts["coins"], 1)
        if counts["coins"] and not counts["open"] else None,
        "disk_gb": round(_disk_bytes(learn_dir(settings.data_dir)) / 1e9, 3)})
    state["budget"].update({"registrations_this_week": registrations_this_week(store, now),
                            "trials_total": store.trials_total()})
    state["events"] = _events(store)
    board_day = store.latest_scoreboard_day()
    rows = store.scoreboard(board_day) if board_day else []
    if not rows or not any(r.get("n") for r in rows):
        return state
    state.update({"state": "practice", "headline": "Holding cash: nothing has proven an edge yet",
                  "updated_at": max(r["updated_ts"] for r in rows)})
    rate = _trades_per_day(store, rows, now)
    ideas = sorted((r for r in rows if not r.get("control")),
                   key=lambda r: (-(r.get("proof") or 0.0), r["variant_hash"]))
    state["top"] = [_row(r, rate.get(r["variant_hash"])) for r in ideas[:3]]
    placebo = next((r for r in rows if r.get("control")), None)
    if placebo is not None:
        mean = placebo.get("mean")
        state["placebo"] = {"n": int(placebo.get("n") or 0), "mean_pct": _pct(mean),
                            "ok": mean is None or mean <= PLACEBO_MAX_MEAN or not placebo.get("n")}
    return state


def _pct(x: Any) -> float | None:
    return round(100.0 * float(x), 2) if isinstance(x, (int, float)) and math.isfinite(x) else None


def _row(r: dict[str, Any], per_day: float | None) -> dict[str, Any]:
    eta_trades = r.get("eta_trades")
    eta_days = round(eta_trades / per_day, 1) if eta_trades is not None and per_day else None
    if eta_trades is None:
        eta = "unlikely"
    elif eta_days is None or eta_days > 60:
        eta = "months"
    else:
        eta = f"~{max(1, round(eta_days))} days"
    return {"name": r.get("name") or "", "hash12": r["variant_hash"][:12], "n": int(r.get("n") or 0),
            "mean_pct": _pct(r.get("mean")), "proof": round(float(r.get("proof") or 0.0), 4), "eta_days": eta_days,
            "eta": eta, "status": r.get("status") or ""}


def _trades_per_day(store: LearnStore, rows: list[dict[str, Any]], now: float) -> dict[str, float]:
    """Evidence per day over the last 7 days, per variant (for the ETA)."""
    out = {}
    for r in rows:
        recent = [e for e in store.evidence(r["variant_hash"]) if e["exit_ts"] >= now - 7 * 86400]
        out[r["variant_hash"]] = len(recent) / 7.0
    return out


def _events(store: LearnStore) -> list[dict[str, Any]]:
    events = []
    for row in reversed(store.outbox()):
        template = _EVENT_TEXT.get(row["event"])
        if template is None:
            continue
        p = row["payload"]
        share = p.get("completeness")
        text = template.format(name=p.get("name") or "an idea", day=p.get("day") or "?",
                               completeness=round(100 * share) if isinstance(share, (int, float)) else "?")
        events.append({"ts": row["created_ts"], "text": text, "seq": row["receipt_seq"]})
        if len(events) == 10:
            break
    return events


def _disk_bytes(root: Path) -> int:
    total = 0
    for folder, _, files in os.walk(root):
        for name in files:
            try:
                total += (Path(folder) / name).stat().st_size
            except OSError:
                continue
    return total
