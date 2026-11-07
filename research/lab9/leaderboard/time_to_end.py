"""For a wallet's BUY fills: time from fill to the market's end (gamma event endDate), by family,
plus outcome side (Yes/No) and price buckets. Caches gamma events in raw/gamma/<eventSlug>.json.
Usage: python3 time_to_end.py <wallet> [...]
"""
import json
import statistics as st
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from classify import classify  # noqa: E402
from stage_a import fetch  # noqa: E402

HERE = Path(__file__).parent
G = HERE / "raw" / "gamma"
G.mkdir(parents=True, exist_ok=True)
SESS = requests.Session()


def event(slug):
    f = G / f"{slug}.json"
    if f.exists():
        return json.loads(f.read_text())
    d = fetch(SESS, "https://gamma-api.polymarket.com/events", {"slug": slug}, 0.3)
    d = d[0] if isinstance(d, list) and d else {}
    f.write_text(json.dumps(d))
    return d


def ts(iso):
    if not iso:
        return None
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def main(ws, max_events=150):
    for w in ws:
        d = HERE / "raw" / "b" / w.lower()
        rows = json.loads((d / "act_newest.json").read_text())
        for v in json.loads((d / "act_slices.json").read_text()).values():
            rows += v
        buys = [r for r in rows if r.get("type") == "TRADE" and r.get("side") == "BUY"]
        evs = Counter(r.get("eventSlug") for r in buys if r.get("eventSlug"))
        ends = {}
        for es, _ in evs.most_common(max_events):
            e = event(es)
            for m in e.get("markets", []) or []:
                ends[m.get("conditionId")] = (ts(m.get("endDate")), m.get("groupItemTitle"), m.get("question"))
        by = defaultdict(list)
        side = defaultdict(Counter)
        for r in buys:
            c = r.get("conditionId")
            if c not in ends or not ends[c][0]:
                continue
            fam = classify(r.get("slug"), r.get("eventSlug"), r.get("title"))
            h = (ends[c][0] - r["timestamp"]) / 3600
            by[fam].append((h, float(r.get("price") or 0), float(r.get("usdcSize") or 0)))
            side[fam][(r.get("outcome") or "?")] += float(r.get("usdcSize") or 0)
        print(f"== {w}  buys {len(buys)}  matched to gamma {sum(len(v) for v in by.values())}")
        for fam, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
            hs = sorted(x[0] for x in v)
            hi = [x for x in v if x[1] >= 0.9]
            hhi = sorted(x[0] for x in hi)
            tot = sum(side[fam].values()) or 1
            print(f"   {fam:18} n={len(v):5}  hours-to-end q10/50/90 {hs[len(hs) // 10]:.1f}/{st.median(hs):.1f}/"
                  f"{hs[9 * len(hs) // 10]:.1f}   price>=0.90 fills {len(hi)} hours-to-end median "
                  f"{(st.median(hhi) if hhi else float('nan')):.1f}   side$ {({k: round(x / tot, 2) for k, x in side[fam].most_common(3)})}")


if __name__ == "__main__":
    main(sys.argv[1:])
