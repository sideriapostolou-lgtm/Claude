"""Settings: one frozen dataclass loaded from environment variables.

* Env name = upper-snake of the attribute (``position_pct`` <- ``POSITION_PCT``).
* Empty env values count as unset (Railway sometimes sets blank variables).
* Secrets (``BOT_WALLET_SECRET``, ``ANTHROPIC_API_KEY``, ``JUPITER_API_KEY``,
  ``X_BEARER_TOKEN``, ``DASHBOARD_TOKEN``) are wrapped in :class:`Secret`, whose
  ``repr``/``str`` is ``***``; call ``.reveal()`` only at the point of use.
  :meth:`Settings.public_dict` never contains secret values (only ``*_set``
  booleans) and shows only the scheme and host of ``SOLANA_RPC_URL`` (providers
  put API keys in its query OR its path).
* Construction validates everything (``__post_init__``) and raises
  :class:`ConfigError` listing every problem at once.

Units: see the per-field ``unit`` metadata and ``models.py``. Note the
documented exception: ``POSITION_PCT, DAILY_LOSS_LIMIT_PCT,
MAX_DRAWDOWN_HALT_PCT, DIP_PCT, TAKE_PROFIT_PCT, TRAIL_PCT, STOP_LOSS_PCT`` are
FRACTIONS (0.20 = 20 %); ``MAX_PRICE_IMPACT_PCT``, ``COCOON_*_PCT`` and
``RADAR_*_PCT`` are PERCENT (3.0 = 3 %).
The gap-risk budgets ``DAILY_RISK_BUDGET_PCT`` and ``MAX_AT_RISK_PCT`` are FRACTIONS too.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import math
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit

__all__ = [
    "DASHBOARD_TOKEN_MIN_LEN",
    "LIVE_CONFIRM_PHRASE",
    "ConfigError",
    "Secret",
    "Settings",
    "dashboard_token_problem",
    "load_settings",
    "mask_problem",
    "parse_dotenv",
    "parse_rotation_date",
    "redact_rpc_url",
    "redact_url",
]

LIVE_CONFIRM_PHRASE = "I_ACCEPT_REAL_MONEY_RISK"
_KILL_WORDS = ("off", "stop", "sell_all")
#: Bind addresses that only this machine can reach (no DASHBOARD_TOKEN needed in live mode).
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
#: A path segment or query value this long (letters, digits, ``-``/``_``) is treated as an API key.
_KEY_SHAPED = re.compile(r"^[A-Za-z0-9_-]{16,}$")
_TRUE = {"1", "true", "yes", "on", "y"}
_FALSE = {"0", "false", "no", "off", "n"}
_SECRET_QUERY_HINTS = ("key", "token", "secret", "auth", "password")
#: A raw value quoted in a ConfigError problem (``got '...'``, ``JUDGE_MODE='...'``): a str ``repr``.
_QUOTED_VALUE = re.compile(r"'(?:[^'\\]|\\.)*'" r'|"(?:[^"\\]|\\.)*"')
#: A live dashboard token must be at least this long (and not repetitive, and not the docs' example).
DASHBOARD_TOKEN_MIN_LEN = 24
_TOKEN_MIN_DISTINCT = 8
#: docs/RAILWAY.md's example DASHBOARD_TOKEN starts with this: public, so never a real password.
_TOKEN_EXAMPLE = "change-me"
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Secret:
    """A string that never prints itself. ``bool(secret)`` is True when non-empty."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = str(value)

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret('***')"

    def __str__(self) -> str:
        return "***"

    def __bool__(self) -> bool:
        return bool(self._value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash(("Secret", self._value))

    def __copy__(self) -> Secret:
        return self

    def __deepcopy__(self, memo: dict) -> Secret:
        return self

    def __reduce__(self):  # refuse to pickle secrets by accident
        raise TypeError("Secret values cannot be pickled")


class ConfigError(ValueError):
    """Invalid configuration. ``problems`` lists every issue found."""

    def __init__(self, problems: Iterable[str]) -> None:
        self.problems = list(problems)
        super().__init__("Invalid configuration:\n  - " + "\n  - ".join(self.problems))


def mask_problem(problem: str) -> str:
    """A :class:`ConfigError` problem with every quoted raw value replaced by ``'***'``: a value pasted
    into the wrong variable may be a secret (an API key in a number variable), and safe mode keeps the
    problems (receipts, kv, dashboard). The variable names stay, so the fix is still obvious."""
    return _QUOTED_VALUE.sub("'***'", problem)


def redact_url(url: str) -> str:
    """Replace values of key-like query params (``api-key``, ``token`` ...) with ``***``."""
    if not url or "?" not in url:
        return url
    parts = urlsplit(url)
    pairs = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        if any(h in k.lower() for h in _SECRET_QUERY_HINTS):
            v = "***"
        pairs.append(f"{k}={v}")
    return parts._replace(query="&".join(pairs)).geturl()


def redact_rpc_url(url: str) -> str:
    """An RPC URL with everything but scheme and host hidden: providers such as QuickNode
    (``https://x.quiknode.pro/<KEY>/``) and Alchemy (``/v2/<KEY>``) put the API key in the PATH."""
    if not url:
        return url
    parts = urlsplit(url)
    path = "/***" if parts.path not in ("", "/") else parts.path
    query = "&".join(f"{k}=***" for k, _ in parse_qsl(parts.query, keep_blank_values=True))
    return parts._replace(path=path, query=query, fragment="").geturl()


def _url_secret_values(url: str) -> list[str]:
    """Key-like values in ``url``: key-named query values, plus any key-shaped path segment or
    query value (16+ letters/digits), so the log filter and the dashboard scrub catch path keys."""
    if not url:
        return []
    parts = urlsplit(url)
    out = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        if v and (any(h in k.lower() for h in _SECRET_QUERY_HINTS) or _KEY_SHAPED.match(v)):
            out.append(v)
    out.extend(seg for seg in parts.path.split("/") if _KEY_SHAPED.match(seg))
    return out


def dashboard_token_problem(token: str) -> str | None:
    """Why ``token`` is too weak to lock the dashboard, in plain words (``"too short"``, ``"too easy to guess"``,
    ``"the example from the guide"``), or None when it is strong enough. Never includes the token."""
    if len(token) < DASHBOARD_TOKEN_MIN_LEN:
        return "too short"
    if _TOKEN_EXAMPLE in token.lower():
        return "the example from the guide"
    if len(set(token)) < _TOKEN_MIN_DISTINCT:
        return "too easy to guess"
    return None


def parse_rotation_date(value: str) -> datetime.date | None:
    """``KEYS_ROTATED_ON`` as a date (exactly ``YYYY-MM-DD``), or None when it is anything else."""
    text = value.strip()
    if not _ISO_DATE.match(text):
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def _normalize_kill_switch(value: Any) -> str:
    """``KILL_SWITCH`` read like the ``DATA_DIR/KILL`` file: case, ``-`` and spaces forgiven
    (``sell-all`` -> ``sell_all``). An unrecognized word means ``stop`` (fail SAFE: no new
    entries, exits keep running) - never a startup refusal, which would leave open positions
    with no stop-loss at the very moment the owner reached for the emergency switch."""
    word = "_".join(str(value).strip().lower().replace("-", " ").split())
    if word in _KILL_WORDS:
        return word
    logging.getLogger(__name__).warning("config_kill_switch_unrecognized value=%r using=stop", str(value)[:40])
    return "stop"


def _f(default: Any, unit: str, help: str, *, lo: float | None = None, hi: float | None = None,
       choices: tuple[str, ...] | None = None, secret: bool = False, lo_open: bool = False) -> Any:
    """Dataclass field with documentation/validation metadata."""
    meta = {"unit": unit, "help": help, "lo": lo, "hi": hi, "choices": choices, "secret": secret,
            "lo_open": lo_open}
    return field(default=default, metadata=meta)


@dataclass(frozen=True, slots=True, repr=False)
class Settings:
    """All runtime settings. Build with :meth:`from_env` / :func:`load_settings`.

    ``repr()`` shows :meth:`public_dict` (no secrets, RPC api keys redacted).
    """

    # ---- mode & safety ------------------------------------------------------
    trading_mode: str = _f("paper", "text", "paper (default, simulated fills from live quotes) or live (real money)",
                           choices=("paper", "live"))
    live_confirm: str = _f("", "text", f"Must equal {LIVE_CONFIRM_PHRASE} for TRADING_MODE=live")
    data_dir: Path = _f(Path("./data"), "path", "Where the SQLite ledger, KILL file and datasets live (Railway: /data)")  # noqa: RUF009 - _f returns a dataclasses.field with validation metadata
    log_level: str = _f("INFO", "text", "Logging level", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    kill_switch: str = _f("off", "text", "off | stop (no new entries) | sell_all (exit everything, then stop). "
                          "Case, '-' and spaces are forgiven (sell-all); any other word means stop. "
                          "A DATA_DIR/KILL file containing the same words also works.",
                          choices=("off", "stop", "sell_all"))
    simulate_before_send: bool = _f(True, "bool", "Live: simulate the signed transaction via RPC before sending")
    quote_max_age_s: float = _f(15.0, "seconds", "Reject executing a quote older than this", lo=1, hi=120)
    reset_halt_token: str = _f("", "text", "Clears a drawdown halt once: set it to any NEW value (e.g. today's "
                               "date) and redeploy. Same as `nightcrawler reset-halt`, but works from the "
                               "Railway variables page on a phone")
    keys_rotated_on: str = _f("", "text", "The date (YYYY-MM-DD, e.g. 2026-10-09) you replaced every key that was "
                              "ever pasted into a chat. Only shown on the dashboard's 'ready for real money?' "
                              "checklist; leave empty until the keys really are replaced. Never put a key here")

    # ---- bankroll & risk ----------------------------------------------------
    paper_start_usd: float = _f(100.0, "usd", "Paper bankroll at first start (converted to SOL at the live price)",
                                lo=1, lo_open=False)
    position_pct: float = _f(0.20, "fraction", "Position size as a FRACTION of equity (0.20 = 20%)",
                             lo=0, hi=1, lo_open=True)
    max_position_usd: float = _f(25.0, "usd", "Largest single position", lo=0, lo_open=True)
    min_position_usd: float = _f(5.0, "usd", "Smallest position worth fees; below this, skip", lo=0, lo_open=True)
    max_open_positions: int = _f(3, "count", "Max simultaneous open positions", lo=1, hi=50)
    daily_loss_limit_pct: float = _f(0.20, "fraction", "Stop opening positions for the UTC day after this "
                                     "FRACTION loss vs start-of-day equity", lo=0, hi=1, lo_open=True)
    max_drawdown_halt_pct: float = _f(0.50, "fraction", "Halt entries (until manual reset) after this FRACTION "
                                      "drawdown from the equity peak", lo=0, hi=1, lo_open=True)
    max_wallet_usd: float = _f(150.0, "usd", "Live: refuse NEW entries while the wallet is worth more than this "
                               "(protects against funding the wrong wallet)", lo=0, lo_open=True)
    sol_reserve: float = _f(0.02, "sol", "SOL never spent (fees, rent)", lo=0, hi=10)
    max_price_impact_pct: float = _f(3.0, "percent", "Reject quotes with more PERCENT price impact (3.0 = 3%)",
                                     lo=0, hi=100, lo_open=True)
    max_slippage_pct: float = _f(3.0, "percent", "Buys: reject quotes whose signed minimum output (Ultra's slippage "
                                 "tolerance) is more than this PERCENT below the quoted output. Forced exits are "
                                 "never blocked by it", lo=0, hi=100, lo_open=True)
    network_fee_sol: float = _f(0.0003, "sol", "Paper model of network fee per swap (base + priority)", lo=0, hi=0.01)
    paper_slippage_bps: int = _f(100, "bps", "Paper model of execution slippage: every paper fill receives this many "
                                 "basis points LESS than the quote's out_amount (live fills land below the quote "
                                 "by Ultra's slippage, latency and MEV; 0 = fill exactly at the quote)", lo=0, hi=1000)

    # ---- gap-risk budgets (risk.py: every open ticket counts 0.95 of itself, a rug's real loss) ----------
    daily_risk_budget_pct: float = _f(0.15, "fraction", "Worst-case daily budget as a FRACTION of start-of-day "
                                      "equity: today's loss plus 0.95 of every open ticket plus 0.95 of the new "
                                      "one must stay within it, or the new ticket is made smaller (below "
                                      "MIN_POSITION_USD: no buy). A stop-loss does not bound a rug", lo=0, hi=1,
                                      lo_open=True)
    max_at_risk_pct: float = _f(0.25, "fraction", "Most of the equity (a FRACTION) that may be at rug risk in all "
                                "open positions together, 0.95 of each ticket, the new one included (alongside "
                                "MAX_OPEN_POSITIONS)", lo=0, hi=1, lo_open=True)

    # ---- strategy -----------------------------------------------------------
    min_age_min: float = _f(60.0, "minutes", "Ignore tokens younger than this", lo=0)
    max_age_h: float = _f(48.0, "hours", "Ignore tokens older than this", lo=0, lo_open=True)
    min_mcap_usd: float = _f(100_000.0, "usd", "Market-cap window lower bound", lo=0)
    max_mcap_usd: float = _f(5_000_000.0, "usd", "Market-cap window upper bound", lo=0, lo_open=True)
    min_liquidity_usd: float = _f(30_000.0, "usd", "Liquidity floor (where known)", lo=0)
    min_organic_score: float = _f(0.0, "score", "Jupiter organicScore floor 0-100 (0 disables)", lo=0, hi=100)
    dip_pct: float = _f(0.55, "fraction", "Required drawdown from the rolling high (0.55 = 55%)",
                        lo=0, hi=1, lo_open=True)
    dip_lookback_h: float = _f(6.0, "hours", "Rolling-high window for the dip", lo=0, lo_open=True)
    confirm_green: int = _f(2, "count", "Consecutive closed green 1m candles to confirm buyers returned", lo=1, hi=30)
    min_buy_sell_ratio: float = _f(1.2, "ratio", "Min 5m buys/sells when a snapshot is available", lo=0)
    take_profit_pct: float = _f(0.40, "fraction", "Partial take-profit trigger above entry (0.40 = +40%)",
                                lo=0, hi=10, lo_open=True)
    partial_tp_fraction: float = _f(0.5, "fraction", "Share of the position sold at the take-profit",
                                    lo=0, hi=1, lo_open=True)
    trail_pct: float = _f(0.15, "fraction", "Trailing stop from peak after the partial (0.15 = 15%)",
                          lo=0, hi=1, lo_open=True)
    stop_loss_pct: float = _f(0.18, "fraction", "Stop loss below entry (0.18 = -18%)", lo=0, hi=1, lo_open=True)
    max_hold_min: float = _f(120.0, "minutes", "Time stop", lo=0, lo_open=True)
    cooldown_min: float = _f(30.0, "minutes", "No re-entry into the same mint for this long after an exit", lo=0)
    candle_window_min: int = _f(180, "minutes", "Minimum 1m candles the engine fetches per watch evaluation (it "
                                "always fetches at least DIP_LOOKBACK_H, the window the strategy and the "
                                "backtester use)", lo=10, hi=1000)

    # ---- tested universe (G01, G12): trade only what every test covered -------
    # pump.fun graduates quoted in SOL, not Mayhem (crawler + cocoon); age counts from GRADUATION too.
    min_age_since_grad_min: float = _f(30.0, "minutes", "Only enter a coin this long after it GRADUATED from its "
                                       "bonding curve (Jupiter graduatedAt, GeckoTerminal as fallback); MIN_AGE_MIN "
                                       "still counts from creation. The lab saw the first 30 min after graduation "
                                       "lose most (no entries there)", lo=0)

    # ---- watchlist ----------------------------------------------------------
    watchlist_max: int = _f(15, "count", "Max tokens watched at once", lo=1, hi=100)
    watchlist_ttl_h: float = _f(6.0, "hours", "Drop a watched token after this long", lo=0, lo_open=True)

    # ---- cocoon (rug filter) thresholds; PERCENT ---------------------------
    cocoon_top10_max_pct: float = _f(30.0, "percent", "Hard fail if top-10 holders (AMM/curve/locker excluded) "
                                     "own more than this PERCENT", lo=0, hi=100)
    cocoon_single_holder_max_pct: float = _f(10.0, "percent", "Hard fail if one non-AMM holder owns more",
                                             lo=0, hi=100)
    cocoon_creator_max_pct: float = _f(5.0, "percent", "Hard fail if the creator still holds more", lo=0, hi=100)
    cocoon_insider_max_pct: float = _f(15.0, "percent", "Hard fail if insider networks hold more (together "
                                       "with COCOON_GRAPH_INSIDERS_MIN)", lo=0, hi=100)
    cocoon_graph_insiders_min: int = _f(5, "count", "RugCheck graphInsidersDetected at/above which insider "
                                        "share is enforced", lo=0)
    cocoon_dev_mints_max: int = _f(20, "count", "Hard fail if the creator launched more tokens (serial launcher)",
                                   lo=0)
    cocoon_lp_locked_min_pct: float = _f(90.0, "percent", "Graduated AMM pools: min LP locked/burned PERCENT",
                                         lo=0, hi=100)
    cocoon_min_holders: int = _f(100, "count", "Warn (not fail) below this holder count", lo=0)
    cocoon_cache_min: float = _f(30.0, "minutes", "Reuse a SafetyReport for this long", lo=0)

    # ---- cocoon name checks (decisions/fills team): warnings only, never a hard fail ------
    cocoon_copycat_window_h: float = _f(6.0, "hours", "Warn (not fail) when another coin with the same normalized "
                                        "ticker was seen within this many hours (0 disables)", lo=0, hi=168)
    cocoon_impersonation_names: str = _f(
        "Elon Musk, Elon, Tesla, SpaceX, Trump, Melania, Barron, Kanye, Taylor Swift, MrBeast, Vitalik, Saylor, "
        "BlackRock, Coinbase, Binance, OpenAI, ChatGPT, Nvidia, Apple, Google, Amazon, Microsoft, Meta, Disney, "
        "Nike, Solana, Jupiter, Phantom, Pump.fun, Raydium", "text",
        "Comma-separated brands/celebrities: warn (not fail) when a coin's name or ticker imitates one "
        "(look-alike letters and spacing tricks included). 'none' disables")

    # ---- radar --------------------------------------------------------------
    radar_min_trade_usd: float = _f(300.0, "usd", "Only trades at least this big are scanned", lo=0)
    radar_window_min: float = _f(15.0, "minutes", "Look-back window for big sells", lo=1, hi=1440)
    radar_insider_sell_usd: float = _f(500.0, "usd", "Flag when creator/top-holder/insider sells reach this", lo=0)
    radar_big_sell_liq_pct: float = _f(10.0, "percent", "Flag when big sells in the window reach this PERCENT "
                                       "of pool liquidity", lo=0, hi=1000)
    radar_interval_s: float = _f(180.0, "seconds", "Radar re-scan interval for open positions", lo=10)

    # ---- judge (Jev) --------------------------------------------------------
    anthropic_api_key: Secret | None = _f(None, "secret", "Enables the AI judge", secret=True)  # noqa: RUF009 - _f returns a dataclasses.field with validation metadata
    judge_mode: str = _f("", "text", "off | advisory | required (default: required when ANTHROPIC_API_KEY is set, "
                         "else off)", choices=("off", "advisory", "required"))
    judge_model: str = _f("claude-opus-5-5", "text", "Anthropic model id for the judge")
    judge_effort: str = _f("low", "text", "output_config.effort", choices=("low", "medium", "high", "xhigh", "max"))
    judge_timeout_s: float = _f(10.0, "seconds", "Per-request timeout (no retries: the engine re-asks next tick)",
                                lo=1, hi=600)
    judge_cache_min: float = _f(20.0, "minutes", "Reuse a verdict per mint for this long", lo=0)
    judge_max_daily_usd: float = _f(1.0, "usd", "Judge spend cap per UTC day; beyond it verdicts are 'no' "
                                    "(source=error). 0 blocks every judge call (and so every entry when "
                                    "JUDGE_MODE=required)", lo=0)

    # ---- endpoints & keys ---------------------------------------------------
    jupiter_api_key: Secret | None = _f(None, "secret", "Optional Jupiter key (header x-api-key)", secret=True)  # noqa: RUF009 - _f returns a dataclasses.field with validation metadata
    jupiter_base_url: str = _f("", "url", "Default: https://api.jup.ag with a key, else https://lite-api.jup.ag")
    solana_rpc_url: str = _f("https://api.mainnet-beta.solana.com", "url",
                             "Solana JSON-RPC endpoint (a free Helius key is recommended)")
    bot_wallet_secret: Secret | None = _f(None, "secret", "The bot wallet: base58 64-byte secret (Phantom export) "  # noqa: RUF009 - _f returns a dataclasses.field with validation metadata
                                          "or JSON byte array (solana-keygen). Required for live; in paper mode "
                                          "only its address is used (quotes and the dashboard's balance check)",
                                          secret=True)
    x_bearer_token: Secret | None = _f(None, "secret", "Optional X/Twitter token (unused by default)", secret=True)  # noqa: RUF009 - _f returns a dataclasses.field with validation metadata
    # ---- the bot's own wallet and taking the money back (broker/keystore.py, withdraw.py) ----
    bot_wallet_mode: str = _f("env", "text", "env = the wallet in BOT_WALLET_SECRET; generated = the bot makes its own "
                              "wallet on the first start (paper mode) and keeps the key in DATA_DIR/wallet/ where "
                              "nobody ever sees it: fund it from Phantom with Send, take it back with WITHDRAW_TO")
    withdraw_to: str = _f("", "text", "Your own Solana address (Phantom: Receive, Solana, copy): the wallet that sent "
                          "the bot its SOL. While set the bot buys nothing, sells everything, closes its empty coin "
                          "accounts, then (live, after 10 minutes in which deleting it cancels) sends ALL its SOL "
                          "there minus the network fee; paper mode only shows what it would send. Afterwards set "
                          "TRADING_MODE=paper: after a live withdrawal the bot buys nothing until it ran in paper")

    # ---- data sources (runtime / data-source team) --------------------------
    # GeckoTerminal's free tier (~30/min, 429s on shared IPs such as Railway's) is the scarcest
    # budget: by default it serves only candles and the radar; pump.fun backs up its candles.
    discover_gt_new_pools: bool = _f(False, "bool", "Also discover tokens from GeckoTerminal new_pools (lowest "
                                     "priority feed, paused for 5 min after a 429). Off by default: Jupiter "
                                     "recent/trending plus DexScreener cover discovery and GeckoTerminal's small "
                                     "free budget is kept for candles and the radar")
    pumpfun_candles: bool = _f(True, "bool", "pump.fun coins: take 1m candles from pump.fun's swap API when "
                               "GeckoTerminal fails, rate-limits or lags (one source per series, never mixed)")

    # ---- learning (docs/LEARNING.md) ------------------------------------------
    polydesk_enabled: bool = _f(True, "bool", "The Polymarket desk: a PAPER desk that watches Polymarket US's public "
                                "market data all day and keeps a paper book under one candidate rule (never real "
                                "money, never a key)")
    polydesk_theta: float = _f(0.97, "fraction", "Polymarket desk: buy a side on paper once it can be bought at or "
                                 "above this price", lo=0.5, hi=0.999)
    polydesk_hours: float = _f(1.0, "hours", "Polymarket desk: only within this many hours before a market's end",
                                 lo=0.05, hi=168)
    polydesk_ticket_usd: float = _f(20.0, "usd", "Polymarket desk: paper ticket per market", lo=1, hi=1000)
    polydesk_poll_s: float = _f(90.0, "seconds", "Polymarket desk: seconds between rounds", lo=30, hi=900)
    polydesk_mode: str = _f("paper", "text", "Polymarket desk: paper (default) or live (REAL MONEY on Polymarket US "
                            "through the account's API key; needs POLYDESK_LIVE_CONFIRM and both key variables)",
                            choices=("paper", "live"))
    polydesk_live_confirm: str = _f("", "text", f"Must equal {LIVE_CONFIRM_PHRASE} for POLYDESK_MODE=live")
    polydesk_live_contracts: float = _f(1.0, "count", "Polymarket desk live: contracts per market (1 = about a dollar "
                                        "at 97c; the venue's minimum on most markets)", lo=0.01, hi=100)
    polydesk_live_max_open_usd: float = _f(10.0, "usd", "Polymarket desk live: most money in open positions at once",
                                           lo=1, hi=10_000)
    polydesk_live_daily_loss_usd: float = _f(3.0, "usd", "Polymarket desk live: no more real buys for the UTC day "
                                             "after losing this much", lo=0.5, hi=10_000)
    polydesk_live_total_loss_usd: float = _f(10.0, "usd", "Polymarket desk live: after losing this much in total the "
                                             "desk switches itself back to paper for good (only the owner can "
                                             "switch it live again)", lo=1, hi=100_000)
    polydesk_resume_token: str = _f("", "text", "The owner's switch to turn real money back on after the total-loss "
                                    "cap switched the desk to paper: set it to a NEW value (e.g. today's date) and "
                                    "redeploy; each value works once. The caps and stops stay as they are")
    polydesk_guard: bool = _f(True, "bool", "Polymarket desk's risk manager (nightcrawler.deskguard): pauses new buys "
                              "(paper, and real in live mode) while the current rule's own record is losing, 95 % "
                              "sure (99 % sure from 10 events); open positions still settle; keeps the paper book at "
                              "10 open until the record is winning. It never switches real money on. off = the "
                              "owner's switch to let the desk keep buying")
    marco_real: bool = _f(False, "bool", "Marco's loves desk: when on AND POLYDESK_MODE=live, the Polymarket desk places "
                          "REAL orders (its contracts and every cap and stop) on the moneyline picks Million Dollar "
                          "Marco loves (src/nightcrawler/data/marco_picks.json), the owner's explicit exception to "
                          "the no-real-money-on-sports rule; off = his loves are followed with practice money only")
    follow_picks_url: str = _f("https://raw.githubusercontent.com/sideriapostolou-lgtm/Claude/refs/heads/claude/"
                               "nightcrawler-memecoin-bot-Gwnb1S/src/nightcrawler/data", "text",
                               "Where the loves desks read their picks files between deploys (an https folder URL: "
                               "the deploy branch's nightcrawler/data on GitHub); off = the packaged files only")
    polydesk_guard_min_n: int = _f(30, "count", "Polymarket desk's risk manager: events (a game's markets, or a "
                                   "ladder's markets ending together, count as one) of the current rule before it "
                                   "judges (fewer: still learning, unless a clear loser is stopped early from 10)",
                                   lo=10, hi=100_000)
    polydesk_guard_win_n: int = _f(100, "count", "Polymarket desk's risk manager: events before a record can count as "
                                   "winning (a flag for the owner, never real money by itself; below "
                                   "POLYDESK_GUARD_MIN_N it is raised to it)", lo=30, hi=1_000_000)
    polymarket_us_key_id: str = _f("", "text", "Polymarket US API key id (a Railway variable; the live desk only)",
                                   secret=True)
    polymarket_us_secret_key: str = _f("", "text", "Polymarket US API secret key (a Railway variable; the live desk "
                                       "only; never in a file or the repo)", secret=True)
    # ---- Bitcoin speed desk: practice books plus a separately gated Kalshi companion ----
    speeddesk_enabled: bool = _f(True, "bool", "Run the Bitcoin speed desk's independent practice trial")
    # Owner, 2026-10-13: "scale ... to other markets but let's perfect it first". Practice only: no key, no orders.
    speeddesk_coins: str = _f("", "text", "Comma list of other Kalshi 15-minute coins to run as practice-only "
                              "speed desks (eth, sol, xrp, doge), each with its own paper budget and report; "
                              "empty runs none. Never places a real order")
    speeddesk_kalshi_enabled: bool = _f(True, "bool", "Also read Kalshi Bitcoin 15-minute market data for the "
                                          "speed desk; this switch never authorizes orders")
    speeddesk_kalshi_ws_enabled: bool = _f(True, "bool", "Use the read-only Kalshi market WebSocket when keys "
                                             "are present, with public REST fallback; never enables orders")
    speeddesk_mode: str = _f("paper", "text", "Speed desk: practice only; real orders are unavailable",
                               choices=("paper",))
    speeddesk_window_usd: float = _f(20.0, "usd", "Speed desk: maximum practice spend per window, fees included",
                                      lo=0, lo_open=True, hi=1_000_000)
    speeddesk_open_usd: float = _f(20.0, "usd", "Speed desk: maximum practice spend across open windows",
                                    lo=0, lo_open=True, hi=1_000_000)
    speeddesk_day_stop_usd: float = _f(10.0, "usd", "Speed desk: stop new practice buys at this settled daily loss "
                                        "until midnight UTC", lo=0, lo_open=True, hi=1_000_000)
    speeddesk_take_edge: float = _f(0.02, "fraction", "Speed desk: minimum taker edge after fees", lo=0, hi=1)
    speeddesk_make_edge: float = _f(0.03, "fraction", "Speed desk: resting bid discount below fair value",
                                     lo=0, hi=1)
    speeddesk_pair_cap: float = _f(0.99, "fraction", "Speed desk: maximum matched pair cost including fees",
                                    lo=0, lo_open=True, hi=1)
    speeddesk_max_imbalance: float = _f(0.25, "fraction", "Speed desk: maximum imbalance as a share of total "
                                         "contracts", lo=0, hi=1)
    speeddesk_clip: float = _f(25.0, "count", "Speed desk: maximum contracts per practice order",
                                lo=0, lo_open=True, hi=100_000)
    speeddesk_cutoff_s: float = _f(60.0, "seconds", "Speed desk: stop new practice buys this long before close",
                                    lo=0, hi=899)
    speeddesk_latency_ms: float = _f(250.0, "milliseconds", "Speed desk: minimum delay before checking that a "
                                      "taker's quoted ask still exists", lo=1, hi=60_000)
    speeddesk_kalshi_mode: str = _f("paper", "text", "Kalshi speed companion: paper by default; live requires "
                                      "the owner's exact confirmation and authenticated account checks",
                                      choices=("paper", "live"))
    speeddesk_kalshi_account_type: Literal["unknown", "direct", "fcm"] = _f(
        "unknown", "text", "Owner-attested Kalshi fee category, not permission to trade: direct uses $0.0001 "
        "fee rounding; unknown or fcm reserves the conservative $0.01 bound. Never infer the account type",
        choices=("unknown", "direct", "fcm"))
    speeddesk_kalshi_live_confirm: Secret | None = _f(  # noqa: RUF009 - _f returns a dataclasses.field
        None, "secret", "Must equal yes exactly before the Kalshi speed companion may submit real orders; "
        "mode must also be live", secret=True)
    speeddesk_kalshi_resume_token: Secret | None = _f(  # noqa: RUF009 - _f returns a dataclasses.field
        None, "secret", "Owner-controlled Kalshi total-stop reset: a new value works once; only its hash may be "
        "persisted, never its value. Does not change any cap or enable live mode", secret=True)
    speeddesk_kalshi_integrity_reset_token: Secret | None = _f(  # noqa: RUF009 - _f returns a dataclasses.field
        None, "secret", "Owner-controlled one-time reset of a Kalshi reconciliation stop: a new value clears the "
        "stop present at startup, only after a clean reconcile with nothing open; a value set while no stop "
        "exists is spent at once. Only its hash is persisted. Does not change any cap or enable live mode",
        secret=True)
    speeddesk_kalshi_day_reset_token: Secret | None = _f(  # noqa: RUF009 - _f returns a dataclasses.field
        None, "secret", "Owner-controlled one-time fresh daily budget for the Kalshi companion: a new value makes "
        "today's loss count again from the moment it is first seen, for the rest of that UTC day only. The daily "
        "cap, the lifetime stop and every other limit are unchanged. Only its hash is persisted", secret=True)
    # Owner-authorized 2026-10-13 ("2.5x"): $5 per window, $10 open, -$6 day, -$10 total. Raised 2026-10-13 15:15 UTC
    # ("ten now double tmr if it works"): $10 per window, $20 open; both stops unchanged. Owner, 2026-10-13 16:00 UTC:
    # "Yes when it's winning go $20 a window $40 open $12 daily": the ceilings below allow that step; the defaults stay
    # at $10/$20/$6 and the step is set through the Railway variables (rule in docs/ACCOUNTS.md). Total stop unchanged.
    speeddesk_kalshi_window_usd: float = _f(10.0, "usd", "Kalshi live companion: fee-inclusive maximum spend per "
                                            "window on new buys; owner-authorized ceiling $20 when winning. A lock "
                                            "that only completes pairs may add to it, because it can only lower the "
                                            "loss", lo=0, lo_open=True, hi=20)
    speeddesk_kalshi_open_usd: float = _f(20.0, "usd", "Kalshi live companion: fee-inclusive maximum money that "
                                          "open windows and pending orders can still lose; owner-authorized "
                                          "ceiling $40 when winning", lo=0, lo_open=True, hi=40)
    speeddesk_kalshi_day_stop_usd: float = _f(6.0, "usd", "Kalshi live companion: daily loss stop; "
                                              "owner-authorized ceiling $12 when winning", lo=0, lo_open=True,
                                              hi=12)
    speeddesk_kalshi_total_stop_usd: float = _f(10.0, "usd", "Kalshi live companion: persistent total-loss stop; "
                                                "owner-authorized ceiling $10", lo=0, lo_open=True, hi=10)
    # Owner, 2026-10-13 ~18:40 UTC, after Claude proposed the earned-growth ladder: "Max $50,000 a window build the
    # ladder". The four settings above are its rung 0, the owner's floor; each earned rung adds $5 a window (open 2x,
    # day stop 60 %); the first buy stays SPEEDDESK_KALSHI_CLIP below at every rung (owner, 2026-10-13 ~20:15 UTC:
    # "Keep 5 at every rung") and the $10 total stop never scales
    # (speeddesk_live_ladder.py, rule in docs/SPEEDDESK_SPEC.md 9.2). The ladder never goes above the ceilings above
    # and the risk book's own (LiveLimits): $20 a window, $40 open, $12 a day, 25 contracts until they are raised.
    # A promotion is re-checked at its window boundary before it applies.
    speeddesk_kalshi_ladder: bool = _f(True, "bool", "Kalshi live companion: the earned-growth ladder. One rung up "
                                       "($5 more a window) only after 96 settled windows at the rung, a gain of 2 "
                                       "sigma sqrt(n), house money, 24 h without a stop and the cash for it; one rung "
                                       "down after giving back 60 % of a window from the rung's peak; every change "
                                       "starts at the next window. false = always the configured limits (and the "
                                       "ladder starts again at rung 0)")
    speeddesk_kalshi_ladder_max_window_usd: float = _f(50_000.0, "usd", "Kalshi live companion: the ladder's highest "
                                                       "window (the owner's maximum is $50,000; the code ceilings "
                                                       "above apply first); lower it to stop the climb earlier",
                                                       lo=0, lo_open=True, hi=50_000)
    # Owner, 2026-10-13 16:20 UTC, after two windows were run over at the new 10-contract size: "make sure it never
    # happens again". The first buy in a window is the bet that can be run over, so it is held to 5 contracts
    # (the size of every morning win); the $10 window budget is unchanged.
    speeddesk_kalshi_clip: float = _f(5.0, "count", "Kalshi live companion: maximum contracts per real order, so "
                                      "also the size of the first buy in a window; balancing and lock orders "
                                      "follow it", lo=0, lo_open=True, hi=25)
    speeddesk_kalshi_lock_s: float = _f(240.0, "seconds", "Kalshi live companion: from this long before the close, "
                                        "new buys stop and a half-filled pair is completed (locked) instead of "
                                        "riding to settlement; never shorter than the buying cutoff",
                                        lo=60, hi=899)
    speeddesk_kalshi_lock_max_price: float = _f(0.97, "fraction", "Kalshi live companion: highest price paid per "
                                                "contract to complete a half-filled pair; above it the window is "
                                                "already decided and the pair is left as it is",
                                                lo=0.5, hi=0.99)
    speeddesk_kalshi_cutoff_s: float = _f(180.0, "seconds", "Kalshi live companion: stop buying this long before "
                                          "window close; default trades only the first 12 minutes of a 15m window",
                                          lo=60, hi=899)
    # Owner, 2026-10-13: "Give our bots the incentive they're giving Grok bots: make money or die" (nightcrawler.
    # kalshi_arena). PRACTICE only: these four change pretend money and never a live limit, order or key. A bad value
    # turns the arena off with a warning instead of stopping the engine (Settings._lenient_arena).
    kalshi_arena_enabled: bool = _f(True, "bool", "The Kalshi arena: a PRACTICE town of Kalshi Bitcoin 15-minute "
                                    "desks with their own genes that pay rent, are evicted when broke or losing, and "
                                    "breed from the richest; never places a real order or changes a live setting")
    kalshi_arena_population: int = _f(12, "count", "Kalshi arena: residents, including the control that always runs "
                                      "the live rules", lo=2, hi=24)
    kalshi_arena_rent_usd: float = _f(0.20, "usd", "Kalshi arena: practice rent each resident pays per UTC day (about "
                                      "the whole Railway bill each)", lo=0, hi=5)
    kalshi_arena_broke_usd: float = _f(10.0, "usd", "Kalshi arena: a resident whose practice money falls under this "
                                       "is evicted (it could not fund a $10 window)", lo=0, hi=49)
    kalshi_key_id: Secret | None = _f(  # noqa: RUF009 - _f returns a dataclasses.field
        None, "secret", "Kalshi account key id, supplied by the owner in Railway; never logged", secret=True)
    kalshi_private_key: Secret | None = _f(  # noqa: RUF009 - _f returns a dataclasses.field
        None, "secret", "Kalshi signing key, supplied by the owner in Railway; never logged or stored in desk "
        "state. Public REST needs no key; the authorized read-only market WebSocket uses it", secret=True)
    # ---- Public source-bot observation, separate from every trading desk ----
    skipwatch_enabled: bool = _f(True, "bool", "Observe the source bot's PUBLIC trades and books; never places "
                                    "orders or enables a money strategy")
    skipwatch_poll_s: float = _f(2.5, "seconds", "Public wallet-trade poll interval; rate limits back off longer",
                                   lo=2, hi=3)
    skipwatch_max_storage_mb: int = _f(4096, "count", "Maximum watcher journal size in MiB; stop capture with a "
                                         "visible gap at the limit, never delete research evidence", lo=64, hi=16384)
    skipwatch_min_free_mb: int = _f(128, "count", "Keep this much disk free in MiB for the trading desks; halt "
                                      "watcher capture before using it", lo=64, hi=4096)
    # ---- Weather observation only: no order client or money switches ----
    weatherwatch_enabled: bool = _f(True, "bool", "Measure weather observations and public market depth; "
                                        "never places orders or enables trading")
    weatherwatch_max_storage_mb: int = _f(512, "count", "Maximum weather evidence storage in MiB; halt capture "
                                            "with a visible gap at the limit", lo=64, hi=4096)
    weatherwatch_min_free_mb: int = _f(128, "count", "Keep this much disk free in MiB for existing desks",
                                         lo=64, hi=4096)
    weatherwatch_retention_days: int = _f(7, "count", "Daily weather report retention in UTC days; "
                                            "raw journal evidence is never automatically deleted", lo=4, hi=31)
    weatherwatch_discovery_s: float = _f(300.0, "seconds", "Refresh weather market discovery at this interval",
                                           lo=60, hi=3600)
    weatherwatch_max_active_watches: int = _f(20, "count", "Maximum simultaneous ten-minute weather market "
                                                "observations; skipped watches are reported", lo=1, hi=100)
    trenddesk_enabled: bool = _f(True, "bool", "The trend desk: a PAPER forward test of lab 3's 50-day trend rule on "
                                 "BTC, ETH and SOL, from Coinbase's public daily candles once a day (never real money, "
                                 "never a key)")
    trenddesk_sleeve_usd: float = _f(100.0, "usd", "Trend desk: the paper sleeve, split equally across BTC, ETH and "
                                     "SOL (fixed when its record starts)", lo=10, hi=1_000_000)
    learn_enabled: bool = _f(True, "bool", "Self-learning loop: record every pump.fun graduate and test strategy "
                             "versions in the shadow. It never trades, never changes risk settings and uses its "
                             "own small API budget; false = no learning calls at all")
    learn_disk_cap_gb: float = _f(3.0, "gb", "Disk cap for DATA_DIR/learn (oldest sealed days are deleted first; "
                                  "the ledger always has priority)", lo=0.1, lo_open=False)
    learn_interval_min: float = _f(30.0, "minutes", "How often the bot starts the learner in the background "
                                   "(replays finished days, scores every strategy version)", lo=1.0, lo_open=False)

    # ---- dashboard ----------------------------------------------------------
    port: int = _f(8080, "port", "Dashboard port (Railway sets PORT)", lo=1, hi=65535)
    dashboard_host: str = _f("0.0.0.0", "text", "Dashboard bind address")
    dashboard_token: Secret | None = _f(None, "secret", "If set, the dashboard requires ?token= or cookie. Live "  # noqa: RUF009 - _f returns a dataclasses.field with validation metadata
                                        "mode needs a strong one: a long random password of at least 24 characters",
                                        secret=True)
    # The town card on the page: the desks must earn more than the bot costs to run (pagestate.town_ledger).
    town_railway_usd_month: float = _f(5.0, "usd", "What Railway charges per month to run the bot (Hobby plan: 5). "
                                       "The page's town card turns it into a cost per day, adds the AI judge's "
                                       "spending and compares both with what the desks made. 0 = free hosting",
                                       lo=0)
    # The 3D world's nightly recap film (nightcrawler.recap): "yesterday" is a calendar day of this zone.
    owner_tz: str = _f("America/Los_Angeles", "text", "The owner's time zone, an IANA name such as Europe/Athens: "
                       "the 3D world's nightly recap film replays the previous calendar day of this zone (it plays "
                       "by itself at 00:05 there if the page is open, and on demand)")
    # The 3D world's town goal (nightcrawler.towngoal, /api/page town.goal): text, read leniently there, so a typo
    # can never stop the bot from starting; no desk, limit or rule reads it.
    town_goal_usd: str = _f("100", "text", "DISPLAY ONLY: the owner's goal for the team in real money a day, shown in "
                            "the 3D world; no desk reads it; a value it cannot read shows 100")

    # ---- provider usage budgets (observability team) -------------------------
    # The dashboard's Usage panel shows calls per provider per UTC day and month against these
    # free-tier budgets, with a warning chip at 80 %. 0 = no budget (the provider only rate-limits).
    # The AI judge's budget is JUDGE_MAX_DAILY_USD (above).
    usage_helius_monthly_credits: int = _f(1_000_000, "count", "Helius credits per UTC month (free plan: "
                                           "1,000,000); nightcrawler counts 1 credit per RPC call. 0 = no budget",
                                           lo=0)
    usage_jupiter_monthly_calls: int = _f(0, "count", "Jupiter calls per UTC month (0 = no budget: the free API "
                                          "is only rate-limited)", lo=0)
    usage_geckoterminal_monthly_calls: int = _f(0, "count", "GeckoTerminal calls per UTC month (0 = no budget)",
                                                lo=0)
    usage_dexscreener_monthly_calls: int = _f(0, "count", "DexScreener calls per UTC month (0 = no budget)", lo=0)
    usage_rugcheck_monthly_calls: int = _f(0, "count", "RugCheck calls per UTC month (0 = no budget)", lo=0)

    # ---- intervals ----------------------------------------------------------
    discovery_interval_s: float = _f(30.0, "seconds", "Crawler poll interval", lo=1)
    watch_interval_s: float = _f(60.0, "seconds", "Watchlist evaluation interval", lo=1)
    position_interval_s: float = _f(10.0, "seconds", "Open-position marking interval", lo=1)
    equity_interval_s: float = _f(60.0, "seconds", "Equity snapshot interval", lo=1)

    # ------------------------------------------------------------------ build
    def __post_init__(self) -> None:
        # Derived defaults (frozen dataclass: use object.__setattr__).
        if not self.judge_mode:
            object.__setattr__(self, "judge_mode", "required" if self.anthropic_api_key else "off")
        if not self.jupiter_base_url:
            object.__setattr__(self, "jupiter_base_url",
                               "https://api.jup.ag" if self.jupiter_api_key else "https://lite-api.jup.ag")
        object.__setattr__(self, "jupiter_base_url", self.jupiter_base_url.rstrip("/"))
        if not isinstance(self.data_dir, Path):
            object.__setattr__(self, "data_dir", Path(self.data_dir))
        object.__setattr__(self, "trading_mode", str(self.trading_mode).lower())
        object.__setattr__(self, "kill_switch", _normalize_kill_switch(self.kill_switch))
        object.__setattr__(self, "judge_mode", str(self.judge_mode).lower())
        object.__setattr__(self, "log_level", str(self.log_level).upper())
        object.__setattr__(self, "keys_rotated_on", str(self.keys_rotated_on).strip())
        object.__setattr__(self, "bot_wallet_mode", str(self.bot_wallet_mode).strip().lower())
        object.__setattr__(self, "withdraw_to", str(self.withdraw_to).strip())
        object.__setattr__(self, "owner_tz", str(self.owner_tz).strip())
        for name in ("kalshi_key_id", "kalshi_private_key", "speeddesk_kalshi_resume_token",
                     "speeddesk_kalshi_integrity_reset_token", "speeddesk_kalshi_day_reset_token",
                     "speeddesk_kalshi_live_confirm"):
            value = getattr(self, name)
            if isinstance(value, str):
                object.__setattr__(self, name, Secret(value) if value else None)
        if _zone_unknown(self.owner_tz):  # a cosmetic setting (the recap film): warn, never refuse to start
            logging.getLogger(__name__).warning("config_owner_tz_unknown value=%r using=UTC", self.owner_tz[:60])
        self._lenient_arena()
        problems = self._validate()
        if problems:
            raise ConfigError(problems)

    def _lenient_arena(self, bad: Iterable[str] = ()) -> None:
        """The Kalshi arena's settings change practice money only, so a bad one must never stop the engine (and with
        it the real-money Kalshi companion): it takes its default, the arena is switched off, and a warning names
        it. ``bad`` names values that could not even be read (Settings.from_env)."""
        problems = [name.upper() for name in bad]
        for f in dataclasses.fields(self):
            if not f.name.startswith("kalshi_arena_"):
                continue
            value, meta = getattr(self, f.name), f.metadata
            if meta.get("unit") == "bool":
                ok = isinstance(value, bool)
            else:
                lo, hi = meta.get("lo"), meta.get("hi")
                ok = (not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
                      and (meta.get("unit") != "count" or isinstance(value, int))
                      and (lo is None or value >= lo) and (hi is None or value <= hi))
            if not ok:
                problems.append(f.name.upper())
                object.__setattr__(self, f.name, f.default)
        if problems:
            object.__setattr__(self, "kalshi_arena_enabled", False)
            logging.getLogger(__name__).warning("config_kalshi_arena_off bad=%s (practice town off; everything else "
                                                "runs)", ",".join(sorted(set(problems))))

    def _validate(self) -> list[str]:
        problems: list[str] = []
        for f in dataclasses.fields(self):
            meta = f.metadata
            value = getattr(self, f.name)
            env = f.name.upper()
            if f.name in ("kalshi_key_id", "kalshi_private_key", "speeddesk_kalshi_resume_token",
                          "speeddesk_kalshi_integrity_reset_token", "speeddesk_kalshi_day_reset_token",
                          "speeddesk_kalshi_live_confirm"):
                if value is not None and not isinstance(value, Secret):
                    problems.append(f"{env} must be a secret string")
                continue
            if (f.name.startswith("speeddesk_kalshi_") and meta.get("unit") in ("usd", "seconds", "count")
                    and (isinstance(value, bool) or not isinstance(value, (int, float)))):
                problems.append(f"{env} must be a finite number")
                continue
            if f.name == "speeddesk_coins":
                names = {part.strip().lower() for part in str(value).split(",") if part.strip()}
                unknown = sorted(names - {"eth", "sol", "xrp", "doge"})
                if not isinstance(value, str) or unknown:
                    problems.append(f"{env} accepts only eth, sol, xrp and doge")
                continue
            if f.name in ("skipwatch_poll_s", "skipwatch_max_storage_mb", "skipwatch_min_free_mb"):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    problems.append(f"{env} must be a finite number")
                    continue
                if f.name.endswith("_mb") and not isinstance(value, int):
                    problems.append(f"{env} must be a whole number of MiB")
                    continue
            if f.name.startswith("weatherwatch_"):
                if meta.get("unit") == "bool":
                    if not isinstance(value, bool):
                        problems.append(f"{env} must be a boolean")
                        continue
                elif isinstance(value, bool) or not isinstance(value, (int, float)):
                    problems.append(f"{env} must be a finite number")
                    continue
                elif meta.get("unit") == "count" and not isinstance(value, int):
                    problems.append(f"{env} must be a whole number")
                    continue
            if meta.get("choices") and value not in meta["choices"]:
                problems.append(f"{env}={value!r} must be one of {', '.join(meta['choices'])}")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if f.name.startswith(("speeddesk_", "skipwatch_", "weatherwatch_")) and not math.isfinite(value):
                    problems.append(f"{env} must be finite")
                    continue
                lo, hi = meta.get("lo"), meta.get("hi")
                unit = meta.get("unit")
                hint = " (a FRACTION: 0.20 means 20%)" if unit == "fraction" else (
                    " (PERCENT: 3.0 means 3%)" if unit == "percent" else "")
                if lo is not None and (value <= lo if meta.get("lo_open") else value < lo):
                    op = ">" if meta.get("lo_open") else ">="
                    problems.append(f"{env}={value} must be {op} {lo}{hint}")
                if hi is not None and value > hi:
                    problems.append(f"{env}={value} must be <= {hi}{hint}")
        if self.polydesk_mode == "live":
            if self.polydesk_live_confirm != LIVE_CONFIRM_PHRASE:
                problems.append(f"POLYDESK_MODE=live requires POLYDESK_LIVE_CONFIRM={LIVE_CONFIRM_PHRASE} (exact)")
            if not self.polymarket_us_key_id or not self.polymarket_us_secret_key:
                problems.append("POLYDESK_MODE=live requires POLYMARKET_US_KEY_ID and POLYMARKET_US_SECRET_KEY")
        if self.trading_mode == "live":
            if self.live_confirm != LIVE_CONFIRM_PHRASE:
                problems.append(f"TRADING_MODE=live requires LIVE_CONFIRM={LIVE_CONFIRM_PHRASE} (exact)")
            if not self.bot_wallet_secret and self.bot_wallet_mode != "generated":
                problems.append("TRADING_MODE=live requires a bot wallet: BOT_WALLET_MODE=generated (the bot's own "
                                "wallet) or BOT_WALLET_SECRET (a dedicated bot wallet)")
            if not self.dashboard_token and self.dashboard_host not in _LOOPBACK_HOSTS:
                problems.append("TRADING_MODE=live requires DASHBOARD_TOKEN (or DASHBOARD_HOST=127.0.0.1): "
                                "an open dashboard shows the live wallet, its positions and their stops")
            weak = dashboard_token_problem(self.dashboard_token.reveal()) if self.dashboard_token else None
            if weak:  # never repeat the token: this message goes to the deploy logs
                problems.append(f"TRADING_MODE=live requires a strong DASHBOARD_TOKEN: it is {weak}. Use a long "
                                f"random password of at least {DASHBOARD_TOKEN_MIN_LEN} characters")
        if self.keys_rotated_on and parse_rotation_date(self.keys_rotated_on) is None:
            # never repeat the value: a key pasted into the wrong box would land in the deploy logs
            problems.append("KEYS_ROTATED_ON must be a date like 2026-10-09: the day you replaced the keys "
                            "(leave it empty until then)")
        problems.extend(_wallet_problems(self))
        if self.judge_mode in ("advisory", "required") and not self.anthropic_api_key:
            problems.append(f"JUDGE_MODE={self.judge_mode} requires ANTHROPIC_API_KEY (or set JUDGE_MODE=off)")
        if self.min_position_usd > self.max_position_usd:
            problems.append("MIN_POSITION_USD must be <= MAX_POSITION_USD")
        if self.min_mcap_usd >= self.max_mcap_usd:
            problems.append("MIN_MCAP_USD must be < MAX_MCAP_USD")
        if self.min_age_min >= self.max_age_h * 60:
            problems.append("MIN_AGE_MIN must be shorter than MAX_AGE_H")
        if self.min_age_since_grad_min >= self.max_age_h * 60:
            problems.append("MIN_AGE_SINCE_GRAD_MIN must be shorter than MAX_AGE_H")
        for name in ("jupiter_base_url", "solana_rpc_url"):
            url = getattr(self, name)
            if not url.startswith(("http://", "https://")):
                problems.append(f"{name.upper()} must start with http:// or https://")
        return problems

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Build from a mapping of ENV_NAME -> string (default ``os.environ``).

        Unknown keys are ignored; blank values mean "use the default".
        Raises :class:`ConfigError` (all problems at once) on bad values.
        """
        env = os.environ if env is None else env
        kwargs: dict[str, Any] = {}
        problems: list[str] = []
        unreadable: list[str] = []
        for f in dataclasses.fields(cls):
            raw = env.get(f.name.upper())
            if raw is None or str(raw).strip() == "":
                continue
            raw = str(raw).strip()
            try:
                kwargs[f.name] = _coerce(f, raw)
            except ValueError as exc:
                if f.name.startswith("kalshi_arena_"):
                    unreadable.append(f.name)  # practice only: the arena goes off instead (_lenient_arena)
                    continue
                problems.append(f"{f.name.upper()}: {exc}")
        if problems:
            raise ConfigError(problems)
        if unreadable:
            kwargs["kalshi_arena_enabled"] = False
            settings = cls(**kwargs)
            settings._lenient_arena(unreadable)
            return settings
        return cls(**kwargs)

    def replace(self, **changes: Any) -> Settings:
        """Copy with changes (re-validated). Strings for secret fields are wrapped."""
        for name, value in list(changes.items()):
            f = _FIELDS[name]
            if f.metadata.get("secret") and isinstance(value, str):
                changes[name] = Secret(value) if value else None
        return dataclasses.replace(self, **changes)

    # ------------------------------------------------------------------ views
    def __repr__(self) -> str:
        inner = ", ".join(f"{k}={v!r}" for k, v in self.public_dict().items())
        return f"Settings({inner})"

    @property
    def is_live(self) -> bool:
        return self.trading_mode == "live"

    @property
    def sol_reserve_lamports(self) -> int:
        return int(round(self.sol_reserve * 1_000_000_000))  # noqa: RUF046 - preserve explicit integer conversion at this existing boundary

    @property
    def network_fee_lamports(self) -> int:
        return int(round(self.network_fee_sol * 1_000_000_000))  # noqa: RUF046 - preserve explicit integer conversion at this existing boundary

    @property
    def db_path(self) -> Path:
        return self.data_dir / "nightcrawler.db"

    @property
    def kill_file(self) -> Path:
        return self.data_dir / "KILL"

    @property
    def dataset_dir(self) -> Path:
        return self.data_dir / "dataset"

    @property
    def judge_enabled(self) -> bool:
        return self.judge_mode != "off"

    def ensure_data_dir(self) -> Path:
        """Create DATA_DIR if missing and return it."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir

    def strategy_params(self):  # -> models.StrategyParams (import kept local to avoid cycles)
        from nightcrawler.models import StrategyParams

        return StrategyParams.from_settings(self)

    def secret_values(self) -> list[str]:
        """Raw secret strings (for the log redaction filter). Never log this list."""
        out = []
        for f in dataclasses.fields(self):
            if f.metadata.get("secret"):
                v = getattr(self, f.name)
                if v:
                    out.append(v.reveal())
        out.extend(_url_secret_values(self.solana_rpc_url))
        held = _RUNTIME_SECRETS.get(id(self))
        if held is not None and held[0] is self:
            out.extend(s.reveal() for s in held[1])
        return out

    def add_runtime_secret(self, value: str) -> None:
        """A secret this process made or loaded at run time (the bot's own wallet key, broker/keystore.py):
        from now on :meth:`secret_values` returns it too, so every scrubber treats it like BOT_WALLET_SECRET.
        Kept for THIS Settings object only (never in the environment, never pickled: :class:`Secret`)."""
        if not value:
            return
        held = _RUNTIME_SECRETS.get(id(self))
        known = held[1] if held is not None and held[0] is self else ()
        if all(s.reveal() != value for s in known):
            _RUNTIME_SECRETS[id(self)] = (self, (*known, Secret(value)))

    def public_dict(self) -> dict[str, Any]:
        """JSON-safe settings with NO secret values: secrets become ``<name>_set: bool``."""
        out: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            v = getattr(self, f.name)
            if f.name == "speeddesk_kalshi_live_confirm":
                out["speeddesk_kalshi_live_confirmed"] = v == Secret("yes")
            elif f.metadata.get("secret"):
                out[f"{f.name}_set"] = bool(v)
            elif f.name == "live_confirm":
                out["live_confirmed"] = v == LIVE_CONFIRM_PHRASE
            elif f.name == "solana_rpc_url":
                out[f.name] = redact_rpc_url(v)
            elif isinstance(v, Path):
                out[f.name] = str(v)
            else:
                out[f.name] = v
        return out

    @classmethod
    def describe(cls) -> list[dict[str, Any]]:
        """One dict per setting: env, default, unit, help, secret, choices (for docs/.env.example)."""
        rows = []
        for f in dataclasses.fields(cls):
            default = f.default
            if isinstance(default, Path):
                default = str(default)
            rows.append({
                "env": f.name.upper(),
                "attr": f.name,
                "default": default,
                "unit": f.metadata.get("unit"),
                "help": f.metadata.get("help"),
                "secret": bool(f.metadata.get("secret")),
                "choices": f.metadata.get("choices"),
            })
        return rows


_FIELDS = {f.name: f for f in dataclasses.fields(Settings)}
#: :meth:`Settings.add_runtime_secret`: ``id(settings) -> (settings, secrets)`` (the object is kept, so its id
#: is never reused by another Settings; a frozen slots dataclass cannot hold the list itself).
_RUNTIME_SECRETS: dict[int, tuple[Settings, tuple[Secret, ...]]] = {}


def _zone_unknown(name: str) -> bool:
    """True when ``name`` is not a time zone this machine knows (the recap then uses the UTC day and says so: a
    warning at start, never a refusal, since the setting only names the film's day). A machine without any time-zone
    database (even ``UTC`` fails to load) is not warned about each name."""
    import zoneinfo

    try:
        zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        pass
    else:
        return False
    try:
        zoneinfo.ZoneInfo("UTC")
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True


def _wallet_problems(s: Settings) -> list[str]:
    """BOT_WALLET_MODE and WITHDRAW_TO. A value is never repeated: a key pasted into the wrong box would land in
    the deploy logs (the WITHDRAW_TO checks that need the chain or the wallet are in ``nightcrawler.withdraw``)."""
    from nightcrawler.base58 import is_pubkey

    problems = []
    if s.bot_wallet_mode not in ("env", "generated"):
        problems.append("BOT_WALLET_MODE must be env or generated")
    elif s.bot_wallet_mode == "generated" and s.bot_wallet_secret:
        problems.append("BOT_WALLET_MODE=generated and BOT_WALLET_SECRET are both set: use one wallet only (delete "
                        "BOT_WALLET_SECRET to use the wallet the bot made itself, or set BOT_WALLET_MODE=env)")
    if s.withdraw_to and not is_pubkey(s.withdraw_to):
        problems.append("WITHDRAW_TO must be a Solana address (in Phantom: Receive, choose Solana, copy)")
    return problems


def _coerce(f: dataclasses.Field, raw: str) -> Any:
    if f.metadata.get("secret"):
        return Secret(raw)
    default = f.default
    if isinstance(default, bool):
        low = raw.lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise ValueError(f"expected true/false, got {raw!r}")
    if isinstance(default, int):
        try:
            return int(raw)
        except ValueError:
            try:
                fl = float(raw)
            except ValueError:
                raise ValueError(f"expected a whole number, got {raw!r}") from None
            if not fl.is_integer():
                raise ValueError(f"expected a whole number, got {raw!r}") from None
            return int(fl)
    if isinstance(default, float):
        if raw.endswith("%"):
            raise ValueError(f"write a plain number without '%', got {raw!r}")
        try:
            v = float(raw)
        except ValueError:
            raise ValueError(f"expected a number, got {raw!r}") from None
        if v != v or v in (float("inf"), float("-inf")):  # noqa: PLR0124 - explicit NaN check for parsed floats
            raise ValueError(f"expected a finite number, got {raw!r}")
        return v
    if isinstance(default, Path):
        return Path(raw)
    return raw


def parse_dotenv(path: str | os.PathLike[str]) -> dict[str, str]:
    """Parse a simple ``.env`` file (``KEY=value``, ``#`` comments, optional quotes, ``export``).

    Returns ``{}`` if the file does not exist. No variable interpolation.
    """
    p = Path(path)
    if not p.is_file():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        out[key] = value
    return out


def load_settings(dotenv_path: str | os.PathLike[str] | None = ".env",
                  env: Mapping[str, str] | None = None) -> Settings:
    """Production loader: ``.env`` file values overlaid by real environment variables.

    Real env always wins over the file. Pass ``dotenv_path=None`` to skip the file.
    """
    merged: dict[str, str] = {}
    if dotenv_path is not None:
        merged.update(parse_dotenv(dotenv_path))
    merged.update(os.environ if env is None else env)
    return Settings.from_env(merged)
