"""Foundation tests: model round-trips, unit helpers and P&L arithmetic."""

from __future__ import annotations

import dataclasses
import json

import pytest

from nightcrawler.models import (
    LAMPORTS_PER_SOL,
    SOL_MINT,
    TOKEN_ACCOUNT_RENT_LAMPORTS,
    Balances,
    Candle,
    Decision,
    EquityPoint,
    Fill,
    MarketSnapshot,
    Position,
    Quote,
    RadarSignal,
    Receipt,
    SafetyReport,
    Signal,
    StrategyParams,
    TokenCandidate,
    Verdict,
    base_to_ui,
    effective_price_usd,
    lamports_to_sol,
    new_id,
    sol_to_lamports,
    to_jsonable,
    ui_to_base,
)

MINT = "DoVAVzViX8Bjy3r15nwikSaSbzE6dV4ovd28aWpJpump"


def sample_verdict() -> Verdict:
    return Verdict("no", 0.8, ["insiders selling"], "claude-opus-5-5", 1234, 0.0123, "claude",
                   request_id="req_1")


def sample_fill(**kw) -> Fill:
    base = dict(id="fill_1", mode="paper", side="buy", mint=MINT, sol_lamports=100_000_000,
                token_amount=16_239_400_281, token_decimals=6, price_usd=0.00067, sol_usd=108.85,
                fees_lamports=300_000, platform_fee_bps=10, price_impact_pct=2.1957, signature=None,
                request_id="01a11c56", ts=1_791_475_200.0, rent_lamports=TOKEN_ACCOUNT_RENT_LAMPORTS)
    base.update(kw)
    return Fill(**base)


SAMPLES = [
    Candle(1791117360, 5.0e-05, 9.6e-05, 4.9e-05, 9.4e-05, 39804.8),
    TokenCandidate(MINT, "HIGGS", "Higgspad", pool="BFrS", dex="pumpswap", sources=["jupiter_recent"],
                   created_at=1791117000.0, age_min=61.0, mcap_usd=855186.0, audit={"isSus": False},
                   stats={"5m": {"numBuys": 3}}, socials={"twitter": "https://x.com/higgspad"}),
    MarketSnapshot(MINT, 1791475200.0, 0.0008832, 855186.0, 119336.33, buys_m5=3, sells_m5=4,
                   price_change_m5=-4.83),
    SafetyReport(MINT, False, ["[top10] top-10 holders 41.0% > 30%"], ["mutable metadata"], {"top10_pct": 41.0},
                 1791475200.0, unverified=["rugcheck"], creator="G7Ya", top_holders=["a", "b"]),
    RadarSignal(MINT, 15.0, 1200.0, 800.0, True, [{"wallet": "G7Ya", "usd": 800.0, "role": "creator"}],
                True, ["creator sold $800"]),
    Signal("enter", "dip-rebound", 0.6, {"dip": 0.62}),
    sample_verdict(),
    Quote("buy", SOL_MINT, MINT, 100_000_000, 16_239_400_281, 2.1957, 10, ["Pump.fun Amm"], "req", None,
          1791475200.0, 10.88, 10.64, error="Insufficient funds", error_code=1, raw={"router": "metis"}),
    sample_fill(),
    Position("pos_1", MINT, "HIGGS", "BFrS", 1791475200.0, 6, entry_fill_ids=["fill_1"],
             token_amount=16_239_400_281, initial_token_amount=16_239_400_281, cost_lamports=100_000_000),
    Decision(1791475200.0, MINT, "reject_judge", "judge said no", {"size_usd": 20.0}, sample_verdict(), "HIGGS"),
    Receipt(1, 1791475200.0, "decision", {"a": 1}, "0" * 64, "f" * 64),
    EquityPoint(1791475200.0, 920_000_000, 108.0, 99.36),
    Balances(920_000_000, {MINT: 5}),
    StrategyParams(),
]


@pytest.mark.parametrize("obj", SAMPLES, ids=lambda o: type(o).__name__)
def test_round_trip_through_json(obj) -> None:
    data = obj.to_dict()
    text = json.dumps(data)  # JSON-native
    back = type(obj).from_dict(json.loads(text))
    assert back == obj
    assert back.to_dict() == data


def test_nested_verdict_is_rebuilt() -> None:
    d = SAMPLES[10]
    back = Decision.from_dict(json.loads(json.dumps(d.to_dict())))
    assert isinstance(back.verdict, Verdict) and back.verdict.reasons == ["insiders selling"]
    assert Decision.from_dict({"ts": 1.0, "mint": "m", "action": "watch", "reason": "r"}).verdict is None


def test_from_dict_ignores_unknown_keys() -> None:
    c = Candle.from_dict({"ts": 1, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 3, "extra": "ignored"})
    assert c == Candle(1, 1, 2, 0.5, 1.5, 3)


def test_slots_prevent_typos() -> None:
    c = Candle(1, 1, 1, 1, 1)
    with pytest.raises(AttributeError):
        c.close = 2  # type: ignore[attr-defined]


def test_candle_rows_and_closed() -> None:
    c = Candle.from_row(["1791473520", "0.0007", "0.00071", "0.00069", "0.000705", "12.5"])
    assert c.ts == 1791473520 and c.c == 0.000705 and c.v == 12.5 and c.green
    assert c.to_row() == [1791473520, 0.0007, 0.00071, 0.00069, 0.000705, 12.5]
    assert Candle.from_row([1, 1, 1, 1, 1]).v == 0.0
    assert not c.is_closed(1791473520 + 59) and c.is_closed(1791473520 + 60)


def test_unit_helpers() -> None:
    assert lamports_to_sol(1_500_000_000) == 1.5
    assert sol_to_lamports(0.00204) == 2_040_000 and sol_to_lamports(0.1) == 100_000_000
    assert base_to_ui(16_239_400_281, 6) == pytest.approx(16239.400281)
    assert ui_to_base(16239.400281, 6) == 16_239_400_281
    assert ui_to_base(0.0000019, 6) == 1  # rounds down, never up
    # 0.1 SOL @ $108.85 for 16239.4 tokens -> $0.000670 per token
    assert effective_price_usd(100_000_000, 16_239_400_281, 6, 108.85) == pytest.approx(10.885 / 16239.400281)
    assert effective_price_usd(1, 0, 6, 100.0) == 0.0
    a, b = new_id("fill"), new_id("fill")
    assert a.startswith("fill_") and len(a) == 21 and a != b


def test_quote_helpers() -> None:
    q = SAMPLES[7]
    assert q.token_mint == MINT and q.is_insufficient_funds and not q.executable
    assert q.usd_value_loss_pct == pytest.approx((10.88 - 10.64) / 10.88 * 100)
    sell = Quote("sell", MINT, SOL_MINT, 5, 6, 0.1, 10, [], "r", "AQID", 0.0, None, None)
    assert sell.token_mint == MINT and sell.executable and sell.usd_value_loss_pct is None


def test_fill_deltas() -> None:
    buy = sample_fill()
    assert buy.sol_delta_lamports() == -(100_000_000 + 300_000 + TOKEN_ACCOUNT_RENT_LAMPORTS)
    assert buy.token_delta() == 16_239_400_281
    sell = sample_fill(side="sell", sol_lamports=98_000_000, rent_lamports=-TOKEN_ACCOUNT_RENT_LAMPORTS)
    assert sell.sol_delta_lamports() == 98_000_000 - 300_000 + TOKEN_ACCOUNT_RENT_LAMPORTS
    assert sell.token_delta() == -16_239_400_281


def test_position_pnl() -> None:
    p = Position("p", MINT, "HIGGS", None, 0.0, 6, token_amount=1_000_000_000, cost_lamports=100_000_000,
                 fees_lamports=300_000, rent_lamports=TOKEN_ACCOUNT_RENT_LAMPORTS)
    # 1000 tokens @ $0.02 = $20 = 0.2 SOL @ $100
    assert p.value_lamports(0.02, 100.0) == 200_000_000
    assert p.pnl_lamports(0.02, 100.0) == 200_000_000 - 100_000_000 - 300_000 - TOKEN_ACCOUNT_RENT_LAMPORTS
    assert p.pnl_lamports() == -100_000_000 - 300_000 - TOKEN_ACCOUNT_RENT_LAMPORTS
    assert p.value_lamports(0.02, 0.0) == 0 and p.is_open


def test_snapshot_ratio() -> None:
    s = SAMPLES[2]
    assert s.buy_sell_ratio_m5 == pytest.approx(0.75)
    assert MarketSnapshot("m", 0, None, None, None).buy_sell_ratio_m5 is None
    assert MarketSnapshot("m", 0, None, None, None, buys_m5=4).buy_sell_ratio_m5 == 4.0


def test_strategy_params_from_settings(settings) -> None:
    sp = StrategyParams.from_settings(settings)
    assert sp.stop_loss_pct == 0.18 and sp.confirm_green == 2
    with pytest.raises(dataclasses.FrozenInstanceError):
        sp.dip_pct = 0.1  # type: ignore[misc]  # frozen


def test_to_jsonable_handles_containers() -> None:
    from pathlib import Path

    out = to_jsonable({"t": (1, 2), "s": {3}, "p": Path("/data"), 4: SAMPLES[0]})
    assert out == {"t": [1, 2], "s": [3], "p": "/data", "4": SAMPLES[0].to_dict()}
    assert LAMPORTS_PER_SOL == 10**9
