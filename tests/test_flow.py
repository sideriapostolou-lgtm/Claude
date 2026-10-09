"""nightcrawler.flow: strict causality (garbage after the cutoff never changes a snapshot), ingest semantics,
legality of lab fields, wallet identity (pooled accounts), AGENT detection timing, positions / orphans /
inventory, B1 rows. Real trades come from the parity fixture (tests/fixtures/flow/README.md)."""

from __future__ import annotations

import math
import random
from typing import Any

import pytest

from nightcrawler.flow import (
    AGENT_WINDOW_S,
    DECISION_LAG_S,
    POOLED_ACCOUNTS,
    VENUE_AMM,
    VENUE_CURVE,
    FlowTrade,
    FlowTracker,
    ForbiddenFeature,
    NotYetKnown,
    detect_agent,
    grid_time,
    pumpswap_fee_components,
    wallet_h,
)
from test_flow_parity import COINS, INSTANT, SANE, tracker_for

POOLED = next(iter(POOLED_ACCOUNTS))


def canon(x: Any) -> Any:
    """Comparable form (NaN == NaN)."""
    if isinstance(x, float):
        return "nan" if math.isnan(x) else round(x, 12)
    if isinstance(x, dict):
        return {k: canon(v) for k, v in sorted(x.items())}
    if isinstance(x, (list, tuple)):
        return [canon(v) for v in x]
    if hasattr(x, "__dataclass_fields__"):
        return canon({k: getattr(x, k) for k in x.__dataclass_fields__})
    return x


def fingerprint(tr: FlowTracker, t: float) -> Any:
    s = tr.as_of(t, sol_usd=200.0)
    return canon({
        "features": s.features(), "bars": s.bars.as_dict(), "positions": s.positions(), "orphans": s.orphan_summary(),
        "inventory": s.inventory(), "rows": s.trade_rows(min_sol=0.0), "agent": s.agent, "price": s.price,
        "k": s.k, "g": s.g, "n": s.n_trades, "vol": s.vol_sol(900), "ret": s.ret(120), "c_slot": s.c_slot,
    })


def garbage(after_ts: int, slot0: int, n: int, seed: int, *, interleave_slots: bool = False) -> list[FlowTrade]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        slot = rng.randrange(1, slot0) if interleave_slots else slot0 + 1 + i
        sid = f"{slot:012d}{rng.randrange(10**9):010d}"
        out.append(FlowTrade(slot=slot, pos=int(sid[12:]), sid=sid, ts=after_ts + 1 + rng.randrange(600),
                             wallet=rng.choice(["Gar" + str(i), POOLED, "ANkEbgVR5ycwyWKUxsc1D3dQHwL5Cfe2FEpF"]),
                             is_buy=rng.random() < 0.5, venue=rng.choice([VENUE_CURVE, VENUE_AMM]),
                             amount_sol=rng.random() * 500, tok_raw=rng.randrange(1, 10**14),
                             price=rng.random() * 1e-5 + 1e-9))
    return out


# =========================================================================== causality


@pytest.mark.parametrize("mint", SANE)
@pytest.mark.parametrize("offset", [25, 61, 95, 140])
def test_garbage_after_the_cutoff_never_changes_a_snapshot(mint: str, offset: int) -> None:
    coin = COINS[mint]
    c_ts = coin["created_ms"] // 1000
    t = c_ts + offset
    tr = tracker_for(coin)
    before = fingerprint(tr, t)
    last_slot = max(x.slot for x in tr.trades)
    tr.ingest(garbage(int(t - DECISION_LAG_S), last_slot, 300, seed=offset))
    assert fingerprint(tr, t) == before


@pytest.mark.parametrize("mint", SANE)
def test_garbage_stamped_later_but_ordered_earlier_cannot_leak_either(mint: str) -> None:
    """A malformed feed could put a later-stamped trade earlier in chain order: the prefix is then re-derived from
    the trades with ts <= tau alone."""
    coin = COINS[mint]
    t = coin["created_ms"] // 1000 + 140
    tr = tracker_for(coin)
    before = fingerprint(tr, t)
    first_slot = min(x.slot for x in tr.trades)
    tr.ingest(garbage(int(t - DECISION_LAG_S), first_slot, 50, seed=7, interleave_slots=True))
    assert fingerprint(tr, t) == before


@pytest.mark.parametrize("mint", SANE)
def test_a_snapshot_equals_one_from_a_tracker_that_never_saw_the_future(mint: str) -> None:
    coin = COINS[mint]
    c_ts = coin["created_ms"] // 1000
    full = tracker_for(coin)
    for offset in (30, 75, 140):
        t = c_ts + offset
        tau = t - DECISION_LAG_S
        past = FlowTracker(mint, created_ts=c_ts, creator=coin["graduate"]["creator"], history_from=c_ts)
        past.ingest([x for x in full.trades if x.ts <= tau])
        past.mark_complete(c_ts + 120)
        assert fingerprint(past, t) == fingerprint(full, t)


# =========================================================================== ingest


def test_ingest_dedupes_and_ignores_arrival_order() -> None:
    coin = COINS[INSTANT[0]]
    a = tracker_for(coin)
    trades = list(a.trades)
    b = FlowTracker(a.mint, created_ts=a.meta.created_ts, creator=a.meta.creator, history_from=a.history_from)
    shuffled = trades[:]
    random.Random(3).shuffle(shuffled)
    assert b.ingest(shuffled) == len(trades)
    assert b.ingest(trades[:50]) == 0                 # duplicates (same slotIndexId) are ignored
    assert b.trades == a.trades
    assert [r.usol for r in b.rows()] == [r.usol for r in a.rows()]


def test_complete_flag_follows_mark_complete() -> None:
    coin = COINS[INSTANT[0]]
    c_ts = coin["created_ms"] // 1000
    tr = tracker_for(coin)                             # complete through c + 120 (exclusive)
    assert tr.as_of(c_ts + 139).complete               # tau = c + 119
    assert not tr.as_of(c_ts + 140).complete           # tau = c + 120: a trade at c + 120 may be missing
    tr.mark_complete(c_ts + 100)                       # never moves back
    assert tr.complete_through == c_ts + 120
    assert tr.as_of(c_ts + 139).data_lag_s == pytest.approx(19.0)


# =========================================================================== legality


def test_lab_fields_raise_before_their_legal_time() -> None:
    coin = COINS[INSTANT[0]]
    g = coin["graduate"]["g_ts"]
    tr = tracker_for(coin)
    early = tr.as_of(g + 100)                          # tau = g + 80
    with pytest.raises(NotYetKnown):
        early["w120_buy_sol"]
    assert early.get("w120_buy_sol", "later") == "later"
    with pytest.raises(NotYetKnown):
        early["w300_buy_sol"]
    with pytest.raises(ForbiddenFeature):
        early["virt_sol"]                              # encodes the lab's collection: never a feature
    with pytest.raises(ForbiddenFeature):
        early.get("n_chunks")
    with pytest.raises(KeyError):
        early["no_such_field"]
    late = tr.as_of(g + 140)
    assert late["w120_buy_sol"] > 0
    assert "w120_buy_sol" in late.features() and "w120_buy_sol" not in early.features()
    assert "w300_buy_sol" not in late.features()


def test_agent_fields_follow_detection_and_the_420s_window() -> None:
    coin = COINS[INSTANT[0]]
    g = coin["graduate"]["g_ts"]
    tr = tracker_for(coin)
    a = tr.as_of(g + 140).agent
    assert a is not None
    before = tr.as_of(a.detected_at - 1 + DECISION_LAG_S)
    assert not before.agent_detected and not before.agent_resolved
    with pytest.raises(NotYetKnown):
        before["agent_present"]
    with pytest.raises(NotYetKnown):
        before.top_share("w120")                       # cannot exclude an undecided AGENT
    at = tr.as_of(a.detected_at + DECISION_LAG_S)
    assert at.agent_detected and at["agent_wallet"] == a.wallet and at["agent_known_at"] == a.known_at
    assert math.isnan(before.bars.agent_buy_sol[0]) if before.k else True
    with pytest.raises(NotYetKnown):
        at["agent_slices"]                             # window totals only after g + 420


# =========================================================================== AGENT rule (research/flow/features.py)


def _cands(ts: list[int], sells: int = 0) -> dict[str, dict[str, Any]]:
    return {"A": {"ts": ts, "sol": [0.6] * len(ts), "sells": sells}}


def test_detect_agent_rule() -> None:
    g = 1000
    regular = [g + 2 + 12 * i for i in range(10)]
    hit = detect_agent(_cands(regular), g)
    assert hit is not None and hit["known_at"] == regular[3] and hit["n_slices"] == 10
    assert detect_agent(_cands(regular[:3]), g) is None                   # < 4 buys
    assert detect_agent(_cands(regular, sells=1), g) is None              # a seller is no AGENT
    skipped = regular[:5] + [t + 12 for t in regular[5:]]                 # one skipped slice (24 s gap)
    assert detect_agent(_cands(skipped), g) is not None                   # the robust band rule keeps it
    assert detect_agent(_cands([g + 30 * i for i in range(8)]), g) is None
    late = [g + AGENT_WINDOW_S + 12 * i for i in range(6)]
    assert detect_agent(_cands(late), g) is None                          # outside [g, g + 420)
    assert detect_agent(_cands(regular), g, as_of=regular[2]) is None     # causal: 3 buys seen so far


def _amm(ts: int, wallet: str, buy: bool, sol: float, slot: int, price: float = 5e-7) -> FlowTrade:
    sid = f"{slot:012d}{len(wallet) * 7 + int(buy):010d}"
    return FlowTrade(slot=slot, pos=int(sid[12:]), sid=sid, ts=ts, wallet=wallet, is_buy=buy, venue=VENUE_AMM,
                     amount_sol=sol,
                     tok_raw=int(sol / price * 1e6), price=price)


def test_agent_detection_waits_for_a_regular_cadence_and_ignores_pooled_accounts() -> None:
    g = 2_000_000_000
    trades = [_amm(g + 2 + 30 * i if i < 2 else g + 62 + 12 * (i - 2), "AGT", True, 0.6, 100 + i) for i in range(9)]
    trades += [_amm(g + 2 + 12 * i, POOLED, True, 1.0, 200 + i) for i in range(9)]
    tr = FlowTracker("M", g_ts=g, history_from=g)
    tr.ingest(trades)
    s = tr.as_of(g + 300)
    assert s.agent is not None and s.agent.wallet == "AGT"
    assert s.agent.known_at == trades[3].ts                     # lab definition: the 4th buy
    assert s.agent.detected_at > s.agent.known_at               # but the first gaps were 30 s: detected later


# =========================================================================== wallets


def _cv(ts: int, wallet: str, buy: bool, tok: int, slot: int, sol: float = 0.1) -> FlowTrade:
    sid = f"{slot:012d}{sum(map(ord, wallet)) % 997 * 2 + int(buy):010d}"
    return FlowTrade(slot=slot, pos=int(sid[12:]), sid=sid, ts=ts, wallet=wallet, is_buy=buy, venue=VENUE_CURVE,
                     amount_sol=sol, tok_raw=tok, price=3e-8)


def test_positions_orphans_and_sell_only_wallets() -> None:
    c = 2_000_000_000
    tr = FlowTracker("M", created_ts=c, creator="DEV", c_slot=10, history_from=c)
    tr.ingest([
        _cv(c, "DEV", True, 100_000_000, 10),
        _cv(c, "SNIPE", True, 50_000_000, 10),
        _cv(c + 5, "A", True, 100_000_000, 12),
        _cv(c + 9, "A", False, 150_000_000, 13),      # 50 tokens beyond what A bought: orphan
        _cv(c + 9, "T", False, 30_000_000, 14),       # never bought: sell-only, all orphan
        _cv(c + 9, POOLED, False, 30_000_000, 15),    # pooled: never a wallet
        _cv(c + 70, "DEV", False, 40_000_000, 16),
    ])
    s = tr.as_of(c + 200)
    pos = s.positions()
    assert POOLED not in pos
    assert pos["A"].orphan_tok == pytest.approx(50.0) and pos["A"].peak_tok == pytest.approx(100.0)
    assert pos["T"].orphan_tok == pytest.approx(30.0) and pos["T"].n_sell_without_holding == 1
    summ = s.orphan_summary()
    assert summ["n_orphan_sellers"] == 2 and summ["n_sell_only_wallets"] == 1
    assert summ["orphan_tok"] == pytest.approx(80.0)
    assert set(s.orphan_sellers()) == {"A", "T"}
    inv = s.inventory()
    assert inv["known"]
    assert inv["creator"]["held_tok"] == pytest.approx(60.0) and inv["creator"]["peak_tok"] == pytest.approx(100.0)
    assert inv["bundle"]["wallets"] == 2.0                       # DEV and SNIPE bought in the creation slot
    assert inv["snipers"]["wallets"] == 3.0                      # first 20 curve buyers
    early = tr.as_of(c + 30)                                     # tau = c + 10: DEV's sell not seen yet
    assert early.inventory()["creator"]["held_tok"] == pytest.approx(100.0)


def test_wallet_features_need_history_from_creation() -> None:
    coin = COINS[INSTANT[0]]
    c_ts = coin["created_ms"] // 1000
    tr = FlowTracker(coin["mint"], created_ts=c_ts, history_from=c_ts + 30)   # joined late
    tr.ingest(tracker_for(coin).trades)
    s = tr.as_of(c_ts + 140)
    assert not s.curve_known and s.inventory() == {"known": False}
    assert s.get("curve_buy_sol") is None                       # NULL, never 0
    assert s.bars.X[0] is None                                  # no reserve chain without the pool's start


# =========================================================================== B1 rows, hashes, fees


def test_wallet_h_is_clickhouse_cityhash64() -> None:
    # (wallet_h, base58) pairs from a CryptoHouse B1 query result (FLOW/dev/test_b1.json)
    pairs = [(9740399439260290013, "168Q2pG7tYAoNXLQcA7yJufVzrUnZr85W5eYTBfp5eB"),
             (13548937726806623243, "14Bzxa1JbhAcCgY5qDk5ubuHVq98ecGCxzWgnCKpVRYG"),
             (4654010341800588981, "7EvuC7mQ65DyKqpn42TPSCNNMFUtKYAXFSV9euyhb8a")]
    for h, w in pairs:
        assert wallet_h(w) == h


def test_trades_frame_is_the_b1_dataframe() -> None:
    pd = pytest.importorskip("pandas")
    coin = COINS[INSTANT[0]]
    s = tracker_for(coin).as_of(coin["created_ms"] // 1000 + 140)
    df = s.trades
    assert isinstance(df, pd.DataFrame) and len(df) == len(s.trade_rows())
    assert str(df["wallet_h"].dtype) == "uint64"
    assert (df["usol"] >= 10_000_000).all()
    assert df["ts"].max() <= s.tau


def test_pumpswap_fee_components_follow_the_documented_tiers() -> None:
    assert pumpswap_fee_components(410.0) == (2.0, 93.0, 30.0)          # 1.25 % below 420 SOL
    assert pumpswap_fee_components(1000.0) == (20.0, 5.0, 95.0)         # 1.20 %
    assert pumpswap_fee_components(1e6) == (20.0, 5.0, 5.0)             # 0.30 % at the top


def test_grid_time_matches_the_lab_decision_grid() -> None:
    g = 1_791_417_538                     # 58 s into its minute
    m0 = g // 60 * 60
    assert grid_time(g, 0) == m0 + 20                       # t <= g < t + 60
    assert grid_time(g, 6 * 60) == m0 + 20 + 6 * 60         # S1 checkpoint 6 min: g + 360 lies in [t, t + 60)
    for age in (0, 59, 60, 361, 7200):
        t = grid_time(g, age)
        assert t <= g + age < t + 60 and (t - m0 - 20) % 60 == 0
