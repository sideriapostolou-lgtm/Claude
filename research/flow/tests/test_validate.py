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
    assert c["pairs"] == len(tr) - 2 and c["chain_ok"] == c["pairs"]
    assert c["label_ok"] == c["label_checked"] == c["pairs"]
    s = V.semantics_check(tr)
    assert s["pairs"] > 50 and s["pre_fit"] == s["pairs"] and s["post_fit"] == 0


def test_amm_counts_match_swapapi(launch_amm_fixture):
    tr = _trades(launch_amm_fixture)
    sw = launch_amm_fixture["swapapi"]["trades"]
    assert len(tr) == len(sw) == launch_amm_fixture["cryptohouse"]["n_trades"]
    o = V.ordering_check(tr, sw)
    assert o["matched"] == len(tr) and o["agree"] == o["same_slot_pairs"] > 0


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
