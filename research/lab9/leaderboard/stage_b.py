"""Stage B: deep public pull for shortlisted wallets. Read-only, keyless.

Per wallet (raw/b/<wallet>/):
  act_newest.json   newest up to 3000 activity rows (all types)
  act_slices.json   {days_ago: 500 rows ending that many days ago} for 7,30,60,90,150,240
  trades_taker.json newest 500 fills where the wallet was taker (takerOnly=true)
  trades_all.json   newest 500 fills maker+taker (takerOnly=false)
  closed.json       closed positions, newest first, up to 1500
  open.json         open positions (incl. redeemable losers), up to 500
Usage: python3 stage_b.py <wallet> [<wallet> ...]
"""
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from stage_a import fetch  # noqa: E402

RAW = Path(__file__).parent / "raw" / "b"
D = "https://data-api.polymarket.com"
GAP = 0.4


def pull(w, sess):
    out = RAW / w
    out.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    if not (out / "act_newest.json").exists():
        rows = []
        for off in range(0, 3000, 500):
            page = fetch(sess, f"{D}/activity", {"user": w, "limit": 500, "offset": off}, GAP)
            if not isinstance(page, list) or not page:
                break
            rows += page
            if len(page) < 500:
                break
        (out / "act_newest.json").write_text(json.dumps(rows))
    if not (out / "act_slices.json").exists():
        sl = {}
        for k in (7, 30, 60, 90, 150, 240):
            page = fetch(sess, f"{D}/activity", {"user": w, "limit": 500, "end": now - k * 86400}, GAP)
            sl[k] = page if isinstance(page, list) else []
        (out / "act_slices.json").write_text(json.dumps(sl))
    for name, tk in (("trades_taker", "true"), ("trades_all", "false")):
        if not (out / f"{name}.json").exists():
            page = fetch(sess, f"{D}/trades", {"user": w, "limit": 500, "takerOnly": tk}, GAP)
            (out / f"{name}.json").write_text(json.dumps(page if isinstance(page, list) else []))
    if not (out / "closed.json").exists():
        rows = []
        for off in range(0, 1500, 50):
            page = fetch(sess, f"{D}/closed-positions",
                         {"user": w, "limit": 50, "offset": off, "sortBy": "TIMESTAMP",
                          "sortDirection": "DESC"}, GAP)
            if not isinstance(page, list) or not page:
                break
            rows += page
            if len(page) < 50:
                break
        (out / "closed.json").write_text(json.dumps(rows))
    if not (out / "open.json").exists():
        rows = []
        for off in range(0, 500, 100):
            page = fetch(sess, f"{D}/positions",
                         {"user": w, "limit": 100, "offset": off, "sizeThreshold": 0.01}, GAP)
            if not isinstance(page, list) or not page:
                break
            rows += page
            if len(page) < 100:
                break
        (out / "open.json").write_text(json.dumps(rows))


def main():
    sess = requests.Session()
    for w in sys.argv[1:]:
        pull(w.lower(), sess)
        print("done", w, file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
