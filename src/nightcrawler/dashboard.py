"""Read-only phone dashboard (owner: O6). stdlib only; no external assets.

``DashboardServer`` runs ``http.server.ThreadingHTTPServer`` on
``DASHBOARD_HOST:PORT`` (default ``0.0.0.0:8080``; Railway sets ``PORT``) in a
daemon thread. Routes (GET only; anything else -> 405; unknown path -> 404):

* ``/healthz`` -> 200 ``text/plain`` ``ok`` (no auth; Railway health check).
* ``/api/state`` -> 200 JSON from :func:`build_state` (``Cache-Control: no-store``).
* ``/office`` -> the animated office (:mod:`nightcrawler.office`), same data and auth as ``/``;
  ``/office/art/<name>.jpg`` -> its bundled concept-art sets (whitelist, private cache).
* ``/`` -> the ONE mobile-first page (:mod:`nightcrawler.page`, via :func:`render_html`): money,
  the team at work, trades, learning, "ready for real money?", receipts and usage, in plain words.
  It refreshes every 15 s from ``/api/page`` while the tab is visible.
* ``/api/page`` -> that page's data (:mod:`nightcrawler.pagestate`); ``/api/team`` -> the team room
  JSON (:mod:`nightcrawler.teamroom`). Both are served by :class:`~nightcrawler.teamroom.TeamRoom`
  with the same auth and scrubbing.
* ``/team`` -> 302 to ``/`` (old team-room links keep working).

Auth: if ``DASHBOARD_TOKEN`` is set, every route but ``/healthz`` requires
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
from nightcrawler.office import OFFICE_CSP, art_bytes, render_office_html
from nightcrawler.page import PAGE_CSP, REFRESH_S, render_page_html

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


def build_state(
    ledger: Any,
    settings: Settings,
    now: float,
    verify_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        "fills": [
            {**f.to_dict(), "sol": f.sol_lamports / LAMPORTS_PER_SOL}
            for f in ledger.fills(limit=RECENT_LIMIT)
        ],
        "decisions": [d.to_dict() for d in ledger.decisions(limit=RECENT_LIMIT)],
        "rejections": ledger.decision_counts(since=now - DAY_S),
        "cocoon_rules": _cocoon_rules(
            ledger.safety_failures(since=now - DAY_S).values()
        ),
        "activity": {"candidates_24h": ledger.candidate_count(since=now - DAY_S)},
        "receipts": _receipts(
            ledger, now, verify_cache if verify_cache is not None else {}
        ),
        "judge": _judge(ledger, settings, now),
        "wallet": {
            "address": _str_or_none(ledger.get_kv("wallet.pubkey"))
            if settings.is_live
            else None
        },
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
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


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
    return {
        "heartbeat": _num_or_none(ledger.get_kv("engine.heartbeat")),
        "started_at": _num_or_none(ledger.get_kv("engine.started_at")),
        "status": status if isinstance(status, dict) else None,
        "last_error": _str_or_none(error),
    }


def _equity(ledger: Any, mode: str, now: float) -> dict[str, Any]:
    """Equity, P&L today (vs the first snapshot of the UTC day) and since the start of this wallet."""
    today = [p for p in ledger.equity_series(since=now - now % DAY_S) if p.mode == mode]
    latest = ledger.latest_equity()
    if latest is not None and latest.mode != mode:
        latest = today[-1] if today else None
    start_lamports = _num_or_none(ledger.get_kv(f"{mode}.start_lamports"))
    start_sol_usd = _num_or_none(ledger.get_kv(f"{mode}.start_sol_usd"))
    start_usd = (
        start_lamports / LAMPORTS_PER_SOL * start_sol_usd
        if start_lamports and start_sol_usd
        else None
    )
    out: dict[str, Any] = {
        "sol": None,
        "usd": None,
        "sol_usd": None,
        "start_usd": start_usd,
        "pnl_today_usd": None,
        "pnl_today_sol": None,
        "pnl_total_usd": None,
        "pnl_total_sol": None,
        "pnl_total_trading_usd": None,
        "sol_price_effect_usd": None,
        "curve": [
            [ts, usd]
            for ts, usd in ledger.equity_curve(
                since=now - CURVE_DAYS * DAY_S, max_points=CURVE_MAX_POINTS, mode=mode
            )
        ],
    }
    if latest is None:
        return out
    out.update(
        sol=latest.equity_lamports / LAMPORTS_PER_SOL,
        usd=latest.equity_usd,
        sol_usd=latest.sol_usd,
    )
    if today:
        out["pnl_today_usd"] = latest.equity_usd - today[0].equity_usd
        out["pnl_today_sol"] = (
            latest.equity_lamports - today[0].equity_lamports
        ) / LAMPORTS_PER_SOL
    if start_lamports is not None:
        out["pnl_total_sol"] = (
            latest.equity_lamports - start_lamports
        ) / LAMPORTS_PER_SOL
    if start_lamports is not None:
        out["pnl_total_trading_usd"] = out["pnl_total_sol"] * latest.sol_usd
    if start_usd is not None:
        out["pnl_total_usd"] = latest.equity_usd - start_usd
        if out["pnl_total_trading_usd"] is not None:
            out["sol_price_effect_usd"] = (
                out["pnl_total_usd"] - out["pnl_total_trading_usd"]
            )
    return out


def _safe_mode(ledger: Any) -> dict[str, Any] | None:
    """kv ``engine.safe_mode``: the exits-only banner of a bot running on an invalid configuration (RT-9)."""
    banner = ledger.get_kv("engine.safe_mode")
    if not isinstance(banner, dict):
        return None
    return {
        "problems": [str(x) for x in banner.get("problems") or []],
        "defaults_used": [str(x) for x in banner.get("defaults_used") or []],
        "since": _num_or_none(banner.get("since")),
    }


def _positions(
    ledger: Any, settings: Settings, mode: str, sol_usd: float | None
) -> list[dict[str, Any]]:
    """Open positions of ``mode``; live ones recorded for ANOTHER wallet than kv ``wallet.pubkey`` (F3:
    the engine never sells or counts them) carry that wallet in ``foreign_wallet``."""
    positions = ledger.open_positions(mode=mode)
    own = ledger.get_kv("wallet.pubkey") if settings.is_live else None
    lookup = getattr(ledger, "position_wallets", None)
    foreign: dict[str, Any] = {}
    if isinstance(own, str) and own and lookup is not None and positions:
        foreign = {
            pid: w
            for pid, w in lookup([p.id for p in positions]).items()
            if w and w != own
        }
    return [_position(p, sol_usd, foreign.get(p.id)) for p in positions]


def _position(
    p: Position, sol_usd: float | None, foreign_wallet: str | None = None
) -> dict[str, Any]:
    """Marked with the engine's last price and the latest equity SOL price (None when unknown)."""
    value = pnl = None
    if p.last_price_usd is not None and sol_usd:
        value = p.value_lamports(p.last_price_usd, sol_usd)
        pnl = p.pnl_lamports(p.last_price_usd, sol_usd)
    return {
        "id": p.id,
        "mint": p.mint,
        "symbol": p.symbol,
        "opened_at": p.opened_at,
        "entry_price_usd": p.entry_price_usd,
        "last_price_usd": p.last_price_usd,
        "value_sol": None if value is None else value / LAMPORTS_PER_SOL,
        "cost_sol": p.cost_lamports / LAMPORTS_PER_SOL,
        "unrealized_pnl_sol": None if pnl is None else pnl / LAMPORTS_PER_SOL,
        "unrealized_pnl_pct": pnl / p.cost_lamports * 100.0
        if pnl is not None and p.cost_lamports
        else None,
        "partial_taken": p.partial_taken,
        "foreign_wallet": _str_or_none(foreign_wallet),
    }


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
    return {
        "head_hash": head,
        "seq": seq,
        "count": ledger.receipt_count(),
        "verified": cache["verified"],
        "first_bad_seq": cache["first_bad_seq"],
        "verified_at": cache["verified_at"],
    }


def _judge(ledger: Any, settings: Settings, now: float) -> dict[str, Any]:
    day = ledger.get_kv("judge.cost_usd_day")
    today = (
        _num_or_none(day.get("usd"))
        if isinstance(day, dict) and day.get("day") == utc_day(now)
        else None
    )
    return {
        "mode": settings.judge_mode,
        "model": settings.judge_model,
        "calls": int(_num_or_none(ledger.get_kv("judge.calls")) or 0),
        "cost_usd_total": _num_or_none(ledger.get_kv("judge.cost_usd_total")) or 0.0,
        "cost_usd_today": today or 0.0,
    }


def _usage(ledger: Any, settings: Settings, now: float) -> dict[str, Any]:
    """Provider calls this UTC day/month (kv ``usage.providers``, written by ``http.UsageTracker``)
    against each free-tier budget. Only provider names are shown - never a URL, host or key."""
    stored = ledger.get_kv(KV_USAGE)
    stored = (
        {k: v for k, v in stored.items() if isinstance(v, dict)}
        if isinstance(stored, dict)
        else {}
    )
    day = utc_day(now)
    rpc_host = host_of(settings.solana_rpc_url)
    ids = [provider_of(rpc_host, rpc_host), *_USAGE_CORE]
    ids += [p for p in PROVIDERS if p in stored and p not in ids]
    stamps = [
        v["updated_at"]
        for v in stored.values()
        if _num_or_none(v.get("updated_at")) is not None
    ]
    return {
        "day": day,
        "month": day[:7],
        "warn_pct": USAGE_WARN_PCT,
        "updated_at": max(stamps, default=None),
        "providers": [
            _usage_row(p, stored.get(p, {}), day, ledger, settings) for p in ids
        ],
    }


def _period_counts(entry: dict[str, Any], period: str, key: str) -> dict[str, float]:
    """``entry``'s day/month counters when they belong to ``key`` (today / this month), else ``{}``."""
    counts = entry.get(f"{period}_counts")
    if entry.get(period) != key or not isinstance(counts, dict):
        return {}
    return {
        name: value for name, value in counts.items() if _num_or_none(value) is not None
    }


def _usage_row(
    provider: str, entry: dict[str, Any], day: str, ledger: Any, settings: Settings
) -> dict[str, Any]:
    today, month = (
        _period_counts(entry, "day", day),
        _period_counts(entry, "month", day[:7]),
    )
    row: dict[str, Any] = {
        "id": provider,
        "label": PROVIDERS[provider],
        "unit": "calls",
        "period": "month",
        "calls_today": today.get("calls", 0),
        "calls_month": month.get("calls", 0),
        "used": month.get("calls", 0),
        "budget": None,
        "used_pct": None,
        "level": None,
        "tokens_today": None,
        "tokens_month": None,
        "cost_usd_today": None,
        "cost_usd_month": None,
    }
    if (
        provider == "anthropic"
    ):  # budget: JUDGE_MAX_DAILY_USD, measured like the judge enforces it
        judged = ledger.get_kv("judge.cost_usd_day")
        spent = (
            _num_or_none(judged.get("usd"))
            if isinstance(judged, dict) and judged.get("day") == day
            else None
        )
        spent = spent if spent is not None else today.get("cost_usd", 0.0)
        row.update(
            unit="usd",
            period="day",
            used=spent,
            budget=float(settings.judge_max_daily_usd),
            tokens_today=today.get("input_tokens", 0) + today.get("output_tokens", 0),
            tokens_month=month.get("input_tokens", 0) + month.get("output_tokens", 0),
            cost_usd_today=spent,
            cost_usd_month=month.get("cost_usd", 0.0),
        )
    elif provider in _MONTHLY_BUDGETS:
        field_name, unit = _MONTHLY_BUDGETS[provider]
        budget = getattr(settings, field_name)
        row.update(
            unit=unit, used=month.get(unit, 0), budget=budget if budget > 0 else None
        )
    if row["budget"]:
        row["used_pct"] = row["used"] / row["budget"] * 100.0
        row["level"] = (
            "over"
            if row["used_pct"] >= 100.0
            else "warn"
            if row["used_pct"] >= USAGE_WARN_PCT
            else "ok"
        )
    return row


# =========================================================================== page

#: Sent with ``/``: only the page's exact inline script and style run (:data:`nightcrawler.page.PAGE_CSP`).
CONTENT_SECURITY_POLICY = PAGE_CSP


def render_html(settings: Settings) -> str:
    """The one page at ``/`` (:func:`nightcrawler.page.render_page_html`; no secrets, no external URLs). Pure."""
    return render_page_html(settings)


_LOCKED_PAGE = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1"><title>nightcrawler · locked</title>'
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
        is_art = parts.path.startswith("/office/art/")
        if not is_art and parts.path not in (
            "/",
            "/office",
            "/api/state",
            "/api/page",
            "/team",
            "/api/team",
        ):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        dashboard: DashboardServer = self.server.dashboard  # type: ignore[attr-defined]
        query_token = parse_qs(parts.query).get("token", [None])[0]
        allowed, set_cookie = dashboard.authorize(query_token, self._cookie())
        if not allowed:
            self._send(401, _LOCKED_PAGE, "text/html; charset=utf-8")
            return
        headers = (
            [("Set-Cookie", dashboard.cookie_header(self._is_https()))]
            if set_cookie
            else []
        )
        if (
            parts.path == "/team"
        ):  # the old team room page: now part of the one page (the cookie carries auth)
            self._send(
                302, b"", "text/plain; charset=utf-8", [*headers, ("Location", "/")]
            )
            return
        if parts.path in (
            "/api/team",
            "/api/page",
        ):  # live data: nightcrawler.teamroom.TeamRoom
            self._send(*dashboard.team.response(parts.path, headers))
            return
        if parts.path == "/":
            headers.append(("Content-Security-Policy", CONTENT_SECURITY_POLICY))
            self._send(200, dashboard.page, "text/html; charset=utf-8", headers)
            return
        if (
            parts.path == "/office"
        ):  # the animated office (nightcrawler.office): same data, same auth
            headers.append(("Content-Security-Policy", OFFICE_CSP))
            self._send(200, dashboard.office, "text/html; charset=utf-8", headers)
            return
        if is_art:  # the office's bundled sets: a fixed whitelist of JPEGs, never a directory listing
            art = art_bytes(parts.path[len("/office/art/") :])
            if art is None:
                self._send(404, b"not found", "text/plain; charset=utf-8", headers)
                return
            self._send(
                200,
                art,
                "image/jpeg",
                [*headers, ("Cache-Control", "private, max-age=86400")],
            )
            return
        try:
            body = dashboard.state_json()
        except Exception:
            log.exception("dashboard_state_failed")
            self._send(
                500, b'{"error":"state unavailable"}', "application/json", headers
            )
            return
        self._send(200, body, "application/json", headers)

    def _not_allowed(self) -> None:
        self._send(
            405,
            b"method not allowed (read-only dashboard)",
            "text/plain; charset=utf-8",
            [("Allow", "GET")],
        )

    do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = (
        do_CONNECT
    ) = _not_allowed

    def _cookie(self) -> str | None:
        try:
            morsel = SimpleCookie(self.headers.get("Cookie", "")).get(COOKIE_NAME)
        except CookieError:
            return None
        return morsel.value if morsel is not None else None

    def _is_https(self) -> bool:
        return self.headers.get("X-Forwarded-Proto", "").lower() == "https"

    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str,
        headers: list[tuple[str, str]] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        extra = headers or []
        if not any(
            name == "Cache-Control" for name, _ in extra
        ):  # the office's sets override the default
            self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # Request lines carry ?token=...: log the method, the path WITHOUT its query, and the status only.
    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        log.debug(
            "dashboard_request method=%s path=%s status=%s",
            self.command,
            urlsplit(self.path).path,
            code,
        )

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

    def __init__(
        self,
        settings: Settings,
        state_provider: Callable[[], dict[str, Any]],
        host: str | None = None,
        port: int | None = None,
        team: Any = None,
    ) -> None:
        from nightcrawler.teamroom import (
            TeamRoom,  # late: teamroom builds on this module
        )

        self.team = (
            team if team is not None else TeamRoom(settings)
        )  # /team + /api/team
        self.settings = settings
        self.state_provider = state_provider
        self.host = host if host is not None else settings.dashboard_host
        self.port = port if port is not None else settings.port
        self._thread: threading.Thread | None = None
        self._server: Any = None
        self.page = render_html(settings).encode("utf-8")
        self.office = render_office_html(settings).encode("utf-8")
        self._secrets = settings.secret_values()
        token = settings.dashboard_token.reveal() if settings.dashboard_token else None
        self._token = token
        self._cookie_value = (
            hmac.new(token.encode("utf-8"), _COOKIE_CONTEXT, hashlib.sha256).hexdigest()
            if token
            else None
        )

    # ------------------------------------------------------------------ auth + content
    def authorize(
        self, query_token: str | None, cookie: str | None
    ) -> tuple[bool, bool]:
        """``(allowed, set_cookie)`` for a request carrying ``?token=`` and/or the cookie."""
        if self._token is None:
            return True, False
        if query_token is not None and _same(query_token, self._token):
            return True, True
        if cookie is not None and (
            _same(cookie, self._cookie_value or "") or _same(cookie, self._token)
        ):
            return True, False
        return False, False

    def cookie_header(self, https: bool) -> str:
        """``Set-Cookie`` value: an HMAC of the token (never the token itself)."""
        secure = "; Secure" if https else ""
        return f"{COOKIE_NAME}={self._cookie_value}; Path=/; Max-Age={COOKIE_MAX_AGE_S}; HttpOnly; SameSite=Strict{secure}"

    def state_json(self) -> bytes:
        """The provider's state, scrubbed, as strict JSON bytes."""
        state = scrub(self.state_provider(), self._secrets)
        return json.dumps(
            state, allow_nan=False, separators=(",", ":"), default=str
        ).encode("utf-8")

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> threading.Thread:
        """Bind and serve in a daemon thread; returns the thread. ``port=0`` picks a free port
        (read the bound port from :attr:`bound_port`)."""
        if self._thread is not None:
            return self._thread
        self.team.open()  # stop() closed it
        self._server = _Server((self.host, self.port), self)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.5},
            name="nightcrawler-dashboard",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "dashboard_listening host=%s port=%d auth=%s",
            self.host,
            self.bound_port,
            "token" if self._token else "none",
        )
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
        self.team.close()
