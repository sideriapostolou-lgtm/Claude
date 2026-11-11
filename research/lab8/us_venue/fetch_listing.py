"""Page through /v1/events and /v1/markets with categories=crypto (open), raw pages to disk.

usage: python -I fetch_listing.py OUTDIR TAG [extra k=v ...]
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gw  # noqa: E402

out = Path(sys.argv[1])
tag = sys.argv[2]
extra = dict(a.split("=", 1) for a in sys.argv[3:])
out.mkdir(parents=True, exist_ok=True)
kind = extra.pop("kind", "events")
maxpages = int(extra.pop("pages", "60"))
total = 0
for page in range(maxpages):
    params = {"limit": 100, "offset": page * 100, **extra}
    reply = gw.get(f"/{kind}", params)
    items = reply.get(kind) or []
    (out / f"{tag}_{page:03d}.json").write_text(json.dumps({"params": params, "fetched": time.time(), kind: items}))
    total += len(items)
    print(tag, page, len(items), flush=True)
    if len(items) < 100:
        break
print("total", total)
