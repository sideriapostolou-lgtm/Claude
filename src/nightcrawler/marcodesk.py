"""Marco's loves desk: a PAPER desk that copies only the picks "Million Dollar Marco" Piemonte says he LOVES (All In
Sports podcast, YouTube @Cousins_AllIn) onto Polymarket US, with pretend money, so the owner can see whether his loves
make money before any real dollar follows them.

PAPER ONLY. This module has no venue client, no key and no order path: it reads the venue's PUBLIC gateway through the
Polymarket desk's own helpers (:func:`nightcrawler.polydesk._get`, :func:`~nightcrawler.polydesk.bbo`,
:func:`~nightcrawler.polydesk.settlement`, :func:`~nightcrawler.polydesk.parse_iso`) and writes its own file. Whatever
mode the Polymarket desk is in (live included), nothing here can ever send a real order.

The picks: :data:`DATA_PATH` (``nightcrawler/data/marco_picks.json``, package data), written by a separate weekly
routine that transcribes each new episode: ``episodes: [{id, title, published, source_url, picks: [{rank (1 = his
favorite), love, league, team (full name), opponent, kind (moneyline | spread | total | parlay | prop), line, quote,
game_date (the game's local US date)}]}]``. A malformed pick is left out, never guessed.

Every :data:`POLL_S` seconds, in its own thread (started where the Polymarket desk starts):

1. Each LOVED pick of an episode already published (never before the data) whose game is not over is followed. Its
   game is found on the gateway from the game date's sports events, each with its moneyline market only (the listing's
   ``marketTypes=moneyline``: a few KB a game, not the 3 MB of every prop), read at most every :data:`DISCOVER_S` per
   date while a love is still unmatched: the pick's league (event slug or tag), its team on one side of the moneyline
   market (and the opponent, when given, on the other) and a kickoff on the pick's US date.
2. A moneyline pick is that market's side for the team (the venue lists one moneyline market per game, whose two
   sides are the two teams: the "long" side's ask is the book's best ask, the other side's ask is 1 - best bid). A
   spread or total pick is bought only when the gateway lists that EXACT line for that side (a full-game spread side
   ``+3.00`` for the team, a full-game total ``Under`` at 51), checked at most every :data:`LINE_RECHECK_S`; until then
   it reads "not on Polymarket US" (the venue lists half-point lines, so a whole-number line is usually not there).
   Parlays and props are never on the venue: shown, never bought. A pick he does not love is shown, never followed.
3. Buy once, on paper, at the ask: a :data:`TICKET_USD` practice ticket, the market's own taker fee
   (``feeCoefficient x shares x p x (1 - p)``, :func:`nightcrawler.polydesk._fee`), only while the market is OPEN and
   the game has not started or is at most :data:`LATE_BUY_S` old. A pick not bought by kickoff + :data:`CUTOFF_S` is
   closed: "no market" (never found by then) or "missed" (found, but no price to buy in time).
4. Settle at the venue's settlement price (the long side's value; the other side gets 1 - value), checked from
   kickoff + :data:`SETTLE_AFTER_S`, every :data:`SETTLE_EVERY_S`: won (the side paid $1), lost (paid nothing) or even
   (a tie's $0.50). The record (``picks`` settled, ``won``, ``lost``, ``even``, ``pnl_usd``) is pretend money only.

State: ``DATA_DIR/marcodesk/state.json`` (atomic rewrite, :func:`nightcrawler.polydesk.save_state`). The page reads it
through :func:`panel_state` (``/api/page`` ``money.marco`` and ``plain.marco_line``), always labelled practice.

The same desk follows more than one expert (:data:`FOLLOWS`, one :class:`Follow` each: Marco, and the NHL bettor
:data:`NHL`), each in its own thread with its own state folder and picks file. A picks file changes more often than
the bot is deployed (the NHL bettor posts every day), so each desk also reads its file's copy on the deploy branch
(``FOLLOW_PICKS_URL`` + the file's name, a public raw GitHub URL) every :data:`REMOTE_EVERY_S`, checks it parses, and
keeps it as ``DATA_DIR/<desk>/picks.json``; the packaged file and that copy are merged by episode id (the copy wins).
An expert with a public pick page (:attr:`Follow.source`: Nick Martin's Action Network profile, where every pick is
logged before the game with its units) is also read every :data:`SOURCE_EVERY_S` (:func:`fetch_source`): his NHL
picks become ``DATA_DIR/<desk>/source.json``, one episode per game day; a love is a full-size pre-game moneyline.
The NHL desk is practice money only.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from nightcrawler import polydesk
from nightcrawler.config import Settings

log = logging.getLogger("nightcrawler.marcodesk")

PACKAGE_DATA = Path(__file__).resolve().parent / "data"
DATA_PATH = PACKAGE_DATA / "marco_picks.json"
STATE_VERSION = 1


@dataclass(frozen=True)
class Follow:
    """One expert whose loves are followed: his picks file, his desk's state folder, the venue's sport name for his
    games and the leagues a pick of his may be in (empty: any)."""

    key: str  # the desk's folder under DATA_DIR ("marcodesk") and the page's key
    who: str  # the page's short name for him ("Marco")
    file: str  # the picks file's name in nightcrawler/data (and on the deploy branch)
    sport: str  # the Polymarket desk's sport name for his games ("american football")
    leagues: tuple[str, ...] = ()
    source: str = ""  # a public page that lists his picks as data (an Action Network profile), read by the desk

    @property
    def data_path(self) -> Path:
        return PACKAGE_DATA / self.file


MARCO = Follow("marcodesk", "Marco", "marco_picks.json", "american football")
NHL = Follow("nhldesk", "Nick Martin", "nhl_picks.json", "hockey", ("nhl",),
             "https://www.actionnetwork.com/picks/profile/nicholaskmartin")
FOLLOWS = (MARCO, NHL)
REMOTE_EVERY_S = 600.0  # the deploy branch's copy of a picks file, read at most this often
REMOTE_MAX_BYTES = 512 * 1024
REMOTE_TIMEOUT_S = 15.0
SOURCE_EVERY_S = 900.0  # an expert's own pick page, read at most this often
SOURCE_MAX_BYTES = 4 * 1024 * 1024
SOURCE_KEEP_DAYS = 14  # game days kept in the file built from his page
SOURCE_LOVE_UNITS = 1.0  # a love on his page: a full-size (1 unit or more) pre-game NHL moneyline
AN_MONEYLINE = {"ml_home", "ml_away"}
AN_POSTED = {"published", "settled"}  # a pick he posted (pending or graded); anything else was withdrawn
POLL_S = 180.0
FIRST_POLL_DELAY_S = 30.0  # a bot built and closed within seconds (tests) never touches the network
TICKET_USD = 20.0  # the practice ticket per pick (pretend money)
LATE_BUY_S = 10 * 60.0  # buy at most this long after kickoff (the game's first minutes)
CUTOFF_S = 30 * 60.0  # a pick not bought by kickoff + this is closed ("no market" / "missed")
LATEST_KICKOFF_H = 28.0  # a game never found: its US date's latest kickoff (04:00 UTC the next day) is the clock
DISCOVER_S = 15 * 60.0  # the game date's listing, read again at most this often while a love is unmatched
LINE_RECHECK_S = 3600.0  # a spread or total pick's exact line, looked for again at most this often
SETTLE_AFTER_S = 2.5 * 3600.0  # settlement is looked for from kickoff + this
SETTLE_EVERY_S = 600.0  # ... at most this often per position (an unsettled market answers 404, retried 3 times)
UNRESOLVED_S = 14 * 86_400.0  # never settled this long after kickoff: closed with no result
MAX_ASK = 0.99  # an ask above this is not a price worth a ticket
DAY_FROM_H, DAY_TO_H = 8.0, 36.0  # a US date's games start between 08:00 UTC that day and 12:00 UTC the next
PAGES = 10  # listing pages read at most per date (100 events each)
EVENTS_KEEP = 20
LABEL = "Practice (pretend money)"

KINDS = ("moneyline", "spread", "total", "parlay", "prop")
BUYABLE = {"moneyline": "moneyline", "spread": "spreads", "total": "totals"}  # kind -> the gateway's marketTypes

WAITING = "waiting"
BOUGHT = "bought"
WON, LOST, EVEN = "won", "lost", "even"
NO_MARKET = "no market"
MISSED = "missed"
NOT_LISTED = "not on Polymarket US"
NOT_LOVE = "not a love"
UNRESOLVED = "unresolved"
STATUSES = (WAITING, BOUGHT, WON, LOST, EVEN, NO_MARKET, MISSED, NOT_LISTED, NOT_LOVE, UNRESOLVED)
CLOSED = frozenset({WON, LOST, EVEN, NO_MARKET, MISSED, NOT_LOVE, UNRESOLVED})
HELD = (BOUGHT, WON, LOST, EVEN, UNRESOLVED)  # a pick the desk bought (its price is shown)


# ---------------------------------------------------------------------- the picks
def _text(value: Any, limit: int) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _date_ok(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return False
    return True


def _pick(episode: str, raw: Any) -> dict[str, Any] | None:
    """One pick of the data file, checked; None when it is malformed (left out, never guessed)."""
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").lower()
    team, rank, game_date = _text(raw.get("team"), 60), raw.get("rank"), raw.get("game_date")
    if kind not in KINDS or not team or not isinstance(rank, int) or isinstance(rank, bool) or not _date_ok(game_date):
        return None
    return {
        "id": f"{episode}|{rank}|{kind}|{team.lower()}",
        "episode": episode,
        "rank": rank,
        "love": raw.get("love") is True,
        "league": _text(raw.get("league"), 12).lower(),
        "team": team,
        "opponent": _text(raw.get("opponent"), 60) or None,
        "kind": kind,
        "line": _text(raw.get("line"), 20) or ("ML" if kind == "moneyline" else ""),
        "quote": _text(raw.get("quote"), 160),
        "game_date": game_date,
    }


def load_episodes(path: Path | None = None) -> list[dict[str, Any]]:
    """The data file's episodes, newest first (``published`` as a unix time); [] when the file is missing or junk."""
    try:
        doc = json.loads((path or DATA_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    raw_eps = doc.get("episodes") if isinstance(doc, dict) else None
    out: list[dict[str, Any]] = []
    for ep in raw_eps if isinstance(raw_eps, list) else []:
        if not isinstance(ep, dict):
            continue
        eid, published = _text(ep.get("id"), 60), polydesk.parse_iso(ep.get("published"))
        if not eid or published is None:
            continue
        raw_picks = ep.get("picks")
        picks = [p for p in (_pick(eid, raw) for raw in (raw_picks if isinstance(raw_picks, list) else []))
                 if p is not None]
        out.append({"id": eid, "title": _text(ep.get("title"), 120), "published": published,
                    "source_url": _text(ep.get("source_url"), 200), "picks": picks})
    out.sort(key=lambda e: -e["published"])
    return out


def remote_path(settings: Settings, follow: Follow = MARCO) -> Path:
    """Where the deploy branch's copy of ``follow``'s picks file is kept (see the module docstring)."""
    return Path(settings.data_dir) / follow.key / "picks.json"


def source_path(settings: Settings, follow: Follow = MARCO) -> Path:
    """Where the picks read from ``follow``'s own page are kept (:func:`fetch_source`)."""
    return Path(settings.data_dir) / follow.key / "source.json"


def follow_episodes(settings: Settings, follow: Follow = MARCO) -> list[dict[str, Any]]:
    """``follow``'s episodes, newest first: the packaged file, the branch copy and the picks read from his own page
    merged by episode id (later ones win), each pick outside his leagues left out."""
    by_id = {ep["id"]: ep for ep in load_episodes(follow.data_path)}
    by_id.update({ep["id"]: ep for ep in load_episodes(remote_path(settings, follow))})
    by_id.update({ep["id"]: ep for ep in load_episodes(source_path(settings, follow))})
    out = []
    for ep in by_id.values():
        picks = [p for p in ep["picks"] if not follow.leagues or p.get("league") in follow.leagues]
        out.append({**ep, "picks": picks})
    out.sort(key=lambda e: -e["published"])
    return out


def _us_date(iso: Any) -> str | None:
    """A game's US (Eastern) date from its UTC start: '2026-10-12T02:30:00Z' -> '2026-10-11'."""
    ts = polydesk.parse_iso(iso)
    return None if ts is None else (datetime.fromtimestamp(ts, UTC) - timedelta(hours=4)).strftime("%Y-%m-%d")


def action_picks(html: str) -> list[dict[str, Any]]:
    """An Action Network profile page's picks (its embedded ``__NEXT_DATA__``) as raw picks of the picks-file schema
    plus ``source_id`` and ``created``: every NHL pick he posted (pending or graded) with its game; [] when there is
    none.
    A love (:data:`SOURCE_LOVE_UNITS`) is a pre-game, full-game NHL moneyline of at least one unit: his long-shot
    specials (a quarter or half unit), props, live bets and other bet types are kept as "not a love"."""
    start = html.find('id="__NEXT_DATA__"')
    start = html.find(">", start) + 1 if start >= 0 else -1
    end = html.find("</script>", start) if start > 0 else -1
    if start <= 0 or end < 0:
        return []
    try:
        doc = json.loads(html[start:end])
        profile = doc["props"]["pageProps"]["profile"]
        rows = profile["picks"]
    except (ValueError, KeyError, TypeError):
        return []
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("status") not in AN_POSTED or row.get("league_name") != "nhl":
            continue
        game = row.get("game")
        teams = {t.get("id"): t for t in (game.get("teams") or []) if isinstance(t, dict)} if isinstance(
            game, dict) else {}
        mine, date = teams.get(row.get("side_id")), _us_date(row.get("starts_at"))
        if not isinstance(game, dict) or not isinstance(mine, dict) or date is None:
            continue
        other_id = game.get("home_team_id") if row.get("side_id") == game.get("away_team_id") else game.get(
            "away_team_id")
        other = teams.get(other_id) if other_id != row.get("side_id") else None
        units = polydesk._num(row.get("units")) or 0.0
        play = _text(row.get("play"), 80)
        moneyline = row.get("type") in AN_MONEYLINE and row.get("period") == "game"
        live = row.get("is_live") is True or "live" in play.lower()
        out.append({"source_id": str(row.get("id")), "created": _text(row.get("created_at"), 30),
                    "love": moneyline and not live and units >= SOURCE_LOVE_UNITS, "league": "nhl",
                    "team": _text(mine.get("full_name"), 60),
                    "opponent": _text(other.get("full_name"), 60) if isinstance(other, dict) else None,
                    "kind": "moneyline" if moneyline else "prop", "line": "ML" if moneyline else play,
                    "quote": f"{play} ({units:g}u)", "game_date": date})
    return out


def merge_source(old: Any, picks: list[dict[str, Any]], who: str, url: str, now: float) -> dict[str, Any]:
    """The picks file built from an expert's page: one episode per game day (id ``<desk>-<date>``, published at
    his first pick of that day), each pick kept once by its ``source_id`` with the rank it was first seen at (a pick
    scrolled off his page stays), the last :data:`SOURCE_KEEP_DAYS` days."""
    days: dict[str, dict[str, Any]] = {}
    for ep in (old.get("episodes") if isinstance(old, dict) else None) or []:
        if isinstance(ep, dict) and isinstance(ep.get("game_date"), str) and isinstance(ep.get("picks"), list):
            days[ep["game_date"]] = ep
    for pick in sorted(picks, key=lambda p: p["created"]):
        ep = days.setdefault(pick["game_date"], {"id": f"{who.lower().replace(' ', '-')}-{pick['game_date']}",
                                                  "game_date": pick["game_date"],
                                                  "title": f"{who}'s NHL picks for {pick['game_date']}",
                                                  "published": pick["created"], "source_url": url, "picks": []})
        if any(p.get("source_id") == pick["source_id"] for p in ep["picks"]):
            continue
        ep["picks"].append({**pick, "rank": len(ep["picks"]) + 1})
        if pick["created"] < str(ep.get("published") or "~"):
            ep["published"] = pick["created"]
    cutoff = (datetime.fromtimestamp(now, UTC) - timedelta(days=SOURCE_KEEP_DAYS)).strftime("%Y-%m-%d")
    kept = sorted((ep for date, ep in days.items() if date >= cutoff), key=lambda e: e["game_date"], reverse=True)
    return {"about": f"Built by the bot from {url}", "episodes": kept}


def fetch_source(settings: Settings, follow: Follow, now: float) -> bool:
    """Read ``follow``'s own pick page (:attr:`Follow.source`), add its new picks to his file (:func:`merge_source`);
    False when there is no page, it is unreachable or holds no picks (the file already kept stays)."""
    if not follow.source.startswith("https://"):
        return False
    try:
        reply = requests.get(follow.source, timeout=REMOTE_TIMEOUT_S, headers={"User-Agent": "Mozilla/5.0"})
    except requests.RequestException:
        return False
    if reply.status_code != 200 or len(reply.content) > SOURCE_MAX_BYTES:
        return False
    picks = action_picks(reply.content.decode("utf-8", errors="replace"))
    if not picks:
        return False
    path = source_path(settings, follow)
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    polydesk.save_state(path, merge_source(old, picks, follow.who, follow.source, now))
    return True


def fetch_remote(settings: Settings, follow: Follow = MARCO) -> bool:
    """Read the deploy branch's copy of ``follow``'s picks file and keep it when it is a picks file (a JSON object
    with an ``episodes`` list, at most :data:`REMOTE_MAX_BYTES`); False when it is off (``off``, or not an https URL),
    unreachable or junk (the copy already kept stays)."""
    base = str(settings.follow_picks_url or "").strip()
    if not base.startswith("https://"):
        return False
    try:
        reply = requests.get(f"{base.rstrip('/')}/{follow.file}", timeout=REMOTE_TIMEOUT_S)
    except requests.RequestException:
        return False
    if reply.status_code != 200 or len(reply.content) > REMOTE_MAX_BYTES:
        return False
    try:
        doc = json.loads(reply.content)
    except ValueError:
        return False
    if not isinstance(doc, dict) or not isinstance(doc.get("episodes"), list):
        return False
    polydesk.save_state(remote_path(settings, follow), doc)
    return True


def pick_line(pick: Mapping[str, Any]) -> tuple[str, float] | None:
    """What a buyable pick needs on the venue: ``("ml", 0)``, ``("spread", 3.0)`` for '+3', ``("under", 51.0)`` for
    'u51' / ``("over", 48.5)`` for 'o48.5'; None when it is not buyable or its line does not read."""
    kind, line = pick.get("kind"), str(pick.get("line") or "").strip().lower().replace(" ", "")
    if kind == "moneyline":
        return ("ml", 0.0)
    try:
        if kind == "spread":
            return ("spread", 0.0 if line in ("pk", "pick", "pickem") else float(line))
        if kind == "total" and line[:1] in ("u", "o"):
            side = "under" if line[0] == "u" else "over"
            return (side, float(line[len(side):] if line.startswith(side) else line[1:]))
    except ValueError:
        return None
    return None


def followed(pick: Mapping[str, Any]) -> bool:
    """A pick the desk follows: one he loves, of a kind the venue can list, with a line that reads."""
    return bool(pick.get("love")) and pick.get("kind") in BUYABLE and pick_line(pick) is not None


def first_status(pick: Mapping[str, Any]) -> str:
    """A pick's status before the desk has looked at the venue."""
    if pick.get("kind") not in BUYABLE:
        return NOT_LISTED  # parlays and props: never on Polymarket US
    if not pick.get("love"):
        return NOT_LOVE
    return WAITING if pick.get("kind") == "moneyline" else NOT_LISTED  # an exact spread / total line is rare


def nickname(team: str) -> str:
    """'Green Bay Packers' -> 'Packers' (the page's short name)."""
    words = team.split()
    return words[-1] if words else team


def pick_label(pick: Mapping[str, Any]) -> str:
    """'Packers moneyline', 'Packers +3', 'Raiders u51', 'Six-leg parlay +2300'."""
    team = str(pick.get("team") or "")
    if pick.get("kind") == "moneyline":
        return f"{nickname(team)} moneyline"
    if pick.get("kind") in ("parlay", "prop"):
        return f"{team} {pick.get('line') or ''}".strip()
    return f"{nickname(team)} {pick.get('line') or pick.get('kind')}".strip()


# ---------------------------------------------------------------------- the venue (public gateway, read only)
def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day_start(game_date: str) -> float:
    return datetime.strptime(game_date, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()


def _window(game_date: str) -> dict[str, str]:
    start = _day_start(game_date)
    return {"startDateMin": _iso(start + DAY_FROM_H * 3600), "startDateMax": _iso(start + DAY_TO_H * 3600)}


def _on_date(kickoff: float, game_date: str) -> bool:
    """A kickoff on the pick's local US date (Eastern to Hawaii time, no time-zone table needed)."""
    return game_date in {(datetime.fromtimestamp(kickoff, UTC) - timedelta(hours=h)).strftime("%Y-%m-%d")
                         for h in (4, 10)}


def _norm(name: Any) -> str:
    return " ".join(str(name or "").lower().split())


def same_team(a: Any, b: Any) -> bool:
    """The same team: the full name, or the nickname ('Packers'), within one league's listing."""
    x, y = _norm(a), _norm(b)
    return bool(x and y) and (x == y or x.split()[-1] == y.split()[-1])


def _side_team(side: Mapping[str, Any]) -> str:
    team = side.get("team")
    return str((team.get("name") if isinstance(team, dict) else None) or side.get("description") or "")


def _league_ok(league: str, ev: Mapping[str, Any]) -> bool:
    if not league:
        return True
    return str(ev.get("slug") or "").lower().startswith(f"{league}-") or league in polydesk._event_tags(ev)


def _is_moneyline(m: Mapping[str, Any]) -> bool:
    return "MONEYLINE" in str(m.get("sportsMarketTypeV2") or "").upper() or str(m.get("marketType")) == "moneyline"


def _sides(m: Mapping[str, Any]) -> list[dict[str, Any]]:
    sides = m.get("marketSides")
    return [s for s in sides if isinstance(s, dict)] if isinstance(sides, list) else []


def match_game(pick: Mapping[str, Any], events: list[Any]) -> dict[str, Any] | None:
    """The pick's game in a listing of events (each with its moneyline market): the league, the team on exactly one
    side (the opponent, when given, on the other) and a kickoff on the pick's date; None when it is not there."""
    for ev in events:
        if not isinstance(ev, dict) or not _league_ok(str(pick.get("league") or ""), ev):
            continue
        for m in ev.get("markets") or []:
            if not isinstance(m, dict) or not m.get("slug") or not _is_moneyline(m) or m.get("closed"):
                continue
            sides = _sides(m)
            mine = [s for s in sides if same_team(pick["team"], _side_team(s))]
            if len(sides) != 2 or len(mine) != 1:
                continue
            other = sides[1] if mine[0] is sides[0] else sides[0]
            if pick.get("opponent") and not same_team(pick["opponent"], _side_team(other)):
                continue
            kickoff = polydesk.parse_iso(m.get("gameStartTime")) or polydesk.parse_iso(
                ev.get("startTime") or ev.get("startDate"))
            if kickoff is None or not _on_date(kickoff, str(pick["game_date"])):
                continue
            return {"event_slug": str(ev.get("slug") or ""), "event": _text(ev.get("title"), 80), "kickoff": kickoff,
                    "slug": str(m["slug"]), "long": mine[0].get("long") is True, "side": _side_team(mine[0])[:60],
                    "fee_coef": polydesk._num(m.get("feeCoefficient"))}
    return None


def day_events(game_date: str, wanted: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The games of ``wanted`` picks (all on ``game_date``) by pick id, from the date's sports events with their
    moneyline market only; pages stop once every pick is matched."""
    found: dict[str, dict[str, Any]] = {}
    for page in range(PAGES):
        reply = polydesk._get("/events", {"limit": polydesk.PAGE, "offset": page * polydesk.PAGE, "closed": "false",
                                          "categories": "sports", "marketTypes": "moneyline", **_window(game_date)})
        evs = reply.get("events") if isinstance(reply, dict) else None
        if not isinstance(evs, list) or not evs:
            break
        for pick in wanted:
            if pick["id"] not in found:
                game = match_game(pick, evs)
                if game is not None:
                    found[pick["id"]] = game
        if len(found) == len(wanted) or len(evs) < polydesk.PAGE:
            break
        time.sleep(polydesk.REQ_SLEEP_S)
    return found


def exact_line(pick: Mapping[str, Any], game: Mapping[str, Any]) -> dict[str, Any] | None:
    """A spread or total pick's market when the gateway lists that EXACT line in the pick's game: a full-game spread
    side for the team at the same number ('+3' needs ``+3.00``), or a full-game total's Over / Under side at the same
    number; None otherwise (the venue lists half points, so a whole number is usually not there)."""
    want, kind = pick_line(pick), str(pick.get("kind"))
    if want is None or kind not in ("spread", "total") or not game.get("event_slug"):
        return None
    reply = polydesk._get("/events", {"limit": 1, "offset": 0, "closed": "false", "categories": "sports",
                                      "slug": game["event_slug"], "marketTypes": BUYABLE[kind],
                                      **_window(str(pick["game_date"]))})
    evs = reply.get("events") if isinstance(reply, dict) else None
    for ev in evs if isinstance(evs, list) else []:
        if not isinstance(ev, dict) or ev.get("slug") != game["event_slug"]:
            continue
        for m in ev.get("markets") or []:
            if not isinstance(m, dict) or not m.get("slug") or m.get("closed"):
                continue
            smt = str(m.get("sportsMarketType") or "")
            for side in _sides(m):
                if kind == "spread":
                    ok = (smt.endswith("_full_game_spread") and same_team(pick["team"], _side_team(side))
                          and polydesk._num(side.get("description")) == want[1])
                else:
                    ok = (smt.endswith("full_game_total") and "points" not in smt
                          and polydesk._num(m.get("line")) == want[1]
                          and _norm(side.get("description")) == want[0])
                if ok:
                    return {"slug": str(m["slug"]), "long": side.get("long") is True,
                            "side": _text(side.get("description"), 30),
                            "fee_coef": polydesk._num(m.get("feeCoefficient"))}
    return None


def side_ask(q: Mapping[str, Any], long: bool) -> float | None:
    """The price to buy one side of a market from its quote (:func:`nightcrawler.polydesk.bbo`, the long side's
    book): the best ask for the long side, 1 - the best bid for the other; None when there is no sane price."""
    if long:
        ask = polydesk._num(q.get("best_ask"))
    else:
        bid = polydesk._num(q.get("best_bid"))
        ask = 1.0 - bid if bid is not None else None
    if ask is None or not 0.0 < ask <= MAX_ASK:
        return None
    return round(ask, 4)


# ---------------------------------------------------------------------- the desk's own record
def empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "picks": {},  # pick id -> {status, game, market, position, result, ...}
        "record": {"picks": 0, "won": 0, "lost": 0, "even": 0, "pnl_usd": 0.0},  # settled picks, pretend money
        "events": [],
        "discover": {},  # game date -> the last listing read
        "counters": {"polls": 0, "errors": 0, "bought": 0, "settled": 0},
        "last_poll": None,
        "last_ok": None,
        "last_error": None,
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def load_state(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text())
        if isinstance(doc, dict) and doc.get("version") == STATE_VERSION:
            base = empty_state()
            fresh = empty_state()
            base.update({k: v for k, v in doc.items() if type(v) is type(base.get(k)) or base.get(k) is None})
            for key in ("record", "counters"):  # every count present, whatever an older file kept
                base[key] = {**fresh[key], **base[key]}
            return base
    except (OSError, ValueError):
        pass
    return empty_state()


def state_path(settings: Settings, follow: Follow = MARCO) -> Path:
    return Path(settings.data_dir) / follow.key / "state.json"


class MarcoDesk:
    """The loves desk's runtime (one daemon thread). PAPER ONLY: it holds no client and no key, and has no order path.
    ``poll(now)`` is also callable directly (tests)."""

    def __init__(self, settings: Settings, path: Path | None = None, data_path: Path | None = None,
                 follow: Follow = MARCO) -> None:
        self.settings = settings
        self.follow = follow
        self.path = path or state_path(settings, follow)
        self.data_path = data_path  # a fixed picks file (tests); None: the packaged file and the branch copy
        self.state = load_state(self.path)
        self._fetched_at = 0.0
        self._sourced_at = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def episodes(self) -> list[dict[str, Any]]:
        """The picks this desk follows (:func:`follow_episodes`, or the fixed file given at construction)."""
        if self.data_path is not None:
            return load_episodes(self.data_path)
        return follow_episodes(self.settings, self.follow)

    def refresh(self, now: float) -> bool:
        """The branch copy of the picks file, read at most every REMOTE_EVERY_S (the thread's loop, never poll)."""
        if self.data_path is not None:
            return False
        ok = False
        if now - self._fetched_at >= REMOTE_EVERY_S:
            self._fetched_at = now
            ok = fetch_remote(self.settings, self.follow)
            if not ok:
                log.info("followdesk_remote_unread desk=%s", self.follow.key)
        if self.follow.source and now - self._sourced_at >= SOURCE_EVERY_S:
            self._sourced_at = now
            sourced = fetch_source(self.settings, self.follow, now)
            if not sourced:
                log.info("followdesk_source_unread desk=%s", self.follow.key)
            ok = ok or sourced
        return ok

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name=self.follow.key, daemon=True)
        self._thread.start()
        log.info("marcodesk_started desk=%s poll_s=%g ticket_usd=%.0f (paper only)", self.follow.key, POLL_S,
                 TICKET_USD)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self._stop.wait(FIRST_POLL_DELAY_S)
        while not self._stop.is_set():
            t0 = time.time()
            try:
                self.refresh(t0)
                self.poll(t0)
            except Exception as exc:  # noqa: BLE001 (a paper desk keeps going; nothing else is affected)
                self.state["counters"]["errors"] += 1
                self.state["last_error"] = type(exc).__name__
                self._save()
                log.warning("marcodesk_poll_failed error=%s", type(exc).__name__)
            self._stop.wait(max(5.0, POLL_S - (time.time() - t0)))

    def _save(self) -> None:
        polydesk.save_state(self.path, self.state)

    def _event(self, ts: float, text: str, tone: str = "neutral") -> None:
        self.state["events"].insert(0, {"ts": ts, "text": text[:160], "tone": tone})
        del self.state["events"][EVENTS_KEEP:]

    # ------------------------------------------------------------------ one round
    def poll(self, now: float) -> dict[str, int]:
        st = self.state
        st["counters"]["polls"] += 1
        st["last_poll"] = now
        live: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for ep in self.episodes():
            for pick in ep["picks"]:
                rec = st["picks"].get(pick["id"])
                if not isinstance(rec, dict) or rec.get("status") not in STATUSES:  # new (or junk): a fresh record
                    rec = st["picks"][pick["id"]] = {"status": first_status(pick), "game": None, "market": None,
                                                     "position": None, "result": None}
                if rec["status"] in CLOSED or rec.get("position") or not followed(pick):
                    continue
                if now < ep["published"]:  # never before the data: the episode is not out yet
                    continue
                if now > self._cutoff(pick, rec):
                    self._close(now, pick, rec)
                    continue
                live.append((pick, rec))
        self._find(now, live)
        bought = sum(self._buy(now, pick, rec) for pick, rec in live)
        for pick, rec in live:  # a game found only after its cutoff (or not bought in time) closes now
            if not rec.get("position") and now > self._cutoff(pick, rec):
                self._close(now, pick, rec)
        settled = self._settle(now)
        st["last_ok"] = now
        st["last_error"] = None
        self._save()
        return {"followed": len(live), "bought": bought, "settled": settled}

    @staticmethod
    def _cutoff(pick: Mapping[str, Any], rec: Mapping[str, Any]) -> float:
        game = rec.get("game")
        if isinstance(game, dict) and polydesk._num(game.get("kickoff")) is not None:
            return float(game["kickoff"]) + CUTOFF_S
        return _day_start(str(pick["game_date"])) + LATEST_KICKOFF_H * 3600 + CUTOFF_S

    def _close(self, now: float, pick: Mapping[str, Any], rec: dict[str, Any]) -> None:
        """A followed pick not bought by its cutoff: "no market" (never found in time), "missed" (found, no price
        in time); a spread or total whose exact line never showed stays "not on Polymarket US"."""
        if rec["status"] != WAITING:
            return
        market = rec.get("market")
        found_in_time = isinstance(market, dict) and (market.get("found_at") or 0) <= self._cutoff(pick, rec)
        rec["status"] = MISSED if found_in_time else NO_MARKET
        rec["closed_at"] = now
        what = "found but no price before the game was under way" if found_in_time else (
            "no Polymarket US market by kickoff + 30 min")
        self._event(now, f"{self.follow.who} desk: {pick_label(pick)}: {what} (practice).", "neutral")

    def _find(self, now: float, live: list[tuple[dict[str, Any], dict[str, Any]]]) -> None:
        """Each followed pick's game (the date's listing, at most every DISCOVER_S per date), then a spread or total
        pick's exact line (at most every LINE_RECHECK_S)."""
        st = self.state
        by_date: dict[str, list[dict[str, Any]]] = {}
        for pick, rec in live:
            if rec.get("game") is None:
                by_date.setdefault(str(pick["game_date"]), []).append(pick)
        recs = {pick["id"]: rec for pick, rec in live}
        for date, picks in by_date.items():
            if now - float(st["discover"].get(date) or 0.0) < DISCOVER_S:
                continue
            st["discover"][date] = now
            try:
                games = day_events(date, picks)
            except RuntimeError:
                st["counters"]["errors"] += 1
                continue
            for pid, game in games.items():
                rec = recs[pid]
                rec["game"] = {**game, "found_at": now}
                if rec["status"] == WAITING and not rec.get("market"):  # a moneyline: the game's own market
                    rec["market"] = {k: game[k] for k in ("slug", "long", "side", "fee_coef")} | {"found_at": now}
        for pick, rec in live:
            known = rec.get("game")
            if pick["kind"] == "moneyline" or not isinstance(known, dict) or rec.get("market"):
                continue
            if now - float(rec.get("line_checked_at") or 0.0) < LINE_RECHECK_S:
                continue
            rec["line_checked_at"] = now
            try:
                market = exact_line(pick, known)
            except RuntimeError:
                st["counters"]["errors"] += 1
                continue
            if market is not None:
                rec["market"] = {**market, "found_at": now}
                rec["status"] = WAITING

    def _buy(self, now: float, pick: Mapping[str, Any], rec: dict[str, Any]) -> int:
        """Buy the pick once, on paper, at the ask, while its market is open and the game at most LATE_BUY_S old."""
        market, game = rec.get("market"), rec.get("game")
        if rec["status"] != WAITING or rec.get("position") or not isinstance(market, dict) or not isinstance(game, dict):
            return 0
        kickoff = float(game["kickoff"])
        if now > kickoff + LATE_BUY_S:  # the game is under way: too late to copy him
            return 0
        try:
            q = polydesk.bbo(str(market["slug"]))
        except RuntimeError:
            self.state["counters"]["errors"] += 1
            return 0
        if q.get("state") and q["state"] != polydesk.OPEN_STATE:
            return 0
        ask = side_ask(q, bool(market.get("long")))
        if ask is None:
            return 0
        coef = polydesk._num(market.get("fee_coef"))
        coef = polydesk.US_TAKER if coef is None else coef
        shares = TICKET_USD / ask
        rec["position"] = {"slug": market["slug"], "long": bool(market.get("long")), "side": market.get("side"),
                           "price": ask, "shares": shares, "fee_usd": polydesk._fee(coef, ask) * shares,
                           "cost_usd": TICKET_USD, "bought_at": now, "kickoff": kickoff,
                           "event": game.get("event")}
        rec["status"] = BOUGHT
        self.state["counters"]["bought"] += 1
        self._event(now, f"{self.follow.who} desk bought {pick_label(pick)} at {ask:.2f} (practice, pretend money).",
                    "neutral")
        log.info("marcodesk_bought pick=%s slug=%s ask=%.4f (paper)", pick["id"], market["slug"], ask)
        return 1

    def _settle(self, now: float) -> int:
        """Book each bought pick at the venue's settlement price (looked for from kickoff + SETTLE_AFTER_S)."""
        st = self.state
        settled = 0
        for rec in st["picks"].values():
            pos = rec.get("position") if isinstance(rec, dict) else None
            if not isinstance(pos, dict) or rec.get("status") != BOUGHT:
                continue
            if now < pos["kickoff"] + SETTLE_AFTER_S or now - float(rec.get("settle_tried_at") or 0.0) < SETTLE_EVERY_S:
                continue
            rec["settle_tried_at"] = now
            try:
                value = polydesk.settlement(str(pos["slug"]))
            except RuntimeError:  # not settled yet (the venue answers 404) or not reachable: next time
                value = None
            if value is None:
                if now > pos["kickoff"] + UNRESOLVED_S:
                    rec["status"] = UNRESOLVED
                    rec["result"] = {"value": None, "pnl_usd": None, "settled_at": now}
                continue
            paid = value if pos["long"] else 1.0 - value
            pnl = pos["shares"] * paid - pos["fee_usd"] - pos["cost_usd"]
            status = WON if paid >= 0.999 else LOST if paid <= 0.001 else EVEN
            rec["status"] = status
            rec["result"] = {"value": value, "paid": paid, "pnl_usd": pnl, "settled_at": now}
            record = st["record"]
            record["picks"] += 1
            record[status] += 1
            record["pnl_usd"] = float(record["pnl_usd"]) + pnl
            st["counters"]["settled"] += 1
            settled += 1
            team = nickname(str(pos.get("side") or ""))
            self._event(now, f"{self.follow.who} desk settled {team or pos['slug']}: {status} {pnl:+.2f} $ "
                        "(practice, pretend).",
                        "good" if pnl > 0 else "bad" if pnl < 0 else "neutral")
        return settled


# ---------------------------------------------------------------------- the panel
def panel_state(settings: Settings, now: float, data_path: Path | None = None,
                follow: Follow = MARCO) -> dict[str, Any]:
    """What the page shows (``money.marco``): the newest episode's picks with their status (plus any older pick
    still open), the price each bought pick was bought at, and the record. Read from files only (no network)."""
    st = load_state(state_path(settings, follow))
    picks_state = st["picks"] if isinstance(st.get("picks"), dict) else {}
    episodes = load_episodes(data_path) if data_path is not None else follow_episodes(settings, follow)
    latest = episodes[0] if episodes else None
    rows: list[dict[str, Any]] = []
    for ep in episodes:
        for pick in ep["picks"]:
            rec = picks_state.get(pick["id"])
            rec = rec if isinstance(rec, dict) else {}
            status = rec.get("status") if rec.get("status") in STATUSES else first_status(pick)
            if ep is not latest and status != BOUGHT:
                continue
            pos, game, result = (_dict(rec.get(key)) for key in ("position", "game", "result"))
            rows.append({"rank": pick["rank"], "love": pick["love"], "team": pick["team"],
                         "opponent": pick["opponent"], "kind": pick["kind"], "line": pick["line"],
                         "quote": pick["quote"], "game_date": pick["game_date"], "label": pick_label(pick),
                         "status": status, "price": pos.get("price"), "kickoff": game.get("kickoff"),
                         "event": game.get("event"), "pnl_usd": result.get("pnl_usd")})
    loves = {p["rank"] for p in latest["picks"] if p["love"]} if latest else set()
    return {
        "mode": "paper",
        "who": follow.who,
        "label": LABEL,
        "as_of": st.get("last_ok"),
        "episode": ({"id": latest["id"], "title": latest["title"], "published": latest["published"],
                     "source_url": latest["source_url"]} if latest else None),
        "loves": len(loves),
        "picks": rows,
        "record": st.get("record"),
        "ticket_usd": TICKET_USD,
    }
