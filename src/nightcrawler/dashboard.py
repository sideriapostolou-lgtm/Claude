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
READ-ONLY: no endpoint changes state. NEVER include secrets in any response.

``/api/state`` schema (all keys always present; unknown -> null)::

    {
      "version": str, "generated_at": float, "mode": "PAPER"|"LIVE",
      "kill": "off"|"stop"|"sell_all", "halted": {"halted": bool, "reason": str|null},
      "engine": {"heartbeat": float|null, "started_at": float|null, "status": dict|null,
                 "last_error": str|null},
      "equity": {"sol": float|null, "usd": float|null, "sol_usd": float|null,
                 "start_usd": float|null, "pnl_today_usd": float|null, "pnl_today_sol": float|null,
                 "pnl_total_usd": float|null, "pnl_total_sol": float|null,
                 "curve": [[ts, equity_usd], ...]   # <= 300 points, downsampled},
      "positions": [{"id", "mint", "symbol", "opened_at", "entry_price_usd", "last_price_usd",
                     "value_sol", "unrealized_pnl_sol", "unrealized_pnl_pct", "partial_taken"}],
      "fills": [Fill.to_dict() + {"sol": float}],          # last 50, newest first
      "decisions": [Decision.to_dict()],                   # last 50, newest first
      "rejections": {action: count},                       # last 24 h, from decision_counts
      "receipts": {"head_hash": str, "count": int, "verified": bool|null,
                   "first_bad_seq": int|null, "verified_at": float|null},
      "judge": {"mode": str, "model": str, "calls": int, "cost_usd_total": float,
                "cost_usd_today": float},
      "wallet": {"address": str|null}                      # live only, else null
    }

Chain verification is expensive on long chains: ``build_state`` re-verifies
at most every 5 minutes (cached in the server instance).
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from nightcrawler.config import Settings

__all__ = ["DashboardServer", "build_state", "render_html", "VERIFY_EVERY_S", "REFRESH_S"]

VERIFY_EVERY_S = 300
REFRESH_S = 15


def build_state(ledger: Any, settings: Settings, now: float, verify_cache: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assemble the ``/api/state`` JSON (schema in the module docstring) from the ledger ONLY.

    No network calls: prices come from what the engine last stored
    (``Position.last_price_usd``, ``EquityPoint.sol_usd``). ``verify_cache``
    is a mutable dict the server keeps between calls to throttle chain verification.
    """
    raise NotImplementedError


def render_html(settings: Settings) -> str:
    """The complete single-page HTML (no secrets, no external URLs). Pure function."""
    raise NotImplementedError


class DashboardServer:
    """Threaded read-only HTTP server.

    ``state_provider()`` returns the ``/api/state`` dict (normally
    ``lambda: build_state(ledger, settings, clock.now(), cache)``).
    """

    def __init__(self, settings: Settings, state_provider: Callable[[], dict[str, Any]],
                 host: str | None = None, port: int | None = None) -> None:
        self.settings = settings
        self.state_provider = state_provider
        self.host = host if host is not None else settings.dashboard_host
        self.port = port if port is not None else settings.port
        self._thread: threading.Thread | None = None
        self._server: Any = None

    def start(self) -> threading.Thread:
        """Bind and serve in a daemon thread; returns the thread. ``port=0`` picks a free port
        (read the bound port from :attr:`bound_port`)."""
        raise NotImplementedError

    @property
    def bound_port(self) -> int:
        raise NotImplementedError

    def stop(self) -> None:
        """Shut down the server and join the thread (idempotent)."""
        raise NotImplementedError
