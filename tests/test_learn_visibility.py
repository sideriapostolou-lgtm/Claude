"""The learner cannot see the future (docs/LEARNING.md §3.2), checked end to end through the replay:

* GARBAGE AFTER THE CUTOFF: for 200 random (coin, t) pairs, every candle minute with
  ``m + 60 + L_obs > t`` and every state row fetched after ``t`` is replaced by noise; no decision
  made at or before ``t`` changes, and ``TapeView(as_of=t)`` shows exactly the same data.
* PREFIX INVARIANCE: the tape as it was written by time ``t`` (rows with ``ts <= t``) gives the
  same decisions as the full tape for every candle it covers, and any result it already calls
  final is the full tape's result.
"""

from __future__ import annotations

import copy
import random

import pytest

from learn_world import DAY0, make_coins
from nightcrawler.learn import replay as rp
from nightcrawler.learn.tape import TapeView
from nightcrawler.learn.variants import make_spec
from nightcrawler.models import StrategyParams

ANCHOR = StrategyParams()
T0 = DAY0 + 600.0
L_OBS = 60.0
SNAP_AGES_MIN = (5, 15, 30, 60, 120, 240, 360)
SPECS = {"dip_rebound": make_spec("dip_rebound", {}, ANCHOR), "placebo": make_spec("placebo", {}, ANCHOR)}


@pytest.fixture(scope="module")
def coins():
    coins = make_coins(10, seed=7, start=T0 + 60, spacing_s=1500, fetch_after_h=(2, 5, 9))
    for mint, coin in coins.items():  # the DexScreener snapshot ladder, by age since first seen
        seen = coin["rows"]["universe"][0]["first_seen_ts"]
        coin["rows"]["snaps"] = [{"v": 1, "ts": seen + age * 60, "mint": mint, "age_min": age,
                                  "pair": {"priceUsd": "0.0003", "liquidity": {"usd": 50_000}}}
                                 for age in SNAP_AGES_MIN]
    return coins


def census(coins) -> list[dict]:
    return [row for c in coins.values() for row in c["rows"]["universe"]]


def replay(spec, mint, rows, all_census, *, as_of=DAY0 + 30 * 86400, closed=True):
    created = rows["universe"][0]["created_ts"] if rows["universe"] else None
    sol = rp.sol_usd_asof(all_census, created, rp.SimConfig().sol_usd) if created else None
    return rp.replay_coin(spec, TapeView(mint, as_of=as_of, rows=rows, l_obs=L_OBS), t0=T0, closed=closed,
                          sol_usd=sol)


def noise_value(rng: random.Random) -> str:
    return repr(rng.uniform(1e-5, 2e-3))


def garble(rows: dict, t: float, rng: random.Random) -> dict:
    """Noise in every candle minute invisible at ``t`` and every state field fetched after ``t``."""
    out = copy.deepcopy(rows)
    for fetch in out["candles"]:
        for key in ("rows", "revised"):
            for r in fetch[key]:
                if r[0] + 60 + L_OBS > t:
                    o, c = float(noise_value(rng)), float(noise_value(rng))
                    r[1:] = [repr(o), repr(max(o, c) * (1 + rng.random())), repr(min(o, c) * rng.uniform(0.05, 1)),
                             repr(c), repr(rng.uniform(0, 1e6))]
    for snap in out["snaps"]:
        if snap["ts"] > t:
            snap["pair"] = {"priceUsd": noise_value(rng), "liquidity": {"usd": rng.uniform(0, 1e7)}}
    for row in out["universe"]:  # launch fields are visible from creation; the census STATE from its fetch
        if row["ts"] > t:
            row["raw"] = {**row["raw"], "market_cap": rng.uniform(1, 1e6), "usd_market_cap": rng.uniform(1, 1e9),
                          "ath_market_cap": rng.uniform(1, 1e9), "complete": rng.random() < 0.5}
    return out


def until(decisions: list[dict], t: float) -> list[dict]:
    return [d for d in decisions if d["t_dec"] <= t]


def signal(d: dict) -> tuple:
    """A decision without its fill: when, on which newest candle, and what the strategy measured."""
    return d["t_dec"], d["last_ts"], d["metrics"]


@pytest.mark.parametrize("family,pairs", [("dip_rebound", 200), ("placebo", 60)])
def test_garbage_after_the_cutoff_changes_no_decision_before_it(coins, family, pairs) -> None:
    spec, rng = SPECS[family], random.Random(11 if family == "dip_rebound" else 12)
    all_census = census(coins)
    full = {m: replay(spec, m, c["rows"], all_census) for m, c in coins.items()}
    assert sum(len(o.decisions) for o in full.values()) >= 10
    informative = changed_later = 0
    for _ in range(pairs):
        mint = rng.choice(sorted(coins))
        coin = coins[mint]
        t = coin["created_ts"] + rng.uniform(0.5, 9.5) * 3600
        garbled = garble(coin["rows"], t, rng)
        others = garble({"candles": [], "snaps": [], "universe": [r for r in all_census if r["mint"] != mint]}, t, rng)
        out = replay(spec, mint, garbled, others["universe"] + garbled["universe"])
        assert until(out.decisions, t) == until(full[mint].decisions, t), (mint, t)
        a = TapeView(mint, as_of=t, rows=coin["rows"], l_obs=L_OBS)
        b = TapeView(mint, as_of=t, rows=garbled, l_obs=L_OBS)
        assert a.candles() == b.candles() and a.state("snaps") == b.state("snaps") and a.launch == b.launch
        informative += bool(until(full[mint].decisions, t))
        changed_later += out.decisions != full[mint].decisions or out.evidence != full[mint].evidence
    assert informative >= pairs // 10  # many cutoffs fall after real decisions...
    assert changed_later >= pairs // 10  # ...and the noise really changed what came after them


def test_a_tape_truncated_at_t_gives_identical_decisions_up_to_t(coins) -> None:
    spec, rng = SPECS["dip_rebound"], random.Random(13)
    all_census = census(coins)
    full = {m: replay(spec, m, c["rows"], all_census) for m, c in coins.items()}
    finals = compared = 0
    for _ in range(120):
        mint = rng.choice(sorted(coins))
        coin = coins[mint]
        t = coin["created_ts"] + rng.uniform(0.0, 10.0) * 3600
        written = {stream: [r for r in rows if r["ts"] <= t] for stream, rows in coin["rows"].items()}
        known = [r for r in all_census if r["ts"] <= t]
        if not written["universe"]:  # not seen yet at t: the learner cannot even name the coin
            continue
        candles_t = TapeView(mint, as_of=t, rows=written, l_obs=L_OBS).candles()
        out = replay(spec, mint, written, known, as_of=t, closed=False)
        last = candles_t[-1].ts if candles_t else -1
        # every signal of the partial tape, in order, is the full tape's signal on the same candle...
        assert [signal(d) for d in out.decisions] == [signal(d) for d in full[mint].decisions if d["last_ts"] <= last]
        # ...and every fill it already saw is the same fill
        assert [d["entry_ts"] for d in out.decisions if d["entry_ts"] is not None] == [
            d["entry_ts"] for d in full[mint].decisions if d["entry_ts"] is not None and d["entry_ts"] <= last]
        compared += bool(out.decisions)
        if out.kind == "trade":  # anything the partial tape already calls final never changes later
            finals += 1
            assert out.evidence == full[mint].evidence
        else:
            assert out.kind in ("pending", "excluded")
    assert finals >= 5 and compared >= 20


def test_no_entry_before_the_coin_is_known_to_have_graduated() -> None:
    """The universe is "coins that graduated". The census shows a coin only once it has, so before the
    recorder first saw it, buying it on the bonding curve would use the future fact that it graduates
    (research/lab: no entries before graduation). Here 30 coins dip and rebound on the curve for 8 h and
    graduate afterwards; the Settings floors are low enough (valid MIN_MCAP_USD / MIN_LIQUIDITY_USD) to
    let the strategy trade them."""
    from learn_world import dip_rebound_series, record_coin
    from nightcrawler.models import Candle

    spec = make_spec("dip_rebound", {}, StrategyParams(min_mcap_usd=10_000.0, min_liquidity_usd=5_000.0))
    entries = 0
    for seed in range(30):
        created = T0 + 60
        base = dip_rebound_series(created, random.Random(seed))
        scale = 40_000.0 / 1e9 / max(c.h for c in base)  # below the curve's completion (~$43k at SOL $106)
        candles = [Candle(c.ts, c.o * scale, c.h * scale, c.l * scale, c.c * scale, c.v) for c in base]
        graduated = candles[-1].ts + 60
        mint = f"Curve{seed:03d}" + "c" * 36
        rows = record_coin(mint, created, candles, first_seen_ts=graduated + 120, fetch_after_h=(3, 12, 50))
        out = replay(spec, mint, rows, rows["universe"])
        for d in out.decisions:
            assert d["t_dec"] >= rows["universe"][0]["first_seen_ts"], (seed, d)
        if out.evidence is not None:
            entries += 1
            assert out.evidence["entry_ts"] >= rows["universe"][0]["first_seen_ts"]
    assert entries == 0  # the coins never trade again after graduating: nothing left to buy
