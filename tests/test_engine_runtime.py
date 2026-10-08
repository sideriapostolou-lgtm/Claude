"""Engine runtime/data-source fixes, tick-level over the fake world of ``test_engine``:

* candles: GeckoTerminal first, pump.fun when GT fails, rate-limits or lags (one source per series);
* RT-14: the watchlist and the crawler nursery survive a redeploy (ledger kv, bounded, age-expired);
* F10: a full exit sells what the wallet really holds and writes off the difference;
* F3: live positions record their wallet; another wallet's positions are never managed;
* F5: an unknown live swap is settled from its signature status as soon as the chain is final;
* RT-9 (engine part): the exits-only safe mode.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

from fakes import FakeClock, FakeHttp
from nightcrawler import engine as engine_mod
from nightcrawler.audit import Auditor
from nightcrawler.broker.base import SwapUnknown
from nightcrawler.broker.paper import PaperBroker
from nightcrawler.cocoon import Cocoon
from nightcrawler.crawler import Crawler
from nightcrawler.engine import (
    HOLDINGS_SETTLE_S,
    RECONCILE_AFTER_S,
    SIGNATURE_CHECK_S,
    STATE_SAVE_S,
    Engine,
    build_app,
)
from nightcrawler.http import HttpClient
from nightcrawler.judge import Judge
from nightcrawler.ledger import Ledger
from nightcrawler.models import SOL_MINT, Candle, SafetyReport, TokenCandidate
from nightcrawler.radar import Radar
from nightcrawler.risk import RiskManager
from nightcrawler.sources import build_sources
from nightcrawler.sources import pumpfun as pumpfun_mod
from nightcrawler.sources.pumpfun import PumpFunClient
from nightcrawler.sources.solana_rpc import RpcError
from test_engine import LIVE, FakeLiveBroker, NoJudge, Rig, live_rig, notes
from world import GARY, RISKY, World, dip_rebound_candles, iso, make_world

OLD_WALLET = "OLDwa11etAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
NEW_WALLET = "NEWwa11etBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"


@pytest.fixture
def world(fake_http: FakeHttp, fake_clock: FakeClock) -> World:
    return make_world(fake_http, fake_clock)


@pytest.fixture
def make_rig(world: World, http_client: HttpClient, fake_clock: FakeClock, make_settings,
             tmp_path) -> Callable[..., Rig]:
    """Like ``test_engine.make_rig`` plus the pump.fun candle client (``pumpfun=False`` leaves it out)."""
    ledgers: list[Ledger] = []

    def _make(*, judge: Any = None, broker: Any = None, broker_factory: Any = None, ledger_path: Any = None,
              pumpfun: bool = True, **overrides: Any) -> Rig:
        settings = make_settings(**overrides)
        sources = build_sources(settings, http_client)
        ledger = Ledger(ledger_path or tmp_path / f"ledger{len(ledgers)}.db", clock=fake_clock)
        ledgers.append(ledger)
        if broker is None and broker_factory is not None:
            broker = broker_factory(sources, ledger, settings)
        broker = broker if broker is not None else PaperBroker(sources.jupiter, ledger, settings, fake_clock)
        engine = Engine(settings, clock=fake_clock, ledger=ledger, crawler=Crawler(sources, settings, fake_clock),
                        cocoon=Cocoon(sources, settings, fake_clock), radar=Radar(sources, settings, fake_clock),
                        judge=judge or Judge(settings, clock=fake_clock, ledger=ledger),
                        risk=RiskManager(settings, ledger, fake_clock), broker=broker, sources=sources,
                        pumpfun=PumpFunClient(http_client) if pumpfun else None)
        return Rig(engine, ledger, broker, fake_clock, world, settings)

    yield _make
    for ledger in ledgers:
        ledger.close()


def serve_pumpfun(world: World) -> None:
    """pump.fun's candle API over the world's candles: the latest ``limit`` traded minutes, ascending."""

    def respond(req: Any) -> list[dict[str, Any]]:
        limit = int(req.params["limit"])
        rows = [c for c in world.candles if c.ts <= world.clock.now()][-limit:]
        return [{"timestamp": c.ts * 1000, "open": repr(c.o), "high": repr(c.h), "low": repr(c.l),
                 "close": repr(c.c), "volume": repr(c.v)} for c in rows]

    world.http.register(pumpfun_mod.HOST, respond)


def gt_rate_limited(world: World) -> None:
    world.http.register("/ohlcv/minute", {"errors": [{"status": "429", "title": "Too many requests"}]}, status=429)


def gt_serves(world: World, candles: list[Candle]) -> None:
    rows = [c.to_row() for c in reversed(candles)]
    world.http.register("/ohlcv/minute", {"data": {"attributes": {"ohlcv_list": rows}}})


def enter_inputs(rig: Rig) -> dict[str, Any]:
    [enter] = rig.ledger.decisions(actions=["enter"])
    return enter.inputs


# =========================================================================== candles: GeckoTerminal, then pump.fun


def test_geckoterminal_candles_are_used_first_and_pumpfun_is_not_asked(make_rig, world) -> None:
    serve_pumpfun(world)
    rig = make_rig()
    rig.tick()
    assert len(rig.ledger.fills()) == 1
    assert enter_inputs(rig)["candle_source"] == "geckoterminal"
    assert world.http.calls_to(pumpfun_mod.HOST) == []


def test_pumpfun_candles_replace_a_rate_limited_geckoterminal(make_rig, world) -> None:
    serve_pumpfun(world)
    gt_rate_limited(world)
    rig = make_rig()
    rig.tick()
    assert len(rig.ledger.fills()) == 1  # the setup was still seen and traded
    assert enter_inputs(rig)["candle_source"] == "pumpfun"
    assert rig.engine.watchlist[GARY].candle_source == "pumpfun"


def test_pumpfun_candles_replace_lagging_geckoterminal_candles(make_rig, world, fake_clock) -> None:
    serve_pumpfun(world)
    gt_serves(world, dip_rebound_candles(fake_clock.now() - 11 * 60))  # GT 11 minutes behind
    rig = make_rig()
    rig.tick()
    assert enter_inputs(rig)["candle_source"] == "pumpfun"


def test_a_lagging_series_is_never_patched_with_the_other_source(make_rig, world, fake_clock) -> None:
    serve_pumpfun(world)
    world.http.register(pumpfun_mod.HOST, [])  # pump.fun has nothing either
    gt_serves(world, dip_rebound_candles(fake_clock.now() - 11 * 60))
    rig = make_rig()
    rig.tick()
    item = rig.engine.watchlist[GARY]
    assert rig.ledger.fills() == [] and item.candle_source == "geckoterminal"
    assert "stale" in (item.last_signal_reason or "")
    assert {c.ts for c in item.candles} <= {c.ts for c in dip_rebound_candles(fake_clock.now() - 11 * 60)}


def test_a_coin_trading_outside_pumpfun_never_uses_its_candles(make_rig, world) -> None:
    serve_pumpfun(world)
    gt_rate_limited(world)
    original = world.pair
    world.pair = lambda mint: {**original(mint), "dexId": "raydium"}  # type: ignore[method-assign]
    rig = make_rig()
    results = rig.tick()
    assert results["watch"] == "ok" and rig.ledger.fills() == []
    assert world.http.calls_to(pumpfun_mod.HOST) == []
    assert "candles unavailable" in (rig.engine.watchlist[GARY].last_signal_reason or "")


def test_both_candle_sources_down_is_no_entry_and_no_stage_error(make_rig, world) -> None:
    gt_rate_limited(world)
    world.http.register(pumpfun_mod.HOST, "<html>Attention Required! | Cloudflare</html>", status=403)
    rig = make_rig()
    results = rig.tick()
    assert results["watch"] == "ok" and rig.ledger.fills() == []
    assert "candles unavailable" in (rig.engine.watchlist[GARY].last_signal_reason or "")


def test_the_pumpfun_fallback_can_be_switched_off(make_rig, world) -> None:
    serve_pumpfun(world)
    gt_rate_limited(world)
    rig = make_rig(PUMPFUN_CANDLES=False)
    rig.tick()
    assert rig.ledger.fills() == [] and world.http.calls_to(pumpfun_mod.HOST) == []


def test_a_geckoterminal_429_pauses_its_candle_calls(make_rig, world, monkeypatch) -> None:
    monkeypatch.setattr(engine_mod, "GT_CANDLE_PAUSE_S", 300.0)
    serve_pumpfun(world)
    gt_rate_limited(world)
    rig = make_rig(judge=NoJudge(), ANTHROPIC_API_KEY="sk-ant-test-key-000", JUDGE_MODE="required")
    rig.tick()
    gt_calls = len(world.http.calls_to("/ohlcv/minute"))
    assert gt_calls >= 1 and len(world.http.calls_to(pumpfun_mod.HOST)) == 1
    rig.tick(60)  # re-evaluated while GT is paused: straight to pump.fun, GT's budget is left alone
    assert len(world.http.calls_to("/ohlcv/minute")) == gt_calls
    assert len(world.http.calls_to(pumpfun_mod.HOST)) == 2
    rig.tick(300)
    assert len(world.http.calls_to("/ohlcv/minute")) > gt_calls  # tried again after the pause


def test_build_app_wires_pumpfun_with_its_own_rate_bucket(make_settings, fake_clock) -> None:
    app = build_app(make_settings(), fake_clock, session=FakeHttp())
    try:
        assert isinstance(app.engine.pumpfun, PumpFunClient)
        assert app.http.limiter.limits[pumpfun_mod.HOST] == pumpfun_mod.RATE_LIMIT
    finally:
        app.close()
    app = build_app(make_settings(PUMPFUN_CANDLES=False), fake_clock, session=FakeHttp())
    try:
        assert app.engine.pumpfun is None
    finally:
        app.close()


# =========================================================================== RT-11: launchpad deployers end to end


def test_a_coin_from_a_shared_launchpad_deployer_passes_prefilter_and_cocoon(make_rig, world) -> None:
    from nightcrawler.crawler import KNOWN_LAUNCHPAD_DEPLOYERS

    deployer = next(a for a, label in KNOWN_LAUNCHPAD_DEPLOYERS.items() if "pump.fun" in label)
    world.trending[0]["dev"] = deployer
    world.trending[0]["audit"]["devMints"] = 169_827  # the platform's count, not the creator's
    rig = make_rig(KILL_SWITCH="stop")
    rig.tick()
    assert GARY in rig.engine.watchlist
    assert [d.mint for d in rig.ledger.decisions(actions=["reject_cocoon"])] == [RISKY]


def test_a_serial_creator_is_still_rejected(make_rig, world) -> None:
    world.trending[0]["audit"]["devMints"] = 7_306  # one person (or bot) launching thousands of coins
    rig = make_rig(KILL_SWITCH="stop")
    rig.tick()
    assert GARY not in rig.engine.watchlist
    assert rig.engine.prefilter_reasons["serial launcher"] == 1


# =========================================================================== RT-14: state survives a redeploy


def test_the_watchlist_survives_a_redeploy(make_rig, tmp_path) -> None:
    path = tmp_path / "ledger.db"
    rig = make_rig(ledger_path=path, KILL_SWITCH="stop")
    rig.tick()
    item = rig.engine.watchlist[GARY]
    rig.ledger.close()  # killed: no graceful shutdown

    rig2 = make_rig(ledger_path=path, KILL_SWITCH="stop")
    rig2.tick(60)
    restored = rig2.engine.watchlist[GARY]
    assert restored.added_at == item.added_at and restored.safety.passed
    assert restored.candidate.symbol == "Gary" and restored.snapshot_at is not None
    assert [d.mint for d in rig2.ledger.decisions(actions=["watch"], limit=100)] == [GARY]  # never re-added
    assert rig2.ledger.get_kv("engine.watchlist")["items"][0]["candidate"]["mint"] == GARY


def test_a_restored_watchlist_item_older_than_the_ttl_expires(make_rig, tmp_path, fake_clock) -> None:
    path = tmp_path / "ledger.db"
    rig = make_rig(ledger_path=path, KILL_SWITCH="stop")
    rig.tick()
    rig.ledger.close()
    fake_clock.advance(7 * 3600)  # down for 7 h (WATCHLIST_TTL_H = 6)
    rig2 = make_rig(ledger_path=path, KILL_SWITCH="stop")
    rig2.tick()
    [unwatch] = rig2.ledger.decisions(actions=["unwatch"])
    assert unwatch.mint == GARY and unwatch.reason.startswith("expired after 6 h")
    assert rig2.engine.watchlist[GARY].added_at == fake_clock.now()  # rediscovered and checked afresh


def test_the_watchlist_restore_is_bounded_and_skips_garbage(make_rig, fake_clock) -> None:
    rig = make_rig(KILL_SWITCH="stop", WATCHLIST_MAX=2)
    now = fake_clock.now()
    mints = [f"Mint{i}" + "1" * 39 for i in range(3)]
    items = [{"candidate": TokenCandidate(mint=m, symbol=f"M{i}").to_dict(),
              "safety": SafetyReport(mint=m, passed=True, checked_at=now).to_dict(), "added_at": now - 60 * i}
             for i, m in enumerate(mints)]
    rig.ledger.set_kv("engine.watchlist", {"saved_at": now, "items": [*items, {"candidate": {}}, "junk",
                                                                       {"candidate": {"mint": RISKY}}]})
    rig.engine._restore_state()
    assert set(rig.engine.watchlist) == set(mints[:2])  # the newest WATCHLIST_MAX


def test_the_nursery_survives_a_redeploy(make_rig, world, tmp_path, fake_clock) -> None:
    world.trending[0]["firstPool"]["createdAt"] = iso(fake_clock.now() - 30 * 60)  # GARY is 30 min old
    path = tmp_path / "ledger.db"
    rig = make_rig(ledger_path=path, KILL_SWITCH="stop")
    rig.tick()
    assert GARY in rig.engine.crawler.nursery and GARY not in rig.engine.watchlist
    rig.engine.stop()
    rig.engine.run_forever()  # SIGTERM of a redeploy: the shutdown saves the nursery
    rig.ledger.close()

    world.trending = []  # the young coin is no longer listed anywhere
    rig2 = make_rig(ledger_path=path, KILL_SWITCH="stop")
    rig2.tick(31 * 60)
    assert GARY in rig2.engine.watchlist  # matured from the restored nursery, refreshed and cocoon-checked


def test_candidates_waiting_for_the_cocoon_survive_a_redeploy(make_rig, tmp_path, fake_clock) -> None:
    path = tmp_path / "ledger.db"
    rig = make_rig(ledger_path=path, KILL_SWITCH="stop")
    waiting = [TokenCandidate(mint=f"Mint{i}" + "1" * 39, symbol=f"W{i}", created_at=fake_clock.now() - 7200)
               for i in range(2)]
    too_old = TokenCandidate(mint="Old" + "1" * 40, symbol="OLD", created_at=fake_clock.now() - 49 * 3600)
    rig.engine.queue.extend([*waiting, too_old])
    rig.engine.save_state(fake_clock.now())
    rig.ledger.close()

    rig2 = make_rig(ledger_path=path, KILL_SWITCH="stop")
    rig2.engine._restore_state()
    assert [c.mint for c in rig2.engine.queue] == [c.mint for c in waiting]  # past MAX_AGE_H: dropped
    rig3 = make_rig(ledger_path=path, KILL_SWITCH="stop")
    fake_clock.advance(engine_mod.QUEUE_RESTORE_MAX_AGE_S + 1)
    rig3.engine._restore_state()
    assert list(rig3.engine.queue) == []  # saved too long ago: discovery starts afresh


def test_state_is_also_saved_periodically(make_rig, world, fake_clock) -> None:
    world.trending[0]["firstPool"]["createdAt"] = iso(fake_clock.now() - 30 * 60)
    rig = make_rig(KILL_SWITCH="stop")
    rig.tick()
    rig.tick(STATE_SAVE_S)
    saved = rig.ledger.get_kv("crawler.nursery")
    assert [item["mint"] for item in saved["items"]] == [GARY]


# =========================================================================== F10: exits sell what the wallet holds


def sells(rig: Rig) -> list[Any]:
    return sorted((f for f in rig.ledger.fills(limit=None) if f.side == "sell"), key=lambda f: -f.sol_lamports)


def test_a_full_exit_sells_what_the_paper_wallet_holds_and_writes_off_the_rest(make_rig, world) -> None:
    rig = make_rig()
    rig.tick()
    [position] = rig.ledger.open_positions()
    held = position.token_amount * 7 // 10
    tokens = rig.ledger.get_kv("paper.tokens")
    rig.ledger.set_kv("paper.tokens", {**tokens, GARY: held})  # 30 % vanished from the virtual wallet
    world.price *= 0.5  # stop loss
    rig.tick(10)
    closed = rig.ledger.get_position(position.id)
    assert closed.status == "closed" and closed.token_amount == 0 and closed.exit_reason == "stop_loss"
    sale, write_off = sells(rig)
    assert sale.token_amount == held and sale.sol_lamports > 0
    assert write_off.token_amount == position.token_amount - held and write_off.sol_lamports == 0
    [note] = notes(rig, "exit_shortfall")
    assert (note["books"], note["wallet"], note["written_off"]) == (position.token_amount, held,
                                                                    position.token_amount - held)
    report = Auditor(rig.ledger, rig.broker, rig.clock).reconcile()
    assert report.ok, report.issues


def test_a_full_exit_of_tokens_the_paper_wallet_no_longer_has_closes_the_books(make_rig, world) -> None:
    rig = make_rig()
    rig.tick()
    [position] = rig.ledger.open_positions()
    tokens = rig.ledger.get_kv("paper.tokens")
    tokens.pop(GARY)
    rig.ledger.set_kv("paper.tokens", tokens)
    world.price *= 0.5
    rig.tick(10)
    closed = rig.ledger.get_position(position.id)
    assert closed.status == "closed" and closed.token_amount == 0
    assert world.http.calls_to(f"outputMint={SOL_MINT}") == []  # nothing to sell: no quote, no swap
    [write_off] = sells(rig)
    assert write_off.token_amount == position.token_amount and write_off.sol_lamports == 0
    exits = rig.ledger.decisions(actions=["exit"])
    assert exits and "written off" in exits[0].reason
    assert Auditor(rig.ledger, rig.broker, rig.clock).reconcile().ok


def test_a_live_exit_after_a_manual_sale_sells_the_rest_and_clears_the_drift(make_rig, world, fake_clock) -> None:
    rig = live_rig(make_rig, world, fake_clock)
    rig.tick()
    [position] = rig.ledger.open_positions()
    rig.broker.tokens[GARY] = position.token_amount // 2  # half sold by hand in Phantom
    world.price *= 0.5
    rig.tick(HOLDINGS_SETTLE_S)
    closed = rig.ledger.get_position(position.id)
    assert closed.status == "closed" and rig.broker.tokens[GARY] == 0
    sale, write_off = sells(rig)
    assert sale.token_amount == position.token_amount // 2
    assert write_off.token_amount == position.token_amount - position.token_amount // 2
    rig.engine.check_drift(fake_clock.now())
    assert rig.engine.drift == {}


@pytest.mark.parametrize("lands", [True, False])
def test_an_unknown_short_exit_is_reconciled_against_what_the_wallet_held_before(make_rig, world, fake_clock,
                                                                                lands: bool) -> None:
    """Books 100, wallet 50, the sale of the 50 has an unknown outcome. The wallet must be compared with
    the 50 it held before the swap: comparing it with the books would read the old shortfall as a sale."""
    from test_engine import _timeout

    rig = live_rig(make_rig, world, fake_clock)
    rig.tick()
    [position] = rig.ledger.open_positions()
    held = position.token_amount // 2
    rig.broker.tokens[GARY] = held
    if lands:
        rig.broker.after_land = _timeout
    else:
        rig.broker.refuse = SwapUnknown("Ultra execute outcome unknown (connection reset)")
    world.price *= 0.5
    rig.tick(HOLDINGS_SETTLE_S)
    entry = rig.engine.unresolved[GARY]
    assert (entry["wallet_before"], entry["write_off"]) == (held, position.token_amount - held)
    rig.broker.refuse = None
    rig.tick(RECONCILE_AFTER_S)  # reconcile; then (did not land) the stop-loss sells again with a FRESH quote
    [note] = notes(rig, "reconcile")
    assert note["landed"] is lands
    # either way: ONE real sale of the 50 the wallet had, the other 50 written off, books == wallet
    assert rig.ledger.get_position(position.id).status == "closed" and rig.broker.tokens[GARY] == 0
    assert [f.token_amount for f in sells(rig)] == [held, position.token_amount - held]
    assert rig.broker.executed == ["buy", "sell"]


def test_a_live_balance_that_may_still_be_indexing_is_not_written_off(make_rig, world, fake_clock) -> None:
    rig = live_rig(make_rig, world, fake_clock)
    rig.tick()
    [position] = rig.ledger.open_positions()
    rig.broker.tokens[GARY] = 0  # Ultra holdings have not caught up with the fresh buy yet
    world.price *= 0.5
    rig.tick(10)
    assert rig.ledger.get_position(position.id).is_open and notes(rig, "exit_shortfall") == []
    assert rig.ledger.decisions(actions=["hold"])  # the stop-loss is retried, nothing written off
    rig.broker.tokens[GARY] = position.token_amount  # it was only lag
    rig.tick(HOLDINGS_SETTLE_S)
    [sale] = sells(rig)
    assert sale.token_amount == position.token_amount and not rig.ledger.get_position(position.id).is_open


def test_an_unreadable_wallet_never_writes_anything_off(make_rig, world, fake_clock, monkeypatch) -> None:
    rig = live_rig(make_rig, world, fake_clock)
    rig.tick()
    [position] = rig.ledger.open_positions()

    def down() -> Any:
        raise RuntimeError("holdings API down")

    monkeypatch.setattr(rig.broker, "balances", down)
    world.price *= 0.5
    rig.tick(HOLDINGS_SETTLE_S)
    [sale] = sells(rig)
    assert sale.token_amount == position.token_amount and notes(rig, "exit_shortfall") == []


def test_a_full_exit_never_sells_more_than_the_books(make_rig, world, fake_clock) -> None:
    rig = live_rig(make_rig, world, fake_clock)
    rig.tick()
    [position] = rig.ledger.open_positions()
    rig.broker.tokens[GARY] += 1_000_000  # an airdrop on top
    world.price *= 0.5
    rig.tick(HOLDINGS_SETTLE_S)
    [sale] = sells(rig)
    assert sale.token_amount == position.token_amount and rig.broker.tokens[GARY] == 1_000_000


# =========================================================================== F3: live positions belong to a wallet


def test_a_live_position_records_its_wallet(make_rig, world, fake_clock) -> None:
    rig = live_rig(make_rig, world, fake_clock)
    rig.broker.pubkey = NEW_WALLET
    rig.tick()
    [position] = rig.ledger.open_positions()
    assert rig.ledger.position_wallets() == {position.id: NEW_WALLET}


def test_positions_of_another_wallet_are_never_managed_and_are_surfaced(make_rig, world, fake_clock,
                                                                        tmp_path) -> None:
    path = tmp_path / "live.db"
    old = live_rig(make_rig, world, fake_clock, path=path)
    old.broker.pubkey = OLD_WALLET
    old.tick()
    [position] = old.ledger.open_positions()
    old.ledger.close()

    rig = live_rig(make_rig, world, fake_clock, path=path, KILL_SWITCH="stop")  # BOT_WALLET_SECRET changed
    rig.broker.pubkey = NEW_WALLET
    rig.engine._boot_checks(fake_clock.now())
    [note] = notes(rig, "foreign_positions")
    assert note["wallet"] == NEW_WALLET and note["positions"][0]["id"] == position.id
    assert note["positions"][0]["wallet"] == OLD_WALLET
    assert rig.ledger.get_kv("engine.foreign_positions")[0]["id"] == position.id
    world.price *= 0.5  # its stop-loss level: but the tokens are not in THIS wallet
    rig.tick(10)
    assert [q for q in rig.broker.quotes if q.side == "sell"] == []
    assert [d for d in rig.ledger.decisions(limit=100) if d.action in ("hold", "exit")] == []
    assert rig.ledger.get_position(position.id).is_open and rig.engine.sell_all("kill_switch") == []
    status = rig.ledger.get_kv("engine.status")
    assert status["foreign_positions"][0]["wallet"] == OLD_WALLET
    equity, _sol_usd, balances = rig.engine._equity_now()
    assert equity == balances.sol_lamports  # no phantom value from the other wallet


# =========================================================================== F5: settle unknown swaps from the chain


class ChainBroker(FakeLiveBroker):
    """FakeLiveBroker whose sent swaps have a signature status on a fake chain; like LiveBroker it
    reports each transaction's signature (``on_signed``) right before sending it."""

    reports_signature = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.chain: dict[str, Any] = {}
        self.status_calls: list[str] = []

    def execute(self, quote: Any, position: Any, *, symbol: str = "", on_fill: Any = None,
                on_signed: Any = None) -> Any:
        if on_signed is not None:
            on_signed(f"sig-{quote.request_id}")
        return super().execute(quote, position, symbol=symbol, on_fill=on_fill)

    def swap_status(self, signature: str) -> str | None:
        self.status_calls.append(signature)
        status = self.chain.get(signature)
        if isinstance(status, Exception):
            raise status
        return status


def chain_rig(make_rig: Callable[..., Rig], world: World, clock: FakeClock, **overrides: Any) -> Rig:
    def factory(_sources: Any, ledger: Ledger, _settings: Any) -> ChainBroker:
        return ChainBroker(world, ledger, clock)

    return make_rig(broker_factory=factory, **{**LIVE, **overrides})


def unknown(signature: str) -> SwapUnknown:
    exc = SwapUnknown("Ultra execute outcome unknown (read timed out)")
    exc.signature = signature  # type: ignore[attr-defined]
    return exc


def landed_then_unknown(signature: str) -> Callable[[Any], None]:
    def hook(_fill: Any) -> None:
        raise unknown(signature)

    return hook


def test_an_unknown_swap_is_booked_as_soon_as_the_chain_confirms_it(make_rig, world, fake_clock) -> None:
    rig = chain_rig(make_rig, world, fake_clock, WATCH_INTERVAL_S=600)
    rig.broker.after_land = landed_then_unknown("sigA")
    rig.tick()
    assert rig.engine.unresolved[GARY]["signature"] == "sigA" and not rig.engine.entries_allowed
    rig.broker.chain["sigA"] = "landed"
    rig.tick(SIGNATURE_CHECK_S)  # long before RECONCILE_AFTER_S
    assert rig.engine.unresolved == {} and rig.engine.entries_allowed
    [position] = rig.ledger.open_positions()
    assert position.token_amount == rig.broker.tokens[GARY]
    [note] = notes(rig, "reconcile")
    assert note["landed"] is True and note["chain"] == "landed" and note["signature"] == "sigA"


def test_an_unknown_swap_that_failed_on_chain_unblocks_entries_at_once(make_rig, world, fake_clock) -> None:
    rig = chain_rig(make_rig, world, fake_clock, WATCH_INTERVAL_S=600)
    rig.broker.refuse = unknown("sigB")  # nothing landed
    rig.tick()
    assert GARY in rig.engine.unresolved
    rig.broker.refuse = None
    rig.broker.chain["sigB"] = "failed"
    rig.tick(1)
    assert rig.engine.unresolved == {} and rig.engine.entries_allowed and rig.ledger.fills() == []
    [note] = notes(rig, "reconcile")
    assert note["landed"] is False and "failed on chain" in note["result"]


def test_without_a_final_status_the_wallet_decides_after_the_wait(make_rig, world, fake_clock) -> None:
    rig = chain_rig(make_rig, world, fake_clock, WATCH_INTERVAL_S=600)
    rig.broker.after_land = landed_then_unknown("sigC")
    rig.tick()
    for _ in range(3):
        rig.tick(SIGNATURE_CHECK_S)
    assert GARY in rig.engine.unresolved and rig.broker.status_calls  # asked, but no final answer
    rig.broker.chain["sigC"] = RpcError(-32005, "node is behind", "getSignatureStatuses")  # RPC trouble: ignored
    rig.tick(RECONCILE_AFTER_S)
    assert rig.engine.unresolved == {}
    assert notes(rig, "reconcile")[0]["landed"] is True


def test_a_confirmed_swap_is_never_called_not_landed_while_the_wallet_lags(make_rig, world, fake_clock) -> None:
    rig = chain_rig(make_rig, world, fake_clock, WATCH_INTERVAL_S=600)
    rig.broker.refuse = unknown("sigD")  # the fake wallet does not show it yet
    rig.tick()
    quote = rig.broker.quotes[-1]
    rig.broker.refuse = None
    rig.broker.chain["sigD"] = "landed"
    rig.tick(SIGNATURE_CHECK_S)
    rig.tick(RECONCILE_AFTER_S)
    assert GARY in rig.engine.unresolved and notes(rig, "reconcile") == []  # waits instead of "did not land"
    rig.broker.tokens[GARY] = quote.out_amount  # the holdings index caught up
    rig.broker.sol -= quote.in_amount
    rig.tick(SIGNATURE_CHECK_S)
    assert rig.engine.unresolved == {}
    [position] = rig.ledger.open_positions()
    assert position.token_amount == quote.out_amount


def test_the_signature_is_known_even_when_the_broker_could_not_say(make_rig, world, fake_clock) -> None:
    from test_engine import _timeout

    rig = chain_rig(make_rig, world, fake_clock, WATCH_INTERVAL_S=600)
    rig.broker.after_land = _timeout  # a SwapUnknown without a signature
    rig.tick()
    assert rig.engine.unresolved[GARY]["signature"] == "sig-r0"  # from the in-flight marker


def test_a_swap_in_flight_when_the_process_died_is_settled_from_its_signature(make_rig, world, fake_clock,
                                                                             tmp_path) -> None:
    from test_engine import Killed

    path = tmp_path / "live.db"
    rig = chain_rig(make_rig, world, fake_clock, ledger_path=path)
    rig.broker.refuse = Killed()  # SIGKILL right after signing, before Ultra answered
    with pytest.raises(Killed):
        rig.tick()
    assert rig.ledger.get_kv("engine.inflight")[GARY]["signature"] == "sig-r0"
    rig.ledger.close()

    rig2 = chain_rig(make_rig, world, fake_clock, ledger_path=path)
    rig2.broker.chain["sig-r0"] = "failed"
    rig2.tick(1)
    assert rig2.engine.unresolved == {} and rig2.engine.entries_allowed  # no 90 s blind wait
    assert "failed on chain" in notes(rig2, "reconcile")[0]["result"]


def test_signature_checks_are_rate_limited(make_rig, world, fake_clock) -> None:
    rig = chain_rig(make_rig, world, fake_clock, WATCH_INTERVAL_S=600)
    rig.broker.after_land = landed_then_unknown("sigE")
    rig.tick()
    for _ in range(20):
        rig.tick(1)
    assert 1 <= len(rig.broker.status_calls) <= 20 // SIGNATURE_CHECK_S + 1


# =========================================================================== RT-9: exits-only safe mode


def test_safe_mode_blocks_entries_and_discovery_but_keeps_stop_losses(make_rig, world, fake_clock) -> None:
    rig = make_rig()
    rig.tick()
    [position] = rig.ledger.open_positions()
    problems = ["STOP_LOSS_PCT=18.0 must be <= 1 (a FRACTION: 0.20 means 20%)"]
    rig.engine.enter_safe_mode(problems, ["STOP_LOSS_PCT"])
    rig.engine._boot_checks(fake_clock.now())
    [note] = notes(rig, "safe_mode")
    assert note["problems"] == problems and note["defaults_used"] == ["STOP_LOSS_PCT"]
    banner = rig.ledger.get_kv("engine.safe_mode")
    assert banner["problems"] == problems and banner["since"] == fake_clock.now()
    assert rig.engine.status(fake_clock.now())["entries_blocked"].startswith("SAFE MODE")

    world.price *= 0.5
    results = rig.tick(30)
    assert results["discover"] == "skipped"
    assert rig.ledger.get_position(position.id).exit_reason == "stop_loss"  # exits still work
    world.price /= 0.5
    world.candles = dip_rebound_candles(fake_clock.now() + 3600)
    rig.engine.crawler.forget(GARY)
    rig.tick(3600)
    assert len([f for f in rig.ledger.fills(limit=None) if f.side == "buy"]) == 1  # no new entry


def test_a_normal_boot_clears_the_safe_mode_banner(make_rig, fake_clock) -> None:
    rig = make_rig()
    rig.ledger.set_kv("engine.safe_mode", {"problems": ["old"], "since": 1.0})
    rig.engine._boot_checks(fake_clock.now())
    assert rig.ledger.get_kv("engine.safe_mode") is None
    assert rig.engine.status(fake_clock.now())["safe_mode"] is None
