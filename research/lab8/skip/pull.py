import json, sys, time, requests
A = "0xc53375ff94e96100f2b30a4b5775db35218d69a9"; out = sys.argv[1]
rows = []
for off in range(0, 10000, 500):
    r = requests.get("https://data-api.polymarket.com/trades", params={"user": A, "limit": 500, "offset": off, "takerOnly": "false"}, timeout=30)
    if r.status_code != 200: print("stop", off, r.status_code, r.text[:200]); break
    b = r.json()
    if not b: break
    rows += b; time.sleep(0.3)
json.dump(rows, open(out, "w"))
print(len(rows), "trades; keys:", list(rows[0]) if rows else None)
print(json.dumps(rows[0], indent=1)[:1500] if rows else "")
