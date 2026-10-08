"""dataset.py: census-based unbiased collector over the real GT client + FakeHttp (offline)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fakes import FakeHttp, FakeRequest
from nightcrawler.backtest import Backtester, load_series
from nightcrawler.clock import FakeClock, iso_utc, minute_floor
from nightcrawler.dataset import CENSUS_FILE, collect, load_census, select_pools, update_census
from nightcrawler.http import HttpClient
from nightcrawler.models import SOL_MINT, StrategyParams
from nightcrawler.sources.geckoterminal import GeckoTerminalClient

H = 3600
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


# --------------------------------------------------------------------------- pure selection


def pool(name: str, created: float | None, base: str | None = None) -> dict[str, Any]:
    return {"pool": name, "created_at": created, "base_mint": base or f"mint_{name}"}


def test_select_pools_age_exclusions_dedupe_order_and_cap() -> None:
    now = 100 * H
    pools = [pool("old", now - 30 * H), pool("young", now - 2 * H), pool("sol", now - 40 * H, SOL_MINT),
             pool("usdc", now - 40 * H, USDC), pool("newer", now - 25 * H), pool("old", now - 1 * H),
             pool("unknown_age", None), pool("edge", now - 24 * H)]
    got = select_pools(pools, now, 24, 10)
    assert [p["pool"] for p in got] == ["edge", "newer", "old"]  # newest first, first sighting of 'old' kept
    assert [p["pool"] for p in select_pools(pools, now, 24, 2)] == ["edge", "newer"]
    assert select_pools(pools, now, 24, 0) == []


def test_census_append_dedupe_and_corrupt_lines(tmp_path: Path) -> None:
    assert load_census(tmp_path) == []
    assert update_census(tmp_path, [pool("a", 1.0), pool("b", 2.0), pool("a", 3.0)], now=10.0) == 2
    assert update_census(tmp_path, [pool("b", 9.0), pool("c", 4.0)], now=20.0) == 1
    with (tmp_path / CENSUS_FILE).open("a", encoding="utf-8") as fh:
        fh.write('{"pool": "half-writ')  # crash mid-line
    assert update_census(tmp_path, [pool("d", 5.0)], now=30.0) == 1  # starts on a fresh line
    census = load_census(tmp_path)
    assert [(r["pool"], r["created_at"], r["discovered_at"]) for r in census] == [
        ("a", 1.0, 10.0), ("b", 2.0, 10.0), ("c", 4.0, 20.0), ("d", 5.0, 30.0)]


# --------------------------------------------------------------------------- fake GeckoTerminal

NOW = 1_791_475_200  # FakeClock default: 2026-10-08T16:00:00Z


def gt_pool(address: str, created: float, symbol: str, *, dex: str = "pumpswap", base: str | None = None,
            price: str = "0.001", fdv: str = "1000000") -> dict[str, Any]:
    base = base or f"Mint{symbol}"
    return {
        "id": f"solana_{address}", "type": "pool",
        "attributes": {"address": address, "name": f"{symbol} / SOL", "pool_created_at": iso_utc(created),
                       "base_token_price_usd": price, "fdv_usd": fdv, "reserve_in_usd": "50000.0"},
        "relationships": {"base_token": {"data": {"id": f"solana_{base}", "type": "token"}},
                          "quote_token": {"data": {"id": f"solana_{SOL_MINT}", "type": "token"}},
                          "dex": {"data": {"id": dex, "type": "dex"}}},
    }


def gt_token(mint: str, symbol: str) -> dict[str, Any]:
    return {"id": f"solana_{mint}", "type": "token",
            "attributes": {"address": mint, "symbol": symbol, "name": f"{symbol} coin", "decimals": 6}}


class FakeGecko:
    """Serves GT new_pools pages and per-pool OHLCV like the real API (newest first, before exclusive)."""

    POOLS = {  # address -> (age_h, symbol, minutes of trading since creation, price path)
        "PoolOld": (30, "OLD", 26 * 60, "steady"),
        "PoolRug": (26, "RUG", 3 * 60, "rug"),
        "PoolNever": (25, "NEVER", 0, "steady"),
        "PoolYoung": (2, "YOUNG", 120, "steady"),
    }

    def __init__(self, fake_http: FakeHttp) -> None:
        self.http = fake_http
        fake_http.register("/new_pools", self.new_pools)
        fake_http.register("/ohlcv/minute", self.ohlcv)

    def created(self, address: str) -> float:
        return NOW - self.POOLS[address][0] * H - 17  # not on a minute boundary

    def new_pools(self, req: FakeRequest) -> dict[str, Any]:
        if int(req.params["page"]) > 1:
            return {"data": []}
        data = [gt_pool(a, self.created(a), sym) for a, (_, sym, _, _) in self.POOLS.items()]
        data.append(gt_pool("PoolSol", NOW - 40 * H, "SOL", base=SOL_MINT))
        included = [gt_token(f"Mint{sym}", sym) for _, sym, _, _ in self.POOLS.values()]
        return {"data": data, "included": included}

    def rows(self, address: str) -> list[list[float]]:
        _, _, minutes, shape = self.POOLS[address]
        start = minute_floor(self.created(address))
        out = []
        for i in range(minutes):
            price = 0.001 * (1 + 0.01 * (i % 7)) if shape == "steady" else (0.001 if i < 120 else 1e-8)
            out.append([start + 60 * i, price, price * 1.01, price * 0.99, price, 50.0])
        return out

    def ohlcv(self, req: FakeRequest) -> dict[str, Any]:
        address = req.url.split("/pools/")[1].split("/")[0]
        before, limit = int(req.params["before_timestamp"]), int(req.params["limit"])
        rows = [r for r in self.rows(address) if r[0] < before][::-1][:limit]
        return {"data": {"attributes": {"ohlcv_list": [[str(x) for x in r] for r in rows]}}}


@pytest.fixture
def gecko(http_client: HttpClient, fake_http: FakeHttp) -> GeckoTerminalClient:
    FakeGecko(fake_http)
    return GeckoTerminalClient(http_client)


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- collect


def test_collect_writes_unbiased_backtest_files(gecko: GeckoTerminalClient, fake_http: FakeHttp,
                                                tmp_path: Path) -> None:
    progress: list[tuple[int, int, str]] = []
    summary = collect(gecko, tmp_path, n_pools=10, min_age_h=24, hours=24,
                      progress=lambda done, total, p: progress.append((done, total, p)))

    assert sorted(summary.written) == ["PoolNever", "PoolOld", "PoolRug"]  # the rug is kept: no survival filter
    assert summary.census_added == 5 and summary.considered == 5
    assert summary.skipped_young == 1 and summary.empty == 1 and summary.failed == {}
    assert [p[:2] for p in progress] == [(1, 3), (2, 3), (3, 3)]
    assert len(fake_http.calls_to("/new_pools")) == 2  # page 2 was empty -> stop

    old = read(tmp_path / "PoolOld.json")
    created = NOW - 30 * H - 17
    assert old["coin"] == "OLD" and old["name"] == "OLD coin" and old["mint"] == "MintOLD"
    assert old["dex"] == "pumpswap" and old["pool"] == "PoolOld"
    assert old["supply"] == pytest.approx(1e9)  # fdv / price
    assert old["created_utc"] == iso_utc(created) and old["collected_utc"] == iso_utc(NOW)
    assert old["source"].startswith("geckoterminal ohlcv/minute")
    ts = [row[0] for row in old["candles"]]
    assert len(ts) == 24 * 60 and ts[0] == minute_floor(created) and ts[-1] < created + 24 * H
    assert ts == sorted(ts)

    rug = read(tmp_path / "PoolRug.json")
    assert len(rug["candles"]) == 180 and rug["candles"][-1][4] == pytest.approx(1e-8)
    assert read(tmp_path / "PoolNever.json")["candles"] == []


def test_collect_resumes_without_refetching(gecko: GeckoTerminalClient, fake_http: FakeHttp, tmp_path: Path) -> None:
    collect(gecko, tmp_path, n_pools=10, min_age_h=24, hours=24)
    ohlcv_calls = len(fake_http.calls_to("/ohlcv/minute"))
    again = collect(gecko, tmp_path, n_pools=10, min_age_h=24, hours=24)
    assert again.written == [] and again.skipped_existing == 3 and again.census_added == 0
    assert len(fake_http.calls_to("/ohlcv/minute")) == ohlcv_calls
    fresh = collect(gecko, tmp_path, n_pools=10, min_age_h=24, hours=24, resume=False)
    assert len(fresh.written) == 3


def test_collect_takes_newest_eligible_pools_first(gecko: GeckoTerminalClient, tmp_path: Path) -> None:
    summary = collect(gecko, tmp_path, n_pools=1, min_age_h=24, hours=24)
    assert summary.written == ["PoolNever"]  # 25 h old: the newest pool that is old enough


def test_collect_downloads_only_closed_history_for_young_pools(gecko: GeckoTerminalClient, tmp_path: Path) -> None:
    collect(gecko, tmp_path, n_pools=10, min_age_h=1, hours=24)
    young = read(tmp_path / "PoolYoung.json")["candles"]
    assert 0 < len(young) <= 120 and young[-1][0] + 60 <= NOW


def test_collect_records_a_pool_failure_and_continues(gecko: GeckoTerminalClient, fake_http: FakeHttp,
                                                      tmp_path: Path) -> None:
    fake_http.register("/pools/PoolRug/ohlcv", {"errors": "boom"}, status=500)
    summary = collect(gecko, tmp_path, n_pools=10, min_age_h=24, hours=24)
    assert "PoolRug" in summary.failed and "500" in summary.failed["PoolRug"]
    assert sorted(summary.written) == ["PoolNever", "PoolOld"]
    assert not (tmp_path / "PoolRug.json").exists()  # retried on the next call


def test_collect_listing_outage(http_client: HttpClient, fake_http: FakeHttp, tmp_path: Path) -> None:
    fake_http.register("/new_pools", {"errors": "down"}, status=503)
    gecko = GeckoTerminalClient(http_client)
    with pytest.raises(RuntimeError, match="listing failed"):
        collect(gecko, tmp_path, max_pages=2)
    update_census(tmp_path, [{"pool": "P", "created_at": NOW - 48 * H, "base_mint": "M"}], NOW - 47 * H)
    fake_http.register("/ohlcv/minute", {"data": {"attributes": {"ohlcv_list": []}}})
    summary = collect(gecko, tmp_path, max_pages=2)  # census still has work: no raise
    assert set(summary.failed) == {"new_pools p1", "new_pools p2"} and summary.written == ["P"]


def test_collected_files_feed_the_backtester(gecko: GeckoTerminalClient, tmp_path: Path) -> None:
    collect(gecko, tmp_path, n_pools=10, min_age_h=24, hours=24)
    candles, meta = load_series(tmp_path / "PoolOld.json")
    assert meta["coin"] == "OLD" and len(candles) == 1440
    results, agg = Backtester(StrategyParams()).run_many(sorted(tmp_path.glob("*.json")))
    assert {r.coin for r in results} == {"OLD", "RUG"} and agg["series_skipped"] == 1  # NEVER has no candles
    assert not list(tmp_path.glob("*.tmp"))  # atomic writes leave nothing behind


def test_collect_uses_injected_clock(http_client: HttpClient, fake_http: FakeHttp, tmp_path: Path) -> None:
    FakeGecko(fake_http)
    later = FakeClock(NOW + 10 * H)
    summary = collect(GeckoTerminalClient(http_client), tmp_path, n_pools=10, min_age_h=24, hours=24, clock=later)
    assert "PoolSol" not in summary.written and len(summary.written) == 3
    assert read(tmp_path / "PoolOld.json")["collected_utc"] == iso_utc(NOW + 10 * H)
