"""The tested universe on the live path (G01 + N3, G12): engine identity on ``tests/world.py``.

World decisions are pinned as they were before the universe rules (``HEAD_TRACE``, captured from the
engine at 510f347 on the same world). Every variant below changes ONE fact about GARY and asserts exactly
which decisions the new rules remove or add; everything else stays identical.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Callable

import pytest

from fakes import FakeClock, FakeHttp, load_fixture
from nightcrawler.broker.paper import PaperBroker
from nightcrawler.cocoon import Cocoon
from nightcrawler.crawler import Crawler
from nightcrawler.engine import Engine, WatchItem
from nightcrawler.http import HttpClient
from nightcrawler.judge import Judge
from nightcrawler.ledger import Ledger
from nightcrawler.models import MarketSnapshot, SafetyReport, TokenCandidate
from nightcrawler.radar import Radar
from nightcrawler.risk import RiskManager
from nightcrawler.sources import build_sources
from world import GARY, GARY_POOL, RISKY, World, iso, make_world

START = 1_791_475_200.0
RISKY_REASONS = ("[rugcheck_danger] RugCheck danger: Creator history of rugged tokens, Single holder ownership; "
                 "[top10] top-10 holders own 50.0% (max 30%); [single_holder] one holder owns 49.9% (max 10%); "
                 "[serial_launcher] creator has a history of rugged tokens (RugCheck)")
#: Receipts of the walk below on the unchanged world, captured BEFORE G01/G12 (kind, ts, action|side, mint, ...).
HEAD_TRACE: list[tuple[Any, ...]] = [
    ("decision", START, "reject_cocoon", RISKY, RISKY_REASONS),
    ("decision", START, "watch", GARY, "passed cocoon"),
    ("note", START),
    ("decision", START, "enter", GARY, "dip-rebound: dip 60.0% from high, 2 green closes"),
    ("fill", START, "buy", GARY, 200000000, 42526956521),
    ("decision", START + 10, "exit_partial", GARY, "take_profit_partial"),
    ("fill", START + 10, "sell", GARY, 145587632, 21263478260),
    ("decision", START + 30, "exit", GARY, "trailing_stop"),
    ("fill", START + 30, "sell", GARY, 155986749, 21263478261),
    ("decision", START + 60, "reject_risk", GARY, "[cooldown] closed 0.5 min ago (COOLDOWN_MIN 30)"),
    ("decision", START + 120, "reject_risk", GARY, "[cooldown] closed 1.5 min ago (COOLDOWN_MIN 30)"),
]
#: The paper bankroll note of the first equity point: written whether or not anything is traded.
NOTE = HEAD_TRACE[2]
ONLY_RISKY = [HEAD_TRACE[0], NOTE]


class Bot:
    def __init__(self, tmp_path: Path, make_settings: Callable[..., Any], change: Callable[[World], None]) -> None:
        self.clock, self.http = FakeClock(START), FakeHttp()
        self.world = make_world(self.http, self.clock)
        change(self.world)
        client = HttpClient(session=self.http, clock=self.clock, rate_limits={}, default_rate=None,
                            rng=random.Random(0))
        settings = make_settings(DATA_DIR=str(tmp_path / "bot"))
        settings.ensure_data_dir()
        sources = build_sources(settings, client)
        self.ledger = Ledger(settings.db_path, clock=self.clock)
        self.engine = Engine(settings, clock=self.clock, ledger=self.ledger,
                             crawler=Crawler(sources, settings, self.clock),
                             cocoon=Cocoon(sources, settings, self.clock), radar=Radar(sources, settings, self.clock),
                             judge=Judge(settings, clock=self.clock, ledger=self.ledger),
                             risk=RiskManager(settings, self.ledger, self.clock),
                             broker=PaperBroker(sources.jupiter, self.ledger, settings, self.clock), sources=sources)

    def walk(self) -> list[tuple[Any, ...]]:
        """The whole trade of tests/test_engine.py (entry, partial take-profit, new peak, trailing exit), then
        quiet ticks; returns the receipts as compact tuples."""
        self.engine.tick(self.clock.now())
        for price in (0.70e-3, 0.90e-3, 0.75e-3):
            self.world.price = price
            self.clock.advance(10)
            self.engine.tick(self.clock.now())
        for _ in range(4):
            self.clock.advance(30)
            self.engine.tick(self.clock.now())
        return trace(self.ledger)


def trace(ledger: Ledger) -> list[tuple[Any, ...]]:
    out: list[tuple[Any, ...]] = []
    for r in ledger.receipts():
        p = r.payload
        if r.kind == "decision":
            out.append((r.kind, r.ts, p.get("action"), p.get("mint"), p.get("reason")))
        elif r.kind == "fill":
            out.append((r.kind, r.ts, p.get("side"), p.get("mint"), p.get("sol_lamports"), p.get("token_amount")))
        else:
            out.append((r.kind, r.ts))
    return out


@pytest.fixture
def bot(tmp_path, make_settings):
    made: list[Bot] = []

    def build(change: Callable[[World], None] = lambda w: None) -> Bot:
        made.append(Bot(tmp_path / str(len(made)), make_settings, change))
        return made[-1]

    yield build
    for b in made:
        b.ledger.close()


def gary(world: World) -> dict[str, Any]:
    return next(t for t in world.trending if t["id"] == GARY)


# =========================================================================== identity


def test_the_world_trades_exactly_as_before_the_universe_rules(bot) -> None:
    """GARY is a SOL-quoted pump.fun graduate (graduated at creation, 5 h ago, 994M supply): nothing changes."""
    b = bot()
    assert b.walk() == HEAD_TRACE
    assert b.engine.crawler.stats()["nursery"] == 0 and b.http.calls_to("api.geckoterminal.com/api/v2/networks"
                                                                        "/solana/tokens/") == []


def test_a_coin_that_graduated_10_minutes_ago_waits_for_the_graduation_window(bot) -> None:
    """G12: created 5 h ago (the old creation-age rule let it in at once), graduated 10 min ago: not watched
    during the walk; RISKY's decision is unchanged."""
    b = bot(lambda w: gary(w).update(graduatedAt=iso(START - 600)))
    assert b.walk() == ONLY_RISKY
    assert GARY in b.engine.crawler.nursery and GARY not in b.engine.watchlist


def test_an_untested_launchpad_is_skipped_before_the_cocoon(bot) -> None:
    b = bot(lambda w: gary(w).update(launchpad="bags.fun"))
    assert b.walk() == ONLY_RISKY
    assert b.engine.prefilter_reasons == {"untested launchpad": 1}
    assert b.http.calls_to(f"/tokens/{GARY}/report") == []  # no RugCheck budget spent on it


def test_a_coin_without_a_launchpad_is_skipped_before_the_cocoon(bot) -> None:
    b = bot(lambda w: gary(w).pop("launchpad"))
    assert b.walk() == ONLY_RISKY
    assert b.engine.prefilter_reasons == {"not a pump.fun launch": 1}


def test_a_mayhem_coin_is_thrown_out_by_the_cocoon(bot) -> None:
    """G01: GARY's on-chain mint, but with Mayhem mode's second billion."""
    mint_info = load_fixture("rpc_getAccountInfo_mint")
    mint_info["result"]["value"]["data"]["parsed"]["info"]["supply"] = str(2_000_000_000 * 10**6)
    b = bot(lambda w: w.http.register("api.mainnet-beta.solana.com", mint_info, method="POST"))
    assert b.walk() == [HEAD_TRACE[0], ("decision", START, "reject_cocoon", GARY,
                                        "[mayhem] supply 2,000,000,000 tokens > 1,000,000,000: a Mayhem-mode coin, "
                                        "outside the universe the bot was tested on"), NOTE]


def gt_token_body(completed_at: str) -> dict[str, Any]:
    body = load_fixture("gt_token")
    body["data"]["attributes"]["launchpad_details"]["completed_at"] = completed_at
    return body


def test_a_graduation_time_from_geckoterminal_trades_exactly_as_before(bot) -> None:
    """Jupiter without ``graduatedAt``: one GeckoTerminal token lookup supplies it, and the trade is identical."""
    def change(w: World) -> None:
        gary(w).pop("graduatedAt")
        w.http.register(f"api.geckoterminal.com/api/v2/networks/solana/tokens/{GARY}?",
                        gt_token_body(iso(START - 5 * 3600)))

    b = bot(change)
    assert b.walk() == HEAD_TRACE
    assert len(b.http.calls_to(f"networks/solana/tokens/{GARY}?")) == 1


def test_without_any_graduation_time_the_coin_is_never_traded_blind(bot) -> None:
    def change(w: World) -> None:
        gary(w).pop("graduatedAt")
        w.http.register(f"api.geckoterminal.com/api/v2/networks/solana/tokens/{GARY}?",
                        {"errors": [{"status": "404", "title": "Not Found"}]}, status=404)

    b = bot(change)
    assert b.walk() == ONLY_RISKY
    assert GARY not in b.engine.crawler.seen and GARY not in b.engine.watchlist  # re-checked as Jupiter lists it
    # one GeckoTerminal lookup per GRADUATION_RETRY_S (120 s) of the 150 s walk, never one per poll
    assert len(b.http.calls_to(f"networks/solana/tokens/{GARY}?")) == 2


# =========================================================================== the entry-time check


def watch_item(now: float, **candidate: Any) -> WatchItem:
    c = TokenCandidate(mint=GARY, symbol="Gary", pool=GARY_POOL, created_at=now - 5 * 3600, launchpad="pump.fun",
                       graduated=True, raw={"graduated_at": now - 5 * 3600}, mcap_usd=460_000.0)
    for key, value in candidate.items():
        setattr(c, key, value)
    snap = MarketSnapshot(mint=GARY, ts=now, price_usd=0.46e-3, mcap_usd=460_000.0, liquidity_usd=80_000.0)
    return WatchItem(candidate=c, safety=SafetyReport(mint=GARY, passed=True, checked_at=now), added_at=now,
                     snapshot=snap, snapshot_at=now)


@pytest.mark.parametrize("candidate,problem", [
    ({}, None),
    ({"raw": {"graduated_at": START - 30 * 60}}, None),
    ({"raw": {}}, "graduation time unknown"),  # e.g. watched by an older build: never traded blind
    ({"raw": {"graduated_at": START - 29 * 60}}, "29 min since graduation (< 30 min)"),
    ({"created_at": START - 59 * 60}, "age 59 min outside [60 min, 48 h]"),
    ({"launchpad": "bags.fun"}, "untested launchpad: bags.fun"),
    ({"launchpad": None}, "not a pump.fun launch: no launchpad reported"),
    ({"raw": {"graduated_at": START - 3600, "quote_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"}},
     "not SOL-quoted: quote mint EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
])
def test_the_entry_time_universe_check_mirrors_the_crawler(bot, candidate, problem) -> None:
    b = bot()
    assert b.engine._universe_problem(watch_item(START, **candidate), START) == problem


def test_a_watched_coin_without_a_graduation_time_never_enters(bot) -> None:
    """A watch item from a build before G12 (no graduation time on the candidate): the setup fires, no entry."""
    b = bot()
    poll = b.engine.crawler.poll

    def older_build_poll() -> list[TokenCandidate]:
        out = poll()
        for c in out:
            c.raw.pop("graduated_at", None)
        return out

    b.engine.crawler.poll = older_build_poll  # type: ignore[method-assign]
    b.engine.tick(START)
    assert trace(b.ledger) == HEAD_TRACE[:3]  # RISKY thrown out, GARY watched ... and no entry
    assert b.engine.watchlist[GARY].last_signal_reason == "setup, but graduation time unknown"
