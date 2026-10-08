"""Engine tick-level tests: real components over FakeHttp + FakeClock (no network).

The "world" below serves every upstream API from a small mutable market
state, so a whole trade can be walked tick by tick: discovery -> cocoon
reject/pass -> watchlist -> dip-rebound entry -> paper buy with receipts ->
marking -> partial take-profit -> trailing stop -> chain verifies and the
books reconcile.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import pytest

from fakes import FakeClock, FakeHttp, load_fixture
from nightcrawler.audit import Auditor
from nightcrawler.broker.base import SwapUnknown
from nightcrawler.broker.paper import PaperBroker
from nightcrawler.cocoon import Cocoon
from nightcrawler.crawler import Crawler
from nightcrawler.engine import (
    ERROR_RECEIPT_EVERY_S,
    RECONCILE_AFTER_S,
    App,
    Engine,
    build_app,
)
from nightcrawler.http import HttpClient
from nightcrawler.judge import Judge
from nightcrawler.ledger import Ledger
from nightcrawler.models import SOL_MINT, Balances, Quote, Verdict
from nightcrawler.radar import Radar
from nightcrawler.risk import RiskManager
from nightcrawler.sources import build_sources
from world import GARY, GARY_DEV, RISKY, SOL_USD, SWAP_COST, World, dip_rebound_candles, iso, make_world

@pytest.fixture
def world(fake_http: FakeHttp, fake_clock: FakeClock) -> World:
    return make_world(fake_http, fake_clock)


@dataclass
class Rig:
    engine: Engine
    ledger: Ledger
    broker: Any
    clock: FakeClock
    world: World
    settings: Any

    def tick(self, advance: float = 0.0) -> dict[str, Any]:
        if advance:
            self.clock.advance(advance)
        return self.engine.tick(self.clock.now())

    def decisions(self) -> list[str]:
        return [d.action for d in reversed(self.ledger.decisions(limit=1000))]

    def receipt_kinds(self) -> list[str]:
        return [r.kind for r in self.ledger.receipts()]


@pytest.fixture
def make_rig(world: World, http_client: HttpClient, fake_clock: FakeClock, make_settings,
             tmp_path) -> Callable[..., Rig]:
    ledgers: list[Ledger] = []

    def _make(*, judge: Any = None, broker: Any = None, crawler: Any = None, **overrides: Any) -> Rig:
        settings = make_settings(**overrides)
        sources = build_sources(settings, http_client)
        ledger = Ledger(tmp_path / f"ledger{len(ledgers)}.db", clock=fake_clock)
        ledgers.append(ledger)
        broker = broker if broker is not None else PaperBroker(sources.jupiter, ledger, settings, fake_clock)
        engine = Engine(settings, clock=fake_clock, ledger=ledger,
                        crawler=crawler or Crawler(sources, settings, fake_clock),
                        cocoon=Cocoon(sources, settings, fake_clock), radar=Radar(sources, settings, fake_clock),
                        judge=judge or Judge(settings, clock=fake_clock, ledger=ledger),
                        risk=RiskManager(settings, ledger, fake_clock), broker=broker, sources=sources)
        return Rig(engine, ledger, broker, fake_clock, world, settings)

    yield _make
    for ledger in ledgers:
        ledger.close()


# =========================================================================== the whole trade


def test_full_trade_from_discovery_to_trailing_exit(make_rig) -> None:
    rig = make_rig()
    w = rig.world

    results = rig.tick()
    assert all(not str(v).startswith("error") for v in results.values()), results
    # discovery: the risky token fails the cocoon, Gary passes and is watched
    assert rig.decisions()[:2] == ["reject_cocoon", "watch"]
    reject = rig.ledger.decisions(actions=["reject_cocoon"])[0]
    assert reject.mint == RISKY and "[rugcheck_danger]" in reject.reason
    # watch: the dip-rebound setup fires and the paper broker buys at the live (fake) quote
    assert rig.decisions()[2] == "enter"
    [position] = rig.ledger.open_positions()
    [buy] = rig.ledger.fills()
    assert position.mint == GARY and position.entry_fill_ids == [buy.id] and position.token_amount == buy.token_amount
    assert buy.side == "buy" and buy.sol_lamports == 200_000_000  # 20 % of $100 at $100/SOL
    haircut = 1 - rig.settings.paper_slippage_bps / 1e4  # paper fills land PAPER_SLIPPAGE_BPS below the quote
    assert position.entry_price_usd == pytest.approx(w.price / (1 - SWAP_COST) / haircut, rel=1e-4)
    # the decision receipt came BEFORE the fill receipt
    receipts = rig.ledger.receipts()
    enter_seq = next(r.seq for r in receipts if r.kind == "decision" and r.payload["action"] == "enter")
    fill_seq = next(r.seq for r in receipts if r.kind == "fill")
    assert enter_seq < fill_seq
    enter = rig.ledger.decisions(actions=["enter"])[0]
    assert enter.inputs["quote"]["expected_out_amount"] == buy.expected_out_amount
    assert buy.token_amount == buy.expected_out_amount * (10_000 - rig.settings.paper_slippage_bps) // 10_000
    assert enter.verdict is not None and enter.verdict.source == "rules"  # judge off without an API key
    assert rig.ledger.latest_equity() is not None

    # mark: +52 % -> partial take-profit (sell half)
    w.price = 0.70e-3
    rig.tick(10)
    assert rig.decisions()[-1] == "exit_partial"
    [position] = rig.ledger.open_positions()
    assert position.partial_taken and position.token_amount == buy.token_amount - buy.token_amount // 2

    # new peak, no exit (trailing stop at 15 % below the peak)
    w.price = 0.90e-3
    rig.tick(10)
    [position] = rig.ledger.open_positions()
    assert position.peak_price_usd == pytest.approx(0.90e-3) and rig.decisions()[-1] == "exit_partial"

    # 16.7 % below the peak -> trailing stop sells the rest
    w.price = 0.75e-3
    rig.tick(10)
    assert rig.decisions()[-1] == "exit"
    assert rig.ledger.open_positions() == []
    [closed] = rig.ledger.positions(status="closed")
    assert closed.exit_reason == "trailing_stop" and closed.token_amount == 0 and closed.rent_lamports == 0
    assert closed.pnl_lamports() > 0

    assert rig.ledger.verify_chain() == (True, None)
    report = Auditor(rig.ledger, rig.broker, rig.clock).reconcile()
    assert report.ok, report.issues
    assert len(rig.ledger.fills(limit=None)) == 3


def test_entry_is_not_retried_while_the_position_is_open_and_cooldown_holds(make_rig) -> None:
    rig = make_rig()
    rig.tick()
    assert len(rig.ledger.fills()) == 1
    rig.world.candles = dip_rebound_candles(rig.clock.now() + 60)
    rig.tick(60)  # watch is due again; the open mint is skipped (no second buy)
    assert len(rig.ledger.fills()) == 1


# =========================================================================== kill switch


def test_kill_stop_blocks_new_entries(make_rig, tmp_data_dir) -> None:
    (tmp_data_dir / "KILL").write_text("stop")
    rig = make_rig()
    rig.tick()
    assert "watch" in rig.decisions()  # discovery and the cocoon keep running
    assert rig.ledger.fills() == []
    assert rig.world.http.calls_to("/ohlcv/minute") == []  # no candle budget spent while stopped
    kill = [r for r in rig.ledger.receipts() if r.kind == "kill"]
    assert kill and kill[0].payload == {"mode": "stop", "previous": None}
    assert rig.ledger.get_kv("engine.kill_mode") == "stop"
    rig.tick(1)
    assert [r.kind for r in rig.ledger.receipts()].count("kill") == 1  # receipted once per change


def test_kill_sell_all_exits_everything_then_stays_stopped(make_rig, tmp_data_dir) -> None:
    rig = make_rig()
    rig.tick()
    assert len(rig.ledger.open_positions()) == 1
    (tmp_data_dir / "KILL").write_text("sell all")
    rig.tick(1)
    assert rig.ledger.open_positions() == []
    [closed] = rig.ledger.positions(status="closed")
    assert closed.exit_reason == "kill_switch"
    assert any(r.kind == "kill" and r.payload["mode"] == "sell_all" for r in rig.ledger.receipts())
    # still stopped: a fresh setup does not buy again
    rig.world.candles = dip_rebound_candles(rig.clock.now() + 3600)
    rig.engine.crawler.forget(GARY)
    rig.tick(3600)
    assert len(rig.ledger.fills(limit=None)) == 2


def test_engine_sell_all_method(make_rig) -> None:
    rig = make_rig()
    rig.tick()
    fills = rig.engine.sell_all("manual")
    assert len(fills) == 1 and fills[0].side == "sell"
    assert rig.ledger.positions(status="closed")[0].exit_reason == "manual"


# =========================================================================== gates


class NoJudge:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def decide(self, features: dict[str, Any]) -> Verdict:
        self.calls.append(features)
        return Verdict(decision="no", confidence=0.8, reasons=["insider wallets dominate"], model="fake",
                       latency_ms=5, cost_usd=0.01, source="claude")


def test_judge_no_blocks_entry_in_required_mode(make_rig) -> None:
    judge = NoJudge()
    rig = make_rig(judge=judge, ANTHROPIC_API_KEY="sk-ant-test-key-000", JUDGE_MODE="required")
    rig.tick()
    assert rig.ledger.fills() == []
    [rejected] = rig.ledger.decisions(actions=["reject_judge"])
    assert rejected.verdict is not None and rejected.verdict.reasons == ["insider wallets dominate"]
    assert rejected.inputs["features"]["mint"] == GARY
    assert judge.calls and judge.calls[0]["symbol"] == "Gary"


def test_judge_no_is_only_logged_in_advisory_mode(make_rig) -> None:
    rig = make_rig(judge=NoJudge(), ANTHROPIC_API_KEY="sk-ant-test-key-000", JUDGE_MODE="advisory")
    rig.tick()
    assert len(rig.ledger.fills()) == 1
    assert rig.ledger.decisions(actions=["enter"])[0].verdict.decision == "no"


def test_risk_halt_blocks_entry_before_radar_and_judge(make_rig) -> None:
    judge = NoJudge()
    rig = make_rig(judge=judge, ANTHROPIC_API_KEY="sk-ant-test-key-000", JUDGE_MODE="required")
    rig.ledger.set_kv("risk.halted", {"halted": True, "reason": "drawdown 55%", "ts": rig.clock.now()})
    rig.tick()
    [rejected] = rig.ledger.decisions(actions=["reject_risk"])
    assert rejected.reason.startswith("[halted]")
    assert judge.calls == [] and rig.world.http.calls_to("/trades") == []
    assert rig.ledger.fills() == []


def test_radar_error_rejects_entry_fail_closed(make_rig) -> None:
    rig = make_rig()
    rig.world.http.register("/trades", {"errors": "not found"}, status=404)
    rig.tick()
    [rejected] = rig.ledger.decisions(actions=["reject_radar"])
    assert rejected.reason.startswith("radar unavailable")
    assert rig.ledger.fills() == []


def test_radar_flag_rejects_entry(make_rig) -> None:
    rig = make_rig()
    now = rig.clock.now()
    rig.world.trades = [{"type": "trade", "attributes": {
        "block_timestamp": iso(now - 120), "tx_hash": "abc", "tx_from_address": GARY_DEV, "kind": "sell",
        "volume_in_usd": "2500", "price_from_in_usd": "0.0005", "from_token_amount": "5000000"}}]
    rig.tick()
    [rejected] = rig.ledger.decisions(actions=["reject_radar"])
    assert "creator sold" in rejected.reason
    assert rig.ledger.fills() == []


def test_weak_buy_pressure_means_no_entry(make_rig) -> None:
    rig = make_rig()
    rig.world.buys_m5, rig.world.sells_m5 = 5, 10
    rig.tick()
    assert rig.ledger.fills() == []
    assert "buy/sell ratio" in (rig.engine.watchlist[GARY].last_signal_reason or "")


def test_quote_with_too_much_impact_is_rejected(make_rig) -> None:
    rig = make_rig(MAX_PRICE_IMPACT_PCT=0.1)  # the fake Ultra reports 0.2 %
    rig.tick()
    [rejected] = rig.ledger.decisions(actions=["reject_quote"])
    assert "price impact" in rejected.reason
    assert rig.ledger.fills() == []


# =========================================================================== robustness


class BrokenCrawler:
    def __init__(self, inner: Crawler) -> None:
        self.inner = inner
        self.error: Exception | None = RuntimeError("feed exploded")
        self.last_rejected: list[Any] = []

    def poll(self) -> list[Any]:
        if self.error is not None:
            raise self.error
        return self.inner.poll()

    def refresh(self, mints: list[str]) -> dict[str, Any]:
        return self.inner.refresh(mints)

    def stats(self) -> dict[str, Any]:
        return self.inner.stats()


def test_a_failing_stage_never_kills_the_loop(make_rig, world, http_client, fake_clock, make_settings) -> None:
    settings = make_settings()
    crawler = BrokenCrawler(Crawler(build_sources(settings, http_client), settings, fake_clock))
    rig = make_rig(crawler=crawler)
    results = rig.tick()
    assert results["discover"] == "error: RuntimeError"
    assert results["equity"] == "ok" and results["kill"] == "ok"
    errors = [r for r in rig.ledger.receipts() if r.kind == "error"]
    assert len(errors) == 1 and errors[0].payload == {"stage": "discover", "error": "RuntimeError: feed exploded"}
    assert "discover: RuntimeError: feed exploded" in rig.ledger.get_kv("engine.last_error")

    rig.tick(30)  # same error again soon: logged, not receipted again
    assert rig.receipt_kinds().count("error") == 1
    rig.tick(ERROR_RECEIPT_EVERY_S)
    assert rig.receipt_kinds().count("error") == 2

    crawler.error = None  # the source recovers and the same engine carries on
    rig.tick(30)
    assert "watch" in rig.decisions()
    assert rig.ledger.verify_chain() == (True, None)


def test_tick_survives_a_broken_ledger_write(make_rig, monkeypatch) -> None:
    rig = make_rig()

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(rig.ledger, "record_equity", boom)
    results = rig.tick()
    assert results["equity"] == "error: RuntimeError"
    assert results["watch"] == "ok"


def test_heartbeat_and_status_are_written(make_rig) -> None:
    rig = make_rig()
    rig.tick()
    assert rig.ledger.get_kv("engine.heartbeat") == rig.clock.now()
    status = rig.ledger.get_kv("engine.status")
    assert status["state"] == "running" and status["mode"] == "paper"
    assert status["counters"]["cocoon_checked"] == 2 and status["counters"]["entries"] == 1
    assert status["crawler"]["polls"] == 1


def test_run_forever_writes_boot_and_shutdown_receipts(make_rig) -> None:
    rig = make_rig()
    ticks: list[float] = []
    original = rig.engine.tick

    def counting_tick(now: float) -> dict[str, Any]:
        ticks.append(now)
        if len(ticks) >= 3:
            rig.engine.stop()
        return original(now)

    rig.engine.tick = counting_tick  # type: ignore[method-assign]
    rig.engine.run_forever()
    kinds = rig.receipt_kinds()
    assert kinds[0] == "boot" and kinds[-1] == "note"
    boot = rig.ledger.receipts()[0]
    assert boot.payload["mode"] == "paper" and "anthropic_api_key" not in boot.payload["settings"]
    assert boot.payload["settings"]["anthropic_api_key_set"] is False
    assert rig.ledger.get_kv("engine.status")["state"] == "stopped"
    assert len(ticks) == 3 and ticks[1] - ticks[0] == pytest.approx(1.0, abs=0.01)


def test_reset_halt_token_clears_a_halt_once_at_boot(make_rig) -> None:
    rig = make_rig(RESET_HALT_TOKEN="2026-10-08")
    rig.ledger.set_kv("risk.halted", {"halted": True, "reason": "drawdown", "ts": 1.0})
    rig.engine.stop()  # boot, then exit the loop at once
    rig.engine.run_forever()
    assert rig.ledger.get_kv("risk.halted")["halted"] is False
    assert rig.ledger.get_kv("risk.reset_token") == "2026-10-08"
    rig.ledger.set_kv("risk.halted", {"halted": True, "reason": "again", "ts": 2.0})
    rig.engine.run_forever()  # same token: no second reset
    assert rig.ledger.get_kv("risk.halted")["halted"] is True


# =========================================================================== unknown live outcomes


class UnknownOutcomeBroker:
    """A live-like broker whose /execute outcome is unknown; the wallet then shows what really happened."""

    mode = "live"

    def __init__(self, clock: FakeClock, lands: bool) -> None:
        self.clock = clock
        self.lands = lands
        self.tokens: dict[str, int] = {}
        self.sol = 1_000_000_000
        self.quotes: list[Quote] = []

    def quote(self, side: str, mint: str, amount_in: int, decimals: int, **_: Any) -> Quote:
        q = Quote(side=side, input_mint=SOL_MINT if side == "buy" else mint,  # type: ignore[arg-type]
                  output_mint=mint if side == "buy" else SOL_MINT, in_amount=amount_in, out_amount=40_000_000_000,
                  price_impact_pct=0.2, fee_bps=10, route_labels=["x"], request_id=f"r{len(self.quotes)}",
                  transaction_b64="AAAA", quoted_at=self.clock.now(), in_usd=20.0, out_usd=19.8)
        self.quotes.append(q)
        return q

    def execute(self, quote: Quote, position: Any, *, symbol: str = "") -> Any:
        if self.lands:
            self.tokens[quote.output_mint] = quote.out_amount
            self.sol -= quote.in_amount
        raise SwapUnknown("transport error during /execute")

    def balances(self) -> Balances:
        return Balances(sol_lamports=self.sol, tokens=dict(self.tokens))

    def sol_price_usd(self) -> float:
        return SOL_USD

    def wallet_value_usd(self) -> float:
        return 50.0


LIVE = {"TRADING_MODE": "live", "LIVE_CONFIRM": "I_ACCEPT_REAL_MONEY_RISK", "BOT_WALLET_SECRET": "x" * 88,
        "DASHBOARD_HOST": "127.0.0.1"}


@pytest.mark.parametrize("lands", [True, False])
def test_unknown_live_outcome_blocks_entries_then_reconciles(make_rig, fake_clock, lands: bool) -> None:
    broker = UnknownOutcomeBroker(fake_clock, lands)
    rig = make_rig(broker=broker, WATCH_INTERVAL_S=600, **LIVE)
    rig.tick()
    assert rig.decisions()[-1] == "enter" and rig.ledger.fills() == []
    assert set(rig.engine.unresolved) == {GARY}
    assert rig.ledger.get_kv("engine.unresolved")[GARY]["side"] == "buy"
    assert not rig.engine.entries_allowed

    rig.tick(RECONCILE_AFTER_S / 2)  # too early: still blocked
    assert rig.engine.unresolved
    rig.tick(RECONCILE_AFTER_S / 2)
    assert rig.engine.unresolved == {} and rig.ledger.get_kv("engine.unresolved") == {}
    note = [r for r in rig.ledger.receipts() if r.kind == "note" and r.payload.get("event") == "reconcile"]
    assert len(note) == 1 and note[0].payload["landed"] is lands
    if lands:
        [fill] = rig.ledger.fills()
        [position] = rig.ledger.open_positions()
        assert fill.token_amount == 40_000_000_000 and fill.sol_lamports == broker.quotes[0].in_amount
        assert position.entry_fill_ids == [fill.id] and position.entry_price_usd > 0
    else:
        assert rig.ledger.fills() == [] and rig.ledger.open_positions() == []
        rig.tick(600)  # the setup is still there: a FRESH quote is fetched, the old one is never re-sent
        assert [q.request_id for q in broker.quotes] == ["r0", "r1"]
    assert rig.ledger.verify_chain() == (True, None)


# =========================================================================== wiring


def test_build_app_wires_paper_mode(make_settings, http_client, fake_clock) -> None:
    settings = make_settings()
    app = build_app(settings, fake_clock, http=http_client)
    try:
        assert isinstance(app, App) and isinstance(app.broker, PaperBroker)
        assert app.engine.broker is app.broker and app.engine.ledger is app.ledger
        assert app.auditor.broker is app.broker and app.judge.ledger is app.ledger
        assert app.ledger.path == str(settings.db_path)
        state = app.dashboard.state_provider()
        assert state["mode"] == "PAPER" and state["receipts"]["count"] == 0
    finally:
        app.close()


def test_build_app_live_mode_sets_the_wallet_pubkey(make_settings, http_client, fake_clock) -> None:
    keypair_mod = pytest.importorskip("solders.keypair")
    from nightcrawler.base58 import b58encode
    from nightcrawler.broker.live import LiveBroker

    kp = keypair_mod.Keypair()
    settings = make_settings(TRADING_MODE="live", LIVE_CONFIRM="I_ACCEPT_REAL_MONEY_RISK",
                             BOT_WALLET_SECRET=b58encode(bytes(kp)), DASHBOARD_TOKEN="test-dashboard-token-0123")
    app = build_app(settings, fake_clock, http=http_client)
    try:
        assert isinstance(app.broker, LiveBroker)
        assert app.ledger.get_kv("wallet.pubkey") == str(kp.pubkey())
        assert app.dashboard.state_provider()["wallet"]["address"] == str(kp.pubkey())
    finally:
        app.close()


def test_build_app_refuses_a_bad_wallet_secret(make_settings, http_client, fake_clock) -> None:
    from nightcrawler.broker.wallet import WalletError

    settings = make_settings(TRADING_MODE="live", LIVE_CONFIRM="I_ACCEPT_REAL_MONEY_RISK",
                             BOT_WALLET_SECRET="not-a-real-secret", DASHBOARD_HOST="127.0.0.1")
    with pytest.raises(WalletError):
        build_app(settings, fake_clock, http=http_client)


def test_fixture_sanity() -> None:
    """The fixtures this module relies on still say what the tests assume."""
    report = load_fixture("rugcheck_report")
    assert report["mint"] == GARY and report["creator"] == GARY_DEV
    assert math.isclose(dip_rebound_candles(0.0)[-1].c, 0.46e-3)


def test_engine_http_client_fails_fast_on_geckoterminal(make_settings, fake_clock) -> None:
    settings = make_settings()
    app = build_app(settings, fake_clock, session=FakeHttp())
    try:
        assert app.http.host_max_retries == {"api.geckoterminal.com": 1}
        assert app.http.max_retries == 4
    finally:
        app.close()


def test_watchlist_hysteresis_ttl_and_missing_data(make_rig) -> None:
    rig = make_rig(KILL_SWITCH="stop")  # watch only, no entries
    rig.tick()
    assert set(rig.engine.watchlist) == {GARY}
    rig.world.price = 0.09e-3  # mcap $90K: below the $100K floor but inside the 2x slack -> still watched
    rig.tick(60)
    assert GARY in rig.engine.watchlist
    rig.world.price = 0.04e-3  # mcap $40K: collapsed -> unwatched
    rig.tick(60)
    assert GARY not in rig.engine.watchlist
    assert rig.ledger.decisions(actions=["unwatch"])[0].reason == "mcap fell to $40,000"


def test_watchlist_expires_after_ttl(make_rig) -> None:
    rig = make_rig(KILL_SWITCH="stop", WATCHLIST_TTL_H=1)
    rig.tick()
    rig.tick(3601)
    assert rig.ledger.decisions(actions=["unwatch"])[0].reason == "expired after 1 h"


def test_entry_needs_mcap_inside_the_strict_window(make_rig) -> None:
    rig = make_rig()
    rig.world.price = 0.09e-3  # setup candles unchanged, but mcap $90K < MIN_MCAP_USD at decision time
    rig.tick()
    assert rig.ledger.fills() == []
    assert "outside the window" in (rig.engine.watchlist[GARY].last_signal_reason or "")


def test_radar_flag_on_an_open_position_exits_everything(make_rig) -> None:
    rig = make_rig()
    rig.tick()
    assert len(rig.ledger.open_positions()) == 1
    now = rig.clock.now()
    rig.world.trades = [{"type": "trade", "attributes": {
        "block_timestamp": iso(now), "tx_hash": "dump", "tx_from_address": GARY_DEV, "kind": "sell",
        "volume_in_usd": "9000", "price_from_in_usd": "0.0005", "from_token_amount": "18000000"}}]
    rig.tick(200)  # past RADAR_INTERVAL_S (180 s) and the radar's 60 s trade cache
    [closed] = rig.ledger.positions(status="closed")
    assert closed.exit_reason.startswith("radar: creator sold")


def test_a_radar_error_on_an_open_position_is_not_an_exit(make_rig) -> None:
    rig = make_rig()
    rig.tick()
    rig.world.http.register("/trades", {"errors": "down"}, status=404)
    rig.tick(200)
    assert len(rig.ledger.open_positions()) == 1
