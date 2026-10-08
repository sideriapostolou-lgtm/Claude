"""The learning card's data (docs/LEARNING.md §9): :func:`learning_card_state` for the dashboard.

A pure READ of ``DATA_DIR/learn/learn.db`` (opened read-only; a missing file is never created), cached
for 60 s, with no network calls. It NEVER raises: any problem gives a well-formed state.

States (phase 1): ``off`` (LEARN_ENABLED=false), ``collecting`` (no evidence yet: "Collecting data,
day N"), ``practice`` (variants are being scored - "Practice: promotions start in phase 2"; nothing can
be promoted before phase 2) and ``unavailable`` (learn.db unreadable). Phase 2 adds
``cash | paper_champion | live_ready | live``.

What the one-page dashboard reads (``pagestate.learning_card``):

* ``state``, ``headline`` (the state line) and ``subline`` - plain strings;
* ``variants`` - the top 3 ideas by proof, then the placebo: ``{"name", "hash12", "n", "avg"`` (net
  percent per trade, None before any trade) ``, "proof"`` (0..1, ``log E / log threshold``) ``,
  "status", "control"}``;
* ``data`` (= ``data_line``) - one line: coins taped, days of data, disk used of the cap;
* ``updated_at`` - when the scoreboard was written.

The structured numbers stay in ``stats`` (coins yesterday/total, completeness, days, disk, cap),
``top``, ``placebo``, ``events``, ``budget``, ``live``, ``paper_variant`` and ``champion`` (§9).
Every key of :data:`EMPTY_KEYS` is always present; unknown values are None. Every string is scrubbed
(:func:`_scrub`: secrets redacted, control characters removed, at most :data:`TEXT_MAX` characters);
the dashboard still inserts them with ``textContent``.
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
from nightcrawler.logging_setup import redact_text

__all__ = ["CACHE_S", "TEXT_MAX", "NAME_MAX", "EMPTY_KEYS", "PRACTICE_HEADLINE", "learning_card_state",
           "clear_cache"]

log = logging.getLogger("nightcrawler.learn.card")

CACHE_S = 60.0
TEXT_MAX = 200
NAME_MAX = 60
EMPTY_KEYS = ("state", "headline", "subline", "frozen", "updated_at", "paper_variant", "champion", "top", "placebo",
              "variants", "data", "data_line", "stats", "events", "budget", "live")
PRACTICE_HEADLINE = "Practice: promotions start in phase 2"
_SUBLINE = "No idea has proven an edge yet. Paper practises with the default strategy (unproven)."
_EVENT_TEXT = {"register": "started testing {name}", "tape_seal": "sealed the {day} data ({completeness}% complete)",
               "scoreboard": "scored every idea for {day}"}
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _empty(state: str, headline: str, cap_gb: float | None) -> dict[str, Any]:
    return {
        "state": state, "headline": headline, "subline": _SUBLINE, "frozen": None, "updated_at": None,
        "paper_variant": {"name": "default strategy", "hash12": None, "label": "practice"},
        "champion": None, "top": [], "placebo": None, "variants": [], "data": "", "data_line": "",
        "stats": {"coins_yesterday": 0, "coins_total": 0, "completeness_pct": None, "cost_gap_pp": None,
                  "fidelity_pct": None, "disk_gb": 0.0, "cap_gb": cap_gb, "day": 1, "days": 0},
        "events": [], "budget": {"registrations_this_week": 0, "live_attempts": 0, "trials_total": None},
        "live": {"ready": False, "armed": False, "why": "real money needs proof on real quotes and your OK (phase 2)"},
    }


def learning_card_state(settings: Any, now: float) -> dict[str, Any]:
    """The card's state (see the module docstring). Never raises."""
    try:
        cap = float(getattr(settings, "learn_disk_cap_gb", 3.0))
        secrets = _secrets(settings)
        if not getattr(settings, "learn_enabled", True):
            return _finish(_empty("off", "Learning is off (LEARN_ENABLED=false)", cap), secrets)
        path = db_path(settings.data_dir)
        key = str(path)
        with _lock:
            hit = _cache.get(key)
            if hit is not None and 0 <= now - hit[0] < CACHE_S:
                return copy.deepcopy(hit[1])
        state = _finish(_build(path, settings, now, cap), secrets)
        with _lock:
            _cache[key] = (now, state)
        return copy.deepcopy(state)
    except Exception as exc:  # the dashboard must always render
        log.warning("learning_card_failed error=%s", type(exc).__name__)
        return _finish(_empty("unavailable", "Learning data unavailable right now", None), ())


def _secrets(settings: Any) -> tuple[str, ...]:
    values = getattr(settings, "secret_values", None)
    try:
        return tuple(values()) if callable(values) else ()
    except Exception:
        return ()


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
    state["stats"].update({
        "coins_yesterday": counts["coins"], "coins_total": len(coins), "day": day_n, "days": len(store.days()),
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
    state.update({"state": "practice", "headline": PRACTICE_HEADLINE,
                  "updated_at": max(r["updated_ts"] for r in rows)})
    rate = _trades_per_day(store, rows, now)
    ideas = sorted((r for r in rows if not r.get("control")),
                   key=lambda r: (-(r.get("proof") or 0.0), r["variant_hash"]))
    state["top"] = [_row(r, rate.get(r["variant_hash"])) for r in ideas[:3]]
    placebo = next((r for r in rows if r.get("control")), None)
    if placebo is not None:
        mean = placebo.get("mean")
        state["placebo"] = {"name": placebo.get("name") or "random entry (control)",
                            "hash12": placebo["variant_hash"][:12], "n": int(placebo.get("n") or 0),
                            "mean_pct": _pct(mean),
                            "ok": mean is None or mean <= PLACEBO_MAX_MEAN or not placebo.get("n")}
    return state


def _finish(state: dict[str, Any], secrets: tuple[str, ...]) -> dict[str, Any]:
    """Add what the page reads (``variants``, the data line) and scrub every string."""
    state["variants"] = [{"name": t["name"], "hash12": t["hash12"], "n": t["n"], "avg": t["mean_pct"],
                          "proof": float(t["proof"]), "status": t["status"], "control": False}
                         for t in state["top"]]
    p = state["placebo"]
    if p is not None:
        state["variants"].append({"name": p["name"], "hash12": p["hash12"], "n": p["n"], "avg": p["mean_pct"],
                                  "proof": 0.0, "status": "control", "control": True})
    stats = state["stats"]
    if stats["cap_gb"] is None:
        line = "Data: unavailable right now"
    else:
        days = stats["days"]
        line = (f"Data: {stats['coins_total']:,} coins taped · {days} day{'' if days == 1 else 's'} · "
                f"{stats['disk_gb']:.3f} GB of {stats['cap_gb']:g} GB")
    state["data"] = state["data_line"] = line
    return _scrub(state, secrets)


def _scrub(value: Any, secrets: tuple[str, ...], limit: int = TEXT_MAX) -> Any:
    if isinstance(value, str):
        text = "".join(ch if ch.isprintable() else " " for ch in redact_text(value, secrets))
        return text if len(text) <= limit else text[:limit - 1] + "…"
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _scrub(v, secrets, NAME_MAX if k == "name" else limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, secrets, limit) for v in value]
    return value


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
