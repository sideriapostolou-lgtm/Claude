"""Speed plan step 2: a crash keeps the pre-send journal row and the last full save, and nothing it needs is lost.

The two kills are real (``os._exit`` in a child process: no shutdown, no save, no flush); the other restarts start
from a copy of the ledger taken mid-run (the disk as a crash leaves it). No account or network is touched.
"""

from __future__ import annotations

import asyncio
import copy
import json
import random
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from test_speeddesk_live import TICKER, FakeAccount, make_desk

from nightcrawler.clock import FakeClock
from nightcrawler.ledger import Ledger
from nightcrawler.speeddesk_live import (
    JOURNAL_KEY,
    ORDER_LIST_LAG_S,
    STATE_KEY,
    KalshiLiveDesk,
    LiveSnapshot,
    durable_state,
)
from nightcrawler.speeddesk_live_model import LiveRiskBook, without_default_lock
from nightcrawler.speeddesk_model import Book, Level, Side

TESTS = Path(__file__).resolve().parent
KILLED = 17

# The child runs the live desk of make_desk until its first order and dies at the named point. "row": after the
# journal row is synced, before any byte of the create leaves. "sent": Kalshi has the order, the reply never came.
CHILD = textwrap.dedent("""
    import asyncio, json, os, sys
    from pathlib import Path

    tests, src, root, where = sys.argv[1:5]
    sys.path[:0] = [src, tests]
    from test_speeddesk_live import make_desk

    root = Path(root)
    desk, account, clock = make_desk(root)
    journal, create = desk._journal_intent, account.create_order

    def journaled(intent, window):
        journal(intent, window)
        status = desk.book.risk_status(clock.now())
        (root / "memory.json").write_text(json.dumps({
            "client_order_id": intent.client_order_id, "at": intent.at,
            "risk": {key: status[key] for key in ("reserved_usd", "at_risk_usd", "day_at_risk_usd",
                                                  "total_at_risk_usd")},
            "worst": desk.book.worst_loss(intent.window)}))

    def killed(**kwargs):
        if where == "row":
            os._exit(17)
        reply = create(**kwargs)  # the request reached Kalshi, which now lists the order
        (root / "venue.json").write_text(json.dumps({"orders": account.orders, "creates": account.creates}))
        os._exit(17)

    desk._journal_intent = journaled
    account.create_order = killed
    asyncio.run(desk.step())
    os._exit(3)  # no order was attempted
""")


def kill_child(root: Path, where: str) -> dict[str, Any]:
    done = subprocess.run([sys.executable, "-c", CHILD, str(TESTS), str(TESTS.parent / "src"), str(root), where],
                          capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == KILLED, done.stderr
    memory: dict[str, Any] = json.loads((root / "memory.json").read_text())
    return memory


def saved_rows(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    ledger = Ledger(root / "live" / "receipts.db")
    try:
        return ledger.get_kv(STATE_KEY), ledger.get_kv(JOURNAL_KEY)
    finally:
        ledger.close()


def restored_risk(desk: KalshiLiveDesk) -> dict[str, float]:
    status = desk.book.risk_status(desk.clock())
    return {key: status[key] for key in ("reserved_usd", "at_risk_usd", "day_at_risk_usd", "total_at_risk_usd")}


def test_a_kill_between_the_journal_row_and_the_send_keeps_the_reservation_then_releases_it(tmp_path: Path) -> None:
    memory = kill_child(tmp_path, "row")
    identity = memory["client_order_id"]
    state, journal = saved_rows(tmp_path)
    # Only the journal row knows the order: the last full save was made before the decision.
    assert identity not in state["intents"] and identity in journal["intents"]
    desk, account, clock = make_desk(tmp_path)  # the restart: same ledger and clock; Kalshi never saw the order
    try:
        assert desk.book.intents[identity].reservation_active and not desk.intents[identity].order_id
        assert restored_risk(desk) == pytest.approx(memory["risk"])
        assert desk.book.worst_loss(TICKER) == pytest.approx(memory["worst"])
        assert any(event.get("client_order_id") == identity and event.get("state", "").startswith("restored")
                   for event in desk.latest_events)
        close, released_at = desk.book.windows[TICKER].end, None
        while clock.now() < close + 3 * 60:
            asyncio.run(desk.step())
            if desk.book.intents[identity].reservation_active:
                # Held in full, and nothing new is sent, while the market trades (a delayed copy of the request
                # could still arrive) and until two complete lists after the close leave it out.
                assert not desk.startup_done and desk.reason == "Reconciling startup orders" and not account.creates
                assert restored_risk(desk)["reserved_usd"] == pytest.approx(memory["risk"]["reserved_usd"])
            elif released_at is None:
                released_at = clock.now()
            clock.advance(20)
        assert released_at is not None and released_at >= close + ORDER_LIST_LAG_S
        assert desk.startup_done and desk.book.reserved_usd == 0 and desk.book.at_risk_usd == 0
        assert desk.intents[identity].terminal and desk.book.intents[identity].uncertainty == "never_reached_venue"
        assert all(create["client_order_id"] != identity for create in account.creates)  # never sent again
        assert not account.cancels and not desk.book.integrity_error
        assert any(event.get("client_order_id") == identity and "never reached Kalshi" in event.get("state", "")
                   for event in desk.latest_events)
    finally:
        desk.close()
    restarted, _, _ = make_desk(tmp_path)  # the release was saved: a later restart does not hold it again
    try:
        assert not restarted.book.intents[identity].reservation_active
    finally:
        restarted.close()


def test_a_late_copy_of_the_request_is_adopted_and_canceled_never_released(tmp_path: Path) -> None:
    """Kalshi lists the order minutes after the crash (the request was held up on the way): it is the bot's order,
    adopted by its client id and canceled; the reservation is released on Kalshi's word, not by absence."""
    memory = kill_child(tmp_path, "row")
    identity = memory["client_order_id"]
    desk, account, clock = make_desk(tmp_path)
    try:
        for _ in range(12):  # four minutes of complete and recent reads without it
            asyncio.run(desk.step())
            clock.advance(20)
        assert desk.book.intents[identity].reservation_active and not desk.startup_done
        intent = desk.intents[identity]
        account.orders.append({"order_id": "late-1", "client_order_id": identity, "ticker": TICKER,
                               "status": "resting", "fill_count_fp": "0.00", "remaining_count_fp": f"{intent.size:.2f}",
                               "initial_count_fp": f"{intent.size:.2f}", "outcome_side": "yes", "book_side": "bid",
                               "yes_price_dollars": str(intent.price), "no_price_dollars": str(round(1 - intent.price, 2))})
        asyncio.run(desk.step())
        assert desk.intents[identity].order_id == "late-1" and account.cancels == ["late-1"]
        assert desk.startup_done and not desk.book.intents[identity].reservation_active
        assert desk.book.intents[identity].status == "canceled" and not desk.book.integrity_error
        assert all(create["client_order_id"] != identity for create in account.creates)
    finally:
        desk.close()


def test_a_kill_after_the_send_before_the_reply_finds_cancels_and_releases_the_order(tmp_path: Path) -> None:
    memory = kill_child(tmp_path, "sent")
    identity = memory["client_order_id"]
    venue = json.loads((tmp_path / "venue.json").read_text())
    assert [order["client_order_id"] for order in venue["orders"]] == [identity]
    state, journal = saved_rows(tmp_path)
    assert identity not in state["intents"] and identity in journal["intents"]
    desk, account, _ = make_desk(tmp_path)
    account.orders, account.creates = venue["orders"], venue["creates"]
    try:
        assert desk.book.intents[identity].reservation_active and not desk.intents[identity].order_id
        assert restored_risk(desk) == pytest.approx(memory["risk"])
        cancel, proofs = account.cancel, []

        def proven_cancel(order_id: str, *, ticker: str) -> dict[str, Any]:
            proofs.append(desk.book.intents[identity].reservation_active)  # still held when the cancel goes out
            return cancel(order_id, ticker=ticker)

        account.cancel = proven_cancel  # type: ignore[method-assign]
        # Startup: the order list names it, so it is adopted and canceled; the next list proves the cancel.
        asyncio.run(desk.step())
        assert desk.intents[identity].order_id == "order-1" and account.cancels == ["order-1"] and proofs == [True]
        assert desk.startup_done and desk.intents[identity].terminal
        assert not desk.book.intents[identity].reservation_active
        assert desk.book.intents[identity].status == "canceled"  # released on Kalshi's word, not by the timer
        # The create was never repeated; trading resumed with new orders only.
        assert [create["client_order_id"] for create in account.creates].count(identity) == 1
        assert not desk.book.integrity_error
    finally:
        desk.close()


def compare(left: Any, right: Any, path: str = "") -> list[str]:
    """Where two saved states differ (an empty list when they are equal)."""
    if isinstance(left, dict) and isinstance(right, dict):
        return [item for key in sorted(set(left) | set(right), key=str)
                for item in (compare(left[key], right[key], f"{path}/{key}") if key in left and key in right
                             else [f"{path}/{key} only on one side"])]
    return [] if left == right else [f"{path}: {left!r} != {right!r}"]


SIDES: tuple[Side, Side] = ("up", "down")


def view(desk: KalshiLiveDesk, clock: FakeClock, bitcoin: float, up_ask: float, down_ask: float) -> None:
    """Bitcoin at ``bitcoin`` and each side's best ask, with a bid three cents under it, all fresh now."""
    current = next(item for item in desk.snapshot().windows if item.slug == TICKER)

    def snapshot() -> LiveSnapshot:
        asks = {"up": up_ask, "down": down_ask}
        books = {(TICKER, side): Book(TICKER, side, (Level(round(asks[side] - .03, 2), 4),), (Level(asks[side], 10),),
                                      clock.now(), "book", source="rest", requested_at=clock.now())
                 for side in SIDES}
        return LiveSnapshot((current,), books, bitcoin, clock.now(), .001, frozenset({TICKER}))
    desk.snapshot = snapshot  # type: ignore[method-assign]


def fill_some(account: FakeAccount, clock: FakeClock, rng: random.Random) -> None:
    """Kalshi fills part or all of one resting order of the bot's, and the account position follows."""
    resting = [order for order in account.orders if order["status"] == "resting"]
    if not resting:
        return
    order = rng.choice(resting)
    remaining = int(float(order["remaining_count_fp"]))
    count = rng.randint(1, remaining)
    filled = int(float(order["fill_count_fp"])) + count
    order.update(fill_count_fp=f"{filled:.2f}", remaining_count_fp=f"{remaining - count:.2f}",
                 status="resting" if remaining > count else "executed")
    outcome = order["outcome_side"]
    price = float(order[f"{outcome}_price_dollars"])
    kind = next(item["kind"] for item in account.creates if item["client_order_id"] == order["client_order_id"])
    fee = int(.07 * price * (1 - price) * count * 10000) / 10000 if kind == "take" else 0.0
    account.executions.append({"fill_id": f"fill-{len(account.executions)}", "order_id": order["order_id"],
                               "ticker": TICKER, "outcome_side": outcome, "book_side": order["book_side"],
                               "count_fp": f"{count:.2f}", f"{outcome}_price_dollars": f"{price:.2f}",
                               "fee_cost": f"{fee:.4f}", "ts": clock.now()})
    net = sum(float(fill["count_fp"]) * (1 if fill["outcome_side"] == "yes" else -1) for fill in account.executions)
    account.account_positions = [{"ticker": TICKER, "position_fp": f"{net:.2f}"}] if net else []


def beat(desk: KalshiLiveDesk, account: FakeAccount, clock: FakeClock, rng: random.Random) -> None:
    """Bitcoin and the Kalshi books move, Kalshi may fill a resting order, and the desk takes one step."""
    up_ask = round(rng.uniform(.25, .75), 2)
    view(desk, clock, 80000 + rng.uniform(-600, 600), up_ask, round(min(.95, max(.05, 1.02 - up_ask)), 2))
    if rng.random() < .35:
        fill_some(account, clock, rng)
    asyncio.run(desk.step())
    clock.advance(rng.choice((.1, .3, .6, 1.2)))


def stop_math(desk: KalshiLiveDesk) -> dict[str, Any]:
    """Everything the caps and stops are computed from, and what they answer for a spread of new orders."""
    now = desk.clock()
    status = desk.book.risk_status(now)
    probes = {f"{side} {kind} {price} x{size}": desk.book.can_buy(TICKER, side, kind, price, size, now)
              for side in ("up", "down") for kind in ("take", "rest") for price in (.2, .45, .7) for size in (1, 5)}
    return {**{key: round(status[key], 9) if isinstance(status[key], float) else status[key]
               for key in ("reserved_usd", "open_cost_usd", "open_loss_usd", "at_risk_usd", "day_loss_usd",
                           "day_at_risk_usd", "day_stopped", "total_loss_usd", "total_at_risk_usd", "halted",
                           "integrity_error")},
            "worst": round(desk.book.worst_loss(TICKER), 9), "probes": probes,
            "reserved": {key: (item.reservation_active, round(item.reserved, 9), item.filled_size)
                         for key, item in desk.book.intents.items()}}


def crash_image(desk: KalshiLiveDesk, target: Path) -> None:
    """The live directory as a crash leaves it: the committed ledger pages and log, nothing from memory."""
    shutil.copytree(desk.directory, target, ignore=shutil.ignore_patterns("*-shm", "controller.lock"))


def serving(venue: FakeAccount) -> Callable[[], FakeAccount]:
    return lambda: venue


def venue_copy(account: FakeAccount, clock: FakeClock) -> FakeAccount:
    """What Kalshi holds at this moment, for a restart to read."""
    venue = FakeAccount(clock)
    for name in ("orders", "executions", "account_positions", "resolutions", "creates", "cancels"):
        setattr(venue, name, copy.deepcopy(getattr(account, name)))
    venue.cash = account.cash
    return venue


OWNERS_CAPS = {"speeddesk_kalshi_window_usd": 10.0, "speeddesk_kalshi_open_usd": 20.0,
               "speeddesk_kalshi_day_stop_usd": 6.0, "speeddesk_kalshi_total_stop_usd": 10.0}


@pytest.mark.parametrize("seed", range(10))
def test_stop_math_is_identical_across_crash_and_graceful_restarts(tmp_path: Path, seed: int) -> None:
    """A restart from any point restores the caps' and stops' inputs: at once after a full save, and after one
    reconcile with Kalshi after a crash; until then a crash can only restore more money at risk, never less."""
    rng = random.Random(seed)
    desk, account, clock = make_desk(tmp_path / "run", caps=OWNERS_CAPS)
    restarts = {"crash": 0, "graceful": 0}
    try:
        for index in range(60):
            beat(desk, account, clock, rng)
            if index % 6 != 5:
                continue
            graceful = rng.random() < .4
            if graceful:
                desk.checkpoint(durable=True)
            before = stop_math(desk)
            image = tmp_path / f"image-{index}"
            crash_image(desk, image)
            moment = FakeClock(clock.now())
            venue = venue_copy(account, moment)
            restored = KalshiLiveDesk(desk.settings, image, desk.snapshot, clock=moment.now,
                                      client_factory=serving(venue), direct_member_verified=True)
            try:
                after = stop_math(restored)
                # Cash is a Kalshi fact read again: until the first read every new order is refused.
                assert set(after.pop("probes").values()) == {"cash_stale"}
                del before["probes"]
                if graceful:
                    assert after == before
                else:
                    # Fills, settlements and stops are saved at once; only a release Kalshi proves again can be
                    # missing, so the restored stops are as strict or stricter, and no order is forgotten.
                    for key in ("day_loss_usd", "total_loss_usd", "halted", "integrity_error", "open_cost_usd"):
                        assert after[key] == before[key], key
                    assert after["at_risk_usd"] >= before["at_risk_usd"] - 1e-9
                    assert after["reserved_usd"] >= before["reserved_usd"] - 1e-9
                    assert set(before["reserved"]) <= set(after["reserved"])
                asyncio.run(restored._ensure_client())
                asyncio.run(restored._reconcile())
                asyncio.run(desk._reconcile())
                assert stop_math(restored) == stop_math(desk)
            finally:
                restored.close()
            restarts["graceful" if graceful else "crash"] += 1
        assert account.creates and account.executions  # the run traded and filled
        assert sum(restarts.values()) == 10
    finally:
        desk.close()


def in_memory(desk: KalshiLiveDesk) -> dict[str, Any]:
    """The books and orders a full save would write now (no window is archived in these runs)."""
    assert not desk.archived
    return {"book": desk.book.to_state(),
            "intents": {key: without_default_lock(asdict(value)) for key, value in desk.intents.items()}}


@pytest.mark.parametrize("seed", range(4))
def test_journal_replay_equals_the_full_save_at_every_send(tmp_path: Path, seed: int) -> None:
    """With every other change saved at once (the old behaviour), what a restart reads at an order's first
    network byte, the last full save plus the journal, is exactly the full save made at that moment."""
    rng = random.Random(seed)
    desk, account, clock = make_desk(tmp_path / "run", caps=OWNERS_CAPS)
    desk._save_soon = desk.checkpoint  # type: ignore[method-assign]
    create, checked = account.create_order, []

    def at_the_send(**kwargs: Any) -> dict[str, Any]:
        replayed = durable_state(desk.ledger)
        assert replayed is not None
        assert kwargs["client_order_id"] in desk.ledger.get_kv(JOURNAL_KEY)["intents"]
        assert kwargs["client_order_id"] not in desk.ledger.get_kv(STATE_KEY)["intents"]
        memory = in_memory(desk)
        for part in ("book", "intents"):
            assert compare(replayed[part], memory[part]) == [], part
        checked.append(kwargs["client_order_id"])
        return create(**kwargs)

    account.create_order = at_the_send  # type: ignore[method-assign]
    try:
        for _ in range(60):
            beat(desk, account, clock, rng)
        assert len(checked) >= 3
        desk.checkpoint()  # the comparison's model of a full save is the full save
        saved, memory = desk.ledger.get_kv(STATE_KEY), in_memory(desk)
        assert compare({part: saved[part] for part in ("book", "intents")}, memory) == []
    finally:
        desk.close()


@pytest.mark.parametrize("seed", range(4))
def test_journal_replay_holds_every_order_and_never_less_risk(tmp_path: Path, seed: int) -> None:
    """With the one-second full save, several orders can sit in the journal. At every send the replay holds each
    order with the rows its decision wrote, the same fills and realized money, and at least the money at risk."""
    rng = random.Random(seed)
    desk, account, clock = make_desk(tmp_path / "run", caps=OWNERS_CAPS)
    create, depths = account.create_order, []

    def at_the_send(**kwargs: Any) -> dict[str, Any]:
        identity = kwargs["client_order_id"]
        replayed = durable_state(desk.ledger)
        assert replayed is not None
        memory = in_memory(desk)
        depths.append(len(desk.ledger.get_kv(JOURNAL_KEY)["intents"]))
        assert replayed["intents"][identity] == memory["intents"][identity]
        assert replayed["book"]["intents"][identity] == memory["book"]["intents"][identity]
        for part in ("inventory", "fills", "settled", "windows", "bootstrap_order"):
            assert compare(replayed["book"][part], memory["book"][part]) == [], part
        for key in ("realized_pnl", "day_pnl", "stop_anchor", "halted", "integrity_error"):
            assert replayed["book"][key] == memory["book"][key], key
        restored = LiveRiskBook.from_state(replayed["book"], desk.book.limits)
        for key, item in desk.book.intents.items():
            if item.reservation_active:  # an order that may be on Kalshi keeps its whole reservation
                assert restored.intents[key].reservation_active and restored.intents[key].reserved == item.reserved
        assert restored.at_risk_usd >= desk.book.at_risk_usd - 1e-9
        assert restored.reserved_usd >= desk.book.reserved_usd - 1e-9
        return create(**kwargs)

    account.create_order = at_the_send  # type: ignore[method-assign]
    try:
        for _ in range(60):
            beat(desk, account, clock, rng)
        assert len(depths) >= 3 and max(depths) >= 2  # some sends found earlier orders still in the journal
    finally:
        desk.close()
