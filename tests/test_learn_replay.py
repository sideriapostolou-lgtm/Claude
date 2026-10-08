"""The shadow book: forward-only, one observation per coin, determinism, missing data = -50 %, the day
completeness rule, the cost/impact gates and parity with the plain Backtester (docs/LEARNING.md §4)."""

from __future__ import annotations

import math
import random
from pathlib import Path

import pytest

from learn_world import DAY0, api_rows, census_row, dip_rebound_series, make_coins, record_coin
from nightcrawler.backtest import Backtester, CostModel, load_series
from nightcrawler.learn import replay as rp
from nightcrawler.learn.store import LearnStore
from nightcrawler.learn.tape import (
    TapeReader,
    TapeView,
    TapeWriter,
    candle_fetch_row,
    candle_mark,
    tape_day,
    universe_row,
)
from nightcrawler.learn.variants import make_spec
from nightcrawler.models import StrategyParams
from nightcrawler.sources._parse import parse_ts

ANCHOR = StrategyParams()
SPEC = make_spec("dip_rebound", {}, ANCHOR)
T0 = DAY0 + 600.0  # the variant's register receipt time
SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"


def view(rows, as_of=DAY0 + 10 * 86400, l_obs=60.0) -> TapeView:
    return TapeView(rows["universe"][0]["mint"], as_of=as_of, rows=rows, l_obs=l_obs)


def outcomes(coins, spec=SPEC, **kw):
    return {m: rp.replay_coin(spec, view(c["rows"]), t0=T0, closed=True, **kw) for m, c in coins.items()}


@pytest.fixture(scope="module")
def coins():
    return make_coins(12, seed=1, start=T0 + 60, fetch_after_h=(3, 9))


@pytest.fixture(scope="module")
def base(coins):
    return outcomes(coins)


@pytest.fixture(scope="module")
def traded(coins, base):
    return {m: c for m, c in coins.items() if base[m].kind == "trade"}


def test_the_synthetic_market_trades(base) -> None:
    kinds = [o.kind for o in base.values()]
    assert kinds.count("trade") >= 6, kinds  # enough entries for the tests below to mean something


# --------------------------------------------------------------------------- forward-only


def test_coins_created_at_or_before_t0_never_produce_evidence(traded) -> None:
    coin = next(iter(traded.values()))
    rows, created = coin["rows"], coin["created_ts"]
    assert rp.replay_coin(SPEC, view(rows), t0=created - 1, closed=True).kind == "trade"
    for t0 in (created, created + 1, created + 86400):
        out = rp.replay_coin(SPEC, view(rows), t0=t0, closed=True)
        assert out.kind == "excluded" and out.evidence is None and out.decisions == []
    assert rp.replay_coin(SPEC, view(rows), t0=None, closed=True).kind == "excluded"  # not receipted yet


def test_non_sol_and_mayhem_coins_are_outside_the_universe() -> None:
    candles = dip_rebound_series(T0 + 60, random.Random(3))
    for kw in ({"quote_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"}, {"mayhem": True}):
        rows = record_coin("MintZ" + "z" * 39, T0 + 60, candles, fetch_after_h=(9,), **kw)
        assert rp.replay_coin(SPEC, view(rows), t0=T0, closed=True).kind == "excluded"


# --------------------------------------------------------------------------- one observation, the first trade


def test_one_observation_per_coin_the_first_trade(base) -> None:
    multi = {m: o for m, o in base.items() if sum(d["entry_ts"] is not None for d in o.decisions) >= 2}
    assert multi, "need a coin with re-entries"
    for out in multi.values():
        assert out.evidence["entry_ts"] == next(d["entry_ts"] for d in out.decisions if d["entry_ts"] is not None)
        assert out.evidence["x"] == pytest.approx(max(-1.0, min(1.0, out.evidence["x_raw"])))


def test_evidence_fields_and_costs(base) -> None:
    for out in base.values():
        if out.kind != "trade":
            continue
        e = out.evidence
        assert e["pricing"] == "replay" and e["sim_hash"] == rp.sim_hash() and e["variant_hash"] == SPEC.hash
        assert e["exit_ts"] >= e["entry_ts"] and e["cost"] > 0.01  # fees, impact, haircut, network
        assert e["x_stress"] == pytest.approx(max(-1.0, min(1.0, e["gross"] - 1.5 * e["cost"])))
        assert e["x_raw"] == pytest.approx(e["gross"] - e["cost"])


def test_decisions_follow_the_lag_and_the_cadence(base) -> None:
    cfg = rp.SimConfig()
    for mint, out in base.items():
        phase = rp.phase_s(mint, cfg.cadence_s)
        for d in out.decisions:
            assert (d["t_dec"] - phase) % cfg.cadence_s == 0
            assert d["last_ts"] + 60 + cfg.l_obs_s <= d["t_dec"] < d["last_ts"] + 120 + cfg.l_obs_s
            if d["entry_ts"] is not None:  # filled where the order lands: L_obs + L_land after the decision
                assert d["entry_ts"] <= d["t_dec"] + cfg.l_obs_s + cfg.l_land_s < d["entry_ts"] + 60


# --------------------------------------------------------------------------- missing data, pending


def test_a_first_trade_open_where_the_tape_ends_is_pending_then_minus_50pct(traded, base) -> None:
    mint, coin = next(iter(traded.items()))
    entry = base[mint].evidence["entry_ts"]
    seen = coin["created_ts"] + 600
    hours = (entry + 5 * 60 - seen) / 3600  # the only fetch lands 5 minutes after the entry
    rows = record_coin(mint, coin["created_ts"], coin["candles"], fetch_after_h=(hours,))
    assert rp.replay_coin(SPEC, view(rows), t0=T0, closed=False).kind == "pending"  # never counted early
    out = rp.replay_coin(SPEC, view(rows), t0=T0, closed=True)  # the recorder gave up on this coin
    assert out.kind == "missing" and out.evidence["x"] == out.evidence["x_raw"] == -0.5
    assert out.evidence["exit_ts"] == entry + ANCHOR.max_hold_min * 60


def test_a_hole_after_the_entry_is_missing_data(traded, base) -> None:
    mint, coin = next(iter(traded.items()))
    entry = base[mint].evidence["entry_ts"]
    first = record_coin(mint, coin["created_ts"], coin["candles"], first_seen_ts=entry + 120, fetch_after_h=(0,))
    later = [c for c in coin["candles"] if c.ts <= entry + 6 * 3600]
    served = api_rows(later)[-60:]  # the API's row cap was hit: the minutes between the fetches are unknown
    second = candle_fetch_row(mint, served, fetched_ts=entry + 6 * 3600,
                              previous=candle_mark(first["candles"][0], None), limit=60)
    v = view({**first, "candles": [*first["candles"], second]})
    assert v.complete_from_start and v.covered_until == (entry + 120) // 60 * 60
    out = rp.replay_coin(SPEC, v, t0=T0, closed=True)
    assert out.kind == "missing" and out.evidence["x"] == -0.5


# --------------------------------------------------------------------------- the driver: days, determinism


def write_day(root: Path, store: LearnStore, coins: dict, *, incomplete: int = 0) -> str:
    day = tape_day(next(iter(coins.values()))["created_ts"] + 600)
    with TapeWriter(root) as w:
        for i, (mint, coin) in enumerate(coins.items()):
            for stream, rows in coin["rows"].items():
                for row in rows:
                    w.append(stream, day, row)
            store.add_coin(mint, created_ts=coin["created_ts"], first_seen_ts=coin["created_ts"] + 600, day=day)
            store.set_coin_status(mint, "incomplete" if i < incomplete else "closed")
    return day


def registered(store: LearnStore, spec=SPEC, t0=T0) -> str:
    store.add_variant(spec.hash, family=spec.family, params=spec.params, source="seed", alpha=0.005,
                      threshold=200.0, promotable=spec.promotable, name=spec.name, now=t0)
    store.mark_outbox(store.next_outbox()["id"], 1, t0)  # as the engine does once receipted
    return spec.hash


def test_replay_is_deterministic_down_to_the_evidence_root(tmp_path, coins) -> None:
    results = []
    for k in range(2):
        with LearnStore(tmp_path / f"s{k}" / "learn.db") as store:
            day = write_day(tmp_path / f"s{k}" / "tape", store, coins)
            h = registered(store)
            counts = rp.replay_day(store, TapeReader(tmp_path / f"s{k}" / "tape"), day, now=DAY0 + 5 * 86400)
            assert sum(counts.values()) == len(coins)
            rows = store.evidence(h)
            results.append((rows, rp.evidence_root(rows)))
            assert rp.replay_day(store, TapeReader(tmp_path / f"s{k}" / "tape"), day, now=DAY0 + 6 * 86400) == {}
    assert results[0] == results[1] and results[0][0]
    order = sorted(results[0][0], key=lambda r: (r["exit_ts"], r["mint"]))
    assert [r["mint"] for r in results[0][0]] == [r["mint"] for r in order]


def test_an_incomplete_day_is_excluded_for_every_variant(tmp_path) -> None:
    twenty = make_coins(20, seed=2, start=T0 + 60, spacing_s=300, fetch_after_h=(3,))
    with LearnStore(tmp_path / "learn.db") as store:
        day = write_day(tmp_path / "tape", store, twenty, incomplete=2)  # 90 % < 95 %
        h = registered(store)
        counts = rp.replay_day(store, TapeReader(tmp_path / "tape"), day, now=DAY0 + 5 * 86400)
        assert counts == {"excluded": 20} and store.evidence(h) == []
    with LearnStore(tmp_path / "ok.db") as store:
        day = write_day(tmp_path / "tape_ok", store, twenty, incomplete=1)  # 95 %: kept
        h = registered(store)
        counts = rp.replay_day(store, TapeReader(tmp_path / "tape_ok"), day, now=DAY0 + 5 * 86400)
        assert "excluded" not in counts and store.evidence(h)


def test_a_day_with_open_coins_is_not_replayed_yet(tmp_path, coins) -> None:
    with LearnStore(tmp_path / "learn.db") as store:
        day = write_day(tmp_path / "tape", store, coins)
        store.set_coin_status(next(iter(coins)), "open")
        registered(store)
        assert rp.replay_day(store, TapeReader(tmp_path / "tape"), day, now=DAY0 + 5 * 86400) == {}


def test_the_scoreboard_scores_evidence_and_is_receipted_once_a_day(tmp_path, coins) -> None:
    with LearnStore(tmp_path / "learn.db") as store:
        day = write_day(tmp_path / "tape", store, coins)
        h = registered(store)
        rp.replay_day(store, TapeReader(tmp_path / "tape"), day, now=DAY0 + 5 * 86400)
        rows = rp.update_scoreboard(store, now=DAY0 + 5 * 86400)
        xs = [e["x"] for e in store.evidence(h)]
        assert rows[h]["n"] == len(xs) and rows[h]["mean"] == pytest.approx(sum(xs) / len(xs))
        assert rows[h]["evidence_root"] == rp.evidence_root(store.evidence(h))
        rp.update_scoreboard(store, now=DAY0 + 5 * 86400 + 60)
        events = [o for o in store.outbox() if o["event"] == "scoreboard"]
        assert len(events) == 1 and events[0]["payload"]["variants"][h]["n"] == len(xs)
        assert events[0]["payload"]["sim_hash"] == rp.sim_hash()


def test_evidence_root_is_a_merkle_root() -> None:
    rows = [{"mint": str(i)} for i in range(5)]
    assert rp.evidence_root(rows) == rp.evidence_root([dict(r) for r in rows])
    assert rp.evidence_root(rows) != rp.evidence_root(rows[::-1]) != rp.evidence_root(rows[:4])
    assert len(rp.evidence_root([])) == 64


# --------------------------------------------------------------------------- costs and gates


def test_the_impact_cap_and_liquidity_floor_refuse_entries(traded) -> None:
    strict = rp.SimConfig(max_price_impact_pct=0.01)
    assert all(o.kind == "none" for o in outcomes(traded, cfg=strict).values())
    deep_floor = make_spec("dip_rebound", {"min_liquidity_usd": 10_000_000}, ANCHOR)
    assert all(o.kind == "none" for o in outcomes(traded, spec=deep_floor).values())


def test_a_higher_cost_scale_never_helps(traded, base) -> None:
    worse = outcomes(traded, cfg=rp.SimConfig(cost_scale={"lt100k": 1.5, "100k-1m": 1.5, "1m+": 1.5}))
    compared = 0
    for mint, out in worse.items():
        if out.kind == "trade" and out.evidence["entry_ts"] == base[mint].evidence["entry_ts"]:
            assert out.evidence["cost"] > base[mint].evidence["cost"]
            compared += 1
    assert compared


def test_the_placebo_trades_at_its_hash_time(coins) -> None:
    outs = outcomes(coins, spec=make_spec("placebo", {}, ANCHOR))
    assert sum(o.kind == "trade" for o in outs.values()) >= 6
    for o in outs.values():
        for d in o.decisions:
            assert d["metrics"]["due_ts"] <= d["t_dec"]


def test_estimate_l_obs_uses_the_p75_once_there_are_500_samples() -> None:
    assert rp.estimate_l_obs([10.0] * 499) == 60.0
    assert rp.estimate_l_obs([float(i) for i in range(1, 1001)]) == 750.0


# --------------------------------------------------------------------------- parity with the backtester


def test_with_the_hooks_off_replay_equals_the_backtester_on_a_real_sample() -> None:
    candles, meta = load_series(SAMPLES / "higgs_1m.json")
    created = parse_ts(meta["created_utc"])
    mint = meta["mint"]
    rows = record_coin(mint, created, candles, first_seen_ts=candles[-1].ts + 120 - 3600, fetch_after_h=(1,),
                       limit=10_000)
    rows["universe"] = [universe_row({**census_row(mint, created), "total_supply": int(meta["supply"] * 1e6)},
                                     fetched_ts=created + 600, offset=0, late=False)]
    v = view(rows)
    tape_candles = v.candles()
    by_ts = {c.ts: c for c in tape_candles}
    assert tape_candles[0].ts == candles[0].ts and tape_candles[-1].ts >= candles[-1].ts  # flat to the fetch
    assert all(by_ts[c.ts] == c for c in candles if c.v > 0)  # the tape round trip is lossless
    out = rp.replay_coin(SPEC, v, t0=created - 1, closed=True, cfg=rp.SimConfig(hooks=False))
    bt = Backtester(ANCHOR, CostModel(), start_usd=100.0, position_pct=0.2, min_position_usd=20.0,
                    max_position_usd=20.0)
    first = bt.run(tape_candles, {"coin": meta.get("coin"), "mint": mint, "created_utc": created,
                                  "supply": meta["supply"]}).trades[0]
    assert out.kind == "trade"
    assert out.evidence["x_raw"] == pytest.approx(first.pnl_usd / first.size_usd, abs=1e-12)
    assert (out.evidence["entry_ts"], out.evidence["exit_ts"]) == (first.entry_ts, first.exit_ts)
    assert not math.isnan(out.evidence["x"])
