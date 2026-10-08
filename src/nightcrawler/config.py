"""Settings: one frozen dataclass loaded from environment variables.

* Env name = upper-snake of the attribute (``position_pct`` <- ``POSITION_PCT``).
* Empty env values count as unset (Railway sometimes sets blank variables).
* Secrets (``BOT_WALLET_SECRET``, ``ANTHROPIC_API_KEY``, ``JUPITER_API_KEY``,
  ``X_BEARER_TOKEN``, ``DASHBOARD_TOKEN``) are wrapped in :class:`Secret`, whose
  ``repr``/``str`` is ``***``; call ``.reveal()`` only at the point of use.
  :meth:`Settings.public_dict` never contains secret values (only ``*_set``
  booleans) and redacts API keys embedded in ``SOLANA_RPC_URL``.
* Construction validates everything (``__post_init__``) and raises
  :class:`ConfigError` listing every problem at once.

Units: see the per-field ``unit`` metadata and ``models.py``. Note the
documented exception: ``POSITION_PCT, DAILY_LOSS_LIMIT_PCT,
MAX_DRAWDOWN_HALT_PCT, DIP_PCT, TAKE_PROFIT_PCT, TRAIL_PCT, STOP_LOSS_PCT`` are
FRACTIONS (0.20 = 20 %); ``MAX_PRICE_IMPACT_PCT``, ``COCOON_*_PCT`` and
``RADAR_*_PCT`` are PERCENT (3.0 = 3 %).
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlsplit

__all__ = [
    "LIVE_CONFIRM_PHRASE",
    "Secret",
    "ConfigError",
    "Settings",
    "load_settings",
    "parse_dotenv",
    "redact_url",
]

LIVE_CONFIRM_PHRASE = "I_ACCEPT_REAL_MONEY_RISK"
_TRUE = {"1", "true", "yes", "on", "y"}
_FALSE = {"0", "false", "no", "off", "n"}
_SECRET_QUERY_HINTS = ("key", "token", "secret", "auth", "password")


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

    def __copy__(self) -> "Secret":
        return self

    def __deepcopy__(self, memo: dict) -> "Secret":
        return self

    def __reduce__(self):  # refuse to pickle secrets by accident
        raise TypeError("Secret values cannot be pickled")


class ConfigError(ValueError):
    """Invalid configuration. ``problems`` lists every issue found."""

    def __init__(self, problems: Iterable[str]) -> None:
        self.problems = list(problems)
        super().__init__("Invalid configuration:\n  - " + "\n  - ".join(self.problems))


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


def _url_secret_values(url: str) -> list[str]:
    if not url or "?" not in url:
        return []
    out = []
    for k, v in parse_qsl(urlsplit(url).query, keep_blank_values=True):
        if v and any(h in k.lower() for h in _SECRET_QUERY_HINTS):
            out.append(v)
    return out


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
    data_dir: Path = _f(Path("./data"), "path", "Where the SQLite ledger, KILL file and datasets live (Railway: /data)")
    log_level: str = _f("INFO", "text", "Logging level", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    kill_switch: str = _f("off", "text", "off | stop (no new entries) | sell_all (exit everything, then stop). "
                          "A DATA_DIR/KILL file containing the same words also works.",
                          choices=("off", "stop", "sell_all"))
    simulate_before_send: bool = _f(True, "bool", "Live: simulate the signed transaction via RPC before sending")
    quote_max_age_s: float = _f(15.0, "seconds", "Reject executing a quote older than this", lo=1, hi=120)

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
    network_fee_sol: float = _f(0.0003, "sol", "Paper model of network fee per swap (base + priority)", lo=0, hi=0.01)

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
                                lo=0, hi=100, lo_open=True)
    partial_tp_fraction: float = _f(0.5, "fraction", "Share of the position sold at the take-profit",
                                    lo=0, hi=1, lo_open=True)
    trail_pct: float = _f(0.15, "fraction", "Trailing stop from peak after the partial (0.15 = 15%)",
                          lo=0, hi=1, lo_open=True)
    stop_loss_pct: float = _f(0.18, "fraction", "Stop loss below entry (0.18 = -18%)", lo=0, hi=1, lo_open=True)
    max_hold_min: float = _f(120.0, "minutes", "Time stop", lo=0, lo_open=True)
    cooldown_min: float = _f(30.0, "minutes", "No re-entry into the same mint for this long after an exit", lo=0)
    candle_window_min: int = _f(180, "minutes", "How many 1m candles the engine fetches per watch evaluation",
                                lo=10, hi=1000)

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

    # ---- radar --------------------------------------------------------------
    radar_min_trade_usd: float = _f(300.0, "usd", "Only trades at least this big are scanned", lo=0)
    radar_window_min: float = _f(15.0, "minutes", "Look-back window for big sells", lo=1, hi=1440)
    radar_insider_sell_usd: float = _f(500.0, "usd", "Flag when creator/top-holder/insider sells reach this", lo=0)
    radar_big_sell_liq_pct: float = _f(10.0, "percent", "Flag when big sells in the window reach this PERCENT "
                                       "of pool liquidity", lo=0, hi=1000)
    radar_interval_s: float = _f(180.0, "seconds", "Radar re-scan interval for open positions", lo=10)

    # ---- judge (Jev) --------------------------------------------------------
    anthropic_api_key: Secret | None = _f(None, "secret", "Enables the AI judge", secret=True)
    judge_mode: str = _f("", "text", "off | advisory | required (default: required when ANTHROPIC_API_KEY is set, "
                         "else off)", choices=("off", "advisory", "required"))
    judge_model: str = _f("claude-opus-5-5", "text", "Anthropic model id for the judge")
    judge_effort: str = _f("low", "text", "output_config.effort", choices=("low", "medium", "high", "xhigh", "max"))
    judge_timeout_s: float = _f(20.0, "seconds", "Per-request timeout", lo=1, hi=600)
    judge_cache_min: float = _f(20.0, "minutes", "Reuse a verdict per mint for this long", lo=0)
    judge_max_daily_usd: float = _f(1.0, "usd", "Judge spend cap per UTC day; beyond it verdicts are 'no' "
                                    "(source=error)", lo=0)

    # ---- endpoints & keys ---------------------------------------------------
    jupiter_api_key: Secret | None = _f(None, "secret", "Optional Jupiter key (header x-api-key)", secret=True)
    jupiter_base_url: str = _f("", "url", "Default: https://api.jup.ag with a key, else https://lite-api.jup.ag")
    solana_rpc_url: str = _f("https://api.mainnet-beta.solana.com", "url",
                             "Solana JSON-RPC endpoint (a free Helius key is recommended)")
    bot_wallet_secret: Secret | None = _f(None, "secret", "Live only: base58 64-byte secret (Phantom export) or "
                                          "JSON byte array (solana-keygen)", secret=True)
    x_bearer_token: Secret | None = _f(None, "secret", "Optional X/Twitter token (unused by default)", secret=True)

    # ---- dashboard ----------------------------------------------------------
    port: int = _f(8080, "port", "Dashboard port (Railway sets PORT)", lo=1, hi=65535)
    dashboard_host: str = _f("0.0.0.0", "text", "Dashboard bind address")
    dashboard_token: Secret | None = _f(None, "secret", "If set, the dashboard requires ?token= or cookie",
                                        secret=True)

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
        object.__setattr__(self, "kill_switch", str(self.kill_switch).lower())
        object.__setattr__(self, "judge_mode", str(self.judge_mode).lower())
        object.__setattr__(self, "log_level", str(self.log_level).upper())
        problems = self._validate()
        if problems:
            raise ConfigError(problems)

    def _validate(self) -> list[str]:
        problems: list[str] = []
        for f in dataclasses.fields(self):
            meta = f.metadata
            value = getattr(self, f.name)
            env = f.name.upper()
            if meta.get("choices") and value not in meta["choices"]:
                problems.append(f"{env}={value!r} must be one of {', '.join(meta['choices'])}")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                lo, hi = meta.get("lo"), meta.get("hi")
                unit = meta.get("unit")
                hint = " (a FRACTION: 0.20 means 20%)" if unit == "fraction" else (
                    " (PERCENT: 3.0 means 3%)" if unit == "percent" else "")
                if lo is not None and (value <= lo if meta.get("lo_open") else value < lo):
                    op = ">" if meta.get("lo_open") else ">="
                    problems.append(f"{env}={value} must be {op} {lo}{hint}")
                if hi is not None and value > hi:
                    problems.append(f"{env}={value} must be <= {hi}{hint}")
        if self.trading_mode == "live":
            if self.live_confirm != LIVE_CONFIRM_PHRASE:
                problems.append(f"TRADING_MODE=live requires LIVE_CONFIRM={LIVE_CONFIRM_PHRASE} (exact)")
            if not self.bot_wallet_secret:
                problems.append("TRADING_MODE=live requires BOT_WALLET_SECRET (a dedicated bot wallet)")
        if self.judge_mode in ("advisory", "required") and not self.anthropic_api_key:
            problems.append(f"JUDGE_MODE={self.judge_mode} requires ANTHROPIC_API_KEY (or set JUDGE_MODE=off)")
        if self.min_position_usd > self.max_position_usd:
            problems.append("MIN_POSITION_USD must be <= MAX_POSITION_USD")
        if self.min_mcap_usd >= self.max_mcap_usd:
            problems.append("MIN_MCAP_USD must be < MAX_MCAP_USD")
        if self.min_age_min >= self.max_age_h * 60:
            problems.append("MIN_AGE_MIN must be shorter than MAX_AGE_H")
        for name in ("jupiter_base_url", "solana_rpc_url"):
            url = getattr(self, name)
            if not url.startswith(("http://", "https://")):
                problems.append(f"{name.upper()} must start with http:// or https://")
        return problems

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Build from a mapping of ENV_NAME -> string (default ``os.environ``).

        Unknown keys are ignored; blank values mean "use the default".
        Raises :class:`ConfigError` (all problems at once) on bad values.
        """
        env = os.environ if env is None else env
        kwargs: dict[str, Any] = {}
        problems: list[str] = []
        for f in dataclasses.fields(cls):
            raw = env.get(f.name.upper())
            if raw is None or str(raw).strip() == "":
                continue
            raw = str(raw).strip()
            try:
                kwargs[f.name] = _coerce(f, raw)
            except ValueError as exc:
                problems.append(f"{f.name.upper()}: {exc}")
        if problems:
            raise ConfigError(problems)
        return cls(**kwargs)

    def replace(self, **changes: Any) -> "Settings":
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
        return int(round(self.sol_reserve * 1_000_000_000))

    @property
    def network_fee_lamports(self) -> int:
        return int(round(self.network_fee_sol * 1_000_000_000))

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
        return out

    def public_dict(self) -> dict[str, Any]:
        """JSON-safe settings with NO secret values: secrets become ``<name>_set: bool``."""
        out: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            v = getattr(self, f.name)
            if f.metadata.get("secret"):
                out[f"{f.name}_set"] = bool(v)
            elif f.name == "live_confirm":
                out["live_confirmed"] = v == LIVE_CONFIRM_PHRASE
            elif f.name == "solana_rpc_url":
                out[f.name] = redact_url(v)
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
        if v != v or v in (float("inf"), float("-inf")):
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
