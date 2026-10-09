"""PARITY HARNESS: the live tracker (swap-api trades -> nightcrawler.flow) against the wave-2 lab's own rows.

Fixture ``tests/fixtures/flow/parity.json.gz`` (``tests/fixtures/flow/README.md``): for 6 census coins, the
recorded swap-api trades of their first 2 minutes (as served, complete windows) and, for the SAME coins, the lab's
rows: CryptoHouse raw trades (``raw.sql``, the B1 selection with full fields, untruncated), ``graduates.parquet``,
``b2_coins.parquet`` and the ``b2_bars.parquet`` minutes that end inside the recorded window.

What must match, and how exactly:

* per trade (B1 columns): chain order, side, venue, tokens EXACT, wallet exact except pooled accounts (the chain
  names the pool, swap-api the signer); pre-trade reserves EXACT (curve virtual reserves within 1 lamport; PumpSwap
  y exact, x + v to 1e-9); user-side SOL exact on PumpSwap sells, ``buy`` instructions and fee-free buys, within
  0.1 % on ``buy_exact_quote_in`` (creator-fee tier estimated), within 2 lamports on the curve (1.25 % fee);
* B2 minute bars: counts, tokens, prices and reserves exact (float32 storage), SOL sums within 0.1 %;
* the early window ``w120_*`` and its top-10 buyers, AGENT wallet / known_at / first offset / slices, per-minute
  AGENT SOL;
* curve.sql launch / curve-life / creator / bundle / sniper / completer / first-20 columns (``graduates``).
"""

from __future__ import annotations

import gzip
import json
import math
from pathlib import Path
from typing import Any

import pytest

from nightcrawler.flow import (
    LAMPORTS,
    POOLED_ACCOUNTS,
    VENUE_AMM,
    VENUE_CURVE,
    FlowRow,
    FlowSnapshot,
    FlowTracker,
    NotYetKnown,
)
from nightcrawler.sources.pumpfun_trades import parse_trade

FIXTURE = Path(__file__).parent / "fixtures" / "flow" / "parity.json.gz"
CH_FIELDS = ("slot", "tx_idx", "pix", "ix", "ts", "venue", "is_buy", "user", "usol", "tok", "x0", "y0", "x1", "y1",
             "qamt", "lp_fee", "pfee", "cfee", "ix_name", "virt")
F32 = 2e-6            # float32 storage in B2
SOL_TOL = 1e-5        # SOL sums: per-fee ceil rounding (a lamport per trade), float32 storage


def _load() -> dict[str, Any]:
    with gzip.open(FIXTURE, "rt") as fh:
        return json.load(fh)


DOC = _load()
COINS = {c["mint"]: c for c in DOC["coins"]}
MINTS = list(COINS)
INSTANT = [m for m in MINTS if COINS[m]["graduate"]["grad_delay_s"] == 0]
MAYHEM = "5ZbEkbmNTaBiRWPcwpsgHvz7GpuVBWcm4DsmGZmTpump"       # Mayhem: SOL leaves the curve outside trades
SLOW = "3siP5yjvKkhcEFhN9QYpeNBuDhKfR7UVnJgSLqYspump"         # graduated 226 s after creation
SANE = [m for m in MINTS if m != MAYHEM]


def tracker_for(coin: dict[str, Any], *, with_g: bool = False, with_c_slot: bool = False) -> FlowTracker:
    gr = coin["graduate"]
    c_ts = coin["created_ms"] // 1000
    tr = FlowTracker(coin["mint"], created_ts=c_ts, creator=gr["creator"],
                     c_slot=gr["c_slot"] if with_c_slot else None, g_ts=gr["g_ts"] if with_g else None,
                     history_from=c_ts)
    trades = [parse_trade(r) for r in coin["swap"]]
    assert all(t is not None for t in trades)
    tr.ingest(reversed([t for t in trades if t is not None]))   # served newest first; ingest order must not matter
    tr.mark_complete(c_ts + 120)
    return tr


def snap_at_window_end(tr: FlowTracker, coin: dict[str, Any]) -> FlowSnapshot:
    """tau = creation + 120 s: the recorded window holds every trade with ts < c + 120 (none at c + 120 in these
    coins, checked against the lab's inclusive launch window)."""
    c_ts = coin["created_ms"] // 1000
    return tr.as_of(c_ts + 140)


def ch_rows(coin: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(zip(CH_FIELDS, r, strict=True)) for r in coin["ch_trades"]]


def matched(coin: dict[str, Any], rows: list[FlowRow]) -> list[tuple[FlowRow, dict[str, Any]]]:
    ch = ch_rows(coin)
    assert len(ch) == len(rows), "same trade count in both sources"
    return list(zip(rows, ch, strict=True))


def rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-12)


# =========================================================================== per-trade (B1 rows)


@pytest.mark.parametrize("mint", MINTS)
def test_trades_match_the_chain_one_for_one(mint: str) -> None:
    coin = COINS[mint]
    tr = tracker_for(coin)
    for r, c in matched(coin, tr.rows()):
        t = r.trade
        assert (t.slot, t.ts, int(t.is_buy), t.venue, t.tok_raw) == (c["slot"], c["ts"], c["is_buy"], c["venue"],
                                                                     c["tok"])
        # the chain's event `user` of a pooled account is the pool; swap-api names the real signer (AUDIT 3.6)
        assert t.wallet == c["user"] or c["user"] in POOLED_ACCOUNTS


@pytest.mark.parametrize("mint", SANE)
def test_reserves_before_each_trade_are_rebuilt_exactly(mint: str) -> None:
    coin = COINS[mint]
    tr = tracker_for(coin)
    n_amm = 0
    for r, c in matched(coin, tr.rows()):
        if r.trade.venue == VENUE_CURVE:
            assert r.y0 == c["y0"]
            assert r.x0 is not None and abs(r.x0 - c["x0"]) <= 1.0          # lamports
        else:
            n_amm += 1
            assert r.y0 == c["y0"]
            if c["virt"]:                                                   # raw.sql carries v on buys only
                assert r.X0 is not None and rel(r.X0, c["x0"] + c["virt"]) < 1e-9
    assert tr.chain_breaks == 0
    if mint != SLOW:
        assert n_amm > 0


def test_a_mayhem_curve_breaks_the_reserve_chain_and_is_flagged() -> None:
    """Mayhem curves move SOL outside TradeEvents (README caveat 3): the lab excludes them; live, the broken chain
    is visible (chain_breaks > 0), so an integrator can skip the coin even without the census flag."""
    assert tracker_for(COINS[MAYHEM]).chain_breaks > 0


@pytest.mark.parametrize("mint", MINTS)
def test_user_side_sol_follows_the_lab_convention(mint: str) -> None:
    coin = COINS[mint]
    tr = tracker_for(coin)
    for r, c in matched(coin, tr.rows()):
        if r.trade.venue == VENUE_AMM:
            if not c["is_buy"] or c["ix_name"] == "buy" or c["pfee"] + c["cfee"] + c["lp_fee"] == 0:
                assert r.usol == c["usol"], (r.kind, c["ix_name"])
                assert r.usol_exact
            else:
                assert r.kind == "exact_in"
                assert abs(r.usol - c["usol"]) <= 2                      # each fee is ceil(net * bps / 1e4)
        else:
            fee = c["pfee"] + c["cfee"]
            if fee == 0 or abs(fee - c["qamt"] * 0.0125) <= 2:
                assert abs(r.usol - c["usol"]) <= 2
            else:  # an odd fee on the curve (not 95 + 30 bps): the documented 1.25 % estimate
                assert rel(r.usol, c["usol"]) < 2e-2


@pytest.mark.parametrize("mint", MINTS)
def test_buy_instruction_kind_is_read_from_the_reserve_chain(mint: str) -> None:
    coin = COINS[mint]
    tr = tracker_for(coin)
    for r, c in matched(coin, tr.rows()):
        if r.trade.venue != VENUE_AMM or not c["is_buy"]:
            continue
        free = c["pfee"] + c["cfee"] + c["lp_fee"] == 0
        want = "fee_free" if free else ("buy" if c["ix_name"] == "buy" else "exact_in")
        assert r.kind == want


@pytest.mark.parametrize("mint", MINTS)
def test_ch_minute_totals_match_over_all_trades(mint: str) -> None:
    """raw.sql per-minute totals (never truncated): (minute since creation, venue, n, n_buys, buy, sell, swap-api)."""
    coin = COINS[mint]
    tr = tracker_for(coin)
    c_ts = coin["created_ms"] // 1000
    agg: dict[tuple[int, int], list[float]] = {}
    for r in tr.rows():
        k = ((r.trade.ts - c_ts) // 60, r.trade.venue)
        a = agg.setdefault(k, [0, 0, 0.0, 0.0, 0.0])
        a[0] += 1
        a[1] += int(r.trade.is_buy)
        a[2 if r.trade.is_buy else 3] += r.usol
        a[4] += r.trade.amount_sol * LAMPORTS
    for m, venue, n, nb, bs, ss, api in coin["ch_minutes"]:
        a = agg[(m, venue)]
        assert (a[0], a[1]) == (n, nb)
        assert abs(a[4] - api) <= n                     # swap-api amountSol is exactly validate.net_swap_sol
        assert rel(a[2], bs) < SOL_TOL if bs else a[2] == 0
        assert rel(a[3], ss) < SOL_TOL if ss else a[3] == 0


# =========================================================================== B2 minute bars


@pytest.mark.parametrize("mint", [m for m in MINTS if COINS[m]["b2_bars"]])
def test_minute_bars_match_b2(mint: str) -> None:
    coin = COINS[mint]
    snap = snap_at_window_end(tracker_for(coin), coin)
    bars = snap.bars
    by_ts = {ts: i for i, ts in enumerate(bars.minute_ts)}
    for b in coin["b2_bars"]:
        i = by_ts[b["minute_ts"]]
        assert bars.traded[i] == 1.0
        for f in ("n_buys", "n_sells", "n_dust", "n_buyers", "n_sellers"):
            assert getattr(bars, f)[i] == b[f], f
        for f in ("buy_tok", "sell_tok"):
            assert rel(getattr(bars, f)[i], b[f]) < F32 if b[f] else getattr(bars, f)[i] == 0, f
        for f in ("buy_sol", "sell_sol", "top5_buy_sol"):
            assert rel(getattr(bars, f)[i], b[f]) < SOL_TOL if b[f] else getattr(bars, f)[i] == 0, f
        o, c = bars.o[i], bars.c[i]
        assert rel(o, b["open"]) < 1e-9
        assert rel(c, b["close"]) < 1e-9
        assert rel(bars.h[i], max(b["high"], o, c)) < 1e-9        # common._dense: h = max(h, o, c)
        assert rel(bars.l[i], min(b["low"], o, c)) < 1e-9         # l = min(l, o, c)
        assert rel(bars.y[i], b["y_close"]) < F32
        assert rel(bars.X[i], b["close"] * b["y_close"]) < F32    # X = close * y (pricing reserve)
        if snap.agent_detected:
            assert abs(bars.agent_buy_sol[i] - (b["agent_buy_sol"] or 0.0)) < 1e-6


# =========================================================================== early window, AGENT


@pytest.mark.parametrize("mint", INSTANT)
def test_w120_window_matches_b2_coins(mint: str) -> None:
    """g = c for instant graduates, so [g, g + 120) is exactly the recorded window. b2_coins counts and top lists
    are exact only when the window sat inside one chain hour (``w_exact``); its sums always are."""
    coin = COINS[mint]
    lab = coin["b2_coin"]
    snap = snap_at_window_end(tracker_for(coin), coin)
    assert snap.g == coin["graduate"]["g_ts"]                     # inferred from the chain (no g given)
    assert rel(snap["w120_buy_sol"], lab["w120_buy_sol"]) < SOL_TOL
    assert rel(snap["w120_sell_sol"], lab["w120_sell_sol"]) < SOL_TOL
    if not lab["w_exact"]:
        assert snap["w120_n_buyers"] >= lab["w120_n_buyers"]      # the lab's split-window count is a lower bound
        return
    # a pooled account is ONE buyer on chain; swap-api spreads its trades over the real signers
    g = snap.g
    pooled_buy: dict[str, int] = {}
    for c in ch_rows(coin):
        if c["user"] in POOLED_ACCOUNTS and c["venue"] == VENUE_AMM and c["is_buy"] and g <= c["ts"] < g + 120:
            pooled_buy[c["user"]] = pooled_buy.get(c["user"], 0) + c["usol"]
    n_pooled = sum(1 for v in pooled_buy.values() if v >= 10_000_000)
    assert 0 <= lab["w120_n_buyers"] - snap["w120_n_buyers"] <= n_pooled
    assert snap["w120_n_sellers"] == lab["w120_n_sellers"]
    # wallets that swap-api credited with a pooled account's trades rank differently: leave them out of both lists
    signers = {r.trade.wallet for r, c in matched(coin, snap.rows) if c["user"] in POOLED_ACCOUNTS}
    ours = [x for x in snap["w120_top10"] if x[0] not in signers]
    theirs = [tuple(x) for x in json.loads(lab["w120_top10"]) if x[0] not in POOLED_ACCOUNTS | signers]
    ours = ours[:len(theirs)]
    assert [w for w, _, _ in ours] == [w for w, _, _ in theirs]
    for (_, b1, s1), (_, b2, s2) in zip(ours, theirs, strict=True):
        assert rel(b1, b2) < SOL_TOL
        assert abs(s1 - s2) <= max(SOL_TOL * s2, 1e-6)


@pytest.mark.parametrize("mint", [m for m in INSTANT if COINS[m]["b2_coin"]["agent_present"]])
def test_agent_identity_matches_the_lab(mint: str) -> None:
    coin = COINS[mint]
    lab = coin["b2_coin"]
    snap = snap_at_window_end(tracker_for(coin), coin)
    a = snap.agent
    assert a is not None
    assert a.wallet == lab["agent_wallet"]
    assert a.known_at == lab["agent_known_at"]
    assert a.first_offset_s == lab["agent_first_offset_s"]
    assert a.detected_at == a.known_at                          # regular cadence from the 1st slice: no delay
    assert abs(a.median_gap - 12.0) <= 1.0
    # BOOST slices are fee-free: their user-side SOL is exact (the reserve chain says amountSol == quote in)
    ch = {(c["slot"], c["tok"]): c["usol"] for c in ch_rows(coin) if c["user"] == a.wallet}
    rows = [r for r in snap.rows if r.trade.wallet == a.wallet]
    assert len(rows) == len(a.buy_ts) and all(r.kind == "fee_free" for r in rows)
    assert all(r.usol == ch[(r.trade.slot, r.trade.tok_raw)] for r in rows)
    assert snap["agent_wallet"] == lab["agent_wallet"]
    with pytest.raises(NotYetKnown):                             # window totals: only after g + 420
        snap["agent_sol"]


# =========================================================================== curve.sql columns


CURVE_LIFE = ("curve_buy_sol", "curve_sell_sol", "curve_buy_tok", "curve_sell_tok", "curve_n_buys", "curve_n_sells",
              "curve_n_buyers", "curve_n_sellers", "curve_top1_buy_sol", "curve_top3_buy_sol", "completer_sol",
              "completer30", "creator_buy_sol", "creator_sell_sol", "creator_buy_tok", "creator_sell_tok",
              "first20_buy_sol")
LAUNCH = ("l_buy_sol", "l_sell_sol", "l_buy_tok", "l_sell_tok", "l_n_buys", "l_n_sells", "l_n_buyers", "l_n_sellers",
          "l_n_wallets", "l_top3_buy_sol", "l_rsol_max", "l_bundle_slots", "l_max_buyers_slot", "l_creator_buy_sol",
          "l_creator_sell_sol", "z_n_buyers", "z_n_buyers_noncreator", "z_buy_sol", "z_buy_tok", "sn60_n_buyers",
          "sn60_buy_sol")


def _same(name: str, ours: Any, theirs: Any) -> bool:
    if ours is None or theirs is None:
        return ours is None and theirs is None
    if isinstance(theirs, str) or isinstance(ours, str):
        return ours == theirs
    if name.endswith(("_sol", "_tok", "rsol_max")):
        return abs(float(ours) - float(theirs)) <= max(1e-4 * abs(float(theirs)), 1e-6)
    return int(ours) == int(theirs)


def compare_curve(coin: dict[str, Any], names: tuple[str, ...]) -> dict[str, tuple[Any, Any]]:
    """Mismatching columns {name: (ours, lab)} at tau = creation + 120 s (creation slot and g inferred)."""
    snap = snap_at_window_end(tracker_for(coin), coin)
    gr = coin["graduate"]
    bad = {}
    for n in names:
        ours = snap.get(n)
        if not _same(n, ours, gr[n]):
            bad[n] = (ours, gr[n])
    return bad


@pytest.mark.parametrize("mint", SANE)
def test_launch_window_columns_match_graduates(mint: str) -> None:
    assert compare_curve(COINS[mint], LAUNCH) == {}


@pytest.mark.parametrize("mint", [m for m in SANE if COINS[m]["graduate"]["grad_delay_s"] < 119])
def test_curve_life_columns_match_graduates(mint: str) -> None:
    assert compare_curve(COINS[mint], CURVE_LIFE) == {}


@pytest.mark.parametrize("mint", MINTS)
def test_creation_slot_is_inferred_like_the_create_event(mint: str) -> None:
    coin = COINS[mint]
    snap = snap_at_window_end(tracker_for(coin), coin)
    first = snap.rows[0].trade
    if first.ts == coin["created_ms"] // 1000:
        assert snap.c_slot == coin["graduate"]["c_slot"] and snap.c_slot_exact   # the dev buy rides in the create tx
    else:                                                         # nobody traded in the creation second:
        assert not snap.c_slot_exact                              # the slot is unknowable: an upper bound
        assert coin["graduate"]["c_slot"] <= snap.c_slot < first.slot
        assert snap["z_n_buyers"] == 0 == coin["graduate"]["z_n_buyers"]   # and the bundle is empty (exact)


def test_slow_graduate_has_no_pool_or_curve_life_yet() -> None:
    coin = COINS[SLOW]
    snap = snap_at_window_end(tracker_for(coin), coin)
    assert not snap.graduated and math.isnan(snap.g) and snap.k == 0 and len(snap.bars) == 0
    with pytest.raises(NotYetKnown):
        snap["curve_buy_sol"]                                   # curve-life columns are known at g only
    assert snap["l_n_buys"] == coin["graduate"]["l_n_buys"]


# =========================================================================== B1 rows for lab strategy code


@pytest.mark.parametrize("mint", SANE)
def test_trade_rows_have_the_b1_shape_and_selection(mint: str) -> None:
    coin = COINS[mint]
    snap = snap_at_window_end(tracker_for(coin), coin)
    rows = snap.trade_rows()
    ch = [c for c in ch_rows(coin) if c["usol"] >= 10_000_000]            # B1 keeps trades >= 0.01 SOL
    assert [(r["slot"], r["tok"], int(r["is_buy"])) for r in rows] == [(c["slot"], c["tok"], c["is_buy"]) for c in ch]
    for r, c in zip(rows, ch, strict=True):
        assert set(r) >= {"slot", "tx_idx", "ts", "venue", "is_buy", "wallet_h", "usol", "tok", "x0", "y0", "fees",
                          "virt_ksol"}
        assert r["y0"] == c["y0"]
        if r["venue"] == VENUE_AMM:
            assert r["virt_ksol"] > 0
            assert rel(r["x0"] + r["virt_ksol"] * 1000, c["x0"] + (c["virt"] or r["virt_ksol"] * 1000)) < 1e-6
