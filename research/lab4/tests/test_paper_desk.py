"""Tests for research/lab4/paper_desk.py on a synthetic recorder output: long and short entries, fees, settlement
wins and losses, open positions, families, and the report."""

import csv
import json

import pandas as pd
import paper_desk as P

T0 = 1_791_500_000


def _write(us_dir, rows, settlements):
    (us_dir / "bbo").mkdir(parents=True)
    with (us_dir / "bbo" / "2026-10-09.csv").open("w", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "ts",
                "slug",
                "category",
                "best_bid",
                "best_ask",
                "last",
                "end_ts",
                "fee_coef",
            ],
        )
        w.writeheader()
        for r in rows:
            w.writerow(r)
    (us_dir / "settlements.json").write_text(json.dumps(settlements))


def _q(ts, slug, cat, bid, ask, end, coef=0.0695):
    return {
        "ts": ts,
        "slug": slug,
        "category": cat,
        "best_bid": bid,
        "best_ask": ask,
        "last": "",
        "end_ts": end,
        "fee_coef": coef,
    }


def test_shadow_trades_and_summary(tmp_path):
    end = T0 + 3600
    rows = [
        # w1: climate, long side reaches 0.97 at T0+600 (within H=1h), settles 1 -> win
        _q(T0, "w1", "climate", 0.90, 0.92, end),
        _q(T0 + 600, "w1", "climate", 0.96, 0.97, end),
        _q(T0 + 1200, "w1", "climate", 0.98, 0.99, end),
        # c1: crypto, SHORT side: bid 0.02 -> short price 0.98 at T0+300, settles 0 -> short wins
        _q(T0 + 300, "c1", "crypto", 0.02, 0.05, end),
        _q(T0 + 900, "c1", "crypto", 0.01, 0.03, end),
        # s1: sports, endDate weeks away; long 0.98 at T0+100, settled (closed_at T0+2000) at 0 -> loss plus fee
        _q(T0 + 100, "s1", "sports", 0.97, 0.98, end + 30 * 86400),
        # o1: open (no settlement yet)
        _q(T0 + 100, "o1", "crypto", 0.95, 0.96, end),
        # n1: never reaches theta
        _q(T0 + 100, "n1", "crypto", 0.50, 0.52, end),
        # e1: reaches theta but only outside the last hour (H=1) -> no trade for H=1, trade for H=6
        _q(end - 5 * 3600, "e1", "climate", 0.97, 0.98, end),
        _q(end - 1800, "e1", "climate", 0.40, 0.45, end),
    ]
    _write(
        tmp_path,
        rows,
        {
            "w1": {"settlement": 1},
            "c1": {"settlement": 0},
            "s1": {"settlement": 0, "closed_at": T0 + 2000},
            "e1": {"settlement": 1},
        },
    )
    books = P.load_books(tmp_path)
    assert len(books) == len(rows) and books["slug"].nunique() == 6
    tr = P.shadow_trades(books, P.load_settlements(tmp_path), 0.95, 1.0, "all")
    by = {r.slug: r for r in tr.itertuples(index=False)}
    assert set(by) == {"w1", "c1", "s1", "o1"}
    assert by["w1"].side == "long" and by["w1"].p_in == 0.97 and by["w1"].won is True
    assert abs(by["w1"].fee_usd - (20 / 0.97) * 0.0695 * 0.97 * 0.03) < 1e-9
    assert abs(by["w1"].pnl_usd - ((20 / 0.97) - by["w1"].fee_usd - 20)) < 1e-9
    assert (
        by["c1"].side == "short"
        and abs(by["c1"].p_in - 0.98) < 1e-9
        and by["c1"].won is True
    )
    assert by["s1"].won is False and by["s1"].pnl_usd < -20
    assert (
        by["o1"].settled is False
        and pd.isna(by["o1"].won)
        and pd.isna(by["o1"].pnl_usd)
    )
    s = P.summarize(tr)
    assert (
        s["n"] == 4
        and s["open"] == 1
        and s["settled"] == 3
        and abs(s["win_rate"] - 2 / 3) < 1e-9
    )
    assert (
        set(s["by_category"]) == {"climate", "crypto", "sports"}
        and s["worst_usd"] < -20
    )
    # families and the window
    assert set(
        P.shadow_trades(books, P.load_settlements(tmp_path), 0.95, 1.0, "sports")[
            "slug"
        ]
    ) == {"s1"}
    assert set(
        P.shadow_trades(books, P.load_settlements(tmp_path), 0.95, 1.0, "nonsports")[
            "slug"
        ]
    ) == {"w1", "c1", "o1"}
    assert "e1" in set(
        P.shadow_trades(books, P.load_settlements(tmp_path), 0.95, 6.0, "all")["slug"]
    )
    md, doc = P.report(tmp_path, cells=[(0.95, 1.0, "all"), (0.99, 1.0, "all")])
    assert (
        "paper money" in md
        and "| all | 0.95 | 1 | 4 | 1 | 3 |" in md
        and len(doc["cells"]) == 2
    )
    none = P.summarize(P.shadow_trades(books, {}, 0.999, 1.0, "all"))
    assert (
        none["n"] == 0 and none["settled"] == 0 and none["win_rate"] is None
    )  # nothing prints at 0.999
    unsettled = P.summarize(
        P.shadow_trades(books, {}, 0.95, 1.0, "all")
    )  # no settlements known: all open
    assert (
        unsettled["n"] >= 3
        and unsettled["settled"] == 0
        and unsettled["total_usd"] == 0.0
    )


def test_empty_recorder_dir(tmp_path):
    books = P.load_books(tmp_path)
    assert books.empty
    md, doc = P.report(tmp_path, cells=[(0.97, 1.0, "all")])
    assert doc["quotes"] == 0 and "| all | 0.97 | 1 | 0 | 0 | 0 |" in md
