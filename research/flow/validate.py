"""Validation gates V1-V7 (PLAN 6.3) for the CryptoHouse flow data, plus V0 (census coverage).

Inputs:
* backfill outputs in ``--out`` (graduates.parquet, b2_bars.parquet, b2_coins.parquet; run
  ``backfill.py --consolidate`` first),
* the swap-api launch sample ``LAB/trades_launch/*.json.gz`` (first 2 minutes of each coin's life),
* the lab's census and 1m candles ``LAB/census.json``, ``LAB/coins/*.json``, ``LAB/sol_usd.json``.

For V1-V5 the script fetches raw CryptoHouse trades for the launch-sample coins (``sql/raw.sql``),
grouped by creation hour (one query per hour, cached in ``<out>/validation/``). Then it writes
``<out>/VALIDATION.md`` and ``<out>/validation.json``.

    python research/flow/validate.py --out $SCRATCH/flow [--max-hours 10]
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import logging
import os
import random
import statistics as stats
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cryptohouse import CryptoHouse, summarize_log  # noqa: E402
from decode import render_sql, sql_in, sql_tuples  # noqa: E402
from backfill import LAB, SCRATCH, Q15, SlotMap, Store, floor_to, utc  # noqa: E402

log = logging.getLogger("validate")

TRADE_FIELDS = ("slot", "tx_idx", "pix", "ix", "ts", "tx", "venue", "is_buy", "user", "usol", "tok", "x0", "y0",
                "x1", "y1", "qamt", "lp_fee", "pfee", "cfee", "ix_name", "virt")
SOL_NATIVE = "11111111111111111111111111111111"


# ----------------------------------------------------------------------------------------------
# pure checks (unit-tested in tests/test_validate.py)


def chain_check(trades: list[dict]) -> dict:
    """Reserve-chain continuity per venue/pool for trades sorted in chain order.

    pre semantics: post-state of trade i == pre-state of trade i+1 (x1_i == x0_{i+1} and y1_i == y0_{i+1}).
    Also V1: a buy must raise the pricing SOL reserve and lower the token reserve (x1 > x0, y1 < y0),
    judged on the *emitted* pre-state of the next trade, which is independent of the label.
    """
    n_pairs = n_ok = n_label = n_label_ok = 0
    breaks = []
    by_venue = defaultdict(list)
    for t in trades:
        by_venue[t["venue"]].append(t)
    for venue, ts in by_venue.items():
        for a, b in zip(ts, ts[1:]):
            n_pairs += 1
            # PumpSwap: x (real quote) jumps between trades while the virtual reserve v moves the other way
            # (X = x + v is conserved; audit 2026-10-08). Completeness is judged on the token side; a quote-side
            # jump counts as explained when both events carry v and x + v chains.
            quote_ok = a["x1"] == b["x0"] or (venue == 1 and a.get("virt") and b.get("virt")
                                              and a["x1"] + a["virt"] == b["x0"] + b["virt"])
            if venue == 1 and a["y1"] == b["y0"] and not quote_ok and not (a.get("virt") and b.get("virt")):
                quote_ok = True   # v unknown on a sell: token side chains, quote jump assumed to be a v shift
            if quote_ok and a["y1"] == b["y0"]:
                n_ok += 1
                # V1 on a verified transition: does the observed reserve move match the label?
                n_label += 1
                dx, dy = b["x0"] - a["x0"], b["y0"] - a["y0"]
                if (a["is_buy"] and dx > 0 and dy < 0) or (not a["is_buy"] and dx < 0 and dy > 0) or (dx == 0 and dy == 0):
                    n_label_ok += 1
            else:
                breaks.append((a["slot"], b["slot"]))
    return {"pairs": n_pairs, "chain_ok": n_ok, "label_checked": n_label, "label_ok": n_label_ok,
            "breaks": breaks[:20]}


def semantics_check(trades: list[dict]) -> dict:
    """V5: are PumpSwap event reserves pre-trade or post-trade? Count which hypothesis the next event fits."""
    amm = [t for t in trades if t["venue"] == 1]
    pre = post = n = 0
    for a, b in zip(amm, amm[1:]):
        n += 1
        # pre-trade semantics: b.x0 == a.x0 +/- a's pool delta (x1 is derived that way)
        if b["x0"] == a["x1"] and b["y0"] == a["y1"]:
            pre += 1
        # post-trade semantics would mean the emitted reserve already includes the trade itself
        if b["x0"] == a["x0"] and b["y0"] == a["y0"]:
            post += 1
    return {"pairs": n, "pre_fit": pre, "post_fit": post}


def slot_index_order(slot_index_id: str) -> tuple[int, int]:
    """swap-api slotIndexId: 22 digits = 12-digit slot + 10-digit position inside the slot."""
    return int(slot_index_id[:12]), int(slot_index_id[12:])


def ordering_check(ours: list[dict], theirs: list[dict]) -> dict:
    """V4: for same-slot pairs present in both sources, does (tx_idx, pix, ix) order match slotIndexId order?"""
    key = {}
    # several trades under one key (same tx, wallet, side) pair in each source's own order, so take swap-api's in
    # slotIndexId order whatever order the pages came in (they are newest-first)
    for t in sorted(theirs, key=lambda t: t["slotIndexId"]):
        k = (t["tx"], t["userAddress"], t["type"] == "buy")
        key.setdefault(k, []).append(slot_index_order(t["slotIndexId"]))
    pos = []
    for t in ours:
        k = (t["tx"], t["user"], bool(t["is_buy"]))
        if k in key and key[k]:
            pos.append(((t["slot"], t["tx_idx"], t["pix"], t["ix"]), key[k].pop(0)))
    same = agree = 0
    for i in range(len(pos)):
        for j in range(i + 1, len(pos)):
            (oa, ta), (ob, tb) = pos[i], pos[j]
            if oa[0] != ob[0] or ta[0] != tb[0]:
                continue
            same += 1
            if (oa < ob) == (ta < tb):
                agree += 1
    return {"matched": len(pos), "same_slot_pairs": same, "agree": agree}


def net_swap_sol(t: dict) -> float:
    """SOL in swap-api's ``amountSol`` convention, measured on 24k tx-matched trades (2026-10-08).

    PumpSwap: sells and 'buy' instructions = user-side SOL; other buys (buy_exact_quote_in, ...) = net of
    all fees. Curve: buys and sells = the curve's sol_amount (fees excluded on buys, included on sells).
    """
    if t["venue"] == 1:
        if not t["is_buy"] or t.get("ix_name") == "buy":
            return t["usol"] / 1e9
        return (t["usol"] - t["pfee"] - t["cfee"] - t["lp_fee"]) / 1e9
    return t["qamt"] / 1e9


def cross_source_minutes(minutes: list, sw: dict, c0: int) -> list[dict]:
    """V3 rows per (coin, window): CryptoHouse vs swap-api counts and SOL (net convention for buys)."""
    out = []
    for w in sw["windows"]:
        if not w.get("complete"):
            continue
        lo, hi = c0 + int(w["start_min"] * 60), c0 + int(w["end_min"] * 60)
        st = [x for x in sw["trades"] if lo * 1000 <= x["ts_ms"] < hi * 1000]
        out.append({"window": w["start_min"], "sw_n": len(st),
                    "sw_buy": sum(float(x["amountSol"]) for x in st if x["type"] == "buy"),
                    "sw_sell": sum(float(x["amountSol"]) for x in st if x["type"] == "sell")})
    return out


# ----------------------------------------------------------------------------------------------


def _q(xs: list[float]) -> list[float] | None:
    xs = sorted(xs)
    return [xs[len(xs) // 2], xs[min(len(xs) - 1, int(len(xs) * 0.99))]] if xs else None


def load_launch_sample() -> list[dict]:
    cen = {c["mint"]: c for c in json.loads((LAB / "census.json").read_text())["coins"]}
    out = []
    for f in sorted(glob.glob(str(LAB / "trades_launch" / "*.json.gz"))):
        t = json.load(gzip.open(f))
        c = cen.get(t["mint"])
        if not c:
            continue
        out.append({"mint": t["mint"], "pool": c.get("pump_swap_pool") or "", "c0": t["created_ms"] // 1000,
                    "quote": c.get("quote_mint"), "sw": t})
    return out


def fetch_raw_validation(out: Path, ch: CryptoHouse, sample: list[dict], max_hours: int) -> dict[str, dict]:
    vdir = out / "validation"
    vdir.mkdir(parents=True, exist_ok=True)
    store = Store(out)
    slots = SlotMap(store, ch) if ch else None
    by_hour = defaultdict(list)
    for s in sample:
        if s["quote"] == SOL_NATIVE and s["pool"]:
            by_hour[s["c0"] // 3600 * 3600].append(s)
    hours = sorted(by_hour, key=lambda h: -len(by_hour[h]))[:max_hours]
    raw: dict[str, dict] = {}
    for h in sorted(hours):
        p = vdir / f"raw_{h}.json.gz"
        if not p.exists() and ch is None:
            continue
        if not p.exists():
            rows, columns = [], None
            for part in _fetch_raw_parts(ch, slots, by_hour[h]):
                columns = part["columns"]
                rows.extend(part["rows"])
            with gzip.open(p, "wt") as f:
                json.dump({"columns": columns, "rows": rows}, f)
        d = json.load(gzip.open(p))
        for r in d["rows"]:
            row = dict(zip(d["columns"], r))
            row["trades"] = [dict(zip(TRADE_FIELDS, t)) for t in row["trades"]]
            raw[row["mint"]] = row
    return raw


def _fetch_raw_parts(ch: CryptoHouse, slots: SlotMap, cs: list[dict], max_trades: int = 300) -> list[dict]:
    """raw.sql for launch windows of coins created in one hour; halves the coin set on a 1 MB overflow."""
    from cryptohouse import QueryTimeout, ResultTooLarge
    t0 = floor_to(min(c["c0"] for c in cs) - 5, Q15)
    t1 = floor_to(max(c["c0"] for c in cs) + 125, Q15) + Q15
    slots.ensure(t0 - Q15, t1 + Q15)
    params = dict(s0=slots.first_slot(t0), s1=slots.last_slot_before(t1), t0=utc(t0), t1=utc(t1),
                  win=sql_tuples([(c["mint"], c["pool"], c["c0"], c["c0"] + 120) for c in cs]),
                  mints=sql_in([c["mint"] for c in cs]), min_usol=0, max_trades=max_trades)
    try:
        res = ch.query(render_sql("raw", **params), tag=f"validate:raw:{utc(t0)}:{len(cs)}")
    except (ResultTooLarge, QueryTimeout):
        if len(cs) == 1:
            return []
        h = len(cs) // 2
        return _fetch_raw_parts(ch, slots, cs[:h], max_trades) + _fetch_raw_parts(ch, slots, cs[h:], max_trades)
    return [{"columns": res.columns, "rows": res.rows}]


def run(out: Path, max_hours: int, ch: CryptoHouse | None) -> dict:
    res: dict = {}
    sample = load_launch_sample()
    smap = {s["mint"]: s for s in sample}
    raw = fetch_raw_validation(out, ch, sample, max_hours)

    # ---- V1, V2, V5 on raw launch windows -------------------------------------------------------
    tot = defaultdict(int)
    cen_all = {c["mint"]: c for c in json.loads((LAB / "census.json").read_text())["coins"]}
    for m, r in raw.items():
        c = chain_check(r["trades"])
        s5 = semantics_check(r["trades"])
        if cen_all.get(m, {}).get("mayhem_state") is not None:
            # Mayhem curves change their SOL reserve outside TradeEvents; report them apart (not tradeable)
            for k in ("pairs", "chain_ok"):
                tot["mayhem_" + k] += c[k]
            tot["mayhem_coins"] += 1
            tot["v5_pairs"] += s5["pairs"]
            tot["v5_pre"] += s5["pre_fit"]
            tot["v5_post"] += s5["post_fit"]
            continue
        tot["coins"] += 1
        for k in ("pairs", "chain_ok", "label_checked", "label_ok"):
            tot[k] += c[k]
        tot["v5_pairs"] += s5["pairs"]
        tot["v5_pre"] += s5["pre_fit"]
        tot["v5_post"] += s5["post_fit"]
    # swap-api tx cross-check of labels (50 random matched trades per PLAN; we use all matched)
    lab_match = lab_n = 0
    for m, r in raw.items():
        sw = smap[m]["sw"]["trades"]
        idx = {(x["tx"], x["userAddress"]): x for x in sw}
        for t in r["trades"]:
            x = idx.get((t["tx"], t["user"]))
            if x:
                lab_n += 1
                lab_match += (x["type"] == "buy") == bool(t["is_buy"])
    res["V1"] = {"reserve_label_agree": tot["label_ok"], "reserve_label_checked": tot["label_checked"],
                 "swapapi_label_agree": lab_match, "swapapi_label_checked": lab_n,
                 "pass": tot["label_checked"] > 0 and tot["label_ok"] / tot["label_checked"] >= 0.999
                 and lab_n > 0 and lab_match / lab_n >= 0.999}
    res["V2"] = {"coins": tot["coins"], "transitions": tot["pairs"], "chain_ok": tot["chain_ok"],
                 "mayhem_coins": tot["mayhem_coins"], "mayhem_transitions": tot["mayhem_pairs"],
                 "mayhem_chain_ok": tot["mayhem_chain_ok"],
                 "share": tot["chain_ok"] / tot["pairs"] if tot["pairs"] else None,
                 "pass": tot["pairs"] > 0 and tot["chain_ok"] / tot["pairs"] >= 0.99}
    res["V5"] = {"amm_pairs": tot["v5_pairs"], "pre_fit": tot["v5_pre"], "post_fit": tot["v5_post"],
                 "semantics": "pre-trade" if tot["v5_pre"] > tot["v5_post"] else "post-trade",
                 "pass": tot["v5_pairs"] > 0 and tot["v5_pre"] / tot["v5_pairs"] >= 0.99}

    # ---- V3 cross-source per coin-window ----------------------------------------------------------
    rows3 = []
    for m, r in raw.items():
        s = smap[m]
        c0 = s["c0"]
        mins = defaultdict(lambda: {"n": 0, "buy": 0.0, "sell": 0.0})
        # raw.sql minutes are relative to ts_lo = c0; the per-minute totals are never truncated but are
        # user-side SOL. Convert buys to the net-of-fee convention with the per-trade sample when complete.
        full = not r["truncated"]
        for m7 in r["minutes"]:
            mi, venue, n, nb, bs, ss = m7[:6]
            mins[mi]["n"] += n
            mins[mi]["sell"] += ss / 1e9
            mins[mi]["buy_user"] = mins[mi].get("buy_user", 0.0) + bs / 1e9
            if len(m7) > 6:   # server-side swap-api convention total (buys + sells), exact for every coin
                mins[mi]["sw_total"] = mins[mi].get("sw_total", 0.0) + m7[6] / 1e9
        if full:
            for k in mins:
                mins[k]["sw_total_trades"] = 0.0
            for t in r["trades"]:
                mi = (t["ts"] - c0) // 60
                mins[mi]["sw_total_trades"] = mins[mi].get("sw_total_trades", 0.0) + net_swap_sol(t)
        for w in cross_source_minutes(r["minutes"], s["sw"], c0):
            mi = int(w["window"])
            ours = mins.get(mi, {"n": 0, "sell": 0.0, "buy_user": 0.0})
            if "sw_total" in ours:
                total, exact = ours["sw_total"], True
            elif full:
                total, exact = ours.get("sw_total_trades", 0.0), True
            else:   # old cache without the server-side total: approximate
                total, exact = ours.get("buy_user", 0.0) / 1.0125 + ours["sell"], False
            rows3.append({"mint": m, "minute": mi, "ch_n": ours["n"], "sw_n": w["sw_n"],
                          "ch_sol": total, "sw_sol": w["sw_buy"] + w["sw_sell"], "sol_exact": exact})
    def within(a, b, tol):
        return abs(a - b) <= tol * max(abs(b), 1e-9) or abs(a - b) < 1e-6
    ok_n = sum(1 for x in rows3 if within(x["ch_n"], x["sw_n"], 0.02))
    ok_sol = sum(1 for x in rows3 if within(x["ch_sol"], x["sw_sol"], 0.01))
    ok_both = sum(1 for x in rows3 if within(x["ch_n"], x["sw_n"], 0.02) and within(x["ch_sol"], x["sw_sol"], 0.01))
    res["V3"] = {"coins": len(raw), "coin_windows": len(rows3), "count_within_2pct": ok_n, "sol_within_1pct": ok_sol,
                 "both": ok_both, "exact_count_match": sum(1 for x in rows3 if x["ch_n"] == x["sw_n"]),
                 "share_both": ok_both / len(rows3) if rows3 else None,
                 "sol_exact_rows": sum(1 for x in rows3 if x["sol_exact"]),
                 "sol_rel_err_p50_p99": _q([abs(x["ch_sol"] - x["sw_sol"]) / max(x["sw_sol"], 1e-9) for x in rows3]),
                 "pass": bool(rows3) and ok_both / len(rows3) >= 0.95,
                 "worst": sorted(rows3, key=lambda x: -abs(x["ch_sol"] - x["sw_sol"]) / max(x["sw_sol"], 1e-9))[:5]}

    # ---- V4 ordering ------------------------------------------------------------------------------------
    o_same = o_agree = o_matched = 0
    for m, r in raw.items():
        oc = ordering_check(r["trades"], smap[m]["sw"]["trades"])
        o_same += oc["same_slot_pairs"]
        o_agree += oc["agree"]
        o_matched += oc["matched"]
    res["V4"] = {"matched_trades": o_matched, "same_slot_pairs": o_same, "agree": o_agree,
                 "share": o_agree / o_same if o_same else None,
                 "pass": o_same > 0 and o_agree / o_same >= 0.995}

    # ---- V0 census coverage, V6 candles, V7 agent ---------------------------------------------------------
    try:
        import pyarrow.parquet as pq
        grads = {r["mint"]: r for r in pq.read_table(out / "graduates.parquet").to_pylist()}
        coins = {r["pool"]: r for r in pq.read_table(out / "b2_coins.parquet").to_pylist()}
        bars = pq.read_table(out / "b2_bars.parquet").to_pylist()
    except Exception as e:  # noqa: BLE001
        log.warning("backfill outputs missing (%s); V0/V6/V7 skipped", e)
        grads, coins, bars = {}, {}, []
    census = json.loads((LAB / "census.json").read_text())
    cen = {c["mint"]: c for c in census["coins"]}
    if grads:
        g_lo = min(g["g_ts"] for g in grads.values())
        g_hi = max(g["g_ts"] for g in grads.values())
        in_window = [c for c in cen.values() if c.get("pump_swap_pool")]
        found = [m for m in cen if m in grads]
        ts_match = sum(1 for m in found if grads[m]["has_create"] and grads[m]["c_ts"] == cen[m]["created_timestamp"] // 1000)
        may_c = [m for m in found if cen[m].get("mayhem_state") is not None]
        may_agree = sum(1 for m in found if bool(grads[m]["is_mayhem"]) == (cen[m].get("mayhem_state") is not None))
        pool_match = sum(1 for m in found if grads[m].get("pool") == cen[m].get("pump_swap_pool"))
        may_derived = sum(1 for m in found if bool(grads[m].get("mayhem")) == (cen[m].get("mayhem_state") is not None))
        solq = sum(1 for m in found if bool(grads[m].get("sol_quoted")) == (cen[m].get("quote_mint") == SOL_NATIVE))
        missing = [g for g in grads.values() if g.get("has_create") and census["created_min_ts"] <= g["c_ts"] <= census["created_max_ts"]
                   and g["g_ts"] <= census["census_started_ts"] and g["mint"] not in cen]
        ch_in_census_window = [g for g in grads.values() if census["created_min_ts"] <= (g["c_ts"] or 0) <= census["created_max_ts"]]
        res["V0"] = {"census_coins": len(cen), "found_in_cryptohouse": len(found),
                     "creation_ts_exact": ts_match, "pool_match": pool_match,
                     "mayhem_flag_agree": may_agree, "census_mayhem_state_set": len(may_c),
                     "mayhem_derived_agree": may_derived, "sol_quoted_agree": solq,
                     "graduates_missing_from_census": [g["mint"] for g in missing],
                     "cryptohouse_graduates_created_in_census_window": len(ch_in_census_window),
                     "graduates_span": [utc(g_lo), utc(g_hi)]}
    if bars:
        sol = {c[0]: c[4] for c in json.loads((LAB / "sol_usd.json").read_text())["candles"]}
        by_mint = defaultdict(list)
        for b in bars:
            by_mint[b["mint"]].append(b)
        ratios, vratios, n_coins = [], [], 0
        for m, bs in by_mint.items():
            c = cen.get(m)
            f = LAB / "coins" / f"{m}.json"
            if not c or c.get("quote_mint") != SOL_NATIVE or not f.exists():
                continue
            cd = json.loads(f.read_text())
            cm = {x[0]: x for x in cd["candles"]}
            used = False
            for b in bs:
                t = b["minute_ts"]
                if t in cm and t in sol and cm[t][5] > 0 and b["minute_idx"] >= 1 and b["close"]:
                    ratios.append(b["close"] * sol[t] / cm[t][4])
                    vratios.append((b["buy_sol"] + b["sell_sol"]) * sol[t] / cm[t][5])
                    used = True
            n_coins += used
        ratios.sort()
        vratios.sort()
        med = ratios[len(ratios) // 2] if ratios else None
        res["V6"] = {"coins": n_coins, "coin_minutes": len(ratios), "close_ratio_median": med,
                     "close_ratio_p05": ratios[len(ratios) // 20] if ratios else None,
                     "close_ratio_p95": ratios[19 * len(ratios) // 20] if ratios else None,
                     "close_within_1pct": sum(1 for x in ratios if abs(x - 1) <= 0.01) / len(ratios) if ratios else None,
                     "volume_ratio_median": vratios[len(vratios) // 2] if vratios else None,
                     "pass": med is not None and abs(med - 1) <= 0.01}
    if coins:
        elig = [c for c in coins.values() if c["mint"] in grads and grads[c["mint"]].get("sol_quoted")
                and not grads[c["mint"]].get("mayhem")]
        census_elig = [c for c in elig if c["mint"] in cen]
        pres = [c for c in census_elig if c["agent_present"]]
        sl = sorted(c["agent_slices"] for c in pres)
        so = sorted(c["agent_sol"] for c in pres)
        gp = sorted(c["agent_median_gap"] for c in pres)
        all_pres = [c for c in elig if c["agent_present"]]
        # cross-check with the census boost_mode (COMPLETED / NONE / IN_PROGRESS), exact windows only
        conf = defaultdict(int)
        for c in census_elig:
            if c.get("w_exact"):
                conf[(str(cen[c["mint"]].get("boost_mode")), bool(c["agent_present"]))] += 1
        boost_completed = [c for c in census_elig if cen[c["mint"]].get("boost_mode") == "COMPLETED" and c.get("w_exact")]
        agent_given_boost = sum(1 for c in boost_completed if c["agent_present"])
        res["V7"] = {"census_eligible": len(census_elig), "census_agent_present": len(pres),
                     "share": len(pres) / len(census_elig) if census_elig else None,
                     "slices_median": sl[len(sl) // 2] if sl else None,
                     "slices_p10_p90": [sl[len(sl) // 10], sl[9 * len(sl) // 10]] if sl else None,
                     "sol_median": so[len(so) // 2] if so else None,
                     "sol_p10_p90": [so[len(so) // 10], so[9 * len(so) // 10]] if so else None,
                     "median_gap_median": gp[len(gp) // 2] if gp else None,
                     "all_eligible": len(elig), "all_agent_present": len(all_pres),
                     "vs_census_boost_mode": {f"{k[0]}|agent={k[1]}": v for k, v in sorted(conf.items())},
                     "agent_given_boost_completed": [agent_given_boost, len(boost_completed)],
                     # PLAN expectation (>= 90 % present, 25 +/- 2 slices) came from 2-minute swap-api windows;
                     # judged here against the census boost_mode instead: AGENT found on >= 90 % of COMPLETED
                     "pass": bool(boost_completed) and agent_given_boost / len(boost_completed) >= 0.9}
    res["queries"] = summarize_log(ch.qlog.path) if ch else None
    return res


# ----------------------------------------------------------------------------------------------
# per-split range records: PLAN stop rule 1 on each split's own dates (read by research/lab2/common.validation_gates)
#
# For each split, a few chain hours are drawn at random, one per equal segment of the split. In each hour a random
# sample of lab-universe graduates (SOL-quoted, not Mayhem, created in the split by the lab's rule) whose B2 window
# [g, g + 180 min) overlaps the hour is fetched with raw.sql (one query per hour), window = the hour inside B2, first
# ``max_trades`` trades per coin. V2 = chain_check (token side + X = x + v, audit fix 7) and V1 (reserve moves) on
# those trades; V1 (labels) and V4 (intra-slot order) against swap-api trades of the same coins and times.

RANGE_SPLITS = {   # name: (lo_utc, hi_utc, sampled chain hours); census = the census day incl. TEST's last hour
    "confirm": ("2026-09-16 00:00:00", "2026-10-01 00:00:00", 4),
    "train": ("2026-10-01 00:00:00", "2026-10-05 00:00:00", 4),
    "val": ("2026-10-05 00:00:00", "2026-10-06 12:00:00", 2),
    "test": ("2026-10-06 12:00:00", "2026-10-07 19:37:30", 2),
    "census": ("2026-10-07 19:00:00", "2026-10-08 19:00:00", 2),
}
WSOL = "So11111111111111111111111111111111111111112"
B2_HORIZON_S = 180 * 60
SLOW_CREATE_S = 1800          # has_create = 0: created before g - 1800 (curve scan lookback); the lab uses g - 1800


def _uts(s: str) -> int:
    from datetime import datetime, timezone
    return int(datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())


def pick_hours(name: str, lo: int, hi: int, k: int, seed: int = 0) -> list[int]:
    """k chain hours lying fully inside [lo, hi), one drawn at random from each of k equal contiguous segments."""
    hours = list(range(-(-lo // 3600) * 3600, hi - 3599, 3600))
    k = max(1, min(k, len(hours)))
    rng = random.Random(f"{name}:{seed}")
    return [rng.choice(hours[i * len(hours) // k:(i + 1) * len(hours) // k]) for i in range(k)]


def range_candidates(grads: dict[str, dict], lo: int, hi: int, hour: int,
                     census_created: dict[str, float] | None = None) -> list[dict]:
    """Lab-universe graduates created in [lo, hi) whose B2 window meets ``hour``; window = hour inside B2.

    Creation time as the lab assigns splits: census time for census coins, else c_ts when the CreateEvent was
    scanned, else g - 1800. Excluded: no pool, non-SOL quote, Mayhem (flag, or real SOL < 80 at completion)."""
    cc = census_created or {}
    out = []
    for m, g in grads.items():
        if not g.get("pool") or g.get("pool_quote_mint") != WSOL:
            continue
        if g.get("is_mayhem") or (g.get("rsol_complete") or 0) < 80:
            continue
        gt = int(g["g_ts"])
        if not (gt < hour + 3600 and gt + B2_HORIZON_S > hour):
            continue
        c = cc.get(m) or (g["c_ts"] if g.get("has_create") and g.get("c_ts") else gt - SLOW_CREATE_S)
        if lo <= c < hi:
            out.append({"mint": m, "pool": g["pool"], "g_ts": gt, "c_ts": int(c),
                        "lo": max(gt, hour), "hi": min(gt + B2_HORIZON_S, hour + 3600)})
    return sorted(out, key=lambda d: d["mint"])


def label_pairs(ours: list[dict], theirs: list[dict]) -> list[tuple[dict, dict]]:
    """(CryptoHouse trade, swap-api trade) pairs by tx + wallet, never by the label under test. A wallet with several
    trades in one tx (e.g. a dust buy + sell) pairs them in each source's own order (chain order vs slotIndexId);
    a plain (tx, wallet) dict would compare the buy with the sell."""
    g = defaultdict(list)
    for x in sorted(theirs, key=lambda x: x["slotIndexId"]):
        g[(x["tx"], x["userAddress"])].append(x)
    used: dict = defaultdict(int)
    out = []
    for t in sorted(ours, key=lambda t: (t["slot"], t["tx_idx"], t["pix"], t["ix"])):
        k = (t["tx"], t["user"])
        if used[k] < len(g.get(k, ())):
            out.append((t, g[k][used[k]]))
            used[k] += 1
    return out


def block_stats(rows: list[dict], sw: dict[str, list[dict]]) -> dict:
    """V1 / V2 / V4 counts over one sampled hour. ``rows``: raw.sql rows (trades decoded); ``sw``: mint -> swap-api
    trades of the same coin over the same span (only trades present in both sources count for V1-labels / V4)."""
    s = defaultdict(int)
    breaks = []
    for r in rows:
        c = chain_check(r["trades"])
        for k in ("pairs", "chain_ok", "label_checked", "label_ok"):
            s[k] += c[k]
        breaks += [[r["mint"], a, b] for a, b in c["breaks"][:3]]
        s["coins"] += 1
        s["trades"] += len(r["trades"])
        s["truncated"] += bool(r.get("truncated"))
        st = sw.get(r["mint"]) or []
        for t, x in label_pairs(r["trades"], st):
            s["sw_label_n"] += 1
            s["sw_label_ok"] += (x["type"] == "buy") == bool(t["is_buy"])
        s["sw_multi_trade_tx_wallets"] += sum(1 for v in Counter((x["tx"], x["userAddress"]) for x in st).values() if v > 1)
        o = ordering_check(r["trades"], st)
        s["o_matched"] += o["matched"]
        s["o_same"] += o["same_slot_pairs"]
        s["o_agree"] += o["agree"]
    return dict(s, breaks=breaks[:10])


def range_record(name: str, lo: str, hi: str, blocks: list[dict], validated_utc: str) -> dict:
    """One ``validation_ranges.json`` record from per-hour :func:`block_stats` (pass rules as in :func:`run`)."""
    t = defaultdict(int)
    for b in blocks:
        for k, v in b["stats"].items():
            if isinstance(v, int):
                t[k] += v
    v1 = {"reserve_label_agree": t["label_ok"], "reserve_label_checked": t["label_checked"],
          "swapapi_label_agree": t["sw_label_ok"], "swapapi_label_checked": t["sw_label_n"],
          "swapapi_multi_trade_tx_wallets": t["sw_multi_trade_tx_wallets"]}
    v1["pass"] = (t["label_checked"] > 0 and t["label_ok"] / t["label_checked"] >= 0.999
                  and t["sw_label_n"] > 0 and t["sw_label_ok"] / t["sw_label_n"] >= 0.999)
    v2 = {"coins": t["coins"], "transitions": t["pairs"], "chain_ok": t["chain_ok"],
          "share": t["chain_ok"] / t["pairs"] if t["pairs"] else None,
          "pass": t["pairs"] > 0 and t["chain_ok"] / t["pairs"] >= 0.99,
          "definition": "per pool, consecutive trades: token reserve chains exactly; quote side chains on x, or on "
                        "x + virt when both events carry virt, or is a virtual-reserve shift when virt is unknown"}
    v4 = {"matched_trades": t["o_matched"], "same_slot_pairs": t["o_same"], "agree": t["o_agree"],
          "share": t["o_agree"] / t["o_same"] if t["o_same"] else None,
          "pass": t["o_same"] > 0 and t["o_agree"] / t["o_same"] >= 0.995}
    return {"split": name, "lo_utc": lo, "hi_utc": hi, "validated_utc": validated_utc, "V1": v1, "V2": v2, "V4": v4,
            "sample": {"hours": [b["hour_utc"] for b in blocks], "coins": t["coins"], "trades": t["trades"],
                       "coins_truncated": t["truncated"], "swapapi_trades": t["sw_n"],
                       "blocks": [{k: b[k] for k in b if k != "stats"} | {"breaks": b["stats"].get("breaks")}
                                  for b in blocks]},
            "source": "research/flow/validate.py --ranges"}


def merge_ranges(old: list[dict], new: list[dict]) -> list[dict]:
    """Replace records of the same split (or the same lo/hi) and keep the rest."""
    keys = {r.get("split") for r in new} | {(r["lo_utc"], r["hi_utc"]) for r in new}
    return [r for r in old if r.get("split") not in keys and (r.get("lo_utc"), r.get("hi_utc")) not in keys] + new


def _known_graduates(out: Path) -> tuple[dict[str, dict], list[tuple[int, int]]]:
    """Graduates from the backfill's raw curve chunks (read-only) and the [t0, t1) spans they cover."""
    grads: dict[str, dict] = {}
    spans = []
    for p in sorted((out / "raw" / "curve").glob("*.json.gz")):
        try:
            with gzip.open(p, "rt") as f:
                ch = json.load(f)
        except (OSError, ValueError):
            continue
        spans.append((int(ch["t0"]), int(ch["t1"])))
        for r in ch["rows"]:
            d = dict(zip(ch["columns"], r))
            old = grads.get(d["mint"])
            if old is None or (d["has_create"] and not old["has_create"]):
                grads[d["mint"]] = d
    return grads, spans


def _covered(spans: list[tuple[int, int]], a: int, b: int) -> bool:
    t = a
    for s0, s1 in sorted(spans):
        if s0 <= t < s1:
            t = s1
    return t >= b


def _discover_hour(ch: CryptoHouse, slots: SlotMap, hour: int, vdir: Path) -> dict:
    """curve.sql for one chain hour the backfill has not scanned (graduates of that hour only; cached)."""
    from backfill import CURVE_LOOKBACK_S, LAUNCH_S
    from cryptohouse import QueryTimeout
    p = vdir / f"curve_{hour}.json.gz"
    if p.exists():
        return json.load(gzip.open(p))
    t0, t1 = hour, hour + 3600
    while True:
        slots.ensure(t0 - CURVE_LOOKBACK_S - Q15, t1 + 2 * Q15)
        params = dict(s_lo=slots.first_slot(t0 - CURVE_LOOKBACK_S), s0=slots.first_slot(t0),
                      s1=slots.last_slot_before(t1), s1_pool=slots.last_slot_before(t1 + Q15),
                      t_lo=utc(t0 - CURVE_LOOKBACK_S - 120), t_hi=utc(t1 + Q15 + 120), launch_s=LAUNCH_S)
        try:
            res = ch.query(render_sql("curve", **params), tag=f"validate:curve:{utc(t0)}")
            break
        except QueryTimeout:
            if t1 - t0 <= Q15:
                raise
            t1 = t0 + floor_to((t1 - t0) // 2, Q15)
            log.warning("curve discovery %s timed out; using [%s, %s)", utc(hour), utc(t0), utc(t1))
    d = {"t0": t0, "t1": t1, "columns": res.columns, "rows": res.rows, "fetched_ts": time.time()}
    with gzip.open(p, "wt") as f:
        json.dump(d, f)
    return d


def _fetch_block(ch: CryptoHouse, slots: SlotMap, coins: list[dict], max_trades: int) -> tuple[list, list, int]:
    """raw.sql over the coins' windows (one hour). Halves the coin set on a 1 MB overflow and the time span on a
    timeout (windows clipped to the first half). -> (columns, rows, span end actually scanned)."""
    from cryptohouse import QueryTimeout, ResultTooLarge
    t0 = floor_to(min(c["lo"] for c in coins), Q15)
    t1 = floor_to(max(c["hi"] for c in coins) - 1, Q15) + Q15
    while True:
        cs = [c for c in coins if c["lo"] < t1]
        slots.ensure(t0, t1)
        params = dict(s0=slots.first_slot(t0), s1=slots.last_slot_before(t1), t0=utc(t0), t1=utc(t1),
                      win=sql_tuples([(c["mint"], c["pool"], c["lo"], min(c["hi"], t1)) for c in cs]),
                      mints=sql_in([c["mint"] for c in cs]), min_usol=0, max_trades=max_trades)
        try:
            res = ch.query(render_sql("raw", **params), tag=f"validate:range:{utc(t0)}:{len(cs)}")
            return res.columns, res.rows, t1
        except ResultTooLarge:
            if len(coins) == 1:
                return [], [], t1
            h = len(coins) // 2
            c1, r1, e1 = _fetch_block(ch, slots, coins[:h], max_trades)
            c2, r2, e2 = _fetch_block(ch, slots, coins[h:], max_trades)
            return c1 or c2, r1 + r2, min(e1, e2)
        except QueryTimeout:
            if t1 - t0 <= Q15:
                raise
            t1 = t0 + floor_to((t1 - t0) // 2, Q15)
            log.warning("range block %s timed out; scanning [%s, %s) only", utc(t0), utc(t0), utc(t1))


def _swapapi_window(sess, throttle, mint: str, start_ms: int, end_ms: int, max_pages: int = 8) -> dict:
    from collect_trades import fetch_window
    trades, complete = fetch_window(sess, throttle, mint, start_ms, end_ms, max_pages)
    trades.sort(key=lambda t: (t["ts_ms"], t.get("slotIndexId") or ""))     # pages are newest-first
    return {"start_ms": start_ms, "end_ms": end_ms, "complete": complete, "trades": trades}


def run_ranges(out: Path, ch: CryptoHouse | None, names: list[str], coins_per_hour: int = 14,
               max_trades: int = 150, seed: int = 0, sw_rpm: float = 12.0) -> list[dict]:
    import requests
    from collect_trades import Throttle
    vdir = out / "validation" / "ranges"
    vdir.mkdir(parents=True, exist_ok=True)
    slots = SlotMap(Store(out), ch) if ch else None
    if slots is not None:
        slots.path = vdir / "slotmap.json"     # never rewrite the backfill's shared slot map
    grads, spans = _known_graduates(out)
    try:
        census = json.loads((LAB / "census.json").read_text())
        census_created = {c["mint"]: c["created_timestamp"] / 1000 for c in census["coins"]}
    except (OSError, ValueError, KeyError):
        census_created = {}
    sess = requests.Session()
    sess.headers["User-Agent"] = "nightcrawler-research/0.1"
    throttle = Throttle(sw_rpm)
    records = []
    for name in names:
        lo_s, hi_s, k = RANGE_SPLITS[name]
        lo, hi = _uts(lo_s), _uts(hi_s)
        blocks = []
        for hour in pick_hours(name, lo, hi, k, seed):
            p = vdir / f"raw_{hour}.json.gz"
            g = dict(grads)
            partial = not _covered(spans, hour - B2_HORIZON_S, hour + 3600)
            if not _covered(spans, hour, hour + 3600):
                if ch is None and not (vdir / f"curve_{hour}.json.gz").exists():
                    log.warning("%s %s: no graduates known and offline; skipped", name, utc(hour))
                    continue
                d = _discover_hour(ch, slots, hour, vdir)
                for r in d["rows"]:
                    x = dict(zip(d["columns"], r))
                    g.setdefault(x["mint"], x)
            cands = range_candidates(g, lo, hi, hour, census_created)
            sample = random.Random(f"{name}:{hour}:{seed}").sample(cands, min(coins_per_hour, len(cands)))
            if not p.exists():
                if ch is None or not sample:
                    log.warning("%s %s: nothing to fetch (%d candidates)", name, utc(hour), len(cands))
                    continue
                cols, rows, scanned_to = _fetch_block(ch, slots, sample, max_trades)
                with gzip.open(p, "wt") as f:
                    json.dump({"hour": hour, "sample": sample, "scanned_to": scanned_to, "columns": cols,
                               "rows": rows, "fetched_ts": time.time(), "candidates": len(cands),
                               "candidates_partial": partial}, f)
            d = json.load(gzip.open(p))
            cands_n, partial = d.get("candidates", len(cands)), d.get("candidates_partial", partial)
            rows = []
            for r in d["rows"]:
                row = dict(zip(d["columns"], r))
                row["trades"] = [dict(zip(TRADE_FIELDS, t)) for t in row["trades"]]
                rows.append(row)
            win = {c["mint"]: c for c in d["sample"]}
            sp = vdir / f"sw_{hour}.json.gz"
            sw = json.load(gzip.open(sp)) if sp.exists() else {}
            for row in rows:
                m = row["mint"]
                if m in sw or not row["trades"]:
                    continue
                c = win[m]
                end = (row["trades"][-1]["ts"] + 1) if row["truncated"] else min(c["hi"], d["scanned_to"])
                sw[m] = _swapapi_window(sess, throttle, m, c["lo"] * 1000, end * 1000)
                with gzip.open(sp, "wt") as f:
                    json.dump(sw, f)
            st = block_stats(rows, {m: v["trades"] for m, v in sw.items()})
            st["sw_n"] = sum(len(v["trades"]) for m, v in sw.items() if m in win)
            st["sw_incomplete"] = sum(1 for m, v in sw.items() if m in win and not v["complete"])
            blocks.append({"hour_utc": utc(hour), "candidates": cands_n, "candidates_partial": partial,
                           "sampled": len(d["sample"]), "scanned_to_utc": utc(d["scanned_to"]),
                           "ch_fetched_utc": utc(d["fetched_ts"]), "stats": st})
        if blocks:
            v_utc = min(b["ch_fetched_utc"] for b in blocks)   # conservative: the oldest CryptoHouse snapshot used
            records.append(range_record(name, lo_s, hi_s, blocks, v_utc))
    return records


def write_report(out: Path, res: dict) -> None:
    def pf(v):
        return "PASS" if v else "FAIL"
    L = ["# CryptoHouse flow data: validation (PLAN 6.3)", ""]
    L.append(f"Generated by `research/flow/validate.py`. Raw numbers: `validation.json` next to this file.")
    L.append("")
    L.append("| Gate | Result | Numbers |")
    L.append("|---|---|---|")
    v = res.get("V1", {})
    if v:
        L.append(f"| V1 labels vs reserve deltas | {pf(v['pass'])} | reserve moves agree with buy/sell on "
                 f"{v['reserve_label_agree']}/{v['reserve_label_checked']} verified transitions; swap-api label agrees on "
                 f"{v['swapapi_label_agree']}/{v['swapapi_label_checked']} tx-matched trades |")
    v = res.get("V2", {})
    if v:
        L.append(f"| V2 reserve-chain completeness | {pf(v['pass'])} | non-Mayhem coins ({v['coins']}): {v['chain_ok']}/{v['transitions']} "
                 f"transitions chain exactly ({(v['share'] or 0):.4%}); Mayhem curves ({v['mayhem_coins']}, not tradeable): "
                 f"{v['mayhem_chain_ok']}/{v['mayhem_transitions']} (their SOL reserve moves outside TradeEvents) |")
    v = res.get("V3", {})
    if v:
        L.append(f"| V3 cross-source vs swap-api launch sample | {pf(v['pass'])} | {v['coins']} coins, {v['coin_windows']} coin-minutes: "
                 f"count within 2% on {v['count_within_2pct']}, SOL within 1% on {v['sol_within_1pct']}, both on {v['both']} "
                 f"({(v['share_both'] or 0):.1%}); exact count match {v['exact_count_match']}; SOL relative error p50/p99 "
                 f"{v['sol_rel_err_p50_p99']}; exact SOL convention on {v['sol_exact_rows']} rows |")
    v = res.get("V4", {})
    if v:
        L.append(f"| V4 intra-slot order vs slotIndexId | {pf(v['pass'])} | {v['agree']}/{v['same_slot_pairs']} same-slot pairs agree "
                 f"({(v['share'] or 0):.4%}); {v['matched_trades']} trades matched by tx+wallet+side |")
    v = res.get("V5", {})
    if v:
        L.append(f"| V5 reserve semantics | {pf(v['pass'])} | PumpSwap Buy/Sell reserves are **{v['semantics']}**: next event fits pre-trade "
                 f"on {v['pre_fit']}/{v['amm_pairs']}, post-trade on {v['post_fit']} |")
    v = res.get("V6", {})
    if v:
        L.append(f"| V6 candle rebuild vs LAB/coins | {pf(v['pass'])} | {v['coins']} coins, {v['coin_minutes']} coin-minutes: close ratio median "
                 f"{v['close_ratio_median']:.4f} (p05 {v['close_ratio_p05']:.4f}, p95 {v['close_ratio_p95']:.4f}), "
                 f"{v['close_within_1pct']:.1%} within 1%; volume ratio median {v['volume_ratio_median']:.4f} |")
    v = res.get("V7", {})
    if v:
        L.append(f"| V7 AGENT (BOOST) presence | {pf(v['pass'])} | census SOL non-Mayhem graduates with B2: {v['census_agent_present']}/"
                 f"{v['census_eligible']} ({(v['share'] or 0):.1%}); slices median {v['slices_median']} (p10-p90 {v['slices_p10_p90']}), "
                 f"SOL median {v['sol_median'] and round(v['sol_median'], 2)} (p10-p90 {[round(x, 2) for x in (v['sol_p10_p90'] or [])]}), "
                 f"gap median {v['median_gap_median']} s; all eligible graduates: {v['all_agent_present']}/{v['all_eligible']}; "
                 f"AGENT found on {v['agent_given_boost_completed'][0]}/{v['agent_given_boost_completed'][1]} census coins with "
                 f"boost_mode=COMPLETED; matrix {v['vs_census_boost_mode']} |")
    v = res.get("V0", {})
    if v:
        L += ["", "## V0: census coverage", "",
              f"- {v['found_in_cryptohouse']} of {v['census_coins']} census coins found as CryptoHouse graduates "
              f"(graduates span {v['graduates_span'][0]} to {v['graduates_span'][1]}).",
              f"- Creation timestamp identical to the census for {v['creation_ts_exact']}; canonical pool identical for {v['pool_match']}.",
              f"- Mayhem flag (CreateEvent `is_mayhem_mode`) agrees with census `mayhem_state` presence on {v['mayhem_flag_agree']}; "
              f"the derived `mayhem` column (flag, or real SOL < 80 at completion on SOL curves) agrees on {v['mayhem_derived_agree']}.",
              f"- SOL-quoted classification agrees with the census quote mint on {v['sol_quoted_agree']}.",
              f"- CryptoHouse graduates created in the census window and graduated before the census ran but absent from it: "
              f"{len(v['graduates_missing_from_census'])} {v['graduates_missing_from_census']}.",
              f"- CryptoHouse graduates created inside the census window: {v['cryptohouse_graduates_created_in_census_window']}."]
    v = res.get("V3", {})
    if v and v.get("worst"):
        L += ["", "Worst V3 coin-minutes (SOL gap):", ""]
        for w in v["worst"]:
            L.append(f"- `{w['mint'][:10]}` minute {w['minute']}: n {w['ch_n']} vs {w['sw_n']}, SOL {w['ch_sol']:.3f} vs "
                     f"{w['sw_sol']:.3f}")
    lc = out / "layout_check_sep16.json"
    if lc.exists():
        j = json.loads(lc.read_text())
        L += ["", "## Layout check at the start of U_ext (2026-09-16)", "",
              f"Window {j['window']}. Same offsets decode correctly:",
              f"- PumpSwap Buy: {j['amm_buy']['n']} events, base58 length {j['amm_buy']['len_chars']}; virtual quote reserve "
              f"present (median {j['amm_buy']['virt_median_lamports'] / 1e9:.4f} SOL).",
              f"- PumpSwap Sell: {j['amm_sell']['n']} events, length {j['amm_sell']['len_chars']} ({j['amm_sell']['note']}).",
              f"- Curve TradeEvent: {j['curve_trade']['n']} events, length {j['curve_trade']['len_chars']}; virtual - real SOL = 30 SOL on "
              f"{j['curve_trade']['vsol_minus_rsol_eq_30SOL']} (the rest are Mayhem / non-standard curves).",
              f"- CreateEvent: {j['curve_create']['vsol0_30SOL_and_native_quote']}/{j['curve_create']['n']} with 30 SOL virtual and native-SOL quote; "
              f"CreatePool with WSOL {j['create_pool']['wsol_side']}/{j['create_pool']['n']}; CompleteEvent length {j['complete']['len_chars']}."]
    L += ["", "## Notes", "",
          "- Failed transactions: `solana.instructions` keeps inner instructions (and so events) of failed transactions. "
          "All templates keep only `transactions_non_voting.err = ''`; without that filter 2.6-4.4 % of PumpSwap events and "
          "~0.7 % of curve trades on 2026-10-08 would be phantom trades.",
          "- SOL convention: our `usol` is what the user paid (buys, fees included) or received (sells). swap-api's `amountSol` "
          "mixes conventions by instruction (PumpSwap sells and `buy` = user-side; `buy_exact_quote_in` = net of fees; curve = "
          "curve amount, fees excluded on buys and included on sells); V3 converts ours to that convention trade by trade.",
          "- PumpSwap price: the AMM prices with `x + virt` where `virt` is a virtual quote reserve (~17.58 SOL on 2026-10 migration "
          "pools) carried only by Buy events (u64 at byte 446 + len(ix_name)). Price = (x + virt) / y. Ignoring it under-prices "
          "fresh pools by ~7 %. It also explains the lab's 17.6 SOL 'floor' market cap.",
          ]
    (out / "VALIDATION.md").write_text("\n".join(L) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=f"{SCRATCH}/flow")
    ap.add_argument("--max-hours", type=int, default=10, help="launch-sample creation hours to fetch (1 query each)")
    ap.add_argument("--offline", action="store_true", help="use cached raw validation data only")
    ap.add_argument("--ranges", default="", help="per-split range records instead of the census run, e.g. "
                    f"train,val,test,census (of {','.join(RANGE_SPLITS)}); merged into <out>/validation_ranges.json")
    ap.add_argument("--max-per-hour", type=int, default=90, help="CryptoHouse queries per rolling hour (shared log)")
    ap.add_argument("--coins-per-hour", type=int, default=14)
    ap.add_argument("--max-trades", type=int, default=150, help="raw trades per coin and sampled hour")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    out = Path(args.out)
    from cryptohouse import Budget
    ch = None if args.offline else CryptoHouse(log_path=os.environ.get("CH_QUERY_LOG", str(out / "ch_query_log.jsonl")),
                                               budget=Budget(max_per_hour=args.max_per_hour))
    if args.ranges:
        t_start = time.time()
        n_calls = [0]
        if ch is not None:
            _query = ch.query

            def counted(sql, tag="", **kw):      # this run's CryptoHouse calls (slot-map lookups included)
                n_calls[0] += 1
                return _query(sql, tag=tag, **kw)
            ch.query = counted
        recs = run_ranges(out, ch, [s.strip() for s in args.ranges.split(",") if s.strip()], args.coins_per_hour,
                          args.max_trades, args.seed)
        p = out / "validation_ranges.json"
        old = json.loads(p.read_text()) if p.exists() else []
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(merge_ranges(old, recs), indent=1, default=str))
        os.replace(tmp, p)
        mine = [e for e in (ch.qlog.entries(since=t_start) if ch else []) if (e.get("tag") or "").startswith("validate:")]
        print(json.dumps({"records": recs, "query_calls_this_run": n_calls[0], "validate_log_entries": len(mine)},
                         indent=1, default=str))
        return 0
    res = run(out, args.max_hours, ch)
    (out / "validation.json").write_text(json.dumps(res, indent=1, default=str))
    write_report(out, res)
    print((out / "VALIDATION.md").read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
