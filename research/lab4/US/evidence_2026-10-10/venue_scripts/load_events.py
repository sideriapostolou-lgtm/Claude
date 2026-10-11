"""Load the raw gateway pages into flat event and market rows (pure, no network)."""

import glob
import json
from datetime import datetime
from pathlib import Path


def parse_iso(v):
    if not v or not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def num(v):
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def tag_slugs(obj):
    out = []
    for t in obj.get("tags") or []:
        out.append(str(t.get("slug") if isinstance(t, dict) else t).lower())
    return out


def load(dirpath, name):
    events, markets = {}, []
    for f in sorted(glob.glob(str(Path(dirpath) / f"{name}_*.json"))):
        doc = json.load(open(f))
        for ev in doc["events"]:
            if ev["slug"] in events:
                continue
            pt = ev.get("primaryTag")
            erow = {
                "event": ev["slug"],
                "title": ev.get("title"),
                "start": parse_iso(ev.get("startTime") or ev.get("startDate")),
                "period": str(ev.get("period") or "").upper(),
                "live": ev.get("live"),
                "ended": ev.get("ended"),
                "series": ev.get("seriesSlug"),
                "tags": tag_slugs(ev),
                "primary_tag": (pt.get("slug") if isinstance(pt, dict) else pt),
                "n_markets": len(ev.get("markets") or []),
                "chat_members": (ev.get("chatChannel") or {}).get("chatMemberCount"),
            }
            events[ev["slug"]] = erow
            for m in ev.get("markets") or []:
                sides = m.get("marketSides") or []
                markets.append(
                    {
                        "event": ev["slug"],
                        "slug": m["slug"],
                        "prefix": m["slug"].split("-", 1)[0],
                        "league": m["slug"].split("-")[1] if m["slug"].count("-") else "",
                        "question": m.get("question"),
                        "market_type": m.get("marketType"),
                        "smt": m.get("sportsMarketType"),
                        "smt2": m.get("sportsMarketTypeV2"),
                        "closed": m.get("closed"),
                        "bid": num(m.get("bestBidQuote")),
                        "ask": num(m.get("bestAskQuote")),
                        "sides": [(s.get("description"), s.get("long"), num(s.get("price"))) for s in sides],
                        "tick": num(m.get("orderPriceMinTickSize")),
                        "fee": num(m.get("feeCoefficient")),
                        "tags": tag_slugs(m),
                        "status": m.get("status"),
                    }
                )
    return events, markets
