"""Kill at every point of the order path (the crash review of speed step 2, 2026-10-13, kept as a regression test).

A randomized run takes a crash image (the live directory as a SIGKILL leaves it, with Kalshi's state at that instant)
at each named point: after the decision's reservation, after the journal row, before the send, after the ack, after
a fill is booked in memory, before and after a cancel, before and after a full save, and between steps. Each image is
restarted and run through the window's close and Kalshi's settlement 5 s later, then compared with the venue: startup
finishes, nothing is left resting or reserved, no bot order is unknown to the books, the window settles, and the
books hold exactly Kalshi's fills. Before the release fix 35 of 350 images (the "after_row" and "before_send" ones in
an unpaired window) stayed in "Reconciling startup orders" for good.
"""

from __future__ import annotations

import asyncio
import copy
import os
import random
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from test_speeddesk_live import TICKER, FakeAccount, make_desk
from test_speeddesk_live_crash import OWNERS_CAPS, fill_some, view

from nightcrawler.clock import FakeClock
from nightcrawler.speeddesk_live import KalshiLiveDesk


class IocAccount(FakeAccount):
    """A take is immediate-or-cancel: with no fill modelled it is canceled at once (it never rests)."""

    def create_order(self, **kwargs: Any) -> dict[str, Any]:
        kind = kwargs["kind"]
        reply = super().create_order(**kwargs)
        if kind == "take":
            self.orders[-1].update(status="canceled", remaining_count_fp="0.00")
        return reply


def venue_now(account: FakeAccount, clock: FakeClock) -> IocAccount:
    venue = IocAccount(clock)
    for name in ("orders", "executions", "account_positions", "resolutions", "creates", "cancels"):
        setattr(venue, name, copy.deepcopy(getattr(account, name)))
    venue.cash = account.cash
    return venue


POINTS = ("after_decision", "after_row", "before_send", "after_ack", "after_fill_booked", "before_cancel",
          "after_cancel", "before_save", "after_save", "between_steps")
# The suite keeps a few images of every point (each restart steps through the close); the review ran 6 seeds at
# rate .25 with no cap (350 images): KILLPOINT_SEEDS=6 KILLPOINT_CAP=1000 python -m pytest this file.
SEEDS, CAP = int(os.environ.get("KILLPOINT_SEEDS", "2")), int(os.environ.get("KILLPOINT_CAP", "3"))


def run_with_images(root: Path, seed: int, rate: float, cap: int = CAP) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    desk, account, clock = make_desk(root / "run", caps=OWNERS_CAPS)
    images: list[dict[str, Any]] = []
    taken: Counter[str] = Counter()

    def image(point: str) -> None:
        if rng.random() >= rate or taken[point] >= cap:
            return
        taken[point] += 1
        target = root / f"img-{len(images)}"
        shutil.copytree(desk.directory, target, ignore=shutil.ignore_patterns("*-shm", "controller.lock"))
        images.append({"point": point, "dir": target, "now": clock.now(), "venue": venue_now(account, clock),
                       "memory_reserved": desk.book.reserved_usd})

    journal, checkpoint, record_fill = desk._journal_intent, desk.checkpoint, desk.book.record_fill
    reserve = desk.book.reserve_intent
    create, cancel = account.create_order, account.cancel

    def journaled(intent: Any, window: Any, **kwargs: Any) -> None:
        if kwargs.get("durable", True):  # the pre-send row (a refusal's rewrite is not a decision)
            image("after_decision")
        journal(intent, window, **kwargs)
        image("after_row")

    def saving(durable: bool = False) -> None:
        image("before_save")
        checkpoint(durable)
        image("after_save")

    def booked(fill: Any) -> bool:
        result = record_fill(fill)
        if result:
            image("after_fill_booked")
        return result

    def sending(**kwargs: Any) -> dict[str, Any]:
        guard = kwargs.pop("before_send")

        def guarded() -> bool:
            permitted = guard()
            if permitted:
                image("before_send")
            return permitted

        reply = create(**kwargs, before_send=guarded)
        image("after_ack")
        return reply

    def canceling(order_id: str, *, ticker: str) -> dict[str, Any]:
        image("before_cancel")
        reply = cancel(order_id, ticker=ticker)
        image("after_cancel")
        return reply

    desk._journal_intent = journaled  # type: ignore[method-assign]
    desk.checkpoint = saving  # type: ignore[method-assign]
    desk.book.record_fill = booked  # type: ignore[method-assign]
    desk.book.reserve_intent = reserve  # type: ignore[method-assign]
    account.create_order = sending  # type: ignore[method-assign]
    account.cancel = canceling  # type: ignore[method-assign]
    try:
        for _ in range(90):
            up_ask = round(rng.uniform(.25, .75), 2)
            view(desk, clock, 80000 + rng.uniform(-600, 600), up_ask, round(min(.95, max(.05, 1.02 - up_ask)), 2))
            if rng.random() < .35:
                fill_some(account, clock, rng)
            asyncio.run(desk.step())
            image("between_steps")
            clock.advance(rng.choice((.1, .3, .6, 1.2)))
    finally:
        desk.close()
    return images


def settle_venue(venue: FakeAccount, close: float, up_wins: bool) -> None:
    net = sum(float(fill["count_fp"]) * (1 if fill["outcome_side"] == "yes" else -1) for fill in venue.executions)
    venue.account_positions = []
    venue.resolutions = [{"ticker": TICKER, "market_result": "yes" if up_wins else "no",
                          "revenue": round(max(net if up_wins else -net, 0.0) * 100), "settled_time": close + 5}]


def after_restart(item: dict[str, Any], settings: Any) -> dict[str, Any]:
    venue: IocAccount = item["venue"]
    moment = FakeClock(item["now"])
    venue.clock = moment
    desk = KalshiLiveDesk(settings, item["dir"], lambda: None, clock=moment.now,  # type: ignore[arg-type,return-value]
                          client_factory=lambda: venue, direct_member_verified=True)
    try:
        from nightcrawler.speeddesk_live import LiveSnapshot
        window = desk.book.windows.get(TICKER)
        if window is None:
            from nightcrawler.speeddesk_model import Window
            start = FakeClock().now()
            window = Window(TICKER, start - 10, start + 890, start_price=80000, venue_start_price=80000, venue="kalshi",
                            taker_coefficient=.07, maker_coefficient=0, min_trade_qty=.01, fee_rounding="kalshi",
                            exchange_index=2)
        desk.snapshot = lambda: LiveSnapshot((window,), {}, 80000, moment.now(), .001,  # type: ignore[method-assign]
                                             frozenset({TICKER}))
        desk.on_windows([window])  # production calls on_windows right after constructing the companion
        close = window.end
        # Restart: no new fills; Kalshi lists what it had at the kill. The window runs to its close, Kalshi
        # settles 5 s after it (as on 2026-10-13), and the desk keeps stepping for 3 minutes more (the release
        # needs two complete lists 30 s apart after the close).
        stuck_since = None
        done_at = None
        settled = False
        while moment.now() < close + 180:
            if not settled and moment.now() >= close + 5:
                settled = True
                settle_venue(venue, close, up_wins=True)
            view(desk, moment, 80000, .55, .55)
            asyncio.run(desk.step())
            if desk.startup_done and done_at is None:
                done_at = moment.now()
            if not desk.startup_done and stuck_since is None:
                stuck_since = moment.now()
            moment.advance(20 if moment.now() < close - 30 else 5)
        bot_orders = {order["client_order_id"] for order in venue.orders}
        orphans = sorted(bot_orders - set(desk.intents))
        active = sorted(key for key, value in desk.book.intents.items() if value.reservation_active)
        resting = [order["client_order_id"] for order in venue.orders if order["status"] == "resting"]
        return {"point": item["point"], "startup_done": desk.startup_done, "reason": desk.reason,
                "waiting": desk._waiting_reason(), "settled": TICKER in desk.book.settled,
                "has_fills": bool(venue.executions), "orphans": orphans, "active": active, "resting": resting,
                "integrity": desk.book.integrity_error, "fatal": desk.fatal_reason,
                "creates_after": len(venue.creates), "inventory_up": desk.book.inventory[TICKER].up.shares,
                "inventory_down": desk.book.inventory[TICKER].down.shares,
                "venue_up": sum(float(f["count_fp"]) for f in venue.executions if f["outcome_side"] == "yes"),
                "venue_down": sum(float(f["count_fp"]) for f in venue.executions if f["outcome_side"] == "no"),
                "restored_reserved_vs_memory": None}
    finally:
        desk.close()


@pytest.mark.parametrize("seed", range(SEEDS))
def test_kill_anywhere_then_restart_matches_kalshi(tmp_path: Path, seed: int) -> None:
    images = run_with_images(tmp_path, seed, rate=.25)
    settings = make_desk(tmp_path / "settings", caps=OWNERS_CAPS)[0]
    settings.close()
    results = [after_restart(item, settings.settings) for item in images]
    counts = Counter(result["point"] for result in results)
    bad = [result for result in results
           if not result["startup_done"] or result["orphans"] or result["active"] or result["resting"]
           or result["integrity"] or result["fatal"] or (result["has_fills"] and not result["settled"])
           or abs(result["inventory_up"] - result["venue_up"]) > 1e-9
           or abs(result["inventory_down"] - result["venue_down"]) > 1e-9]
    print(f"\nSEED {seed} images={len(results)} points={dict(counts)}")
    for result in bad:
        print("BAD", {key: result[key] for key in ("point", "startup_done", "waiting", "settled", "has_fills",
                                                    "orphans", "active", "resting", "integrity", "fatal",
                                                    "inventory_up", "venue_up", "inventory_down", "venue_down")})
    assert not bad
