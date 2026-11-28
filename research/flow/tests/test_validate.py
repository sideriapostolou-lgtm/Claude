"""Validation logic on one real launch window present in both sources (JBfdBN1q, 2026-10-08 12:xx)."""
import validate as V


def _trades(fx):
    return [dict(zip(V.TRADE_FIELDS, t)) for t in fx["cryptohouse"]["trades"]]


def test_counts_and_sol_match_swapapi(launch_fixture):
    ch = launch_fixture["cryptohouse"]
    sw = launch_fixture["swapapi"]
    assert ch["n_trades"] == len(sw["trades"]) == 174
    trades = _trades(launch_fixture)
    sells_ch = sum(t["usol"] for t in trades if not t["is_buy"]) / 1e9
    sells_sw = sum(float(x["amountSol"]) for x in sw["trades"] if x["type"] == "sell")
    assert abs(sells_ch - sells_sw) / sells_sw < 0.001
    buys_ch = sum(V.net_swap_sol(t) for t in trades if t["is_buy"])
    buys_sw = sum(float(x["amountSol"]) for x in sw["trades"] if x["type"] == "buy")
    assert abs(buys_ch - buys_sw) / buys_sw < 0.001


def test_mayhem_curve_reserves_move_outside_trade_events(launch_fixture):
    """Mayhem curves: the token side chains exactly, the SOL side does not (reserves change without TradeEvents)."""
    assert launch_fixture["mayhem"]
    tr = [t for t in _trades(launch_fixture) if t["venue"] == 0]
    y_ok = sum(1 for a, b in zip(tr, tr[1:]) if a["y1"] == b["y0"])
    x_ok = sum(1 for a, b in zip(tr, tr[1:]) if a["x1"] == b["x0"])
    assert y_ok == len(tr) - 1
    assert x_ok < 0.5 * (len(tr) - 1)


def test_chain_labels_and_pre_trade_semantics(launch_amm_fixture):
    """V1/V2/V5 on a normal graduate: curve + PumpSwap chains close exactly; reserves are pre-trade."""
    tr = _trades(launch_amm_fixture)
    assert {t["venue"] for t in tr} == {0, 1}
    c = V.chain_check(tr)
    assert c["pairs"] == len(tr) - 2
    # one real break on this pool: 46,189 lamports reached the pool's SOL vault without a trade event
    assert c["chain_ok"] >= c["pairs"] - 1
    assert c["label_ok"] == c["label_checked"] == c["chain_ok"]
    s = V.semantics_check(tr)
    assert s["pairs"] > 50 and s["pre_fit"] >= s["pairs"] - 1 and s["post_fit"] == 0


def test_amm_counts_match_swapapi(launch_amm_fixture):
    tr = _trades(launch_amm_fixture)
    sw = launch_amm_fixture["swapapi"]["trades"]
    assert len(tr) == len(sw) == launch_amm_fixture["cryptohouse"]["n_trades"]
    o = V.ordering_check(tr, sw)
    assert o["matched"] >= len(tr) - 1 and o["agree"] == o["same_slot_pairs"] > 0


def test_ordering_matches_slot_index(launch_fixture):
    o = V.ordering_check(_trades(launch_fixture), launch_fixture["swapapi"]["trades"])
    assert o["matched"] == 174
    assert o["same_slot_pairs"] > 0 and o["agree"] == o["same_slot_pairs"]


def test_slot_index_parse():
    assert V.slot_index_order("0004544585160010010002") == (454458516, 10010002)


def test_chain_check_detects_phantom():
    base = dict(slot=1, venue=1, is_buy=1)
    t1 = dict(base, x0=100, y0=1000, x1=110, y1=910)
    phantom = dict(base, slot=2, x0=110, y0=910, x1=120, y1=830)    # failed tx: state never realised
    t2 = dict(base, slot=3, x0=110, y0=910, x1=105, y1=950, is_buy=0)
    c = V.chain_check([t1, phantom, t2])
    assert c["pairs"] == 2 and c["chain_ok"] == 1


def test_swapapi_amount_convention_per_trade(launch_fixture, launch_amm_fixture):
    """net_swap_sol reproduces swap-api amountSol to the lamport on every tx-matched trade."""
    n = 0
    for fx in (launch_fixture, launch_amm_fixture):
        idx = {}
        for x in fx["swapapi"]["trades"]:
            idx.setdefault((x["tx"], x["userAddress"], x["type"] == "buy"), []).append(x)
        for t in _trades(fx):
            xs = idx.get((t["tx"], t["user"], bool(t["is_buy"])))
            if not xs:
                continue
            n += 1
            a = float(xs[0]["amountSol"])
            if t["venue"] == 1 and t["is_buy"] and not t["ix_name"]:
                # fixture captured before raw.sql extracted ix_name for PumpSwap buys: either convention
                assert min(abs(t["usol"] / 1e9 - a), abs(V.net_swap_sol(t) - a)) <= 2e-9
            else:
                assert abs(V.net_swap_sol(t) - a) <= 2e-9
    assert n >= 240


# ---- per-split range records (validate.py --ranges) ------------------------------------------------------------


def _g(mint, g_ts, **kw):
    d = {"mint": mint, "pool": "P" + mint, "g_ts": g_ts, "c_ts": g_ts - 600, "has_create": 1,
         "pool_quote_mint": V.WSOL, "is_mayhem": 0, "rsol_complete": 85.0}
    d.update(kw)
    return d


def test_pick_hours_one_per_segment_inside_the_split():
    lo, hi = V._uts("2026-10-06 12:00:00"), V._uts("2026-10-07 19:37:30")
    hs = V.pick_hours("test", lo, hi, 2)
    assert hs == V.pick_hours("test", lo, hi, 2)            # deterministic
    assert len(hs) == 2 and all(lo <= h and h + 3600 <= hi for h in hs)
    mid = lo + 16 * 3600                                       # 31 whole hours -> segments of 15 and 16
    assert hs[0] < lo + 15 * 3600 <= hs[1] < mid + 15 * 3600
    assert V.pick_hours("x", lo, lo + 3600, 4) == [lo]        # never more hours than the split holds


def test_range_candidates_universe_creation_rule_and_window():
    H = V._uts("2026-10-03 12:00:00")
    lo, hi = V._uts("2026-10-01 00:00:00"), V._uts("2026-10-05 00:00:00")
    grads = {g["mint"]: g for g in [
        _g("a", H - 2 * 3600),                                # graduated 2 h before: window = the whole hour
        _g("b", H + 1200),                                    # graduates inside the hour: window starts at g
        _g("c", H - 4 * 3600),                                # B2 window over before the hour
        _g("d", H + 100, pool=None),                          # no pool
        _g("e", H + 100, pool_quote_mint="USD1"),             # not SOL-quoted
        _g("f", H + 100, is_mayhem=1),                        # Mayhem flag
        _g("h", H + 100, rsol_complete=40.0),                 # Mayhem by real SOL at completion
        _g("i", H + 100, has_create=0, c_ts=0),               # creation unknown -> g - 1800 (inside the split)
        _g("j", H + 100, c_ts=lo - 10),                       # created before the split
        _g("k", H + 100, c_ts=lo - 10),                       # ... but the census says otherwise
    ]}
    out = {c["mint"]: c for c in V.range_candidates(grads, lo, hi, H, {"k": lo + 5})}
    assert set(out) == {"a", "b", "i", "k"}
    assert (out["a"]["lo"], out["a"]["hi"]) == (H, H + 3600)
    assert (out["b"]["lo"], out["b"]["hi"]) == (H + 1200, H + 3600)
    assert out["i"]["c_ts"] == H + 100 - 1800 and out["k"]["c_ts"] == lo + 5
    late = V.range_candidates({"z": _g("z", H - 3 * 3600 + 600)}, lo, hi, H)
    assert late[0]["hi"] == H + 600                           # B2 ends inside the hour


def _row(fx):
    return {"mint": fx["mint"], "truncated": 0, "trades": _trades(fx)}


def test_range_record_passes_on_real_amm_window(launch_amm_fixture):
    fx = launch_amm_fixture
    st = V.block_stats([_row(fx)], {fx["mint"]: fx["swapapi"]["trades"]})
    rec = V.range_record("val", "2026-10-05 00:00:00", "2026-10-06 12:00:00",
                         [{"hour_utc": "2026-10-05 05:00:00", "stats": st}], "2026-10-09 02:00:00")
    assert rec["V1"]["pass"] and rec["V2"]["pass"] and rec["V4"]["pass"]
    assert rec["V2"]["transitions"] == len(fx["cryptohouse"]["trades"]) - 2 and rec["V2"]["chain_ok"] >= rec["V2"]["transitions"] - 1
    assert rec["V1"]["swapapi_label_checked"] >= len(fx["swapapi"]["trades"]) - 1
    assert rec["V4"]["same_slot_pairs"] > 0
    # the fields research/lab2/common.validation_gates reads
    for k in ("lo_utc", "hi_utc", "validated_utc"):
        assert len(rec[k]) == 19
    assert {"chain_ok", "transitions"} <= set(rec["V2"]) and "pass" in rec["V1"] and "pass" in rec["V4"]


def test_range_record_fails_on_missing_trades_and_wrong_labels(launch_amm_fixture):
    fx = launch_amm_fixture
    row = _row(fx)
    amm = [i for i, t in enumerate(row["trades"]) if t["venue"] == 1]
    gapped = dict(row, trades=[t for i, t in enumerate(row["trades"]) if i not in amm[5:40:5]])   # 7 missing
    bad_sw = [dict(x, type="sell" if x["type"] == "buy" else "buy") if i % 50 == 0 else x
              for i, x in enumerate(fx["swapapi"]["trades"])]
    st = V.block_stats([gapped], {fx["mint"]: bad_sw})
    rec = V.range_record("val", "a" * 19, "b" * 19, [{"hour_utc": "h", "stats": st}], "c" * 19)
    assert not rec["V2"]["pass"] and rec["V2"]["transitions"] - rec["V2"]["chain_ok"] >= 7
    assert not rec["V1"]["pass"] and rec["V1"]["swapapi_label_agree"] < rec["V1"]["swapapi_label_checked"]
    empty = V.range_record("val", "a" * 19, "b" * 19, [{"hour_utc": "h", "stats": V.block_stats([], {})}], "c" * 19)
    assert not (empty["V1"]["pass"] or empty["V2"]["pass"] or empty["V4"]["pass"])


def test_merge_ranges_replaces_same_split_only():
    old = [{"split": "train", "lo_utc": "1", "hi_utc": "2", "v": 0}, {"split": "val", "lo_utc": "3", "hi_utc": "4"},
           {"lo_utc": "5", "hi_utc": "6"}]
    new = [{"split": "train", "lo_utc": "1", "hi_utc": "2", "v": 1}, {"split": "x", "lo_utc": "5", "hi_utc": "6"}]
    got = V.merge_ranges(old, new)
    assert [r.get("split") for r in got] == ["val", "train", "x"] and got[1]["v"] == 1


def test_label_pairs_same_wallet_buy_and_sell_in_one_tx():
    """Seen on 2026-10-01: a wallet's dust buy + sell in one tx. A (tx, wallet) dict compares the buy with the sell."""
    ours = [{"tx": "T", "user": "W", "slot": 5, "tx_idx": 9, "pix": 7, "ix": 5, "is_buy": 0},
            {"tx": "T", "user": "W", "slot": 5, "tx_idx": 9, "pix": 4, "ix": 5, "is_buy": 1},
            {"tx": "U", "user": "X", "slot": 6, "tx_idx": 1, "pix": 2, "ix": 3, "is_buy": 1}]
    theirs = [{"tx": "T", "userAddress": "W", "slotIndexId": "0000000000050000090001", "type": "sell"},
              {"tx": "T", "userAddress": "W", "slotIndexId": "0000000000050000090000", "type": "buy"}]
    pairs = V.label_pairs(ours, theirs)
    assert len(pairs) == 2 and all((x["type"] == "buy") == bool(t["is_buy"]) for t, x in pairs)
    rows = [{"mint": "M", "truncated": 0, "trades": [dict(t, venue=1, x0=1, y0=1, x1=1, y1=1, virt=0) for t in ours]}]
    st = V.block_stats(rows, {"M": theirs})
    assert (st["sw_label_n"], st["sw_label_ok"], st["sw_multi_trade_tx_wallets"]) == (2, 2, 1)


def test_ordering_check_ignores_swapapi_page_order(launch_amm_fixture):
    """swap-api pages come newest-first; a wallet's two same-side trades in one tx must still pair in order."""
    tr = _trades(launch_amm_fixture)
    sw = launch_amm_fixture["swapapi"]["trades"]
    assert V.ordering_check(tr, sw[::-1]) == V.ordering_check(tr, sw)
    a = {"tx": "T", "user": "W", "is_buy": 1, "slot": 9, "tx_idx": 1, "pix": 2, "ix": 5}
    b = dict(a, pix=4)
    c = {"tx": "U", "user": "Z", "is_buy": 0, "slot": 9, "tx_idx": 3, "pix": 1, "ix": 5}
    theirs = [{"tx": "T", "userAddress": "W", "type": "buy", "slotIndexId": f"{9:012d}{p:010d}"} for p in (10001, 10000)]
    theirs.append({"tx": "U", "userAddress": "Z", "type": "sell", "slotIndexId": f"{9:012d}{30000:010d}"})
    o = V.ordering_check([a, b, c], theirs)
    assert o["matched"] == 3 and o["agree"] == o["same_slot_pairs"] == 3


def test_quote_side_breakdown_and_chain_check_agree():
    def t(x0, y0, x1, y1, virt=0, buy=1):
        return {"venue": 1, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "virt": virt, "is_buy": buy, "slot": 1}
    tr = [t(100, 50, 110, 45, virt=20),        # -> next x0 = 110: real x chains
          t(110, 45, 120, 40, virt=20),        # -> x jumps +3, v -3 on the next buy: X chains
          t(123, 40, 133, 35, virt=17),        # -> sell with v unknown, x jumps: accepted as a v shift
          t(134, 35, 130, 36, buy=0),          # -> token side breaks (a trade is missing)
          t(130, 37, 140, 30, virt=17)]
    q = V.quote_side_breakdown(tr)
    assert q == {"amm_pairs": 4, "token_ok": 3, "x_ok": 1, "xv_only": 1, "xv_fail": 0, "v_unknown_jump": 1}
    assert V.chain_check(tr)["chain_ok"] == q["token_ok"] - q["xv_fail"]
