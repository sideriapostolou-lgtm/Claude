"""Read-only phone dashboard (owner: O6). stdlib only; no external assets.

``DashboardServer`` runs ``http.server.ThreadingHTTPServer`` on
``DASHBOARD_HOST:PORT`` (default ``0.0.0.0:8080``; Railway sets ``PORT``) in a
daemon thread. Routes (GET only; anything else -> 405; unknown path -> 404):

* ``/healthz`` -> 200 ``text/plain`` ``ok`` (no auth; Railway health check).
* ``/api/state`` -> 200 JSON from :func:`build_state` (``Cache-Control: no-store``).
* ``/`` -> the single mobile-first HTML page from :func:`render_html`
  (inline CSS/JS, auto-refresh every 15 s by fetching ``/api/state``,
  dark/light via ``prefers-color-scheme``, big PAPER/LIVE badge, equity
  sparkline as inline SVG, positions & trades tables, receipt head hash with
  a "what is this?" explainer).

Auth: if ``DASHBOARD_TOKEN`` is set, ``/`` and ``/api/state`` require
``?token=<value>`` or cookie ``nc_token=<value>`` (constant-time compare);
a valid ``?token=`` sets the cookie (HttpOnly, SameSite=Strict). 401 otherwise.
The cookie the server sets holds an HMAC derived from the token rather than the
token itself (a cookie holding the raw token is accepted too). The page removes
``?token=`` from the address bar and keeps it in memory for its own fetches.
READ-ONLY: no endpoint changes state. NEVER include secrets in any response:
every string in the state is scrubbed of ``settings.secret_values()`` (and
secret-shaped text) before it is served, and request logs never include the
query string.

Hardening: a strict ``Content-Security-Policy`` (``default-src 'none'``; the
inline script and style are allowed by their sha256 hashes only, so injected
markup could not run), ``X-Frame-Options: DENY``, ``nosniff``,
``Referrer-Policy: no-referrer``. Token names/symbols are untrusted data: the
page inserts every value with ``textContent``, never as HTML.

``/api/state`` schema (all keys always present; unknown -> null)::

    {
      "version": str, "generated_at": float, "mode": "PAPER"|"LIVE",
      "kill": "off"|"stop"|"sell_all", "halted": {"halted": bool, "reason": str|null},
      "engine": {"heartbeat": float|null, "started_at": float|null, "status": dict|null,
                 "last_error": str|null},
      "equity": {"sol": float|null, "usd": float|null, "sol_usd": float|null,
                 "start_usd": float|null, "pnl_today_usd": float|null, "pnl_today_sol": float|null,
                 "pnl_total_usd": float|null, "pnl_total_sol": float|null,
                 "pnl_total_trading_usd": float|null,   # pnl_total_sol at today's SOL price
                 "sol_price_effect_usd": float|null,    # pnl_total_usd - pnl_total_trading_usd
                 "curve": [[ts, equity_usd], ...]   # <= 300 points, downsampled},
      "positions": [{"id", "mint", "symbol", "opened_at", "entry_price_usd", "last_price_usd",
                     "value_sol", "unrealized_pnl_sol", "unrealized_pnl_pct", "partial_taken",
                     "foreign_wallet": str|null}],   # live: set when the position is another wallet's
      "fills": [Fill.to_dict() + {"sol": float}],          # last 50, newest first
      "decisions": [Decision.to_dict()],                   # last 50, newest first
      "rejections": {action: count},                       # last 24 h, from decision_counts
      "receipts": {"head_hash": str, "count": int, "verified": bool|null,
                   "first_bad_seq": int|null, "verified_at": float|null},
      "judge": {"mode": str, "model": str, "calls": int, "cost_usd_total": float,
                "cost_usd_today": float},
      "wallet": {"address": str|null},                     # live only, else null
      "safe_mode": {"problems": [str], "defaults_used": [str], "since": float|null}|null
    }

``safe_mode`` (kv ``engine.safe_mode``, RT-9) is set while the bot runs EXITS-ONLY on an
invalid configuration (red chip, problems under Details). ``foreign_wallet`` (F3): a live
position recorded for another wallet than kv ``wallet.pubkey`` - the engine never sells or
counts it, so it is marked apart and left out of "N of max".

The "Today" and "Since start" tiles show the SOL result (the unit risk limits use)
as their headline and colour; USD only as a sub-line, split into the trading result
at today's SOL price and the SOL price effect - over a paper run, SOL/USD moves
dwarf the bot's own P&L. Positions are those of the current TRADING_MODE only.

Additional keys (also always present): ``receipts.seq`` (head seq),
``positions[].cost_sol``, ``cocoon_rules`` ``{rule_id: mints}`` (rug-filter
failures of the last 24 h by the ``[rule]`` prefix of each reason, latest report
per mint), ``activity`` ``{"candidates_24h": int}`` and ``limits``
``{"max_open_positions": int}``. ``unrealized_pnl_*`` is the open position's
whole marked-to-market result (partial-sale proceeds + marked value - cost -
fees - locked rent, :meth:`Position.pnl_lamports`), percent of its cost.

``usage`` (the "API usage" card) - provider calls per UTC day and month from kv
``usage.providers`` (written by ``http.UsageTracker``; provider names only, never
a URL or key) against each free-tier budget::

    {"day": "YYYY-MM-DD", "month": "YYYY-MM", "warn_pct": 80.0, "updated_at": float|null,
     "providers": [{"id", "label", "unit": "calls"|"credits"|"usd", "period": "month"|"day",
                    "calls_today", "calls_month", "used", "budget": number|null,
                    "used_pct": float|null, "level": "ok"|"warn"|"over"|null,
                    "tokens_today", "tokens_month", "cost_usd_today", "cost_usd_month"}]}

The RPC row (Helius or Solana RPC, by ``SOLANA_RPC_URL``), Jupiter, GeckoTerminal,
DexScreener, RugCheck and Anthropic are always listed; other providers once used.
Budgets: ``USAGE_*_MONTHLY_*`` settings (Helius: credits, 1 per RPC call); Anthropic:
``JUDGE_MAX_DAILY_USD`` per day, measured by the judge's own kv ``judge.cost_usd_day``.
``tokens_*``/``cost_usd_*`` are set for Anthropic only. ``level`` ``warn`` (>= 80 %)
and ``over`` (>= 100 %) also add a chip to the status row.

Chain verification is expensive on long chains: ``build_state`` re-verifies
at most every 5 minutes (cached in the server instance).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import threading
from collections.abc import Callable, Iterable
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from nightcrawler import __version__
from nightcrawler.clock import utc_day
from nightcrawler.config import Settings
from nightcrawler.http import KV_USAGE, PROVIDERS, host_of, provider_of
from nightcrawler.logging_setup import get_logger, redact_text
from nightcrawler.models import LAMPORTS_PER_SOL, Position

__all__ = [
    "CONTENT_SECURITY_POLICY",
    "COOKIE_NAME",
    "REFRESH_S",
    "VERIFY_EVERY_S",
    "DashboardServer",
    "build_state",
    "render_html",
]

log = get_logger(__name__)

VERIFY_EVERY_S = 300
REFRESH_S = 15
COOKIE_NAME = "nc_token"
COOKIE_MAX_AGE_S = 30 * 86_400
DAY_S = 86_400
CURVE_DAYS = 30
CURVE_MAX_POINTS = 300
RECENT_LIMIT = 50
KILL_MODES = ("off", "stop", "sell_all")
_RULE_PREFIX = re.compile(r"^\[([A-Za-z0-9_]+)\]")
_COOKIE_CONTEXT = b"nightcrawler-dashboard-cookie-v1"
#: A provider at or above this PERCENT of its budget gets a warning chip (100 % and more: red).
USAGE_WARN_PCT = 80.0
#: Always on the Usage panel after the RPC row (Helius or Solana RPC, by SOLANA_RPC_URL); others once used.
_USAGE_CORE = ("jupiter", "geckoterminal", "dexscreener", "rugcheck", "anthropic")
#: provider -> (Settings field holding its monthly budget, the unit counted against it)
_MONTHLY_BUDGETS = {
    "helius": ("usage_helius_monthly_credits", "credits"),
    "jupiter": ("usage_jupiter_monthly_calls", "calls"),
    "geckoterminal": ("usage_geckoterminal_monthly_calls", "calls"),
    "dexscreener": ("usage_dexscreener_monthly_calls", "calls"),
    "rugcheck": ("usage_rugcheck_monthly_calls", "calls"),
}


# =========================================================================== state


def build_state(ledger: Any, settings: Settings, now: float,
                verify_cache: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assemble the ``/api/state`` JSON (schema in the module docstring) from the ledger ONLY.

    No network calls: prices come from what the engine last stored
    (``Position.last_price_usd``, ``EquityPoint.sol_usd``). ``verify_cache``
    is a mutable dict the server keeps between calls to throttle chain verification.
    """
    mode = "live" if settings.is_live else "paper"
    equity = _equity(ledger, mode, now)
    state = {
        "version": __version__,
        "generated_at": now,
        "mode": mode.upper(),
        "kill": _kill(ledger, settings),
        "halted": _halted(ledger),
        "engine": _engine(ledger),
        "equity": equity,
        "positions": _positions(ledger, settings, mode, equity["sol_usd"]),
        "fills": [{**f.to_dict(), "sol": f.sol_lamports / LAMPORTS_PER_SOL} for f in ledger.fills(limit=RECENT_LIMIT)],
        "decisions": [d.to_dict() for d in ledger.decisions(limit=RECENT_LIMIT)],
        "rejections": ledger.decision_counts(since=now - DAY_S),
        "cocoon_rules": _cocoon_rules(ledger.safety_failures(since=now - DAY_S).values()),
        "activity": {"candidates_24h": ledger.candidate_count(since=now - DAY_S)},
        "receipts": _receipts(ledger, now, verify_cache if verify_cache is not None else {}),
        "judge": _judge(ledger, settings, now),
        "wallet": {"address": _str_or_none(ledger.get_kv("wallet.pubkey")) if settings.is_live else None},
        "limits": {"max_open_positions": settings.max_open_positions},
        "usage": _usage(ledger, settings, now),
        "safe_mode": _safe_mode(ledger),
    }
    return scrub(state, settings.secret_values())


def scrub(value: Any, secrets: Iterable[str]) -> Any:
    """Copy of a JSON-like structure with secrets redacted from every string (keys too)
    and non-finite floats replaced by None, so the result is always valid, safe JSON."""
    secrets = tuple(secrets)
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {scrub(str(k), secrets): scrub(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v, secrets) for v in value]
    return value


def _str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _num_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _kill(ledger: Any, settings: Settings) -> str:
    """What the engine last applied (kv ``engine.kill_mode``), else the configured switch."""
    applied = ledger.get_kv("engine.kill_mode")
    return applied if applied in KILL_MODES else settings.kill_switch


def _halted(ledger: Any) -> dict[str, Any]:
    state = ledger.get_kv("risk.halted")
    if not isinstance(state, dict) or not state.get("halted"):
        return {"halted": False, "reason": None}
    return {"halted": True, "reason": _str_or_none(state.get("reason"))}


def _engine(ledger: Any) -> dict[str, Any]:
    status = ledger.get_kv("engine.status")
    error = ledger.get_kv("engine.last_error")
    if isinstance(error, (dict, list)):
        error = json.dumps(error, sort_keys=True, default=str)
    return {"heartbeat": _num_or_none(ledger.get_kv("engine.heartbeat")),
            "started_at": _num_or_none(ledger.get_kv("engine.started_at")),
            "status": status if isinstance(status, dict) else None,
            "last_error": _str_or_none(error)}


def _equity(ledger: Any, mode: str, now: float) -> dict[str, Any]:
    """Equity, P&L today (vs the first snapshot of the UTC day) and since the start of this wallet."""
    today = [p for p in ledger.equity_series(since=now - now % DAY_S) if p.mode == mode]
    latest = ledger.latest_equity()
    if latest is not None and latest.mode != mode:
        latest = today[-1] if today else None
    start_lamports = _num_or_none(ledger.get_kv(f"{mode}.start_lamports"))
    start_sol_usd = _num_or_none(ledger.get_kv(f"{mode}.start_sol_usd"))
    start_usd = start_lamports / LAMPORTS_PER_SOL * start_sol_usd if start_lamports and start_sol_usd else None
    out: dict[str, Any] = {"sol": None, "usd": None, "sol_usd": None, "start_usd": start_usd,
                           "pnl_today_usd": None, "pnl_today_sol": None, "pnl_total_usd": None, "pnl_total_sol": None,
                           "pnl_total_trading_usd": None, "sol_price_effect_usd": None,
                           "curve": [[ts, usd] for ts, usd in ledger.equity_curve(
                               since=now - CURVE_DAYS * DAY_S, max_points=CURVE_MAX_POINTS, mode=mode)]}
    if latest is None:
        return out
    out.update(sol=latest.equity_lamports / LAMPORTS_PER_SOL, usd=latest.equity_usd, sol_usd=latest.sol_usd)
    if today:
        out["pnl_today_usd"] = latest.equity_usd - today[0].equity_usd
        out["pnl_today_sol"] = (latest.equity_lamports - today[0].equity_lamports) / LAMPORTS_PER_SOL
    if start_lamports is not None:
        out["pnl_total_sol"] = (latest.equity_lamports - start_lamports) / LAMPORTS_PER_SOL
    if start_lamports is not None:
        out["pnl_total_trading_usd"] = out["pnl_total_sol"] * latest.sol_usd
    if start_usd is not None:
        out["pnl_total_usd"] = latest.equity_usd - start_usd
        if out["pnl_total_trading_usd"] is not None:
            out["sol_price_effect_usd"] = out["pnl_total_usd"] - out["pnl_total_trading_usd"]
    return out


def _safe_mode(ledger: Any) -> dict[str, Any] | None:
    """kv ``engine.safe_mode``: the exits-only banner of a bot running on an invalid configuration (RT-9)."""
    banner = ledger.get_kv("engine.safe_mode")
    if not isinstance(banner, dict):
        return None
    return {"problems": [str(x) for x in banner.get("problems") or []],
            "defaults_used": [str(x) for x in banner.get("defaults_used") or []],
            "since": _num_or_none(banner.get("since"))}


def _positions(ledger: Any, settings: Settings, mode: str, sol_usd: float | None) -> list[dict[str, Any]]:
    """Open positions of ``mode``; live ones recorded for ANOTHER wallet than kv ``wallet.pubkey`` (F3:
    the engine never sells or counts them) carry that wallet in ``foreign_wallet``."""
    positions = ledger.open_positions(mode=mode)
    own = ledger.get_kv("wallet.pubkey") if settings.is_live else None
    lookup = getattr(ledger, "position_wallets", None)
    foreign: dict[str, Any] = {}
    if isinstance(own, str) and own and lookup is not None and positions:
        foreign = {pid: w for pid, w in lookup([p.id for p in positions]).items() if w and w != own}
    return [_position(p, sol_usd, foreign.get(p.id)) for p in positions]


def _position(p: Position, sol_usd: float | None, foreign_wallet: str | None = None) -> dict[str, Any]:
    """Marked with the engine's last price and the latest equity SOL price (None when unknown)."""
    value = pnl = None
    if p.last_price_usd is not None and sol_usd:
        value = p.value_lamports(p.last_price_usd, sol_usd)
        pnl = p.pnl_lamports(p.last_price_usd, sol_usd)
    return {"id": p.id, "mint": p.mint, "symbol": p.symbol, "opened_at": p.opened_at,
            "entry_price_usd": p.entry_price_usd, "last_price_usd": p.last_price_usd,
            "value_sol": None if value is None else value / LAMPORTS_PER_SOL,
            "cost_sol": p.cost_lamports / LAMPORTS_PER_SOL,
            "unrealized_pnl_sol": None if pnl is None else pnl / LAMPORTS_PER_SOL,
            "unrealized_pnl_pct": pnl / p.cost_lamports * 100.0 if pnl is not None and p.cost_lamports else None,
            "partial_taken": p.partial_taken, "foreign_wallet": _str_or_none(foreign_wallet)}


def rule_id(reason: str) -> str:
    """Group key of a Cocoon hard-fail reason: ``"[top10] ..."`` -> ``top10``."""
    match = _RULE_PREFIX.match(reason)
    if match:
        return match.group(1)
    return "source_unavailable" if reason.startswith("source unavailable") else "other"


def _cocoon_rules(failures: Iterable[list[str]]) -> dict[str, int]:
    """``{rule_id: number of mints}`` sorted by count (desc) then rule id."""
    counts: dict[str, int] = {}
    for reasons in failures:
        for rule in {rule_id(str(r)) for r in reasons}:
            counts[rule] = counts.get(rule, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _receipts(ledger: Any, now: float, cache: dict[str, Any]) -> dict[str, Any]:
    seq, head = ledger.head()
    if not cache or now - cache["verified_at"] >= VERIFY_EVERY_S:
        ok, first_bad = ledger.verify_chain()
        cache.update(verified=ok, first_bad_seq=first_bad, verified_at=now)
    return {"head_hash": head, "seq": seq, "count": ledger.receipt_count(), "verified": cache["verified"],
            "first_bad_seq": cache["first_bad_seq"], "verified_at": cache["verified_at"]}


def _judge(ledger: Any, settings: Settings, now: float) -> dict[str, Any]:
    day = ledger.get_kv("judge.cost_usd_day")
    today = _num_or_none(day.get("usd")) if isinstance(day, dict) and day.get("day") == utc_day(now) else None
    return {"mode": settings.judge_mode, "model": settings.judge_model,
            "calls": int(_num_or_none(ledger.get_kv("judge.calls")) or 0),
            "cost_usd_total": _num_or_none(ledger.get_kv("judge.cost_usd_total")) or 0.0,
            "cost_usd_today": today or 0.0}


def _usage(ledger: Any, settings: Settings, now: float) -> dict[str, Any]:
    """Provider calls this UTC day/month (kv ``usage.providers``, written by ``http.UsageTracker``)
    against each free-tier budget. Only provider names are shown - never a URL, host or key."""
    stored = ledger.get_kv(KV_USAGE)
    stored = {k: v for k, v in stored.items() if isinstance(v, dict)} if isinstance(stored, dict) else {}
    day = utc_day(now)
    rpc_host = host_of(settings.solana_rpc_url)
    ids = [provider_of(rpc_host, rpc_host), *_USAGE_CORE]
    ids += [p for p in PROVIDERS if p in stored and p not in ids]
    stamps = [v["updated_at"] for v in stored.values() if _num_or_none(v.get("updated_at")) is not None]
    return {"day": day, "month": day[:7], "warn_pct": USAGE_WARN_PCT, "updated_at": max(stamps, default=None),
            "providers": [_usage_row(p, stored.get(p, {}), day, ledger, settings) for p in ids]}


def _period_counts(entry: dict[str, Any], period: str, key: str) -> dict[str, float]:
    """``entry``'s day/month counters when they belong to ``key`` (today / this month), else ``{}``."""
    counts = entry.get(f"{period}_counts")
    if entry.get(period) != key or not isinstance(counts, dict):
        return {}
    return {name: value for name, value in counts.items() if _num_or_none(value) is not None}


def _usage_row(provider: str, entry: dict[str, Any], day: str, ledger: Any, settings: Settings) -> dict[str, Any]:
    today, month = _period_counts(entry, "day", day), _period_counts(entry, "month", day[:7])
    row: dict[str, Any] = {"id": provider, "label": PROVIDERS[provider], "unit": "calls", "period": "month",
                           "calls_today": today.get("calls", 0), "calls_month": month.get("calls", 0),
                           "used": month.get("calls", 0), "budget": None, "used_pct": None, "level": None,
                           "tokens_today": None, "tokens_month": None, "cost_usd_today": None, "cost_usd_month": None}
    if provider == "anthropic":  # budget: JUDGE_MAX_DAILY_USD, measured like the judge enforces it
        judged = ledger.get_kv("judge.cost_usd_day")
        spent = _num_or_none(judged.get("usd")) if isinstance(judged, dict) and judged.get("day") == day else None
        spent = spent if spent is not None else today.get("cost_usd", 0.0)
        row.update(unit="usd", period="day", used=spent, budget=float(settings.judge_max_daily_usd),
                   tokens_today=today.get("input_tokens", 0) + today.get("output_tokens", 0),
                   tokens_month=month.get("input_tokens", 0) + month.get("output_tokens", 0),
                   cost_usd_today=spent, cost_usd_month=month.get("cost_usd", 0.0))
    elif provider in _MONTHLY_BUDGETS:
        field_name, unit = _MONTHLY_BUDGETS[provider]
        budget = getattr(settings, field_name)
        row.update(unit=unit, used=month.get(unit, 0), budget=budget if budget > 0 else None)
    if row["budget"]:
        row["used_pct"] = row["used"] / row["budget"] * 100.0
        row["level"] = ("over" if row["used_pct"] >= 100.0 else
                        "warn" if row["used_pct"] >= USAGE_WARN_PCT else "ok")
    return row


# =========================================================================== page

_STYLE = r"""
:root{color-scheme:light;--page:#f9f9f7;--card:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--hair:#e1e0d9;--border:rgba(11,11,11,.10);--accent:#2a78d6;--accent-soft:rgba(42,120,214,.12);
--up:#006300;--down:#c22f2f;--good:#0ca30c;--warn:#fab219;--serious:#ec835a;--critical:#d03b3b;
--paper:#256abf;--live:#d03b3b;--tag-buy:rgba(42,120,214,.14);--tag-sell:rgba(235,104,52,.16)}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--page:#0d0d0d;--card:#1a1a19;--ink:#fff;
--ink2:#c3c2b7;--hair:#2c2c2a;--border:rgba(255,255,255,.10);--accent:#3987e5;--accent-soft:rgba(57,135,229,.16);
--up:#0ca30c;--down:#e66767;--paper:#2a78d6;--tag-buy:rgba(57,135,229,.22);--tag-sell:rgba(217,89,38,.26)}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--page);color:var(--ink);font:16px/1.45 system-ui,-apple-system,"Segoe UI",
Roboto,sans-serif;padding:16px 16px calc(24px + env(safe-area-inset-bottom))}
main{max-width:720px;margin:0 auto}
header{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:12px}
.brand{font-weight:700;font-size:18px;letter-spacing:.01em}
.brand small{font-weight:400;color:var(--ink2);font-size:13px;margin-left:6px}
.updated{color:var(--ink2);font-size:13px;text-align:right}
.badge{display:block;text-align:center;color:#fff;border-radius:16px;padding:14px 12px 12px;
background:var(--paper)}
.badge b{display:block;font-size:34px;line-height:1.1;letter-spacing:.14em;font-weight:800}
.badge span{font-size:14px;opacity:.92}
.badge.live{background:var(--live)}
.banner{margin-top:12px;padding:10px 14px;border-radius:12px;background:var(--warn);color:#0b0b0b;
font-weight:600;font-size:14px}
.banner[hidden]{display:none}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--border);border-radius:999px;
padding:5px 11px;font-size:13px;font-weight:600;background:var(--card);max-width:100%}
.chip i{width:9px;height:9px;border-radius:50%;flex:none;background:var(--muted)}
.chip.good i{background:var(--good)}.chip.warn i{background:var(--warn)}
.chip.serious i{background:var(--serious)}.chip.critical i{background:var(--critical)}
.chip.critical{border-color:var(--critical)}
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:16px;margin-top:12px}
.card[hidden]{display:none}
h2{font-size:15px;font-weight:650;margin:0 0 10px;display:flex;justify-content:space-between;gap:8px}
h2 small{font-weight:500;color:var(--ink2)}
.hero{font-size:48px;font-weight:650;line-height:1.05;letter-spacing:-.01em}
.sub{color:var(--ink2);font-size:14px;margin-top:4px}
.tiles{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px}
.tile{border:1px solid var(--border);border-radius:12px;padding:10px 12px;min-width:0}
.tile .label{color:var(--ink2);font-size:13px}
.tile .value{font-size:22px;font-weight:650;margin-top:2px}
.tile .sub{margin-top:0;font-size:13px}
.up{color:var(--up)}.down{color:var(--down)}
.readout{display:flex;justify-content:space-between;gap:8px;margin-top:16px;font-size:13px;color:var(--ink2)}
.readout b{color:var(--ink);font-size:15px}
.chart{margin-top:4px;touch-action:pan-y;outline:none}
.chart svg{display:block;width:100%;height:132px}
.chart:focus-visible{box-shadow:0 0 0 2px var(--accent);border-radius:8px}
.chart .area{fill:var(--accent);fill-opacity:.10;stroke:none}
.chart .ln{fill:none;stroke:var(--accent);stroke-width:2;stroke-linejoin:round}
.chart .start{stroke:var(--muted);stroke-width:1;stroke-dasharray:4 4}
.chart .cross{stroke:var(--ink2);stroke-width:1}
.axis{display:flex;justify-content:space-between;color:var(--ink2);font-size:12px;
font-variant-numeric:tabular-nums}
.empty{color:var(--ink2);font-size:14px;margin:4px 0}
.list>div{border-top:1px solid var(--hair);padding:10px 0}
.list>div:first-child{border-top:0;padding-top:2px}
.line{display:flex;justify-content:space-between;align-items:baseline;gap:10px;min-width:0}
.line>*{min-width:0}
.line>.meta{flex:none;white-space:nowrap}
.bars .line{font-size:14px;margin-top:8px}
.name{font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.name small{font-weight:400;color:var(--ink2);margin-left:6px;font-size:12px}
.big{font-size:20px;font-weight:650;white-space:nowrap}
.meta{color:var(--ink2);font-size:13px;margin-top:2px;overflow-wrap:anywhere}
.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.tag{display:inline-block;font-size:12px;font-weight:700;border-radius:6px;padding:1px 7px;margin-right:6px;
background:var(--accent-soft);vertical-align:1px;white-space:nowrap}
.tag.buy{background:var(--tag-buy)}.tag.sell{background:var(--tag-sell)}
.tag.reject{background:rgba(208,59,59,.14)}.tag.ok{background:rgba(12,163,12,.16)}
.reason{color:var(--ink2);font-size:13px;margin-top:2px;overflow-wrap:anywhere;display:-webkit-box;
-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.funnel{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.funnel div{border:1px solid var(--border);border-radius:12px;padding:8px 10px;min-width:0}
.funnel b{display:block;font-size:22px;font-weight:650}
.funnel span{color:var(--ink2);font-size:12px}
.bars{margin-top:14px}
.bar{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 10px;margin-top:10px;font-size:14px}
.bar .track{grid-column:1/-1;height:8px;border-radius:4px;background:var(--hair);overflow:hidden}
.bar .fill{height:100%;border-radius:4px;background:var(--accent);min-width:4px}
.bar .fill.warn{background:var(--warn)}.bar .fill.over{background:var(--critical)}
.bar .meta{grid-column:1/-1;margin-top:0}
.sublabel{color:var(--ink2);font-size:13px;margin:14px 0 0}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px;word-break:break-all}
.hash{margin-top:8px;padding:10px 12px;border-radius:10px;background:var(--page);border:1px solid var(--border)}
button{font:inherit;font-size:13px;font-weight:600;color:var(--ink);background:var(--page);
border:1px solid var(--border);border-radius:8px;padding:6px 12px;margin-top:8px;cursor:pointer}
details{margin-top:10px}
summary{cursor:pointer;color:var(--accent);font-weight:600;font-size:14px}
details p{color:var(--ink2);font-size:14px;margin:8px 0 0}
dl{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:0;font-size:14px}
dt{color:var(--ink2)}dd{margin:0;overflow-wrap:anywhere}
footer{color:var(--ink2);font-size:12px;text-align:center;margin-top:20px}
main.stale .card,main.stale .badge{opacity:.6}
"""

_SCRIPT = r"""
"use strict";
(() => {
  const body = document.body;
  const REFRESH_MS = Number(body.dataset.refresh || 15) * 1000;
  const SVG = "http://www.w3.org/2000/svg";
  const MINUS = "−";
  const $ = (id) => document.getElementById(id);
  let token = null, timer = null, last = null, lastOkAt = null, lastOkTs = null, serverOffset = 0;

  const params = new URLSearchParams(location.search);
  if (params.has("token")) {
    token = params.get("token");
    params.delete("token");
    const rest = params.toString();
    history.replaceState(null, "", location.pathname + (rest ? "?" + rest : "") + location.hash);
  }

  // ---------------------------------------------------------------- helpers (text only, never HTML)
  function el(tag, cls, ...kids) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    for (const k of kids) if (k !== null && k !== undefined && k !== false) node.append(k);
    return node;
  }
  // Fill a card. Missing parts are dropped: replaceChildren(null) would show the word "null".
  function put(node, ...kids) {
    node.replaceChildren(...kids.filter((k) => k !== null && k !== undefined && k !== false));
  }
  function svg(tag, attrs) {
    const node = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
    return node;
  }
  const isNum = (v) => typeof v === "number" && isFinite(v);
  const sign = (v, signed) => (v < 0 ? MINUS : signed && v > 0 ? "+" : "");
  const tone = (v) => (isNum(v) && v > 0 ? "up" : isNum(v) && v < 0 ? "down" : "");
  function usd(v, signed) {
    if (!isNum(v)) return "—";
    const a = Math.abs(v);
    return sign(v, signed) + "$" + (a >= 1000 ? a.toLocaleString(undefined, {maximumFractionDigits: 0}) : a.toFixed(2));
  }
  function sol(v, signed, digits) {
    return isNum(v) ? sign(v, signed) + Math.abs(v).toFixed(digits || 4) + " SOL" : "—";
  }
  function pct(v) { return isNum(v) ? sign(v, true) + Math.abs(v).toFixed(1) + "%" : "—"; }
  function plainPct(v) { return isNum(v) ? v.toFixed(2) + "%" : "—"; }
  function price(v) {
    if (!isNum(v) || v <= 0) return "—";
    if (v >= 1) return "$" + v.toFixed(4);
    return "$" + (v >= 1e-6 ? v.toPrecision(4) : v.toExponential(2));
  }
  const nowS = () => Date.now() / 1000 + serverOffset;
  function ago(ts) {
    if (!isNum(ts)) return "—";
    const s = Math.max(0, nowS() - ts);
    if (s < 60) return Math.round(s) + "s ago";
    if (s < 3600) return Math.round(s / 60) + "m ago";
    if (s < 86400) return Math.round(s / 3600) + "h ago";
    return Math.round(s / 86400) + "d ago";
  }
  function held(ts) { return isNum(ts) ? ago(ts).replace(" ago", "") : "—"; }
  function when(ts) {
    if (!isNum(ts)) return "—";
    const d = new Date(ts * 1000);
    const sameDay = d.toDateString() === new Date(nowS() * 1000).toDateString();
    return sameDay ? d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})
      : d.toLocaleString([], {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"});
  }
  const short = (s) => (typeof s === "string" && s.length > 12 ? s.slice(0, 4) + "…" + s.slice(-4) : s || "");
  const symbolOf = (o) => o.symbol || short(o.mint);

  // ---------------------------------------------------------------- sections
  const RULES = {
    mint_authority: "Creator can still mint more", freeze_authority: "Creator can freeze wallets",
    token2022_ext: "Dangerous token extensions", rugged: "Already rugged", rugcheck_danger: "RugCheck danger flags",
    top10: "Top 10 wallets hold too much", single_holder: "One wallet holds too much",
    creator_holding: "Creator still holds too much", insiders: "Insider wallet network",
    serial_launcher: "Serial coin launcher", shield: "Jupiter Shield warning", lp_unlocked: "Liquidity not locked",
    source_unavailable: "Could not verify (data source down)", other: "Other",
  };
  const OTHER_REJECTIONS = [
    ["reject_radar", "Big sells spotted (radar)"], ["reject_judge", "AI judge said no"],
    ["reject_risk", "Risk limits"], ["reject_quote", "Bad quote (impact / error)"],
  ];
  const ACTIONS = {
    reject_prefilter: "Prefilter", reject_cocoon: "Rug filter", watch: "Watching", unwatch: "Unwatched",
    no_signal: "No setup", reject_radar: "Radar", reject_judge: "Judge", reject_risk: "Risk",
    reject_quote: "Quote", enter: "Bought", exit: "Sold", exit_partial: "Took profit", hold: "Hold",
    kill: "Kill switch", error: "Error",
  };

  function renderStatus(s) {
    const live = s.mode === "LIVE";
    const badge = $("badge");
    badge.className = "badge" + (live ? " live" : "");
    put(badge, el("b", null, live ? "LIVE" : "PAPER"), el("span", null,
      live ? "Real money · signed swaps through Jupiter" : "Simulated fills from live Jupiter quotes"));
    const chips = [];
    const hb = s.engine.heartbeat;
    const age = isNum(hb) ? nowS() - hb : null;
    if (age === null) chips.push(["", "Engine: not started yet"]);
    else if (age < 180) chips.push(["good", "Engine running · " + ago(hb)]);
    else if (age < 900) chips.push(["warn", "Engine slow · last seen " + ago(hb)]);
    else chips.push(["critical", "Engine stopped · last seen " + ago(hb)]);
    if (s.kill === "stop") chips.push(["warn", "Kill switch: STOP (no new buys)"]);
    if (s.kill === "sell_all") chips.push(["critical", "Kill switch: SELL ALL"]);
    if (s.halted.halted) chips.push(["serious", "Halted: " + (s.halted.reason || "drawdown limit")]);
    const status = s.engine.status || {};
    if (status.drift && Object.keys(status.drift).length) {
      chips.push(["critical", "Wallet differs from the books (" + Object.keys(status.drift).length
        + " coin) · new buys blocked"]);
    }
    if (status.unresolved_swaps && status.unresolved_swaps.length) {
      chips.push(["serious", "Unresolved swap: checking the wallet · new buys blocked"]);
    }
    if (s.safe_mode) chips.push(["critical", "SAFE MODE: invalid configuration · exits only, no new buys"]);
    const foreign = s.positions.filter((p) => p.foreign_wallet).length;
    if (foreign) {
      chips.push(["serious", foreign + " live position" + (foreign > 1 ? "s" : "") + " in another wallet · "
        + "not sold by this bot"]);
    }
    chips.push(...usageChips(s.usage));
    put($("chips"), ...chips.map(([cls, text]) => el("span", "chip " + cls, el("i"), text)));
  }

  // ---------------------------------------------------------------- provider usage (free-tier budgets)
  const PERIOD = {day: "daily", month: "monthly"};
  function usageChips(u) {
    return ((u && u.providers) || []).filter((r) => r.level === "warn" || r.level === "over").map((r) =>
      r.level === "over"
        ? ["critical", r.label + " over its " + PERIOD[r.period] + " budget (" + Math.round(r.used_pct) + "%)"]
        : ["warn", r.label + " at " + Math.round(r.used_pct) + "% of its " + PERIOD[r.period] + " budget"]);
  }
  function compact(n) {
    if (!isNum(n)) return "—";
    if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (Math.abs(n) >= 1e4) return (n / 1e3).toFixed(1) + "k";
    return Math.round(n).toLocaleString();
  }
  function amount(v, unit) { return unit === "usd" ? usd(v) : compact(v) + " " + unit; }

  function renderUsage(u) {
    const rows = u.providers.map((r) => {
      const budget = isNum(r.budget) && r.budget > 0;
      const right = budget ? Math.round(r.used_pct) + "%" : r.unit === "usd" ? "judge blocked (cap $0)" : "no budget";
      const when = r.period === "day" ? " today" : " this month";
      const used = amount(r.used, r.unit) + (budget ? " of " + amount(r.budget, r.unit) : "") + when;
      const meta = r.unit === "usd"
        ? used + " · " + compact(r.calls_today) + " calls, " + compact(r.tokens_today) + " tokens today · "
          + usd(r.cost_usd_month) + " this month"
        : budget ? used + " · " + compact(r.calls_today) + " calls today"
          : compact(r.calls_today) + " calls today · " + compact(r.calls_month) + " this month";
      const fill = budget ? el("div", "fill " + (r.level === "ok" ? "" : r.level)) : null;
      if (fill) fill.style.width = Math.min(100, r.used_pct).toFixed(1) + "%";
      return el("div", "bar", el("span", null, r.label), el("b", "num " + (r.level === "over" ? "down" : ""), right),
        fill ? el("div", "track", fill) : null, el("div", "meta", meta));
    });
    const counted = isNum(u.updated_at) ? "UTC day & month · counted " + ago(u.updated_at) : "nothing counted yet";
    put($("usage"), el("h2", null, "API usage", el("small", null, counted)),
      el("div", "bars", ...rows),
      el("p", "sublabel", "Free-tier budgets come from the USAGE_* settings and JUDGE_MAX_DAILY_USD; a chip warns at "
        + u.warn_pct + "%."));
  }

  function renderEquity(e, s) {
    const card = $("equity");
    const hasUsd = isNum(e.usd);
    // Headline + colour in SOL (what the bot controls); USD only as context, with the SOL price effect apart.
    const tiles = el("div", "tiles",
      tile("Today", sol(e.pnl_today_sol, true), isNum(e.pnl_today_usd) ? usd(e.pnl_today_usd, true) + " in USD" : "—",
        tone(e.pnl_today_sol)),
      tile("Since start", sol(e.pnl_total_sol, true),
        isNum(e.pnl_total_trading_usd)
          ? usd(e.pnl_total_trading_usd, true) + " at today's SOL price"
            + (isNum(e.sol_price_effect_usd) ? " · SOL price " + usd(e.sol_price_effect_usd, true) : "")
          : usd(e.pnl_total_usd, true),
        tone(e.pnl_total_sol)));
    put(card,
      el("h2", null, "Equity", el("small", null, s.mode === "LIVE" ? "bot wallet" : "virtual wallet")),
      el("div", "hero", hasUsd ? usd(e.usd) : "—"),
      el("div", "sub", hasUsd ? sol(e.sol) + " · SOL " + usd(e.sol_usd)
        : "Waiting for the first equity snapshot…"),
      tiles, chart(e.curve || [], e.start_usd));
  }

  function tile(label, value, sub, cls) {
    return el("div", "tile", el("div", "label", label), el("div", "value " + (cls || ""), value),
      el("div", "sub " + (cls || ""), sub));
  }

  function chart(curve, startUsd) {
    const wrap = el("div");
    if (curve.length < 2) {
      wrap.append(el("p", "empty", "The equity chart appears after a few minutes of running."));
      return wrap;
    }
    const W = 600, H = 132, top = 8, bottom = 8;
    const ts = curve.map((p) => p[0]), vs = curve.map((p) => p[1]);
    let lo = Math.min(...vs), hi = Math.max(...vs);
    if (isNum(startUsd)) { lo = Math.min(lo, startUsd); hi = Math.max(hi, startUsd); }
    if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
    const t0 = ts[0], t1 = ts[ts.length - 1];
    const x = (t) => (t1 > t0 ? (t - t0) / (t1 - t0) : 1) * W;
    const y = (v) => top + (1 - (v - lo) / (hi - lo)) * (H - top - bottom);
    const pts = curve.map((p) => x(p[0]).toFixed(1) + "," + y(p[1]).toFixed(1));
    const plot = svg("svg", {viewBox: "0 0 " + W + " " + H, preserveAspectRatio: "none", "aria-hidden": "true"});
    plot.append(svg("path", {d: "M" + pts.join("L") + "L" + W + "," + H + "L0," + H + "Z", class: "area"}));
    if (isNum(startUsd)) {
      plot.append(svg("line", {x1: 0, x2: W, y1: y(startUsd), y2: y(startUsd), class: "start",
        "vector-effect": "non-scaling-stroke"}));
    }
    plot.append(svg("polyline", {points: pts.join(" "), class: "ln", "vector-effect": "non-scaling-stroke"}));
    const cross = svg("line", {y1: 0, y2: H, class: "cross", "vector-effect": "non-scaling-stroke",
      visibility: "hidden"});
    plot.append(cross);
    const box = el("div", "chart", plot);
    box.tabIndex = 0;
    box.setAttribute("role", "img");
    box.setAttribute("aria-label", "Equity over time, from " + usd(vs[0]) + " to " + usd(vs[vs.length - 1])
      + (isNum(startUsd) ? "; dashed line is the starting " + usd(startUsd) : ""));
    const value = el("b"), at = el("span");
    const readout = el("div", "readout", el("span", null, value, " ", at),
      el("span", null, isNum(startUsd) ? "dashed line = start " + usd(startUsd) : ""));
    let idx = curve.length - 1;
    function show(i, active) {
      idx = Math.max(0, Math.min(curve.length - 1, i));
      value.textContent = usd(vs[idx]);
      at.textContent = active ? when(ts[idx]) : "now";
      cross.setAttribute("x1", x(ts[idx]));
      cross.setAttribute("x2", x(ts[idx]));
      cross.setAttribute("visibility", active ? "visible" : "hidden");
    }
    function nearest(clientX) {
      const r = plot.getBoundingClientRect();
      const t = t0 + ((clientX - r.left) / Math.max(1, r.width)) * (t1 - t0);
      let best = 0;
      for (let i = 1; i < ts.length; i++) if (Math.abs(ts[i] - t) < Math.abs(ts[best] - t)) best = i;
      return best;
    }
    box.addEventListener("pointermove", (ev) => show(nearest(ev.clientX), true));
    box.addEventListener("pointerdown", (ev) => show(nearest(ev.clientX), true));
    box.addEventListener("pointerleave", () => show(curve.length - 1, false));
    box.addEventListener("blur", () => show(curve.length - 1, false));
    box.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") {
        show(idx + (ev.key === "ArrowLeft" ? -1 : 1), true);
        ev.preventDefault();
      }
    });
    show(idx, false);
    wrap.append(readout, box, el("div", "axis", el("span", null, when(t0)), el("span", null, when(t1))));
    return wrap;
  }

  function renderPositions(list, max) {
    const card = $("positions");
    const rows = list.map((p) => el("div", null,
      el("div", "line", el("div", "name", symbolOf(p), el("small", null, short(p.mint))),
        el("div", "big " + tone(p.unrealized_pnl_pct), pct(p.unrealized_pnl_pct))),
      el("div", "line meta",
        el("span", null, "Value " + sol(p.value_sol) + " · cost " + sol(p.cost_sol)),
        el("span", "num " + tone(p.unrealized_pnl_sol), sol(p.unrealized_pnl_sol, true))),
      el("div", "meta", "Entry " + price(p.entry_price_usd) + " → now " + price(p.last_price_usd)
        + " · held " + held(p.opened_at), p.partial_taken ? el("span", null, " · profit partly taken") : null),
      p.foreign_wallet ? el("div", "meta", "In another wallet (" + short(p.foreign_wallet) + "): no stop-loss "
        + "from this bot · run it with that wallet to close") : null));
    const own = list.filter((p) => !p.foreign_wallet).length;
    put(card, el("h2", null, "Open positions", el("small", null, own + " of " + max)),
      rows.length ? el("div", "list", ...rows)
        : el("p", "empty", "No open positions. The bot is watching for a setup."));
  }

  function renderFills(fills) {
    const rows = fills.slice(0, 20).map((f) => el("div", null,
      el("div", "line",
        el("div", "name", el("span", "tag " + f.side, f.side === "buy" ? "BUY" : "SELL"), symbolOf(f)),
        el("div", "num", sol(f.sol))),
      el("div", "meta", when(f.ts) + " · " + price(f.price_usd) + " · impact " + plainPct(f.price_impact_pct)
        + " · fee " + f.platform_fee_bps + " bps" + (f.signature ? " · tx " + short(f.signature) : ""))));
    put($("fills"), el("h2", null, "Recent trades", el("small", null, fills.length ? "newest first" : "")),
      rows.length ? el("div", "list", ...rows)
        : el("p", "empty", "No trades yet. Every paper fill is priced from a live Jupiter quote at the exact size."));
  }

  function renderFilter(s) {
    const counts = s.rejections || {};
    const funnel = el("div", "funnel",
      step(s.activity.candidates_24h, "coins seen"), step(counts.watch || 0, "passed rug filter"),
      step(counts.enter || 0, "bought"));
    const rules = Object.entries(s.cocoon_rules || {});
    const top = rules.length ? rules[0][1] : 0;
    const bars = rules.map(([rule, n]) => {
      const fill = el("div", "fill");
      fill.style.width = (n / top * 100).toFixed(1) + "%";
      return el("div", "bar", el("span", null, RULES[rule] || rule), el("b", "num", String(n)),
        el("div", "track", fill));
    });
    const others = OTHER_REJECTIONS.filter(([key]) => counts[key]).map(([key, label]) =>
      el("div", "line", el("span", null, label), el("b", "num", String(counts[key]))));
    put($("filter"), el("h2", null, "Why coins were skipped", el("small", null, "last 24 h")), funnel,
      bars.length ? el("div", "bars", el("p", "sublabel", "Rug filter failures (coins)"), ...bars)
        : el("p", "sublabel", "No rug-filter failures in the last 24 h."),
      others.length ? el("div", "bars", el("p", "sublabel", "Later checks that said no"), ...others) : null);
  }
  function step(n, label) { return el("div", null, el("b", null, String(n || 0)), el("span", null, label)); }

  function renderDecisions(list) {
    const rows = list.slice(0, 25).map((d) => {
      const bad = d.action.startsWith("reject") || d.action === "error";
      const verdict = d.verdict ? "Jev: " + d.verdict.decision + " (" + Math.round((d.verdict.confidence || 0) * 100)
        + "%) " + (d.verdict.reasons || []).join("; ") : null;
      return el("div", null,
        el("div", "line", el("div", "name", el("span", "tag " + (bad ? "reject" : "ok"), ACTIONS[d.action] || d.action),
          d.symbol || short(d.mint)), el("div", "meta", when(d.ts))),
        el("div", "reason", d.reason || ""), verdict ? el("div", "reason", verdict) : null);
    });
    put($("decisions"), el("h2", null, "Decisions", el("small", null, "newest first")),
      rows.length ? el("div", "list", ...rows) : el("p", "empty", "No decisions recorded yet."));
  }

  function renderReceipts(r) {
    let chip;
    if (r.verified === true) chip = ["good", "Chain verified · " + ago(r.verified_at)];
    else if (r.verified === false) chip = ["critical", "Chain BROKEN at receipt #" + r.first_bad_seq];
    else chip = ["", "Not verified yet"];
    const copy = el("button", null, "Copy hash");
    copy.type = "button";
    copy.addEventListener("click", () => {
      const done = (text) => {
        copy.textContent = text;
        setTimeout(() => { copy.textContent = "Copy hash"; }, 1500);
      };
      if (!navigator.clipboard) return done("Copy not available");
      navigator.clipboard.writeText(r.head_hash).then(() => done("Copied"), () => done("Copy failed"));
    });
    const explain = el("details", null, el("summary", null, "What is this?"),
      el("p", null, "Every decision and every trade is written into a chain of receipts the moment it happens, "
        + "before the bot can see what the price does next. Each receipt includes the SHA-256 fingerprint of the one "
        + "before it, so editing, deleting or reordering any past entry changes every fingerprint after it."),
      el("p", null, "The code above fingerprints the whole history up to receipt #" + r.seq + ". Write it down or post "
        + "it somewhere public: later, “nightcrawler receipts verify” (or about 10 lines of code on the "
        + "exported file) proves that history was never rewritten. It proves honesty, not profit."));
    const head = r.seq > 0 ? [el("div", "hash mono", r.head_hash), copy]
      : [el("p", "empty", "No receipts yet: the chain starts when the engine boots.")];
    put($("receipts"), el("h2", null, "Receipts", el("small", null, r.count.toLocaleString() + " recorded")),
      el("div", "chips", el("span", "chip " + chip[0], el("i"), chip[1])), ...head, explain);
  }

  function renderDetails(s) {
    const j = s.judge;
    const rows = [["Jev (AI judge)", j.mode === "off" ? "off — rules only" : j.mode + " · " + j.model],
      ["Judge calls", String(j.calls)],
      ["Judge cost", usd(j.cost_usd_today) + " today · " + usd(j.cost_usd_total) + " total"]];
    if (s.wallet.address) rows.push(["Bot wallet", s.wallet.address]);
    if (isNum(s.engine.started_at)) rows.push(["Engine started", when(s.engine.started_at)]);
    if (s.safe_mode) rows.push(["Safe mode (fix)", s.safe_mode.problems.join(" · ") || "invalid configuration"]);
    const dl = el("dl");
    for (const [k, v] of rows) dl.append(el("dt", null, k), el("dd", k === "Bot wallet" ? "mono" : null, v));
    const err = s.engine.last_error
      ? el("details", null, el("summary", null, "Last engine error"), el("p", "mono", s.engine.last_error)) : null;
    put($("details"), el("h2", null, "Details"), dl, err);
  }

  function render(s) {
    last = s;
    renderStatus(s);
    renderEquity(s.equity, s);
    renderPositions(s.positions, s.limits.max_open_positions);
    renderFills(s.fills);
    renderFilter(s);
    renderDecisions(s.decisions);
    renderReceipts(s.receipts);
    renderUsage(s.usage);
    renderDetails(s);
    $("foot").textContent = "nightcrawler " + s.version + " · read-only · refreshes every " + REFRESH_MS / 1000 + " s";
    tick();
  }

  // ---------------------------------------------------------------- polling
  function banner(text) {
    const b = $("banner");
    b.hidden = !text;
    b.textContent = text || "";
    $("main").classList.toggle("stale", Boolean(text) && last !== null);
  }
  function tick() {
    $("updated").textContent = lastOkAt
      ? "updated " + Math.round((Date.now() - lastOkAt) / 1000) + "s ago" : "loading…";
  }
  async function refresh() {
    clearTimeout(timer);
    try {
      const url = "api/state" + (token ? "?token=" + encodeURIComponent(token) : "");
      const res = await fetch(url, {cache: "no-store", credentials: "same-origin"});
      if (res.status === 401) {
        banner("Locked: open the dashboard link that ends with ?token=…");
      } else if (!res.ok) {
        throw new Error("HTTP " + res.status);
      } else {
        const s = await res.json();
        serverOffset = s.generated_at - Date.now() / 1000;
        lastOkAt = Date.now();
        lastOkTs = s.generated_at;
        render(s);
        banner(null);
      }
    } catch (err) {
      banner("Can't reach the bot right now" + (lastOkTs ? " — showing data from " + ago(lastOkTs) : "")
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


#: Sent with every page: nothing loads from anywhere; only our exact inline script/style run.
CONTENT_SECURITY_POLICY = (
    f"default-src 'none'; script-src {_sha256_source(_SCRIPT)}; style-src {_sha256_source(_STYLE)}; "
    "connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def render_html(settings: Settings) -> str:
    """The complete single-page HTML (no secrets, no external URLs). Pure function."""
    live = settings.is_live
    badge_class = "badge live" if live else "badge"
    badge_word = "LIVE" if live else "PAPER"
    badge_text = "Real money · signed swaps through Jupiter" if live else "Simulated fills from live Jupiter quotes"
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        "<meta name=\"color-scheme\" content=\"light dark\">\n"
        "<meta name=\"theme-color\" content=\"#f9f9f7\" media=\"(prefers-color-scheme: light)\">\n"
        "<meta name=\"theme-color\" content=\"#0d0d0d\" media=\"(prefers-color-scheme: dark)\">\n"
        "<meta name=\"robots\" content=\"noindex, nofollow\">\n"
        "<meta name=\"referrer\" content=\"no-referrer\">\n"
        "<meta name=\"apple-mobile-web-app-capable\" content=\"yes\">\n"
        "<link rel=\"icon\" href=\"data:,\">\n"
        f"<title>nightcrawler · {badge_word.lower()}</title>\n"
        f"<style>{_STYLE}</style>\n</head>\n"
        f"<body data-refresh=\"{REFRESH_S}\">\n<main id=\"main\">\n"
        "<header><div class=\"brand\">nightcrawler<small>" f"v{__version__}</small></div>"
        "<div class=\"updated\" id=\"updated\">loading…</div></header>\n"
        f"<div class=\"{badge_class}\" id=\"badge\"><b>{badge_word}</b><span>{badge_text}</span></div>\n"
        "<div class=\"banner\" id=\"banner\" role=\"status\" hidden></div>\n"
        "<div class=\"chips\" id=\"chips\"></div>\n"
        "<section class=\"card\" id=\"equity\"><h2>Equity</h2><p class=\"empty\">Loading…</p></section>\n"
        "<section class=\"card\" id=\"positions\"></section>\n"
        "<section class=\"card\" id=\"fills\"></section>\n"
        "<section class=\"card\" id=\"filter\"></section>\n"
        "<section class=\"card\" id=\"receipts\"></section>\n"
        "<section class=\"card\" id=\"decisions\"></section>\n"
        "<section class=\"card\" id=\"usage\"></section>\n"
        "<section class=\"card\" id=\"details\"></section>\n"
        "<footer id=\"foot\">read-only dashboard</footer>\n</main>\n"
        f"<script>{_SCRIPT}</script>\n</body>\n</html>\n"
    )


_LOCKED_PAGE = (
    "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>nightcrawler · locked</title>"
    "</head><body><h1>Locked</h1><p>This dashboard needs its token. Open the link that ends with "
    "<code>?token=YOUR_DASHBOARD_TOKEN</code>.</p></body></html>"
).encode()


# =========================================================================== server


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class _Handler(BaseHTTPRequestHandler):
    """Routes for :class:`DashboardServer` (reached through ``self.server.dashboard``)."""

    server_version = "nightcrawler"
    sys_version = ""
    timeout = 15  # seconds a client may take to send its request (slow clients cannot pin threads)

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        if parts.path == "/healthz":
            self._send(200, b"ok", "text/plain; charset=utf-8")
            return
        if parts.path not in ("/", "/api/state"):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        dashboard: DashboardServer = self.server.dashboard  # type: ignore[attr-defined]
        query_token = parse_qs(parts.query).get("token", [None])[0]
        allowed, set_cookie = dashboard.authorize(query_token, self._cookie())
        if not allowed:
            self._send(401, _LOCKED_PAGE, "text/html; charset=utf-8")
            return
        headers = [("Set-Cookie", dashboard.cookie_header(self._is_https()))] if set_cookie else []
        if parts.path == "/":
            headers.append(("Content-Security-Policy", CONTENT_SECURITY_POLICY))
            self._send(200, dashboard.page, "text/html; charset=utf-8", headers)
            return
        try:
            body = dashboard.state_json()
        except Exception:
            log.exception("dashboard_state_failed")
            self._send(500, b'{"error":"state unavailable"}', "application/json", headers)
            return
        self._send(200, body, "application/json", headers)

    def _not_allowed(self) -> None:
        self._send(405, b"method not allowed (read-only dashboard)", "text/plain; charset=utf-8", [("Allow", "GET")])

    do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = do_CONNECT = _not_allowed

    def _cookie(self) -> str | None:
        try:
            morsel = SimpleCookie(self.headers.get("Cookie", "")).get(COOKIE_NAME)
        except CookieError:
            return None
        return morsel.value if morsel is not None else None

    def _is_https(self) -> bool:
        return self.headers.get("X-Forwarded-Proto", "").lower() == "https"

    def _send(self, status: int, body: bytes, content_type: str, headers: list[tuple[str, str]] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for name, value in headers or []:
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # Request lines carry ?token=...: log the method, the path WITHOUT its query, and the status only.
    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        log.debug("dashboard_request method=%s path=%s status=%s", self.command, urlsplit(self.path).path, code)

    def log_error(self, format: str, *args: Any) -> None:
        log.debug("dashboard_bad_request status=%s", args[0] if args else "?")

    def log_message(self, format: str, *args: Any) -> None:
        log.debug("dashboard_message")


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], dashboard: DashboardServer) -> None:
        self.dashboard = dashboard
        super().__init__(address, _Handler)


class DashboardServer:
    """Threaded read-only HTTP server.

    ``state_provider()`` returns the ``/api/state`` dict (normally
    ``lambda: build_state(ledger, settings, clock.now(), cache)``).
    Whatever it returns is scrubbed of secrets again before it is served.
    """

    def __init__(self, settings: Settings, state_provider: Callable[[], dict[str, Any]],
                 host: str | None = None, port: int | None = None) -> None:
        self.settings = settings
        self.state_provider = state_provider
        self.host = host if host is not None else settings.dashboard_host
        self.port = port if port is not None else settings.port
        self._thread: threading.Thread | None = None
        self._server: Any = None
        self.page = render_html(settings).encode("utf-8")
        self._secrets = settings.secret_values()
        token = settings.dashboard_token.reveal() if settings.dashboard_token else None
        self._token = token
        self._cookie_value = (hmac.new(token.encode("utf-8"), _COOKIE_CONTEXT, hashlib.sha256).hexdigest()
                              if token else None)

    # ------------------------------------------------------------------ auth + content
    def authorize(self, query_token: str | None, cookie: str | None) -> tuple[bool, bool]:
        """``(allowed, set_cookie)`` for a request carrying ``?token=`` and/or the cookie."""
        if self._token is None:
            return True, False
        if query_token is not None and _same(query_token, self._token):
            return True, True
        if cookie is not None and (_same(cookie, self._cookie_value or "") or _same(cookie, self._token)):
            return True, False
        return False, False

    def cookie_header(self, https: bool) -> str:
        """``Set-Cookie`` value: an HMAC of the token (never the token itself)."""
        secure = "; Secure" if https else ""
        return (f"{COOKIE_NAME}={self._cookie_value}; Path=/; Max-Age={COOKIE_MAX_AGE_S}; HttpOnly; "
                f"SameSite=Strict{secure}")

    def state_json(self) -> bytes:
        """The provider's state, scrubbed, as strict JSON bytes."""
        state = scrub(self.state_provider(), self._secrets)
        return json.dumps(state, allow_nan=False, separators=(",", ":"), default=str).encode("utf-8")

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> threading.Thread:
        """Bind and serve in a daemon thread; returns the thread. ``port=0`` picks a free port
        (read the bound port from :attr:`bound_port`)."""
        if self._thread is not None:
            return self._thread
        self._server = _Server((self.host, self.port), self)
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.5},
                                        name="nightcrawler-dashboard", daemon=True)
        self._thread.start()
        log.info("dashboard_listening host=%s port=%d auth=%s", self.host, self.bound_port,
                 "token" if self._token else "none")
        return self._thread

    @property
    def bound_port(self) -> int:
        if self._server is None:
            raise RuntimeError("dashboard server is not running")
        return int(self._server.server_address[1])

    def stop(self) -> None:
        """Shut down the server and join the thread (idempotent)."""
        server, thread = self._server, self._thread
        self._server, self._thread = None, None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
