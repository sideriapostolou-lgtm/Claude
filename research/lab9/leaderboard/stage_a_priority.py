"""Priority P&L fetcher: fetch user-pnl first for wallets whose activity sample is mostly in markets that
have a twin on Kalshi open categories / Polymarket US (non-sports). Loops until all such wallets are done.
"""
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from classify import TWIN, classify  # noqa: E402
from stage_a import ACT, PNL, fetch  # noqa: E402


def twin_share(rows):
    if not isinstance(rows, list):
        return 0
    tot = twin = 0.0
    for r in rows:
        if r.get("type") != "TRADE":
            continue
        u = float(r.get("usdcSize") or 0)
        tot += u
        if classify(r.get("slug"), r.get("eventSlug"), r.get("title")) in TWIN:
            twin += u if classify(r.get("slug"), r.get("eventSlug"), r.get("title")) != "sports" else 0
    return twin / tot if tot else 0


def main():
    sess = requests.Session()
    idle = 0
    while idle < 3:
        todo = []
        for f in ACT.glob("*.json"):
            w = f.stem
            if (PNL / f"{w}.json").exists():
                continue
            if twin_share(json.loads(f.read_text())) >= 0.25:
                todo.append(w)
        if not todo:
            idle += 1
            time.sleep(60)
            continue
        idle = 0
        for w in todo:
            if (PNL / f"{w}.json").exists():
                continue
            d = fetch(sess, "https://user-pnl-api.polymarket.com/user-pnl",
                      {"user_address": w, "interval": "all", "fidelity": "1d"})
            (PNL / f"{w}.json").write_text(json.dumps(d))
            print("prio", w, file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
