"""Speed step 2's release of an order that never reached Kalshi, in a window holding unpaired contracts.

Review blocker (2026-10-13): Kalshi settles KXBTC15M about 4.7 s after the close (KXBTC15M-26OCT131145 closed
15:45:00 UTC, settled_time 15:45:04.68), and a settled market leaves the unsettled positions list. An unsent order
(a crash between its journal row and the send, or a create lost on the way) kept its window open, so the window was
never settled, every complete read then failed position_mismatch, and the release, which waited for a read with no
failed check at all, never came: real trading stopped for good. A balancing bid or a lock always sits in such a
window. The release now judges each window on its own evidence (two complete order lists after the close without
the order, no unknown fill there, the position matching or Kalshi's settlement row with a flat position) and runs
before the settlement pass, whose payout check audits the result.

Review major (2026-10-13): a definite refusal (our send guard, or a definite 4xx) was only marked for the next
full save; a crash within that second restored the never-sent order as reserved from the journal.

Each kill is real (``os._exit`` in a child process: no shutdown, no save). Kalshi is the fake account.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

from test_speeddesk_live import TICKER, fill_order, make_desk, reopen, steps
from test_speeddesk_live_crash import view

from nightcrawler.speeddesk_kalshi_client import KalshiClientError
from nightcrawler.speeddesk_live import ORDER_LIST_LAG_S, LiveSnapshot
from nightcrawler.speeddesk_model import Book, Level

TESTS = Path(__file__).resolve().parent
KILLED = 17

# The child trades the first buy (take Up 5 at $0.40), books its fill, and dies at the named point while the
# balancing Down bid (or, at lock time, the lock) goes out.
CHILD = textwrap.dedent("""
    import asyncio, json, os, sys
    from pathlib import Path

    tests, src, root, where = sys.argv[1:5]
    sys.path[:0] = [src, tests]
    from test_speeddesk_live import make_desk, TICKER
    from test_speeddesk_live_crash import view

    root = Path(root)
    desk, account, clock = make_desk(root)
    create = account.create_order

    def dump():
        (root / "venue.json").write_text(json.dumps({
            "orders": account.orders, "executions": account.executions,
            "positions": account.account_positions, "creates": account.creates, "now": clock.now(),
            "memory": {key: (item.reservation_active, item.reserved, item.order_id, item.status)
                       for key, item in desk.book.intents.items()}}))

    def killing(**kwargs):
        count = len(account.creates)
        if where in ("second_row", "lock_row") and count == 1:
            dump(); os._exit(17)                      # journal row synced, nothing sent
        if where == "guard_reject_then_kill" and count == 1:
            kwargs["before_send"] = lambda: False     # our own last check refuses: provably never sent
        return create(**kwargs)

    account.create_order = killing
    asyncio.run(desk.step())                          # first buy: take Up 5 @ 0.40
    first = account.orders[0]
    first.update(status="executed", fill_count_fp="5.00", remaining_count_fp="0.00")
    account.executions.append({"fill_id": "fill-0", "order_id": first["order_id"], "ticker": TICKER,
                               "outcome_side": "yes", "book_side": "bid", "count_fp": "5.00",
                               "yes_price_dollars": "0.40", "fee_cost": "0.0168", "ts": clock.now()})
    account.account_positions = [{"ticker": TICKER, "position_fp": "5.00"}]
    for _ in range(4):
        jump = 0.3 if where != "lock_row" else max(0.3, desk.book.windows[TICKER].end - 200 - clock.now())
        clock.advance(jump)
        view(desk, clock, 80000, .55, .55)
        asyncio.run(desk.step())                      # books the fill, then rests the balancing Down bid
        if where == "guard_reject_then_kill" and any("prices moved" in str(e.get("state"))
                                                     for e in desk.latest_events):
            dump(); os._exit(17)                      # within a second of the refusal, before a full save
    os._exit(3)
""")


def kill_child(root: Path, where: str) -> dict[str, Any]:
    done = subprocess.run([sys.executable, "-c", CHILD, str(TESTS), str(TESTS.parent / "src"), str(root), where],
                          capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == KILLED, (done.returncode, done.stderr[-3000:])
    venue: dict[str, Any] = json.loads((root / "venue.json").read_text())
    return venue


def restart(root: Path, venue: dict[str, Any]) -> tuple[Any, Any, Any]:
    desk, account, clock = make_desk(root)
    account.orders, account.executions = venue["orders"], venue["executions"]
    account.account_positions, account.creates = venue["positions"], venue["creates"]
    clock.advance(venue["now"] - clock.now() + 0.5)
    create = account.create_order

    def ioc(**kwargs: Any) -> dict[str, Any]:  # a take is immediate-or-cancel: unfilled, it is canceled at once
        reply = create(**kwargs)
        if kwargs["kind"] == "take":
            account.orders[-1].update(status="canceled", remaining_count_fp="0.00")
        return reply

    account.create_order = ioc
    return desk, account, clock


def run_past_close(desk: Any, account: Any, clock: Any, *, settle_after_s: float = 5.0,
                   until_s: float = 900.0, step_s: float = 5.0, settlement_row: bool = True) -> dict[str, Any]:
    """Step through the close; Kalshi settles the market settle_after_s after it (Up wins, $5 back; no row for an
    account flat in the market). Returns when the window settled and the order was released, and the checks seen."""
    close, seen, released_at, settled_at = desk.book.windows[TICKER].end, set(), None, None
    settled = False
    while clock.now() < close + until_s:
        if not settled and clock.now() >= close + settle_after_s:
            settled = True
            account.account_positions = []  # settlement_status=unsettled: a settled market leaves the list
            if settlement_row:
                account.resolutions = [{"ticker": TICKER, "market_result": "yes", "revenue": 500,
                                        "settled_time": close + settle_after_s}]
        view(desk, clock, 80000, .55, .55)
        asyncio.run(desk.step())
        if desk.last_sync_report:
            seen |= set(desk.last_sync_report["checks"])
        if released_at is None and not any(item.reservation_active for item in desk.book.intents.values()):
            released_at = clock.now()
        if settled_at is None and TICKER in desk.book.settled:
            settled_at = clock.now()
        clock.advance(step_s)
    return {"close": close, "released_at": released_at, "settled_at": settled_at, "checks": sorted(seen)}


def unsent(venue: dict[str, Any]) -> str:
    keys = [key for key, (active, _r, order_id, _s) in venue["memory"].items() if active and order_id is None]
    assert len(keys) == 1
    return keys[0]


def finished(desk: Any, identity: str, timeline: dict[str, Any]) -> None:
    """Released only after the close and two complete lists ORDER_LIST_LAG_S apart; settled on Kalshi's row; the
    books agree with Kalshi; trading back on."""
    intent = desk.book.intents[identity]
    assert not intent.reservation_active and intent.uncertainty == "never_reached_venue", timeline
    assert timeline["released_at"] is not None and timeline["released_at"] >= timeline["close"] + ORDER_LIST_LAG_S
    result = desk.book.settled.get(TICKER)
    assert result is not None and result.up_shares == 5 and result.down_shares == 0, timeline
    assert not desk.book.integrity_error and desk.fatal_reason is None
    assert desk.startup_done and desk.book.reserved_usd == 0 and desk.book.at_risk_usd == 0
    assert desk._waiting_reason() in ("", "Kalshi account data stale")


def test_a_crash_between_the_journal_row_and_the_send_of_a_balancing_bid_is_released_after_the_close(
        tmp_path: Path) -> None:
    venue = kill_child(tmp_path, "second_row")
    identity = unsent(venue)
    desk, account, clock = restart(tmp_path, venue)
    try:
        assert desk.book.intents[identity].reservation_active
        timeline = run_past_close(desk, account, clock)
        finished(desk, identity, timeline)
        assert timeline["released_at"] <= timeline["close"] + 2 * ORDER_LIST_LAG_S + 10  # about 30-70 s, not never
        assert all(create["client_order_id"] != identity for create in account.creates)  # never sent again
    finally:
        desk.close()


def test_a_crash_between_the_journal_row_and_the_send_of_a_lock_is_released_after_the_close(tmp_path: Path) -> None:
    venue = kill_child(tmp_path, "lock_row")
    desk, account, clock = restart(tmp_path, venue)
    try:
        locks = [key for key, item in desk.intents.items() if item.lock]
        assert len(locks) == 1 and desk.book.intents[locks[0]].reservation_active
        timeline = run_past_close(desk, account, clock)
        finished(desk, locks[0], timeline)
    finally:
        desk.close()


def first_leg_filled(tmp_path: Path) -> tuple[Any, Any, Any]:
    """In-process: the first buy (take Up 5 @ 0.40) fills in full; the account holds +5 Up."""
    desk, account, clock = make_desk(tmp_path)
    asyncio.run(desk.step())
    fill_order(account, clock, 0, side="up", price=.4, size=5)
    account.executions[-1]["fee_cost"] = "0.0168"
    account.account_positions = [{"ticker": TICKER, "position_fp": "5.00"}]
    return desk, account, clock


def lose_the_balancing_create(desk: Any, account: Any, clock: Any) -> str:
    """The balancing bid's create fails in transport before reaching Kalshi (uncertain, never listed)."""
    account.create_error = KalshiClientError("create_order", "transport failure", uncertain=True, timed_out=True)
    for _ in range(4):
        clock.advance(.3)
        view(desk, clock, 80000, .55, .55)
        asyncio.run(desk.step())
    lost = [key for key, item in desk.intents.items() if item.uncertain and not item.order_id]
    assert len(lost) == 1 and len(account.creates) == 2 and len(account.orders) == 1
    account.create_error = None
    return lost[0]


def test_a_lost_balancing_create_in_the_running_desk_is_released_and_trading_resumes(tmp_path: Path) -> None:
    desk, account, clock = first_leg_filled(tmp_path)
    try:
        identity = lose_the_balancing_create(desk, account, clock)
        # Held in full while the market trades: a delayed copy of the request could still arrive.
        assert desk.book.intents[identity].reservation_active
        timeline = run_past_close(desk, account, clock, until_s=600)
        finished(desk, identity, timeline)
    finally:
        desk.close()


def test_the_release_also_works_when_kalshi_settles_after_the_proof(tmp_path: Path) -> None:
    """Kalshi settles a minute after the close: the order is released while the position is still listed (and
    matches), and the window settles once Kalshi's row arrives."""
    desk, account, clock = first_leg_filled(tmp_path)
    try:
        identity = lose_the_balancing_create(desk, account, clock)
        timeline = run_past_close(desk, account, clock, settle_after_s=60, until_s=600)
        finished(desk, identity, timeline)
        assert timeline["released_at"] < timeline["settled_at"]
    finally:
        desk.close()


def test_a_lost_order_beside_an_unknown_fill_in_its_window_is_never_released(tmp_path: Path) -> None:
    """A fill Kalshi lists in that window under an order id the bot does not know could be the lost order's own:
    the order keeps its whole reservation (and trading stays paused) however long the lists leave it out."""
    desk, account, clock = first_leg_filled(tmp_path)
    try:
        identity = lose_the_balancing_create(desk, account, clock)
        account.executions.append({"fill_id": "fill-unknown", "order_id": "order-unknown", "ticker": TICKER,
                                   "outcome_side": "no", "book_side": "ask", "count_fp": "2.00",
                                   "no_price_dollars": "0.45", "fee_cost": "0.0000", "ts": clock.now()})
        account.account_positions = [{"ticker": TICKER, "position_fp": "3.00"}]
        timeline = run_past_close(desk, account, clock, until_s=600)
        assert desk.book.intents[identity].reservation_active and timeline["released_at"] is None
        assert TICKER not in desk.book.settled and "unattributed_fill_beside_unresolved_order" in timeline["checks"]
    finally:
        desk.close()


def test_a_crash_within_a_second_of_a_send_guard_refusal_restores_it_as_refused(tmp_path: Path) -> None:
    """The guard refused the balancing bid (never sent) and the process died before the next full save: the
    journal entry was rewritten with the refusal, so the restart holds no phantom reservation."""
    venue = kill_child(tmp_path, "guard_reject_then_kill")
    refused = [key for key, (active, _r, order_id, status) in venue["memory"].items()
               if not active and status == "rejected"]
    assert len(refused) == 1, venue["memory"]
    desk, account, clock = restart(tmp_path, venue)
    try:
        restored = desk.book.intents[refused[0]]
        assert not restored.reservation_active and restored.status == "rejected"
        assert desk.intents[refused[0]].terminal
        timeline = run_past_close(desk, account, clock, until_s=120)
        assert desk.startup_done and TICKER in desk.book.settled, timeline
    finally:
        desk.close()


def test_a_definite_kalshi_refusal_is_journaled_as_refused(tmp_path: Path) -> None:
    """The same for a definite 4xx from Kalshi: what a restart reads holds the refusal at once."""
    from nightcrawler.speeddesk_live import durable_state

    desk, account, clock = first_leg_filled(tmp_path)
    try:
        account.create_error = KalshiClientError("create_order", "request rejected", status=400)
        for _ in range(4):
            clock.advance(.3)
            view(desk, clock, 80000, .55, .55)
            asyncio.run(desk.step())
            if len(account.creates) == 2:
                break
        refused = account.creates[1]["client_order_id"]
        assert desk.book.intents[refused].status == "rejected"
        saved = durable_state(desk.ledger)
        assert saved is not None and not saved["book"]["intents"][refused]["reservation_active"]
        assert saved["book"]["intents"][refused]["status"] == "rejected" and saved["intents"][refused]["terminal"]
    finally:
        desk.close()


def priced(desk: Any, clock: Any) -> None:
    """A Down ask cheap enough for a balancing bid, and Kalshi's outcome once the market is settled."""
    window = desk.book.windows[TICKER]

    def snapshot() -> LiveSnapshot:
        books = {(TICKER, side): Book(TICKER, side, (Level(.3, 2),), (Level(.9 if side == "up" else .62, 10),),
                                      clock.now(), "book", source="rest", requested_at=clock.now())
                 for side in ("up", "down")}
        return LiveSnapshot((window,), books, 80000, clock.now(), .001, frozenset({TICKER}),
                            outcomes={TICKER: True} if clock.now() > window.end + 5 else {})
    desk.snapshot = snapshot  # type: ignore[method-assign]


def test_lost_balancing_create_in_an_unpaired_window_is_released_after_kalshi_settles(tmp_path: Path) -> None:
    """The caps reviewer's version: steps every 10 s for ten minutes after Kalshi settled."""
    desk, account, clock = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        assert [(c["side"], c["kind"], c["size"]) for c in account.creates] == [("up", "take", 5)]
        fill_order(account, clock, 0, side="up", price=.4, size=5)
        account.account_positions = [{"ticker": TICKER, "position_fp": "5.00"}]
        account.create_error = KalshiClientError("create_order", "transport failure", uncertain=True, timed_out=True)
        steps(desk, clock, 3)
        priced(desk, clock)
        steps(desk, clock, 6)
        lost = [key for key, item in desk.book.intents.items() if item.reservation_active and not item.order_id]
        assert len(lost) == 1 and desk.intents[lost[0]].uncertain
        account.create_error = None
        clock.advance(desk.book.windows[TICKER].end + 5 - clock.now())
        account.account_positions = []
        account.resolutions = [{"ticker": TICKER, "market_result": "yes", "revenue": 500, "settled_time": clock.now()}]
        for _ in range(60):
            asyncio.run(desk.step())
            clock.advance(10)
        assert not desk.book.intents[lost[0]].reservation_active and TICKER in desk.book.settled
    finally:
        desk.close()


def test_restart_with_an_unsent_balancing_bid_finishes_startup_after_kalshi_settles(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path)
    asyncio.run(desk.step())
    fill_order(account, clock, 0, side="up", price=.4, size=5)
    account.account_positions = [{"ticker": TICKER, "position_fp": "5.00"}]
    account.create_error = KalshiClientError("create_order", "transport failure", uncertain=True, timed_out=True)
    window = desk.book.windows[TICKER]
    priced(desk, clock)
    steps(desk, clock, 8)
    lost = [key for key, item in desk.book.intents.items() if item.reservation_active and not item.order_id]
    assert len(lost) == 1
    account.create_error = None
    desk = reopen(tmp_path, desk, account, clock)
    desk.on_windows([window])
    try:
        clock.advance(window.end + 5 - clock.now())
        account.account_positions = []
        account.resolutions = [{"ticker": TICKER, "market_result": "yes", "revenue": 500, "settled_time": clock.now()}]
        for _ in range(60):
            asyncio.run(desk.step())
            clock.advance(10)
        assert desk.startup_done, desk.reason
        assert not desk.book.intents[lost[0]].reservation_active and TICKER in desk.book.settled
    finally:
        desk.close()


def test_the_first_full_save_after_a_restart_empties_the_journal_on_disk(tmp_path: Path) -> None:
    """Review minor: a restart replayed the journal into memory and saved it in full, but the journal on disk kept
    the replayed order (harmless only because a replay skips ids the state already holds)."""
    from nightcrawler.speeddesk_live import JOURNAL_KEY, STATE_KEY

    venue = kill_child(tmp_path, "second_row")
    identity = unsent(venue)
    desk, _account, _clock = restart(tmp_path, venue)
    try:
        assert identity in desk.ledger.get_kv(STATE_KEY)["intents"]  # the startup save holds it in full
        assert desk.ledger.get_kv(JOURNAL_KEY)["intents"] == {}
    finally:
        desk.close()


def test_a_lost_order_beside_the_owners_listed_fill_is_released_after_the_close(tmp_path: Path) -> None:
    """The owner traded the same window by hand: Kalshi lists the owner's order (no bot client id) and its fill.
    That fill cannot be the lost order's, so the window is the owner's and the order is still proven away (it used
    to count as unattributed and hold the order, and real trading, for good)."""
    desk, account, clock = first_leg_filled(tmp_path)
    try:
        identity = lose_the_balancing_create(desk, account, clock)
        account.orders.append({"order_id": "owner-7", "client_order_id": "", "ticker": TICKER, "status": "executed",
                               "fill_count_fp": "2.00", "remaining_count_fp": "0.00", "initial_count_fp": "2.00",
                               "outcome_side": "no", "book_side": "ask", "yes_price_dollars": "0.55",
                               "no_price_dollars": "0.45"})
        account.executions.append({"fill_id": "fill-owner", "order_id": "owner-7", "ticker": TICKER,
                                   "outcome_side": "no", "book_side": "ask", "count_fp": "2.00",
                                   "no_price_dollars": "0.45", "fee_cost": "0.0000", "ts": clock.now()})
        account.account_positions = [{"ticker": TICKER, "position_fp": "3.00"}]
        timeline = run_past_close(desk, account, clock, until_s=600)
        assert TICKER in desk.foreign_windows
        intent = desk.book.intents[identity]
        assert not intent.reservation_active and intent.uncertainty == "never_reached_venue", timeline
        assert timeline["released_at"] >= timeline["close"] + ORDER_LIST_LAG_S
        result = desk.book.settled.get(TICKER)
        assert result is not None and result.up_shares == 5 and result.down_shares == 0  # its own contracts only
        assert not desk.book.integrity_error and desk.fatal_reason is None
    finally:
        desk.close()


def test_a_landed_order_kalshi_lists_without_the_bot_client_id_keeps_its_reservation(tmp_path: Path) -> None:
    """Rebreak minor (2026-10-14), a change from the live base 61ca112: a listed order without the bot's client-id
    prefix was taken as proof that its fill was the owner's. The balancing Down bid's create lands but its reply is
    lost; Kalshi lists that order without the bot's client id and fills it in full before the close (the account
    nets Up 5 and Down 5 to flat, so Kalshi writes no settlement row). Its fill was counted as the owner's, the
    window marked as the owner's (no position check, no payout audit) and the order released: the bot's own Down 5
    vanished from its books. A listed order with that unsent order's exact terms could be its own, so its fill
    holds the order in full, as on the base."""
    desk, account, clock = first_leg_filled(tmp_path)
    try:
        create = account.create_order

        def landed_reply_lost(**kwargs: Any) -> dict[str, Any]:
            create(**kwargs)
            account.orders[-1]["client_order_id"] = ""  # listed without the bot's client id
            raise KalshiClientError("create_order", "transport failure", uncertain=True, timed_out=True)
        account.create_order = landed_reply_lost
        for _ in range(4):
            clock.advance(.3)
            view(desk, clock, 80000, .55, .55)
            asyncio.run(desk.step())
            if len(account.creates) == 2:
                break
        account.create_order = create
        sent = account.creates[1]
        identity = sent["client_order_id"]
        assert sent["side"] == "down" and desk.intents[identity].uncertain and not desk.intents[identity].order_id
        fill_order(account, clock, 1, side="down", price=sent["price"], size=sent["size"])
        account.account_positions = []
        timeline = run_past_close(desk, account, clock, until_s=600, settlement_row=False)
        assert desk.book.intents[identity].reservation_active and timeline["released_at"] is None, timeline
        assert "unattributed_fill_beside_unresolved_order" in timeline["checks"]
        assert TICKER not in desk.foreign_windows and TICKER not in desk.book.settled
    finally:
        desk.close()
