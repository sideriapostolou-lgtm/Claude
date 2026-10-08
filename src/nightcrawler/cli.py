"""Command line interface: the ``nightcrawler`` console script (owner: Integrator).

Subcommands (all accept ``--env-file`` and ``--log-level`` before the subcommand):

* ``run [--no-dashboard]`` - engine + dashboard (Railway start command).
* ``scan [--limit N] [--json]`` - one-shot crawl -> cocoon; prints candidates
  with pass/fail reasons. Never trades.
* ``backtest PATH [--sweep] [--grid JSON] [--json OUT]`` - PATH is a file or a
  directory of backtest JSON files.
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
:data:`EXIT_USAGE` 2 (argparse), :data:`EXIT_CONFIG` 3 (invalid settings),
:data:`EXIT_VERIFY_FAILED` 4 (receipt chain broken / audit drift),
:data:`EXIT_NOT_IMPLEMENTED` 5. Errors print one friendly line to stderr
(no tracebacks unless ``--log-level DEBUG``).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Callable, Sequence

from nightcrawler import __version__
from nightcrawler.config import ConfigError, Settings, load_settings

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

    s = sub.add_parser("backtest", help="replay 1m candles through the strategy")
    s.add_argument("path", help="backtest JSON file or a directory of them")
    s.add_argument("--sweep", action="store_true", help="grid search with a train/test split")
    s.add_argument("--grid", default=None, help='JSON param grid for --sweep, e.g. \'{"dip_pct":[0.5,0.6]}\'')
    s.add_argument("--json", dest="json_out", default=None, metavar="OUT", help="also write results JSON here")

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


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    """setup_logging -> build_engine -> DashboardServer (unless --no-dashboard) -> run_forever."""
    raise NotImplementedError


def cmd_scan(args: argparse.Namespace, settings: Settings) -> int:
    raise NotImplementedError


def cmd_backtest(args: argparse.Namespace, settings: Settings) -> int:
    raise NotImplementedError


def cmd_collect(args: argparse.Namespace, settings: Settings) -> int:
    raise NotImplementedError


def cmd_report(args: argparse.Namespace, settings: Settings) -> int:
    raise NotImplementedError


def cmd_receipts(args: argparse.Namespace, settings: Settings) -> int:
    raise NotImplementedError


def cmd_wallet(args: argparse.Namespace, settings: Settings) -> int:
    raise NotImplementedError


def cmd_sell_all(args: argparse.Namespace, settings: Settings) -> int:
    raise NotImplementedError


def cmd_reset_halt(args: argparse.Namespace, settings: Settings) -> int:
    raise NotImplementedError


def cmd_dashboard(args: argparse.Namespace, settings: Settings) -> int:
    raise NotImplementedError


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
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = load_settings(dotenv_path=args.env_file)
        if args.log_level:
            settings = settings.replace(log_level=args.log_level.upper())
    except ConfigError as exc:
        print(f"nightcrawler: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    handler = HANDLERS[args.command]
    try:
        return handler(args, settings)
    except NotImplementedError:
        print(f"nightcrawler: '{args.command}' is not implemented yet", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED
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
