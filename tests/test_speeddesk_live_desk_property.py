"""The live desk against a truthful, adversarial fake Kalshi (the caps review of 2026-10-13, kept as a test).

Creates are refused, time out (landed or lost) or arrive up to 20 s late; cancels fail after executing or not at
all; reads fail, the feed goes stale, the process restarts, and settlement goes against the bot. The suite runs a
few thousand events per case; the review ran 10,000 per seed: REVIEW_EVENTS=10000 REVIEW_SEEDS=4.

Venue truth (never the desk's own book) is checked after every event:
  * every create is <= 5 contracts, and its full reservation was durable on disk before the request arrived
  * per window: bot spend + every resting/in-flight bot order at its worst cost <= $10 (lock windows exempt)
  * sum of every unsettled window's worst case (all fill combinations of resting and in-flight orders) <= $20
  * realized day loss + worst case < $6 day stop; realized total loss + worst case < $10 total stop
  * the desk's own at_risk is never below the venue's worst case
"""

from __future__ import annotations

import asyncio
import itertools
import math
import os
import random
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from nightcrawler.clock import FakeClock
from nightcrawler.config import Secret, Settings
from nightcrawler.ledger import Ledger
from nightcrawler.speeddesk_kalshi_client import KalshiClientError
from nightcrawler.speeddesk_live import KalshiLiveDesk, LiveSnapshot, durable_state
from nightcrawler.speeddesk_live_model import reserve_unit_cost
from nightcrawler.speeddesk_model import Book, Level, Window, fair_up, utc_day

EPS = 1e-6
OWNER_CAPS = {"speeddesk_kalshi_window_usd": 10.0, "speeddesk_kalshi_open_usd": 20.0,
              "speeddesk_kalshi_day_stop_usd": 6.0, "speeddesk_kalshi_total_stop_usd": 10.0}
# Original tiny-budget case: its $1 daily allowance cannot fund one conservative starter-plus-hedge pair.
TIGHT_CAPS = {"speeddesk_kalshi_window_usd": 3.0, "speeddesk_kalshi_open_usd": 6.0,
              "speeddesk_kalshi_day_stop_usd": 1.0, "speeddesk_kalshi_total_stop_usd": 2.0}
# Separate synthetic coverage of a feasible one-contract start under tight limits; not production settings.
FEASIBLE_TIGHT_CAPS = {**TIGHT_CAPS, "speeddesk_kalshi_day_stop_usd": 1.5}
T0 = 1_791_892_800.0 - 4 * 900 + 5  # an hour before a UTC midnight
EVENTS = int(os.environ.get("REVIEW_EVENTS", "2000"))


class Venue:
    """Kalshi as the bot sees it, with adversarial outcomes. Truth lives here."""

    def __init__(self, rng: random.Random, clock: FakeClock) -> None:
        self.rng, self.clock = rng, clock
        self.orders: list[dict[str, Any]] = []
        self.fills_rows: list[dict[str, Any]] = []
        self.inflight: list[tuple[float, dict[str, Any]]] = []  # creates held in a network buffer
        self.resolutions: list[dict[str, Any]] = []
        self.closed: dict[str, bool] = {}
        self.ends: dict[str, float] = {}
        self.creates: list[dict[str, Any]] = []
        self.cash = 60.0
        self.ledger_path: Path | None = None
        self.counts: Counter[str] = Counter()
        self.fail_reads = 0
        self.ids = itertools.count(1)
        self.violations: list[str] = []  # the desk swallows exceptions from create_order, so record, then assert

    # -- account reads -------------------------------------------------------------------------------------------
    def _maybe_fail(self, operation: str) -> None:
        if self.fail_reads > 0:
            self.fail_reads -= 1
            raise KalshiClientError(operation, "request rejected", status=503)

    def balance(self) -> dict[str, Any]:
        self._maybe_fail("balance")
        return {"balance_dollars": f"{max(0.0, self.cash):.4f}"}

    def subaccount_balances(self) -> list[dict[str, Any]]:
        return [{"subaccount_number": 0, "exchange_index": 2, "balance": f"{max(0.0, self.cash):.4f}"}]

    def list_orders(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._maybe_fail("list_orders")
        since = kwargs.get("min_ts", 0)
        return [dict(order) for order in self.orders if order["created_ts"] >= since]

    def fills(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._maybe_fail("fills")
        since = kwargs.get("min_ts", 0)
        return [dict(row) for row in self.fills_rows if row["ts"] >= since]

    def positions(self, **_kwargs: Any) -> list[dict[str, Any]]:
        net: dict[str, float] = {}
        for row in self.fills_rows:
            if row["ticker"] in self.closed:
                continue
            sign = 1 if row["outcome_side"] == "yes" else -1
            net[row["ticker"]] = net.get(row["ticker"], 0.0) + sign * float(row["count_fp"])
        return [{"ticker": ticker, "position_fp": f"{value:.2f}"} for ticker, value in net.items() if abs(value) > 1e-9]

    def settlements(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return [dict(row) for row in self.resolutions]

    # -- writes --------------------------------------------------------------------------------------------------
    def _durable_check(self, client_order_id: str, size: float) -> None:
        assert self.ledger_path is not None
        ledger = Ledger(self.ledger_path, read_only=True)
        try:
            saved = durable_state(ledger)
        finally:
            ledger.close()
        assert saved is not None and client_order_id in saved["book"]["intents"], "sent before its durable row"
        row = saved["book"]["intents"][client_order_id]
        assert row["reservation_active"] and row["size"] == size, row

    def _order(self, kwargs: dict[str, Any], status: str = "resting") -> dict[str, Any]:
        side = kwargs["side"]
        order = {"order_id": f"order-{next(self.ids)}", "client_order_id": kwargs["client_order_id"],
                 "ticker": kwargs["ticker"], "status": status, "fill_count_fp": "0.00",
                 "remaining_count_fp": f"{kwargs['size']:.2f}", "initial_count_fp": f"{kwargs['size']:.2f}",
                 "outcome_side": "yes" if side == "up" else "no", "book_side": "bid" if side == "up" else "ask",
                 "yes_price_dollars": f"{kwargs['price'] if side == 'up' else 1 - kwargs['price']:.4f}",
                 "no_price_dollars": f"{kwargs['price'] if side == 'down' else 1 - kwargs['price']:.4f}",
                 "created_ts": self.clock.now(), "_kind": kwargs["kind"], "_price": kwargs["price"],
                 "_side": side, "_size": kwargs["size"], "_expires": kwargs.get("expiration_ts")}
        return order

    def _land(self, kwargs: dict[str, Any]) -> dict[str, Any] | None:
        """The request reaches the matching engine (refused once the market has closed)."""
        if kwargs["ticker"] in self.closed or self.clock.now() >= self.ends[kwargs["ticker"]]:
            self.counts["late_create_refused_closed"] += 1
            return None
        order = self._order(kwargs)
        self.orders.append(order)
        if kwargs["kind"] == "take":  # immediate or cancel: fill some or all now, cancel the rest
            filled = self.rng.choice((0, kwargs["size"], kwargs["size"], math.floor(kwargs["size"] / 2)))
            if filled:
                self._fill(order, filled)
            order.update(status="executed" if filled >= kwargs["size"] else "canceled", remaining_count_fp="0.00")
        return order

    def create_order(self, **kwargs: Any) -> dict[str, Any]:
        guard = kwargs.pop("before_send")
        if not guard():
            raise KalshiClientError("create_order", "send_guard_rejected", uncertain=False)
        if kwargs["size"] > 5 + 1e-9:
            self.violations.append(f"clip {kwargs}")  # the 5-contract clip
        try:
            self._durable_check(kwargs["client_order_id"], kwargs["size"])
        except AssertionError as exc:
            self.violations.append(f"not durable before send: {exc}")
        self.creates.append(dict(kwargs))
        fate = self.rng.random()
        if fate < .04:
            self.counts["create_definite_reject"] += 1
            raise KalshiClientError("create_order", "request rejected", status=400)
        if fate < .07:
            self.counts["create_timeout_landed"] += 1
            self._land(kwargs)
            raise KalshiClientError("create_order", "result unconfirmed", uncertain=True, timed_out=True)
        if fate < .09:
            self.counts["create_timeout_lost"] += 1
            raise KalshiClientError("create_order", "result unconfirmed", uncertain=True, timed_out=True)
        if fate < .11:
            self.counts["create_delayed"] += 1  # held up in a buffer; arrives within 20 s, or never after the close
            self.inflight.append((self.clock.now() + self.rng.uniform(.5, 20), dict(kwargs)))
            raise KalshiClientError("create_order", "result unconfirmed", uncertain=True, timed_out=True)
        order = self._land(kwargs)
        if order is None:
            raise KalshiClientError("create_order", "request rejected", status=400)
        return {"order_id": order["order_id"], "ts_ms": int(self.clock.now() * 1000)}

    def cancel(self, order_id: str, *, ticker: str) -> dict[str, Any]:
        order = next((item for item in self.orders if item["order_id"] == order_id), None)
        fate = self.rng.random()
        if fate < .05:
            self.counts["cancel_error_not_done"] += 1
            raise KalshiClientError("cancel", "result unconfirmed", status=502, uncertain=True)
        if order is None or order["status"] != "resting":
            raise KalshiClientError("cancel", "request rejected", status=404)
        assert order["ticker"] == ticker
        reduced = float(order["remaining_count_fp"])
        order.update(status="canceled", remaining_count_fp="0.00")
        if fate < .08:
            self.counts["cancel_error_done"] += 1
            raise KalshiClientError("cancel", "result unconfirmed", status=502, uncertain=True)
        return {"reduced_by": reduced, "ts_ms": int(self.clock.now() * 1000)}

    def close(self) -> None:
        pass

    # -- the market moving ---------------------------------------------------------------------------------------
    def _fill(self, order: dict[str, Any], size: float) -> None:
        price = order["_price"]
        if order["_kind"] == "take":
            price = self.rng.randint(max(1, round(price * 100) - 3), round(price * 100)) / 100
        unit = reserve_unit_cost(order["_price"], .07 if order["_kind"] == "take" else 0.0, .0001)
        fee = max(0.0, math.floor((size * unit - size * price) * 10000 + 1e-7) / 10000)  # as much as allowed
        outcome = "yes" if order["_side"] == "up" else "no"
        self.fills_rows.append({"fill_id": f"fill-{next(self.ids)}", "order_id": order["order_id"],
                                "ticker": order["ticker"], "outcome_side": outcome, "book_side": order["book_side"],
                                "count_fp": f"{size:.2f}", f"{outcome}_price_dollars": f"{price:.4f}",
                                "fee_cost": f"{fee:.4f}", "ts": self.clock.now(),
                                "is_taker": order["_kind"] == "take"})
        filled = float(order["fill_count_fp"]) + size
        remaining = float(order["remaining_count_fp"]) - size
        order.update(fill_count_fp=f"{filled:.2f}", remaining_count_fp=f"{max(0.0, remaining):.2f}")
        if remaining <= 1e-9:
            order["status"] = "executed"
        self.cash -= size * price + fee

    def tick(self) -> None:
        now = self.clock.now()
        for at, kwargs in list(self.inflight):
            if at <= now:
                self.inflight.remove((at, kwargs))
                if self._land(kwargs) is not None:
                    self.counts["delayed_create_landed"] += 1
        for order in self.orders:
            if order["status"] != "resting":
                continue
            if order["_expires"] is not None and now >= order["_expires"] or now >= self.ends[order["ticker"]]:
                order.update(status="canceled", remaining_count_fp="0.00")
                continue
            if order["client_order_id"].startswith("nc-speed-") and self.rng.random() < .08:
                remaining = float(order["remaining_count_fp"])
                size = self.rng.choice((remaining, remaining, 1.0, .01, math.floor(remaining / 2) or remaining))
                self._fill(order, min(size, remaining))
                self.counts["maker_fill"] += 1

    def settle_due(self, outcomes: dict[str, bool]) -> None:
        now = self.clock.now()
        for ticker, end in self.ends.items():
            if ticker in self.closed or now < end + 5:
                continue
            up = sum(float(r["count_fp"]) for r in self.fills_rows if r["ticker"] == ticker and r["outcome_side"] == "yes")
            down = sum(float(r["count_fp"]) for r in self.fills_rows if r["ticker"] == ticker and r["outcome_side"] == "no")
            # Adversarial: the side the bot holds less of wins (most of the time).
            up_wins = (up < down) if abs(up - down) > 1e-9 and self.rng.random() < .85 else self.rng.random() < .5
            pairs = min(up, down)
            payout = (up if up_wins else down) - pairs
            self.closed[ticker] = up_wins
            outcomes[ticker] = up_wins
            self.cash += payout
            self.resolutions.append({"ticker": ticker, "market_result": "yes" if up_wins else "no",
                                     "revenue": round(payout * 100), "settled_time": now})

    # -- truth -----------------------------------------------------------------------------------------------------
    def truth(self, lock_tickers: set[str]) -> dict[str, Any]:
        """Venue-side worst cases from the venue's own records (resting and in-flight orders as pending legs)."""
        per: dict[str, dict[str, Any]] = {}
        for row in self.fills_rows:
            item = per.setdefault(row["ticker"], {"up": 0.0, "down": 0.0, "spent": 0.0, "legs": []})
            outcome = row["outcome_side"]
            size = float(row["count_fp"])
            item["up" if outcome == "yes" else "down"] += size
            item["spent"] += size * float(row[f"{outcome}_price_dollars"]) + float(row["fee_cost"])
        pending = [(order["ticker"], order["_side"], float(order["remaining_count_fp"]), order["_price"],
                    order["_kind"]) for order in self.orders if order["status"] == "resting"]
        pending += [(kw["ticker"], kw["side"], kw["size"], kw["price"], kw["kind"]) for _at, kw in self.inflight]
        for ticker, side, size, price, kind in pending:
            item = per.setdefault(ticker, {"up": 0.0, "down": 0.0, "spent": 0.0, "legs": []})
            unit = reserve_unit_cost(price, .07 if kind == "take" else 0.0, .0001)
            item["legs"].append((side, size, size * unit))
        worst_total, out = 0.0, {}
        for ticker, item in per.items():
            if ticker in self.closed:
                continue
            worst = 0.0
            for flags in itertools.product((False, True), repeat=len(item["legs"])):
                shares, paid = {"up": item["up"], "down": item["down"]}, item["spent"]
                for include, (side, size, cost) in zip(flags, item["legs"], strict=True):
                    if include:
                        shares[side] += size
                        paid += cost
                worst = max(worst, paid - min(shares.values()))
            gross = item["spent"] + sum(cost for _s, _z, cost in item["legs"])
            out[ticker] = {"worst": worst, "gross": gross, "legs": len(item["legs"])}
            worst_total += worst
        realized_day: dict[str, float] = {}
        realized = 0.0
        for row in self.resolutions:
            ticker = row["ticker"]
            spent = sum(float(r["count_fp"]) * float(r[f"{r['outcome_side']}_price_dollars"]) + float(r["fee_cost"])
                        for r in self.fills_rows if r["ticker"] == ticker)
            up = sum(float(r["count_fp"]) for r in self.fills_rows if r["ticker"] == ticker and r["outcome_side"] == "yes")
            down = sum(float(r["count_fp"]) for r in self.fills_rows if r["ticker"] == ticker and r["outcome_side"] == "no")
            pnl = (up if self.closed[ticker] else down) - spent
            day = utc_day(row["settled_time"])
            realized_day[day] = realized_day.get(day, 0.0) + pnl
            realized += pnl
        return {"windows": out, "worst": worst_total, "day_pnl": realized_day, "pnl": realized,
                "lock_tickers": lock_tickers}


class Sim:
    def __init__(self, seed: int, root: Path, caps: dict[str, float]) -> None:
        self.rng = random.Random(seed)
        self.root = root
        self.clock = FakeClock(T0)
        self.venue = Venue(self.rng, self.clock)
        self.windows: dict[str, Window] = {}
        self.outcomes: dict[str, bool] = {}
        self.bitcoin = 80000.0
        self.stale_until = -math.inf
        self.counts: Counter[str] = Counter()
        self.first_sizes: dict[str, float] = {}
        self._books: dict[tuple[str, str], Book] = {}
        self.max_seen = {"window_gross": 0.0, "open_worst": 0.0, "day_phi": 0.0, "total_phi": 0.0}
        self.settings = Settings(data_dir=root, speeddesk_kalshi_mode="live",
                                 speeddesk_kalshi_live_confirm=Secret("yes"), kalshi_key_id=Secret("fake-key-id"),
                                 kalshi_private_key=Secret("fake-private-key"), **caps)
        self.caps = caps
        self.desk = self._open()
        self.venue.ledger_path = root / "live" / "receipts.db"

    def _open(self) -> KalshiLiveDesk:
        desk = KalshiLiveDesk(self.settings, self.root / "live", self.snapshot, clock=self.clock.now,
                              client_factory=lambda: self.venue, direct_member_verified=True)
        desk.on_windows(list(self.windows.values()))
        return desk

    def current(self) -> list[Window]:
        now = self.clock.now()
        return [w for w in self.windows.values() if w.start <= now < w.end]

    def add_windows(self) -> None:
        now = self.clock.now()
        start = (math.floor((now - 5) / 900) * 900) + 5
        for begin in (start, start + 900):
            slug = f"KXBTC15M-R{int(begin)}"
            if slug not in self.windows and begin <= now + 60:
                window = Window(slug, begin, begin + 900, start_price=self.bitcoin, venue_start_price=self.bitcoin,
                                venue="kalshi", taker_coefficient=.07, maker_coefficient=0, min_trade_qty=.01,
                                fee_rounding="kalshi", exchange_index=2)
                self.windows[slug] = window
                self.venue.ends[slug] = window.end
                self.desk.on_windows([window])

    def books(self) -> dict[tuple[str, str], Book]:
        now, books = self.clock.now(), {}
        for window in self.current():
            up = fair_up(self.bitcoin, window.start_price or self.bitcoin, .001, window.end - now,
                         settles_on_average=True) or .5
            for side, fair in (("up", up), ("down", 1 - up)):
                ask = min(.99, max(.01, round(fair + self.rng.choice((-.06, -.01, .02, .04, .06, .1)), 2)))
                bid = max(.01, round(ask - .03, 2))
                books[(window.slug, side)] = Book(window.slug, side, (Level(bid, 10),), (Level(ask, 10),), now, "b",
                                                  source="rest", requested_at=now)
        return books

    def snapshot(self) -> LiveSnapshot:
        now = self.clock.now()
        current = tuple(self.current())
        bitcoin_at = now - 10 if now < self.stale_until else now - .05
        return LiveSnapshot(current, self._books, self.bitcoin, bitcoin_at, .001,
                            frozenset(w.slug for w in current), dict(self.outcomes))

    def lock_tickers(self) -> set[str]:
        return {intent.window for intent in self.desk.intents.values() if intent.lock}

    def check(self, event: str) -> None:
        caps = self.caps
        assert not self.venue.violations, self.venue.violations
        truth = self.venue.truth(self.lock_tickers())
        for slug, item in truth["windows"].items():
            if slug not in truth["lock_tickers"]:
                assert item["gross"] <= caps["speeddesk_kalshi_window_usd"] + EPS, (event, slug, item)
        assert truth["worst"] <= caps["speeddesk_kalshi_open_usd"] + EPS, (event, truth)
        now = self.clock.now()
        day_loss = max(0.0, -truth["day_pnl"].get(utc_day(now), 0.0))
        total_loss = max(0.0, -truth["pnl"])
        assert day_loss + truth["worst"] < caps["speeddesk_kalshi_day_stop_usd"] + EPS, (event, day_loss, truth)
        grosses = [item["gross"] for slug, item in truth["windows"].items() if slug not in truth["lock_tickers"]]
        for key, value in (("window_gross", max(grosses, default=0.0)), ("open_worst", truth["worst"]),
                           ("day_phi", day_loss + truth["worst"]), ("total_phi", total_loss + truth["worst"])):
            self.max_seen[key] = max(self.max_seen[key], value)
        assert total_loss + truth["worst"] < caps["speeddesk_kalshi_total_stop_usd"] + EPS, (event, total_loss, truth)
        # The desk never thinks it can lose less than the venue says it can (no untracked orders in this run).
        assert self.desk.book.at_risk_usd >= truth["worst"] - EPS, (event, self.desk.book.at_risk_usd, truth)
        for create in self.venue.creates:
            self.first_sizes.setdefault(create["ticker"], create["size"])
        assert all(size <= 5 for size in self.first_sizes.values())

    def step(self) -> None:
        asyncio.run(self.desk.step())

    def run(self, events: int) -> None:
        self.add_windows()
        self._books = self.books()
        for _ in range(events):
            roll = self.rng.random()
            if roll < .55:
                dt = self.rng.choice((.05, .3, 1.1, 1.1, 3.0))
            elif roll < .6:
                dt = self.rng.choice((20.0, 45.0, 90.0))
            else:
                dt = 0.0
            if dt:
                self.clock.advance(dt)
                self.bitcoin *= math.exp(self.rng.gauss(0, .0015 * math.sqrt(dt)))
                self.add_windows()
                self._books = self.books()
                self.desk.on_tick(self.bitcoin, self.clock.now() - .05, self.clock.now())
                for book in self._books.values():
                    self.desk.on_book(book)
            self.venue.tick()
            self.venue.settle_due(self.outcomes)
            special = self.rng.random()
            if special < .003:
                self.venue.fail_reads = self.rng.randint(1, 4)
                self.counts["read_errors"] += 1
            elif special < .006:
                self.stale_until = self.clock.now() + self.rng.uniform(2, 8)
                self.counts["feed_stale"] += 1
            elif special < .008:
                self.desk.close()  # a process crash after the last commit; nothing in memory survives
                self.desk = self._open()
                self.counts["restart"] += 1
            self.step()
            self.counts["step"] += 1
            self.check("step")
        self.desk.close()


SEEDS = int(os.environ.get("REVIEW_SEEDS", "2"))
CASES = ([("owner", OWNER_CAPS, seed) for seed in range(SEEDS)]
         + [(name, caps, 100 + seed) for name, caps in (("tight", TIGHT_CAPS), ("tight-feasible", FEASIBLE_TIGHT_CAPS))
            for seed in range(max(1, SEEDS // 2))])


@pytest.mark.parametrize(("name", "caps", "seed"), CASES, ids=[f"{name}-{seed}" for name, _caps, seed in CASES])
def test_desk_against_adversarial_venue_never_crosses_a_cap(name: str, caps: dict[str, float], seed: int,
                                                            tmp_path: Path) -> None:
    sim = Sim(seed, tmp_path, caps)
    sim.run(EVENTS)
    counts = sim.counts + sim.venue.counts
    print(seed, len(sim.venue.creates), "creates", len(sim.venue.fills_rows), "fills", len(sim.venue.resolutions),
          "settled", dict(sorted(counts.items())), "integrity", sim.desk.book.integrity_error,
          "fatal", sim.desk.fatal_reason, "max", {k: round(v, 4) for k, v in sim.max_seen.items()},
          "pnl", round(sim.desk.book.realized_pnl, 4), "reason", sim.desk.reason)
    if name == "tight":
        # Starter-fit leaves room for the hedge, including the rounded fee reserve. A $1 day budget cannot fit
        # a complete permitted pair; refusing every new order is the required result even through restarts.
        assert not sim.venue.creates and not sim.venue.fills_rows
        assert all(value == 0 for value in sim.max_seen.values())
    else:
        # Feasible budgets keep the original liveness requirement through lost/delayed creates and recovery.
        assert len(sim.venue.creates) > EVENTS / 200, len(sim.venue.creates)
        if name == "tight-feasible":
            assert sim.venue.fills_rows  # the separate small-budget case exercises actual execution too
            assert sim.venue.creates[0]["size"] == 1  # one starter fits the initial budget, before any profit
