"""A scripted practice speed desk run, pinned by ``tests/fixtures/speeddesk_model_golden.json``.

The Kalshi arena adds opt-in fields to :class:`~nightcrawler.speeddesk_model.SpeedConfig`; every default must
keep today's behaviour exactly. This run covers windows on both venues, Bitcoin ticks, books, sell prints,
takes, the starter, balancing, reprices, the cutoff, a settled loss, the day stop and a feed-gap cancel. The
fixture was generated from the model BEFORE any arena field existed:

    python tests/speeddesk_golden.py   # rewrites the fixture; only ever on purpose
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict
from pathlib import Path
from typing import Any

from nightcrawler.speeddesk_model import (
    Book,
    Level,
    PracticeDesk,
    SpeedConfig,
    Trade,
    Window,
)

FIXTURE = Path(__file__).parent / "fixtures" / "speeddesk_model_golden.json"
T0 = 1_791_475_200.0  # 2026-10-08 16:00 UTC
LENGTH = 300.0  # short windows keep the run fast; the model never assumes 15 minutes
GAP = 10.0  # each window settles before the next opens


def _warm(desk: PracticeDesk, until: float, rng: random.Random) -> float:
    """An observed one-second close for the hour before ``until`` (test input, so sigma is ready at once)."""
    tape, price = desk.tape, 80_000.0
    first = int(until) - 3700
    for second in range(first, int(until)):
        price *= math.exp(rng.gauss(0, 0.0004))
        tape.prices[second] = tape.first_prices[second] = price
    tape.prices = {key: value for key, value in tape.prices.items() if key >= int(until) - 3602}
    tape.first_prices = dict(tape.prices)
    tape.started_at, tape.last_at, tape.price = float(first), float(int(until) - 1), price
    return price


def _book(slug: str, side: str, bid: float, ask: float, at: float, sequence: str, ask_size: float = 30.0) -> Book:
    return Book(slug, side, (Level(round(bid, 2), 12.0),), (Level(round(ask, 2), ask_size),), at,  # type: ignore[arg-type]
                sequence, at)


def run(config: SpeedConfig) -> dict[str, Any]:
    """The scripted run's decisions and final state (JSON-ready)."""
    rng = random.Random(20261013)
    desk = PracticeDesk(config)
    spot = _warm(desk, T0 - 5, rng)
    windows = [
        Window("golden-us-1", T0, T0 + LENGTH, None, maker_coefficient=0.0),
        Window("KXBTC15M-golden-2", T0 + LENGTH + GAP, T0 + 2 * LENGTH + GAP, None, taker_coefficient=0.07,
               maker_coefficient=0.0, venue_start_price=None, venue="kalshi", fee_rounding="kalshi"),
        Window("golden-us-3", T0 + 2 * (LENGTH + GAP), T0 + 3 * LENGTH + 2 * GAP, None, maker_coefficient=0.0),
    ]
    events: list[dict[str, Any]] = []
    reasons: dict[str, str] = {}

    def keep(step: str, at: float, decisions: list[Any]) -> None:
        for decision in decisions:
            events.append({"step": step, "t": round(at - T0, 3), **asdict(decision)})

    for window in windows:
        if window.venue == "kalshi":
            window.venue_start_price = None  # the strike arrives later, as on the venue
        desk.add_window(window)
    strike_set = gapped = False
    # Scripted shapes: (from, to) seconds after T0 -> drift per second of the Bitcoin log price, and how the books
    # sit around fair value (ask offset of the cheap side, ask offset of the dear side).
    drifts = [(0, 40, 0.0), (40, 120, -0.00012), (120, 200, 0.00008), (200, 300, -0.0002),
              (300, 360, 0.0), (360, 600, 0.00015), (600, 900, -0.0001)]
    opening: dict[str, float] = {}
    t = T0 - 5.0
    last_second = None
    step = 0
    while t < windows[-1].end + 30:
        step += 1
        second = int(t)
        offset = t - T0
        if second != last_second:
            drift = next((value for low, high, value in drifts if low <= offset < high), 0.0)
            spot *= math.exp(drift + rng.gauss(0, 0.00025))
            desk.tick_btc(spot, t)
            last_second = second
        if not strike_set and offset >= LENGTH + GAP - 2:
            # Kalshi's strike for the next window is known before it opens.
            strike = round(spot * (1 + rng.uniform(-0.0002, 0.0002)), 2)
            replacement = Window("KXBTC15M-golden-2", T0 + LENGTH + GAP, T0 + 2 * LENGTH + GAP, None,
                                 taker_coefficient=0.07, maker_coefficient=0.0, venue_start_price=strike,
                                 venue="kalshi", fee_rounding="kalshi")
            desk.add_window(replacement)
            strike_set = True
        for window in desk.windows.values():
            if not window.start - 2 <= t < window.end or window.start_price is None:
                continue
            opening.setdefault(window.slug, window.start_price)
            left = max(1.0, window.end - t)
            z = math.log(spot / window.start_price) / (0.0004 * math.sqrt(left))
            up = 0.5 * (1 + math.erf(z / math.sqrt(2)))
            index = [item.slug for item in windows].index(window.slug)
            # Window 1 opens with a cheap up ask (a take) and is balanced by resting down bids; window 2 opens with
            # a cheap up ask too, but its down side stays dear and prints only hit up, so it is never balanced (the
            # loss that trips the day stop); window 3 is quoted near fair value and meets the day stop.
            early = t - window.start < (30 if index == 0 else 60)
            for side in ("up", "down"):
                fair = up if side == "up" else 1 - up
                if side == "up":
                    discount = 0.12 if early and index < 2 else 0.01
                else:
                    discount = -0.06 if index == 0 else -0.10 if index == 1 else 0.01
                ask = min(0.99, max(0.02, fair - discount + rng.uniform(-0.005, 0.005)))
                bid = max(0.01, ask - 0.04)
                if step % 2 == 0 or early:
                    book = _book(window.slug, side, bid, ask, t, f"{window.slug}:{side}:{step}")
                    if desk.on_book(book):
                        keep("advance", t, desk.advance(t))
            if step % 7 == 0 and window.start <= t:
                side = "up" if index == 1 or not (step // 7) % 3 else "down"
                fair = up if side == "up" else 1 - up
                price = round(max(0.01, min(0.99, fair - 0.035 + rng.uniform(-0.02, 0.02))), 2)
                trade = Trade(window.slug, side, price, round(rng.uniform(0.5, 6.0), 2), t - 0.05,  # type: ignore[arg-type]
                              f"print-{step}", "sell" if step % 3 else "buy", t)
                keep("trade", t, desk.on_trade(trade, t))
        if step % 2 == 1:
            keep("evaluate", t, desk.evaluate(t, makers_enabled=True,
                                              maker_windows=None if t < windows[2].start else {"golden-us-3"}))
            changed = {slug: reason for slug, reason in desk.last_reason.items() if reasons.get(slug) != reason}
            if changed:
                events.append({"step": "reasons", "t": round(t - T0, 3), "reasons": changed})
                reasons.update(changed)
        if (not gapped and t >= windows[1].start + 60
                and any(order.window == windows[1].slug for order in desk.orders.values())):
            gapped = True  # the venue's stream for window 2 drops: its orders go and its books are forgotten
            keep("gap", t, desk.cancel(t, "KXBTC15M-golden-2", "venue_feed_gap"))
            desk.books = {key: book for key, book in desk.books.items() if key[0] != "KXBTC15M-golden-2"}
        for window in windows:
            if t >= window.end + 5 and not any(item.window == window.slug for item in desk.closed):
                # Each window settles the way that costs this run the most: the day stop must fire.
                inventory = desk.inventory[window.slug]
                up_wins = inventory.up.shares < inventory.down.shares
                keep("settle", t, desk.cancel(t, window.slug, "settled"))
                result = desk.settle(window.slug, up_wins, t)
                if result is not None:
                    events.append({"step": "settlement", "t": round(t - T0, 3), **asdict(result)})
        t += 0.5
    state = desk.to_state()
    tape = state.pop("bitcoin")
    state["bitcoin_digest"] = hashlib.sha256(json.dumps(tape, sort_keys=True).encode()).hexdigest()
    return json.loads(json.dumps({"events": events, "state": state, "openings": opening}, allow_nan=False))


def coverage(result: dict[str, Any]) -> dict[str, int]:
    """How often each behaviour the fixture must cover happened."""
    counts: dict[str, int] = {}
    for event in result["events"]:
        name = event.get("event") or event["step"]
        if name == "reasons":
            for reason in event["reasons"].values():
                counts[f"reason:{reason}"] = counts.get(f"reason:{reason}", 0) + 1
            continue
        key = f"{name}:{event.get('reason') or event.get('kind') or ''}"
        counts[key] = counts.get(key, 0) + 1
    return counts


if __name__ == "__main__":
    output = run(SpeedConfig())
    FIXTURE.write_text(json.dumps(output, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    for key, value in sorted(coverage(output).items()):
        print(f"{value:6d} {key}")
    print("bytes", FIXTURE.stat().st_size)
