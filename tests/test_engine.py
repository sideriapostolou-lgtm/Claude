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
from nightcrawler.broker.base import QuoteRejected, SwapUnknown
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
from nightcrawler.models import (
    SOL_MINT,
    TOKEN_ACCOUNT_RENT_LAMPORTS,
    Balances,
    Fill,
    Quote,
    Verdict,
    effective_price_usd,
    new_id,
)
from nightcrawler.radar import Radar
from nightcrawler.risk import RiskManager
from nightcrawler.sources import build_sources
from world import (
    DECIMALS,
    GARY,
    GARY_DEV,
    GARY_POOL,
    RISKY,
    SOL_USD,
    SWAP_COST,
    World,
    dip_rebound_candles,
    iso,
    jupiter_token,
    make_world,
)

COPYCAT = "US517G5965aydkZ46HS38QLi7UQiSojurfbQfKCELFr"  # another coin with GARY's ticker

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

    def _make(*, judge: Any = None, broker: Any = None, crawler: Any = None, broker_factory: Any = None,
              ledger_path: Any = None, **overrides: Any) -> Rig:
        settings = make_settings(**overrides)
        sources = build_sources(settings, http_client)
        ledger = Ledger(ledger_path or tmp_path / f"ledger{len(ledgers)}.db", clock=fake_clock)
        ledgers.append(ledger)
        if broker is None and broker_factory is not None:
            broker = broker_factory(sources, ledger, settings)
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
    # ACC-8: like live (Ultra's sell leaves the emptied token account open), the rent stays locked
    assert closed.exit_reason == "trailing_stop" and closed.token_amount == 0
    assert closed.rent_lamports == TOKEN_ACCOUNT_RENT_LAMPORTS
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
    assert judge.calls and judge.calls[0]["untrusted_text"]["symbol"] == "Gary"  # SI-10: creator text only there


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

    def execute(self, quote: Quote, position: Any, *, symbol: str = "", on_fill: Any = None) -> Any:
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
        rig.world.candles = dip_rebound_candles(rig.clock.now() + 600)
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


def test_paper_mode_reads_the_bot_wallet_balance_for_the_checklist(make_rig, fake_http: FakeHttp,
                                                                   fake_clock: FakeClock) -> None:
    """GOING_LIVE steps 1-3 (a funded bot wallet in BOT_WALLET_SECRET) happen in PAPER mode: the engine reads
    that wallet's SOL every 10 minutes (one getBalance) so "ready for real money?" can tick step 3."""
    from nightcrawler.botwallet import CHECK_EVERY_S, KV_BOT_WALLET

    address = "BotWa11etPubkey1111111111111111111111111111"
    balance = {"jsonrpc": "2.0", "id": 1, "result": {"context": {"slot": 1}, "value": 250_000_000}}
    account = load_fixture("rpc_getAccountInfo_mint")
    fake_http.register("api.mainnet-beta.solana.com",
                       lambda req: balance if req.json.get("method") == "getBalance" else account, method="POST")

    def balance_calls() -> list[Any]:
        return [c for c in fake_http.calls if c.json and c.json.get("method") == "getBalance"]

    rig = make_rig(broker_factory=lambda sources, ledger, settings: PaperBroker(
        sources.jupiter, ledger, settings, fake_clock, taker=address))
    results = rig.tick()
    assert results["bot_wallet"] == "ok"
    assert rig.ledger.get_kv(KV_BOT_WALLET) == {"address": address, "sol_lamports": 250_000_000,
                                                "checked_at": rig.clock.now()}
    (call,) = balance_calls()
    assert call.json["params"][0] == address
    rig.tick(advance=60)
    assert len(balance_calls()) == 1  # not every tick
    rig.tick(advance=CHECK_EVERY_S)
    assert len(balance_calls()) == 2

    # an RPC failure keeps the last reading (the checklist ages it out) and never becomes an engine error
    fake_http.register("api.mainnet-beta.solana.com", RuntimeError("rpc down"), method="POST")
    before = rig.ledger.get_kv(KV_BOT_WALLET)
    receipts = len(rig.ledger.receipts())
    rig.engine.check_bot_wallet(rig.clock.now() + 1)
    assert rig.ledger.get_kv(KV_BOT_WALLET) == before and len(rig.ledger.receipts()) == receipts


def test_without_a_bot_wallet_paper_mode_never_reads_a_balance(make_rig, fake_http: FakeHttp) -> None:
    from nightcrawler.botwallet import KV_BOT_WALLET

    rig = make_rig()
    assert rig.tick()["bot_wallet"] == "ok"
    assert rig.ledger.get_kv(KV_BOT_WALLET) is None
    assert not [c for c in fake_http.calls if c.json and c.json.get("method") == "getBalance"]


def test_build_app_refuses_a_bad_wallet_secret(make_settings, http_client, fake_clock) -> None:
    from nightcrawler.broker.wallet import WalletError

    settings = make_settings(TRADING_MODE="live", LIVE_CONFIRM="I_ACCEPT_REAL_MONEY_RISK",
                             BOT_WALLET_SECRET="not-a-real-secret", DASHBOARD_HOST="127.0.0.1")
    with pytest.raises(WalletError):
        build_app(settings, fake_clock, http=http_client)
    assert http_client.usage.store is None  # never left bound to the ledger build_app closed


def test_fixture_sanity() -> None:
    """The fixtures this module relies on still say what the tests assume."""
    report = load_fixture("rugcheck_report")
    assert report["mint"] == GARY and report["creator"] == GARY_DEV
    assert math.isclose(dip_rebound_candles(0.0)[-1].c, 0.46e-3)


def test_build_app_counts_provider_usage_into_the_ledger(make_settings, fake_clock) -> None:
    """The dashboard's API usage card reads kv ``usage.providers``: build_app binds the engine's
    HTTP client to the ledger, and App.close() writes the last (not yet flushed) counts."""
    from nightcrawler.http import KV_USAGE

    session = FakeHttp()
    session.register("/tokens/v2/recent", [])
    app = build_app(make_settings(), fake_clock, session=session)
    try:
        app.sources.jupiter.tokens_recent()
        assert app.ledger.get_kv(KV_USAGE)["jupiter"]["day_counts"] == {"calls": 1}
        app.sources.jupiter.tokens_recent()  # within the minute: still pending in memory
        assert app.ledger.get_kv(KV_USAGE)["jupiter"]["day_counts"] == {"calls": 1}
        path = app.ledger.path
    finally:
        app.close()
    with Ledger(path) as ledger:
        assert ledger.get_kv(KV_USAGE)["jupiter"]["day_counts"] == {"calls": 2}


def test_build_app_prices_paper_fees_from_helius(make_settings, fake_clock) -> None:
    from nightcrawler.broker.paper import network_fee_from_priority

    session = FakeHttp()
    session.register("helius-rpc.com", {"jsonrpc": "2.0", "id": 1,
                                        "result": {"priorityFeeLevels": {"high": 2_000_000.0}}}, method="POST")
    settings = make_settings(SOLANA_RPC_URL="https://mainnet.helius-rpc.com/?api-key=0123456789abcdef0123")
    app = build_app(settings, fake_clock, session=session)
    try:
        fee = network_fee_from_priority(2_000_000.0)
        assert fee > settings.network_fee_lamports
        assert app.broker.network_fee_lamports() == fee
        assert len(session.calls_to("helius-rpc.com")) == 1
    finally:
        app.close()


def test_entry_size_leaves_room_for_the_brokers_network_fee(make_rig) -> None:
    rig = make_rig()
    rig.broker.network_fee_lamports = lambda: 5_000_000  # e.g. a Helius priority-fee spike
    sizes: list[dict[str, Any]] = []
    real = rig.engine.risk.size_position

    def spy(*args: Any, **kwargs: Any) -> int:
        sizes.append(kwargs)
        return real(*args, **kwargs)

    rig.engine.risk.size_position = spy
    rig.tick()
    assert sizes and sizes[0]["network_fee_lamports"] == 5_000_000


def test_discovery_shows_every_crawled_coin_to_the_copycat_check(make_rig, world) -> None:
    """A coin the cheap prefilter rejects is never rug-checked, but its ticker still counts: the
    engine shows every crawled coin to ``Cocoon.observe``, so GARY's report warns about the copy."""
    copy = jupiter_token(COPYCAT, "GARY", GARY_POOL, world.clock.now() - 4 * 3600, world.price, GARY_DEV)
    copy["audit"]["freezeAuthorityDisabled"] = False  # prefilter: "freeze authority set"
    world.trending.append(copy)
    rig = make_rig(KILL_SWITCH="stop")
    rig.tick()
    [watch] = rig.ledger.decisions(actions=["watch"])
    assert watch.mint == GARY
    safety = watch.inputs["safety"]
    assert any(w.startswith("[copycat]") for w in safety["warnings"])
    assert safety["metrics"]["copycat_count"] == 1 and safety["metrics"]["impersonates"] is None
    counters = rig.engine.status(rig.clock.now())["counters"]
    assert counters["cocoon.copycat"] == 1


def test_engine_http_client_fails_fast_on_geckoterminal(make_settings, fake_clock) -> None:
    settings = make_settings()
    app = build_app(settings, fake_clock, session=FakeHttp())
    try:
        assert app.http.host_max_retries == {"api.geckoterminal.com": 1, "api.rugcheck.xyz": 1,
                                             "api.mainnet-beta.solana.com": 1}
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


# =========================================================================== review fixes: live money safety


class Killed(BaseException):
    """Stands in for SIGKILL: not an Exception, so nothing in the engine can catch it."""


def _die(_fill: Any) -> None:
    raise Killed()


def _timeout(_fill: Any) -> None:
    raise SwapUnknown("Ultra execute outcome unknown (read timed out)")


class FakeLiveBroker:
    """A live-like broker over a fake ON-CHAIN wallet: Ultra-style quotes ("Insufficient funds" when the
    wallet lacks the input) and swaps that LAND first and are then recorded the way LiveBroker records
    them (``on_fill`` in the fill transaction; a failed write is an unknown outcome carrying the fill)."""

    mode = "live"

    def __init__(self, world: World, ledger: Ledger, clock: FakeClock, sol: int = 1_000_000_000,
                 tokens: dict[str, int] | None = None) -> None:
        self.world, self.ledger, self.clock = world, ledger, clock
        self.sol = sol
        self.tokens = dict(tokens or {})
        self.after_land: Callable[[Any], None] | None = None  # runs after landing, before recording
        self.refuse: Exception | None = None  # raised before anything is sent
        self.quotes: list[Quote] = []
        self.executed: list[str] = []
        self.sol_price_error: Exception | None = None

    def quote(self, side: str, mint: str, amount_in: int, decimals: int, **_: Any) -> Quote:
        held = self.sol if side == "buy" else self.tokens.get(mint, 0)
        if amount_in > held:
            raise QuoteRejected("Ultra error: Insufficient funds")
        if side == "buy":
            usd = amount_in / 1e9 * SOL_USD
            out = int(usd * (1 - SWAP_COST) / self.world.price * 10**DECIMALS)
        else:
            usd = amount_in / 10**DECIMALS * self.world.price
            out = int(usd * (1 - SWAP_COST) / SOL_USD * 1e9)
        q = Quote(side=side, input_mint=SOL_MINT if side == "buy" else mint,  # type: ignore[arg-type]
                  output_mint=mint if side == "buy" else SOL_MINT, in_amount=amount_in, out_amount=out,
                  price_impact_pct=0.2, fee_bps=10, route_labels=["x"], request_id=f"r{len(self.quotes)}",
                  transaction_b64="AAAA", quoted_at=self.clock.now(), in_usd=usd, out_usd=usd * (1 - SWAP_COST))
        self.quotes.append(q)
        return q

    def execute(self, quote: Quote, position: Any, *, symbol: str = "", on_fill: Any = None) -> Any:
        if self.refuse is not None:
            raise self.refuse
        self.executed.append(quote.side)
        mint, buy = quote.token_mint, quote.side == "buy"
        if buy:  # the swap LANDS on chain
            self.sol -= quote.in_amount
            self.tokens[mint] = self.tokens.get(mint, 0) + quote.out_amount
        else:
            self.tokens[mint] = self.tokens.get(mint, 0) - quote.in_amount
            self.sol += quote.out_amount
        sol, tokens = (quote.in_amount, quote.out_amount) if buy else (quote.out_amount, quote.in_amount)
        fill = Fill(id=new_id("fill"), mode="live", side=quote.side, mint=mint,  # type: ignore[arg-type]
                    sol_lamports=sol, token_amount=tokens, token_decimals=DECIMALS,
                    price_usd=effective_price_usd(sol, tokens, DECIMALS, SOL_USD), sol_usd=SOL_USD,
                    fees_lamports=15_000, platform_fee_bps=10, price_impact_pct=0.2,
                    signature=f"sig{len(self.executed)}", request_id=quote.request_id, ts=self.clock.now(),
                    position_id=position.id if position is not None else None, symbol=symbol,
                    expected_out_amount=quote.out_amount)
        if self.after_land is not None:
            hook, self.after_land = self.after_land, None
            hook(fill)
        try:
            with self.ledger.transaction():
                recorded = self.ledger.record_fill(fill)
                if on_fill is not None:
                    on_fill(recorded)
        except Exception as exc:  # like LiveBroker: a landed swap that was not recorded is UNKNOWN
            raise SwapUnknown(f"landed but not recorded ({exc})", fill) from exc
        return recorded

    def balances(self) -> Balances:
        return Balances(sol_lamports=self.sol, tokens={m: a for m, a in self.tokens.items() if a})

    def chain_token_balance(self, mint: str) -> int:
        """Like LiveBroker: the wallet's ON-CHAIN holding (here the same fake wallet as ``balances``)."""
        return self.tokens.get(mint, 0)

    def sol_price_usd(self) -> float:
        if self.sol_price_error is not None:
            raise self.sol_price_error
        return SOL_USD

    def wallet_value_usd(self) -> float:
        return self.sol / 1e9 * SOL_USD + sum(a / 10**DECIMALS * self.world.price for a in self.tokens.values())


def live_rig(make_rig: Callable[..., Rig], world: World, clock: FakeClock, *, path: Any = None,
             sol: int = 1_000_000_000, tokens: dict[str, int] | None = None, **overrides: Any) -> Rig:
    def factory(_sources: Any, ledger: Ledger, _settings: Any) -> FakeLiveBroker:
        return FakeLiveBroker(world, ledger, clock, sol=sol, tokens=tokens)

    return make_rig(broker_factory=factory, ledger_path=path, **{**LIVE, **overrides})


def notes(rig: Rig, event: str) -> list[dict[str, Any]]:
    return [r.payload for r in rig.ledger.receipts() if r.kind == "note" and r.payload.get("event") == event]


def test_a_kill_between_a_landed_sell_and_its_record_is_reconciled_after_restart(make_rig, world, fake_clock,
                                                                                 tmp_path) -> None:
    path = tmp_path / "live.db"
    rig = live_rig(make_rig, world, fake_clock, path=path)
    rig.tick()
    [position] = rig.ledger.open_positions()
    world.price *= 0.5  # stop loss
    rig.broker.after_land = _die
    with pytest.raises(Killed):
        rig.tick(10)
    assert rig.broker.tokens[GARY] == 0  # the sell LANDED, then the process died
    rig.ledger.close()

    rig2 = live_rig(make_rig, world, fake_clock, path=path, sol=rig.broker.sol, tokens=rig.broker.tokens)
    rig2.tick(1)
    assert GARY in rig2.engine.unresolved and not rig2.engine.entries_allowed
    assert rig2.broker.executed == []  # nothing re-sent, no hold loop on tokens the wallet no longer has
    rig2.tick(RECONCILE_AFTER_S)
    assert rig2.engine.unresolved == {} and rig2.ledger.open_positions() == []
    closed = rig2.ledger.get_position(position.id)
    assert closed.status == "closed" and closed.token_amount == 0
    assert notes(rig2, "reconcile")[-1]["landed"] is True
    assert rig2.ledger.verify_chain() == (True, None)


def test_a_kill_between_a_landed_buy_and_its_record_never_buys_twice(make_rig, world, fake_clock,
                                                                     tmp_path) -> None:
    path = tmp_path / "live.db"
    rig = live_rig(make_rig, world, fake_clock, path=path)
    rig.broker.after_land = _die
    with pytest.raises(Killed):
        rig.tick()
    landed = rig.broker.tokens[GARY]
    assert landed > 0 and rig.ledger.fills() == [] and rig.ledger.open_positions() == []
    rig.ledger.close()

    rig2 = live_rig(make_rig, world, fake_clock, path=path, sol=rig.broker.sol, tokens=rig.broker.tokens)
    rig2.tick(1)
    assert GARY in rig2.engine.unresolved and rig2.broker.executed == []
    world.candles = dip_rebound_candles(fake_clock.now() + RECONCILE_AFTER_S)
    rig2.tick(RECONCILE_AFTER_S)
    [position] = rig2.ledger.open_positions()
    assert position.token_amount == landed == rig2.broker.tokens[GARY]  # books == wallet, stop-loss covers it
    assert rig2.broker.executed == []  # the setup is still there, but the coin is already held


def test_a_kill_between_the_fill_record_and_the_position_write_leaves_no_half_state(make_rig, world, fake_clock,
                                                                                   tmp_path, monkeypatch) -> None:
    """Fill and position are ONE transaction: dying in between commits neither, so the restart
    reconciles once from the wallet (no orphan fill, no duplicate fill)."""
    path = tmp_path / "live.db"
    rig = live_rig(make_rig, world, fake_clock, path=path)
    real = rig.engine._open_position

    def die_after_the_fill(*args: Any, **kwargs: Any) -> Any:
        real(*args, **kwargs)
        raise Killed()

    monkeypatch.setattr(rig.engine, "_open_position", die_after_the_fill)
    with pytest.raises(Killed):
        rig.tick()
    assert rig.ledger.fills() == [] and rig.ledger.open_positions() == []  # rolled back together
    rig.ledger.close()

    rig2 = live_rig(make_rig, world, fake_clock, path=path, sol=rig.broker.sol, tokens=rig.broker.tokens)
    rig2.tick(1)
    rig2.tick(RECONCILE_AFTER_S)
    [fill] = rig2.ledger.fills()
    [position] = rig2.ledger.open_positions()
    assert position.token_amount == fill.token_amount == rig2.broker.tokens[GARY]
    assert Auditor(rig2.ledger, rig2.broker, rig2.clock).reconcile().token_drift == {}


def test_a_landed_swap_the_ledger_failed_to_record_blocks_entries_and_books_the_actual_fill(
        make_rig, world, fake_clock, monkeypatch) -> None:
    from nightcrawler.ledger import LedgerError

    rig = live_rig(make_rig, world, fake_clock)
    real = rig.ledger.record_fill
    state = {"failed": False}

    def locked_once(fill: Any) -> Any:
        if not state["failed"]:
            state["failed"] = True
            raise LedgerError("sqlite error: database is locked")
        return real(fill)

    monkeypatch.setattr(rig.ledger, "record_fill", locked_once)
    results = rig.tick()
    assert not str(results["watch"]).startswith("error"), results
    assert GARY in rig.engine.unresolved and not rig.engine.entries_allowed
    assert rig.ledger.fills() == [] and rig.broker.tokens[GARY] > 0
    world.candles = dip_rebound_candles(fake_clock.now() + 60)
    rig.tick(60)
    assert rig.broker.executed == ["buy"]  # no second buy while the first is unresolved
    rig.tick(RECONCILE_AFTER_S)
    [fill] = rig.ledger.fills()
    assert fill.signature == "sig1" and fill.fees_lamports == 15_000  # the ACTUAL fill, not an estimate
    [position] = rig.ledger.open_positions()
    assert position.token_amount == rig.broker.tokens[GARY] and position.entry_fill_ids == [fill.id]


def test_a_failed_position_write_rolls_back_the_paper_fill(make_rig, monkeypatch) -> None:
    rig = make_rig()
    real = rig.ledger.upsert_position
    calls = {"n": 0}

    def broken_once(position: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk full")
        real(position)

    monkeypatch.setattr(rig.ledger, "upsert_position", broken_once)
    start = rig.broker.balances()
    rig.tick()
    assert rig.ledger.fills() == [] and rig.ledger.open_positions() == []  # no orphan fill
    assert rig.broker.balances() == start
    assert Auditor(rig.ledger, rig.broker, rig.clock).reconcile().ok


def test_paper_positions_are_invisible_to_a_live_engine_on_the_same_ledger(make_rig, world, fake_clock,
                                                                           tmp_path) -> None:
    path = tmp_path / "shared.db"
    paper = make_rig(ledger_path=path)
    paper.tick()
    [pp] = paper.ledger.open_positions()
    assert pp.mode == "paper"
    paper.ledger.close()

    live = live_rig(make_rig, world, fake_clock, path=path, KILL_SWITCH="stop")
    live.engine._boot_checks(fake_clock.now())
    [note] = notes(live, "other_mode_positions")
    assert note["mode"] == "paper" and note["positions"] == [pp.id]
    equity, _sol_usd, balances = live.engine._equity_now()
    assert equity == balances.sol_lamports == 1_000_000_000  # no phantom paper value in live equity
    assert live.engine.sell_all("kill_switch") == []
    world.price *= 0.5
    live.tick(10)
    assert [d for d in live.ledger.decisions(limit=100) if d.action in ("hold", "exit")] == []
    assert live.broker.quotes == []  # never asked to sell tokens the live wallet never had
    assert live.ledger.get_position(pp.id).is_open  # left alone for a paper engine to manage


def test_sell_all_from_another_process_is_not_undone_by_the_engine(make_rig) -> None:
    rig = make_rig()
    rig.tick()
    [position] = rig.ledger.open_positions()
    cli = make_rig(ledger_path=rig.ledger.path)  # `nightcrawler sell-all` beside the running bot
    original = rig.engine._prices

    def prices_then_cli_sells(mints: list[str]) -> dict[str, float]:
        out = original(mints)  # the network call window
        cli.engine.sell_all("manual")
        return out

    rig.engine._prices = prices_then_cli_sells  # type: ignore[method-assign]
    rig.tick(10)
    after = rig.ledger.get_position(position.id)
    assert after.status == "closed" and after.token_amount == 0 and after.exit_reason == "manual"
    assert Auditor(rig.ledger, rig.broker, rig.clock).reconcile().ok


def test_a_sell_that_definitely_failed_is_on_the_record_as_a_hold(make_rig, world, fake_clock) -> None:
    from nightcrawler.broker.base import SwapFailed

    rig = live_rig(make_rig, world, fake_clock)
    rig.tick()
    rig.broker.refuse = SwapFailed("simulation failed: {'InstructionError': [2, {'Custom': 6001}]}")
    world.price *= 0.5
    rig.tick(10)
    [hold] = rig.ledger.decisions(actions=["hold"])
    assert hold.reason.startswith("stop_loss: swap failed") and "simulation failed" in hold.reason


def test_live_wallet_drift_blocks_entries_and_is_shown(make_rig, world, fake_clock) -> None:
    from nightcrawler.dashboard import build_state
    from nightcrawler.engine import DRIFT_CHECK_S

    rig = live_rig(make_rig, world, fake_clock)
    rig.tick()
    [position] = rig.ledger.open_positions()
    assert rig.engine.drift == {}
    rig.broker.tokens[GARY] = 0  # sold by hand in Phantom (or a lost record): the books still say held
    rig.tick(DRIFT_CHECK_S)
    assert set(rig.engine.drift) == {GARY} and not rig.engine.entries_allowed
    assert rig.ledger.get_kv("engine.drift")[GARY] == {"books": position.token_amount, "wallet": 0}
    assert notes(rig, "drift")[-1]["mints"] == [GARY]
    state = build_state(rig.ledger, rig.settings, fake_clock.now())
    assert GARY in state["engine"]["status"]["drift"]


def test_a_fresh_live_ledger_refuses_entries_while_the_wallet_holds_untracked_tokens(make_rig, world,
                                                                                     fake_clock) -> None:
    rig = live_rig(make_rig, world, fake_clock, tokens={GARY: 50_000_000_000})  # ~$23 the books never saw
    rig.tick()
    assert GARY in rig.engine.drift and rig.broker.executed == []
    assert rig.ledger.fills() == []


def test_live_start_balance_is_recorded_before_the_first_trade(make_rig, world, fake_clock) -> None:
    rig = live_rig(make_rig, world, fake_clock)
    rig.tick()
    assert rig.broker.executed == ["buy"]  # the first tick traded ...
    assert rig.ledger.get_kv("live.start_lamports") == 1_000_000_000  # ... from a recorded starting balance
    assert rig.ledger.get_kv("live.start_sol_usd") == SOL_USD
    assert notes(rig, "live_start")[0]["start_lamports"] == 1_000_000_000


def test_reconcile_without_a_sol_price_uses_the_quote_or_waits(make_rig, world, fake_clock) -> None:
    from nightcrawler.sources.jupiter import JupiterError

    rig = live_rig(make_rig, world, fake_clock)
    rig.broker.after_land = _timeout
    rig.tick()
    assert GARY in rig.engine.unresolved
    rig.broker.sol_price_error = JupiterError("price v3 returned no SOL price")
    saved = rig.engine.unresolved[GARY]["quote"]
    rig.engine.unresolved[GARY]["quote"] = {**saved, "in_usd": None}  # no price anywhere: wait, never book 0
    rig.tick(RECONCILE_AFTER_S)
    assert GARY in rig.engine.unresolved and rig.ledger.fills() == []
    rig.engine.unresolved[GARY]["quote"] = saved  # the quote's own USD valuation is enough
    rig.tick(10)
    [fill] = rig.ledger.fills()
    [position] = rig.ledger.open_positions()
    assert fill.sol_usd == pytest.approx(SOL_USD) and position.entry_price_usd > 0


@pytest.mark.parametrize("move,reason", [(1.0, "time_stop"), (0.5, "stop_loss")])
def test_a_position_without_an_entry_price_still_exits(make_rig, move, reason) -> None:
    rig = make_rig()
    rig.tick()
    [position] = rig.ledger.open_positions()
    position.entry_price_usd = 0.0
    rig.ledger.upsert_position(position)
    rig.world.price *= move
    rig.tick(10 if move < 1 else rig.settings.max_hold_min * 60 + 10)
    [closed] = rig.ledger.positions(status="closed")
    assert closed.exit_reason == reason


def test_a_reconciled_partial_take_profit_counts_as_taken(make_rig, world, fake_clock) -> None:
    rig = live_rig(make_rig, world, fake_clock)
    rig.tick()
    [position] = rig.ledger.open_positions()
    bought = position.token_amount
    world.price = 0.70e-3  # +52 %: partial take-profit
    rig.broker.after_land = _timeout
    rig.tick(10)
    assert rig.engine.unresolved[GARY]["reason"] == "take_profit_partial"
    rig.tick(RECONCILE_AFTER_S)  # reconcile, then the positions stage of the same tick
    [position] = rig.ledger.open_positions()
    assert position.partial_taken and position.token_amount == bought - bought // 2
    assert rig.broker.executed == ["buy", "sell"] and rig.broker.tokens[GARY] == position.token_amount


def test_a_new_position_is_marked_at_the_market_price_not_its_cost(make_rig) -> None:
    rig = make_rig()
    rig.tick()
    [position] = rig.ledger.open_positions()
    point = rig.ledger.latest_equity()
    market = position.value_lamports(rig.world.price, SOL_USD)
    assert point.positions_value_lamports == market < position.cost_lamports


# =========================================================================== review fixes: runtime and strategy


def test_slow_safety_checks_never_starve_open_positions(make_rig) -> None:
    from nightcrawler.models import SafetyReport, TokenCandidate

    rig = make_rig()
    rig.tick()  # GARY bought
    stamps: list[float] = []
    manage = rig.engine.manage_positions

    def counting(now: float) -> None:
        stamps.append(rig.clock.now())
        manage(now)

    def slow_check(c: TokenCandidate, *, force: bool = False) -> SafetyReport:
        rig.clock.advance(30)  # RugCheck 429 with Retry-After, or hanging into timeouts
        return SafetyReport(mint=c.mint, passed=False, hard_fail_reasons=["[top10] 90%"], checked_at=rig.clock.now())

    rig.engine.manage_positions = counting  # type: ignore[method-assign]
    rig.engine.cocoon.check = slow_check  # type: ignore[method-assign]
    rig.engine.queue.extend(TokenCandidate(mint=f"Mint{i}" + "1" * 39, symbol=f"M{i}") for i in range(5))
    start = rig.clock.now() + 30
    rig.tick(30)
    assert rig.clock.now() - start <= 30 + rig.settings.position_interval_s  # discover stopped after its budget
    assert len(rig.engine.queue) >= 3  # the rest waits for the next tick
    assert len(stamps) >= 2 and stamps[-1] > start  # positions ran again after the slow check


def test_the_engine_http_client_fails_fast_on_rugcheck_rpc_and_long_retry_afters(make_settings, fake_clock) -> None:
    settings = make_settings(SOLANA_RPC_URL="https://mainnet.helius-rpc.com/?api-key=abc")
    app = build_app(settings, fake_clock, session=FakeHttp())
    try:
        assert app.http.host_max_retries == {"api.geckoterminal.com": 1, "api.rugcheck.xyz": 1,
                                             "mainnet.helius-rpc.com": 1}
        assert app.http.retry_after_max_s <= 10
    finally:
        app.close()


def test_candles_cover_the_whole_dip_lookback(make_rig) -> None:
    rig = make_rig(CANDLE_WINDOW_MIN=180, DIP_LOOKBACK_H=6)
    rig.tick()
    [call, *_] = rig.world.http.calls_to("/ohlcv/minute")
    assert int(call.params["limit"]) >= 6 * 60 + 1  # the live rolling high sees what the backtest sees


def test_a_rugcheck_not_ready_answer_is_retried_not_final(make_rig) -> None:
    rig = make_rig(KILL_SWITCH="stop")
    rig.world.http.register(f"/tokens/{GARY}/report", {"error": "not found"}, status=400, times=1)
    rig.tick()
    assert GARY not in rig.engine.watchlist
    assert [d for d in rig.ledger.decisions(actions=["reject_cocoon"]) if d.mint == GARY] == []
    rig.tick(150)
    assert GARY in rig.engine.watchlist
    assert len(rig.world.http.calls_to(f"/tokens/{GARY}/report")) == 2


def test_a_stale_market_snapshot_is_never_used_for_an_entry_and_expires(make_rig, tmp_data_dir) -> None:
    from nightcrawler.engine import SNAPSHOT_MISSING_UNWATCH_S

    (tmp_data_dir / "KILL").write_text("stop")
    rig = make_rig()
    rig.tick()
    assert GARY in rig.engine.watchlist
    rig.world.http.register("/tokens/v1/solana/", [])  # DexScreener stops returning the coin
    rig.world.buys_m5, rig.world.sells_m5 = 2, 80
    rig.tick(180)
    (tmp_data_dir / "KILL").unlink()
    rig.world.candles = dip_rebound_candles(rig.clock.now() + 60)
    rig.tick(60)
    assert rig.ledger.fills() == []
    assert "no fresh market snapshot" in (rig.engine.watchlist[GARY].last_signal_reason or "")
    rig.tick(SNAPSHOT_MISSING_UNWATCH_S)
    assert GARY not in rig.engine.watchlist
    assert rig.ledger.decisions(actions=["unwatch"])[0].reason.startswith("no market data for")


def test_candle_fetches_rotate_through_every_dipping_token(make_rig) -> None:
    from nightcrawler.engine import WatchItem
    from nightcrawler.models import Candle, MarketSnapshot, SafetyReport, TokenCandidate

    rig = make_rig()
    now = rig.clock.now()
    drawdowns = [0.95, 0.90, 0.85, 0.60, 0.50, 0.40]
    for i, dd in enumerate(drawdowns):
        mint = f"Mint{i}" + "1" * 39
        item = WatchItem(candidate=TokenCandidate(mint=mint, pool=f"pool{i}"), safety=SafetyReport(mint, True),
                         added_at=now - 3600, candles=[Candle(int(now) - 600, 1.0, 1.0, 1.0, 1.0)],
                         candles_at=now - 120, snapshot_at=now,
                         snapshot=MarketSnapshot(mint=mint, ts=now, price_usd=1.0 - dd, mcap_usd=None,
                                                 liquidity_usd=None))
        rig.engine.watchlist[mint] = item
    picks = {i: 0 for i in range(len(drawdowns))}
    for _ in range(10):
        for item in rig.engine._pick_for_candles(now, set()):
            picks[int(item.mint[4])] += 1
            item.candles_at = now
        now += 60
    assert min(picks.values()) >= 4, picks  # the -60 % token (a live setup) is not starved by dead coins


def test_stale_candles_never_trigger_an_entry(make_rig) -> None:
    rig = make_rig()
    rig.world.candles = dip_rebound_candles(rig.clock.now() - 11 * 60)  # GeckoTerminal 11 minutes behind
    rig.world.price = 0.85e-3  # ... while the coin already ran up
    rig.tick()
    assert rig.ledger.fills() == []
    assert "stale" in (rig.engine.watchlist[GARY].last_signal_reason or "")


def test_a_quote_far_above_the_chase_ceiling_is_rejected(make_rig) -> None:
    rig = make_rig()
    rig.world.price = 0.85e-3  # candles say "dip-rebound at 0.46e-3"; the live price is 85 % higher
    rig.tick()
    assert rig.ledger.fills() == []
    [rejected] = rig.ledger.decisions(actions=["reject_quote"])
    assert "chasing" in rejected.reason


def test_the_safety_report_is_checked_again_before_buying(make_rig, tmp_data_dir) -> None:
    (tmp_data_dir / "KILL").write_text("stop")
    rig = make_rig()
    rig.tick()
    assert GARY in rig.engine.watchlist
    rigged = load_fixture("rugcheck_report") | {"rugged": True}
    rig.world.http.register(f"/tokens/{GARY}/report", rigged)
    (tmp_data_dir / "KILL").unlink()
    rig.clock.advance(4 * 3600)
    rig.world.candles = dip_rebound_candles(rig.clock.now())
    rig.tick()
    assert rig.ledger.fills() == []
    [rejected] = [d for d in rig.ledger.decisions(actions=["reject_cocoon"]) if d.mint == GARY]
    assert "[rugged]" in rejected.reason and GARY not in rig.engine.watchlist


def test_an_open_position_stays_watched_so_the_radar_liquidity_rule_keeps_working(make_rig) -> None:
    rig = make_rig()
    rig.tick()
    rig.world.liquidity = 10_000.0  # below MIN_LIQUIDITY/2: a watched-only token would be dropped
    rig.tick(60)
    assert GARY in rig.engine.watchlist
    now = rig.clock.now()
    rig.world.trades = [{"type": "trade", "attributes": {
        "block_timestamp": iso(now - 30), "tx_hash": "big", "tx_from_address": "Anon11111111111111111111111111111",
        "kind": "sell", "volume_in_usd": "3000", "price_from_in_usd": "0.00046", "from_token_amount": "6500000"}}]
    rig.tick(200)  # past RADAR_INTERVAL_S since the position's first radar scan
    [closed] = rig.ledger.positions(status="closed")
    assert closed.exit_reason.startswith("radar: big sells")
