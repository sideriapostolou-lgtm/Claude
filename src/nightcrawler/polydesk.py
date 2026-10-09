"""The Polymarket desk: a PAPER desk on Polymarket US that watches the venue all day and keeps a paper book under
one candidate rule, so the owner can watch the team work on prediction markets before any rule has earned real
money.

What it does, every ``polydesk_poll_s`` seconds, in its own thread (the trading loop is never blocked):

1. Watch list from the venue's PUBLIC gateway (``gateway.polymarket.us``, no key): every open non-sports market
   ending within :data:`HORIZON_H` hours (per category, the listing is sports-first otherwise) plus the
   match-winner markets of sports games in progress (events with a live period), capped at :data:`SPORTS_CAP`.
2. One best bid / offer per watched market (a small thread pool, well under the gateway's 20 req/s).
3. The candidate rule (lab 4's "near-certain grind", PLAN §2-3): once per market, the first time a side can be
   bought at or above ``polydesk_theta`` within the last ``polydesk_hours`` before the market's end, buy
   ``polydesk_ticket_usd`` of it on paper at the printed price (long at the ask, short at 1 - bid), pay the
   market's own taker fee ``feeCoefficient x shares x p x (1 - p)``, hold to settlement.
4. Settlement: a position whose market left the watch list (or ended) is settled at the venue's settlement price;
   the paper P&L is booked and the day's total updated.

**Live mode** (``POLYDESK_MODE=live`` + ``POLYDESK_LIVE_CONFIRM`` + the account's key in Railway variables, the
owner's explicit switch): the same rule, but a real limit order on Polymarket US for ``polydesk_live_contracts``
contracts of the YES side (long only: the venue prices every order on the YES side, so shorts stay paper-only),
immediate-or-cancel at the printed ask, through :mod:`nightcrawler.polymarket_us`. Caps, checked before every
order: money in open positions <= ``polydesk_live_max_open_usd``; the UTC day's realised loss <=
``polydesk_live_daily_loss_usd`` (then no more buys today); total realised loss <=
``polydesk_live_total_loss_usd`` (then the desk switches itself back to paper for good and says so; only the owner
can switch it live again). Live starts only after a successful balance read; a rejected key leaves the desk on
paper with the reason on the page. Every live order and settlement is receipted in the ledger's hash chain.

State lives in ``DATA_DIR/polydesk/state.json`` (atomic rewrite): open positions, the last closed positions,
daily P&L, counters, the last poll, the live status and the last balance. The team-room panel
(:func:`panel_state`) reads that file. The rule is a CANDIDATE: it earns a real seat only by passing lab 4's
TRAIN / VAL / TEST, and the page says "paper" or "real" everywhere this desk's numbers appear.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from nightcrawler.config import LIVE_CONFIRM_PHRASE, Settings
from nightcrawler.polymarket_us import PolymarketUSClient, PolymarketUSError

log = logging.getLogger("nightcrawler.polydesk")

GATEWAY = "https://gateway.polymarket.us/v1"
UA = {"User-Agent": "nightcrawler/polydesk (paper desk; public market data)"}
PAGE = 100
HORIZON_H = 48.0
SPORTS_CAP = 150
SPORTS_LOOKBACK_H = 12.0
CATEGORIES = (
    "climate",
    "weather",
    "crypto",
    "politics",
    "culture",
    "finance",
    "technology",
    "macro",
    "geopolitics",
    "science",
    "economics",
    "mentions",
    "tech",
)
WINNER_KINDS = ("MONEYLINE", "DRAWABLE_OUTCOME")
NOT_LIVE_PERIODS = {"NS", "", "CAN", "SUS", "PST", "FT", "AOT", "FINAL", "ENDED"}
THREADS = 8
REQ_SLEEP_S = 0.05
MAX_PRICE = 0.999
MAX_SPREAD = 0.03  # a quote counts as near-certain only when bid and ask agree (a wide book is not a belief)
US_TAKER = 0.0695
CLOSED_KEEP = 200
ADOPTED_END_GUESS_S = 3 * 3600.0  # a venue position on a market the watch list no longer carries: check settlement after this
EVENTS_KEEP = 40
STATE_VERSION = 1
FIRST_POLL_DELAY_S = 20.0


def _get(
    path: str,
    params: dict[str, Any] | None = None,
    tries: int = 3,
    timeout: float = 20.0,
) -> Any:
    last: str = "no response"
    for attempt in range(tries):
        try:
            r = requests.get(
                f"{GATEWAY}{path}", params=params, headers=UA, timeout=timeout
            )
            if r.status_code == 429:
                last = "HTTP 429"
                time.sleep(2.0 * (attempt + 1))
                continue
            if r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                time.sleep(1.0 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = type(e).__name__
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"GET {path} failed: {last}")


def parse_iso(value: Any) -> float | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).timestamp()  # Python 3.11+ accepts the trailing Z
    except ValueError:
        return None


def _num(v: Any) -> float | None:
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _market_rec(
    m: dict[str, Any], category: str, end_ts: float, **extra: Any
) -> dict[str, Any]:
    return {
        "slug": m["slug"],
        "question": str(m.get("question") or m.get("title") or m["slug"])[:120],
        "category": category,
        "end_ts": end_ts,
        "fee_coef": _num(m.get("feeCoefficient")),
        **extra,
    }


def open_markets(
    now: float, horizon_h: float = HORIZON_H, max_pages: int = 20
) -> list[dict[str, Any]]:
    """Open non-sports markets ending within ``horizon_h`` hours, listed per category."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cat in CATEGORIES:
        for page in range(max_pages):
            reply = _get(
                "/markets",
                {
                    "limit": PAGE,
                    "offset": page * PAGE,
                    "closed": "false",
                    "categories": cat,
                },
            )
            ms = reply.get("markets") if isinstance(reply, dict) else None
            if not ms:
                break
            for m in ms:
                c = (m.get("category") or "").lower()
                if c == "sports" or m["slug"] in seen:
                    continue
                end_ts = parse_iso(m.get("endDate"))
                if (
                    end_ts is None
                    or end_ts < now - 3600
                    or end_ts > now + horizon_h * 3600
                ):
                    continue
                seen.add(m["slug"])
                out.append(_market_rec(m, c, end_ts))
            if len(ms) < PAGE:
                break
            time.sleep(REQ_SLEEP_S)
        time.sleep(REQ_SLEEP_S)
    return out


def live_sports_markets(now: float, cap: int = SPORTS_CAP) -> list[dict[str, Any]]:
    """Match-winner markets of games in progress (events started within SPORTS_LOOKBACK_H with a live period)."""
    start_min = datetime.fromtimestamp(now - SPORTS_LOOKBACK_H * 3600, UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    start_max = datetime.fromtimestamp(now + 300, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: list[dict[str, Any]] = []
    for page in range(5):
        reply = _get(
            "/events",
            {
                "limit": PAGE,
                "offset": page * PAGE,
                "closed": "false",
                "categories": "sports",
                "startDateMin": start_min,
                "startDateMax": start_max,
            },
        )
        evs = reply.get("events") if isinstance(reply, dict) else None
        if not evs:
            break
        for ev in evs:
            started = parse_iso(ev.get("startTime") or ev.get("startDate"))
            period = str(ev.get("period") or "").upper()
            if started is None or started > now or period in NOT_LIVE_PERIODS:
                continue
            for m in ev.get("markets") or []:
                kind = str(
                    m.get("sportsMarketTypeV2") or m.get("marketType") or ""
                ).upper()
                if not any(w in kind for w in WINNER_KINDS) or m.get("closed"):
                    continue
                out.append(
                    _market_rec(
                        m,
                        "sports",
                        started + 6 * 3600,
                        game_start=started,
                        period=period,
                        event=str(ev.get("title") or ev.get("slug") or "")[:80],
                    )
                )
        if len(evs) < PAGE:
            break
        time.sleep(REQ_SLEEP_S)
    out.sort(key=lambda m: -m["game_start"])
    return out[:cap]


def bbo(slug: str) -> dict[str, float | None]:
    reply = _get(f"/markets/{slug}/bbo")
    md = reply.get("marketData", reply) if isinstance(reply, dict) else {}
    return {
        "best_bid": _num(md.get("bestBid")),
        "best_ask": _num(md.get("bestAsk")),
        "last": _num(md.get("lastTradePx")),
    }


def settlement(slug: str) -> float | None:
    reply = _get(f"/markets/{slug}/settlement")
    return _num(reply.get("settlement")) if isinstance(reply, dict) else None


def empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "positions": {},
        "closed": [],
        "days": {},
        "events": [],
        "counters": {
            "polls": 0,
            "quotes": 0,
            "errors": 0,
            "bought": 0,
            "settled": 0,
            "won": 0,
        },
        "last_poll": None,
        "last_ok": None,
        "watched": 0,
        "last_error": None,
        "rule": None,
        "mode": "paper",
        "live_status": None,
        "live_halted": False,
        "balance": None,
        "live_days": {},
        "live_pnl_total_usd": 0.0,
    }


def load_state(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text())
        if isinstance(doc, dict) and doc.get("version") == STATE_VERSION:
            base = empty_state()
            base.update(doc)
            return base
    except (OSError, ValueError):
        pass
    return empty_state()


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, separators=(",", ":"), sort_keys=True))
    os.replace(tmp, path)


def state_path(settings: Settings) -> Path:
    return Path(settings.data_dir) / "polydesk" / "state.json"


def _reveal(value: Any) -> str:
    """A secret setting's text (``Secret.reveal()``), or the plain string; never logged."""
    return str(value.reveal()) if hasattr(value, "reveal") else str(value or "")


class PolyDesk:
    """The paper desk's runtime (one daemon thread). ``poll(now)`` is also callable directly (tests)."""

    def __init__(
        self,
        settings: Settings,
        path: Path | None = None,
        ledger: Any = None,
        client_factory: Any = None,
    ) -> None:
        self.settings = settings
        self.ledger = ledger
        self.path = path or state_path(settings)
        self.theta = float(settings.polydesk_theta)
        self.hours = float(settings.polydesk_hours)
        self.ticket = float(settings.polydesk_ticket_usd)
        self.poll_s = float(settings.polydesk_poll_s)
        self.contracts = float(settings.polydesk_live_contracts)
        self.client: PolymarketUSClient | None = None  # places orders: live mode only
        self.reader: PolymarketUSClient | None = None  # reads balances and positions whenever the key is set
        self._key_status: str | None = None
        self._client_factory = client_factory or PolymarketUSClient
        self.live_requested = (
            settings.polydesk_mode == "live"
            and settings.polydesk_live_confirm == LIVE_CONFIRM_PHRASE
            and bool(settings.polymarket_us_key_id)
            and bool(settings.polymarket_us_secret_key)
        )
        self.state = load_state(self.path)
        self.state["rule"] = {
            "theta": self.theta,
            "hours": self.hours,
            "ticket_usd": self.ticket,
            "label": f"candidate rule: buy at >= {self.theta:.2f} within the last {self.hours:g} h when bid and ask "
            f"are within {MAX_SPREAD:.2f}, ${self.ticket:.0f} paper tickets. Lab 4 TRAIN (2026-10-09): NO EDGE in any "
            "cell after fees, so this rule never gets real money",
        }
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.state["mode"] = "paper"
        if bool(settings.polymarket_us_key_id) and bool(settings.polymarket_us_secret_key):
            self.reader = self._open_reader()
        if self.live_requested and self.state.get("live_halted"):
            self.state["live_status"] = (
                "Live was switched off by the total-loss cap; the desk stays on paper until the owner resets it."
            )
        elif self.live_requested:
            self._connect()
        elif settings.polydesk_mode == "live":
            self.state["live_status"] = (
                "Live requested but the confirm phrase or the key is missing: staying on paper."
            )
        else:
            self.state["live_status"] = None
        self._save()

    def _open_reader(self) -> PolymarketUSClient | None:
        """A read link to the venue (balances, positions) once the key is accepted, in paper mode too: the
        venue's book is the truth about real money. A rejected key leaves the reason for the panel."""
        try:
            client = self._client_factory(
                _reveal(self.settings.polymarket_us_key_id), _reveal(self.settings.polymarket_us_secret_key)
            )
            bal = client.balances()
        except (PolymarketUSError, ValueError) as exc:
            status = exc.status if isinstance(exc, PolymarketUSError) else "bad key format"
            self._key_status = (
                f"Polymarket rejected the API key ({status}): make a new key in the app and put it in "
                "Railway; staying on paper."
            )
            log.warning("polydesk_key_rejected status=%s", status)
            return None
        self.state["balance"] = {**bal, "at": time.time()}
        return client

    def _connect(self) -> None:
        """Live only after the venue accepts the key (a balance read); otherwise paper, with the reason."""
        if self.reader is None:
            self.client = None
            self.state["mode"] = "paper"
            self.state["live_status"] = self._key_status
            return
        bal = self.state["balance"]
        self.client = self.reader
        self.state["mode"] = "live"
        self.state["live_status"] = None
        log.info(
            "polydesk_live_connected cash=%.2f buying_power=%.2f",
            bal["cash"],
            bal["buying_power"],
        )
        self._receipt(
            "polydesk_live_connected",
            {"cash": bal["cash"], "buying_power": bal["buying_power"]},
        )

    def _receipt(self, kind: str, payload: dict[str, Any]) -> None:
        if self.ledger is None:
            return
        try:
            self.ledger.append_receipt(kind, payload)
        except Exception as exc:  # noqa: BLE001 (a receipt failure must not stop the desk)
            log.warning("polydesk_receipt_failed kind=%s error=%s", kind, type(exc).__name__)

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="polydesk", daemon=True)
        self._thread.start()
        log.info(
            "polydesk_started theta=%.2f hours=%g ticket_usd=%.0f poll_s=%g (%s)",
            self.theta,
            self.hours,
            self.ticket,
            self.poll_s,
            "LIVE: %g contract(s) per order" % self.contracts if self.state.get("mode") == "live" else "paper",
        )

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self._stop.wait(
            FIRST_POLL_DELAY_S
        )  # a bot built and closed within seconds (tests) never touches the network
        while not self._stop.is_set():
            t0 = time.time()
            try:
                self.poll(t0)
            except Exception as exc:  # noqa: BLE001 (a desk keeps going; the trading loop is unaffected)
                self.state["counters"]["errors"] += 1
                self.state["last_error"] = f"{type(exc).__name__}"
                self._save()
                log.warning("polydesk_poll_failed error=%s", type(exc).__name__)
            self._stop.wait(max(5.0, self.poll_s - (time.time() - t0)))

    def _save(self) -> None:
        save_state(self.path, self.state)

    def _event(self, ts: float, text: str, tone: str = "neutral") -> None:
        self.state["events"].insert(0, {"ts": ts, "text": text[:160], "tone": tone})
        del self.state["events"][EVENTS_KEEP:]

    # ------------------------------------------------------------------ one round
    def poll(self, now: float) -> dict[str, int]:
        st = self.state
        st["counters"]["polls"] += 1
        st["last_poll"] = now
        watch = open_markets(now)
        try:
            watch += live_sports_markets(now)
        except RuntimeError:
            st["counters"]["errors"] += 1
        quotes = self._quotes(watch)
        st["counters"]["quotes"] += len(quotes)
        adopted = self._reconcile(now, watch) if self.reader is not None else 0
        bought = self._apply_rule(now, watch, quotes)
        settled = self._settle(now, {m["slug"] for m in watch})
        if bought and st["mode"] == "live" and self.reader is not None:
            adopted += self._reconcile(now, watch)  # the venue summary after this round's real buys
        st["watched"] = len(watch)
        st["last_ok"] = now
        st["last_error"] = None
        if self.reader is not None:
            try:
                st["balance"] = {**self.reader.balances(), "at": now}
            except PolymarketUSError as exc:
                st["counters"]["errors"] += 1
                log.warning("polydesk_balance_failed status=%s", exc.status)
        self._save()
        return {
            "watched": len(watch),
            "quotes": len(quotes),
            "bought": bought,
            "settled": settled,
            "adopted": adopted,
        }

    def _reconcile(self, now: float, watch: list[dict[str, Any]]) -> int:
        """The venue's book is the truth for real money. Every contract it holds that this desk never recorded
        (an order reply that showed no fill, a buy from another place) is adopted as a live position, so it is
        counted against the caps, settled and shown. The venue summary is kept for the panel."""
        assert self.reader is not None
        st = self.state
        try:
            rows = self.reader.positions()
        except PolymarketUSError as exc:
            st["counters"]["errors"] += 1
            log.warning("polydesk_positions_failed status=%s", exc.status)
            return 0
        held = [r for r in rows if r["qty"] > 0 and not r["expired"] and r["slug"]]
        st["exchange"] = {
            "positions": len(held),
            "contracts": sum(r["qty"] for r in held),
            "cost_usd": sum(r["cost"] if r["cost"] > 0 else r["qty"] * r["avg_price"] for r in held),
            "value_usd": sum(r["value"] for r in held),
            "at": now,
        }
        by_slug = {m["slug"]: m for m in watch}
        adopted = 0
        for r in held:
            slug = r["slug"]
            pos = st["positions"].get(slug)
            if pos is not None and pos.get("live"):
                continue
            if pos is not None:  # a paper position on the same market: the real one takes the slot, no paper P&L
                st["closed"].insert(0, {**pos, "settled_at": now, "won": None, "unresolved": True, "replaced_by_real": True})
                del st["closed"][CLOSED_KEEP:]
            m = by_slug.get(slug)
            price = r["avg_price"] if r["avg_price"] > 0 else (r["cost"] / r["qty"] if r["cost"] > 0 else 0.0)
            cost = r["cost"] if r["cost"] > 0 else price * r["qty"]
            coef = m["fee_coef"] if m is not None and m.get("fee_coef") is not None else US_TAKER
            label = f"{r['title']} · {r['outcome']}" if r["outcome"] else r["title"]
            question = m["question"] if m is not None else (label or slug)
            st["positions"][slug] = {
                "slug": slug,
                "question": question,
                "category": m["category"] if m is not None else ("sports" if r["event_slug"] else "other"),
                "side": "long",
                "p_in": price,
                "shares": r["qty"],
                "fee_usd": r["qty"] * coef * price * (1.0 - price),
                "cost_usd": cost,
                "t_in": now,
                "end_ts": m["end_ts"] if m is not None else now + ADOPTED_END_GUESS_S,
                "event": m.get("event") if m is not None else None,
                "live": True,
                "adopted": True,
                "end_known": m is not None,
            }
            st["counters"]["bought"] += 1
            adopted += 1
            self._event(
                now,
                f"REAL position found at the venue: {question[:60]} · {r['qty']:g} contract at {price:.3f} "
                f"(${cost:.2f})",
                "good",
            )
            self._receipt(
                "polydesk_position_adopted",
                {"slug": slug, "contracts": r["qty"], "price": price, "cost_usd": cost},
            )
        if adopted:
            log.info("polydesk_adopted n=%d venue_contracts=%g", adopted, st["exchange"]["contracts"])
        return adopted

    def _fill_from_positions(self, slug: str, fill: dict[str, Any]) -> dict[str, Any]:
        """An order reply without executions is not the last word: the venue's book decides whether it filled."""
        assert self.client is not None
        try:
            rows = self.client.positions()
        except PolymarketUSError as exc:
            self.state["counters"]["errors"] += 1
            log.warning("polydesk_positions_failed status=%s", exc.status)
            return fill
        for r in rows:
            if r["slug"] == slug and r["qty"] > 0:
                price = r["avg_price"] if r["avg_price"] > 0 else (r["cost"] / r["qty"] if r["cost"] > 0 else 0.0)
                if price <= 0:
                    return fill
                return {**fill, "filled": r["qty"], "avg_price": price,
                        "cost": r["cost"] if r["cost"] > 0 else price * r["qty"], "via": "positions"}
        return fill

    def _quotes(
        self, watch: list[dict[str, Any]]
    ) -> dict[str, dict[str, float | None]]:
        def one(m: dict[str, Any]) -> tuple[str, dict[str, float | None]] | None:
            try:
                q = bbo(m["slug"])
            except RuntimeError:
                return None
            time.sleep(REQ_SLEEP_S)
            return m["slug"], q

        with ThreadPoolExecutor(max_workers=THREADS) as pool:
            return {
                slug: q
                for r in pool.map(one, watch)
                if r is not None
                for slug, q in [r]
            }

    def _apply_rule(
        self,
        now: float,
        watch: list[dict[str, Any]],
        quotes: dict[str, dict[str, float | None]],
    ) -> int:
        st = self.state
        bought = 0
        tried: set[str] = set(st.setdefault("tried", []))
        for m in watch:
            slug = m["slug"]
            if slug in st["positions"] or slug in tried:
                continue
            if m["category"] != "sports" and now < m["end_ts"] - self.hours * 3600.0:
                continue  # not yet inside the window (sports: the live list IS the window)
            q = quotes.get(slug)
            if not q:
                continue
            ask, bid = q.get("best_ask"), q.get("best_bid")
            # Both sides of the book must say "near-certain". A thin book quoting bid 0.14 / ask 0.69 has an ask
            # that can sit above theta while the market believes nothing of the kind; the paper desk bought such
            # quotes on 2026-10-09 and lost 60% of them. The lab's rule reads trade prints, which have no such gap.
            if ask is None or bid is None or ask - bid > MAX_SPREAD + 1e-9:
                continue
            side: str | None = None
            price = 0.0
            if ask is not None and ask >= self.theta:
                side, price = "long", float(ask)
            elif bid is not None and (1.0 - bid) >= self.theta:
                side, price = "short", float(1.0 - bid)
            if side is None:
                continue
            price = min(price, MAX_PRICE)
            coef = m["fee_coef"] if m.get("fee_coef") is not None else US_TAKER
            if st["mode"] == "live" and self.client is not None:
                if side != "long":
                    continue  # live: the YES side only (the venue prices every order on YES); shorts stay paper-only
                if not self._live_allows(now, price):
                    continue
                tried.add(slug)
                try:
                    fill = self.client.buy_long_ioc(slug, price, self.contracts)
                except PolymarketUSError as exc:
                    st["counters"]["errors"] += 1
                    self._event(now, f"Order rejected by the venue ({exc.status}): {m['question'][:50]}", "bad")
                    self._receipt("polydesk_order_rejected", {"slug": slug, "status": exc.status})
                    continue
                if fill["filled"] <= 0:
                    fill = self._fill_from_positions(slug, fill)
                if fill["filled"] <= 0:
                    self._event(now, f"No fill at {price:.3f}: {m['question'][:50]} (order cancelled)")
                    continue
                shares = float(fill["filled"])
                p_fill = float(fill["avg_price"])
                cost = float(fill["cost"])
                fee = shares * coef * p_fill * (1.0 - p_fill)
                st["positions"][slug] = {
                    "slug": slug,
                    "question": m["question"],
                    "category": m["category"],
                    "side": "long",
                    "p_in": p_fill,
                    "shares": shares,
                    "fee_usd": fee,
                    "cost_usd": cost,
                    "t_in": now,
                    "end_ts": m["end_ts"],
                    "event": m.get("event"),
                    "live": True,
                    "order_id": fill.get("id"),
                }
                st["counters"]["bought"] += 1
                bought += 1
                self._event(
                    now,
                    f"REAL buy: {m['question'][:60]} · {shares:g} contract at {p_fill:.3f} (${cost:.2f}, "
                    f"{m['category']})",
                    "good",
                )
                self._receipt(
                    "polydesk_order_filled",
                    {"slug": slug, "order_id": fill.get("id"), "contracts": shares, "price": p_fill, "cost_usd": cost},
                )
                continue
            shares = self.ticket / price
            fee = shares * coef * price * (1.0 - price)
            st["positions"][slug] = {
                "slug": slug,
                "question": m["question"],
                "category": m["category"],
                "side": side,
                "p_in": price,
                "shares": shares,
                "fee_usd": fee,
                "cost_usd": self.ticket,
                "t_in": now,
                "end_ts": m["end_ts"],
                "event": m.get("event"),
                "live": False,
            }
            tried.add(slug)
            st["counters"]["bought"] += 1
            bought += 1
            self._event(
                now,
                f"Paper buy: {m['question'][:60]} · {side} at {price:.3f} · ${self.ticket:.0f} "
                f"({m['category']})",
            )
        st["tried"] = sorted(tried)[-5000:]
        return bought

    # ------------------------------------------------------------------ live caps
    def _live_allows(self, now: float, price: float) -> bool:
        st = self.state
        s = self.settings
        open_usd = sum(float(p.get("cost_usd") or 0.0) for p in st["positions"].values() if p.get("live"))
        if open_usd + price * self.contracts > float(s.polydesk_live_max_open_usd):
            return False
        day = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")
        day_pnl = float((st.get("live_days") or {}).get(day, {}).get("pnl_usd") or 0.0)
        if day_pnl <= -float(s.polydesk_live_daily_loss_usd):
            note = "Daily loss cap reached: no more real buys today."
            if st.get("live_status") != note:
                st["live_status"] = note
                self._event(now, note, "bad")
            return False
        return True

    def _check_total_loss(self, now: float) -> None:
        st = self.state
        total = float(st.get("live_pnl_total_usd") or 0.0)
        if total <= -float(self.settings.polydesk_live_total_loss_usd) and st["mode"] == "live":
            st["mode"] = "paper"
            st["live_halted"] = True
            st["live_status"] = (
                f"Total loss cap reached ({total:+.2f} $): the desk switched itself back to paper for good; "
                "only the owner can switch it live again."
            )
            self.client = None
            self._event(now, "Total loss cap reached: real trading stopped, back to paper.", "bad")
            self._receipt("polydesk_live_halted", {"live_pnl_total_usd": total})
            log.warning("polydesk_live_halted total=%.2f", total)

    def _settle(self, now: float, watched: set[str]) -> int:
        st = self.state
        settled = 0
        for slug, pos in list(st["positions"].items()):
            if slug in watched and now < pos["end_ts"]:
                continue
            if pos["category"] != "sports" and now < pos["end_ts"]:
                continue
            try:
                value = settlement(slug)
            except RuntimeError:
                continue
            if value is None:
                if (
                    now > pos["end_ts"] + 7 * 86400
                ):  # never settled in a week: drop it as unresolved (no P&L)
                    pos["pnl_usd"] = None
                    st["closed"].insert(
                        0, {**pos, "settled_at": now, "won": None, "unresolved": True}
                    )
                    del st["positions"][slug]
                continue
            payout = pos["shares"] * (value if pos["side"] == "long" else 1.0 - value)
            pnl = payout - pos["fee_usd"] - float(pos.get("cost_usd", self.ticket))
            won = pnl > 0
            day = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")
            d = st["days"].setdefault(day, {"pnl_usd": 0.0, "settled": 0, "won": 0})
            d["pnl_usd"] += pnl
            d["settled"] += 1
            d["won"] += int(won)
            st["closed"].insert(
                0,
                {**pos, "settled_at": now, "value": value, "pnl_usd": pnl, "won": won},
            )
            del st["closed"][CLOSED_KEEP:]
            del st["positions"][slug]
            st["counters"]["settled"] += 1
            st["counters"]["won"] += int(won)
            settled += 1
            word = "real" if pos.get("live") else "paper"
            self._event(
                now,
                f"Settled: {pos['question'][:60]} · {'won' if won else 'lost'} {pnl:+.2f} $ ({word})",
                "good" if won else "bad",
            )
            if pos.get("live"):
                d_live = st.setdefault("live_days", {}).setdefault(day, {"pnl_usd": 0.0, "settled": 0, "won": 0})
                d_live["pnl_usd"] += pnl
                d_live["settled"] = int(d_live.get("settled") or 0) + 1
                d_live["won"] = int(d_live.get("won") or 0) + int(won)
                st["live_pnl_total_usd"] = float(st.get("live_pnl_total_usd") or 0.0) + pnl
                self._receipt(
                    "polydesk_settled",
                    {"slug": slug, "value": value, "pnl_usd": pnl, "contracts": pos["shares"]},
                )
                self._check_total_loss(now)
            time.sleep(REQ_SLEEP_S)
        return settled


# ---------------------------------------------------------------------- the panel's view
def panel_state(settings: Settings, now: float) -> dict[str, Any]:
    """What the team room shows for this desk (reads the state file only). Paper and real money are
    tallied apart (``paper`` / ``real``: open positions, money at risk, today's and all-time results), so
    paper positions left over from before a switch to live are never shown as real ones. The top-level
    ``open``/``today``/``*_total`` keys are the combined book."""
    st = load_state(state_path(settings))
    enabled = bool(settings.polydesk_enabled)
    today = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")
    day = st["days"].get(today, {"pnl_usd": 0.0, "settled": 0, "won": 0})
    total = sum(float(d.get("pnl_usd") or 0.0) for d in st["days"].values())
    c = st["counters"]
    open_n = len(st["positions"])
    live = st.get("mode") == "live"
    live_days = st.get("live_days") or {}
    live_day = live_days.get(today) or {}
    real_open = [p for p in st["positions"].values() if p.get("live")]
    real_settled = sum(int(d.get("settled") or 0) for d in live_days.values())
    real_won = sum(int(d.get("won") or 0) for d in live_days.values())
    real_total = float(st.get("live_pnl_total_usd") or 0.0)
    real_today = {
        "pnl_usd": float(live_day.get("pnl_usd") or 0.0),
        "settled": int(live_day.get("settled") or 0),
        "won": int(live_day.get("won") or 0),
    }
    real: dict[str, Any] = {
        "open": len(real_open),
        "at_risk_usd": sum(float(p.get("cost_usd") or 0.0) for p in real_open),
        "settled_total": real_settled,
        "won_total": real_won,
        "pnl_total_usd": real_total,
        "today": real_today,
    }
    paper: dict[str, Any] = {
        "open": open_n - len(real_open),
        "settled_total": int(c.get("settled") or 0) - real_settled,
        "won_total": int(c.get("won") or 0) - real_won,
        "pnl_total_usd": total - real_total,
        "today": {
            "pnl_usd": float(day["pnl_usd"]) - real_today["pnl_usd"],
            "settled": int(day["settled"]) - real_today["settled"],
            "won": int(day["won"]) - real_today["won"],
        },
    }
    return {
        "enabled": enabled,
        "mode": "live" if live else "paper",
        "label": "Real money" if live else "Paper money (pretend)",
        "balance": st.get("balance"),
        "live_status": st.get("live_status"),
        "live_pnl_total_usd": real_total,
        "real": real,
        "paper": paper,
        "exchange": st.get("exchange"),
        "rule": st.get("rule"),
        "last_poll": st.get("last_poll"),
        "last_ok": st.get("last_ok"),
        "last_error": st.get("last_error"),
        "watched": int(st.get("watched") or 0),
        "open": open_n,
        "settled_total": int(c.get("settled") or 0),
        "won_total": int(c.get("won") or 0),
        "pnl_total_usd": total,
        "today": {
            "pnl_usd": float(day["pnl_usd"]),
            "settled": int(day["settled"]),
            "won": int(day["won"]),
        },
        "positions": [
            {
                "question": p["question"],
                "side": p["side"],
                "p_in": p["p_in"],
                "category": p["category"],
                "t_in": p["t_in"],
                "live": bool(p.get("live")),
                "cost_usd": float(p.get("cost_usd") or 0.0),
            }
            for p in sorted(st["positions"].values(), key=lambda p: -p["t_in"])[:10]
        ],
        "events": st.get("events", [])[:EVENTS_KEEP],
        "polls": int(c.get("polls") or 0),
    }
