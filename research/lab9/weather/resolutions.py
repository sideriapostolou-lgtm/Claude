"""conditionId -> resolved payout per outcome for Polymarket weather markets (from gamma events, public)."""
import json
from pathlib import Path
RAW = Path(__file__).parent / "raw"
def build():
    out = {}
    for e in json.load(open(RAW / "pm_weather_events_all.json")):
        for m in e.get("markets", []):
            cid = m.get("conditionId")
            if not cid: continue
            try:
                prices = [float(p) for p in json.loads(m.get("outcomePrices") or "[]")]
                outs = json.loads(m.get("outcomes") or "[]")
            except Exception:
                continue
            closed = bool(m.get("closed"))
            if closed and prices and max(prices) >= 0.99:
                out[cid] = {"outcomes": outs, "payout": prices, "end": m.get("endDate"), "event": e.get("slug"), "title": m.get("question")}
    json.dump(out, open(RAW / "pm_resolutions.json", "w"))
    return out
if __name__ == "__main__":
    print(len(build()))
