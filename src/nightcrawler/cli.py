"""Command line interface: the ``nightcrawler`` console script (owner: Integrator).

Subcommands (all accept ``--env-file`` and ``--log-level`` before the subcommand):

* ``run [--no-dashboard]`` - engine + dashboard (Railway start command).
* ``scan [--limit N] [--json] [--include-young]`` - one-shot crawl -> cocoon;
  prints candidates with pass/fail reasons. Never trades, writes nothing.
* ``backtest PATH [--sweep] [--grid JSON] [--json OUT] [--from T] [--until T]`` -
  PATH is a file or a directory of backtest JSON files; ``--from/--until``
  (ISO UTC like ``2026-10-04T22:00`` or epoch seconds) limit ENTRIES to a window.
* ``collect [--pools N] [--hours H] [--min-age-h H] [--out DIR]`` - dataset collector.
* ``report [--json]`` - P&L + audit reconcile + chain verification.
* ``receipts head|verify|export PATH`` - hash-chain tools.
* ``wallet new|show`` - ``new`` prints a fresh address + secret ONCE with a
  big warning and Phantom import help; ``show`` prints address + balances,
  never the secret.
* ``sell-all [--yes]`` - exit every open position now (asks unless ``--yes``).
* ``reset-halt [--yes]`` - clear a drawdown halt (writes a ``reset`` receipt).
* ``config [--json]`` - print public settings (no secrets).
* ``dashboard`` - serve the dashboard only (reads the ledger).

Exit codes: :data:`EXIT_OK` 0, :data:`EXIT_ERROR` 1 (runtime failure),
:data:`EXIT_USAGE` 2 (argparse), :data:`EXIT_CONFIG` 3 (invalid settings, live
mode refused, bad wallet secret), :data:`EXIT_VERIFY_FAILED` 4 (receipt chain
broken / audit drift), :data:`EXIT_NOT_IMPLEMENTED` 5. Errors print one
friendly line to stderr (no tracebacks unless ``--log-level DEBUG``).

SAFE MODE (RT-9): ``run`` with an INVALID configuration still refuses to start -
unless the ledger holds open LIVE positions, which would then sit without a
stop-loss. In that case every variable a problem names falls back to its default
(never TRADING_MODE, LIVE_CONFIRM, BOT_WALLET_SECRET or DATA_DIR; a live dashboard
without DASHBOARD_TOKEN gets a random token, i.e. it is locked) and, when that is a
valid live configuration, the bot runs EXITS-ONLY (``Engine.enter_safe_mode``: no
discovery, no entries; stop-losses, the kill switch and reconciliation work) with
a loud log line, a ``note`` receipt and kv ``engine.safe_mode`` for the dashboard.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import secrets
import signal
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from nightcrawler import __version__
from nightcrawler.config import ConfigError, Settings, load_settings, parse_dotenv

__all__ = [
    "EXIT_OK",
    "EXIT_ERROR",
    "EXIT_USAGE",
    "EXIT_CONFIG",
    "EXIT_VERIFY_FAILED",
    "EXIT_NOT_IMPLEMENTED",
    "build_parser",
    "main",
]

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_CONFIG = 3
EXIT_VERIFY_FAILED = 4
EXIT_NOT_IMPLEMENTED = 5

#: ``scan --include-young`` only checks nursery tokens at least this old (RugCheck needs a few minutes).
YOUNG_MIN_AGE_S = 600.0
#: ``sell-all`` treats the bot as running when its heartbeat is younger than this (seconds).
BOT_ALIVE_S = 60.0
#: ``backtest --sweep`` grid when ``--grid`` is not given.
DEFAULT_SWEEP_GRID: dict[str, list[float]] = {"dip_pct": [0.45, 0.55, 0.65], "take_profit_pct": [0.3, 0.4, 0.6]}
#: Settings the safe mode never replaces with a default: who trades, with which wallet, on which ledger.
SAFE_MODE_KEEP = frozenset({"TRADING_MODE", "LIVE_CONFIRM", "BOT_WALLET_SECRET", "DATA_DIR"})
SAFE_MODE_TOKEN = "DASHBOARD_TOKEN (random: dashboard locked)"
_ENV_NAME = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")


def build_parser() -> argparse.ArgumentParser:
    """The full argument grammar (stable contract for docs and tests)."""
    p = argparse.ArgumentParser(prog="nightcrawler",
                                description="Honest, provable Solana memecoin bot (paper mode by default).")
    p.add_argument("--version", action="version", version=f"nightcrawler {__version__}")
    p.add_argument("--env-file", default=".env", help="optional .env file (real env vars win); default .env")
    p.add_argument("--log-level", default=None, help="override LOG_LEVEL (DEBUG, INFO, WARNING, ERROR)")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    s = sub.add_parser("run", help="run the engine and the dashboard")
    s.add_argument("--no-dashboard", action="store_true", help="do not start the dashboard")

    s = sub.add_parser("scan", help="one-shot crawl + rug filter, no trading")
    s.add_argument("--limit", type=int, default=30, help="max candidates to check (default 30)")
    s.add_argument("--json", action="store_true", help="print JSON instead of a table")
    s.add_argument("--include-young", action="store_true",
                   help="also rug-check tokens still too young to trade (>= 10 min old), marked YOUNG")

    s = sub.add_parser("backtest", help="replay 1m candles through the strategy")
    s.add_argument("path", help="backtest JSON file or a directory of them")
    s.add_argument("--sweep", action="store_true", help="grid search with a train/test split")
    s.add_argument("--grid", default=None, help='JSON param grid for --sweep, e.g. \'{"dip_pct":[0.5,0.6]}\'')
    s.add_argument("--json", dest="json_out", default=None, metavar="OUT", help="also write results JSON here")
    s.add_argument("--from", dest="trade_from", default=None, metavar="TIME",
                   help="only enter at/after this time (ISO UTC, e.g. 2026-10-04T22:00, or epoch seconds)")
    s.add_argument("--until", dest="trade_until", default=None, metavar="TIME",
                   help="only enter before this time (ISO UTC or epoch seconds)")
    s.add_argument("--any-age", action="store_true",
                   help="allow entries at any token age up to MAX_AGE_H (a coin that keeps trending); by default "
                        "a coin is traded only within WATCHLIST_TTL_H of maturity, like the live bot")

    s = sub.add_parser("collect", help="download an unbiased multi-coin dataset")
    s.add_argument("--pools", type=int, default=100, help="number of pools (default 100)")
    s.add_argument("--hours", type=float, default=24.0, help="hours of 1m candles per pool (default 24)")
    s.add_argument("--min-age-h", type=float, default=24.0, help="only pools at least this old (default 24)")
    s.add_argument("--out", default=None, help="output dir (default DATA_DIR/dataset)")

    s = sub.add_parser("report", help="P&L, reconciliation and chain verification")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("receipts", help="hash-chain receipts")
    rs = s.add_subparsers(dest="receipts_cmd", metavar="ACTION")
    rs.required = True
    rs.add_parser("head", help="print the latest seq and hash")
    rs.add_parser("verify", help="re-walk the whole chain")
    r = rs.add_parser("export", help="write all receipts as JSONL")
    r.add_argument("path")

    s = sub.add_parser("wallet", help="bot wallet tools")
    ws = s.add_subparsers(dest="wallet_cmd", metavar="ACTION")
    ws.required = True
    ws.add_parser("new", help="generate a new bot wallet (prints the secret ONCE)")
    ws.add_parser("show", help="address and balances (never the secret)")

    s = sub.add_parser("sell-all", help="exit every open position now")
    s.add_argument("--yes", action="store_true", help="do not ask for confirmation")

    s = sub.add_parser("reset-halt", help="clear a drawdown halt")
    s.add_argument("--yes", action="store_true", help="do not ask for confirmation")

    s = sub.add_parser("config", help="print public settings (no secrets)")
    s.add_argument("--json", action="store_true")

    sub.add_parser("dashboard", help="serve the read-only dashboard only")
    return p


# ---------------------------------------------------------------------- helpers
class UserError(Exception):
    """A problem the user can fix; printed as one line with ``exit_code``."""

    def __init__(self, message: str, exit_code: int = EXIT_ERROR) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _setup_logging(args: argparse.Namespace, settings: Settings, quiet: bool = False) -> Any:
    """Redacting one-line logs. ``quiet`` commands log WARNING+ unless ``--log-level`` was given.
    A ``--json`` command's stdout carries data, so all its logs go to stderr."""
    from nightcrawler.logging_setup import setup_logging

    level = settings.log_level if (args.log_level or not quiet) else "WARNING"
    stream = sys.stderr if getattr(args, "json", False) is True else None
    return setup_logging(level, settings.secret_values(), stream=stream)


def _open_ledger(settings: Settings, must_exist: bool = True) -> Any:
    from nightcrawler.ledger import Ledger

    if must_exist and not settings.db_path.is_file():
        raise UserError(f"no ledger yet at {settings.db_path} (run the bot first, or check DATA_DIR)")
    return Ledger(settings.db_path)


def _confirm(args: argparse.Namespace, question: str, word: str) -> bool:
    if getattr(args, "yes", False):
        return True
    if not sys.stdin.isatty():
        raise UserError(f"refusing without confirmation; re-run with --yes ({question})", EXIT_USAGE)
    answer = input(f"{question} Type {word} to continue: ").strip()
    return answer == word


def _fmt_usd(value: float | None) -> str:
    if value is None:
        return "-"
    for unit, size in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(value) >= size:
            return f"${value / size:.1f}{unit}"
    return f"${value:,.0f}"


def _short(mint: str) -> str:
    return f"{mint[:4]}..{mint[-4:]}" if len(mint) > 10 else mint


def _parse_time(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise UserError(f"cannot read time {text!r}; use ISO UTC like 2026-10-04T22:00 or epoch seconds",
                        EXIT_USAGE) from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _wait_for_signal(stop: threading.Event) -> None:
    """Block until SIGTERM/SIGINT (main thread) or ``stop`` is set."""
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.set())
    while not stop.wait(1.0):
        pass


class _PaperBalances:
    """Read-only paper balances straight from the ledger kv (never initializes a wallet)."""

    mode = "paper"

    def __init__(self, ledger: Any) -> None:
        self.ledger = ledger

    def balances(self) -> Any:
        from nightcrawler.models import Balances

        tokens = {m: int(a) for m, a in (self.ledger.get_kv("paper.tokens") or {}).items()}
        return Balances(sol_lamports=int(self.ledger.get_kv("paper.sol_lamports") or 0), tokens=tokens)


class _LiveBalances:
    """Live wallet balances from Ultra holdings (read-only)."""

    mode = "live"

    def __init__(self, jupiter: Any, pubkey: str) -> None:
        self.jupiter = jupiter
        self.pubkey = pubkey

    def balances(self) -> Any:
        return self.jupiter.holdings(self.pubkey)


def _wallet_pubkey(settings: Settings, ledger: Any | None = None) -> str | None:
    if settings.bot_wallet_secret:
        from nightcrawler.broker.wallet import load_keypair

        return load_keypair(settings.bot_wallet_secret).pubkey()
    return ledger.get_kv("wallet.pubkey") if ledger is not None else None


def _make_clock() -> Any:
    """The wall clock (tests patch this)."""
    from nightcrawler.clock import RealClock

    return RealClock()


def _http(settings: Settings, clock: Any) -> Any:
    """The shared rate-limited HTTP client (tests patch this to inject a fake transport)."""
    from nightcrawler.http import HttpClient

    return HttpClient.from_settings(settings, clock=clock)


def _sources(settings: Settings, clock: Any | None = None) -> Any:
    from nightcrawler.sources import build_sources

    return build_sources(settings, _http(settings, clock if clock is not None else _make_clock()))


def _foreign_positions(ledger: Any, settings: Settings) -> list[dict[str, Any]]:
    """Live: open positions recorded for another wallet than the configured one (F3)."""
    from nightcrawler.engine import foreign_positions_of

    wallet = _wallet_pubkey(settings, ledger) if settings.is_live else None
    return foreign_positions_of(ledger, wallet) if wallet else []


# ---------------------------------------------------------------------- safe mode (RT-9)
def _merged_env(env_file: str | None) -> dict[str, str]:
    """What :func:`load_settings` reads: the ``.env`` file overlaid by the real environment."""
    merged: dict[str, str] = dict(parse_dotenv(env_file)) if env_file is not None else {}
    merged.update(os.environ)
    return merged


def _open_live_positions(env: Mapping[str, str]) -> tuple[int, Path]:
    """``(count, ledger path)`` of open LIVE positions in DATA_DIR's ledger (0 when there is none)."""
    from nightcrawler.ledger import Ledger

    data_dir = str(env.get("DATA_DIR") or "").strip() or str(Settings.__dataclass_fields__["data_dir"].default)
    path = Path(data_dir) / "nightcrawler.db"
    if not path.is_file():
        return 0, path
    with Ledger(path) as ledger:
        return len(ledger.open_positions(mode="live")), path


def safe_mode_settings(env: Mapping[str, str], error: ConfigError) -> tuple[Settings, list[str]] | None:
    """Settings for the exits-only safe mode, or None when they are not a valid LIVE configuration.

    Every variable a problem names falls back to its default, except :data:`SAFE_MODE_KEEP`; a live
    dashboard without ``DASHBOARD_TOKEN`` gets a random one (locked, but ``/healthz`` still answers).
    Returns ``(settings, variables that fell back)``.
    """
    fields = {row["env"] for row in Settings.describe()}
    env = dict(env)
    used: list[str] = []
    problems = list(error.problems)
    for _ in range(len(fields) + 1):
        changed = False
        for problem in problems:
            if "DASHBOARD_TOKEN" in problem and not str(env.get("DASHBOARD_TOKEN") or "").strip():
                env["DASHBOARD_TOKEN"] = secrets.token_urlsafe(32)
                used.append(SAFE_MODE_TOKEN)
                changed = True
                continue
            for name in _ENV_NAME.findall(problem):
                if name in fields and name not in SAFE_MODE_KEEP and str(env.get(name) or "").strip():
                    env.pop(name)
                    used.append(name)
                    changed = True
        if not changed:
            return None
        try:
            settings = Settings.from_env(env)
        except ConfigError as exc:
            problems = list(exc.problems)
            continue
        return (settings, list(dict.fromkeys(used))) if settings.is_live else None
    return None


def _safe_mode_fallback(args: argparse.Namespace, error: ConfigError) -> tuple[Settings, dict[str, Any]] | None:
    """``run`` with an invalid configuration: the exits-only safe mode when the ledger holds open LIVE
    positions and a valid live configuration remains (see module docstring), else None (refuse)."""
    env = _merged_env(args.env_file)
    try:
        count, path = _open_live_positions(env)
    except Exception as exc:  # an unreadable ledger: cannot tell, so refuse as before
        print(f"nightcrawler: cannot read the ledger to look for open live positions ({type(exc).__name__}: "
              f"{exc})", file=sys.stderr)
        return None
    if not count:
        return None
    found = safe_mode_settings(env, error)
    if found is None:
        print(f"nightcrawler: {count} open LIVE position(s) in {path} are NOT managed (no stop-loss) until the "
              "configuration below is fixed: it concerns the live setup itself, so not even an exits-only safe "
              "mode can run", file=sys.stderr)
        return None
    settings, used = found
    if args.log_level:
        settings = settings.replace(log_level=args.log_level.upper())
    print(f"nightcrawler: SAFE MODE - invalid configuration, but {count} open LIVE position(s) need their "
          f"stop-losses: running EXITS ONLY (no new buys) with defaults for {', '.join(used)}. Fix:\n  - "
          + "\n  - ".join(error.problems), file=sys.stderr)
    return settings, {"problems": list(error.problems), "defaults_used": used}


# ---------------------------------------------------------------------- handlers
def cmd_config(args: argparse.Namespace, settings: Settings) -> int:
    data = settings.public_dict()
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True, default=str))
    else:
        width = max(len(k) for k in data)
        for k in sorted(data):
            print(f"{k.upper():<{width}}  {data[k]}")
    return EXIT_OK


def cmd_run(args: argparse.Namespace, settings: Settings, safe_mode: dict[str, Any] | None = None) -> int:
    """setup_logging -> build_app -> DashboardServer (unless --no-dashboard) -> run_forever.
    ``safe_mode``: ``{"problems", "defaults_used"}`` -> exits-only (see module docstring)."""
    from nightcrawler.engine import build_app
    from nightcrawler.logging_setup import get_logger

    filt = _setup_logging(args, settings)
    log = get_logger("nightcrawler.cli")
    app = build_app(settings, redaction_filter=filt)
    if safe_mode is not None:
        app.engine.enter_safe_mode(safe_mode["problems"], safe_mode["defaults_used"])
    try:
        if not args.no_dashboard:
            try:
                app.dashboard.start()
            except OSError as exc:
                raise UserError(f"dashboard cannot listen on {settings.dashboard_host}:{settings.port}: {exc}") from exc
            log.info("dashboard_url http://%s:%d/ (token %s)", settings.dashboard_host, app.dashboard.bound_port,
                     "required" if settings.dashboard_token else "not set")
        app.engine.run_forever()
    finally:
        app.close()
    return EXIT_OK


def cmd_scan(args: argparse.Namespace, settings: Settings) -> int:
    from nightcrawler.cocoon import Cocoon
    from nightcrawler.crawler import Crawler

    _setup_logging(args, settings, quiet=True)
    clock = _make_clock()
    sources = _sources(settings, clock)
    crawler = Crawler(sources, settings, clock)
    cocoon = Cocoon(sources, settings, clock)
    feeds = "Jupiter, GeckoTerminal and DexScreener" if settings.discover_gt_new_pools else "Jupiter and DexScreener"
    print(f"Crawling {feeds} ...", file=sys.stderr)
    candidates = crawler.poll()
    rejected = crawler.last_rejected
    limit = max(0, args.limit)
    if candidates:
        print(f"Checking {min(limit, len(candidates))} of {len(candidates)} candidates with the rug filter "
              "(RugCheck allows ~1 call/s) ...", file=sys.stderr)
    young: list[Any] = []
    if getattr(args, "include_young", False):
        now = clock.now()
        aged = [c for c in crawler.nursery.values()
                if c.created_at is not None and now - c.created_at >= YOUNG_MIN_AGE_S]
        young = sorted(aged, key=lambda c: c.created_at or 0.0)[:max(0, limit - len(candidates))]
        for c in young:
            c.age_min = (now - c.created_at) / 60
    rows = [(c, cocoon.check(c)) for c in [*candidates[:limit], *young]]
    young_mints = {c.mint for c in young}
    reasons: dict[str, int] = {}
    for _c, reason in rejected:
        key = reason.split(":", 1)[0]
        reasons[key] = reasons.get(key, 0) + 1
    stats = crawler.stats()
    if args.json:
        print(json.dumps({
            "checked": [{"candidate": c.to_dict(), "safety": r.to_dict(), "young": c.mint in young_mints}
                        for c, r in rows],
            "not_checked": len(candidates) - len(rows),
            "prefilter_rejections": reasons,
            "nursery": stats["nursery"],
            "feed_errors": stats["feed_errors"],
        }, indent=2, sort_keys=True, default=str))
        return EXIT_OK
    passed = sum(1 for _c, r in rows if r.passed)
    print(f"\n{len(rows)} checked: {passed} PASS, {len(rows) - passed} FAIL"
          f" | prefilter rejected {len(rejected)} | {stats['nursery']} too young (waiting in the nursery)")
    if reasons:
        print("prefilter: " + ", ".join(f"{n} {k}" for k, n in sorted(reasons.items(), key=lambda kv: -kv[1])))
    if stats["feed_errors"]:
        print("feed errors: " + ", ".join(f"{k} x{n}" for k, n in stats["feed_errors"].items()))
    if rows:
        print(f"\n{'RESULT':<6} {'SYMBOL':<12} {'AGE':>6} {'MCAP':>8} {'LIQ':>8}  {'MINT':<10}  WHY")
    for c, r in rows:
        age = f"{c.age_min / 60:.1f}h" if c.age_min is not None else "-"
        why = "; ".join(r.hard_fail_reasons[:2]) if not r.passed else (
            f"{len(r.warnings)} warning(s): " + "; ".join(r.warnings[:2]) if r.warnings else "clean")
        result = ("PASS" if r.passed else "FAIL") + ("*" if c.mint in young_mints else "")
        print(f"{result:<6} {c.symbol[:12]:<12} {age:>6} {_fmt_usd(c.mcap_usd):>8} "
              f"{_fmt_usd(c.liquidity_usd):>8}  {_short(c.mint):<10}  {why}")
    if young:
        print(f"\n* = YOUNG: younger than MIN_AGE_MIN ({settings.min_age_min:g} min), checked for information "
              "only; the bot would not trade it yet (and market-cap/liquidity filters were not applied).")
    if not rows:
        print("\nNo candidate passed the cheap prefilter right now. Brand-new tokens must be at least "
              f"{settings.min_age_min:g} min old; the running bot re-checks them when they mature "
              "(try --include-young to rug-check the young ones anyway).")
    return EXIT_OK


def cmd_backtest(args: argparse.Namespace, settings: Settings) -> int:
    from nightcrawler.backtest import Backtester, aggregate_metrics, format_table, load_series

    _setup_logging(args, settings, quiet=True)
    path = Path(args.path)
    if path.is_dir():
        files = sorted(p for p in path.glob("*.json") if p.is_file())
    elif path.is_file():
        files = [path]
    else:
        raise UserError(f"no such file or folder: {path}")
    if not files:
        raise UserError(f"no backtest *.json files in {path}")
    bt = Backtester.from_settings(settings, any_age=bool(getattr(args, "any_age", False)))
    out: dict[str, Any]
    if args.sweep:
        try:
            grid = json.loads(args.grid) if args.grid else DEFAULT_SWEEP_GRID
        except json.JSONDecodeError as exc:
            raise UserError(f"--grid is not valid JSON: {exc}", EXIT_USAGE) from None
        try:
            result = bt.sweep(grid, files)
        except ValueError as exc:
            raise UserError(f"sweep: {exc}", EXIT_USAGE) from None
        names = list(grid)
        print(f"train: {', '.join(result.train_coins)} | test (out-of-sample): {', '.join(result.test_coins)}")
        header = (" ".join(f"{n:>16}" for n in names)
                  + f" {'train ret%':>11} {'train n':>8} {'TEST ret%':>10} {'test n':>7}")
        print(header + "\n" + "-" * len(header))
        for row in result.rows:
            cells = " ".join(f"{row[n]!s:>16}" for n in names)
            print(f"{cells} {row['train']['total_return_pct']:>11.2f} {row['train']['trades']:>8} "
                  f"{row['test']['total_return_pct']:>10.2f} {row['test']['trades']:>7}")
        print(f"best on TRAIN: {result.best_params} (judge it by its TEST column, not its train column)")
        out = dataclasses.asdict(result)
    else:
        start, until = _parse_time(args.trade_from), _parse_time(args.trade_until)
        if start is None and until is None:
            results, agg = bt.run_many(files)
        else:
            series, skipped = [], 0
            for f in files:
                try:
                    series.append(load_series(f))
                except ValueError:
                    skipped += 1
            results = [bt.run(c, m, trade_from=start, trade_until=until) for c, m in series]
            agg = aggregate_metrics(results, bt.start_usd, skipped)
        print(format_table(results, agg))
        cm = bt.cost_model
        print(f"\nstart ${bt.start_usd:,.0f} per series | costs per side: {cm.fee_bps_per_side:g} bps fee + "
              f"{cm.impact_bps_per_1k_usd:g} bps impact per $1K + ${cm.network_fee_usd_per_side:g} network")
        print("Not modelled (each makes this look BETTER than live): rug filter, radar, judge, liquidity floor, "
              "5m buy/sell ratio.")
        out = {"results": [r.to_dict() for r in results], "aggregate": agg,
               "cost_model": dataclasses.asdict(cm), "start_usd": bt.start_usd,
               "window": {"from": start, "until": until}}
    if args.json_out:
        target = Path(args.json_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(out, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        print(f"wrote {target}")
    return EXIT_OK


def cmd_collect(args: argparse.Namespace, settings: Settings) -> int:
    from nightcrawler.dataset import collect
    from nightcrawler.sources.geckoterminal import GeckoTerminalClient

    _setup_logging(args, settings)
    clock = _make_clock()
    gecko = GeckoTerminalClient(_http(settings, clock))
    out = Path(args.out) if args.out else settings.dataset_dir

    def progress(done: int, total: int, pool: str) -> None:
        print(f"[{done}/{total}] {pool}", file=sys.stderr)

    try:
        summary = collect(gecko, out, n_pools=args.pools, min_age_h=args.min_age_h, hours=args.hours, clock=clock,
                          progress=progress)
    except RuntimeError as exc:
        raise UserError(str(exc)) from exc
    print(f"census: {summary.considered} pools ({summary.census_added} new) in {summary.out_dir}")
    print(f"downloaded {len(summary.written)} ({summary.empty} never traded), already had "
          f"{summary.skipped_existing}, too young {summary.skipped_young}, failed {len(summary.failed)}")
    if not summary.written and summary.skipped_young:
        print(f"Nothing is {args.min_age_h:g} h old yet: the first runs only build the census. "
              "Run `nightcrawler collect` again later (e.g. hourly); pools are downloaded once old enough.")
    return EXIT_OK


def cmd_report(args: argparse.Namespace, settings: Settings) -> int:
    from nightcrawler.audit import Auditor

    _setup_logging(args, settings, quiet=True)
    ledger = _open_ledger(settings)
    try:
        balances: Any = None
        if settings.is_live:
            pubkey = _wallet_pubkey(settings, ledger)
            if pubkey:
                balances = _LiveBalances(_sources(settings).jupiter, pubkey)
        elif ledger.get_kv("paper.sol_lamports") is not None:
            balances = _PaperBalances(ledger)
        report = Auditor(ledger, balances, mode=settings.trading_mode).reconcile()
        foreign = _foreign_positions(ledger, settings)
        if args.json:
            print(json.dumps({**dataclasses.asdict(report), "foreign_positions": foreign}, indent=2, sort_keys=True,
                             default=str))
        else:
            print(Auditor.format_text(report))
            if foreign:
                print(f"\nFOREIGN live positions ({len(foreign)}): recorded for another wallet, so THIS bot never "
                      "sells or counts them - run it with that wallet to close them:")
                for p in foreign:
                    print(f"  {p['id']}  {p['symbol'] or _short(p['mint'])}  {p['token_amount']} base units  "
                          f"wallet {p['wallet']}")
    finally:
        ledger.close()
    return EXIT_OK if report.ok else EXIT_VERIFY_FAILED


def cmd_receipts(args: argparse.Namespace, settings: Settings) -> int:
    _setup_logging(args, settings, quiet=True)
    ledger = _open_ledger(settings)
    try:
        if args.receipts_cmd == "head":
            seq, head = ledger.head()
            print(f"seq  {seq}\nhash {head}")
            return EXIT_OK
        if args.receipts_cmd == "verify":
            ok, bad = ledger.verify_chain()
            seq, head = ledger.head()
            if ok:
                print(f"OK: all {seq} receipts verify; head {head}")
                return EXIT_OK
            print(f"BROKEN: the receipt chain fails at seq {bad} (of {seq}). Someone or something edited the "
                  "ledger; do not trust results after that point.")
            return EXIT_VERIFY_FAILED
        count = ledger.export_receipts(args.path)
        seq, head = ledger.head()
        print(f"wrote {count} receipts to {args.path} (head seq {seq} {head})")
        return EXIT_OK
    finally:
        ledger.close()


_WALLET_WARNING = """
##########################################################################
#  NEW BOT WALLET - THE SECRET BELOW IS SHOWN ONCE AND NEVER AGAIN         #
#  Anyone who sees it can take every coin in this wallet.                 #
#  * Copy it into a password manager or straight into the Railway        #
#    variable BOT_WALLET_SECRET. Do not screenshot it, do not chat it.    #
#  * Use this wallet ONLY for the bot. Never your main wallet.            #
#  * Fund it with no more than you can afford to lose (about $100).       #
##########################################################################
"""


def cmd_wallet(args: argparse.Namespace, settings: Settings) -> int:
    from nightcrawler.broker.wallet import PHANTOM_IMPORT_HELP, generate_new
    from nightcrawler.models import SOL_MINT, lamports_to_sol

    _setup_logging(args, settings, quiet=True)
    if args.wallet_cmd == "new":
        wallet, secret = generate_new()
        print(_WALLET_WARNING)
        print(f"address (public, safe to share): {wallet.pubkey()}")
        print(f"secret  (PRIVATE, shown once):   {secret}")
        print(f"\n{PHANTOM_IMPORT_HELP}")
        return EXIT_OK
    pubkey = _wallet_pubkey(settings)
    if not pubkey:
        raise UserError("BOT_WALLET_SECRET is not set (paper mode needs no wallet; see docs/GOING_LIVE.md)")
    print(f"address: {pubkey}")
    jupiter = _sources(settings).jupiter
    try:
        holdings = jupiter.holdings(pubkey)
        sol_usd = jupiter.sol_price_usd()
    except Exception as exc:
        raise UserError(f"balances unavailable right now ({type(exc).__name__}: {exc})") from exc
    sol = lamports_to_sol(holdings.sol_lamports)
    print(f"SOL:     {sol:.6f} (~${sol * sol_usd:,.2f} at ${sol_usd:,.2f}/SOL)")
    tokens = {m: a for m, a in holdings.tokens.items() if a > 0 and m != SOL_MINT}
    if tokens:
        prices = jupiter.prices(list(tokens))
        print(f"tokens:  {len(tokens)}")
        for mint, amount in sorted(tokens.items()):
            price = prices.get(mint)
            print(f"  {mint}  {amount} base units" + (f"  (price ${price:.10g})" if price else ""))
    return EXIT_OK


def cmd_sell_all(args: argparse.Namespace, settings: Settings) -> int:
    from nightcrawler.engine import build_app

    mode = "REAL MONEY (live)" if settings.is_live else "paper"
    if not _confirm(args, f"Sell every open {mode} position now?", "SELL"):
        print("cancelled")
        return EXIT_ERROR
    filt = _setup_logging(args, settings)
    app = build_app(settings, redaction_filter=filt)
    try:
        heartbeat = app.ledger.get_kv("engine.heartbeat")
        status = app.ledger.get_kv("engine.status")
        age = app.clock.now() - heartbeat if isinstance(heartbeat, (int, float)) else None
        if age is not None and age < BOT_ALIVE_S and isinstance(status, dict) and status.get("state") == "running":
            # Two processes trading one ledger race each other; let the ONE running bot sell.
            settings.kill_file.write_text("sell_all\n", encoding="utf-8")
            print(f"The bot is running (heartbeat {age:.0f}s ago): wrote 'sell_all' to {settings.kill_file}. It "
                  "sells every open position within seconds and then buys nothing more. Watch the dashboard; "
                  "to resume trading later, write 'off' into that file or delete it.")
            return EXIT_OK
        app.engine._restore_state()  # unresolved / in-flight live swaps of a stopped bot are respected
        foreign = app.engine.foreign_positions()
        if foreign:
            print(f"{len(foreign)} live position(s) belong to another wallet ("
                  + ", ".join(sorted({p['wallet'] for p in foreign})) + "): not sold by this wallet")
        before = app.engine._open_positions()
        if not before:
            print("no open positions")
            return EXIT_OK
        fills = app.engine.sell_all("manual")
        for f in fills:
            if f.sol_lamports == 0 and f.request_id is None and f.signature is None:  # F10 write-off
                print(f"wrote off {f.symbol or f.mint}: {f.token_amount} base units the wallet did not hold")
            else:
                print(f"sold {f.symbol or f.mint}: {f.token_amount} base units for {f.sol_lamports / 1e9:.6f} SOL")
        left = app.engine._open_positions()
    finally:
        app.close()
    if settings.kill_switch == "off":
        print("Note: a running bot may buy again. To stop new buys set KILL_SWITCH=stop (Railway variable) "
              f"or write 'stop' into {settings.kill_file}.")
    if left:
        print(f"{len(left)} position(s) could NOT be sold now (see the log); try again in a minute.",
              file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def cmd_reset_halt(args: argparse.Namespace, settings: Settings) -> int:
    from nightcrawler.risk import RiskManager

    _setup_logging(args, settings, quiet=True)
    ledger = _open_ledger(settings)
    try:
        risk = RiskManager(settings, ledger, _make_clock())
        halted, reason = risk.is_halted()
        if not halted:
            print("not halted; nothing to do")
            return EXIT_OK
        print(f"halted: {reason}")
        if not _confirm(args, "Clear the halt and restart the equity peak from now?", "RESET"):
            print("cancelled")
            return EXIT_ERROR
        risk.reset_halt("manual reset via CLI")
        seq, head = ledger.head()
        print(f"halt cleared (reset receipt seq {seq}, head {head})")
        return EXIT_OK
    finally:
        ledger.close()


def cmd_dashboard(args: argparse.Namespace, settings: Settings) -> int:
    from nightcrawler.dashboard import DashboardServer, build_state
    from nightcrawler.teamroom import TeamRoom

    _setup_logging(args, settings)
    settings.ensure_data_dir()
    ledger = _open_ledger(settings, must_exist=False)
    clock = _make_clock()
    cache: dict[str, Any] = {}
    server = DashboardServer(settings, lambda: build_state(ledger, settings, clock.now(), cache),
                             team=TeamRoom(settings, ledger, clock))
    try:
        server.start()
        print(f"dashboard on http://{settings.dashboard_host}:{server.bound_port}/ (Ctrl+C to stop)", file=sys.stderr)
        _wait_for_signal(threading.Event())
    finally:
        server.stop()
        ledger.close()
    return EXIT_OK


HANDLERS: dict[str, Callable[[argparse.Namespace, Settings], int]] = {
    "run": cmd_run,
    "scan": cmd_scan,
    "backtest": cmd_backtest,
    "collect": cmd_collect,
    "report": cmd_report,
    "receipts": cmd_receipts,
    "wallet": cmd_wallet,
    "sell-all": cmd_sell_all,
    "reset-halt": cmd_reset_halt,
    "config": cmd_config,
    "dashboard": cmd_dashboard,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv``, load settings, dispatch. Returns an exit code (never raises SystemExit
    except from argparse's own ``--help``/usage errors)."""
    from nightcrawler.broker.base import LiveNotAllowed
    from nightcrawler.broker.wallet import WalletError
    from nightcrawler.ledger import LedgerError

    parser = build_parser()
    args = parser.parse_args(argv)
    safe_mode: dict[str, Any] | None = None
    try:
        settings = load_settings(dotenv_path=args.env_file)
        if args.log_level:
            settings = settings.replace(log_level=args.log_level.upper())
    except ConfigError as exc:
        fallback = _safe_mode_fallback(args, exc) if args.command == "run" else None
        if fallback is None:
            print(f"nightcrawler: {exc}", file=sys.stderr)
            return EXIT_CONFIG
        settings, safe_mode = fallback
    handler = HANDLERS[args.command]
    try:
        if safe_mode is not None:
            return cmd_run(args, settings, safe_mode=safe_mode)
        return handler(args, settings)
    except NotImplementedError:
        print(f"nightcrawler: '{args.command}' is not implemented yet", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED
    except UserError as exc:
        print(f"nightcrawler: {exc}", file=sys.stderr)
        return exc.exit_code
    except (LiveNotAllowed, WalletError) as exc:
        print(f"nightcrawler: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except LedgerError as exc:
        print(f"nightcrawler: ledger problem: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("nightcrawler: interrupted", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # friendly one-liner; details only at DEBUG
        if settings.log_level == "DEBUG":
            raise
        print(f"nightcrawler: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

