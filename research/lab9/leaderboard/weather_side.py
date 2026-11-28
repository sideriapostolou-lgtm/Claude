"""Weather NO-buyers: was the bucket they bet against BELOW the final high (i.e. already passed by the
observed temperature, a known outcome) or ABOVE it (a forecast call that the day won't get that warm)?
Uses gamma events (cached) for bucket titles and resolved winners. Usage: python3 weather_side.py <wallet> [...]
"""
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
from time_to_end import event  # noqa: E402
from weather_timing import TZ, parse  # noqa: E402

HERE = Path(__file__).parent


def lo_bound(title):
    t = (title or "").replace("−", "-")
    m = re.search(r"(-?\d+)", t)
    if not m:
        return None
    v = int(m.group(1))
    if "below" in t.lower() or "≤" in t or "or lower" in t.lower():
        return v - 0.5  # open-ended low bucket sorts first
    return v


def winner(markets):
    for m in markets:
        try:
            p = json.loads(m.get("outcomePrices") or "[]")
            o = json.loads(m.get("outcomes") or "[]")
        except ValueError:
            continue
        if m.get("closed") and dict(zip(o, map(float, p))).get("Yes", 0) > 0.99:
            return m
    return None


def main(ws, max_events=250):
    for w in ws:
        d = HERE / "raw" / "b" / w.lower()
        rows = json.loads((d / "act_newest.json").read_text())
        for v in json.loads((d / "act_slices.json").read_text()).values():
            rows += v
        buys = [r for r in rows if r.get("type") == "TRADE" and r.get("side") == "BUY" and parse(r.get("eventSlug"))]
        evs = Counter(r["eventSlug"] for r in buys)
        cache = {es: event(es) for es, _ in evs.most_common(max_events)}
        res = defaultdict(lambda: [0, 0.0])
        bytime = defaultdict(lambda: defaultdict(float))
        seen = set()
        for r in buys:
            key = (r.get("transactionHash"), r.get("asset"), r.get("size"))
            if key in seen or r["eventSlug"] not in cache:
                continue
            seen.add(key)
            ms = cache[r["eventSlug"]].get("markets") or []
            win = winner(ms)
            mine = next((m for m in ms if m.get("conditionId") == r.get("conditionId")), None)
            if not win or not mine:
                continue
            a, b = lo_bound(mine.get("groupItemTitle")), lo_bound(win.get("groupItemTitle"))
            if a is None or b is None:
                continue
            rel = "winner" if mine is win else ("below final" if a < b else "above final")
            lab = f"{r.get('outcome')} on {rel}"
            usd = float(r.get("usdcSize") or 0)
            res[lab][0] += 1
            res[lab][1] += usd
            _, city, mo, dy, yr = parse(r["eventSlug"])
            tz = TZ.get(city)
            if tz:
                t = datetime.fromtimestamp(r["timestamp"], tz=timezone.utc).astimezone(ZoneInfo(tz))
                h = (t - datetime(yr or t.year, mo, dy, tzinfo=ZoneInfo(tz))).total_seconds() / 3600
                hb = "before day" if h < 0 else "00-12h" if h < 12 else "12-18h" if h < 18 else "18h+"
                bytime[lab][hb] += usd
        tot = sum(v[1] for v in res.values()) or 1
        print(f"== {w}  resolved weather buys {sum(v[0] for v in res.values())}")
        for lab, (n, usd) in sorted(res.items(), key=lambda kv: -kv[1][1]):
            bt = bytime[lab]
            bts = sum(bt.values()) or 1
            print(f"   {lab:22} fills {n:5}  $share {usd / tot:.2f}   local time $: " +
                  " ".join(f"{k}:{v / bts:.2f}" for k, v in sorted(bt.items())))


if __name__ == "__main__":
    main(sys.argv[1:])
