"""The Arena: a town of trader bots that must pay rent or be evicted (PRACTICE money only).

The owner's idea, 2026-10-11: "give the bots incentive: keep the town alive or you're homeless". A program does not
feel pressure, but a population can be selected by it. The Arena is that selection, run live against Polymarket US:

* :data:`POPULATION` residents, each with its own practice cash (:data:`START_CASH`) and its own way of trading (its
  *genes*: which kind of market, which side, what price band, when to take profit, when to cut a loss, how long to
  hold, how much of its cash per trade). Every :data:`POLL_S` each resident looks at the live quotes and trades by its
  genes: it buys at the ask and sells at the bid, paying the venue's real taker fee both ways
  (:func:`nightcrawler.polydesk._fee`), or holds to the venue's settlement.
* Rent: at each new UTC day every resident pays :data:`RENT_USD`. One whose money (cash plus what its positions would
  sell for) cannot cover the rent, or that falls under :data:`BROKE_USD` at any time, is EVICTED: its positions are
  sold at the bid and it leaves the town (the graveyard keeps its record).
* Births: each empty home goes to a child of one of the richest residents (:func:`child_genes`: the parent's genes,
  each nudged a little, now and then a new side or market kind) with fresh practice cash. Over days the town fills
  with the styles that earned their rent; the ones that did not are gone.
* A resident alive :data:`CANDIDATE_DAYS` days, with :data:`CANDIDATE_TRADES` closed trades and a profit after rent,
  is marked a *candidate*: shown to the owner, never given real money by this module.

PRACTICE ONLY. This module holds no client, no key and no order path: it reads the venue's PUBLIC gateway through
the Polymarket desk's helpers (:func:`~nightcrawler.polydesk.open_markets`,
:func:`~nightcrawler.polydesk.live_sports_markets`, :func:`~nightcrawler.polydesk.bbo`,
:func:`~nightcrawler.polydesk.settlement`) in its own thread, and writes ``DATA_DIR/arena/state.json``. A practice
fill at the quoted price is optimistic for a size the book does not hold; the record says so (``LABEL``).
Evolution also finds styles that were merely lucky: a candidate still needs its own test before any real dollar.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
import zlib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nightcrawler import polydesk
from nightcrawler.config import Settings

log = logging.getLogger("nightcrawler.arena")

STATE_VERSION = 1
LABEL = "Practice (pretend money)"
POLL_S = 60.0
FIRST_POLL_DELAY_S = 45.0
UNIVERSE_EVERY_S = 15 * 60.0  # the market lists, read again at most this often
QUOTES_PER_ROUND = 80  # markets quoted per round besides the ones held (a rotating sample of the lists)
SETTLE_EVERY_S = 600.0  # an ended market's settlement, asked at most this often
VOID_AFTER_S = 7 * 86_400.0  # an ended market never settled this long: the position is closed at its cost
POPULATION = 24
START_CASH = 20.0
RENT_USD = 1.00  # paid by every resident at each new UTC day (20 days of rent in its start cash)
BROKE_USD = 1.0  # below this (cash plus positions at the bid) a resident cannot trade: evicted at once
MAX_POSITIONS = 3  # per resident
MIN_TICKET_USD = 0.50
COOLDOWN_S = 30 * 60.0  # a resident does not buy back a market it sold this recently
CANDIDATE_DAYS = 7
CANDIDATE_TRADES = 30
EVENTS_KEEP = 60
GRAVE_KEEP = 40
SEED = 20261011

FAMILIES = ("crypto", "weather", "sports")  # the kinds of market the venue lists within two days (2026-10-11)
SIDES = ("yes", "no", "cheap", "dear")  # yes / no, or the cheaper / the dearer side of the market
#: Each number gene's range; a child's gene moves by up to :data:`MUTATE` of its range.
RANGES: dict[str, tuple[float, float]] = {
    "lo": (0.03, 0.95),  # the lowest ask it buys at
    "width": (0.02, 0.60),  # ... up to lo + width (at most 0.99)
    "tp": (0.01, 0.40),  # sell when the bid is this far above its price (0.40: in effect, hold)
    "sl": (0.02, 0.60),  # sell when the bid is this far below its price
    "hold_h": (0.25, 72.0),  # sell at the bid after this many hours (or hold to the end when the market ends first)
    "max_spread": (0.01, 0.08),  # a book wider than this is left alone
    "stake": (0.05, 0.60),  # the share of its cash per trade
    "horizon_h": (0.5, 48.0),  # only markets ending within this many hours
}
MUTATE = 0.12
NAMES = ("Ada", "Bo", "Cy", "Dex", "Eve", "Fin", "Gus", "Hal", "Ivy", "Jax", "Kai", "Lux", "Mae", "Nox", "Oz", "Pip",
         "Quin", "Rex", "Sol", "Tex", "Uma", "Vic", "Wren", "Xia", "Yul", "Zed", "Ari", "Bex", "Cal", "Dot", "Echo",
         "Fox", "Gem", "Hex", "Ink", "Jet", "Kit", "Lev", "Moe", "Nia")


# ---------------------------------------------------------------------- genes
def family(m: Mapping[str, Any]) -> str:
    """A market's kind: sports, crypto, weather (climate too), or "other"."""
    cat = str(m.get("category") or "").lower()
    if cat == "sports":
        return "sports"
    if cat in ("crypto",):
        return "crypto"
    if cat in ("weather", "climate"):
        return "weather"
    return "other"  # a kind no resident trades (none was listed within two days on 2026-10-11)


def random_genes(rng: random.Random) -> dict[str, Any]:
    genes: dict[str, Any] = {k: round(rng.uniform(lo, hi), 4) for k, (lo, hi) in RANGES.items()}
    genes["family"] = rng.choice(FAMILIES)
    genes["side"] = rng.choice(SIDES)
    return genes


def child_genes(parent: Mapping[str, Any], rng: random.Random) -> dict[str, Any]:
    """The parent's genes, each number nudged by up to :data:`MUTATE` of its range (kept inside it); one time in
    ten a new market kind, one time in ten a new side."""
    genes: dict[str, Any] = {}
    for k, (lo, hi) in RANGES.items():
        base = polydesk._num(parent.get(k))
        base = rng.uniform(lo, hi) if base is None else base
        genes[k] = round(min(hi, max(lo, base + rng.uniform(-MUTATE, MUTATE) * (hi - lo))), 4)
    genes["family"] = rng.choice(FAMILIES) if rng.random() < 0.1 or parent.get("family") not in FAMILIES else (
        parent["family"])
    genes["side"] = rng.choice(SIDES) if rng.random() < 0.1 or parent.get("side") not in SIDES else parent["side"]
    return genes


def style(genes: Mapping[str, Any]) -> str:
    """A resident's way of trading in a few words: 'crypto, the cheap side 0.10-0.35, +0.08 / -0.12, 6 h'."""
    lo = float(genes["lo"])
    hi = min(0.99, lo + float(genes["width"]))
    side = {"yes": "YES", "no": "NO", "cheap": "the cheap side", "dear": "the favourite"}[str(genes["side"])]
    hold = "to the end" if float(genes["tp"]) >= 0.39 else f"+{float(genes['tp']):.2f} / -{float(genes['sl']):.2f}"
    return f"{genes['family']}, {side} {lo:.2f}-{hi:.2f}, {hold}, {float(genes['hold_h']):.0f} h"


# ---------------------------------------------------------------------- prices
def side_prices(q: Mapping[str, Any], side: str) -> tuple[float | None, float | None]:
    """(ask, bid) of one side of a market from its quote (the YES book; NO's ask is 1 - YES bid, its bid 1 - YES
    ask)."""
    bid, ask = polydesk._num(q.get("best_bid")), polydesk._num(q.get("best_ask"))
    if side == "yes":
        return ask, bid
    return (None if bid is None else 1.0 - bid), (None if ask is None else 1.0 - ask)


def pick_side(genes: Mapping[str, Any], q: Mapping[str, Any]) -> str | None:
    """The side a resident buys in this market by its genes, or None (no price in its band, or the book too wide)."""
    bid, ask = polydesk._num(q.get("best_bid")), polydesk._num(q.get("best_ask"))
    if bid is None or ask is None or not 0.0 < bid < ask < 1.0 or ask - bid > float(genes["max_spread"]) + 1e-9:
        return None
    want = str(genes["side"])
    if want in ("cheap", "dear"):
        yes_cheaper = ask <= 1.0 - bid
        want = "yes" if yes_cheaper == (want == "cheap") else "no"
    price, _ = side_prices(q, want)
    lo = float(genes["lo"])
    hi = min(0.99, lo + float(genes["width"]))
    return want if price is not None and lo <= price <= hi else None


def _day(now: float) -> str:
    return datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------- state
def empty_state() -> dict[str, Any]:
    return {"version": STATE_VERSION, "residents": {}, "grave": [], "events": [], "day": None, "next_id": 1,
            "town": {"born": 0, "evicted": 0, "trades": 0, "rent_paid": 0.0, "days": 0},
            "today": {"day": None, "born": 0, "evicted": 0, "buys": 0, "trades": 0, "pnl_usd": 0.0},
            "markets": [], "universe_at": 0.0, "settle_tried": {}, "cursor": 0,
            "counters": {"polls": 0, "errors": 0, "quotes": 0}, "last_poll": None, "last_ok": None}


def load_state(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return empty_state()
    if not isinstance(doc, dict) or doc.get("version") != STATE_VERSION:
        return empty_state()
    base = empty_state()
    base.update({k: v for k, v in doc.items() if k in base and type(v) is type(base[k]) or base.get(k) is None})
    for key in ("town", "today", "counters"):
        kept = doc.get(key)
        base[key] = {**empty_state()[key], **(kept if isinstance(kept, dict) else {})}
    return base


def state_path(settings: Settings) -> Path:
    return Path(settings.data_dir) / "arena" / "state.json"


def equity(res: Mapping[str, Any], quotes: Mapping[str, Mapping[str, Any]]) -> float:
    """Cash plus each position at its side's bid (its cost when there is no fresh bid)."""
    total = float(res.get("cash") or 0.0)
    for pos in (res.get("positions") or {}).values():
        q = quotes.get(pos["slug"])
        _, bid = side_prices(q, pos["side"]) if q else (None, None)
        total += pos["shares"] * bid if bid is not None else pos["cost_usd"]
    return total


class Arena:
    """The Arena's runtime (one daemon thread). PRACTICE ONLY: no client, no key, no order path.
    ``poll(now, markets=None, quotes=None)`` is also callable directly (tests pass markets and quotes)."""

    def __init__(self, settings: Settings, path: Path | None = None, seed: int = SEED) -> None:
        self.settings = settings
        self.path = path or state_path(settings)
        self.state = load_state(self.path)
        self.rng = random.Random(seed + int(self.state.get("next_id") or 0))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="arena", daemon=True)
        self._thread.start()
        log.info("arena_started population=%d rent_usd=%.2f (practice only)", POPULATION, RENT_USD)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self._stop.wait(FIRST_POLL_DELAY_S)
        while not self._stop.is_set():
            t0 = time.time()
            try:
                self.poll(t0)
            except Exception as exc:  # noqa: BLE001 (a practice town keeps going; nothing else is affected)
                self.state["counters"]["errors"] += 1
                self._save()
                log.warning("arena_poll_failed error=%s", type(exc).__name__)
            self._stop.wait(max(5.0, POLL_S - (time.time() - t0)))

    def _save(self) -> None:
        polydesk.save_state(self.path, self.state)

    def _event(self, now: float, who: str, text: str, tone: str = "neutral") -> None:
        self.state["events"].insert(0, {"ts": now, "who": who, "text": text[:160], "tone": tone})
        del self.state["events"][EVENTS_KEEP:]

    # ------------------------------------------------------------------ the market data
    def _universe(self, now: float) -> list[dict[str, Any]]:
        st = self.state
        if now - float(st.get("universe_at") or 0.0) >= UNIVERSE_EVERY_S or not st["markets"]:
            markets = []
            try:
                markets += polydesk.open_markets(now)
            except RuntimeError:
                st["counters"]["errors"] += 1
            try:
                markets += polydesk.live_sports_markets(now)
            except RuntimeError:
                st["counters"]["errors"] += 1
            if markets:
                st["markets"] = [{k: m.get(k) for k in ("slug", "question", "category", "end_ts", "fee_coef",
                                                        "event")} for m in markets if m.get("slug")]
                st["universe_at"] = now
        return st["markets"]

    def _quotes(self, markets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """This round's quotes: every market a resident holds, plus a rotating sample of the lists."""
        st = self.state
        held = {p["slug"] for r in st["residents"].values() for p in r["positions"].values()}
        n = len(markets)
        start = int(st.get("cursor") or 0) % n if n else 0
        sample = [markets[(start + i) % n]["slug"] for i in range(min(QUOTES_PER_ROUND, n))]
        st["cursor"] = start + len(sample)
        out: dict[str, dict[str, Any]] = {}
        for slug in list(held) + [s for s in sample if s not in held]:
            try:
                out[slug] = polydesk.bbo(slug)
                st["counters"]["quotes"] += 1
            except RuntimeError:
                st["counters"]["errors"] += 1
            time.sleep(polydesk.REQ_SLEEP_S)
        return out

    # ------------------------------------------------------------------ one round
    def poll(self, now: float, markets: list[dict[str, Any]] | None = None,
             quotes: dict[str, dict[str, Any]] | None = None) -> dict[str, int]:
        st = self.state
        st["counters"]["polls"] += 1
        st["last_poll"] = now
        self._new_day(now)
        self._fill_homes(now)
        markets = self._universe(now) if markets is None else markets
        quotes = self._quotes(markets) if quotes is None else quotes
        by_slug = {m["slug"]: m for m in markets}
        closed = self._exits(now, quotes, by_slug)
        opened = self._entries(now, markets, quotes)
        evicted = self._evict(now, quotes)
        self._fill_homes(now)
        st["last_ok"] = now
        self._save()
        today = self._today(now)
        log.info("arena_round residents=%d quotes=%d buys=%d sales=%d evicted=%d today_buys=%d today_sales=%d "
                 "today_pnl=%.2f", len(st["residents"]), len(quotes), opened, closed, evicted, today["buys"],
                 today["trades"], float(today["pnl_usd"]))
        return {"opened": opened, "closed": closed, "evicted": evicted}

    def _today(self, now: float) -> dict[str, Any]:
        t = self.state["today"]
        if t.get("day") != _day(now):
            t.clear()
            t.update({"day": _day(now), "born": 0, "evicted": 0, "buys": 0, "trades": 0, "pnl_usd": 0.0})
        return t

    def _new_day(self, now: float) -> None:
        """Rent day: at each new UTC day every resident pays :data:`RENT_USD` out of its cash (it may go below zero
        while its money is in positions: no new trade until a sale pays it back); one whose money (cash plus its
        positions at their cost) cannot cover the rent is evicted."""
        st = self.state
        day = _day(now)
        if st.get("day") == day:
            return
        first = st.get("day") is None
        st["day"] = day
        if first or not st["residents"]:
            return
        st["town"]["days"] += 1
        quotes: dict[str, dict[str, Any]] = {}
        for res in list(st["residents"].values()):
            if equity(res, quotes) < RENT_USD:
                self._evict_one(now, res, quotes, "could not pay the rent")
                continue
            res["cash"] = float(res["cash"]) - RENT_USD
            res["rent_paid"] += RENT_USD
            st["town"]["rent_paid"] += RENT_USD

    def _fill_homes(self, now: float) -> None:
        """Every empty home gets a resident: random genes for the town's first ones, else a child of one of the
        richest (the top half by money, the richer more often)."""
        st = self.state
        residents = st["residents"]
        while len(residents) < POPULATION:
            ranked = sorted(residents.values(), key=lambda r: -float(r["cash"]) - sum(
                p["cost_usd"] for p in r["positions"].values()))
            parents = ranked[: max(1, len(ranked) // 2)] if st["town"]["born"] >= POPULATION and ranked else []
            if parents:
                parent = parents[min(len(parents) - 1, int(self.rng.random() ** 2 * len(parents)))]
                genes, gen, parent_id = child_genes(parent["genes"], self.rng), int(parent["gen"]) + 1, parent["id"]
            else:
                genes, gen, parent_id = random_genes(self.rng), 1, None
            rid = int(st["next_id"])
            st["next_id"] = rid + 1
            name = f"{NAMES[(rid - 1) % len(NAMES)]}-{rid}"
            residents[str(rid)] = {"id": str(rid), "name": name, "gen": gen, "parent": parent_id, "born": now,
                                   "genes": genes, "cash": START_CASH, "positions": {}, "trades": 0, "wins": 0,
                                   "pnl_usd": 0.0, "rent_paid": 0.0, "last_trade": None}
            st["town"]["born"] += 1
            self._today(now)["born"] += 1
            if parent_id is not None:
                pname = parent["name"]
                self._event(now, name, f"{name} moved in: a child of {pname}, trading {style(genes)}.", "good")

    # ------------------------------------------------------------------ trading
    def _entries(self, now: float, markets: list[dict[str, Any]], quotes: Mapping[str, Mapping[str, Any]]) -> int:
        st = self.state
        opened = 0
        quoted = [m for m in markets if m["slug"] in quotes]
        for res in st["residents"].values():
            genes = res["genes"]
            if len(res["positions"]) >= MAX_POSITIONS:
                continue
            recent = res.setdefault("recent", {})
            for slug in [s for s, t in recent.items() if now - float(t) >= COOLDOWN_S]:
                del recent[slug]
            mine = [m for m in quoted if family(m) == genes["family"] and m["slug"] not in res["positions"]
                    and m["slug"] not in recent
                    and m.get("end_ts") is not None and now < float(m["end_ts"]) <= now + float(genes["horizon_h"])
                    * 3600 and quotes[m["slug"]].get("state") in (None, polydesk.OPEN_STATE)]
            mine.sort(key=lambda m: zlib.crc32(f"{res['id']}|{m['slug']}".encode()))  # each its own order
            for m in mine:
                side = pick_side(genes, quotes[m["slug"]])
                if side is None:
                    continue
                price, _ = side_prices(quotes[m["slug"]], side)
                assert price is not None
                stake = float(res["cash"]) * float(genes["stake"])
                if stake < MIN_TICKET_USD:
                    break
                coef = polydesk._num(m.get("fee_coef"))
                coef = polydesk.US_TAKER if coef is None else coef
                shares = stake / (price + polydesk._fee(coef, price))
                fee = polydesk._fee(coef, price) * shares
                res["cash"] = float(res["cash"]) - stake
                res["positions"][m["slug"]] = {"slug": m["slug"], "side": side, "price": price, "shares": shares,
                                               "fee_usd": fee, "cost_usd": stake, "at": now,
                                               "end_ts": float(m["end_ts"]), "coef": coef,
                                               "what": str(m.get("event") or m.get("question") or m["slug"])[:80]}
                res["last_trade"] = now
                self._today(now)["buys"] += 1
                opened += 1
                self._event(now, res["name"], f"{res['name']} bought {side.upper()} at {price:.2f}: "
                            f"{str(m.get('event') or m.get('question') or '')[:70]} (${stake:.2f}, practice).")
                break
        return opened

    def _exits(self, now: float, quotes: Mapping[str, Mapping[str, Any]], by_slug: Mapping[str, Any]) -> int:
        closed = 0
        for res in self.state["residents"].values():
            genes = res["genes"]
            for slug, pos in list(res["positions"].items()):
                q = quotes.get(slug)
                if now >= pos["end_ts"] or (q and q.get("state") not in (None, polydesk.OPEN_STATE)):
                    closed += self._settle(now, res, pos)
                    continue
                if q is None:
                    continue
                _, bid = side_prices(q, pos["side"])
                if bid is None or bid <= 0.0:
                    continue
                pos["mark"], pos["mark_at"] = bid, now  # what it would sell for now (the page's live worth)
                why = None
                if bid >= pos["price"] + float(genes["tp"]):
                    why = "took profit"
                elif bid <= pos["price"] - float(genes["sl"]):
                    why = "cut the loss"
                elif now - pos["at"] >= float(genes["hold_h"]) * 3600:
                    why = "time's up"
                if why:
                    self._close(now, res, pos, pos["shares"] * bid - polydesk._fee(pos["coef"], bid) * pos["shares"],
                                why)
                    closed += 1
        return closed

    def _settle(self, now: float, res: dict[str, Any], pos: dict[str, Any]) -> int:
        """An ended (or no longer open) market: the venue's settlement price, asked at most every SETTLE_EVERY_S per
        market; a market never settled VOID_AFTER_S after its end is closed at its cost."""
        tried = self.state["settle_tried"]
        slug = pos["slug"]
        cached = tried.get(slug)
        value = cached.get("value") if isinstance(cached, dict) else None
        if value is None and (not isinstance(cached, dict) or now - float(cached.get("at") or 0) >= SETTLE_EVERY_S):
            try:
                value = polydesk.settlement(slug)
            except RuntimeError:
                value = None
            tried[slug] = {"at": now, "value": value}
        if value is None:
            if now - pos["end_ts"] > VOID_AFTER_S:
                self._close(now, res, pos, pos["cost_usd"], "never settled (void)")
                return 1
            return 0
        paid = float(value) if pos["side"] == "yes" else 1.0 - float(value)
        self._close(now, res, pos, pos["shares"] * paid, "won at the end" if paid >= 0.5 else "lost at the end")
        return 1

    def _close(self, now: float, res: dict[str, Any], pos: Mapping[str, Any], proceeds: float, why: str) -> None:
        pnl = proceeds - float(pos["cost_usd"])
        res["cash"] = float(res["cash"]) + proceeds
        res["positions"].pop(pos["slug"], None)
        res.setdefault("recent", {})[pos["slug"]] = now
        res["trades"] += 1
        res["wins"] += int(pnl > 0)
        res["pnl_usd"] = float(res["pnl_usd"]) + pnl
        res["last_trade"] = now
        st = self.state
        st["town"]["trades"] += 1
        today = self._today(now)
        today["trades"] += 1
        today["pnl_usd"] = float(today["pnl_usd"]) + pnl
        self._event(now, res["name"], f"{res['name']} {why}: {pos['what'][:60]} {pnl:+.2f} $ (practice).",
                    "good" if pnl > 0 else "bad" if pnl < 0 else "neutral")

    def _sell_all(self, now: float, res: dict[str, Any], quotes: Mapping[str, Mapping[str, Any]], why: str) -> None:
        for pos in list(res["positions"].values()):
            q = quotes.get(pos["slug"])
            _, bid = side_prices(q, pos["side"]) if q else (None, None)
            proceeds = pos["shares"] * bid - polydesk._fee(pos["coef"], bid) * pos["shares"] if bid else pos[
                "cost_usd"]
            self._close(now, res, pos, proceeds, f"sold {why}")

    def _evict(self, now: float, quotes: Mapping[str, Mapping[str, Any]]) -> int:
        """Anyone whose money (positions at this round's bid) is under BROKE_USD is evicted at once."""
        out = 0
        for res in list(self.state["residents"].values()):
            if equity(res, quotes) < BROKE_USD:
                self._evict_one(now, res, quotes, "went broke")
                out += 1
        return out

    def _evict_one(self, now: float, res: dict[str, Any], quotes: Mapping[str, Mapping[str, Any]], why: str) -> None:
        st = self.state
        self._sell_all(now, res, quotes, "on the way out")
        st["residents"].pop(res["id"], None)
        days = (now - float(res["born"])) / 86_400.0
        st["grave"].insert(0, {"name": res["name"], "gen": res["gen"], "why": why, "at": now, "days": round(days, 2),
                               "trades": res["trades"], "pnl_usd": round(float(res["pnl_usd"]), 4),
                               "style": style(res["genes"])})
        del st["grave"][GRAVE_KEEP:]
        st["town"]["evicted"] += 1
        self._today(now)["evicted"] += 1
        self._event(now, res["name"], f"{res['name']} was evicted: {why} after {days:.1f} days "
                    f"({res['trades']} trades, {float(res['pnl_usd']):+.2f} $).", "bad")


# ---------------------------------------------------------------------- the panel
def panel_state(settings: Settings, now: float, leaders: int = 5) -> dict[str, Any]:
    """What the page shows (``money.arena``), from the state file only (no network): the town's counts, today's,
    the leaders (by money: each position at its last bid, its cost before one was seen), the town's trading result
    since the start (``result_usd``: every trade closed, by residents and by the evicted, plus the open positions at
    their last bid; rent apart), the open bets, the candidates, the newest events and evictions."""
    st = load_state(state_path(settings))
    rows = []
    open_bets, unrealized, realized = 0, 0.0, 0.0
    for res in st["residents"].values():
        if not isinstance(res, dict) or not isinstance(res.get("genes"), dict):
            continue
        positions = [p for p in (res.get("positions") or {}).values() if isinstance(p, dict)]
        worth = [float(p["shares"]) * float(p["mark"]) if polydesk._num(p.get("mark")) is not None else float(
            p.get("cost_usd") or 0.0) for p in positions]
        held = sum(worth)
        open_bets += len(positions)
        unrealized += held - sum(float(p.get("cost_usd") or 0.0) for p in positions)
        realized += float(res.get("pnl_usd") or 0.0)
        money = float(res.get("cash") or 0.0) + held
        days = (now - float(res.get("born") or now)) / 86_400.0
        profit = money - START_CASH  # rent already paid out of the cash
        rows.append({"name": res["name"], "gen": res.get("gen"), "money_usd": round(money, 2),
                     "profit_usd": round(profit, 2), "trades": res.get("trades", 0), "wins": res.get("wins", 0),
                     "open": len(res.get("positions") or {}), "days": round(days, 1), "style": style(res["genes"]),
                     "candidate": days >= CANDIDATE_DAYS and int(res.get("trades") or 0) >= CANDIDATE_TRADES
                     and profit > 0})
    rows.sort(key=lambda r: -r["money_usd"])
    realized += sum(float(g.get("pnl_usd") or 0.0) for g in st["grave"] if isinstance(g, dict))
    return {"label": LABEL, "as_of": st.get("last_ok"), "population": len(rows), "rent_usd": RENT_USD,
            "result_usd": round(realized + unrealized, 2), "open_bets": open_bets,
            "start_cash": START_CASH, "town": st["town"], "today": st["today"] if st["today"].get("day") == _day(
                now) else {"day": _day(now), "born": 0, "evicted": 0, "buys": 0, "trades": 0, "pnl_usd": 0.0},
            "leaders": rows[:leaders], "candidates": [r for r in rows if r["candidate"]][:leaders],
            "events": st["events"][:8], "grave": st["grave"][:5]}


def arena_line(panel: Mapping[str, Any] | None) -> str | None:
    """``plain.arena_line``: the Arena in one sentence, always practice ("The Arena (practice money): 24 traders
    paying $1.00 rent a day; today 40 buys, 31 sales and 2 evictions; leader Kai-7 up $4.20.")."""
    if not panel or not panel.get("population"):
        return None
    today = panel.get("today") or {}
    buys, sales = int(today.get("buys") or 0), int(today.get("trades") or 0)
    evicted = int(today.get("evicted") or 0)
    line = (f"The Arena (practice money): {panel['population']} traders paying ${float(panel['rent_usd']):.2f} rent "
            f"a day; today {buys} buy{'' if buys == 1 else 's'}, {sales} sale{'' if sales == 1 else 's'} and "
            f"{evicted} eviction{'' if evicted == 1 else 's'}")
    result = polydesk._num(panel.get("result_usd"))
    if result is not None:
        sign = "+" if result >= 0 else "-"
        n = int(panel.get("open_bets") or 0)
        line += f"; the town's trading {sign}${abs(result):.2f} so far, {n} bet{'' if n == 1 else 's'} open"
    leaders = panel.get("leaders") or []
    if leaders:
        top = leaders[0]
        sign = "up" if top["profit_usd"] >= 0 else "down"
        line += f"; leader {top['name']} {sign} ${abs(float(top['profit_usd'])):.2f}"
    return line + "."
