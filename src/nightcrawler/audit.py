"""Reconciliation and P&L reporting (owner: O6).

``Auditor.reconcile()`` recomputes what the wallet SHOULD hold from the ledger's
fills and compares it with what the broker says it holds:

* expected SOL = start lamports (kv ``paper.start_lamports`` /
  ``live.start_lamports``) + sum(``fill.sol_delta_lamports()``) - live SOL sent
  to the owner by ``WITHDRAW_TO`` (``withdraw`` receipts: amount + fee);
* expected tokens[mint] = sum(``fill.token_delta()``) per mint;
* drift = broker - expected. Paper: any drift is a bug (``ok=False``).
  Live: token drift beyond 1 base unit -> ``ok=False``; SOL drift is reported
  (deposits/withdrawals and unmodelled fees cause it) but only flags when
  negative beyond ``SOL_DRIFT_TOLERANCE_LAMPORTS``.

Only fills of the broker's mode count, and in paper mode only fills recorded
after the latest ``paper_reset`` note receipt (a reset starts a new virtual
wallet; chain order, not wall-clock time, decides) - for the balances AND for
the trades, daily summary and totals (a live report never shows paper P&L, and
``TradePnL.mode`` says which wallet a trade was in). Live tokens the bot never
traded (airdrops, spam) are listed in ``issues`` but do not fail the audit. A
live wallet with fills but no recorded starting balance fails it (SOL could
leak unnoticed).

Fill ROWS (what the P&L is computed from) are compared with the payload of their
hash-chained ``fill`` receipt; a row edited behind the chain's back fails the
audit even though the chain itself still verifies.

It also checks the books themselves: every fill must belong to a position
(``Fill.position_id`` or the position's ``entry_fill_ids``/``exit_fill_ids``;
an orphan fill means tokens nobody manages), and every position - open AND
closed, any mode - must equal the sums of its own fills (the ``Position``
contract): ``token_amount`` = net tokens, ``initial_token_amount`` = tokens
bought, ``cost_lamports`` = SOL of buys, ``proceeds_lamports`` = SOL of sells,
``fees_lamports`` and ``rent_lamports`` = their sums (``position_drift``). Both
flag ``ok=False``, as does a broken receipt chain. One exception: a closed paper
position whose fills all precede the latest ``paper_reset`` and whose only drift
is tokens left in its fills was abandoned by that reset (the virtual wallet was
wiped); it is listed in ``position_drift`` and ``issues`` without failing.

It also builds per-trade P&L (realized, fees, impact) and a daily summary.
All amounts lamports unless named ``*_usd``; ``*_pct`` are percent.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from nightcrawler.clock import RealClock, iso_utc, utc_day
from nightcrawler.models import LAMPORTS_PER_SOL, Fill, Position

__all__ = [
    "POSITION_SUMS",
    "SOL_DRIFT_TOLERANCE_LAMPORTS",
    "AuditReport",
    "Auditor",
    "DailySummary",
    "TradePnL",
    "daily_summaries",
    "trade_pnl",
]

SOL_DRIFT_TOLERANCE_LAMPORTS = 100_000  # 0.0001 SOL
#: Live token balances may differ from the books by rounding of at most this many base units.
TOKEN_DRIFT_TOLERANCE = 1
#: ``Position`` field -> its value recomputed from the position's own fills (the documented contract).
POSITION_SUMS: dict[str, Callable[[list[Fill]], int]] = {
    "token_amount": lambda fills: sum(f.token_delta() for f in fills),
    "initial_token_amount": lambda fills: sum(f.token_amount for f in fills if f.side == "buy"),
    "cost_lamports": lambda fills: sum(f.sol_lamports for f in fills if f.side == "buy"),
    "proceeds_lamports": lambda fills: sum(f.sol_lamports for f in fills if f.side == "sell"),
    "fees_lamports": lambda fills: sum(f.fees_lamports for f in fills),
    "rent_lamports": lambda fills: sum(f.rent_lamports for f in fills),
}


@dataclass(slots=True)
class TradePnL:
    """Realized result of one position (open positions: realized part only).

    ``realized_lamports`` = proceeds - cost basis of the tokens sold - ALL
    network fees paid so far - rent still locked (closed positions only: the sell
    leaves the emptied token account open, so the deposit is not refunded). The cost basis is the full
    cost once closed, else ``cost * sold / bought``. ``realized_pct`` is percent
    of that cost basis (None while nothing was sold). ``fill_ids`` lists the
    fills used, in time order.
    """

    position_id: str
    mint: str
    symbol: str
    opened_at: float
    closed_at: float | None
    status: str
    cost_lamports: int
    proceeds_lamports: int
    fees_lamports: int
    rent_lamports: int
    realized_lamports: int
    realized_pct: float | None  # percent of cost
    avg_price_impact_pct: float | None  # mean over the position's fills
    exit_reason: str | None
    fills: int
    fill_ids: list[str] = field(default_factory=list)
    mode: str = ""  # paper | live: the wallet this trade was in


@dataclass(slots=True)
class DailySummary:
    """Per UTC day (by close time for realized P&L)."""

    day: str
    trades_closed: int
    wins: int
    losses: int
    realized_lamports: int
    fees_lamports: int
    realized_usd: float | None  # at each fill's sol_usd


@dataclass(slots=True)
class AuditReport:
    ok: bool
    mode: str
    checked_at: float
    expected_sol_lamports: int | None
    broker_sol_lamports: int | None
    sol_drift_lamports: int | None
    token_drift: dict[str, dict[str, int]] = field(default_factory=dict)  # {mint: {expected, actual, drift}}
    issues: list[str] = field(default_factory=list)
    trades: list[TradePnL] = field(default_factory=list)
    daily: list[DailySummary] = field(default_factory=list)
    totals: dict[str, Any] = field(default_factory=dict)  # realized_lamports, fees_lamports, trades, win_rate_pct
    chain_ok: bool | None = None
    chain_first_bad_seq: int | None = None
    #: ``{position_id: {field: {books, fills, drift}}}`` (drift = books - fills), see :data:`POSITION_SUMS`
    position_drift: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)


# --------------------------------------------------------------------------- pure P&L


def _belongs_to(position: Position, fill: Fill) -> bool:
    return fill.position_id == position.id or fill.id in position.entry_fill_ids or fill.id in position.exit_fill_ids


def trade_pnl(position: Position, fills: list[Fill]) -> TradePnL:
    """PURE: P&L of one position from its fills (fills not belonging to it are ignored)."""
    own = sorted((f for f in fills if _belongs_to(position, f)), key=lambda f: f.ts)
    buys = [f for f in own if f.side == "buy"]
    sells = [f for f in own if f.side == "sell"]
    cost = sum(f.sol_lamports for f in buys)
    proceeds = sum(f.sol_lamports for f in sells)
    fees = sum(f.fees_lamports for f in own)
    rent = sum(f.rent_lamports for f in own)
    bought = sum(f.token_amount for f in buys)
    sold = sum(f.token_amount for f in sells)
    closed = position.status == "closed"
    basis = cost if closed else (cost * min(sold, bought) // bought if bought else 0)
    realized = proceeds - basis - fees - (rent if closed else 0)
    symbol = position.symbol or next((f.symbol for f in own if f.symbol), "")
    return TradePnL(
        position_id=position.id, mint=position.mint, symbol=symbol, opened_at=position.opened_at,
        closed_at=position.closed_at, status=position.status, cost_lamports=cost, proceeds_lamports=proceeds,
        fees_lamports=fees, rent_lamports=rent, realized_lamports=realized,
        realized_pct=realized / basis * 100.0 if basis else None,
        avg_price_impact_pct=sum(f.price_impact_pct for f in own) / len(own) if own else None,
        exit_reason=position.exit_reason, fills=len(own), fill_ids=[f.id for f in own],
        mode=position.mode or next((f.mode for f in own), ""))


def _fills_by_position(positions: list[Position], fills: list[Fill]) -> dict[str, list[Fill]]:
    """``{position_id: fills}`` linked by ``Fill.position_id`` or the position's fill id lists."""
    by_id = {f.id: f for f in fills}
    grouped: dict[str, dict[str, Fill]] = defaultdict(dict)
    for f in fills:
        if f.position_id is not None:
            grouped[f.position_id][f.id] = f
    for p in positions:
        for fill_id in (*p.entry_fill_ids, *p.exit_fill_ids):
            if fill_id in by_id:
                grouped[p.id][fill_id] = by_id[fill_id]
    return {p.id: list(grouped[p.id].values()) for p in positions}


def _fills_usd(fills: Iterable[Fill]) -> float | None:
    """Net USD flow of ``fills`` valued at each fill's own SOL price (None if one is unknown)."""
    total = 0.0
    for f in fills:
        if not f.sol_usd or f.sol_usd <= 0:
            return None
        total += f.sol_delta_lamports() / LAMPORTS_PER_SOL * f.sol_usd
    return total


def daily_summaries(trades: list[TradePnL], fills: list[Fill]) -> list[DailySummary]:
    """PURE: group closed trades by UTC day of ``closed_at`` (ascending days)."""
    by_id = {f.id: f for f in fills}
    days: dict[str, DailySummary] = {}
    for t in trades:
        if t.status != "closed" or t.closed_at is None:
            continue
        day = utc_day(t.closed_at)
        s = days.setdefault(day, DailySummary(day=day, trades_closed=0, wins=0, losses=0, realized_lamports=0,
                                              fees_lamports=0, realized_usd=0.0))
        s.trades_closed += 1
        s.wins += t.realized_lamports > 0
        s.losses += t.realized_lamports < 0
        s.realized_lamports += t.realized_lamports
        s.fees_lamports += t.fees_lamports
        usd = _fills_usd(by_id[i] for i in t.fill_ids if i in by_id)
        s.realized_usd = None if s.realized_usd is None or usd is None else s.realized_usd + usd
    return [days[d] for d in sorted(days)]


def _totals(trades: list[TradePnL], daily: list[DailySummary]) -> dict[str, Any]:
    """Closed-trade results (``realized_*``), partial profits of open trades kept apart, all fees."""
    closed = [t for t in trades if t.status == "closed"]
    wins = sum(t.realized_lamports > 0 for t in closed)
    usd = [d.realized_usd for d in daily]
    return {
        "trades": len(closed),
        "open_trades": len(trades) - len(closed),
        "wins": wins,
        "losses": sum(t.realized_lamports < 0 for t in closed),
        "win_rate_pct": wins / len(closed) * 100.0 if closed else None,
        "realized_lamports": sum(t.realized_lamports for t in closed),
        "realized_usd": None if None in usd else sum((u for u in usd if u is not None), 0.0),
        "open_realized_lamports": sum(t.realized_lamports for t in trades if t.status != "closed"),
        "fees_lamports": sum(t.fees_lamports for t in trades),
    }


# --------------------------------------------------------------------------- auditor


class Auditor:
    """Reconciles ledger vs broker; also verifies the receipt chain."""

    def __init__(self, ledger: Any, broker: Any, clock: Any | None = None, *, mode: str | None = None) -> None:
        """``mode`` is only used without a broker (offline report); default ``paper``."""
        self.ledger = ledger
        self.broker = broker
        self.clock = clock if clock is not None else RealClock()
        self.mode = getattr(broker, "mode", None) or mode or "paper"

    def reconcile(self, verify_chain: bool = True) -> AuditReport:
        """Build an :class:`AuditReport` (never raises on drift; raises only on storage errors).

        ``broker`` may be None (offline report): balance comparison is skipped
        and noted in ``issues``.
        """
        report = AuditReport(ok=True, mode=self.mode, checked_at=float(self.clock.now()),
                             expected_sol_lamports=None, broker_sol_lamports=None, sol_drift_lamports=None)
        self._check_balances(report)
        all_fills = self.ledger.fills(limit=None)
        positions = self.ledger.positions(limit=None)
        grouped = _fills_by_position(positions, all_fills)
        self._check_books(report, positions, all_fills, grouped)
        self._check_fill_receipts(report)
        # P&L of THIS wallet only: fills of this mode (paper: since the last reset) and their positions
        _, after_seq = self._epoch()
        epoch = self.ledger.fills_after_seq(after_seq, mode=self.mode)
        epoch_ids = {f.id for f in epoch}
        mine = [p for p in positions
                if (p.mode or next((f.mode for f in grouped[p.id]), None)) == self.mode
                and (p.is_open or any(f.id in epoch_ids for f in grouped[p.id]))]
        report.trades = sorted((trade_pnl(p, [f for f in grouped[p.id] if f.id in epoch_ids]) for p in mine),
                               key=lambda t: (t.opened_at, t.position_id))
        report.daily = daily_summaries(report.trades, epoch)
        report.totals = _totals(report.trades, report.daily)
        if verify_chain:
            report.chain_ok, report.chain_first_bad_seq = self.ledger.verify_chain()
            if not report.chain_ok:
                self._problem(report, f"receipt chain broken at seq {report.chain_first_bad_seq}")
        return report

    # ------------------------------------------------------------------ balances
    @staticmethod
    def _problem(report: AuditReport, issue: str) -> None:
        report.ok = False
        report.issues.append(issue)

    def _epoch(self) -> tuple[int | None, int]:
        """``(start_lamports, after_seq)``: the wallet's starting SOL and the receipt seq it starts after."""
        start = self.ledger.get_kv(f"{self.mode}.start_lamports")
        reset = self.ledger.last_receipt("note", {"event": "paper_reset"}) if self.mode == "paper" else None
        return (None if start is None else int(start)), (reset.seq if reset is not None else 0)

    def _withdrawn(self) -> int:
        """Live: lamports that left this wallet in confirmed ``WITHDRAW_TO`` transfers (``withdraw`` receipts,
        amount + network fee; :mod:`nightcrawler.withdraw`), so a withdrawal is not reported as missing SOL."""
        if self.mode != "live":
            return 0
        wallet = getattr(self.broker, "pubkey", None)
        total = 0
        for r in self.ledger.iter_receipts():
            p = r.payload
            if r.kind != "withdraw" or p.get("mode") != "live" or (wallet and p.get("from") != wallet):
                continue
            total += sum(v for v in (p.get("lamports"), p.get("fee_lamports"))
                         if isinstance(v, int) and not isinstance(v, bool))
        return total

    def _check_balances(self, report: AuditReport) -> None:
        start, after_seq = self._epoch()
        fills = self.ledger.fills_after_seq(after_seq, mode=self.mode)
        expected_tokens: dict[str, int] = defaultdict(int)
        for f in fills:
            expected_tokens[f.mint] += f.token_delta()
        if start is None:
            issue = f"start balance unknown (kv {self.mode}.start_lamports missing): SOL not compared"
            if self.mode == "live" and fills:
                self._problem(report, issue)  # live SOL could leak from the wallet unnoticed
            else:
                report.issues.append(issue)
        else:
            report.expected_sol_lamports = start + sum(f.sol_delta_lamports() for f in fills) - self._withdrawn()
        if self.broker is None:
            report.issues.append("no broker: balance comparison skipped")
            return
        try:
            balances = self.broker.balances()
        except Exception as exc:  # network trouble must not hide the rest of the report
            report.issues.append(f"broker balances unavailable ({type(exc).__name__}): comparison skipped")
            return
        report.broker_sol_lamports = int(balances.sol_lamports)
        self._compare_sol(report)
        self._compare_tokens(report, dict(expected_tokens), {m: int(a) for m, a in balances.tokens.items()})

    def _compare_sol(self, report: AuditReport) -> None:
        if report.expected_sol_lamports is None or report.broker_sol_lamports is None:
            return
        drift = report.broker_sol_lamports - report.expected_sol_lamports
        report.sol_drift_lamports = drift
        text = f"SOL drift {drift / LAMPORTS_PER_SOL:+.9f} SOL ({drift:+d} lamports)"
        if self.mode == "paper" and drift:
            self._problem(report, f"{text}: paper balances must match the fills exactly")
        elif drift < -SOL_DRIFT_TOLERANCE_LAMPORTS:
            self._problem(report, f"{text}: the wallet holds LESS SOL than the books say")
        elif abs(drift) > SOL_DRIFT_TOLERANCE_LAMPORTS:
            report.issues.append(f"{text}: more than the books say (deposit or unmodelled refund?)")

    def _compare_tokens(self, report: AuditReport, expected: dict[str, int], actual: dict[str, int]) -> None:
        for mint in sorted(set(expected) | set(actual)):
            exp, act = expected.get(mint, 0), actual.get(mint, 0)
            drift = act - exp
            if drift == 0:
                continue
            report.token_drift[mint] = {"expected": exp, "actual": act, "drift": drift}
            if self.mode == "live" and mint not in expected:
                report.issues.append(f"untracked token {mint} in the wallet ({act} base units; airdrop?)")
            elif self.mode == "paper" or abs(drift) > TOKEN_DRIFT_TOLERANCE:
                self._problem(report, f"token drift {mint}: books {exp}, wallet {act} ({drift:+d} base units)")

    def _check_fill_receipts(self, report: AuditReport) -> None:
        """Every fill row must equal its hash-chained receipt (the report's numbers come from rows)."""
        pairs = getattr(self.ledger, "fill_receipts", None)
        if pairs is None:  # a duck-typed ledger without receipts per fill
            return
        for fill_id, row, payload, digest in pairs():
            if payload is None:
                self._problem(report, f"fill {fill_id} has no fill receipt")
            elif ({k: v for k, v in row.items() if k != "receipt_hash"}
                  != {k: v for k, v in payload.items() if k != "receipt_hash"} or row.get("receipt_hash") != digest):
                self._problem(report, f"fill {fill_id} differs from its receipt (edited after it was recorded)")

    # ------------------------------------------------------------------ books
    def _check_books(self, report: AuditReport, positions: list[Position], fills: list[Fill],
                     grouped: dict[str, list[Fill]]) -> None:
        linked = {f.id for own in grouped.values() for f in own}
        orphans = sorted(f.id for f in fills if f.id not in linked)
        if orphans:
            self._problem(report, f"{len(orphans)} fill(s) not linked to any position "
                                  f"(tokens nobody manages): {', '.join(orphans[:5])}")
        abandoned = self._abandoned_by_reset(positions, grouped)
        for p in positions:
            drift: dict[str, dict[str, int]] = {}
            for name, total in POSITION_SUMS.items():
                books, from_fills = int(getattr(p, name)), total(grouped[p.id])
                if books != from_fills:
                    drift[name] = {"books": books, "fills": from_fills, "drift": books - from_fills}
            if not drift:
                continue
            report.position_drift[p.id] = drift
            label = f"position {p.id} ({p.symbol or p.mint})"
            tokens = drift.get("token_amount")
            if (p.id in abandoned and set(drift) == {"token_amount"} and tokens is not None
                    and tokens["books"] == 0 < tokens["fills"]):
                report.issues.append(f"{label} was closed by a paper reset with {tokens['fills']} tokens unsold "
                                     "(the virtual wallet was wiped)")
                continue
            for name, d in drift.items():
                if name == "token_amount":
                    self._problem(report, f"{label} says {d['books']} tokens, its fills net {d['fills']}")
                else:
                    self._problem(report, f"{label} {name}: books {d['books']}, its fills {d['fills']} "
                                          f"({d['drift']:+d})")

    def _abandoned_by_reset(self, positions: list[Position], grouped: dict[str, list[Fill]]) -> set[str]:
        """Ids of closed paper positions whose fills all precede the latest ``paper_reset``."""
        reset = self.ledger.last_receipt("note", {"event": "paper_reset"})
        if reset is None:
            return set()
        later = {f.id for f in self.ledger.fills_after_seq(reset.seq, mode="paper")}
        return {p.id for p in positions if not p.is_open and grouped[p.id]
                and all(f.mode == "paper" and f.id not in later for f in grouped[p.id])}

    # ------------------------------------------------------------------ text
    @staticmethod
    def format_text(report: AuditReport) -> str:
        """Human-readable multi-line summary for ``nightcrawler report`` (SOL with 4 decimals)."""
        lines = [f"nightcrawler audit - {report.mode.upper()} - {iso_utc(report.checked_at)}",
                 f"Result: {'OK' if report.ok else 'PROBLEMS FOUND'}",
                 f"Receipt chain: {_chain_text(report)}",
                 (f"SOL: books {_sol(report.expected_sol_lamports)}, wallet {_sol(report.broker_sol_lamports)}, "
                  f"drift {_sol(report.sol_drift_lamports, signed=True)}")]
        if report.token_drift:
            lines.append("Token drift (base units):")
            lines += [f"  {mint}: books {d['expected']}, wallet {d['actual']}, drift {d['drift']:+d}"
                      for mint, d in report.token_drift.items()]
        else:
            lines.append("Tokens: no drift" if report.broker_sol_lamports is not None else "Tokens: not compared")
        if report.position_drift:
            lines.append("Position drift (position row vs the sum of its fills):")
            lines += [f"  {pid} {name}: books {d['books']}, fills {d['fills']}, drift {d['drift']:+d}"
                      for pid, fields in report.position_drift.items() for name, d in fields.items()]
        if report.issues:
            lines.append("Issues:")
            lines += [f"  - {issue}" for issue in report.issues]
        lines += _totals_text(report.totals)
        if report.trades:
            lines += ["", "Trades (oldest first):", _TRADE_HEADER]
            lines += [_trade_row(t) for t in report.trades]
        if report.daily:
            lines += ["", "Daily (UTC, by close time):", _DAY_HEADER]
            lines += [_day_row(d) for d in report.daily]
        return "\n".join(lines)


# --------------------------------------------------------------------------- text helpers

_TRADE_HEADER = (f"  {'symbol':<10} {'opened (UTC)':<20} {'status':<6} {'cost SOL':>9} {'proceeds':>9} "
                 f"{'fees':>7} {'realized':>9} {'pct':>7} {'impact':>6}  exit")
_DAY_HEADER = f"  {'day':<10} {'closed':>6} {'W/L':>5} {'realized SOL':>13} {'realized $':>10} {'fees SOL':>9}"


def _sol(lamports: int | None, signed: bool = False) -> str:
    if lamports is None:
        return "n/a"
    return f"{lamports / LAMPORTS_PER_SOL:{'+' if signed else ''}.4f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def _usd(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}"


def _chain_text(report: AuditReport) -> str:
    if report.chain_ok is None:
        return "not checked"
    return "verified OK" if report.chain_ok else f"BROKEN at seq {report.chain_first_bad_seq}"


def _totals_text(totals: dict[str, Any]) -> list[str]:
    if not totals:
        return []
    win_rate = totals.get("win_rate_pct")
    rate = "n/a" if win_rate is None else f"{win_rate:.0f}%"
    return [(f"Trades: {totals['trades']} closed ({totals['wins']} won / {totals['losses']} lost, "
             f"win rate {rate}), {totals['open_trades']} open"),
            (f"Closed trades: {_sol(totals['realized_lamports'], signed=True)} SOL "
             f"({_usd(totals['realized_usd'])} USD at fill-time SOL prices)"),
            (f"Open trades, realized so far: {_sol(totals['open_realized_lamports'], signed=True)} SOL; "
             f"network fees paid: {_sol(totals['fees_lamports'])} SOL")]


def _trade_row(t: TradePnL) -> str:
    impact = "n/a" if t.avg_price_impact_pct is None else f"{t.avg_price_impact_pct:.2f}%"
    return (f"  {(t.symbol or t.mint[:8])[:10]:<10} {iso_utc(t.opened_at) or '':<20} {t.status:<6} "
            f"{_sol(t.cost_lamports):>9} {_sol(t.proceeds_lamports):>9} {_sol(t.fees_lamports):>7} "
            f"{_sol(t.realized_lamports, signed=True):>9} {_pct(t.realized_pct):>7} {impact:>6}  "
            f"{t.exit_reason or '-'}")


def _day_row(d: DailySummary) -> str:
    return (f"  {d.day:<10} {d.trades_closed:>6} {f'{d.wins}/{d.losses}':>5} "
            f"{_sol(d.realized_lamports, signed=True):>13} {_usd(d.realized_usd):>10} {_sol(d.fees_lamports):>9}")
