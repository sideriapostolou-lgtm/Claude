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
from collections import defaultdict
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
    for _, ts in by_venue.items():
        for a, b in zip(ts, ts[1:]):
            n_pairs += 1
            if a["x1"] == b["x0"] and a["y1"] == b["y0"]:
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
    for t in theirs:
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
    """SOL in swap-api's convention: buys net of all fees, sells as received by the user."""
    if t["is_buy"]:
        return (t["usol"] - t["pfee"] - t["cfee"] - t["lp_fee"]) / 1e9
    return t["usol"] / 1e9


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
    from cryptohouse import ResultTooLarge
    t0 = floor_to(min(c["c0"] for c in cs) - 5, Q15)
    t1 = floor_to(max(c["c0"] for c in cs) + 125, Q15) + Q15
    slots.ensure(t0 - Q15, t1 + Q15)
    params = dict(s0=slots.first_slot(t0), s1=slots.last_slot_before(t1), t0=utc(t0), t1=utc(t1),
                  win=sql_tuples([(c["mint"], c["pool"], c["c0"], c["c0"] + 120) for c in cs]),
                  mints=sql_in([c["mint"] for c in cs]), min_usol=0, max_trades=max_trades)
    try:
        res = ch.query(render_sql("raw", **params), tag=f"validate:raw:{utc(t0)}:{len(cs)}")
    except ResultTooLarge:
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
        for mi, venue, n, nb, bs, ss in r["minutes"]:
            mins[mi]["n"] += n
            mins[mi]["sell"] += ss / 1e9
            mins[mi]["buy_user"] = mins[mi].get("buy_user", 0.0) + bs / 1e9
        if full:
            for k in mins:
                mins[k]["buy"] = 0.0
            for t in r["trades"]:
                mi = (t["ts"] - c0) // 60
                if t["is_buy"]:
                    mins[mi]["buy"] += net_swap_sol(t)
        for w in cross_source_minutes(r["minutes"], s["sw"], c0):
            mi = int(w["window"])
            ours = mins.get(mi, {"n": 0, "buy": 0.0, "sell": 0.0, "buy_user": 0.0})
            buy_ours = ours["buy"] if full else ours.get("buy_user", 0.0) / 1.0125
            rows3.append({"mint": m, "minute": mi, "ch_n": ours["n"], "sw_n": w["sw_n"],
                          "ch_buy": buy_ours, "sw_buy": w["sw_buy"], "ch_sell": ours["sell"], "sw_sell": w["sw_sell"],
                          "buy_exact": full})
    def within(a, b, tol):
        return abs(a - b) <= tol * max(abs(b), 1e-9) or abs(a - b) < 1e-6
    ok_n = sum(1 for x in rows3 if within(x["ch_n"], x["sw_n"], 0.02))
    ok_sol = sum(1 for x in rows3 if within(x["ch_buy"] + x["ch_sell"], x["sw_buy"] + x["sw_sell"], 0.01))
    ok_both = sum(1 for x in rows3 if within(x["ch_n"], x["sw_n"], 0.02)
                  and within(x["ch_buy"] + x["ch_sell"], x["sw_buy"] + x["sw_sell"], 0.01))
    res["V3"] = {"coins": len(raw), "coin_windows": len(rows3), "count_within_2pct": ok_n, "sol_within_1pct": ok_sol,
                 "both": ok_both, "exact_count_match": sum(1 for x in rows3 if x["ch_n"] == x["sw_n"]),
                 "share_both": ok_both / len(rows3) if rows3 else None,
                 "pass": bool(rows3) and ok_both / len(rows3) >= 0.95,
                 "worst": sorted(rows3, key=lambda x: -abs(x["ch_n"] - x["sw_n"]))[:5]}

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
        ch_in_census_window = [g for g in grads.values() if census["created_min_ts"] <= (g["c_ts"] or 0) <= census["created_max_ts"]]
        res["V0"] = {"census_coins": len(cen), "found_in_cryptohouse": len(found),
                     "creation_ts_exact": ts_match, "pool_match": pool_match,
                     "mayhem_flag_agree": may_agree, "census_mayhem_state_set": len(may_c),
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
        res["V7"] = {"census_eligible": len(census_elig), "census_agent_present": len(pres),
                     "share": len(pres) / len(census_elig) if census_elig else None,
                     "slices_median": sl[len(sl) // 2] if sl else None,
                     "slices_p10_p90": [sl[len(sl) // 10], sl[9 * len(sl) // 10]] if sl else None,
                     "sol_median": so[len(so) // 2] if so else None,
                     "sol_p10_p90": [so[len(so) // 10], so[9 * len(so) // 10]] if so else None,
                     "median_gap_median": gp[len(gp) // 2] if gp else None,
                     "all_eligible": len(elig), "all_agent_present": len(all_pres),
                     "pass": bool(census_elig) and len(pres) / len(census_elig) >= 0.9
                     and sl and abs(sl[len(sl) // 2] - 25) <= 2}
    res["queries"] = summarize_log(ch.qlog.path) if ch else None
    return res


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
                 f"({(v['share_both'] or 0):.1%}); exact count match {v['exact_count_match']} |")
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
                 f"gap median {v['median_gap_median']} s; all eligible graduates: {v['all_agent_present']}/{v['all_eligible']} |")
    v = res.get("V0", {})
    if v:
        L += ["", "## V0: census coverage", "",
              f"- {v['found_in_cryptohouse']} of {v['census_coins']} census coins found as CryptoHouse graduates "
              f"(graduates span {v['graduates_span'][0]} to {v['graduates_span'][1]}).",
              f"- Creation timestamp identical to the census for {v['creation_ts_exact']}; canonical pool identical for {v['pool_match']}.",
              f"- Mayhem flag (CreateEvent `is_mayhem_mode`) agrees with census `mayhem_state` presence on {v['mayhem_flag_agree']}.",
              f"- CryptoHouse graduates created inside the census window: {v['cryptohouse_graduates_created_in_census_window']}."]
    v = res.get("V3", {})
    if v and v.get("worst"):
        L += ["", "Worst V3 coin-minutes (count gap):", ""]
        for w in v["worst"]:
            L.append(f"- `{w['mint'][:10]}` minute {w['minute']}: n {w['ch_n']} vs {w['sw_n']}, SOL {w['ch_buy'] + w['ch_sell']:.3f} vs "
                     f"{w['sw_buy'] + w['sw_sell']:.3f}")
    L += ["", "## Notes", "",
          "- Failed transactions: `solana.instructions` keeps inner instructions (and so events) of failed transactions. "
          "All templates keep only `transactions_non_voting.err = ''`; without that filter 2.6-4.4 % of PumpSwap events and "
          "~0.7 % of curve trades on 2026-10-08 would be phantom trades.",
          "- SOL convention: our `usol` is what the user paid (buys, fees included) or received (sells). swap-api's `amountSol` "
          "is net of fees on buys; V3 converts ours to that convention before comparing.",
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
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    out = Path(args.out)
    ch = None if args.offline else CryptoHouse(log_path=os.environ.get("CH_QUERY_LOG", str(out / "ch_query_log.jsonl")))
    res = run(out, args.max_hours, ch)
    (out / "validation.json").write_text(json.dumps(res, indent=1, default=str))
    write_report(out, res)
    print((out / "VALIDATION.md").read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
