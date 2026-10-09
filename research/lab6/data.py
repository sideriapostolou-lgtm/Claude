"""Lab 6 data: Pinnacle's historical moneyline odds (The Odds API, the owner's paid key) for the Polymarket sports
games lab 4 cached, under a hard credit budget. Research only; the live bot never reads this.

Sources:

* The Odds API ``GET /v4/historical/sports/{sport}/odds/?regions=eu&markets=h2h&bookmakers=pinnacle&date=<ISO>``:
  the snapshot at or before ``date`` of every listed event of one sport key (``timestamp``, ``data[]`` with
  ``id``, ``commence_time``, ``home_team``, ``away_team``, ``bookmakers[].markets[].outcomes[]`` in decimal odds).
  10 credits a call. ``GET /v4/sports/`` is free. The key is read from the environment variable
  ``ODDS_API_KEY`` at run time and is never logged, cached, or written anywhere: URLs are never printed, and every
  error text has the key replaced by ``***`` before it is shown.
* Gamma ``GET https://gamma-api.polymarket.com/markets?id=..&closed=true`` (public, keyless): each candidate
  market's ``gameStartTime`` (the scheduled start) and ``sportsMarketType``.
* Lab 4's cache (``$LAB4_DATA``, default ``<scratchpad>/lab4``): ``markets.parquet`` and ``trades/<id>.parquet``.

Credit ledger: ``<scratchpad>/lab6/credits.json`` (``$LAB6_LEDGER``) keeps the running spend from the
``x-requests-last`` header of every response plus the ``x-requests-used`` / ``x-requests-remaining`` the API
reports. A call is refused BEFORE it is sent when the spend plus its cost would pass :data:`CREDIT_CAP`.

Response cache: ``research/lab6/data/cache/`` (``$LAB6_CACHE``; gitignored, rebuildable): one JSON file per
(sport, requested time) holding the response body only. A cached request is never sent again.

Layout of the committed, derived files (``research/lab6/data/``): ``gamma_meta.parquet`` (start times),
``plan.parquet`` (the snapshot schedule), ``pinnacle.parquet`` (one row per event per snapshot), ``manifest.json``.

Rebuild (the key stays in the environment, never on a command line or in a file in the repo)::

    export ODDS_API_KEY=$(cat <path to the key file>)
    python research/lab6/data.py --gamma           # start times for the candidate markets (keyless)
    python research/lab6/data.py --plan            # the snapshot schedule and its credit cost
    python research/lab6/data.py --fetch           # fetch the schedule (cache-first, ledger-capped)
    python research/lab6/data.py --build           # pinnacle.parquet from the cache
    python research/lab6/data.py --status
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

import core as C

API_ODDS = "https://api.the-odds-api.com/v4"
API_GAMMA = "https://gamma-api.polymarket.com"
SCRATCH = Path(
    os.environ.get(
        "CLAUDE_SCRATCHPAD",
        "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad",
    )
)
LAB4_DATA = Path(os.environ.get("LAB4_DATA", str(SCRATCH / "lab4")))
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
CACHE = Path(os.environ.get("LAB6_CACHE", str(DATA / "cache")))
LEDGER = Path(os.environ.get("LAB6_LEDGER", str(SCRATCH / "lab6" / "credits.json")))
KEY_ENV = "ODDS_API_KEY"
CREDIT_CAP = 300_000  # the lab's hard budget
COST = {"odds": 10, "sports": 0}
GRID_S = 300  # historical snapshots are 5 minutes apart
UA = {"User-Agent": "nightcrawler-research/lab6"}

# PLAN §2: snapshot offsets before each scheduled start (minutes). A request for offset o may sit anywhere in
# [start - o - before, start - o + after] (minutes) so games of one sport share snapshots; the closing request
# (o = 1) sits in the last five minutes before the start, every other one inside its entry window.
OFFSETS_MIN: tuple[int, ...] = (1440, 360, 180, 60, 30, 10, 1)
CLOSE_OFFSETS: tuple[int, ...] = (1,)
WINDOW_MIN: dict[int, tuple[int, int]] = {
    1440: (0, 180), 360: (0, 90), 180: (0, 45), 60: (0, 15), 30: (0, 10), 10: (0, 5), 1: (4, 0),
}


class BudgetExceeded(RuntimeError):
    """The next call would take the lab past its credit cap."""


def redact(text: Any, key: str | None) -> str:
    s = str(text)
    return s.replace(key, "***") if key else s


# --- credit ledger ---------------------------------------------------------------------------------------------------


class Ledger:
    """Running credit spend of this lab, shared by every process through a file lock."""

    def __init__(self, path: Path = LEDGER, cap: int = CREDIT_CAP) -> None:
        self.path = Path(path)
        self.cap = int(cap)

    @contextlib.contextmanager
    def _locked(self) -> Iterator[dict[str, Any]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(".lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            doc = self._read()
            yield doc
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
            os.replace(tmp, self.path)
            fcntl.flock(lock, fcntl.LOCK_UN)

    def _read(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                doc = json.loads(self.path.read_text())
            except ValueError:
                doc = {}
        else:
            doc = {}
        doc["cap"] = self.cap  # the current cap, not the one the file was created with
        doc.setdefault("spent", 0)
        doc.setdefault("calls", 0)
        doc.setdefault("by_kind", {})
        doc.setdefault("log", [])
        return doc

    def status(self) -> dict[str, Any]:
        doc = self._read()
        return {k: doc.get(k) for k in ("cap", "spent", "calls", "by_kind", "api_used", "api_remaining",
                                        "api_used_first_seen")}

    def reserve(self, cost: int) -> None:
        """Refuse a call whose cost would take the spend past the cap (checked before the request is sent)."""
        doc = self._read()
        if int(doc["spent"]) + int(cost) > self.cap:
            raise BudgetExceeded(
                f"lab 6 credit cap: spent {doc['spent']} + {cost} would pass {self.cap}"
            )

    def record(self, kind: str, sport: str, requested: str, status: int, headers: dict[str, str]) -> int:
        last = _int(headers.get("x-requests-last"))
        used = _int(headers.get("x-requests-used"))
        remaining = _int(headers.get("x-requests-remaining"))
        with self._locked() as doc:
            spent = int(last or 0)
            doc["spent"] = int(doc["spent"]) + spent
            doc["calls"] = int(doc["calls"]) + 1
            bk = doc["by_kind"].setdefault(kind, {"calls": 0, "credits": 0})
            bk["calls"] += 1
            bk["credits"] += spent
            if used is not None:
                doc.setdefault("api_used_first_seen", used - spent)
                doc["api_used"] = used
            if remaining is not None:
                doc["api_remaining"] = remaining
            doc["log"].append({"utc": datetime.now(UTC).isoformat(timespec="seconds"), "kind": kind,
                               "sport": sport, "date": requested, "status": status, "cost": spent})
            doc["log"] = doc["log"][-5000:]
            return int(doc["spent"])


def _int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# --- The Odds API client -------------------------------------------------------------------------------------------


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def cache_path(sport: str, ts: float, cache: Path = CACHE) -> Path:
    return cache / "odds" / sport / f"{datetime.fromtimestamp(ts, UTC):%Y%m%dT%H%M%SZ}.json"


class OddsClient:
    """Cache-first, ledger-capped client. ``session`` is injectable for tests (any object with ``.get``)."""

    def __init__(
        self,
        key: str | None = None,
        ledger: Ledger | None = None,
        cache: Path = CACHE,
        session: Any = None,
        sleep_s: float = 0.15,
    ) -> None:
        self.key = key if key is not None else os.environ.get(KEY_ENV)
        self.ledger = ledger or Ledger()
        self.cache = Path(cache)
        self.session = session or requests.Session()
        self.sleep_s = sleep_s

    def _get(self, path: str, params: dict[str, Any], kind: str, sport: str, requested: str,
             tries: int = 6) -> tuple[int, Any]:
        if not self.key:
            raise RuntimeError(f"set {KEY_ENV} in the environment (never on the command line)")
        self.ledger.reserve(COST.get(kind, 10))
        last = "no response"
        for attempt in range(tries):
            try:
                r = self.session.get(f"{API_ODDS}{path}", params={**params, "apiKey": self.key},
                                     headers=UA, timeout=60)
            except requests.RequestException as e:  # the message can carry the URL: redact
                last = redact(repr(e), self.key)
                time.sleep(2.0 * (attempt + 1))
                continue
            headers = {k.lower(): v for k, v in r.headers.items()}
            self.ledger.record(kind, sport, requested, r.status_code, headers)
            if r.status_code == 429:
                last = "HTTP 429"
                time.sleep(5.0 * (attempt + 1))
                self.ledger.reserve(COST.get(kind, 10))
                continue
            if r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                time.sleep(3.0 * (attempt + 1))
                self.ledger.reserve(COST.get(kind, 10))
                continue
            try:
                body = r.json()
            except ValueError:
                body = None
            return r.status_code, body
        raise RuntimeError(f"Odds API {kind} {sport} {requested} failed after {tries} tries: {last}")

    def sports(self) -> list[dict[str, Any]]:
        status, body = self._get("/sports/", {"all": "true"}, "sports", "-", "-")
        return body if status == 200 and isinstance(body, list) else []

    def historical_odds(self, sport: str, ts: float) -> dict[str, Any] | None:
        """The Pinnacle h2h snapshot of ``sport`` at or before ``ts`` (cache-first). None on a 4xx (e.g. a sport
        key with no history); the negative answer is cached too so it is never paid for twice."""
        path = cache_path(sport, ts, self.cache)
        if path.exists():
            doc = json.loads(path.read_text())
            return doc.get("response") if doc.get("status") == 200 else None
        params = {"regions": "eu", "markets": "h2h", "bookmakers": "pinnacle", "oddsFormat": "decimal",
                  "dateFormat": "iso", "date": iso(ts)}
        status, body = self._get(f"/historical/sports/{sport}/odds/", params, "odds", sport, iso(ts))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"sport": sport, "requested": iso(ts), "status": status,
                                   "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                                   "response": body if status == 200 else None,
                                   "error": None if status == 200 else redact(body, self.key)}))
        os.replace(tmp, path)
        time.sleep(self.sleep_s)
        return body if status == 200 else None


# --- Gamma metadata (keyless) --------------------------------------------------------------------------------------


def _gamma_get(params: list[tuple[str, Any]], tries: int = 6) -> list[dict[str, Any]]:
    last = "no response"
    for attempt in range(tries):
        try:
            r = requests.get(f"{API_GAMMA}/markets", params=params, headers=UA, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                time.sleep(3.0 * (attempt + 1))
                continue
            if r.status_code != 200:
                return []
            body = r.json()
            return body if isinstance(body, list) else []
        except (requests.RequestException, ValueError) as e:
            last = repr(e)
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"Gamma failed: {last}")


def parse_time(value: Any) -> float | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace(" ", "T", 1)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    elif len(text) >= 3 and text[-3] in "+-" and text[-2:].isdigit():
        text += ":00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def fetch_gamma_meta(ids: list[str], out: Path = DATA / "gamma_meta.parquet", chunk: int = 50) -> pd.DataFrame:
    """``gameStartTime`` and ``sportsMarketType`` per market id (resumable: ids already saved are skipped)."""
    have = pd.read_parquet(out) if out.exists() else pd.DataFrame(
        columns=["id", "game_start", "sports_market_type", "slug"])
    todo = [i for i in dict.fromkeys(ids) if i not in set(have["id"].astype(str))]
    rows: list[dict[str, Any]] = []
    for k in range(0, len(todo), chunk):
        part = todo[k:k + chunk]
        got = _gamma_get([("closed", "true"), ("limit", len(part))] + [("id", i) for i in part])
        seen = set()
        for m in got:
            seen.add(str(m.get("id")))
            rows.append({"id": str(m.get("id")), "game_start": parse_time(m.get("gameStartTime")),
                         "sports_market_type": m.get("sportsMarketType"), "slug": m.get("slug")})
        for i in part:
            if i not in seen:
                rows.append({"id": i, "game_start": None, "sports_market_type": None, "slug": None})
        if (k // chunk) % 20 == 0:
            print(f"  gamma {k + len(part)}/{len(todo)}", flush=True)
        time.sleep(0.2)
    df = pd.concat([have, pd.DataFrame(rows)], ignore_index=True).drop_duplicates("id", keep="last")
    df["game_start"] = pd.to_numeric(df["game_start"], errors="coerce")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return df


def lab4_markets(lab4: Path = LAB4_DATA) -> pd.DataFrame:
    return pd.read_parquet(lab4 / "markets.parquet")


def candidate_games(lab4: Path = LAB4_DATA, meta_path: Path = DATA / "gamma_meta.parquet") -> tuple[pd.DataFrame, pd.DataFrame]:
    meta = pd.read_parquet(meta_path) if meta_path.exists() else None
    return C.build_games(lab4_markets(lab4), meta)


def load_tape(market_id: str, lab4: Path = LAB4_DATA) -> pd.DataFrame | None:
    path = lab4 / "trades" / f"{market_id}.parquet"
    if not path.exists():
        return None
    t = pd.read_parquet(path, columns=["ts", "price", "size", "side", "outcome_index"])
    return t[(t["ts"] > 0) & (t["price"] > 0) & (t["price"] < 1) & t["outcome_index"].isin([0, 1])]


def pregame_prints(games: pd.DataFrame, sides: pd.DataFrame, window_s: float = 86400.0,
                   lab4: Path = LAB4_DATA) -> pd.DataFrame:
    """Per game: whether every market has a tape, and the number of prints (any market, any side) in the
    ``window_s`` before Polymarket's scheduled start. Reads tapes only (no prices are compared to anything)."""
    markets = sides.drop_duplicates("market_id")[["game_id", "market_id"]]
    start = games.set_index("game_id")["game_start"]
    rows: dict[str, dict[str, Any]] = {}
    for gid, g in markets.groupby("game_id"):
        s = float(start.get(gid, float("nan")))
        n, tapes = 0, 0
        for mid in g["market_id"]:
            t = load_tape(str(mid), lab4)
            if t is None:
                continue
            tapes += 1
            if s == s:
                n += int(((t["ts"] >= s - window_s) & (t["ts"] < s)).sum())
        rows[str(gid)] = {"game_id": gid, "tapes": tapes, "markets": len(g), "prints_24h": n}
    return pd.DataFrame(list(rows.values()))


# --- the snapshot schedule (PLAN §2) -------------------------------------------------------------------------------


def plan_snapshots(
    games: pd.DataFrame,
    offsets_min: tuple[int, ...] = OFFSETS_MIN,
    window_min: dict[int, tuple[int, int]] | None = None,
) -> pd.DataFrame:
    """The fewest request times per sport key such that, for every covered game start ``c`` and every offset
    ``o``, one request falls in ``[c - o - before(o), c - o + after(o)]`` (greedy interval stabbing: sort by right
    end, request at the right end, rounded down to the 5-minute grid when that stays inside the interval). A
    request returns the snapshot at or before it, and every interval ends before the start, so every snapshot is
    from before the game. Games without a start time are skipped."""
    window_min = window_min or WINDOW_MIN
    rows: list[dict[str, Any]] = []
    for g in games.itertuples(index=False):
        if pd.isna(g.game_start):
            continue
        for key in json.loads(g.sport_keys):
            rows.append({"sport_key": key, "start": float(g.game_start) // 60 * 60})
    if not rows:
        return pd.DataFrame(columns=["sport_key", "request_ts", "n_intervals"])
    starts = pd.DataFrame(rows).drop_duplicates()
    out: list[dict[str, Any]] = []
    for key, g in starts.groupby("sport_key"):
        ivs = sorted(
            (
                (c - (o + window_min.get(o, (0, 0))[0]) * 60, c - (o - window_min.get(o, (0, 0))[1]) * 60)
                for c in g["start"]
                for o in offsets_min
            ),
            key=lambda iv: iv[1],
        )
        point: float | None = None
        count = 0
        for lo, hi in ivs:
            if point is not None and lo <= point <= hi:
                count += 1
                continue
            if point is not None:
                out.append({"sport_key": key, "request_ts": point, "n_intervals": count})
            snapped = hi // GRID_S * GRID_S
            point = snapped if snapped >= lo else hi
            count = 1
        if point is not None:
            out.append({"sport_key": key, "request_ts": point, "n_intervals": count})
    return pd.DataFrame(out).sort_values(["request_ts", "sport_key"]).reset_index(drop=True)


def fetch_plan(plan: pd.DataFrame, client: OddsClient, max_credits: int | None = None,
               order: str = "time") -> dict[str, Any]:
    """Fetch every planned snapshot (cache-first). Stops cleanly at the lab cap or at ``max_credits`` spent in
    this run."""
    done = cached = failed = 0
    rows = plan if order == "time" else plan.sample(frac=1.0, random_state=0)
    t0 = time.time()
    for i, r in enumerate(rows.itertuples(index=False), 1):
        if cache_path(r.sport_key, r.request_ts, client.cache).exists():
            cached += 1
            continue
        if max_credits is not None and (done + 1) * COST["odds"] > max_credits:  # this worker's own calls
            print(f"  stop: this run's limit of {max_credits} credits", flush=True)
            break
        try:
            body = client.historical_odds(r.sport_key, r.request_ts)
        except BudgetExceeded as e:
            print(f"  stop: {e}", flush=True)
            break
        done += 1
        failed += body is None
        if done % 100 == 0:
            st = client.ledger.status()
            print(f"  {i}/{len(rows)} fetched {done} (cached {cached}, 4xx {failed}); lab spend {st['spent']}; "
                  f"{time.time() - t0:.0f}s", flush=True)
    st = client.ledger.status()
    return {"fetched": done, "cached": cached, "http_4xx": failed, "lab_spent": st["spent"]}


# --- the derived table -----------------------------------------------------------------------------------------------


PIN_COLS = ["sport_key", "requested", "snap_ts", "event_id", "commence", "home", "away", "last_update", "names",
            "prices"]


def parse_snapshot(sport: str, requested: float, body: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows of one historical response: one per event that has a Pinnacle h2h market. ``snap_ts`` is the
    snapshot's own timestamp (at or before the requested time)."""
    snap = parse_time(body.get("timestamp"))
    rows: list[dict[str, Any]] = []
    for ev in body.get("data") or []:
        for bk in ev.get("bookmakers") or []:
            if bk.get("key") != "pinnacle":
                continue
            for mk in bk.get("markets") or []:
                if mk.get("key") != "h2h":
                    continue
                outs = mk.get("outcomes") or []
                rows.append({
                    "sport_key": sport,
                    "requested": requested,
                    "snap_ts": snap,
                    "event_id": str(ev.get("id")),
                    "commence": parse_time(ev.get("commence_time")),
                    "home": ev.get("home_team"),
                    "away": ev.get("away_team"),
                    "last_update": parse_time(mk.get("last_update") or bk.get("last_update")),
                    "names": json.dumps([o.get("name") for o in outs]),
                    "prices": json.dumps([float(o.get("price") or 0.0) for o in outs]),
                })
    return rows


def build_pinnacle(cache: Path = CACHE, out: Path = DATA / "pinnacle.parquet") -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in sorted((cache / "odds").glob("*/*.json")):
        doc = json.loads(path.read_text())
        if doc.get("status") != 200 or not isinstance(doc.get("response"), dict):
            continue
        req = parse_time(doc.get("requested"))
        rows.extend(parse_snapshot(doc["sport"], req or 0.0, doc["response"]))
    df = pd.DataFrame(rows, columns=PIN_COLS)
    df = df.drop_duplicates(["event_id", "snap_ts"]).sort_values(["sport_key", "event_id", "snap_ts"])
    df = df[df["snap_ts"] < df["commence"]].reset_index(drop=True)  # pre-game lines only
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return df


def events_table(pin: pd.DataFrame) -> pd.DataFrame:
    """One row per (sport_key, event_id): teams and the commence time of the LAST pre-game snapshot."""
    if pin.empty:
        return pd.DataFrame(columns=["sport_key", "event_id", "home", "away", "commence"])
    last = pin.sort_values("snap_ts").groupby("event_id", sort=False).tail(1)
    return last[["sport_key", "event_id", "home", "away", "commence"]].reset_index(drop=True)


def active_games(games: pd.DataFrame, pre: pd.DataFrame) -> pd.DataFrame:
    """Covered games with a scheduled start, a tape for every market and at least one print in the 24 h before
    the start: the only games worth a snapshot."""
    g = games[games["sport_keys"] != "[]"].merge(pre, on="game_id", how="left")
    keep = g["game_start"].notna() & (g["tapes"] == g["markets"]) & (g["prints_24h"] > 0)
    return g[keep].reset_index(drop=True)


def match_all(games: pd.DataFrame, pin: pd.DataFrame) -> C.MatchResult:
    return C.match_games(games, events_table(pin))


def _print_plan(name: str, plan: pd.DataFrame) -> None:
    print(plan.groupby("sport_key").size().sort_values(ascending=False).head(40).to_string())
    print(f"{name}: {len(plan)} requests, {len(plan) * COST['odds']:,} credits", flush=True)


def main(argv: list[str] | None = None) -> int:
    """Stages (PLAN §2): --gamma, --pregame, --plan-close, --pilot, --fetch close, --build, --match,
    --plan-full, --fetch full, --build, --match."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--gamma", action="store_true", help="fetch Gamma start times for the candidate markets")
    ap.add_argument("--pregame", action="store_true", help="count each game's pre-start prints (tapes only)")
    ap.add_argument("--plan-close", action="store_true", help="closing snapshots for every active game")
    ap.add_argument("--pilot", action="store_true", help="fetch the busiest closing snapshot of each sport key")
    ap.add_argument("--plan-full", action="store_true", help="the other offsets, for matched games only")
    ap.add_argument("--fetch", choices=["close", "full"], default=None, help="fetch a planned schedule")
    ap.add_argument("--max-credits", type=int, default=None, help="stop this run after this many credits")
    ap.add_argument("--sports", nargs="*", default=None, help="restrict --fetch to these sport keys")
    ap.add_argument("--build", action="store_true", help="write pinnacle.parquet from the cache")
    ap.add_argument("--match", action="store_true", help="match games to Pinnacle events")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)
    did = False
    if a.gamma:
        did = True
        sp = lab4_markets()
        sp = sp[sp["fee_type"].fillna("").str.startswith("sports")]
        games, sides = C.build_games(sp, None)
        covered = games[games["sport_keys"] != "[]"]["game_id"]
        ids = sides[sides["game_id"].isin(covered)]["market_id"].astype(str).unique().tolist()
        print(f"gamma: {len(ids)} candidate markets in {len(covered)} covered games", flush=True)
        fetch_gamma_meta(ids)
    if a.pregame:
        did = True
        games, sides = candidate_games()
        pre = pregame_prints(games[games["sport_keys"] != "[]"], sides)
        pre.to_parquet(DATA / "pregame.parquet", index=False)
        print(f"pregame: {len(pre)} covered games, {(pre['prints_24h'] > 0).sum()} with prints", flush=True)
    if a.plan_close:
        did = True
        games, _ = candidate_games()
        act = active_games(games, pd.read_parquet(DATA / "pregame.parquet"))
        plan = plan_snapshots(act, CLOSE_OFFSETS)
        plan.to_parquet(DATA / "plan_close.parquet", index=False)
        _print_plan("plan_close", plan)
    if a.pilot:
        did = True
        plan = pd.read_parquet(DATA / "plan_close.parquet")
        best = plan.sort_values("n_intervals", ascending=False).groupby("sport_key").head(1)
        print(json.dumps(fetch_plan(best, OddsClient(), max_credits=a.max_credits)), flush=True)
    if a.fetch:
        did = True
        plan = pd.read_parquet(DATA / f"plan_{a.fetch}.parquet")
        if a.sports:
            plan = plan[plan["sport_key"].isin(a.sports)]
        print(json.dumps(fetch_plan(plan, OddsClient(), max_credits=a.max_credits)), flush=True)
    if a.build:
        did = True
        pin = build_pinnacle()
        print(f"pinnacle.parquet: {len(pin)} rows, {pin['event_id'].nunique()} events, "
              f"{pin['snap_ts'].nunique()} snapshots", flush=True)
    if a.match:
        did = True
        games, _ = candidate_games()
        act = active_games(games, pd.read_parquet(DATA / "pregame.parquet"))
        res = match_all(act, pd.read_parquet(DATA / "pinnacle.parquet"))
        res.games.to_parquet(DATA / "matches.parquet", index=False)
        res.failures.to_parquet(DATA / "match_failures.parquet", index=False)
        print(f"match: {len(res.games)} of {len(act)} active games matched; failures by reason:")
        print(res.failures["reason"].value_counts().to_string(), flush=True)
    if a.plan_full:
        did = True
        games, _ = candidate_games()
        act = active_games(games, pd.read_parquet(DATA / "pregame.parquet"))
        matched = pd.read_parquet(DATA / "matches.parquet")
        sub = act.merge(matched[["game_id", "sport_key"]], on="game_id")
        sub["sport_keys"] = [json.dumps([k]) for k in sub["sport_key"]]
        plan = plan_snapshots(sub, tuple(o for o in OFFSETS_MIN if o not in CLOSE_OFFSETS))
        plan.to_parquet(DATA / "plan_full.parquet", index=False)
        _print_plan("plan_full", plan)
    if a.status or not did:
        print(json.dumps(Ledger().status(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
