"""Pull Polymarket (international) public profit leaderboards. Read-only, keyless.

Boards: overall all/month/week top 200 by PNL, and category boards (crypto, weather, economics,
finance) all/month top 100. Output: raw/boards.json  {board_key: [rows]}.
"""
import json
import sys
import time
from pathlib import Path

import requests

B = "https://data-api.polymarket.com/v1/leaderboard"
OUT = Path(__file__).parent / "raw" / "boards.json"


def get(params):
    for attempt in range(6):
        r = requests.get(B, params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("429 storm")


def board(period, category, depth):
    rows = []
    for off in range(0, depth, 50):
        p = {"timePeriod": period, "orderBy": "PNL", "limit": 50, "offset": off}
        if category:
            p["category"] = category
        page = get(p)
        if not page:
            break
        rows += page
        time.sleep(0.35)
    return rows


def main():
    boards = {}
    for period in ("all", "month", "week"):
        boards[f"overall:{period}"] = board(period, None, 200)
        print("overall", period, len(boards[f"overall:{period}"]), file=sys.stderr)
    for cat in ("crypto", "weather", "economics", "finance"):
        for period in ("all", "month", "week"):
            boards[f"{cat}:{period}"] = board(period, cat, 100)
            print(cat, period, len(boards[f"{cat}:{period}"]), file=sys.stderr)
    OUT.write_text(json.dumps(boards))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
