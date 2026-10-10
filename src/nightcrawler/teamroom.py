"""Team room: a live, read-only view of every bot "team member" at work (owner: O6).

Served by :class:`nightcrawler.dashboard.DashboardServer` behind the same ``DASHBOARD_TOKEN`` gate,
security headers and secret scrubbing as ``/api/state`` (:class:`TeamRoom` is the glue):

* ``/api/team`` -> :func:`build_team_state` (JSON, schema below).
* ``/api/page`` -> :func:`nightcrawler.pagestate.build_page_state`, the one page's data, which shows these
  panels as its "team" rows. (``/team`` itself now redirects to that page, ``/``.)

Texts are plain words for a non-developer: rule ids such as ``[top10]`` become labels (:func:`plain`), and
every panel carries ``doing``, ONE short sentence of what the member is doing right now.

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
coins waiting), saved by the engine as ``{saved_at, items}`` snapshots every few minutes, win unless
``engine.status`` (``watching``, ``crawler.nursery``; rewritten every 15 s) is newer; without either they
are ``null``.

The Strategy panel also carries the trend desk (:mod:`nightcrawler.trenddesk`, a PAPER forward test of lab 3's
50-day trend rule on BTC, ETH and SOL; its state file only): stats "Trend desk ..." (in or out per coin, since start
against holding the three bought on day one and never touched, and lab 3's own figures re-balanced daily for
comparison only), its flips as events ("Trend desk: BTC closed above its 50-day average -> in (paper)") and ``trend``
(the same, for the page). Its activity never sets the Strategy chip, and its figures are never summed with anything
else.

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
      "panels": [{"id", "name", "role", "status", "why", "doing": str, "last_activity": float|null,
                  "headline": {"value", "unit", "label"},
                  "stats": [{"label", "value", "unit", "ts"?}],
                  "events": [{"ts": float, "text": str, "tone": "good"|"bad"|"neutral"}],   # newest first
                  "bars"?: [{"label", "value": fraction|null, "text"}], "bars_empty"?: str,
                  "meter"?: {"used", "limit", "fraction", "text"}, "hash"?: {"head", "short", "explainer"},
                  "desks"?: [{"desk", "verdict", "phrase", "reason", "paused", "since", "line"}],   # risk: each desk's verdict
                  "risk_wall"?: {"allowance_used_pct": float|null, "slots_used": int, "slots_max": int,   # risk: the
                                 "daily_stop": bool|null, "stopped_by": "halt"|"kill"|"daily_loss"|null,  # 3D world's
                                 "desks": [{"desk", "verdict", "paused"}]}}]                            # gauge board
    }

The risk member's ``risk_wall`` is the same panel as numbers, for the 3D world's gauge board (Rook's risk wall): the
share of today's loss allowance used (``meter.fraction`` as a percent, null before the day's first money check; it may
pass 100 once the limit is reached), the trade slots in use of the most allowed, whether today's loss stop is on (null
while the allowance is unknown), what stops new buys right now if anything, and each desk's verdict with its pause.

Units:``count``, ``sol``, ``usd``, ``pct`` (percent), ``ts`` (epoch s), ``dur`` (seconds), ``text``.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable, Iterable, Mapping
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
    "FUTURE_SKEW_S",
    "PANELS",
    "REFRESH_S",
    "TeamRoom",
    "build_team_state",
    "deploy_info",
    "derive_status",
    "duration_text",
    "json_body",
    "plain",
    "proximity",
]

log = get_logger(__name__)

REFRESH_S = 10
#: The engine rewrites its heartbeat every 15 s; older than this = silent (the page's banner uses it too).
ENGINE_STALE_S = 180.0
#: An activity stamp later than now + this is not trusted (a millisecond epoch, a clock far ahead).
FUTURE_SKEW_S = 60.0
EVENTS_MAX = 5
BARS_MAX = 5
TEXT_MAX = 160
HOUR_S = 3600.0
DAY_S = 86_400.0
#: Kv keys the engine saves its in-memory facts to (used unless ``engine.status`` is newer).
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
    ("risk", "Risk", ("Sizes trades, enforces the daily loss, drawdown and position limits, and pauses a desk "
                      "whose record loses money")),
    ("receipts", "Receipts", "Writes every decision and fill into a tamper-evident hash chain"),
    ("upgrades", "Upgrades", "What is deployed right now and how long it has been running"),
    ("predict", "Polymarket desk", "PAPER desk on Polymarket US: buys outcomes that are almost decided, all day"),
)
_ROLES = {pid: (name, role) for pid, name, role in PANELS}

#: How recent an activity must be for a member to count as working (seconds); see ``_window``.
WORKING_WINDOW_S = {"crawler": 300.0, "cocoon": 600.0, "radar": 1800.0, "judge": 1800.0, "strategy": 300.0,
                    "broker": 1800.0, "risk": 300.0, "receipts": 600.0, "upgrades": 600.0, "predict": 600.0}

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
#: Risk-manager refusal rule ids (``[rule]`` prefix) in plain words.
RISK_LABELS = {
    "kill": "Kill switch on", "halted": "Buying halted", "drawdown": "Fell too far from its high",
    "daily_loss": "Today's loss limit reached", "max_positions": "Too many open trades",
    "already_open": "Already holding this coin", "cooldown": "Sold this coin recently",
    "wallet_cap": "Wallet holds more than the safety cap", "blocked": "New buys paused",
    "size": "Not enough money for a trade",
}
_TAG = re.compile(r"\[([A-Za-z0-9_]+)\]\s*")
_LABELS = {**RULE_LABELS, **RISK_LABELS}
#: Why new buys are stopped (``_entry_blocks`` source), in plain words.
_BLOCKED_WORDS = {"halt": "buying is halted after a big drop", "kill": "the kill switch is on",
                  "daily_loss": "today's loss limit is reached"}
#: Where a coin was found (candidate ``sources`` prefix -> provider).
_FEEDS = (("jupiter", "Jupiter"), ("gt_", "GeckoTerminal"), ("dexscreener", "DexScreener"), ("pumpfun", "pump.fun"))
#: Decision actions in plain words (receipt lines).
_ACTION_WORDS = {
    "reject_prefilter": "skipped", "reject_cocoon": "thrown out", "watch": "now watching",
    "unwatch": "stopped watching", "no_signal": "no setup", "reject_radar": "radar said no",
    "reject_judge": "judge said no", "reject_risk": "risk said no", "reject_quote": "bad price, no buy",
    "enter": "bought", "exit": "sold", "exit_partial": "took profit", "hold": "holding", "kill": "kill switch",
    "error": "error",
}
_SIGNAL_ACTIONS = ("enter", "reject_risk", "reject_radar", "reject_judge", "reject_quote")
_RADAR_ACTIONS = ("enter", "reject_radar", "reject_judge", "reject_quote", "exit", "exit_partial")
_STOPPED_BY = {"reject_risk": "risk", "reject_radar": "radar", "reject_judge": "the judge",
               "reject_quote": "the quote"}
_DIP = re.compile(r"dip (\d+(?:\.\d+)?)% < required (\d+(?:\.\d+)?)%")
#: Strategy reasons that mean the dip is deep enough, with what is still missing in plain words.
_DIP_REACHED = {"chasing": "dropped enough, but the price already bounced too far",
                "buyers not back": "dropped enough; waiting for buyers to come back",
                "buy/sell ratio": "dropped enough; more sellers than buyers right now",
                "setup, but": "setup found, but another check said no", "dip-rebound": "setup found"}
RECEIPTS_EXPLAINER = ("Every decision and fill is chained to the one before it by a SHA-256 fingerprint the "
                      "moment it happens, so no result can be edited with hindsight without breaking the chain.")


# =========================================================================== small helpers


def derive_status(now: float, last_activity: float | None, window_s: float, *, blocked: str | None = None,
                  waiting: str | None = None, idle: str | None = None) -> tuple[str, str]:
    """``(status, why)``: ``blocked`` > ``working`` (activity within ``window_s``) > ``waiting`` > ``idle``.

    A working member's ``why`` is empty: the page shows how long ago it acted from ``last_activity``. A stamp
    more than :data:`FUTURE_SKEW_S` in the future counts as unknown, so it can never keep a member Working.
    """
    if last_activity is not None and last_activity > now + FUTURE_SKEW_S:
        last_activity = None
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
        return (min(1.0, dip / required) if required > 0 else None), f"dropped {dip:g}% of the {required:g}% needed"
    reached = next((words for prefix, words in _DIP_REACHED.items() if last_signal.startswith(prefix)), None)
    if reached is not None:
        return 1.0, reached
    return None, last_signal


def deploy_info(environ: Mapping[str, str], secrets: Iterable[str] = ()) -> dict[str, str | None]:
    """The deployed commit from Railway's two git variables ONLY (no other variable is ever read)."""
    sha = (environ.get("RAILWAY_GIT_COMMIT_SHA") or "").strip()
    message = redact_text((environ.get("RAILWAY_GIT_COMMIT_MESSAGE") or "").strip(), tuple(secrets))
    first = message.splitlines()[0].strip() if message else ""
    return {"commit": sha[:12] or None, "message": _clip(first, 120) or None}


def plain(reason: str) -> str:
    """Rule ids in plain words: ``"[top10] top-10 own 45%"`` -> ``"Top 10 wallets hold too much: top-10 own 45%"``
    (Cocoon and risk rules; an unknown ``[tag]`` is dropped)."""
    return _TAG.sub(lambda m: f"{_LABELS[m.group(1)]}: " if m.group(1) in _LABELS else "", reason)


def _n(count: int, word: str) -> str:
    """``1 coin`` / ``3 coins`` (regular plurals only)."""
    return f"{count:,} {word}{'' if count == 1 else 's'}"


def duration_text(seconds: float) -> str:
    """``"5 min"``, ``"2 h 05 min"``, ``"3 d 4 h"`` (``"3 d"`` on the hour)."""
    minutes = int(max(0.0, seconds) // 60)
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 24 * 60:
        return f"{minutes // 60} h {minutes % 60:02d} min"
    hours = minutes % 1440 // 60
    return f"{minutes // 1440} d" + (f" {hours} h" if hours else "")


def _feed(source: str) -> str:
    return next((name for prefix, name in _FEEDS if source.startswith(prefix)), source)


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
    """When a since-boot counter in ``engine.status`` CHANGED between two reads, the member acted somewhere
    between them: the activity is dated to the PREVIOUS read's status stamp, so a member never looks more
    recent than proven (after an hour with the phone screen off that is an hour ago, not "5 s ago"). An
    unchanged counter proves nothing. ``memory[key]`` = ``[value, activity stamp | None, last read's stamp]``."""
    if memory is None or _num(value) is None or stamp is None:
        return None
    seen = memory.get(key)
    if seen is None:
        memory[key] = [value, None, stamp]
    elif seen[0] != value:
        memory[key] = [value, seen[2], stamp]
    else:
        seen[2] = stamp
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
    desk: dict[str, Any] | None = None

    @property
    def status_ts(self) -> float | None:
        return _num(self.status.get("ts"))

    def polydesk(self) -> dict[str, Any]:
        """The Polymarket desk's panel state (:func:`nightcrawler.polydesk.panel_state`), read once per answer: the
        desk's own panel and the risk member's desk verdicts share it."""
        if self.desk is None:
            from nightcrawler.polydesk import panel_state

            self.desk = panel_state(self.settings, self.now)
        return self.desk

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
        return status, self.text(plain(why))

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


def _panel(pid: str, status_why: tuple[str, str], last: float | None, doing: str, headline: dict[str, Any],
           stats: list[dict[str, Any]], events: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    """One panel; ``doing`` is already redacted and clipped (``_Ctx.text``)."""
    name, role = _ROLES[pid]
    status, why = status_why
    if extra.pop("sort", True):
        events = sorted(events, key=lambda e: e["ts"], reverse=True)
    return {"id": pid, "name": name, "role": role, "status": status, "why": why, "doing": doing,
            "last_activity": last, "headline": headline, "stats": stats, "events": events[:EVENTS_MAX], **extra}


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
        return "stale", f"engine silent for {duration_text(age)}"
    return "running", None


def build_team_state(ledger: Any, settings: Settings, now: float, engine_status: dict[str, Any] | None = None,
                     *, verify_cache: dict[str, Any] | None = None, memory: dict[str, Any] | None = None,
                     deploy: dict[str, str | None] | None = None, state: dict[str, Any] | None = None
                     ) -> dict[str, Any]:
    """Assemble ``/api/team`` (schema in the module docstring) from the ledger ONLY (no network calls).

    ``engine_status`` overrides kv ``engine.status``; ``verify_cache`` throttles chain verification
    (see ``dashboard.build_state``); ``memory`` is a dict kept between calls so a since-boot counter that
    moved counts as activity; ``deploy`` is :func:`deploy_info` (read once at startup by :class:`TeamRoom`);
    ``state`` is ``dashboard.build_state`` for the same ``now`` when the caller already built it.
    """
    secrets = tuple(settings.secret_values())
    state = state if state is not None else build_state(ledger, settings, now, verify_cache)
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
              _receipts(ctx), _upgrades(ctx, deploy or {"commit": None, "message": None}, started_at),
              _predict(ctx)]
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


def _saved_wins(ctx: _Ctx, saved: Any, live: Any) -> bool:
    """A kv value the engine saved wins over the live ``engine.status`` value unless the status is NEWER (the
    engine saves ``{saved_at, items}`` snapshots every few minutes; it rewrites its status every 15 s)."""
    if live is None:
        return True
    saved_at, status_at = _num(_dict(saved).get("saved_at")), ctx.status_ts
    return saved_at is None or status_at is None or saved_at >= status_at


def _nursery(ctx: _Ctx) -> int | None:
    live = _int(_dict(ctx.status.get("crawler")).get("nursery"))
    for key in KV_NURSERY:
        value = ctx.ledger.get_kv(key)
        if value is None or not _saved_wins(ctx, value, live):
            continue
        if isinstance(value, dict):
            if isinstance(value.get("items"), list):  # the engine's snapshot: {saved_at, items}
                return len(value["items"])
            for name in ("count", "size", "total"):
                if _num(value.get(name)) is not None:
                    return int(value[name])
            return len(value)
        if isinstance(value, list):
            return len(value)
        if _num(value) is not None:
            return int(value)
    return live


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
            bits.append(f"worth {_usd_compact(c['mcap_usd'])}")
        feeds = list(dict.fromkeys(_feed(str(s)) for s in c.get("sources") or []))[:2]
        if feeds:
            bits.append("found on " + ", ".join(feeds))
        events.append(ctx.event(first_seen, " · ".join(bits)))
    errors = _dict(crawler.get("feed_errors"))
    last = _latest(_num(newest), ctx.counter("crawler.polls", crawler.get("polls")))
    status = ctx.derive("crawler", last, idle="no new coin passed the cheap prefilter recently")
    found, nursery = ctx.ledger.candidate_count(since=ctx.now - HOUR_S), _nursery(ctx)
    doing = (f"Found {_n(found, 'new coin')} in the last hour" if found
             else "No new coin got past the first quick checks in the last hour")
    doing += (f"; {nursery:,} too young to judge yet." if nursery else ".")
    return _panel("crawler", status, last, ctx.text(doing),
                  _headline(found, "count", "new coins handed to the scam filter, last hour"),
                  [_stat("Last 24 h", ctx.state["activity"]["candidates_24h"]),
                   _stat("Too young, waiting", nursery),
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
            events.append(ctx.event(d.ts, f"REJECT {name} · {plain(d.reason)}", "bad"))
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
    if passed or rejected:
        doing = f"Last 24 h: threw out {_n(rejected, 'coin')}, let {passed:,} through."
        if rules:
            doing += f" Most common problem: {RULE_LABELS.get(rules[0][0], rules[0][0]).lower()}."
    else:
        doing = f"{_n(queue, 'coin')} waiting to be checked." if queue else "No coin to check in the last 24 h."
    return _panel("cocoon", status, last, ctx.text(doing),
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
    last = _latest(scans[0].ts if scans else None, exits[0].ts if exits else None)
    held = ctx.open_positions
    status = ctx.derive("radar", last, waiting="waiting for a coin to reach a buy setup" if not held else None,
                        idle=(f"re-checks {held} open position(s) every {ctx.settings.radar_interval_s:g} s; "
                              "only recorded when it forces a sale") if held else None)
    if held:
        doing = f"Watching {_n(held, 'open trade')} for danger: the creator or big holders selling."
    elif day_scans:
        stopped = sum(d.action == "reject_radar" for d in day_scans)
        doing = f"Checked {_n(len(day_scans), 'coin')} right before buying in 24 h; stopped {stopped:,}."
    else:
        doing = "Nothing to check yet: it looks right before a buy."
    return _panel("radar", status, last, ctx.text(doing),
                  _headline(len(flagged), "count", "big sells flagged, last 24 h"),
                  [_stat("Scans before a buy (24 h)", len(day_scans)), _stat("Last scan", last, "ts"),
                   _stat("Creator sold", reasons.count("creator sold")),
                   _stat("Insiders / top holders sold", reasons.count("insiders sold")),
                   _stat("Big sells vs liquidity", reasons.count("big sells"))],
                  events)


def _judge(ctx: _Ctx) -> dict[str, Any]:
    s, judge = ctx.settings, ctx.state["judge"]
    # A ``source="rules"`` verdict is the judge being OFF (a rules-only yes on every entry): not Jev's work.
    verdicts = [(d, v) for d in ctx.decisions(("reject_judge", "enter", "reject_quote"))
                if (v := _verdict(d)) and v.get("source") != "rules"]
    events = []
    for d, v in verdicts:
        name = d.symbol or _short(d.mint)
        word = str(v.get("decision", "?")).upper()
        if v.get("source") == "error":
            events.append(ctx.event(d.ts, f"{word} (error) · {name} · {v.get('error') or 'no answer'}", "bad"))
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
    yes = sum(v.get("decision") == "yes" for v in day)
    if s.judge_mode == "off":
        doing = "Switched off: the rules decide alone (no AI cost)."
    elif blocked:
        doing = "Spent today's budget: says no to everything until midnight UTC."
    else:
        doing = (f"Last 24 h: {yes} yes, {len(day) - yes} no. "
                 f"Spent ${spent:.2f} of ${s.judge_max_daily_usd:.2f} today.")
    return _panel("judge", status, last, ctx.text(doing),
                  _headline(spent, "usd", f"spent today (cap ${s.judge_max_daily_usd:.2f})"),
                  [_stat("Mode", s.judge_mode, "text"), _stat("Model", s.judge_model, "text"),
                   _stat("Calls since start", judge["calls"]),
                   _stat("Spent since start", judge["cost_usd_total"], "usd"),
                   _stat("Verdicts 24 h", f"{yes} yes · {len(day) - yes} no", "text")],
                  events)


def _watchlist(ctx: _Ctx) -> tuple[int | None, list[dict[str, Any]]]:
    """``(size, items)`` from kv ``engine.watchlist`` when persisted (and not older than ``engine.status``),
    else ``engine.status``; (None, []). Items: ``{mint, symbol, last_signal}`` (the engine saves its own
    ``{candidate: {mint, symbol}, last_signal_reason}`` shape, read here too)."""
    stored = ctx.ledger.get_kv(KV_WATCHLIST)
    watching = ctx.status.get("watching")
    if stored is not None and not _saved_wins(ctx, stored, watching if isinstance(watching, list) else None):
        stored = None
    if isinstance(stored, dict):
        stored = stored.get("items", [{"mint": k, **_dict(v)} for k, v in stored.items()])
    if isinstance(stored, list):
        items = []
        for raw in stored:
            item, candidate = _dict(raw), _dict(_dict(raw).get("candidate"))
            items.append({**item, "mint": item.get("mint") or candidate.get("mint"),
                          "symbol": item.get("symbol") or candidate.get("symbol")})
        return len(items), items
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
            events.append(ctx.event(d.ts, f"SETUP {name} · the drop and the bounce came · bought", "good"))
        elif signal:
            who = _STOPPED_BY.get(d.action, d.action)
            why = plain(re.sub(r"^(?:judge|radar):\s*", "", d.reason))
            events.append(ctx.event(d.ts, f"SETUP {name} · stopped by {who}: {why}", "bad"))
        if len(events) >= EVENTS_MAX:
            break
    counters = _dict(ctx.status.get("counters"))
    last = _latest(events[0]["ts"] if events else None, ctx.counter("candle_fetches", counters.get("candle_fetches")))
    blocked = None
    if ctx.state["kill"] != "off":
        blocked = f"kill switch {ctx.state['kill']}: not looking for new setups"
    elif ctx.status.get("entries_blocked"):
        blocked = f"new entries blocked: {ctx.status['entries_blocked']}"
    status = ctx.derive("strategy", last, blocked=blocked,
                        waiting="waiting for the scam filter to pass a coin" if size == 0 else None,
                        idle=f"watching {size} coin(s); no setup yet" if size else "watchlist not available yet")
    if size is None:
        doing = "Watchlist not available yet."
    elif size == 0:
        doing = "Nothing to watch yet: waiting for a coin that passes the scam filter."
    else:
        closest = ranked[0][1]["label"] if ranked and ranked[0][1]["value"] is not None else None
        doing = (f"Watching {_n(size, 'coin')} for a {s.dip_pct * 100:g}% drop and a bounce back"
                 + (f"; closest: {closest}." if closest else "."))
    if blocked is not None:
        doing = ("Paused by the kill switch" if ctx.state["kill"] != "off"
                 else f"Paused: new buys are blocked ({plain(str(ctx.status['entries_blocked']))})")
        doing += f"; still watching {_n(size, 'coin')}." if size else "."
    trend_stats, trend_events, trend = _trend_desk(ctx)  # after ``last``: the trend desk never sets this chip
    return _panel("strategy", status, last, ctx.text(doing),
                  _headline(f"{size} of {s.watchlist_max}" if size is not None else None, "text",
                            "coins on the watchlist"),
                  [_stat("Required dip", round(s.dip_pct * 100.0, 2), "pct"),
                   _stat("Setups found since boot", _int(counters.get("entry_signals"))),
                   _stat("Candle checks since boot", _int(counters.get("candle_fetches"))), *trend_stats],
                  events + trend_events, bars=[bar for _, bar in ranked[:BARS_MAX]],
                  bars_empty=("Watchlist not available yet." if size is None
                              else "Nothing on the watchlist right now."), trend=trend)


def _trend_desk(ctx: _Ctx) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    """The trend desk (nightcrawler.trenddesk, PAPER), shown with the Strategy member: ``(stats, events, view)``.
    Stats: in or out per coin, and since start (the rule's book in three thirds) against holding the three (bought on
    day one, never touched), plus lab 3's own reckoning of both (re-balanced daily for free) for comparison only;
    events: its flips (and its start, or a restarted record); view: the same figures for the page. Nothing when the
    desk is off or its state cannot be read."""
    if not ctx.settings.trenddesk_enabled:
        return [], [], None
    from nightcrawler import trenddesk

    try:
        d = trenddesk.panel_state(ctx.settings, ctx.now)
        since, hold = float(d["since_start_usd"]), float(d["bh_since_start_usd"])
        lab, lab_hold = float(d["lab_since_start_usd"]), float(d["lab_hold_since_start_usd"])
        booked = d.get("as_of") is not None
        in_market = {c: bool(d["in_market"].get(c)) for c in trenddesk.COINS}
        events = [ctx.event(float(e["ts"]), str(e["text"]), str(e.get("tone") or "neutral"))
                  for e in d.get("events") or [] if isinstance(e, dict) and _num(e.get("ts")) is not None]
    except (KeyError, TypeError, ValueError, AttributeError) as exc:  # a malformed state file: no trend rows
        log.warning("trenddesk_panel_failed error=%s", type(exc).__name__)
        return [], [], None
    stats = [_stat("Trend desk (paper)", trenddesk.in_out_text(in_market) if booked else "no daily close booked yet",
                   "text")]
    stats += [_stat(f"Trend desk {c} (paper)", "in" if in_market[c] else "out", "text") for c in trenddesk.COINS]
    stats += [_stat("Trend desk since start $ (paper)", round(since, 2), "usd"),
              _stat("Holding the three instead $ (paper, bought on day one, never touched)", round(hold, 2), "usd"),
              _stat("Lab benchmark (re-balanced daily, paper)",
                    f"rule {_usd_text(lab)}, holding {_usd_text(lab_hold)}" if booked else "nothing booked yet",
                    "text")]
    reset = d.get("reset_from")
    view = {"label": d.get("label"), "as_of": _num(d.get("as_of")), "started": d.get("started"),
            "in_market": in_market, "since_start_usd": since, "hold_since_start_usd": hold,
            "lab": {"since_start_usd": lab, "hold_since_start_usd": lab_hold},
            "today_usd": _num(d.get("today_usd")), "problem": ctx.text(d["problem"]) if d.get("problem") else None,
            "reset_from": ctx.text(reset, 80) if isinstance(reset, str) and reset else None}
    return stats, events, view


def _usd_text(value: float) -> str:
    """``+$1.10`` / ``-$0.50`` / ``$0.00``: a signed dollar figure inside a text stat."""
    cents = round(value, 2)
    return ("+" if cents > 0 else "-" if cents < 0 else "") + f"${abs(cents):,.2f}"


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
        events.append(ctx.event(f.ts, f"{f.side.upper()} {f.symbol or _short(f.mint)} for "
                                      f"{f.sol_lamports / LAMPORTS_PER_SOL:.4f} SOL at {_price(f.price_usd)} · "
                                      f"price moved {f.price_impact_pct:.2f}% · fees {f.platform_fee_bps / 100:.2f}% "
                                      f"+ {f.fees_lamports / LAMPORTS_PER_SOL:.6f} SOL network"
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
    doing = (f"{_n(nb, 'buy')} and {_n(ns, 'sell')} in the last 24 h, with {'real' if s.is_live else 'pretend'} "
             "money." if day else "No trades in the last 24 h: waiting for a setup that passed every check.")
    if blocks:
        source, why = blocks[0]
        doing = ("No new buys right now: " + _BLOCKED_WORDS.get(source, plain(why)) + "; sells still run.")
    if ctx.open_positions:
        doing += f" Holding {_n(ctx.open_positions, 'trade')}."
    return _panel("broker", status, last, ctx.text(doing),
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
    if pnl > 0:
        text = f"Up {pnl:.4f} SOL today; the bot may lose up to {limit:.4f} SOL ({pct * 100:g}%) before it stops."
    elif pnl == 0:
        text = f"No gain or loss today; the bot may lose up to {limit:.4f} SOL ({pct * 100:g}%) before it stops."
    else:
        text = f"Down {used:.4f} of {limit:.4f} SOL allowed today ({pct * 100:g}% of start-of-day equity)."
    return {"used": used, "limit": limit, "fraction": fraction, "text": text}


def _verdict_stat(v: dict[str, Any]) -> str:
    """A desk book's verdict as a stat value: ``not proven yet``, or ``paused since 18:40 UTC; now losing`` (the
    pause and what the record says now, which may have moved since)."""
    phrase = str(v.get("phrase") or "")
    if not v.get("paused"):
        return phrase
    since = v.get("paused_since") or v.get("since")
    return f"paused since {since}; now {phrase}" if since else f"paused; now {phrase}"


def _desk_verdicts(ctx: _Ctx) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(desks, events)``: the risk manager's verdict on each paper desk's current rule (``nightcrawler.deskguard``
    through the desk's panel state: Polymarket paper, and Polymarket real once it has a real record), and the
    desk's own risk-manager events. Nothing while the desk is off or its state cannot be read."""
    if not ctx.settings.polydesk_enabled:
        return [], []
    from nightcrawler.polydesk import GUARD_EVENTS

    try:
        d = ctx.polydesk()
    except (KeyError, TypeError, ValueError, AttributeError):  # a malformed state file never takes the panel down
        return [], []
    guard = _dict(d.get("guard"))
    desks = []
    for book, name in (("paper", "Polymarket paper"), ("real", "Polymarket real")):
        v = _dict(guard.get(book))
        if not v:
            continue
        desks.append({"desk": name, "verdict": str(v.get("verdict") or ""), "phrase": str(v.get("phrase") or ""),
                      "reason": ctx.text(v.get("reason") or ""), "paused": bool(v.get("paused")),
                      "since": ctx.text(v.get("paused_since"), 40) if v.get("paused_since") else None,
                      "line": ctx.text(v.get("line") or "", 3 * TEXT_MAX)})
    events = [ctx.event(float(e["ts"]), str(e["text"]), str(e.get("tone") or "neutral")) for e in d.get("events") or []
              if isinstance(e, dict) and str(e.get("text") or "").startswith(GUARD_EVENTS)]
    return desks, events


def _risk(ctx: _Ctx) -> dict[str, Any]:
    s, eq = ctx.settings, ctx.state["equity"]
    latest = ctx.ledger.latest_equity()
    last = latest.ts if latest is not None and latest.mode == ctx.mode else None
    events = [ctx.event(d.ts, f"REFUSED {d.symbol or _short(d.mint)} · {plain(d.reason)}", "bad")
              for d in ctx.decisions(("reject_risk",), limit=EVENTS_MAX)]
    desks, desk_events = _desk_verdicts(ctx)
    events += desk_events
    for kind in ("halt", "kill", "reset"):
        receipt = ctx.ledger.last_receipt(kind)
        if receipt is not None:
            p = receipt.payload
            detail = p.get("reason") or p.get("mode") or p.get("note") or ""
            events.append(ctx.event(receipt.ts, f"{kind.upper()} {detail}".strip(),
                                    "neutral" if kind == "reset" else "bad"))
    blocks = [(source, why) for source, why in _entry_blocks(ctx) if source != "engine"]
    status = ctx.derive("risk", last, blocked=blocks[0][1] if blocks else None, idle="no equity snapshot recently")
    meter = _loss_meter(ctx)
    slots = f"{ctx.open_positions} of {s.max_open_positions} trade slots in use"
    doing = {"halt": "Stopped new buys: the money fell too far from its high. It needs your reset.",
             "kill": "Kill switch is on: no new buys.",
             "daily_loss": "Today's loss limit is reached: no new buys until midnight UTC."}.get(
        blocks[0][0] if blocks else "", "")
    if not doing:
        if meter["fraction"] is None:
            doing = f"No money check yet today; {slots}."
        elif eq["pnl_today_sol"] == 0:
            doing = f"Flat today: no gain or loss yet; {slots}."
        elif eq["pnl_today_sol"] > 0:
            doing = f"Up today; {slots}."
        else:
            doing = f"Used {meter['fraction'] * 100:.0f}% of today's loss allowance; {slots}."
    paused = [x["desk"] for x in desks if x["paused"]]
    if paused:
        doing += f" Paused {' and '.join(paused)} buys: the record was losing."
    fraction = meter["fraction"]
    wall = {"allowance_used_pct": round(fraction * 100.0, 1) if fraction is not None else None,
            "slots_used": ctx.open_positions, "slots_max": s.max_open_positions,
            "daily_stop": (fraction > 1.0) if fraction is not None else None,
            "stopped_by": blocks[0][0] if blocks else None,
            "desks": [{"desk": x["desk"], "verdict": x["verdict"], "paused": x["paused"]} for x in desks]}
    return _panel("risk", status, last, ctx.text(doing),
                  _headline(eq["sol"], "sol", "equity (" + ("bot wallet" if s.is_live else "paper wallet") + ")"),
                  [_stat("Equity (USD)", eq["usd"], "usd"), _stat("Today", eq["pnl_today_sol"], "sol"),
                   _stat("Open positions", f"{ctx.open_positions} of {s.max_open_positions}", "text"),
                   _stat("Kill switch", ctx.state["kill"], "text"),
                   _stat("Halted", ctx.text(ctx.state["halted"]["reason"] or "yes", 60)
                         if ctx.state["halted"]["halted"] else "no", "text"),
                   *(_stat(x["desk"], _verdict_stat(x), "text") for x in desks)],
                  events, meter=meter, desks=desks, risk_wall=wall)


def _receipt_line(r: Any) -> str:
    p = _dict(r.payload)
    coin = p.get("symbol") or _short(str(p.get("mint", "")))
    if r.kind == "decision":
        line = f"decision: {_ACTION_WORDS.get(str(p.get('action')), p.get('action'))} {coin}"
    elif r.kind == "fill":
        line = f"trade: {p.get('side')} {coin}"
    elif r.kind == "boot":
        line = f"started v{p.get('version')} ({p.get('mode')})"
    else:
        detail = p.get("event") or p.get("stage") or p.get("mode") or p.get("reason") or p.get("note") or ""
        line = f"{r.kind} {detail}".strip()
    return f"#{r.seq} {line} · {r.hash[:8]}"


def _receipts(ctx: _Ctx) -> dict[str, Any]:
    r = ctx.state["receipts"]
    recent = list(reversed(ctx.ledger.receipts(after_seq=max(0, r["seq"] - EVENTS_MAX))))
    events = [ctx.event(rc.ts, _receipt_line(rc), "bad" if rc.kind == "error" else "neutral") for rc in recent]
    last = max((rc.ts for rc in recent), default=None)
    blocked = f"chain BROKEN at receipt #{r['first_bad_seq']}" if r["verified"] is False else None
    status = ctx.derive("receipts", last, blocked=blocked, idle="no new receipt recently")
    head = r["head_hash"]
    verified = {True: "yes", False: "NO"}.get(r["verified"])
    count = r["count"]
    if r["verified"] is False:
        doing = f"Chain BROKEN at entry #{r['first_bad_seq']}: something was changed after the fact."
    elif count:
        doing = (f"{count:,} {'entry' if count == 1 else 'entries'} sealed; "
                 + ("checked: nothing was edited." if r["verified"] else "not checked yet."))
    else:
        doing = "Nothing recorded yet."
    return _panel("receipts", status, last, ctx.text(doing), _headline(count, "count", "receipts in the chain"),
                  [_stat("Head", r["seq"]), _stat("Verified", verified, "text", r["verified_at"]),
                   _stat("Last receipt", recent[0].kind if recent else None, "text",
                         recent[0].ts if recent else None)],
                  events, sort=False,
                  hash={"head": head, "short": f"{head[:8]}…{head[-8:]}", "explainer": RECEIPTS_EXPLAINER})


def _since_fix_stats(since: dict[str, Any], book: str) -> list[dict[str, Any]]:
    """The current rule version's own record for one book (``paper`` / ``real``), as two stats."""
    rec = _dict(since.get(book))
    return [_stat(f"Since fix ({book}) won/settled", f"{_int(rec.get('won_total')) or 0}/"
                                                     f"{_int(rec.get('settled_total')) or 0}", "text"),
            _stat(f"Since fix $ ({book})", round(_num(rec.get("pnl_total_usd")) or 0.0, 2), "usd")]


def _predict(ctx: _Ctx) -> dict[str, Any]:
    """The Polymarket desk (nightcrawler.polydesk): paper positions and settlements from its state file. The
    desk's own ``Lesson: ...`` events ride along in ``events``; its ``lessons``, ``since_fix`` (the current rule
    version's record, paper and real apart), ``before_fix`` and ``worst`` row ride along for the page, and so does
    ``guard``, the risk manager's view (``polydesk.guard_view``); a pause leads the ``doing`` sentence."""
    d = ctx.polydesk()
    events = [ctx.event(float(e["ts"]), str(e["text"]), str(e.get("tone") or "neutral")) for e in d["events"]]
    since = _dict(d.get("since_fix"))
    last = d["last_ok"]
    if not d["enabled"]:
        status: tuple[str, str] = ("idle", "switched off (POLYDESK_ENABLED)")
    else:
        blocked = f"last round failed ({d['last_error']})" if d["last_error"] and not last else None
        status = ctx.derive("predict", last, blocked=blocked, idle="no round finished recently")
    t = d["today"]
    live = d.get("mode") == "live"
    real, paper = d.get("real") or {}, d.get("paper") or {}
    bal = d.get("balance")
    account = (f" Polymarket account: ${float(bal['cash']):.2f} cash."
               if isinstance(bal, dict) and bal.get("cash") is not None else "")
    if last is None:
        doing = ("Starting up: first look at the venue's markets." if d["enabled"] else "Switched off.") + account
    elif live:
        rt = real["today"]
        doing = (f"Watching {d['watched']:,} markets; {real['open']} real positions open "
                 f"(${real['at_risk_usd']:.2f} at risk); real money today {rt['won']}/{rt['settled']} settled won, "
                 f"{rt['pnl_usd']:+.2f} $; all time {real['won_total']}/{real['settled_total']} won, "
                 f"{real['pnl_total_usd']:+.2f} $." + account)
        if paper["open"] or paper["settled_total"]:
            doing += (f" Paper (pretend, from before the switch): {paper['open']} still running off; "
                      f"{paper['won_total']}/{paper['settled_total']} won, {paper['pnl_total_usd']:+.2f} $.")
    else:
        pt = paper.get("today") or t
        paper_text = (f"Paper (pretend): {paper.get('open', d['open'])} open; today {pt['won']}/{pt['settled']} won, "
                      f"{pt['pnl_usd']:+.2f} $; all time {paper.get('won_total', d['won_total'])}/"
                      f"{paper.get('settled_total', d['settled_total'])} won, {paper.get('pnl_total_usd', d['pnl_total_usd']):+.2f} $.")
        if real and (real["open"] or real["settled_total"]):
            rt = real["today"]
            doing = (f"REAL money (no new buys): {real['open']} open, ${real['at_risk_usd']:.2f} at risk; today "
                     f"{rt['won']}/{rt['settled']} won, {rt['pnl_usd']:+.2f} $; all time {real['won_total']}/"
                     f"{real['settled_total']} won, {real['pnl_total_usd']:+.2f} $. " + paper_text + account)
        else:
            doing = f"Watching {d['watched']:,} markets. " + paper_text + account
    venue = d.get("exchange") if isinstance(d.get("exchange"), dict) else None
    if venue and float(venue.get("contracts") or 0) > 0:
        doing += (f" Venue holds {float(venue['contracts']):g} real contract(s): cost ${float(venue['cost_usd']):.2f}, "
                  f"worth ${float(venue['value_usd']):.2f} now.")
    if d.get("live_status"):
        doing += f" {d['live_status']}"
    guard = _dict(d.get("guard"))
    g_paper, g_real = _dict(guard.get("paper")), _dict(guard.get("real"))
    book = "real" if live else "paper"  # the buys this mode makes (live: a losing paper record stops them too)
    lead = g_real if live else g_paper
    if lead.get("paused"):  # the pause first: the most important thing the desk says
        when = f" since {lead['paused_since']}" if lead.get("paused_since") else ""
        doing = f"Paused by the risk manager{when}: no new {book} buys, the record was losing. " + doing
    if live:
        stats = [_stat("Watching", d["watched"], "count"), _stat("Open (real)", real["open"], "count"),
                 _stat("At risk (real)", round(real["at_risk_usd"], 2), "usd"),
                 _stat("Today $ (real)", round(real["today"]["pnl_usd"], 2), "usd"),
                 _stat("All time $ (real)", round(real["pnl_total_usd"], 2), "usd")]
        if isinstance(bal, dict) and bal.get("cash") is not None:
            stats.append(_stat("Polymarket cash", round(float(bal["cash"]), 2), "usd"))
        stats += _since_fix_stats(since, "real")
        if paper["open"] or paper["settled_total"]:
            stats += [_stat("Open (paper, running off)", paper["open"], "count"),
                      _stat("All time $ (paper)", round(paper["pnl_total_usd"], 2), "usd"),
                      *_since_fix_stats(since, "paper")]
        headline = _headline(real["open"], "count", "real positions open")
    else:  # the paper tallies, never the combined book: real venue contracts can sit in the book in paper mode
        pt = paper.get("today") or t
        stats = [_stat("Watching", d["watched"], "count"), _stat("Open (paper)", paper.get("open", d["open"]), "count"),
                 _stat("Today $ (paper)", round(pt["pnl_usd"], 2), "usd"),
                 _stat("All time $ (paper)", round(paper.get("pnl_total_usd", d["pnl_total_usd"]), 2), "usd"),
                 *_since_fix_stats(since, "paper")]
        if isinstance(bal, dict) and bal.get("cash") is not None:
            stats.append(_stat("Polymarket cash", round(float(bal["cash"]), 2), "usd"))
        if real and (real["open"] or real["settled_total"]):
            stats += [_stat("Open (real)", real["open"], "count"), _stat("At risk (real)", round(real["at_risk_usd"], 2), "usd"),
                      _stat("All time $ (real)", round(real["pnl_total_usd"], 2), "usd"),
                      *_since_fix_stats(since, "real")]
        if venue and float(venue.get("contracts") or 0) > 0:
            stats += [_stat("Venue contracts (real)", float(venue["contracts"]), "count"),
                      _stat("Venue value (real)", round(float(venue["value_usd"]), 2), "usd")]
        headline = _headline(paper.get("open", d["open"]), "count", "paper positions open")
    for book, v in (("paper", g_paper), ("real", g_real)):
        if v:
            stats.append(_stat(f"Risk manager ({book})", _verdict_stat(v), "text"))
    return _panel("predict", status, last, ctx.text(doing), headline, stats, events, rule=d["rule"],
                  positions=d["positions"], label=d["label"], mode=d.get("mode"),
                  open_real=int(real.get("open") or 0), open_paper=int(paper.get("open") or 0),
                  lessons=[ctx.text(str(s)) for s in d.get("lessons") or []], since_fix=d.get("since_fix"),
                  before_fix=d.get("before_fix"), worst=d.get("worst"), guard=d.get("guard"))


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
    doing = f"Running version {__version__}" + (f" for {duration_text(uptime)}." if uptime is not None else ".")
    return _panel("upgrades", status, started_at, ctx.text(doing),
                  _headline(f"v{__version__}", "text", "deployed version"),
                  [_stat("Commit", deploy.get("commit"), "text"),
                   _stat("Commit message", ctx.text(deploy["message"], 120) if deploy.get("message") else None,
                         "text"),
                   _stat("Uptime", uptime, "dur"), _stat("Booted", started_at, "ts")],
                  events)


# =========================================================================== server glue


def json_body(state: dict[str, Any]) -> bytes:
    """Strict JSON bytes with ``<`` escaped: ledger text such as a coin called ``<img ...>`` can never read
    as a tag, even to a client that ignores the content type."""
    text = json.dumps(state, allow_nan=False, separators=(",", ":"), default=str)
    return text.replace("<", "\\u003c").encode("utf-8")


class TeamRoom:
    """The live-data routes for :class:`~nightcrawler.dashboard.DashboardServer`: ``/api/team``
    (:func:`build_team_state`) and ``/api/page`` (:func:`nightcrawler.pagestate.build_page_state`, the one
    page's data). Both share one chain-verification cache and one counter memory.

    ``ledger`` is the engine's own ledger (``build_app`` and ``nightcrawler dashboard`` pass theirs). Only
    when None (standalone use) is ``settings.db_path`` opened lazily on the first request, READ-ONLY (never
    created or migrated), and closed by :meth:`close`. :meth:`close` and :meth:`open` follow the server's
    ``stop()``/``start()``: a closed room answers 500 and never reopens a ledger.
    """

    def __init__(self, settings: Settings, ledger: Any = None, clock: Clock | None = None,
                 environ: Mapping[str, str] | None = None) -> None:
        self.settings = settings
        self.clock = clock if clock is not None else RealClock()
        self._ledger = ledger
        self._owns_ledger = ledger is None
        self._secrets = tuple(settings.secret_values())
        self.deploy = deploy_info(os.environ if environ is None else environ, self._secrets)
        self._verify_cache: dict[str, Any] = {}
        self._memory: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._closed = False

    def state(self) -> dict[str, Any]:
        """``/api/team`` for now, scrubbed of secrets."""
        return self._build(build_team_state)

    def page_state(self) -> dict[str, Any]:
        """``/api/page`` for now, scrubbed of secrets."""
        from nightcrawler.pagestate import build_page_state  # late: pagestate builds on this module

        return self._build(build_page_state)

    def _build(self, builder: Callable[..., dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                raise RuntimeError("team room is closed")
            if self._ledger is None:
                self._ledger = Ledger(self.settings.db_path, clock=self.clock, read_only=True)
            state = builder(self._ledger, self.settings, self.clock.now(), verify_cache=self._verify_cache,
                            memory=self._memory, deploy=self.deploy)
        clean: dict[str, Any] = scrub(state, self._secrets)
        return clean

    def response(self, path: str, headers: list[tuple[str, str]]) -> tuple[int, bytes, str, list[tuple[str, str]]]:
        """``(status, body, content type, headers)`` for an AUTHORIZED request to ``/api/team`` or ``/api/page``."""
        page = path == "/api/page"
        try:
            body = json_body(self.page_state() if page else self.state())
        except Exception:
            log.exception("page_state_failed" if page else "team_state_failed")
            error = b'{"error":"page state unavailable"}' if page else b'{"error":"team state unavailable"}'
            return 500, error, "application/json", headers
        return 200, body, "application/json", headers

    def open(self) -> None:
        """Serve again after :meth:`close` (the dashboard server calls this from ``start()``)."""
        with self._lock:
            self._closed = False

    def close(self) -> None:
        """Close the ledger this object opened itself (idempotent); requests answer 500 until :meth:`open`."""
        with self._lock:
            self._closed = True
            if self._owns_ledger and self._ledger is not None:
                self._ledger.close()
                self._ledger = None
