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

State lives in ``DATA_DIR/polydesk/state.json`` (atomic rewrite): open positions, the last closed positions,
daily P&L, counters, the last poll. The team-room panel (:func:`panel_state`) reads that file; nothing here
touches the ledger, the wallet, a key or an order. The rule is a CANDIDATE: it earns a real seat only by passing
lab 4's TRAIN / VAL / TEST, and the page says "paper" everywhere this desk's numbers appear.
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

from nightcrawler.config import Settings

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
US_TAKER = 0.0695
CLOSED_KEEP = 200
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
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
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


class PolyDesk:
    """The paper desk's runtime (one daemon thread). ``poll(now)`` is also callable directly (tests)."""

    def __init__(self, settings: Settings, path: Path | None = None) -> None:
        self.settings = settings
        self.path = path or state_path(settings)
        self.theta = float(settings.polydesk_theta)
        self.hours = float(settings.polydesk_hours)
        self.ticket = float(settings.polydesk_ticket_usd)
        self.poll_s = float(settings.polydesk_poll_s)
        self.state = load_state(self.path)
        self.state["rule"] = {
            "theta": self.theta,
            "hours": self.hours,
            "ticket_usd": self.ticket,
            "label": f"candidate rule: buy at >= {self.theta:.2f} within the last {self.hours:g} h, "
            f"${self.ticket:.0f} paper tickets (not yet passed the lab)",
        }
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="polydesk", daemon=True)
        self._thread.start()
        log.info(
            "polydesk_started theta=%.2f hours=%g ticket_usd=%.0f poll_s=%g (paper)",
            self.theta,
            self.hours,
            self.ticket,
            self.poll_s,
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
        bought = self._apply_rule(now, watch, quotes)
        settled = self._settle(now, {m["slug"] for m in watch})
        st["watched"] = len(watch)
        st["last_ok"] = now
        st["last_error"] = None
        self._save()
        return {
            "watched": len(watch),
            "quotes": len(quotes),
            "bought": bought,
            "settled": settled,
        }

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
                "t_in": now,
                "end_ts": m["end_ts"],
                "event": m.get("event"),
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
            pnl = payout - pos["fee_usd"] - self.ticket
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
            self._event(
                now,
                f"Settled: {pos['question'][:60]} · {'won' if won else 'lost'} {pnl:+.2f} $ (paper)",
                "good" if won else "bad",
            )
            time.sleep(REQ_SLEEP_S)
        return settled


# ---------------------------------------------------------------------- the panel's view
def panel_state(settings: Settings, now: float) -> dict[str, Any]:
    """What the team room shows for this desk (reads the state file only)."""
    st = load_state(state_path(settings))
    enabled = bool(settings.polydesk_enabled)
    today = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")
    day = st["days"].get(today, {"pnl_usd": 0.0, "settled": 0, "won": 0})
    total = sum(float(d.get("pnl_usd") or 0.0) for d in st["days"].values())
    c = st["counters"]
    open_n = len(st["positions"])
    return {
        "enabled": enabled,
        "label": "Paper money (pretend)",
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
            }
            for p in sorted(st["positions"].values(), key=lambda p: -p["t_in"])[:10]
        ],
        "events": st.get("events", [])[:EVENTS_KEEP],
        "polls": int(c.get("polls") or 0),
    }
