"""Tests for research/lab2/desk_core.py: decision parsing and clamping, the as-of brief and its hash (no lookahead on
synthetic bars), panel vs solo deliberation through the fake client, the decision cache, the budget and retries."""

import dataclasses
import json

import numpy as np
import pytest

import common as C
import desk_core as D
from conftest import make_frames
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
BRIEF = {"class": "OPERATOR", "last_15_min": {"net_flow_sol": 1.5}, "name": "x", "alive": True}


def test_parse_decision_clamps_to_the_registered_bounds():
    bad = D.parse_decision("not json")
    assert bad["action"] == "skip" and bad["size_usd"] == 0.0 and bad["error"].startswith("malformed")
    assert D.parse_decision("[1, 2]")["error"]
    d = D.parse_decision(json.dumps({"action": "BUY", "confidence": 2, "size_usd": 50, "stop_pct": 0.9,
                                     "max_hold_min": 500, "reason": "x" * 1000}))
    assert d == {"action": "buy", "confidence": 1.0, "size_usd": D.SIZE_USD_MAX, "stop_pct": D.STOP_PCT_BOUNDS[1],
                 "max_hold_min": D.HOLD_MIN_BOUNDS[1], "reason": "x" * D.MAX_REASON_CHARS, "error": None}
    d = D.parse_decision(json.dumps({"action": "buy", "confidence": 0.5, "size_usd": 3, "stop_pct": 0.05,
                                     "max_hold_min": 1}))
    assert d["action"] == "skip" and d["size_usd"] == 0.0            # a ticket under $5 is a skip
    assert d["stop_pct"] == D.STOP_PCT_BOUNDS[0] and d["max_hold_min"] == D.HOLD_MIN_BOUNDS[0]
    d = D.parse_decision(json.dumps({"action": "buy", "confidence": "nan", "size_usd": 10, "stop_pct": None,
                                     "max_hold_min": "abc"}))
    assert d["action"] == "buy" and d["confidence"] == 0.0 and d["stop_pct"] == 0.35 and d["max_hold_min"] == 60
    d = D.parse_decision(json.dumps({"action": "skip", "size_usd": 20}))
    assert d["action"] == "skip" and d["size_usd"] == 0.0


def _decision(**kw) -> D.Decision:
    base = dict(action="buy", confidence=0.6, size_usd=20.0, stop_pct=0.35, max_hold_min=60, reason="r",
                config="panel", prompt_version=D.PROMPT_VERSION, brief_hash="h", models=("a", "b"), cost_usd=0.01,
                memos={"scout": "m"}, raw="{}")
    return D.Decision(**{**base, **kw})


def test_decision_buy_rule_and_json_roundtrip():
    d = _decision()
    assert d.buy
    assert D.Decision.from_json(json.loads(json.dumps(d.to_json()))) == d
    assert not dataclasses.replace(d, error="x").buy
    assert not dataclasses.replace(d, action="skip").buy
    assert not dataclasses.replace(d, size_usd=D.SIZE_USD_MIN - 0.01).buy


def test_brief_hash_depends_on_content_only():
    a = {"x": 1, "y": {"b": 2, "a": [1, 2]}}
    b = {"y": {"a": [1, 2], "b": 2}, "x": 1}
    assert D.brief_hash(a) == D.brief_hash(b) and len(D.brief_hash(a)) == 24
    assert D.brief_hash({**a, "x": 2}) != D.brief_hash(a)


def test_untrusted_text_is_sanitized_and_cut():
    assert D._text(None) is None and D._text(12) is None
    s = D._text("a\x00b​<script>c</script>" + "d" * 100)
    assert s is not None and "\x00" not in s and "​" not in s and "<" not in s and len(s) <= 40
    assert D._text("ok", 1) == "o"


def _dataset(frames=None, split="train"):
    g, c, b = frames or make_frames()
    return C.Dataset.from_frames(split, g, c, b, census=C.Census.empty(), sol=SOL)


BRIEF_KEYS = {"age_min", "class", "graduation_delay_s", "name", "symbol", "metadata_host", "price_sol",
              "market_cap_usd", "pool_sol_depth", "curve", "first_2_min_after_graduation", "last_15_min",
              "return_30_min", "drawdown_from_30_min_high", "airdrop_dump_seen", "alive"}


def test_build_brief_fields_are_json_and_stable():
    ds = _dataset()
    m = ds.mints[0]
    cd = ds.coin(m)
    snap = ds.asof(m, cd.g + 1800.0 + C.DECISION_LAG_S)
    brief = D.build_brief(snap)
    assert set(brief) == BRIEF_KEYS
    assert 29.0 <= brief["age_min"] <= 31.5 and isinstance(brief["class"], str)
    assert brief["name"] is None or len(brief["name"]) <= 40
    assert brief["symbol"] is None or len(brief["symbol"]) <= 16
    assert set(brief["last_15_min"]) == {"buy_sol", "sell_sol", "buyers", "sellers", "volume_usd", "return",
                                         "net_flow_sol"}
    json.dumps(brief)                                                 # plain JSON, nothing exotic
    assert D.brief_hash(brief) == D.brief_hash(D.build_brief(ds.asof(m, cd.g + 1800.0 + C.DECISION_LAG_S)))
    for v in brief.values():                                          # no NaN leaks (they would break the hash)
        if isinstance(v, float):
            assert v == v


def test_build_brief_has_no_lookahead_synthetic():
    """The brief at t is unchanged when every bar after tau is garbage: the desk only ever sees the past."""
    frames = make_frames()
    clean = _dataset(frames)
    rng = np.random.default_rng(5)
    n = 0
    for m in clean.mints[:6]:
        cd = clean.coin(m)
        for dt in (1800.0, 1800.0 + 60.0 * 7, 4500.0):
            t = cd.g + dt + C.DECISION_LAG_S
            dirty = _dataset(_garble(frames, m, t - C.DECISION_LAG_S, rng))
            if m not in dirty.mints:
                continue
            assert D.build_brief(clean.asof(m, t)) == D.build_brief(dirty.asof(m, t))
            n += 1
    assert n >= 10


def test_deliberate_panel_runs_three_memos_then_the_decider():
    cl = D.FakeDeskClient()
    d = D.deliberate(BRIEF, "panel", cl)
    roles = tuple(D.CONFIGS["panel"]["roles"])
    assert len(cl.calls) == len(roles) + 1 and d.buy and d.config == "panel" and d.brief_hash == D.brief_hash(BRIEF)
    assert tuple(d.memos) == roles and d.models == (D.ROLE_MODEL,) * len(roles) + (D.DECIDER_MODEL_PANEL,)
    for r in cl.calls:
        assert r["temperature"] == D.TEMPERATURE == 0.0
        assert r["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert json.loads(r["messages"][0]["content"])["brief"] == BRIEF
    for r in cl.calls[:-1]:                                           # memos are free text
        assert (r.get("output_config") or {}).get("format") is None
    last = cl.calls[-1]
    assert last["output_config"]["format"] == {"type": "json_schema", "schema": D.DECISION_SCHEMA}
    assert json.loads(last["messages"][0]["content"])["panel_memos"] == d.memos
    assert d.prompt_version == D.PROMPT_VERSION and d.error is None and d.cost_usd > 0


def test_deliberate_solo_is_one_call_and_skips_are_skips():
    for cfg in ("solo-haiku", "solo-sonnet"):
        cl = D.FakeDeskClient()
        d = D.deliberate(BRIEF, cfg, cl)
        assert len(cl.calls) == 1 and d.buy and d.memos == {} and d.models == (D.CONFIGS[cfg]["decider_model"],)
    d = D.deliberate({**BRIEF, "class": "ORGANIC"}, "solo-haiku", D.FakeDeskClient())
    assert not d.buy and d.action == "skip" and d.size_usd == 0.0
    assert D.deliberate(BRIEF, "panel", D.FakeDeskClient()).cost_usd > D.deliberate(BRIEF, "solo-haiku",
                                                                                  D.FakeDeskClient()).cost_usd


def test_decision_cache_layout_roundtrip_and_count(tmp_path):
    cache = D.DecisionCache(tmp_path / "dec")
    d = D.deliberate(BRIEF, "solo-haiku", D.FakeDeskClient())
    assert cache.get("solo-haiku", d.brief_hash) is None and cache.count("solo-haiku") == 0
    cache.put(d)
    assert cache.path("solo-haiku", d.brief_hash) == tmp_path / "dec" / D.PROMPT_VERSION / "solo-haiku" / (
        d.brief_hash + ".json")
    assert cache.get("solo-haiku", d.brief_hash) == d
    assert cache.count("solo-haiku") == 1 and cache.count("panel") == 0
    assert cache.get("panel", d.brief_hash) is None                  # one config never reads another's answer


class Flaky(D.FakeDeskClient):
    def __init__(self, fail_first: int):
        super().__init__()
        self.fail_first, self.n = fail_first, 0

    def create(self, **request):
        self.n += 1
        if self.n <= self.fail_first:
            raise ConnectionError("boom")
        return super().create(**request)


def test_decide_cached_hits_charges_and_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(D.time, "sleep", lambda s: None)
    cache = D.DecisionCache(tmp_path / "dec")
    assert D.decide_cached(BRIEF, "solo-haiku", cache, None) is None  # no client: undecided, nothing written
    assert cache.count("solo-haiku") == 0
    budget = D.Budget(max_usd=1.0)
    cl = D.FakeDeskClient()
    d1 = D.decide_cached(BRIEF, "solo-haiku", cache, cl, budget)
    assert d1.buy and budget.calls == 1 and budget.spent_usd == d1.cost_usd > 0
    d2 = D.decide_cached(BRIEF, "solo-haiku", cache, cl, budget)
    assert d2 == d1 and len(cl.calls) == 1 and budget.calls == 1      # cache hit: no API call, no charge
    tight = D.Budget(max_usd=1e-9)
    with pytest.raises(D.BudgetExceeded):
        D.decide_cached({**BRIEF, "name": "other"}, "solo-haiku", cache, cl, tight)
    assert cache.count("solo-haiku") == 2                            # the paid-for decision is kept
    fl = Flaky(2)
    d3 = D.decide_cached({**BRIEF, "name": "third"}, "solo-haiku", cache, fl, D.Budget(max_usd=1.0))
    assert d3.buy and fl.n == 3
    with pytest.raises(ConnectionError):
        D.decide_cached({**BRIEF, "name": "fourth"}, "solo-haiku", cache, Flaky(3), D.Budget(max_usd=1.0))
    assert cache.count("solo-haiku") == 3
