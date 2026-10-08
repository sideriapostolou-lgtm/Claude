"""Team room: a live, read-only view of every bot "team member" at work (owner: O6).

Served by :class:`nightcrawler.dashboard.DashboardServer` behind the same ``DASHBOARD_TOKEN`` gate,
security headers and secret scrubbing as ``/api/state``:

* ``/team`` -> :func:`render_team_html`: one self-contained, mobile-first page (inline CSS/JS, no external
  assets, dark/light via ``prefers-color-scheme``, refreshes every :data:`REFRESH_S` seconds by fetching
  ``/api/team``; every value is inserted with ``textContent``).
* ``/api/team`` -> :func:`build_team_state` (JSON, schema below).

REAL DATA ONLY. Every number and event comes from the ledger (candidates, safety, decisions, fills,
positions, equity, receipts, kv) or from the engine's own status dict (kv ``engine.status``, rewritten
every 15 s). Nothing is animated to look busy: a member is ``working`` only when a recorded event, an
equity snapshot or a since-boot counter that MOVED between two reads proves it acted within its window
(:func:`derive_status`). Unknown values are ``null`` and the page says "not available yet".

Status chips (first match wins): ``blocked`` (engine silent/stopped, or the member is stopped by a real
condition: kill switch, halt, daily loss limit, judge budget, broken receipt chain) -> ``working`` (last
activity within the member's window) -> ``waiting`` (it needs something upstream first, or the engine has
not started) -> ``idle``.

Engine facts that live only in memory are read from kv when the engine persists them:
``engine.watchlist`` (watched coins with their last strategy reason) and ``crawler.nursery`` (too-young
coins waiting) win when present; otherwise the same facts come from ``engine.status`` (``watching``,
``crawler.nursery``); otherwise they are ``null``.

Deployed commit: only ``RAILWAY_GIT_COMMIT_SHA`` and ``RAILWAY_GIT_COMMIT_MESSAGE`` are read from the
environment (:func:`deploy_info`), never anything else.

``/api/team`` schema (lists capped: events <= :data:`EVENTS_MAX`, bars <= 5, texts <= 160 chars)::

    {
      "version": str, "generated_at": float, "mode": "PAPER"|"LIVE", "refresh_s": int,
      "kill": "off"|"stop"|"sell_all", "halted": {"halted": bool, "reason": str|null},
      "engine": {"health": "running"|"not_started"|"stale"|"stopped", "heartbeat": float|null,
                 "started_at": float|null, "uptime_s": float|null},
      "bank": {"sol", "usd", "start_sol", "change_sol", "change_pct", "change_usd"},   # floats|null
      "team": {"working": int, "idle": int, "waiting": int, "blocked": int},
      "panels": [{"id", "name", "role", "status", "why", "last_activity": float|null,
                  "headline": {"value", "unit", "label"},
                  "stats": [{"label", "value", "unit", "ts"?}],
                  "events": [{"ts": float, "text": str, "tone": "good"|"bad"|"neutral"}],   # newest first
                  "bars"?: [{"label", "value": fraction|null, "text"}], "bars_empty"?: str,
                  "meter"?: {"used", "limit", "fraction", "text"}, "hash"?: {"head", "short", "explainer"}}]
    }

Units: ``count``, ``sol``, ``usd``, ``pct`` (percent), ``ts`` (epoch s), ``dur`` (seconds), ``text``.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from nightcrawler import __version__
from nightcrawler.clock import Clock, RealClock
from nightcrawler.config import Settings
from nightcrawler.dashboard import build_state, scrub
from nightcrawler.ledger import Ledger
from nightcrawler.logging_setup import get_logger, redact_text
from nightcrawler.models import LAMPORTS_PER_SOL, Decision, Fill

__all__ = [
    "ENGINE_STALE_S",
    "EVENTS_MAX",
    "PANELS",
    "REFRESH_S",
    "TEAM_CSP",
    "TeamRoom",
    "build_team_state",
    "deploy_info",
    "derive_status",
    "proximity",
    "render_team_html",
]

log = get_logger(__name__)

REFRESH_S = 10
#: The engine rewrites its heartbeat every 15 s; older than this = silent (same as the dashboard chip).
ENGINE_STALE_S = 180.0
EVENTS_MAX = 5
BARS_MAX = 5
TEXT_MAX = 160
HOUR_S = 3600.0
DAY_S = 86_400.0
#: Kv keys another component may persist with in-memory engine facts (preferred when present).
KV_WATCHLIST = "engine.watchlist"
KV_NURSERY = ("crawler.nursery", "engine.nursery")

#: (id, name, one-line role) in display order.
PANELS: tuple[tuple[str, str, str], ...] = (
    ("crawler", "Crawler", "Finds brand-new coins on Jupiter, GeckoTerminal and DexScreener"),
    ("cocoon", "Cocoon", "Scam filter: holders, mint and freeze authority, LP lock, RugCheck, Shield"),
    ("radar", "Radar", "Looks for big sells by the creator, insiders and top holders"),
    ("judge", "Jev", "AI judge: a last yes or no on every setup that passed the rules"),
    ("strategy", "Strategy", "Watches passed coins for a deep dip followed by a rebound"),
    ("broker", "Broker", "Buys and sells at live Jupiter quotes (paper: simulated fills)"),
    ("risk", "Risk", "Sizes trades and enforces the daily loss, drawdown and position limits"),
    ("receipts", "Receipts", "Writes every decision and fill into a tamper-evident hash chain"),
    ("upgrades", "Upgrades", "What is deployed right now and how long it has been running"),
)
_ROLES = {pid: (name, role) for pid, name, role in PANELS}

#: How recent an activity must be for a member to count as working (seconds); see ``_window``.
WORKING_WINDOW_S = {"crawler": 300.0, "cocoon": 600.0, "radar": 1800.0, "judge": 1800.0, "strategy": 300.0,
                    "broker": 1800.0, "risk": 300.0, "receipts": 600.0, "upgrades": 600.0}

#: Cocoon rule ids (``[rule]`` prefix of a hard-fail reason) in plain words.
RULE_LABELS = {
    "mint_authority": "Creator can still mint more", "freeze_authority": "Creator can freeze wallets",
    "token2022_ext": "Dangerous token extensions", "rugged": "Already rugged",
    "rugcheck_danger": "RugCheck danger flags", "top10": "Top 10 wallets hold too much",
    "single_holder": "One wallet holds too much", "creator_holding": "Creator still holds too much",
    "insiders": "Insider wallet network", "serial_launcher": "Serial coin launcher",
    "shield": "Jupiter Shield warning", "lp_unlocked": "Liquidity not locked",
    "source_unavailable": "Could not verify (data source down)", "other": "Other",
}
_SIGNAL_ACTIONS = ("enter", "reject_risk", "reject_radar", "reject_judge", "reject_quote")
_RADAR_ACTIONS = ("enter", "reject_radar", "reject_judge", "reject_quote", "exit", "exit_partial")
_STOPPED_BY = {"reject_risk": "risk", "reject_radar": "radar", "reject_judge": "the judge",
               "reject_quote": "the quote"}
_DIP = re.compile(r"dip (\d+(?:\.\d+)?)% < required (\d+(?:\.\d+)?)%")
_DIP_REACHED = ("chasing", "buyers not back", "buy/sell ratio", "setup, but", "dip-rebound")
RECEIPTS_EXPLAINER = ("Every decision and fill is chained to the one before it by a SHA-256 fingerprint the "
                      "moment it happens, so no result can be edited with hindsight without breaking the chain.")


# =========================================================================== small helpers


def derive_status(now: float, last_activity: float | None, window_s: float, *, blocked: str | None = None,
                  waiting: str | None = None, idle: str | None = None) -> tuple[str, str]:
    """``(status, why)``: ``blocked`` > ``working`` (activity within ``window_s``) > ``waiting`` > ``idle``.

    A working member's ``why`` is empty: the page shows how long ago it acted from ``last_activity``.
    """
    if blocked:
        return "blocked", blocked
    if last_activity is not None and now - last_activity <= window_s:
        return "working", ""
    if waiting:
        return "waiting", waiting
    if idle:
        return "idle", idle
    return "idle", "nothing new recently" if last_activity is not None else "nothing recorded yet"


def proximity(last_signal: str | None) -> tuple[float | None, str]:
    """How close a watched coin is to the entry setup, parsed from the strategy's own reason text.

    ``(fraction of the required dip reached, capped at 1 | None when unknown, short text)``.
    """
    if not last_signal:
        return None, "not checked yet"
    match = _DIP.search(last_signal)
    if match:
        dip, required = float(match.group(1)), float(match.group(2))
        return (min(1.0, dip / required) if required > 0 else None), f"dip {dip:g}% of {required:g}% needed"
    if last_signal.startswith(_DIP_REACHED):
        return 1.0, "dip reached · " + last_signal
    return None, last_signal


def deploy_info(environ: Mapping[str, str], secrets: Iterable[str] = ()) -> dict[str, str | None]:
    """The deployed commit from Railway's two git variables ONLY (no other variable is ever read)."""
    sha = (environ.get("RAILWAY_GIT_COMMIT_SHA") or "").strip()
    message = redact_text((environ.get("RAILWAY_GIT_COMMIT_MESSAGE") or "").strip(), tuple(secrets))
    first = message.splitlines()[0].strip() if message else ""
    return {"commit": sha[:12] or None, "message": _clip(first, 120) or None}


def _clip(text: str, limit: int = TEXT_MAX) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(number) if number is not None else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _latest(*stamps: float | None) -> float | None:
    known = [s for s in stamps if s is not None]
    return max(known) if known else None


def _short(mint: str) -> str:
    return f"{mint[:4]}…{mint[-4:]}" if len(mint) > 12 else mint


def _usd_compact(value: float | None) -> str:
    if value is None:
        return "$?"
    if abs(value) >= 1e6:
        return f"${value / 1e6:.1f}M"
    if abs(value) >= 1e3:
        return f"${value / 1e3:.0f}k"
    return f"${value:,.0f}"


def _price(value: float | None) -> str:
    if value is None or value <= 0:
        return "$?"
    if value >= 1:
        return f"${value:.4f}"
    return f"${value:.4g}" if value >= 1e-6 else f"${value:.2e}"


def _stat(label: str, value: Any, unit: str = "count", ts: float | None = None) -> dict[str, Any]:
    row = {"label": label, "value": value, "unit": unit}
    if ts is not None:
        row["ts"] = ts
    return row


def _headline(value: Any, unit: str, label: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "label": label}


def _verdict(d: Decision) -> dict[str, Any] | None:
    v = d.verdict
    if v is None:
        return None
    return v.to_dict() if hasattr(v, "to_dict") else _dict(v)


def _counter_activity(memory: dict[str, Any] | None, key: str, value: Any, stamp: float | None) -> float | None:
    """When a since-boot counter in ``engine.status`` CHANGED between two reads, the member acted in
    between: remember the status stamp of the read that saw it move. An unchanged counter proves nothing."""
    if memory is None or _num(value) is None or stamp is None:
        return None
    seen = memory.get(key)
    if seen is None:
        memory[key] = [value, None]
    elif seen[0] != value:
        memory[key] = [value, stamp]
    return memory[key][1]


# =========================================================================== state


@dataclass
class _Ctx:
    """Everything the panel builders share for one ``/api/team`` answer."""

    ledger: Any
    settings: Settings
    now: float
    mode: str
    state: dict[str, Any]
    status: dict[str, Any]
    memory: dict[str, Any] | None
    secrets: tuple[str, ...]
    engine_block: str | None = None
    engine_wait: str | None = None
    open_positions: int = 0

    @property
    def status_ts(self) -> float | None:
        return _num(self.status.get("ts"))

    def text(self, value: Any, limit: int = TEXT_MAX) -> str:
        """Secrets are redacted BEFORE clipping, so a clipped secret can never slip past the scrub."""
        return _clip(redact_text(str(value), self.secrets), limit)

    def event(self, ts: float, text: str, tone: str = "neutral") -> dict[str, Any]:
        return {"ts": ts, "text": self.text(text), "tone": tone}

    def counter(self, key: str, value: Any) -> float | None:
        return _counter_activity(self.memory, key, value, self.status_ts)

    def derive(self, pid: str, last: float | None, *, blocked: str | None = None, waiting: str | None = None,
               idle: str | None = None) -> tuple[str, str]:
        status, why = derive_status(self.now, last, _window(pid, self.settings),
                                    blocked=self.engine_block or blocked,
                                    waiting=self.engine_wait or waiting, idle=idle)
        return status, self.text(why)

    def decisions(self, actions: Iterable[str], limit: int = 50) -> list[Decision]:
        return self.ledger.decisions(limit=limit, actions=list(actions))


def _window(pid: str, settings: Settings) -> float:
    base = WORKING_WINDOW_S[pid]
    if pid == "crawler":
        return max(base, 4 * settings.discovery_interval_s)
    if pid == "strategy":
        return max(base, 4 * settings.watch_interval_s)
    if pid == "risk":
        return max(base, 3 * settings.equity_interval_s)
    return base


def _panel(pid: str, status_why: tuple[str, str], last: float | None, headline: dict[str, Any],
           stats: list[dict[str, Any]], events: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    name, role = _ROLES[pid]
    status, why = status_why
    if extra.pop("sort", True):
        events = sorted(events, key=lambda e: e["ts"], reverse=True)
    return {"id": pid, "name": name, "role": role, "status": status, "why": why, "last_activity": last,
            "headline": headline, "stats": stats, "events": events[:EVENTS_MAX], **extra}


def _select(ledger: Any, sql: str, params: Iterable[Any] = ()) -> list[Any]:
    """A read-only SELECT through the ledger's own locked connection (the ledger has no public helper
    for the newest candidates; this view never writes)."""
    return ledger._rows(sql, list(params))


def _engine_health(state: dict[str, Any], status: dict[str, Any], now: float) -> tuple[str, str | None]:
    heartbeat = _num(state["engine"]["heartbeat"])
    if heartbeat is None:
        return "not_started", "engine has not started yet"
    if status.get("state") == "stopped":
        return "stopped", "engine stopped"
    age = now - heartbeat
    if age > ENGINE_STALE_S:
        return "stale", f"engine silent for {age / 60:.0f} min"
    return "running", None


def build_team_state(ledger: Any, settings: Settings, now: float, engine_status: dict[str, Any] | None = None,
                     *, verify_cache: dict[str, Any] | None = None, memory: dict[str, Any] | None = None,
                     deploy: dict[str, str | None] | None = None) -> dict[str, Any]:
    """Assemble ``/api/team`` (schema in the module docstring) from the ledger ONLY (no network calls).

    ``engine_status`` overrides kv ``engine.status``; ``verify_cache`` throttles chain verification
    (see ``dashboard.build_state``); ``memory`` is a dict kept between calls so a since-boot counter that
    moved counts as activity; ``deploy`` is :func:`deploy_info` (read once at startup by :class:`TeamRoom`).
    """
    secrets = tuple(settings.secret_values())
    state = build_state(ledger, settings, now, verify_cache)
    status = engine_status if isinstance(engine_status, dict) else _dict(state["engine"]["status"])
    mode = "live" if settings.is_live else "paper"
    ctx = _Ctx(ledger=ledger, settings=settings, now=now, mode=mode, state=state, status=status, memory=memory,
               secrets=secrets, open_positions=len(state["positions"]))
    health, problem = _engine_health(state, status, now)
    if health in ("stale", "stopped"):
        ctx.engine_block = problem
    elif health == "not_started":
        ctx.engine_wait = problem
    started_at = _num(state["engine"]["started_at"])
    panels = [_crawler(ctx), _cocoon(ctx), _radar(ctx), _judge(ctx), _strategy(ctx), _broker(ctx), _risk(ctx),
              _receipts(ctx), _upgrades(ctx, deploy or {"commit": None, "message": None}, started_at)]
    team = {"working": 0, "idle": 0, "waiting": 0, "blocked": 0}
    for panel in panels:
        team[panel["status"]] += 1
    out = {
        "version": __version__,
        "generated_at": now,
        "mode": mode.upper(),
        "refresh_s": REFRESH_S,
        "kill": state["kill"],
        "halted": state["halted"],
        "engine": {"health": health, "heartbeat": state["engine"]["heartbeat"], "started_at": started_at,
                   "uptime_s": now - started_at if started_at is not None and health == "running" else None},
        "bank": _bank(ctx),
        "team": team,
        "panels": panels,
    }
    return scrub(out, secrets)


def _bank(ctx: _Ctx) -> dict[str, float | None]:
    eq = ctx.state["equity"]
    start = _num(ctx.ledger.get_kv(f"{ctx.mode}.start_lamports"))
    start_sol = start / LAMPORTS_PER_SOL if start else None
    change = eq["pnl_total_sol"]
    return {"sol": eq["sol"], "usd": eq["usd"], "start_sol": start_sol, "change_sol": change,
            "change_pct": change / start_sol * 100.0 if change is not None and start_sol else None,
            "change_usd": eq["pnl_total_usd"]}


# =========================================================================== panels


def _nursery(ctx: _Ctx) -> int | None:
    for key in KV_NURSERY:
        value = ctx.ledger.get_kv(key)
        if isinstance(value, dict):
            for name in ("count", "size", "total"):
                if _num(value.get(name)) is not None:
                    return int(value[name])
            return len(value)
        if isinstance(value, list):
            return len(value)
        if _num(value) is not None:
            return int(value)
    return _int(_dict(ctx.status.get("crawler")).get("nursery"))


def _crawler(ctx: _Ctx) -> dict[str, Any]:
    crawler = _dict(ctx.status.get("crawler"))
    rows = _select(ctx.ledger, "SELECT data, first_seen FROM candidates ORDER BY first_seen DESC LIMIT ?",
                   (EVENTS_MAX,))
    newest = _select(ctx.ledger, "SELECT MAX(last_seen) FROM candidates")[0][0]
    events = []
    for data, first_seen in rows:
        c = _dict(json.loads(data))
        bits = [str(c.get("symbol") or _short(str(c.get("mint", ""))))]
        age = _num(c.get("age_min"))
        if age is not None:
            bits.append(f"{age:.0f} min old" if age < 120 else f"{age / 60:.1f} h old")
        if _num(c.get("mcap_usd")) is not None:
            bits.append(f"mcap {_usd_compact(c['mcap_usd'])}")
        sources = [str(s) for s in c.get("sources") or []][:2]
        if sources:
            bits.append("via " + ", ".join(sources))
        events.append(ctx.event(first_seen, " · ".join(bits)))
    errors = _dict(crawler.get("feed_errors"))
    last = _latest(_num(newest), ctx.counter("crawler.polls", crawler.get("polls")))
    status = ctx.derive("crawler", last, idle="no new coin passed the cheap prefilter recently")
    return _panel("crawler", status, last,
                  _headline(ctx.ledger.candidate_count(since=ctx.now - HOUR_S), "count",
                            "new coins handed to the scam filter, last hour"),
                  [_stat("Last 24 h", ctx.state["activity"]["candidates_24h"]),
                   _stat("Too young, waiting", _nursery(ctx)),
                   _stat("Prefilter rejections since boot", _int(crawler.get("rejected"))),
                   _stat("Feed errors since boot", sum(int(v) for v in errors.values() if _num(v) is not None)
                         if crawler else None),
                   _stat("Polls since boot", _int(crawler.get("polls")))],
                  events)


def _cocoon(ctx: _Ctx) -> dict[str, Any]:
    hour = ctx.ledger.decision_counts(since=ctx.now - HOUR_S)
    day = ctx.state["rejections"]
    recent = ctx.decisions(("watch", "reject_cocoon"), limit=EVENTS_MAX)
    newest_pass = ctx.decisions(("watch",), limit=1)
    events = []
    for d in recent:
        name = d.symbol or _short(d.mint)
        if d.action == "watch":
            events.append(ctx.event(d.ts, f"PASS {name} · {d.reason}", "good"))
        else:
            events.append(ctx.event(d.ts, f"REJECT {name} · {d.reason}", "bad"))
    rules = list(ctx.state["cocoon_rules"].items())[:BARS_MAX]
    top = rules[0][1] if rules else 0
    bars = [{"label": RULE_LABELS.get(rule, rule), "value": n / top if top else None, "text": str(n), "note": None}
            for rule, n in rules]
    counters = _dict(ctx.status.get("counters"))
    last = _latest(recent[0].ts if recent else None, ctx.counter("cocoon_checked", counters.get("cocoon_checked")))
    queue = _int(ctx.status.get("cocoon_queue"))
    status = ctx.derive("cocoon", last, waiting="waiting for the crawler to hand over a coin" if not queue else None)
    passed, rejected = day.get("watch", 0), day.get("reject_cocoon", 0)
    pass_row = newest_pass[0] if newest_pass else None
    return _panel("cocoon", status, last,
                  _headline(f"{passed} passed · {rejected} rejected", "text", "last 24 h"),
                  [_stat("Passed 1 h", hour.get("watch", 0)), _stat("Rejected 1 h", hour.get("reject_cocoon", 0)),
                   _stat("Passed 24 h", passed), _stat("Rejected 24 h", rejected),
                   _stat("Waiting in queue", queue),
                   _stat("Newest pass", ctx.text(pass_row.symbol or _short(pass_row.mint), 40) if pass_row else None,
                         "text", pass_row.ts if pass_row else None)],
                  events, bars=bars, bars_empty="No coin failed the scam filter in the last 24 h.")


def _radar_line(d: Decision) -> tuple[str, str]:
    """``(text, tone)`` for one decision that carries a radar scan (or a radar-triggered exit)."""
    name = d.symbol or _short(d.mint)
    radar = _dict(d.inputs.get("radar"))
    if not radar:
        return f"SOLD {name} · {d.reason}", "bad"
    if radar.get("error"):
        return f"NO SCAN {name} · source down: {radar['error']}", "bad"
    if radar.get("flagged"):
        return f"FLAGGED {name} · " + "; ".join(str(r) for r in radar.get("reasons") or []), "bad"
    sells = _num(radar.get("big_sells_usd")) or 0.0
    return (f"CLEAR {name} · {int(_num(radar.get('trades_seen')) or 0)} big trades, sells ${sells:,.0f} "
            f"in {_num(radar.get('window_min')) or 0:g} min"), "good"


def _radar(ctx: _Ctx) -> dict[str, Any]:
    rows = ctx.decisions(_RADAR_ACTIONS, limit=200)  # newest first
    scans = [d for d in rows if _dict(d.inputs.get("radar"))]
    exits = [d for d in rows if d.action in ("exit", "exit_partial") and d.reason.startswith("radar")]
    events = [ctx.event(d.ts, *_radar_line(d)) for d in [*scans[:EVENTS_MAX], *exits[:EVENTS_MAX]]]
    day_scans = [d for d in scans if d.ts >= ctx.now - DAY_S]
    flagged = [d for d in day_scans if d.action == "reject_radar"] + [d for d in exits if d.ts >= ctx.now - DAY_S]
    reasons = " ".join(" ".join(str(r) for r in _dict(d.inputs.get("radar")).get("reasons") or []) or d.reason
                       for d in flagged).lower()
    last = scans[0].ts if scans else None
    held = ctx.open_positions
    status = ctx.derive("radar", last, waiting="waiting for a coin to reach a buy setup" if not held else None,
                        idle=(f"re-checks {held} open position(s) every {ctx.settings.radar_interval_s:g} s; "
                              "only recorded when it forces a sale") if held else None)
    return _panel("radar", status, last,
                  _headline(len(flagged), "count", "big sells flagged, last 24 h"),
                  [_stat("Scans before a buy (24 h)", len(day_scans)), _stat("Last scan", last, "ts"),
                   _stat("Creator sold", reasons.count("creator sold")),
                   _stat("Insiders / top holders sold", reasons.count("insiders sold")),
                   _stat("Big sells vs liquidity", reasons.count("big sells"))],
                  events)


def _judge(ctx: _Ctx) -> dict[str, Any]:
    s, judge = ctx.settings, ctx.state["judge"]
    verdicts = [(d, v) for d in ctx.decisions(("reject_judge", "enter", "reject_quote")) if (v := _verdict(d))]
    events = []
    for d, v in verdicts:
        name = d.symbol or _short(d.mint)
        word = str(v.get("decision", "?")).upper()
        if v.get("source") == "error":
            events.append(ctx.event(d.ts, f"{word} (error) · {name} · {v.get('error') or 'no answer'}", "bad"))
        elif v.get("source") == "rules":
            events.append(ctx.event(d.ts, f"{word} (rules only) · {name}", "neutral"))
        else:
            conf = round((_num(v.get("confidence")) or 0.0) * 100)
            why = "; ".join(str(r) for r in v.get("reasons") or [])
            events.append(ctx.event(d.ts, f"{word} {conf}% · {name} · {why}", "good" if word == "YES" else "bad"))
    day = [v for d, v in verdicts if d.ts >= ctx.now - DAY_S]
    last = verdicts[0][0].ts if verdicts else None
    spent = judge["cost_usd_today"]
    blocked = None
    if s.judge_mode != "off" and spent >= s.judge_max_daily_usd:
        blocked = "daily budget used up: every verdict is 'no' until 00:00 UTC"
    status = ctx.derive("judge", last, blocked=blocked,
                        waiting="waiting for a setup that passed risk and radar" if s.judge_mode != "off" else None,
                        idle="off: the rules decide alone" if s.judge_mode == "off" else None)
    return _panel("judge", status, last,
                  _headline(spent, "usd", f"spent today (cap ${s.judge_max_daily_usd:.2f})"),
                  [_stat("Mode", s.judge_mode, "text"), _stat("Model", s.judge_model, "text"),
                   _stat("Calls since start", judge["calls"]),
                   _stat("Spent since start", judge["cost_usd_total"], "usd"),
                   _stat("Verdicts 24 h", f"{sum(v.get('decision') == 'yes' for v in day)} yes · "
                                          f"{sum(v.get('decision') != 'yes' for v in day)} no", "text")],
                  events)


def _watchlist(ctx: _Ctx) -> tuple[int | None, list[dict[str, Any]]]:
    """``(size, items)`` from kv ``engine.watchlist`` when persisted, else ``engine.status``; (None, [])."""
    stored = ctx.ledger.get_kv(KV_WATCHLIST)
    if isinstance(stored, dict):
        stored = stored.get("items", [{"mint": k, **_dict(v)} for k, v in stored.items()])
    if isinstance(stored, list):
        items = [_dict(i) for i in stored]
        return len(items), items
    watching = ctx.status.get("watching")
    size = _num(ctx.status.get("watchlist"))
    if not isinstance(watching, list) and size is None:
        return None, []
    items = [_dict(i) for i in watching or []]
    return (int(size) if size is not None else len(items)), items


def _strategy(ctx: _Ctx) -> dict[str, Any]:
    s = ctx.settings
    size, items = _watchlist(ctx)
    ranked = []
    for item in items:
        signal = item.get("last_signal") or item.get("last_signal_reason") or item.get("signal")
        value, text = proximity(str(signal) if signal else None)
        name = str(item.get("symbol") or _short(str(item.get("mint", ""))))
        ranked.append((-1.0 if value is None else value, {
            "label": ctx.text(name, 24), "value": value, "text": f"{value * 100:.0f}%" if value is not None else "",
            "note": ctx.text(text, 100)}))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    events = []
    for d in ctx.decisions((*_SIGNAL_ACTIONS, "unwatch"), limit=40):
        name = d.symbol or _short(d.mint)
        signal = _dict(d.inputs.get("signal"))
        if d.action == "unwatch":
            events.append(ctx.event(d.ts, f"DROP {name} · {d.reason}"))
        elif signal and d.action == "enter":
            events.append(ctx.event(d.ts, f"SETUP {name} · {signal.get('reason', d.reason)} · bought", "good"))
        elif signal:
            who = _STOPPED_BY.get(d.action, d.action)
            why = re.sub(r"^(?:judge|radar):\s*", "", d.reason)
            events.append(ctx.event(d.ts, f"SETUP {name} · stopped by {who}: {why}", "bad"))
        if len(events) >= EVENTS_MAX:
            break
    counters = _dict(ctx.status.get("counters"))
    last = _latest(events[0]["ts"] if events else None, ctx.counter("candle_fetches", counters.get("candle_fetches")))
    blocked = None
    if ctx.state["kill"] != "off":
        blocked = f"kill switch {ctx.state['kill']}: no candles fetched, no new setups"
    elif ctx.status.get("entries_blocked"):
        blocked = f"new entries blocked: {ctx.status['entries_blocked']}"
    status = ctx.derive("strategy", last, blocked=blocked,
                        waiting="waiting for the scam filter to pass a coin" if size == 0 else None,
                        idle=f"watching {size} coin(s); no setup yet" if size else "watchlist not available yet")
    return _panel("strategy", status, last,
                  _headline(f"{size} of {s.watchlist_max}" if size is not None else None, "text",
                            "coins on the watchlist"),
                  [_stat("Required dip", round(s.dip_pct * 100.0, 2), "pct"),
                   _stat("Setups found since boot", _int(counters.get("entry_signals"))),
                   _stat("Candle checks since boot", _int(counters.get("candle_fetches")))],
                  events, bars=[bar for _, bar in ranked[:BARS_MAX]],
                  bars_empty=("Watchlist not available yet." if size is None
                              else "Nothing on the watchlist right now."))


def _haircut_pct(f: Fill) -> float | None:
    """How far the fill landed below its quote, percent (paper: the PAPER_SLIPPAGE_BPS model)."""
    expected = f.expected_out_amount
    actual = f.token_amount if f.side == "buy" else f.sol_lamports
    return (expected - actual) / expected * 100.0 if expected else None


def _broker(ctx: _Ctx) -> dict[str, Any]:
    s = ctx.settings
    fills = [f for f in ctx.ledger.fills(limit=50) if f.mode == ctx.mode]
    day = [f for f in fills if f.ts >= ctx.now - DAY_S]
    buys = [f for f in fills if f.side == "buy"]
    sells = [f for f in fills if f.side == "sell"]
    events = []
    for f in fills[:EVENTS_MAX]:
        cut = _haircut_pct(f)
        events.append(ctx.event(f.ts, f"{f.side.upper()} {f.symbol or _short(f.mint)} "
                                      f"{f.sol_lamports / LAMPORTS_PER_SOL:.4f} SOL @ {_price(f.price_usd)} · impact "
                                      f"{f.price_impact_pct:.2f}% · fee {f.platform_fee_bps} bps + "
                                      f"{f.fees_lamports / LAMPORTS_PER_SOL:.6f} SOL"
                                      + (f" · {cut:.2f}% below quote" if cut is not None else "")))
    cuts = [c for f in fills if (c := _haircut_pct(f)) is not None]
    haircut = (f"{s.paper_slippage_bps} bps (paper model)" if not s.is_live
               else f"{sum(cuts) / len(cuts):.2f}% average measured" if cuts else None)
    nb = sum(f.side == "buy" for f in day)
    ns = len(day) - nb
    last = fills[0].ts if fills else None
    blocks = _entry_blocks(ctx)
    blocked = "new buys blocked (sells still run): " + blocks[0][1] if blocks else None
    status = ctx.derive("broker", last, blocked=blocked,
                        waiting="waiting for an approved setup" if not ctx.open_positions else None,
                        idle=f"holding {ctx.open_positions} position(s); sells when an exit rule fires")
    return _panel("broker", status, last,
                  _headline(len(day), "count", f"fills, last 24 h ({ctx.mode})"),
                  [_stat("Fills 24 h", f"{nb} buy{'s' * (nb != 1)} · {ns} sell{'s' * (ns != 1)}", "text"),
                   _stat("Last entry", ctx.text(f"{buys[0].symbol or _short(buys[0].mint)} @ "
                                                f"{_price(buys[0].price_usd)}", 60) if buys else None,
                         "text", buys[0].ts if buys else None),
                   _stat("Last exit", ctx.text(f"{sells[0].symbol or _short(sells[0].mint)} @ "
                                               f"{_price(sells[0].price_usd)}", 60) if sells else None,
                         "text", sells[0].ts if sells else None),
                   _stat("Network fees 24 h", sum(f.fees_lamports for f in day) / LAMPORTS_PER_SOL, "sol"),
                   _stat("Slippage haircut", haircut, "text")],
                  events)


def _entry_blocks(ctx: _Ctx) -> list[tuple[str, str]]:
    """``[(source, why)]``: real conditions that stop new entries right now, most important first.
    Sources ``halt``, ``kill`` and ``daily_loss`` are the risk manager's; ``engine`` is the engine's own
    (unresolved live swap, wallet drift, live start balance missing)."""
    out = []
    if ctx.state["halted"]["halted"]:
        out.append(("halt", "halted: " + str(ctx.state["halted"]["reason"] or "drawdown limit")))
    if ctx.state["kill"] != "off":
        out.append(("kill", f"kill switch {ctx.state['kill']}"))
    meter = _loss_meter(ctx)
    if meter["fraction"] is not None and meter["fraction"] > 1.0:
        out.append(("daily_loss", "daily loss limit reached (resets 00:00 UTC)"))
    if ctx.status.get("entries_blocked"):
        out.append(("engine", str(ctx.status["entries_blocked"])))
    return out


def _loss_meter(ctx: _Ctx) -> dict[str, Any]:
    """Today's SOL result vs the daily loss limit (start of day = first snapshot of the UTC day)."""
    eq = ctx.state["equity"]
    sol, pnl = eq["sol"], eq["pnl_today_sol"]
    pct = ctx.settings.daily_loss_limit_pct
    if sol is None or pnl is None:
        return {"used": None, "limit": None, "fraction": None,
                "text": f"Daily loss limit {pct * 100:g}% of start-of-day equity; no snapshot today yet."}
    limit = (sol - pnl) * pct
    used = max(0.0, -pnl)
    fraction = used / limit if limit > 0 else None
    if pnl >= 0:
        text = f"Up {pnl:.4f} SOL today; the bot may lose up to {limit:.4f} SOL ({pct * 100:g}%) before it stops."
    else:
        text = f"Down {used:.4f} of {limit:.4f} SOL allowed today ({pct * 100:g}% of start-of-day equity)."
    return {"used": used, "limit": limit, "fraction": fraction, "text": text}


def _risk(ctx: _Ctx) -> dict[str, Any]:
    s, eq = ctx.settings, ctx.state["equity"]
    latest = ctx.ledger.latest_equity()
    last = latest.ts if latest is not None and latest.mode == ctx.mode else None
    events = [ctx.event(d.ts, f"REFUSED {d.symbol or _short(d.mint)} · {d.reason}", "bad")
              for d in ctx.decisions(("reject_risk",), limit=EVENTS_MAX)]
    for kind in ("halt", "kill", "reset"):
        receipt = ctx.ledger.last_receipt(kind)
        if receipt is not None:
            detail = receipt.payload.get("reason") or receipt.payload.get("mode") or ""
            events.append(ctx.event(receipt.ts, f"{kind.upper()} {detail}".strip(),
                                    "neutral" if kind == "reset" else "bad"))
    blocks = [why for source, why in _entry_blocks(ctx) if source != "engine"]
    status = ctx.derive("risk", last, blocked=blocks[0] if blocks else None, idle="no equity snapshot recently")
    meter = _loss_meter(ctx)
    return _panel("risk", status, last,
                  _headline(eq["sol"], "sol", "equity (" + ("bot wallet" if s.is_live else "paper wallet") + ")"),
                  [_stat("Equity (USD)", eq["usd"], "usd"), _stat("Today", eq["pnl_today_sol"], "sol"),
                   _stat("Open positions", f"{ctx.open_positions} of {s.max_open_positions}", "text"),
                   _stat("Kill switch", ctx.state["kill"], "text"),
                   _stat("Halted", ctx.text(ctx.state["halted"]["reason"] or "yes", 60)
                         if ctx.state["halted"]["halted"] else "no", "text")],
                  events, meter=meter)


def _receipt_line(r: Any) -> str:
    p = _dict(r.payload)
    if r.kind == "decision":
        detail = f"{p.get('action')} {p.get('symbol') or _short(str(p.get('mint', '')))}"
    elif r.kind == "fill":
        detail = f"{p.get('side')} {p.get('symbol') or _short(str(p.get('mint', '')))}"
    elif r.kind == "boot":
        detail = f"v{p.get('version')} {p.get('mode')}"
    else:
        detail = str(p.get("event") or p.get("stage") or p.get("mode") or p.get("reason") or "")
    return f"#{r.seq} {r.hash[:8]} · {r.kind} {detail}".strip()


def _receipts(ctx: _Ctx) -> dict[str, Any]:
    r = ctx.state["receipts"]
    recent = list(reversed(ctx.ledger.receipts(after_seq=max(0, r["seq"] - EVENTS_MAX))))
    events = [ctx.event(rc.ts, _receipt_line(rc), "bad" if rc.kind == "error" else "neutral") for rc in recent]
    last = max((rc.ts for rc in recent), default=None)
    blocked = f"chain BROKEN at receipt #{r['first_bad_seq']}" if r["verified"] is False else None
    status = ctx.derive("receipts", last, blocked=blocked, idle="no new receipt recently")
    head = r["head_hash"]
    verified = {True: "yes", False: "NO"}.get(r["verified"])
    return _panel("receipts", status, last, _headline(r["count"], "count", "receipts in the chain"),
                  [_stat("Head", r["seq"]), _stat("Verified", verified, "text", r["verified_at"]),
                   _stat("Last receipt", recent[0].kind if recent else None, "text",
                         recent[0].ts if recent else None)],
                  events, sort=False,
                  hash={"head": head, "short": f"{head[:8]}…{head[-8:]}", "explainer": RECEIPTS_EXPLAINER})


def _upgrades(ctx: _Ctx, deploy: dict[str, str | None], started_at: float | None) -> dict[str, Any]:
    events = []
    boot = ctx.ledger.last_receipt("boot")
    if boot is not None:
        events.append(ctx.event(boot.ts, f"Booted v{boot.payload.get('version')} ({boot.payload.get('mode')})",
                                "good"))
    shutdown = ctx.ledger.last_receipt("note", {"event": "shutdown"})
    if shutdown is not None:
        events.append(ctx.event(shutdown.ts, f"Shut down (v{shutdown.payload.get('version')})"))
    running = ctx.engine_block is None and ctx.engine_wait is None
    uptime = ctx.now - started_at if started_at is not None and running else None
    status = ctx.derive("upgrades", started_at, idle=f"running v{__version__}")
    return _panel("upgrades", status, started_at, _headline(f"v{__version__}", "text", "deployed version"),
                  [_stat("Commit", deploy.get("commit"), "text"),
                   _stat("Commit message", ctx.text(deploy["message"], 120) if deploy.get("message") else None,
                         "text"),
                   _stat("Uptime", uptime, "dur"), _stat("Booted", started_at, "ts")],
                  events)


# =========================================================================== page

_STYLE = r"""
:root{color-scheme:light;--page:#f9f9f7;--card:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--hair:#e1e0d9;--border:rgba(11,11,11,.10);--accent:#2a78d6;--accent-soft:#cde2fb;--up:#006300;--down:#c22f2f;
--good:#0ca30c;--warn:#fab219;--critical:#d03b3b;--idle:#898781;--paper:#256abf;--live:#d03b3b;
--new:rgba(42,120,214,.14)}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--page:#0d0d0d;--card:#1a1a19;--ink:#fff;
--ink2:#c3c2b7;--hair:#2c2c2a;--border:rgba(255,255,255,.10);--accent:#3987e5;--accent-soft:#184f95;
--up:#0ca30c;--down:#e66767;--paper:#2a78d6;--new:rgba(57,135,229,.22)}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--page);color:var(--ink);font:16px/1.45 system-ui,-apple-system,"Segoe UI",
Roboto,sans-serif;font-variant-numeric:tabular-nums;padding:16px 16px calc(24px + env(safe-area-inset-bottom))}
main{max-width:1080px;margin:0 auto}
header{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:4px 12px;
margin-bottom:12px}
.brand{font-weight:700;font-size:18px}
.brand small{font-weight:400;color:var(--ink2);font-size:13px;margin-left:6px}
.updated{color:var(--ink2);font-size:13px}
header a{color:var(--accent);font-size:14px;font-weight:600;text-decoration:none;white-space:nowrap}
.strip{display:grid;grid-template-columns:auto minmax(0,1fr);gap:10px;align-items:stretch}
.badge{border-radius:14px;color:#fff;background:var(--paper);padding:10px 14px;display:flex;flex-direction:column;
justify-content:center;text-align:center}
.badge b{font-size:24px;letter-spacing:.12em;font-weight:800;line-height:1.1}
.badge span{font-size:12px;opacity:.92}
.badge.live{background:var(--live)}
.bank{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:10px 14px;min-width:0}
.bank .label{color:var(--ink2);font-size:13px}
.bank .value{font-size:26px;font-weight:650;line-height:1.15}
.bank .sub{color:var(--ink2);font-size:13px;overflow-wrap:anywhere}
.up{color:var(--up)}.down{color:var(--down)}
.team{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.status{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--border);border-radius:999px;
padding:3px 10px;font-size:13px;font-weight:650;background:var(--card);white-space:nowrap}
.status i{width:9px;height:9px;border-radius:50%;flex:none;background:var(--idle)}
.status.working i{background:var(--good)}.status.waiting i{background:var(--warn)}
.status.blocked i{background:var(--critical)}.status.blocked{border-color:var(--critical)}
.banner{margin-top:10px;padding:10px 14px;border-radius:12px;background:var(--warn);color:#0b0b0b;font-weight:600;
font-size:14px}
.banner[hidden]{display:none}
.grid{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;margin-top:12px}
@media (min-width:760px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (min-width:1080px){.grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:14px 14px 12px;min-width:0}
.card.blocked{border-color:var(--critical)}
.head{display:flex;justify-content:space-between;align-items:center;gap:8px}
h2{font-size:17px;font-weight:700;margin:0}
.role{color:var(--ink2);font-size:13px;margin:2px 0 0}
.why{color:var(--ink2);font-size:13px;margin:8px 0 0;overflow-wrap:anywhere}
.headline{margin-top:10px;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.headline b{font-size:30px;font-weight:650;line-height:1.1;overflow-wrap:anywhere}
.headline span{color:var(--ink2);font-size:13px}
dl{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:3px 12px;margin:10px 0 0;font-size:14px}
dt{color:var(--ink2)}dd{margin:0;text-align:right;overflow-wrap:anywhere}
dd small{color:var(--ink2)}
.na{color:var(--muted)}
.bars{margin-top:10px}
.bar{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:3px 10px;margin-top:8px;font-size:13px}
.bar span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar small{grid-column:1/-1;color:var(--ink2);overflow-wrap:anywhere}
.track{grid-column:1/-1;height:8px;border-radius:4px;background:var(--accent-soft);overflow:hidden}
.fill{height:100%;border-radius:4px;background:var(--accent)}
.fill.warn{background:var(--warn)}.fill.critical{background:var(--critical)}
.meter{margin-top:10px;font-size:13px;color:var(--ink2)}
.meter .track{margin:4px 0}
.hash{margin-top:10px;padding:8px 10px;border-radius:10px;background:var(--page);border:1px solid var(--border);
font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:14px;overflow-wrap:anywhere}
.explain{color:var(--ink2);font-size:13px;margin:6px 0 0}
.empty{color:var(--ink2);font-size:13px;margin:8px 0 0}
ol{list-style:none;margin:10px 0 0;padding:0;border-top:1px solid var(--hair)}
li{display:grid;grid-template-columns:auto minmax(0,1fr);gap:10px;padding:6px 0;border-bottom:1px solid var(--hair);
font-size:13px;align-items:baseline}
li time{color:var(--ink2);white-space:nowrap}
li span{overflow-wrap:anywhere}
li.good span::before,li.bad span::before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;
margin-right:6px;vertical-align:1px;background:var(--good)}
li.bad span::before{background:var(--critical)}
li.new{animation:flash 2.4s ease-out}
@keyframes flash{from{background:var(--new)}to{background:transparent}}
@media (prefers-reduced-motion:reduce){li.new{animation:none}}
footer{color:var(--ink2);font-size:12px;text-align:center;margin-top:18px}
main.stale .card,main.stale .bank{opacity:.6}
"""

_SCRIPT = r"""
"use strict";
(() => {
  const REFRESH_MS = Number(document.body.dataset.refresh || 10) * 1000;
  const MINUS = "−";
  const $ = (id) => document.getElementById(id);
  const seen = new Set();
  let token = null, timer = null, first = true, last = null, lastOkAt = null, serverOffset = 0;

  const params = new URLSearchParams(location.search);
  if (params.has("token")) {
    token = params.get("token");
    params.delete("token");
    const rest = params.toString();
    history.replaceState(null, "", location.pathname + (rest ? "?" + rest : "") + location.hash);
  }

  // ------------------------------------------------------------ helpers (text only, never HTML)
  function el(tag, cls, ...kids) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    for (const k of kids) if (k !== null && k !== undefined && k !== false) node.append(k);
    return node;
  }
  const isNum = (v) => typeof v === "number" && isFinite(v);
  const sign = (v, signed) => (v < 0 ? MINUS : signed && v > 0 ? "+" : "");
  const tone = (v) => (isNum(v) && v > 0 ? "up" : isNum(v) && v < 0 ? "down" : "");
  const nowS = () => Date.now() / 1000 + serverOffset;
  function sol(v, signed) { return isNum(v) ? sign(v, signed) + Math.abs(v).toFixed(4) + " SOL" : null; }
  function usd(v, signed) {
    if (!isNum(v)) return null;
    const a = Math.abs(v);
    const text = a >= 1000 ? a.toLocaleString(undefined, {maximumFractionDigits: 0})
      : a >= 1 || a === 0 ? a.toFixed(2) : a.toFixed(3);
    return sign(v, signed) + "$" + text;
  }
  function dur(s) {
    if (!isNum(s)) return null;
    s = Math.max(0, s);
    if (s < 60) return Math.round(s) + " s";
    if (s < 3600) return Math.floor(s / 60) + " min";
    if (s < 86400) return Math.floor(s / 3600) + " h " + String(Math.floor(s % 3600 / 60)).padStart(2, "0") + " min";
    return Math.floor(s / 86400) + " d " + Math.floor(s % 86400 / 3600) + " h";
  }
  function ago(ts) { return isNum(ts) ? dur(nowS() - ts) + " ago" : null; }
  function utc(ts) { return isNum(ts) ? new Date(ts * 1000).toISOString().slice(11, 19) : null; }
  function fmt(value, unit) {
    if (value === null || value === undefined || value === "") return null;
    switch (unit) {
      case "count": return isNum(value) ? value.toLocaleString() : String(value);
      case "sol": return sol(value);
      case "usd": return usd(value);
      case "pct": return isNum(value) ? value.toFixed(1) + "%" : null;
      case "ts": return isNum(value) ? utc(value) + " UTC · " + ago(value) : null;
      case "dur": return dur(value);
      default: return String(value);
    }
  }
  const NA = () => el("span", "na", "not available yet");
  const WORD = {working: "Working", idle: "Idle", waiting: "Waiting", blocked: "Blocked"};
  function chip(status, text) { return el("span", "status " + status, el("i"), text || WORD[status] || status); }

  // ------------------------------------------------------------ top strip
  function renderStrip(s) {
    const live = s.mode === "LIVE";
    const badge = $("badge");
    badge.className = "badge" + (live ? " live" : "");
    badge.replaceChildren(el("b", null, s.mode), el("span", null, live ? "real money" : "simulated fills"));
    const b = s.bank;
    $("bank-label").textContent = live ? "Live wallet" : "Paper bank";
    $("bank-value").textContent = sol(b.sol) || "—";
    const parts = [];
    if (isNum(b.usd)) parts.push(usd(b.usd));
    if (isNum(b.change_sol)) {
      parts.push(el("span", tone(b.change_sol), sol(b.change_sol, true)
        + (isNum(b.change_pct) ? " (" + sign(b.change_pct, true) + Math.abs(b.change_pct).toFixed(1) + "%)" : "")
        + " since start"));
    }
    const sub = $("bank-sub");
    sub.replaceChildren();
    parts.forEach((p, i) => { if (i) sub.append(" · "); sub.append(p); });
    if (!parts.length) sub.textContent = "Waiting for the first equity snapshot.";
    const order = ["working", "idle", "waiting", "blocked"];
    $("team").replaceChildren(...order.map((k) => chip(k, s.team[k] + " " + k)));
  }

  // ------------------------------------------------------------ one member
  function stats(rows) {
    const dl = el("dl");
    for (const r of rows) {
      const text = fmt(r.value, r.unit);
      const dd = el("dd", null, text === null ? NA() : text);
      if (text !== null && isNum(r.ts) && r.unit !== "ts") dd.append(el("small", null, " · " + utc(r.ts)));
      dl.append(el("dt", null, r.label), dd);
    }
    return dl;
  }
  function track(fraction, cls) {
    const fill = el("div", "fill" + (cls ? " " + cls : ""));
    fill.style.width = (isNum(fraction) ? Math.max(0, Math.min(1, fraction)) * 100 : 0).toFixed(1) + "%";
    return el("div", "track", fill);
  }
  function bars(p) {
    if (!p.bars.length) return el("p", "empty", p.bars_empty || "");
    return el("div", "bars", ...p.bars.map((b) => el("div", "bar", el("span", null, b.label),
      el("b", null, b.text || ""), track(b.value), b.note ? el("small", null, b.note) : null)));
  }
  function events(panel) {
    if (!panel.events.length) return el("p", "empty", "No events recorded yet.");
    const list = el("ol");
    for (const e of panel.events) {
      const key = panel.id + "|" + e.ts + "|" + e.text;
      const item = el("li", e.tone, el("time", null, utc(e.ts)), el("span", null, e.text));
      item.title = new Date(e.ts * 1000).toISOString().replace("T", " ").slice(0, 19) + " UTC";
      if (!first && !seen.has(key)) item.classList.add("new");
      seen.add(key);
      list.append(item);
    }
    return list;
  }
  function renderPanel(p) {
    const card = $("m-" + p.id);
    if (!card) return;
    card.className = "card " + p.status;
    card.querySelector(".head").replaceChildren(el("h2", null, p.name), chip(p.status));
    const why = p.status === "working"
      ? "Last activity " + (ago(p.last_activity) || "just now")
      : p.why + (isNum(p.last_activity) ? " · last activity " + ago(p.last_activity) : "");
    const kids = [el("p", "why", why)];
    const h = p.headline;
    const value = fmt(h.value, h.unit);
    kids.push(el("div", "headline", el("b", null, value === null ? "—" : value), el("span", null, h.label)));
    if (p.meter) {
      const m = p.meter, f = m.fraction;
      const meter = track(f, isNum(f) && f >= 1 ? "critical" : isNum(f) && f >= 0.5 ? "warn" : "");
      meter.setAttribute("role", "meter");
      meter.setAttribute("aria-valuemin", "0");
      meter.setAttribute("aria-valuemax", "100");
      meter.setAttribute("aria-valuenow", isNum(f) ? String(Math.round(Math.min(1, f) * 100)) : "0");
      meter.setAttribute("aria-label", "Share of today's loss limit used");
      kids.push(el("div", "meter", el("div", null, "Daily loss limit used"), meter, el("div", null, m.text)));
    }
    if (p.hash) kids.push(el("div", "hash", p.hash.short), el("p", "explain", p.hash.explainer));
    if (p.bars) kids.push(bars(p));
    kids.push(stats(p.stats), events(p));
    card.querySelector(".body").replaceChildren(...kids);
  }

  function render(s) {
    last = s;
    renderStrip(s);
    s.panels.forEach(renderPanel);
    if (seen.size > 3000) seen.clear();
    first = false;
    $("foot").textContent = "nightcrawler " + s.version + " · real data only · refreshes every "
      + REFRESH_MS / 1000 + " s";
    tick();
  }

  // ------------------------------------------------------------ polling
  function banner(text) {
    const b = $("banner");
    b.hidden = !text;
    b.textContent = text || "";
    $("main").classList.toggle("stale", Boolean(text) && last !== null);
  }
  function tick() {
    $("updated").textContent = lastOkAt ? "updated " + Math.round((Date.now() - lastOkAt) / 1000) + " s ago"
      : "loading…";
  }
  async function refresh() {
    clearTimeout(timer);
    try {
      const url = "api/team" + (token ? "?token=" + encodeURIComponent(token) : "");
      const res = await fetch(url, {cache: "no-store", credentials: "same-origin"});
      if (res.status === 401) {
        banner("Locked: open the link that ends with ?token=…");
      } else if (!res.ok) {
        throw new Error("HTTP " + res.status);
      } else {
        const s = await res.json();
        serverOffset = s.generated_at - Date.now() / 1000;
        lastOkAt = Date.now();
        render(s);
        banner(null);
      }
    } catch (err) {
      banner("Can't reach the bot right now" + (last ? " — showing data from " + ago(last.generated_at) : "")
        + ". Retrying…");
    } finally {
      if (!document.hidden) timer = setTimeout(refresh, REFRESH_MS);
    }
  }
  document.addEventListener("visibilitychange", () => { if (document.hidden) clearTimeout(timer); else refresh(); });
  setInterval(tick, 5000);
  refresh();
})();
"""


def _sha256_source(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") + "'"


#: Sent with ``/team``: nothing loads from anywhere; only this exact inline script and style run.
TEAM_CSP = (f"default-src 'none'; script-src {_sha256_source(_SCRIPT)}; style-src {_sha256_source(_STYLE)}; "
            "connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def render_team_html() -> str:
    """The complete ``/team`` page (static skeleton with every panel; the script fills in live data). Pure."""
    cards = "".join(
        f"<section class=\"card\" id=\"m-{pid}\" aria-label=\"{html.escape(name)}\">"
        f"<div class=\"head\"><h2>{html.escape(name)}</h2><span class=\"status\"><i></i>…</span></div>"
        f"<p class=\"role\">{html.escape(role, quote=False)}</p>"
        "<div class=\"body\"><p class=\"empty\">Loading…</p></div></section>\n"
        for pid, name, role in PANELS)
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        "<meta name=\"color-scheme\" content=\"light dark\">\n"
        "<meta name=\"theme-color\" content=\"#f9f9f7\" media=\"(prefers-color-scheme: light)\">\n"
        "<meta name=\"theme-color\" content=\"#0d0d0d\" media=\"(prefers-color-scheme: dark)\">\n"
        "<meta name=\"robots\" content=\"noindex, nofollow\">\n<meta name=\"referrer\" content=\"no-referrer\">\n"
        "<link rel=\"icon\" href=\"data:,\">\n<title>nightcrawler · team room</title>\n"
        f"<style>{_STYLE}</style>\n</head>\n"
        f"<body data-refresh=\"{REFRESH_S}\">\n<main id=\"main\">\n"
        "<header><div class=\"brand\">nightcrawler<small>team room</small></div>"
        "<div><span class=\"updated\" id=\"updated\">loading…</span> · <a href=\"./\">Dashboard</a></div></header>\n"
        "<div class=\"strip\"><div class=\"badge\" id=\"badge\"><b>…</b><span>mode</span></div>"
        "<div class=\"bank\"><div class=\"label\" id=\"bank-label\">Bank</div>"
        "<div class=\"value\" id=\"bank-value\">—</div><div class=\"sub\" id=\"bank-sub\"></div></div></div>\n"
        "<div class=\"team\" id=\"team\" aria-label=\"Team status\"></div>\n"
        "<div class=\"banner\" id=\"banner\" role=\"status\" hidden></div>\n"
        f"<div class=\"grid\">\n{cards}</div>\n"
        "<footer id=\"foot\">read-only · real data only</footer>\n</main>\n"
        f"<script>{_SCRIPT}</script>\n</body>\n</html>\n"
    )


# =========================================================================== server glue


class TeamRoom:
    """The two team-room routes for :class:`~nightcrawler.dashboard.DashboardServer`.

    ``ledger`` is the engine's ledger when wired by the caller; when None (``build_app`` does not pass
    one), the ledger file ``settings.db_path`` is opened lazily on the first ``/api/team`` request as a
    second WAL connection (reads never block the engine) and closed by :meth:`close`.
    """

    def __init__(self, settings: Settings, ledger: Any = None, clock: Clock | None = None,
                 environ: Mapping[str, str] | None = None) -> None:
        self.settings = settings
        self.clock = clock if clock is not None else RealClock()
        self._ledger = ledger
        self._owns_ledger = ledger is None
        self._secrets = tuple(settings.secret_values())
        self.deploy = deploy_info(os.environ if environ is None else environ, self._secrets)
        self.page = render_team_html().encode("utf-8")
        self._verify_cache: dict[str, Any] = {}
        self._memory: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._closed = False

    def state(self) -> dict[str, Any]:
        """``/api/team`` for now, scrubbed of secrets."""
        with self._lock:
            if self._closed:
                raise RuntimeError("team room is closed")
            if self._ledger is None:
                self._ledger = Ledger(self.settings.db_path, clock=self.clock)
            state = build_team_state(self._ledger, self.settings, self.clock.now(), verify_cache=self._verify_cache,
                                     memory=self._memory, deploy=self.deploy)
        return scrub(state, self._secrets)

    def response(self, path: str, headers: list[tuple[str, str]]) -> tuple[int, bytes, str, list[tuple[str, str]]]:
        """``(status, body, content type, headers)`` for an AUTHORIZED request to ``/team`` or ``/api/team``."""
        if path == "/team":
            return 200, self.page, "text/html; charset=utf-8", [*headers, ("Content-Security-Policy", TEAM_CSP)]
        try:
            body = json.dumps(self.state(), allow_nan=False, separators=(",", ":"), default=str).encode("utf-8")
        except Exception:
            log.exception("team_state_failed")
            return 500, b'{"error":"team state unavailable"}', "application/json", headers
        return 200, body, "application/json", headers

    def close(self) -> None:
        """Close the ledger this object opened itself (idempotent); later requests answer 500."""
        with self._lock:
            self._closed = True
            if self._owns_ledger and self._ledger is not None:
                self._ledger.close()
                self._ledger = None
