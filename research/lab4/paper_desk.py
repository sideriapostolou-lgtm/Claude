"""Lab 4 shadow paper desk: the near-certain rule replayed on the US venue's own recorded books.

Input is what :mod:`recorder` writes (``$SCRATCH/lab4/us``): one best bid / offer per watched market per round
(``bbo/YYYY-MM-DD.csv``), the settlement price of every market that closed (``settlements.json``) and the market
metadata (``markets.json``). For each candidate cell (theta, H hours, family) the desk buys, ONCE per market, the
first time a side can be bought at or above ``theta`` within the last ``H`` hours before the market's end: the long
side at the best ask, or the short side at ``1 - best bid``. The ticket is $20 at the printed price (no depth,
no impact: a caveat the report states), the fee is the market's own ``feeCoefficient x shares x p x (1 - p)``
(Polymarket US taker schedule), and the position is held to settlement. Markets without a settlement yet are
OPEN positions; nothing is marked to market.

This is paper on recorded prices. It never places an order, never reads a key, and labels itself as such.

CLI::

    python research/lab4/paper_desk.py --report            # summary per cell (markdown to stdout)
    python research/lab4/paper_desk.py --report --write    # also research/lab4/US/paper_shadow.md
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

HERE = Path(__file__).resolve().parent
SCRATCH = Path(
    os.environ.get(
        "CLAUDE_SCRATCHPAD",
        "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad",
    )
)
US_DIR = Path(os.environ.get("LAB4_US_DATA", str(SCRATCH / "lab4" / "us")))
TICKET_USD = 20.0
US_TAKER = 0.0695
#: The candidate cells mirror PLAN §3 (theta x H); families: all, sports, nonsports.
CELLS: list[tuple[float, float, str]] = [
    (t, h, fam)
    for fam in ("all", "sports", "nonsports")
    for t in (0.95, 0.97, 0.99)
    for h in (1.0, 6.0, 24.0)
]
MAX_PRICE = 0.999


def load_books(us_dir: Path = US_DIR) -> pd.DataFrame:
    """Every recorded quote: ts, slug, category, best_bid, best_ask, last, end_ts, fee_coef (floats; NaN when
    a side was empty)."""
    files = sorted((us_dir / "bbo").glob("*.csv")) if (us_dir / "bbo").exists() else []
    frames = []
    for f in files:
        try:
            frames.append(pd.read_csv(f))
        except (pd.errors.EmptyDataError, OSError):
            continue
    if not frames:
        return pd.DataFrame(
            columns=[
                "ts",
                "slug",
                "category",
                "best_bid",
                "best_ask",
                "last",
                "end_ts",
                "fee_coef",
            ]
        )
    df = pd.concat(frames, ignore_index=True)
    for c in ("ts", "best_bid", "best_ask", "last", "end_ts", "fee_coef"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return (
        df.dropna(subset=["ts", "slug"])
        .sort_values(["slug", "ts"])
        .reset_index(drop=True)
    )


def load_settlements(us_dir: Path = US_DIR) -> dict[str, dict[str, Any]]:
    p = us_dir / "settlements.json"
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except ValueError:
        return {}


def _in_family(category: str, family: str) -> bool:
    if family == "all":
        return True
    if family == "sports":
        return category == "sports"
    return category != "sports"


def shadow_trades(
    books: pd.DataFrame,
    settlements: dict[str, dict[str, Any]],
    theta: float,
    hours: float,
    family: str = "all",
    ticket: float = TICKET_USD,
) -> pd.DataFrame:
    """One paper trade per market for a cell. Columns: slug, category, side ('long' | 'short'), t_in, p_in, shares,
    fee_usd, settled (bool), won (bool | None), pnl_usd (None while open), end_ts."""
    rows: list[dict[str, Any]] = []
    for slug, g in books.groupby("slug", sort=False):
        cat = str(g["category"].iloc[0])
        if not _in_family(cat, family):
            continue
        s_rec = settlements.get(slug)
        if (
            cat == "sports"
        ):  # a game's endDate is a deadline weeks out: its end is when it left the live list
            last_quote = float(g["ts"].iloc[-1])
            closed_at = (
                float(s_rec["closed_at"])
                if s_rec and s_rec.get("closed_at")
                else math.inf
            )
            end_ts = min(
                last_quote + 1.0, closed_at
            )  # the last quote itself is still eligible
        else:
            end_ts = float(g["end_ts"].iloc[-1])
        window = g[
            (g["ts"] >= end_ts - hours * 3600.0) & (g["ts"] < end_ts)
        ]  # never after the end (Amendment 3)
        if window.empty:
            continue
        long_ok = window["best_ask"] >= theta
        short_ok = (1.0 - window["best_bid"]) >= theta
        hit = window[long_ok.fillna(False) | short_ok.fillna(False)]
        if hit.empty:
            continue
        first = hit.iloc[0]
        if bool(first["best_ask"] >= theta) if pd.notna(first["best_ask"]) else False:
            side, p_in = "long", float(first["best_ask"])
        else:
            side, p_in = "short", float(1.0 - first["best_bid"])
        p_in = min(p_in, MAX_PRICE)
        if p_in <= 0:
            continue
        coef = float(first["fee_coef"]) if pd.notna(first["fee_coef"]) else US_TAKER
        shares = ticket / p_in
        fee = shares * coef * p_in * (1.0 - p_in)
        s = s_rec
        settled = s is not None and s.get("settlement") is not None
        won: bool | None = None
        pnl: float | None = None
        if settled:
            value = float(
                s["settlement"]
            )  # long pays `value` per share, short pays 1 - value
            payout = shares * (value if side == "long" else 1.0 - value)
            pnl = payout - fee - ticket
            won = pnl > 0
        rows.append(
            {
                "slug": slug,
                "category": cat,
                "side": side,
                "t_in": float(first["ts"]),
                "p_in": p_in,
                "shares": shares,
                "fee_usd": fee,
                "settled": settled,
                "won": won,
                "pnl_usd": pnl,
                "end_ts": end_ts,
            }
        )
    cols = [
        "slug",
        "category",
        "side",
        "t_in",
        "p_in",
        "shares",
        "fee_usd",
        "settled",
        "won",
        "pnl_usd",
        "end_ts",
    ]
    return pd.DataFrame(rows, columns=cols)


def summarize(trades: pd.DataFrame) -> dict[str, Any]:
    closed = trades[trades["settled"].astype(bool)] if len(trades) else trades
    out: dict[str, Any] = {
        "n": len(trades),
        "open": int(len(trades) - len(closed)),
        "settled": len(closed),
    }
    if len(closed) == 0:
        return {
            **out,
            "win_rate": None,
            "mean_p_in": None,
            "mean_net": None,
            "total_usd": 0.0,
            "worst_usd": None,
            "by_category": {},
        }
    pnl = closed["pnl_usd"].astype(float)
    out.update(
        {
            "win_rate": float(closed["won"].astype(bool).mean()),
            "mean_p_in": float(closed["p_in"].mean()),
            "mean_net": float((pnl / TICKET_USD).mean()),
            "total_usd": float(pnl.sum()),
            "worst_usd": float(pnl.min()),
            "by_category": {
                str(c): {
                    "settled": len(g),
                    "win_rate": float(g["won"].astype(bool).mean()),
                    "total_usd": float(g["pnl_usd"].astype(float).sum()),
                }
                for c, g in closed.groupby("category")
            },
        }
    )
    return out


def report(
    us_dir: Path = US_DIR, cells: list[tuple[float, float, str]] | None = None
) -> tuple[str, dict[str, Any]]:
    books = load_books(us_dir)
    settlements = load_settlements(us_dir)
    span = (
        (
            datetime.fromtimestamp(float(books["ts"].min()), UTC).strftime(
                "%Y-%m-%d %H:%M"
            ),
            datetime.fromtimestamp(float(books["ts"].max()), UTC).strftime(
                "%Y-%m-%d %H:%M"
            ),
        )
        if len(books)
        else ("-", "-")
    )
    doc: dict[str, Any] = {
        "utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "quotes": len(books),
        "markets": int(books["slug"].nunique()) if len(books) else 0,
        "settlements": len(settlements),
        "span": span,
        "cells": [],
    }
    lines = [
        "# Shadow paper desk on Polymarket US recorded books (paper money, pretend)",
        "",
        f"Generated {doc['utc']}. Quotes {doc['quotes']:,} over {doc['markets']:,} markets, {span[0]} .. {span[1]} UTC; "
        f"{doc['settlements']} settlements seen. Each cell buys once per market, $20 at the printed best price, "
        "pays the market's own taker fee, holds to settlement. No depth or impact is modelled; nothing was ordered.",
        "",
        "| family | theta | H (h) | trades | open | settled | win rate | mean price | net per $1 | total $ | worst $ |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for theta, hours, fam in cells or CELLS:
        tr = shadow_trades(books, settlements, theta, hours, fam)
        s = summarize(tr)
        doc["cells"].append(
            {"family": fam, "theta": theta, "hours": hours, "summary": s}
        )
        f = lambda v, nd=3: (
            "-" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))
        )
        lines.append(
            f"| {fam} | {theta:g} | {hours:g} | {s['n']} | {s['open']} | {s['settled']} | {f(s['win_rate'])} | "
            f"{f(s['mean_p_in'])} | {f(s['mean_net'], 4)} | {f(s['total_usd'], 2)} | {f(s['worst_usd'], 2)} |"
        )
    lines += [
        "",
        "Open = bought on paper, market not yet settled. This desk follows the lab's cells; it does not "
        "choose among them. A rule earns a real seat only by passing lab 4's TRAIN / VAL / TEST.",
    ]
    return "\n".join(lines) + "\n", doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Shadow paper desk on recorded Polymarket US books"
    )
    ap.add_argument("--report", action="store_true")
    ap.add_argument(
        "--write",
        action="store_true",
        help="also write research/lab4/US/paper_shadow.md and .json",
    )
    a = ap.parse_args(argv)
    md, doc = report()
    if a.write:
        (HERE / "US").mkdir(exist_ok=True)
        (HERE / "US" / "paper_shadow.md").write_text(md)
        (HERE / "US" / "paper_shadow.json").write_text(json.dumps(doc, indent=1) + "\n")
    if a.report or not a.write:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
