"""Read-only, bounded projections of the two saved real-money books for the town.

These are recorded bot holdings, not freshly queried venue positions. In particular,
Kalshi does not persist its successful account reconciliation timestamp or position
snapshot. A recent checkpoint cannot stand in for either. No client, key or trading
operation is used here, and the full books are checked before display truncation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nightcrawler.polydesk import _owner_migration
from nightcrawler.polymarket_day import pacific_booked_day
from nightcrawler.speeddesk_live_model import LiveRiskBook

MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_ROWS = 50
FRESH_SECONDS = 60.0
PM_FRESH_SECONDS = 600.0
Text = Callable[[Any], str]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def _timestamp(value: Any, now: float) -> float | None:
    result = _number(value)
    return result if result is not None and 0 < result <= now else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _identity(venue: str, kind: str, *parts: Any) -> str:
    # The town needs stable deduplication, not private exchange/account identifiers.
    encoded = json.dumps([venue, kind, *parts], separators=(",", ":"), default=str)
    return f"{venue}:{kind}:{hashlib.sha256(encoded.encode()).hexdigest()[:24]}"


def _base(venue: str, now: float) -> dict[str, Any]:
    return {"venue": venue, "as_of": None, "stale": True, "status": "unavailable",
            "source_note": "Saved source unavailable; this does not establish an empty account.",
            "positions_basis": "Unknown", "venue_positions_at": None, "cash_at": None,
            "cash_usd": None, "cash_scope": "account", "reported_mode": None, "total_pnl_usd": None,
            "positions": [], "orders": [], "events": [], "open_cost_usd": None,
            "reserved_usd": None, "at_risk_usd": None,
            "today_pacific": pacific_booked_day(None, now), "issues": [],
            "truncated": {"positions": False, "orders": False, "events": False},
            "counts": {"positions": None, "orders": None, "events": None}}


def _event(out: dict[str, Any], text: Text, kind: str, identity: Any, at: Any, now: float,
           *, message: str, market: Any, side: str | None = None, quantity: Any = None,
           price: Any = None, fee: Any = None, pnl: Any = None, source: str,
           time_source: str, observed_at: Any = None, eligible: bool = True) -> dict[str, Any]:
    stamp = _timestamp(at, now)
    source_at = out["as_of"]
    return {"id": _identity(out["venue"], kind, identity), "venue": out["venue"], "type": kind,
            "ts": stamp, "observed_at": _timestamp(observed_at, now), "time_source": text(time_source),
            "real": True, "scope": "bot", "source": text(source), "source_at": source_at,
            "qualified": bool(eligible and out["status"] == "ok" and not out["stale"]
                              and stamp is not None and source_at is not None and stamp <= source_at),
            "text": text(message), "market": text(market), "side": side,
            "quantity": _number(quantity), "price": _number(price), "fee_usd": _number(fee),
            "fee_source": "actual" if out["venue"] == "kalshi" else "estimated",
            "pnl_usd": _number(pnl) if kind == "settlement" else None}


def _finish(out: dict[str, Any], text: Text) -> dict[str, Any]:
    for name in ("positions", "orders", "events"):
        unique = {row["id"]: row for row in out[name]}
        rows = list(unique.values())
        if name == "events":
            rows.sort(key=lambda row: (row.get("ts") or 0, row["id"]), reverse=True)
            if out["status"] != "ok" or out["stale"]:
                for row in rows:
                    row["qualified"] = False
        elif name == "orders":
            rows.sort(key=lambda row: (bool(row["reservation_active"]), row.get("created_at") or 0,
                                       row["id"]), reverse=True)
        else:
            rows.sort(key=lambda row: (row.get("opened_at") or 0, row["id"]), reverse=True)
        out["counts"][name] = len(rows)
        out["truncated"][name] = len(rows) > MAX_ROWS
        out[name] = rows[:MAX_ROWS]
    out["issues"] = list(dict.fromkeys(text(value) for value in out["issues"]))[:12]
    return out


def _kalshi_book(raw: Any, now: float) -> LiveRiskBook:
    if not isinstance(raw, dict):
        raise TypeError("missing_book")
    # Reject malformed scalar types the execution model tolerates through Python's
    # bool-as-int arithmetic. Restore then checks fills, gross holdings and P&L.
    numeric_fields = {
        "intents": ("price", "size", "created_at", "unit_reserve", "filled_size", "reported_filled_size"),
        "fills": ("price", "size", "fee_usd", "at"),
        "settled": ("at", "up_shares", "down_shares", "cost_usd", "fee_usd", "paired_credit_usd",
                    "net_payout_usd", "payout_usd", "locked_usd", "direction_usd", "pnl_usd"),
    }
    for group, fields in numeric_fields.items():
        rows = raw.get(group)
        if not isinstance(rows, dict):
            raise TypeError("invalid_rows")
        for row in rows.values():
            if not isinstance(row, dict) or any(_number(row.get(key)) is None for key in fields):
                raise ValueError("invalid_number")
            for key in ("at", "created_at", "last_snapshot_at"):
                if row.get(key) is not None and _timestamp(row[key], now) is None:
                    raise ValueError("invalid_time")
    # The execution restore retains references to a few dictionaries. Keep even
    # those isolated: reading the town must never mutate a caller's real book.
    book = LiveRiskBook.from_state(copy.deepcopy(raw))
    for inventory in book.inventory.values():
        for holding in (inventory.up, inventory.down):
            if any(_number(value) is None for value in (holding.shares, holding.cost, holding.fees)):
                raise ValueError("invalid_inventory")
    if any(_number(value) is None for value in (book.realized_pnl, *book.day_pnl.values())):
        raise ValueError("invalid_profit")
    return book


def _kalshi_day(book: LiveRiskBook, as_of: float | None, now: float) -> dict[str, Any]:
    closed: list[dict[str, Any]] = []
    days: dict[str, dict[str, Any]] = {}
    for result in book.settled.values():
        closed.append({"live": True, "settled_at": result.at, "pnl_usd": result.pnl_usd})
        day = datetime.fromtimestamp(result.at, UTC).date().isoformat()
        item = days.setdefault(day, {"settled": 0, "pnl_usd": book.day_pnl.get(day, 0.0)})
        item["settled"] += 1
    # This reuses the DST/day-coverage guard, after the *full* real book was checked.
    return pacific_booked_day({"last_ok": as_of, "last_poll": as_of, "closed": closed,
                               "live_days": days}, now)


def kalshi_connection(raw_state: Any, now: float, text: Text) -> dict[str, Any]:
    """Project actual persisted Kalshi fills and settlements; never the practice twin."""
    out = _base("kalshi", now)
    if not isinstance(raw_state, Mapping) or raw_state.get("version") != 1:
        return out
    as_of = _timestamp(raw_state.get("updated_at"), now)
    panel = _mapping(raw_state.get("panel"))
    out.update(as_of=as_of, stale=as_of is None or now - as_of > FRESH_SECONDS,
               cash_at=_timestamp(panel.get("cash_at"), now), cash_usd=_number(panel.get("cash_usd")),
               reported_mode=panel.get("mode") if panel.get("mode") in ("paper", "live") else None,
               source_note="Saved Kalshi real-fill book. Checkpoint age is not a successful account reconciliation.",
               positions_basis="Gross bot fills awaiting a recorded settlement, including both sides; not current account bets.")
    out["issues"].append("Venue positions and successful account reconciliation time are not saved by this source.")
    try:
        book = _kalshi_book(raw_state.get("book"), now)
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, RecursionError):
        out["status"] = "incomplete"
        out["issues"].append("The saved real book does not reconcile; individual money rows and profit are unavailable.")
        return _finish(out, text)
    out["status"] = "ok"
    out["total_pnl_usd"] = book.realized_pnl
    out["today_pacific"] = _kalshi_day(book, as_of, now)
    if book.integrity_error or raw_state.get("fatal_reason"):
        out["status"] = "incomplete"
        out["issues"].append("The desk reports an accounting or reconciliation problem; recorded figures need review.")
        out["today_pacific"].update(status="incomplete", pnl_usd=None, settled=None,
                                     reason="desk_reconciliation_problem")
    out.update(open_cost_usd=book.open_cost_usd, reserved_usd=book.reserved_usd, at_risk_usd=book.at_risk_usd)
    foreign_rows = raw_state.get("foreign_windows")
    foreign = {row for row in foreign_rows if isinstance(row, str)} if isinstance(foreign_rows, list) else set()
    outcomes = _mapping(raw_state.get("final_outcomes"))
    settlement_evidence = {}
    latest = raw_state.get("latest_events")
    if isinstance(latest, list):
        settlement_evidence = {row.get("window"): row for row in latest if isinstance(row, Mapping)
                               and row.get("event") == "speeddesk_live_settlement"
                               and isinstance(row.get("window"), str)}
    for market, inventory in book.inventory.items():
        if market in book.settled:
            continue
        window = book.windows[market]
        ended = window.end <= now
        outcome = outcomes.get(market)
        finalized = ended and isinstance(outcome, bool)
        mixed = market in foreign
        status = "finalized_unreconciled" if finalized else "ended_unreconciled" if ended else "recorded_unsettled"
        note = ("Window finalized; these old bot fills still await a reconciled settlement record."
                if finalized else "Window ended; these bot fills still await settlement reconciliation."
                if ended else "Recorded bot fills; current account holdings are not verified by this report.")
        if mixed:
            note += " Other account trades occurred in this window; gross bot fills are not the account position."
        if ended and inventory.up.shares + inventory.down.shares > 0:
            out["issues"].append("Ended windows remain in the recorded fill book until settlement reconciles; they are not proof of current account exposure.")
        if mixed and inventory.up.shares + inventory.down.shares > 0:
            out["issues"].append("Some recorded bot fills share a window with other account trades; this source cannot establish the remaining account position.")
        for side, holding in (("up", inventory.up), ("down", inventory.down)):
            if holding.shares <= 0:
                continue
            fills = [row for row in book.fills.values() if row.window == market and row.side == side]
            out["positions"].append({"id": _identity("kalshi", "position", market, side),
                                     "market": text(market), "title": text(market),
                                     "side": "YES" if side == "up" else "NO", "scope": "bot",
                                     "quantity": holding.shares, "price": holding.cost / holding.shares,
                                     "cost_usd": holding.cost, "fee_usd": holding.fees, "fee_source": "actual",
                                     "fee_basis": "actual",
                                     "opened_at": min((row.at for row in fills), default=None),
                                     "end_at": window.end, "status": status, "status_note": text(note),
                                     "final_outcome": ("YES" if outcome else "NO") if finalized else None,
                                     "mixed_account_activity": mixed, "current_position_verified": False,
                                     "source": "actual Kalshi fills; gross recorded holdings"})
    for intent in book.intents.values():
        side = "YES" if intent.side == "up" else "NO"
        order = {"id": _identity("kalshi", "order", intent.client_order_id), "market": text(intent.window),
                 "title": text(intent.window), "side": side, "scope": "bot", "status": text(intent.status),
                 "quantity": intent.size, "filled_quantity": intent.filled_size,
                 "remaining_quantity": intent.remaining, "reserved_usd": intent.reserved,
                 "created_at": intent.created_at, "as_of": intent.last_snapshot_at,
                 "lock": intent.lock,
                 "cancel_requested": intent.cancel_requested, "reservation_active": intent.reservation_active}
        if intent.reservation_active:
            out["orders"].append(order)
        out["events"].append(_event(out, text, "order", intent.client_order_id, intent.created_at, now,
                                    message=f"Kalshi {side} buy intent recorded; {intent.size:g} at ${intent.price:.2f}.",
                                    market=intent.window, side=side, quantity=intent.size, price=intent.price,
                                    source="saved real-order intent", time_source="bot intent creation time"))
        if intent.status == "canceled" and not intent.reservation_active:
            # last_snapshot_at advances every reconcile, even for old terminal
            # orders. It proves the state was observed, not when it changed.
            out["issues"].append("Confirmed order cancellations have no retained event time; repeated account reads are not new activity.")
    for fill in book.fills.values():
        side = "YES" if fill.side == "up" else "NO"
        out["events"].append(_event(out, text, "fill", fill.fill_id, fill.at, now,
                                    message=f"Kalshi filled {fill.size:g} {side} at ${fill.price:.2f}; actual fee ${fill.fee_usd:.4f}.",
                                    market=fill.window, side=side, quantity=fill.size, price=fill.price, fee=fill.fee_usd,
                                    source="actual Kalshi fill", time_source="venue fill time"))
    for result in book.settled.values():
        evidence = settlement_evidence.get(result.window, {})
        out["events"].append(_event(out, text, "settlement", result.settlement_id, result.at, now,
                                    message=f"Kalshi window booked {result.pnl_usd:+.4f} USD after actual fees.",
                                    market=result.window, fee=result.fee_usd, pnl=result.pnl_usd,
                                    source="validated real-fill settlement book",
                                    time_source=evidence.get("time_source") or "recorded settlement time; exact receipt timing not retained",
                                    observed_at=evidence.get("observed_at")))
    _kalshi_recent_events(out, latest, book, now, text)
    return _finish(out, text)


def _kalshi_recent_events(out: dict[str, Any], latest: Any, book: LiveRiskBook, now: float, text: Text) -> None:
    if not isinstance(latest, list):
        return
    for row in latest[-50:]:
        if not isinstance(row, Mapping):
            continue
        event = row.get("event")
        if event not in ("speeddesk_live_cancel", "speeddesk_live_reject"):
            continue
        identity = row.get("client_order_id")
        if event == "speeddesk_live_reject" and identity is None:
            out["events"].append(_event(out, text, "reject", [row.get("at"), row.get("reason")], row.get("at"), now,
                                        message="Kalshi account check failed; new orders paused.", market="Kalshi desk",
                                        source="saved real desk account-check event", time_source="bot error observation time",
                                        eligible=False))
            continue
        if not isinstance(identity, str) or identity not in book.intents:
            continue
        intent = book.intents[identity]
        kind = "cancel" if event == "speeddesk_live_cancel" else "reject"
        # Cancellation requests are not terminal evidence and cannot release a reserve.
        message = ("Kalshi cancellation requested; this receipt does not confirm reserved cash was released."
                   if kind == "cancel" else "Kalshi buy rejected or blocked; check the desk status.")
        out["events"].append(_event(out, text, kind, [identity, row.get("at"), "request"], row.get("at"), now,
                                    message=message, market=intent.window, source="saved real desk event",
                                    time_source="bot cancellation request time" if kind == "cancel" else "bot event time",
                                    eligible=kind != "cancel"))


def _pm_scope(row: Mapping[str, Any]) -> str:
    if "owner" in row and not isinstance(row["owner"], bool):
        return "unknown"
    if row.get("owner") is True or row.get("rule") == "owner":
        return "owner"
    return "bot" if isinstance(row.get("rule"), str) and row.get("rule") else "unknown"


def _pm_position(row: Mapping[str, Any], now: float, text: Text) -> dict[str, Any] | None:
    quantity, price, cost, fee = (_number(row.get(name)) for name in ("shares", "p_in", "cost_usd", "fee_usd"))
    if (quantity is None or quantity <= 0 or price is None or not 0 <= price <= 1
            or cost is None or cost < 0 or fee is None or fee < 0 or not isinstance(row.get("slug"), str)):
        return None
    side = "YES" if row.get("side") == "long" else "NO" if row.get("side") == "short" else None
    if side is None:
        return None
    return {"id": _identity("polymarket_us", "position", row.get("order_id"), row["slug"], row.get("t_in")),
            "market": text(row["slug"]), "title": text(row.get("question") or row["slug"]),
            "side": side, "scope": _pm_scope(row), "quantity": quantity, "price": price,
            "cost_usd": cost, "fee_usd": fee, "fee_source": "estimated",
            "fee_basis": "estimated",
            "opened_at": _timestamp(row.get("t_in"), now), "source": "bot recorded position; fees estimated"}


def _pm_fill(out: dict[str, Any], row: Mapping[str, Any], position: dict[str, Any], now: float, text: Text) -> None:
    if position["scope"] != "bot":
        return
    adopted = bool(row.get("adopted")) or row.get("rule") == "venue"
    event = _event(out, text, "fill", position["id"], row.get("t_in"), now,
                                message=f"Polymarket US recorded {position['quantity']:g} {position['side']} at ${position['price']:.2f}.",
                                market=row["slug"], side=position["side"], quantity=position["quantity"],
                                price=position["price"], fee=position["fee_usd"], source="recorded real bot position; fee estimated",
                                time_source=("original order/adoption time; exact fill confirmation time not retained" if adopted
                                             else "bot booking time; exact venue fill time not retained"), eligible=not adopted)
    if row.get("sold_in_app") is True or any(item["id"] == event["id"] for item in out["events"]):
        # Partial cash-outs split one holding into several mutable rows. Adding
        # their quantities would assume no earlier fragment has been truncated.
        event.update(quantity=None, fee_usd=None, qualified=False,
                     text="Polymarket US position has cash-out fragments; original fill quantity is not verified.",
                     source="recorded holding fragments, not a complete execution receipt")
    out["events"].append(event)


def polymarket_connection(raw_state: Any, now: float, text: Text) -> dict[str, Any]:
    """Project bot/owner records separately; paper rows never become real activity."""
    out = _base("polymarket_us", now)
    if not isinstance(raw_state, dict) or raw_state.get("version") != 1:
        return out
    try:
        state = copy.deepcopy(raw_state)
        # Same owner classification as the existing reader, on a private copy only.
        _owner_migration(state)
    except (TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        out["status"] = "incomplete"
        out["issues"].append("Saved owner/bot classification could not be verified.")
        return _finish(out, text)
    as_of = _timestamp(state.get("last_ok"), now)
    balance, exchange = _mapping(state.get("balance")), _mapping(state.get("exchange"))
    out.update(as_of=as_of, stale=as_of is None or now - as_of > PM_FRESH_SECONDS,
               cash_at=_timestamp(balance.get("at"), now), cash_usd=_number(balance.get("cash")),
               reported_mode=state.get("mode") if state.get("mode") in ("paper", "live") else None,
               venue_positions_at=_timestamp(exchange.get("at"), now), status="ok",
               source_note="Recorded Polymarket US bot book; cash and venue totals include the owner's bets.",
               positions_basis="Tracked bot/owner rows, not a current itemized venue snapshot.")
    out["today_pacific"] = pacific_booked_day(state, now)
    out["issues"].append("Polymarket fees are estimated. Recorded cash-outs/corrections keep their original booking time.")
    out["issues"].append("Saved cash-out accounting has known edge cases; results are not fully verified against venue activity.")
    venue_at = out["venue_positions_at"]
    if venue_at is None or now - venue_at > PM_FRESH_SECONDS:
        out["issues"].append("The aggregate venue position check is missing or old; tracked rows may differ from the account.")
    if out["today_pacific"]["status"] == "incomplete":
        out["status"] = "incomplete"
        out["issues"].append("Retained real results do not fully reconcile to the day book; today's profit is unavailable.")
    positions, closed, pending = state.get("positions"), state.get("closed"), state.get("pending_orders")
    if not isinstance(positions, dict) or not isinstance(closed, list) or not isinstance(pending, dict):
        out["status"] = "incomplete"
        out["issues"].append("Saved real holdings or orders are incomplete.")
        return _finish(out, text)
    for row in positions.values():
        if not isinstance(row, Mapping):
            out["status"] = "incomplete"
            continue
        if row.get("live") is not True:
            continue
        position = _pm_position(row, now, text)
        if position is None:
            out["status"] = "incomplete"
            out["issues"].append("A saved real holding has incomplete amounts or ownership evidence.")
            continue
        out["positions"].append(position)
        if position["scope"] == "unknown":
            out["issues"].append("Some tracked positions have unknown ownership; they cannot animate bot activity.")
        _pm_fill(out, row, position, now, text)
    for row in closed:
        if not isinstance(row, Mapping) or row.get("live") is not True or _pm_scope(row) != "bot":
            continue
        position = _pm_position(row, now, text)
        if position is not None:
            _pm_fill(out, row, position, now, text)
        if row.get("unresolved") is True:
            continue
        pnl, at = _number(row.get("pnl_usd")), _timestamp(row.get("settled_at"), now)
        if pnl is None or at is None:
            out["status"] = "incomplete"
            continue
        identity = [row.get("order_id"), row.get("slug"), row.get("t_in"), at]
        cashout = row.get("sold_in_app") is True
        message = (f"Polymarket US bot cash-out booked {pnl:+.4f} USD; venue-reported realized figure."
                   if cashout else f"Polymarket US bot result booked {pnl:+.4f} USD after estimated fees.")
        out["events"].append(_event(out, text, "settlement", identity, at, now,
                                    message=message,
                                    market=row.get("slug") or "Unknown market", pnl=pnl, fee=row.get("fee_usd"),
                                    source=("venue-reported result booked by bot; fee inclusion not established" if cashout
                                            else "recorded real bot result; estimated fees already included"),
                                    time_source="original bot result booking time; later corrections may retain this time"))
    for market, row in pending.items():
        if not isinstance(row, Mapping):
            out["status"] = "incomplete"
            continue
        quantity, price = _number(row.get("contracts")), _number(row.get("limit"))
        if quantity is None or quantity <= 0 or price is None or not 0 < price <= 1:
            out["status"] = "incomplete"
            continue
        fee_coef = _number(row.get("fee_coef"))
        reserve = (_number(quantity * (price + fee_coef * price * (1 - price)))
                   if fee_coef is not None and 0 <= fee_coef <= 1 else None)
        if reserve is None:
            out["status"] = "incomplete"
            out["issues"].append("A pending order's reserved cost cannot be verified.")
        at = _timestamp(row.get("t_in"), now)
        identity = [row.get("order_id"), market, row.get("t_in")]
        out["orders"].append({"id": _identity("polymarket_us", "order", *identity), "market": text(market),
                              "title": text(row.get("question") or market), "side": None, "scope": "bot",
                              "status": "unconfirmed IOC", "quantity": quantity, "filled_quantity": None,
                              "remaining_quantity": None, "reserved_usd": reserve, "created_at": at,
                              "as_of": None, "cancel_requested": False, "reservation_active": True})
        out["events"].append(_event(out, text, "order", identity, at, now,
                                    message=f"Polymarket US buy submitted for {quantity:g} contracts; fill unconfirmed.",
                                    market=market, quantity=quantity, price=price, source="saved pending real bot order",
                                    time_source="bot order attempt time"))
    # No account exposure is invented from a subset of tracked positions. The
    # existing venue aggregate remains the account-wide source elsewhere on page.
    return _finish(out, text)


def _read_saved(path: Path) -> tuple[Any, str | None]:
    try:
        if path.stat().st_size > MAX_SOURCE_BYTES:
            return None, "Saved source exceeds the safe display read limit; values are unavailable."
        with path.open("rb") as handle:
            blob = handle.read(MAX_SOURCE_BYTES + 1)
        if len(blob) > MAX_SOURCE_BYTES:
            return None, "Saved source exceeds the safe display read limit; values are unavailable."
        return json.loads(blob), None
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None, "Saved source could not be read; values are unavailable."


def saved_kalshi_state(data_dir: Path) -> tuple[Any, str | None]:
    """Bounded read of the real display mirror; no trading client or ledger access."""
    return _read_saved(data_dir / "speeddesk/kalshi_live/state.json")


def saved_kalshi_panel(data_dir: Path) -> Mapping[str, Any] | None:
    """Read the real companion independently of the practice report, with a size cap.

    The mirror's panel already carries its own cash/report times. Reading it does
    not validate its fill book or establish Pacific-day profit coverage.
    """
    raw, _ = saved_kalshi_state(data_dir)
    if not isinstance(raw, Mapping) or raw.get("version") != 1:
        return None
    panel = raw.get("panel")
    return panel if isinstance(panel, Mapping) else None


def load_connections(data_dir: Path, now: float, text: Text,
                     *, read_clock: Callable[[], float] | None = None) -> dict[str, Any]:
    """Read saved snapshots, optionally checking each against its observation time.

    A checkpoint may be written while the page is assembled. Its timestamp must
    precede the completed read, not necessarily the start of the page request.
    The caller supplies elapsed request time; source timestamps remain unchanged.
    """
    result: dict[str, Any] = {"version": 1}
    for venue, relative, builder in (("polymarket_us", "polydesk/state.json", polymarket_connection),
                                      ("kalshi", "speeddesk/kalshi_live/state.json", kalshi_connection)):
        raw, problem = _read_saved(data_dir / relative)
        observed_at = _number(read_clock()) if read_clock is not None else now
        projection_now = observed_at if observed_at is not None and observed_at >= now else now
        view = builder(raw, projection_now, text)
        if problem:
            view["issues"].append(text(problem))
        result[venue] = view
    return result
