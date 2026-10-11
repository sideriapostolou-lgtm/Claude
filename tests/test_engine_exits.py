"""Engine exits and risk arithmetic, tick-level over the fake world of ``test_engine``:

* G33 "blind means out": a position without a price for more than 30 s is priced by a Jupiter Ultra sell
  quote for the WHOLE position; two failed quotes in a row force an exit, retried every position interval
  (live: through the chain-truth rules of a full exit - nothing is written off on the holdings index alone);
* G23/G38 in the engine: every ticket is sized so that its rug fits the daily budget, the drawdown cushion
  and the total-at-risk cap, and exactly these entries of a losing day change.
"""

from __future__ import annotations

from typing import Any

import pytest

from fakes import FakeClock, FakeHttp
from nightcrawler import risk as risk_mod
from nightcrawler.broker.paper import PaperBroker
from nightcrawler.cocoon import Cocoon
from nightcrawler.crawler import Crawler
from nightcrawler.engine import BLIND_PRICE_MAX_AGE_S, BLIND_QUOTE_FAILURES, Engine
from nightcrawler.http import HttpClient
from nightcrawler.judge import Judge
from nightcrawler.ledger import Ledger
from nightcrawler.models import LAMPORTS_PER_SOL, SOL_MINT
from nightcrawler.radar import Radar
from nightcrawler.risk import RiskManager
from nightcrawler.sources import build_sources
from test_engine import Rig, fresh_rig, live_rig, notes
from world import GARY, SOL_USD, World, dip_rebound_candles, make_world

SOL = LAMPORTS_PER_SOL
#: The first ticket at $100: 20 % would risk $19 in a rug, more than the 15 % daily budget (G38).
FIRST_TICKET = int(0.15 * SOL / 0.95)


@pytest.fixture
def world(fake_http: FakeHttp, fake_clock: FakeClock) -> World:
    return make_world(fake_http, fake_clock)


@pytest.fixture
def make_rig(world: World, http_client: HttpClient, fake_clock: FakeClock, make_settings, tmp_path):
    ledgers: list[Ledger] = []

    def _make(*, broker: Any = None, broker_factory: Any = None, ledger_path: Any = None, **overrides: Any) -> Rig:
        settings = make_settings(**overrides)
        sources = build_sources(settings, http_client)
        ledger = Ledger(ledger_path or tmp_path / f"ledger{len(ledgers)}.db", clock=fake_clock)
        ledgers.append(ledger)
        if broker is None and broker_factory is not None:
            broker = broker_factory(sources, ledger, settings)
        broker = broker if broker is not None else PaperBroker(sources.jupiter, ledger, settings, fake_clock)
        engine = Engine(settings, clock=fake_clock, ledger=ledger, crawler=Crawler(sources, settings, fake_clock),
                        cocoon=Cocoon(sources, settings, fake_clock), radar=Radar(sources, settings, fake_clock),
                        judge=Judge(settings, clock=fake_clock, ledger=ledger),
                        risk=RiskManager(settings, ledger, fake_clock), broker=broker, sources=sources)
        return Rig(engine, ledger, broker, fake_clock, world, settings)

    yield _make
    for ledger in ledgers:
        ledger.close()


def go_blind(world: World) -> None:
    """Jupiter price v3 drops the coin (it does that for coins it flags right after a rug) and DexScreener
    returns nothing: the engine has no price for GARY. SOL keeps its price."""
    world.http.register("/price/v3", lambda req: {SOL_MINT: {"usdPrice": SOL_USD, "decimals": 9}})
    world.http.register("/tokens/v1/solana/", [])


def see_again(world: World) -> None:
    world.http.register("/price/v3", world.prices)
    world.http.register("/tokens/v1/solana/", world.dexscreener_tokens)


def sell_orders(world: World) -> list[Any]:
    return world.http.calls_to(f"inputMint={GARY}")


def break_sells(world: World) -> None:
    """Ultra answers every sell of GARY without amounts (no route): every sell quote fails."""
    world.http.register(f"inputMint={GARY}", {"errorMessage": "No routes found", "errorCode": 1})


def fix_sells(world: World) -> None:
    world.http.register(f"inputMint={GARY}", world.order)


# =========================================================================== G33: blind means out


def test_a_blind_position_is_priced_by_an_ultra_sell_quote_for_the_whole_position(make_rig, world) -> None:
    rig = make_rig()
    rig.tick()
    [position] = rig.ledger.open_positions()
    go_blind(world)
    world.price = 0.20e-3  # it rugged while the feeds went quiet
    rig.tick(10)
    rig.tick(10)  # 20 s without a price: still within BLIND_PRICE_MAX_AGE_S, nothing is quoted yet
    assert sell_orders(world) == [] and rig.ledger.open_positions()
    rig.tick(BLIND_PRICE_MAX_AGE_S - 20 + 1)  # 31 s: blind
    probe = sell_orders(world)[0]
    assert int(probe.params["amount"]) == position.token_amount  # the WHOLE position
    [closed] = rig.ledger.positions(status="closed")
    assert closed.exit_reason == "stop_loss"  # the quote's price is -57 %: the stop-loss sold it
    [exit_] = rig.ledger.decisions(actions=["exit"])
    assert exit_.inputs["price_source"] == "ultra_quote"
    assert exit_.inputs["price_now"] == pytest.approx(0.20e-3 * 0.988, rel=1e-3)  # Ultra's executable price


def test_a_blind_price_that_is_fine_keeps_the_position_and_marks_it(make_rig, world) -> None:
    rig = make_rig()
    rig.tick()
    go_blind(world)
    rig.tick(BLIND_PRICE_MAX_AGE_S + 1)
    [position] = rig.ledger.open_positions()
    assert len(sell_orders(world)) == 1 and position.last_marked_at == rig.clock.now()
    assert position.last_price_usd == pytest.approx(world.price * 0.988, rel=1e-3)
    rig.tick(10)  # still blind: quoted again every position interval
    assert len(sell_orders(world)) == 2 and rig.ledger.open_positions()
    see_again(world)
    rig.tick(10)  # the feed is back: no more quotes
    assert len(sell_orders(world)) == 2


def test_two_failed_quotes_force_an_exit_retried_every_interval(make_rig, world) -> None:
    rig = make_rig()
    rig.tick()
    go_blind(world)
    break_sells(world)
    rig.tick(BLIND_PRICE_MAX_AGE_S + 1)  # 1st failed quote: wait
    assert len(sell_orders(world)) == 1 and rig.decisions()[-1] == "enter"
    rig.tick(10)  # 2nd failed quote: an exit is tried at once (its own quote fails too)
    assert BLIND_QUOTE_FAILURES == 2 and len(sell_orders(world)) == 3
    [hold] = rig.ledger.decisions(actions=["hold"])
    assert hold.reason.startswith("blind_exit: sell quote failed")
    rig.tick(10)  # retried every position interval: one exit quote each, no more probes
    rig.tick(10)
    assert len(sell_orders(world)) == 5 and rig.ledger.open_positions()
    fix_sells(world)
    rig.tick(10)
    [closed] = rig.ledger.positions(status="closed")
    assert closed.exit_reason == "blind_exit" and len(sell_orders(world)) == 6
    assert rig.ledger.verify_chain() == (True, None)


def test_a_price_that_comes_back_resets_the_failed_quotes(make_rig, world) -> None:
    rig = make_rig()
    rig.tick()
    go_blind(world)
    break_sells(world)
    rig.tick(BLIND_PRICE_MAX_AGE_S + 1)  # one failed quote
    see_again(world)
    rig.tick(10)  # priced again by the feed
    go_blind(world)
    rig.tick(BLIND_PRICE_MAX_AGE_S + 1)  # blind again: one failed quote is not two in a row
    assert rig.ledger.decisions(actions=["hold", "exit"]) == [] and rig.ledger.open_positions()
    rig.tick(10)
    assert rig.ledger.decisions(actions=["hold"])[0].reason.startswith("blind_exit")


def test_a_blind_position_past_its_time_stop_still_tries_to_leave(make_rig, world) -> None:
    rig = make_rig()
    rig.tick()
    go_blind(world)
    break_sells(world)
    rig.tick(rig.settings.max_hold_min * 60 + 1)
    [hold] = rig.ledger.decisions(actions=["hold"])
    assert hold.reason.startswith("time_stop: sell quote failed")


def test_a_blind_live_exit_follows_the_chain_truth_rules(make_rig, world, fake_clock) -> None:
    """Live, the probe quotes the books; the wallet holds less (sold by hand), so Ultra says "Insufficient
    funds" twice and the exit is forced. It sells what the wallet holds and writes off the rest only once
    the holdings had time to settle AND the chain confirmed the balance (F10 + the chain-truth fix round)."""
    rig = live_rig(make_rig, world, fake_clock)
    rig.tick()
    [position] = rig.ledger.open_positions()
    rig.broker.tokens[GARY] = position.token_amount // 2  # half sold by hand in Phantom
    chain_reads: list[str] = []
    read = rig.broker.chain_token_balance

    def chain(mint: str) -> int:
        chain_reads.append(mint)
        return read(mint)

    rig.broker.chain_token_balance = chain
    go_blind(world)
    rig.tick(BLIND_PRICE_MAX_AGE_S + 1)  # probe of the whole position: Insufficient funds
    rig.tick(10)  # second failure -> forced exit; holdings may still be settling: the books are tried
    assert rig.ledger.open_positions() and chain_reads == [] and notes(rig, "exit_shortfall") == []
    rig.tick(30)  # past HOLDINGS_SETTLE_S: the chain says half -> sell it, write the rest off
    [closed] = rig.ledger.positions(status="closed")
    assert closed.exit_reason == "blind_exit" and chain_reads == [GARY]
    [shortfall] = notes(rig, "exit_shortfall")
    assert shortfall["written_off"] == position.token_amount - position.token_amount // 2


def test_a_blind_live_exit_never_writes_off_on_the_index_alone(make_rig, world, fake_clock) -> None:
    from nightcrawler.sources.solana_rpc import RpcError

    rig = live_rig(make_rig, world, fake_clock)
    rig.tick()
    [position] = rig.ledger.open_positions()
    rig.broker.tokens[GARY] = position.token_amount // 2

    def chain_down(_mint: str) -> int:
        raise RpcError("rpc down")

    rig.broker.chain_token_balance = chain_down
    go_blind(world)
    for advance in (BLIND_PRICE_MAX_AGE_S + 1, 10, 30, 10):
        rig.tick(advance)
    [still] = rig.ledger.open_positions()
    assert still.token_amount == position.token_amount and notes(rig, "exit_shortfall") == []
    assert rig.ledger.decisions(actions=["hold"])[0].reason.startswith("blind_exit")


# =========================================================================== G23/G38 in the engine


def test_the_first_entry_is_sized_to_the_daily_risk_budget(make_rig) -> None:
    rig = make_rig()
    rig.tick()
    [buy] = rig.ledger.fills()
    assert buy.sol_lamports == FIRST_TICKET
    [enter] = rig.ledger.decisions(actions=["enter"])
    sizing = enter.inputs["sizing"]
    assert sizing["size_lamports"] == FIRST_TICKET and sizing["risk_cap_lamports"] == FIRST_TICKET
    assert sizing["risk_cap_by"] == "daily_budget" and sizing["at_risk_lamports"] == 0


def test_a_second_coin_waits_while_the_first_ticket_uses_the_budget(make_rig) -> None:
    rig = make_rig()
    rig.tick()
    [position] = rig.ledger.open_positions()
    equity, sol_usd, _ = rig.engine._equity_now()
    ok, reason = rig.engine.risk.can_open("Other1111111111111111111111111111111111111pump",
                                          rig.engine._open_positions(), equity, sol_usd=sol_usd)
    assert not ok and reason.startswith("[risk_budget]")  # one $15.79 rug fills the 15 % budget


def losing_day(rig: Rig, setups: int = 4) -> None:
    """``setups`` dip-rebound setups 31 minutes apart (past the cooldown); every entry rugs to -46 %."""
    for i in range(setups):
        if i:
            rig.world.price = 0.46e-3
            rig.world.candles = dip_rebound_candles(rig.clock.now() + 31 * 60)
        rig.tick(31 * 60 if i else 0)
        if rig.ledger.open_positions():
            rig.world.price = 0.25e-3
            rig.tick(10)


def entries(rig: Rig) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for d in reversed(rig.ledger.decisions(limit=1000)):
        if d.action == "enter":
            out.append(("enter", d.inputs["sizing"]["size_lamports"]))
        elif d.action == "reject_risk":
            out.append(("reject_risk", d.reason.split("]", 1)[0] + "]"))
        elif d.action == "exit":
            out.append(("exit", d.reason))
    return out


def test_new_risk_rules_change_exactly_these_entries(tmp_path, make_settings, monkeypatch) -> None:
    """The same losing day (four setups, every entry rugs to -46 %) under the old arithmetic (stop-distance
    risk: L_MAX 0, no budget, no cap) and under today's rules. Only the entries change: smaller tickets,
    and the third setup is refused by the daily budget instead of the fourth by the daily loss limit."""
    with monkeypatch.context() as m:
        m.setattr(risk_mod, "L_MAX", 0.0)
        legacy = fresh_rig(tmp_path, make_settings, "legacy", DAILY_RISK_BUDGET_PCT=1, MAX_AT_RISK_PCT=1)
        try:
            losing_day(legacy)
            old = entries(legacy)
        finally:
            legacy.ledger.close()
    now = fresh_rig(tmp_path, make_settings, "now")
    try:
        losing_day(now)
        new = entries(now)
        start = now.ledger.equity_series()[0].equity_lamports  # today's first snapshot (after entry 1)
        first, second = [d.inputs["sizing"] for d in reversed(now.ledger.decisions(actions=["enter"]))]
        refusals = now.ledger.decisions(actions=["reject_risk"])
    finally:
        now.ledger.close()
    # old: 20 % tickets until the realized day loss passed 20 %
    assert [a for a, _ in old] == ["enter", "exit", "enter", "exit", "enter", "exit", "reject_risk"]
    assert old[0][1] == 200_000_000 and old[-1][1] == "[daily_loss]"
    # new: the first ticket fits a rug into 15 % of the day, the second the rest of the budget, then no more
    assert [a for a, _ in new] == ["enter", "exit", "enter", "exit", "reject_risk", "reject_risk"]
    assert new[0][1] == first["size_lamports"] == FIRST_TICKET
    assert new[2][1] == second["size_lamports"] == int(
        (0.15 * start - (start - second["equity_lamports"])) / 0.95)
    assert new[4][1] == new[5][1] == "[risk_budget]"
    assert len(refusals) == 2 and all("worst case today" in d.reason for d in refusals)
    # the exits themselves are the same rules on the same prices
    assert [r for a, r in old if a == "exit"][:2] == [r for a, r in new if a == "exit"] == ["stop_loss"] * 2


def test_the_risk_record_names_the_binding_budget_on_a_refusal(make_rig, world) -> None:
    rig = make_rig(DAILY_RISK_BUDGET_PCT=0.03)  # less than one $5 rug: nothing fits
    rig.tick()
    [reject] = rig.ledger.decisions(actions=["reject_risk"])
    assert reject.reason.startswith("[risk_budget]") and rig.ledger.fills() == []
    assert reject.inputs["sizing"]["equity_lamports"] > 0


def test_a_tiny_budget_never_rounds_a_ticket_up_to_the_minimum(make_rig, world) -> None:
    rig = make_rig(DAILY_RISK_BUDGET_PCT=0.06)  # room for a $6.32 ticket: bought at exactly that size
    rig.tick()
    [buy] = rig.ledger.fills()
    assert buy.sol_lamports == int(0.06 * SOL / 0.95)
