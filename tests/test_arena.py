"""The Arena (nightcrawler.arena): a practice town of trader bots that pay rent or are evicted; the richest have
children. No network: markets and quotes are passed to ``poll``; settlement goes through a fake."""

from __future__ import annotations

import inspect
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nightcrawler import arena as A
from nightcrawler import polydesk as P
from nightcrawler.config import Settings

NOW = datetime(2026, 10, 11, 14, 0, tzinfo=UTC).timestamp()


def _settings(tmp_path: Path) -> Settings:
    return Settings.from_env({"DATA_DIR": str(tmp_path)})


def _market(slug: str, cat: str = "crypto", hours: float = 3.0) -> dict[str, Any]:
    return {"slug": slug, "question": f"Will {slug} happen?", "category": cat, "end_ts": NOW + hours * 3600,
            "fee_coef": 0.0695}


def _q(bid: float, ask: float) -> dict[str, Any]:
    return {"best_bid": bid, "best_ask": ask, "state": P.OPEN_STATE}


def _genes(**kw: Any) -> dict[str, Any]:
    g = {"lo": 0.40, "width": 0.20, "tp": 0.05, "sl": 0.10, "hold_h": 6.0, "max_spread": 0.03, "stake": 0.5,
         "horizon_h": 24.0, "family": "crypto", "side": "yes"}
    return {**g, **kw}


def _town(tmp_path: Path, genes: dict[str, Any] | None = None, n: int = 1) -> A.Arena:
    """An arena whose residents all trade by ``genes`` (the town's first rent day already behind it)."""
    town = A.Arena(_settings(tmp_path))
    town.poll(NOW, markets=[], quotes={})
    for i, res in enumerate(list(town.state["residents"].values())):
        if i < n:
            res["genes"] = dict(genes or _genes())
        else:
            res["genes"] = _genes(family="weather")  # the others stay out of the way
    return town


def test_the_town_fills_with_random_traders_and_pays_no_rent_on_its_first_day(tmp_path: Path) -> None:
    town = A.Arena(_settings(tmp_path))
    town.poll(NOW, markets=[], quotes={})
    residents = town.state["residents"]
    assert len(residents) == A.POPULATION
    assert all(r["cash"] == A.START_CASH and r["gen"] == 1 for r in residents.values())
    assert len({A.style(r["genes"]) for r in residents.values()}) > A.POPULATION // 2  # varied
    assert A.load_state(A.state_path(town.settings))["town"]["born"] == A.POPULATION


def test_a_trader_buys_by_its_genes_and_takes_profit_paying_fees_both_ways(tmp_path: Path) -> None:
    town = _town(tmp_path)
    res = next(r for r in town.state["residents"].values() if r["genes"]["family"] == "crypto")
    m = _market("btc-up")
    town.poll(NOW, markets=[m], quotes={"btc-up": _q(0.49, 0.50)})
    pos = res["positions"]["btc-up"]
    assert (pos["side"], pos["price"]) == ("yes", 0.50) and pos["cost_usd"] == pytest.approx(10.0)
    assert res["cash"] == pytest.approx(10.0)
    town.poll(NOW + 120, markets=[m], quotes={"btc-up": _q(0.56, 0.57)})  # bid 0.56 >= 0.50 + 0.05
    assert "btc-up" not in res["positions"] and res["trades"] == 1 and res["wins"] == 1
    gross = pos["shares"] * 0.56
    assert res["pnl_usd"] == pytest.approx(gross - P._fee(0.0695, 0.56) * pos["shares"] - 10.0)
    assert 0 < res["pnl_usd"] < 10.0 * (0.56 / 0.50 - 1)  # the fees came out of it
    assert "took profit" in town.state["events"][0]["text"]


def test_the_cheap_side_buys_no_at_one_minus_the_bid(tmp_path: Path) -> None:
    genes = _genes(side="cheap", lo=0.10, width=0.30)
    q = _q(0.75, 0.77)  # YES ask 0.77, NO ask 0.25: the cheap side is NO
    assert A.pick_side(genes, q) == "no"
    assert A.side_prices(q, "no") == (pytest.approx(0.25), pytest.approx(0.23))
    assert A.pick_side(_genes(side="dear", lo=0.70, width=0.2), q) == "yes"
    assert A.pick_side(genes, _q(0.70, 0.77)) is None  # 7 cents wide: over its max spread


def test_a_stop_and_a_time_limit_close_a_position(tmp_path: Path) -> None:
    town = _town(tmp_path)
    res = next(r for r in town.state["residents"].values() if r["genes"]["family"] == "crypto")
    m = _market("eth-up", hours=20)
    town.poll(NOW, markets=[m], quotes={"eth-up": _q(0.49, 0.50)})
    town.poll(NOW + 120, markets=[m], quotes={"eth-up": _q(0.39, 0.41)})  # bid 0.39 <= 0.50 - 0.10
    assert res["trades"] == 1 and res["pnl_usd"] < 0 and "cut the loss" in town.state["events"][0]["text"]
    town.poll(NOW + 240, markets=[m], quotes={"eth-up": _q(0.49, 0.50)})
    assert "eth-up" not in res["positions"]  # not bought back so soon (COOLDOWN_S)
    town.poll(NOW + A.COOLDOWN_S + 300, markets=[m], quotes={"eth-up": _q(0.49, 0.50)})
    assert "eth-up" in res["positions"]
    town.poll(NOW + A.COOLDOWN_S + 300 + 6 * 3600, markets=[m], quotes={"eth-up": _q(0.50, 0.51)})
    assert res["trades"] == 2 and "time's up" in town.state["events"][0]["text"]


def test_an_ended_market_settles_at_the_venues_price(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    town = _town(tmp_path, _genes(tp=0.40, hold_h=72))
    res = next(r for r in town.state["residents"].values() if r["genes"]["family"] == "crypto")
    m = _market("sol-up", hours=1)
    town.poll(NOW, markets=[m], quotes={"sol-up": _q(0.49, 0.50)})
    asked: list[str] = []
    monkeypatch.setattr(P, "settlement", lambda slug: asked.append(slug) or 1.0)
    town.poll(NOW + 3700, markets=[], quotes={})
    assert asked == ["sol-up"] and res["wins"] == 1
    assert res["cash"] == pytest.approx(10.0 + 10.0 / (0.5 + P._fee(0.0695, 0.5)))


def test_rent_day_evicts_the_broke_and_the_richest_have_children(tmp_path: Path) -> None:
    town = _town(tmp_path)
    residents = town.state["residents"]
    ids = list(residents)
    rich, poor = residents[ids[0]], residents[ids[1]]
    rich["cash"], poor["cash"] = 60.0, 0.30
    next_day = datetime(2026, 10, 12, 0, 1, tzinfo=UTC).timestamp()
    town.poll(next_day, markets=[], quotes={})
    assert poor["id"] not in residents and rich["cash"] == pytest.approx(60.0 - A.RENT_USD)
    assert len(residents) == A.POPULATION
    child = residents[str(town.state["next_id"] - 1)]
    assert child["gen"] >= 2 and child["parent"] is not None and child["cash"] == A.START_CASH
    grave = town.state["grave"][0]
    assert grave["why"] == "could not pay the rent" and grave["name"] == poor["name"]
    panel = A.panel_state(town.settings, next_day)
    assert panel["today"]["evicted"] == 1 and panel["leaders"][0]["name"] == rich["name"]
    line = A.arena_line(panel)
    assert line is not None and line.startswith(f"The Arena (practice money): {A.POPULATION} traders")
    assert "and 1 eviction;" in line and f"leader {rich['name']} up $" in line


def test_a_trader_under_the_broke_line_is_evicted_at_once(tmp_path: Path) -> None:
    town = _town(tmp_path)
    victim = next(iter(town.state["residents"].values()))
    victim["cash"] = A.BROKE_USD / 2
    town.poll(NOW + 120, markets=[], quotes={})
    assert victim["id"] not in town.state["residents"] and town.state["grave"][0]["why"] == "went broke"


def test_children_inherit_nudged_genes_inside_their_ranges() -> None:
    rng = random.Random(1)
    parent = _genes()
    kids = [A.child_genes(parent, rng) for _ in range(200)]
    for k, (lo, hi) in A.RANGES.items():
        assert all(lo <= kid[k] <= hi for kid in kids)
        assert all(abs(kid[k] - parent[k]) <= A.MUTATE * (hi - lo) + 1e-9 for kid in kids if lo < parent[k] < hi)
    assert sum(kid["family"] == "crypto" for kid in kids) > 150  # mostly the parent's kind
    assert {kid["family"] for kid in kids} <= set(A.FAMILIES)


def test_the_state_survives_a_restart(tmp_path: Path) -> None:
    town = _town(tmp_path)
    town.poll(NOW, markets=[_market("btc-up")], quotes={"btc-up": _q(0.49, 0.50)})
    again = A.Arena(_settings(tmp_path))
    assert again.state["residents"] == town.state["residents"]
    assert A.load_state(tmp_path / "missing.json") == A.empty_state()


def test_practice_only() -> None:
    src = inspect.getsource(A)
    assert "polymarket_us" not in src and "buy_long_ioc" not in src and "client" not in A.Arena.__init__.__code__.co_varnames


def test_the_page_shows_the_arena_as_practice(tmp_path: Path) -> None:
    from nightcrawler.pagestate import arena_town

    settings = _settings(tmp_path)
    town = _town(tmp_path)
    town.poll(NOW, markets=[_market("btc-up")], quotes={"btc-up": _q(0.49, 0.50)})
    block = arena_town(settings, NOW + 60)
    assert block is not None and block["label"] == "Practice (pretend money)" and block["population"] == A.POPULATION
    assert block["events"][0]["text"].endswith("practice).") and block["today"]["buys"] == 1
    off = Settings.from_env({"DATA_DIR": str(tmp_path), "POLYDESK_ENABLED": "0"})
    assert arena_town(off, NOW) is None
