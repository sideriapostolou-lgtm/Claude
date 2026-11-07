"""Tiny public-gateway helper (no key). Polite: <= ~3 req/s, retries on 429/5xx."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

GATEWAY = "https://gateway.polymarket.us/v1"
UA = {"User-Agent": "nightcrawler-research/lab8 (public market data)"}
_last = [0.0]
MIN_GAP = 0.3


def get(path, params=None, tries=4, raw=False):
    url = GATEWAY + path + (("?" + urllib.parse.urlencode(params, doseq=True)) if params else "")
    err = None
    for attempt in range(tries):
        gap = time.time() - _last[0]
        if gap < MIN_GAP:
            time.sleep(MIN_GAP - gap)
        _last[0] = time.time()
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                body = r.read()
                return (r.status, body) if raw else json.loads(body)
        except urllib.error.HTTPError as e:
            err = e.code
            if e.code == 429 or e.code >= 500:
                time.sleep(2.0 * (attempt + 1))
                continue
            if raw:
                return e.code, e.read()
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            err = repr(e)
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {err}")
