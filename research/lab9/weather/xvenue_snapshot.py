"""Cross-venue check, Kalshi vs Polymarket US daily-high brackets on the same NWS CLI station (read-only snapshot).

For each matching bracket: cost of Yes on one venue + No on the other (taker, at top of book, with each venue's
fee coef x p x (1-p) per contract; Kalshi rounds its fee up to the cent per order, applied here per 10-lot).
A positive net = a true cross-venue arbitrage (same settlement number), before the size limit at the top of book."""
import json, re, sys, time, math, datetime as dt, urllib.request, urllib.parse
from pathlib import Path
RAW = Path(__file__).parent / "raw"
K = "https://api.elections.kalshi.com/trade-api/v2"; G = "https://gateway.polymarket.us/v1"
CITY = {"nychigh": "KXHIGHNY", "mdwhigh": "KXHIGHCHI", "miahigh": "KXHIGHMIA", "laxhigh": "KXHIGHLAX", "sfohigh": "KXHIGHTSFO"}
def get(url, tries=8):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lab9-research"}), timeout=30) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(3 * (i + 1)); continue
            if e.code == 404: return None
            time.sleep(1)
        except Exception: time.sleep(1)
    return None
def pm_bracket(slug):
    s = slug.rsplit("-", 1)[1]
    m = re.fullmatch(r"lt(\d+)f", s)
    if m: return (-999, int(m.group(1)) - 1)
    m = re.fullmatch(r"gte(\d+)lt(\d+)f", s)
    if m: return (int(m.group(1)), int(m.group(2)))
    m = re.fullmatch(r"gte(\d+)f", s)
    if m: return (int(m.group(1)), 999)
def k_bracket(m):
    s = m["strike_type"]
    if s == "less": return (-999, int(round(m["cap_strike"])) - 1)
    if s == "greater": return (int(round(m["floor_strike"])) + 1, 999)
    if s == "between": return (int(round(m["floor_strike"])), int(round(m["cap_strike"])))
def kfee(p, n=10): return math.ceil(0.07 * n * p * (1 - p) * 100 - 1e-9) / 100 / n
def pfee(p, coef=0.0695): return coef * p * (1 - p)
def run(dates):
    ms = [m for m in json.load(open(RAW / "pmus_temp_markets.json")) if not m.get("closed")]
    out = []
    for city, series in CITY.items():
        for d in dates:
            code = dt.date.fromisoformat(d).strftime("%y%b%d").upper()
            km = get(f"{K}/markets?" + urllib.parse.urlencode({"event_ticker": f"{series}-{code}", "limit": 50}))
            time.sleep(1.2)
            kmk = {k_bracket(m): m for m in (km or {}).get("markets", [])}
            for pm in [m for m in ms if m["slug"].startswith(f"tc-temp-{city}-{d}")]:
                br = pm_bracket(pm["slug"]); k = kmk.get(br)
                if not k: out.append({"pm": pm["slug"], "kalshi": None}); continue
                b = get(f"{G}/markets/{pm['slug']}/bbo"); time.sleep(0.4)
                md = (b or {}).get("marketData", b) or {}
                num = lambda q: float(q["value"]) if isinstance(q, dict) and q.get("value") else None
                pb, pa = num(md.get("bestBid")), num(md.get("bestAsk"))
                ky_ask = float(k.get("yes_ask_dollars") or 0) or None; ky_bid = float(k.get("yes_bid_dollars") or 0) or None
                row = {"pm": pm["slug"], "kalshi": k["ticker"], "pm_bid": pb, "pm_ask": pa, "pm_bid_sz": md.get("bidShares"), "pm_ask_sz": md.get("askShares"),
                       "k_bid": ky_bid, "k_ask": ky_ask, "k_bid_sz": k.get("yes_bid_size_fp"), "k_ask_sz": k.get("yes_ask_size_fp")}
                # A: Yes on Kalshi (ask) + No on PM US (1 - PM bid)
                if ky_ask and pb:
                    row["A_net"] = round(1 - (ky_ask + (1 - pb)) - kfee(ky_ask) - pfee(1 - pb), 4)
                # B: Yes on PM US (ask) + No on Kalshi (1 - Kalshi yes bid)
                if pa and ky_bid:
                    row["B_net"] = round(1 - (pa + (1 - ky_bid)) - pfee(pa) - kfee(1 - ky_bid), 4)
                out.append(row)
    return out
if __name__ == "__main__":
    dates = sys.argv[1:] or ["2026-10-13"]
    rows = run(dates)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M")
    json.dump(rows, open(RAW / f"xvenue_{ts}.json", "w"), indent=0)
    for r in rows:
        print(r.get("pm"), r.get("kalshi"), "PM", r.get("pm_bid"), r.get("pm_ask"), "K", r.get("k_bid"), r.get("k_ask"), "A_net", r.get("A_net"), "B_net", r.get("B_net"))
