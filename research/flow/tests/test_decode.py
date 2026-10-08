"""Python decoders vs CryptoHouse server-side decoding of the same real events (2026-10-08 rows)."""
import re

import pytest

import decode as D

TRADE_FIELDS = ("slot", "tx_idx", "pix", "ix", "ts", "tx", "venue", "is_buy", "user", "usol", "tok", "x0", "y0",
                "x1", "y1", "qamt", "lp_fee", "pfee", "cfee", "ix_name")


def test_base58_roundtrip():
    for s in (D.CURVE_PROGRAM, D.AMM_PROGRAM, D.WSOL, D.NATIVE_SOL_QUOTE, "1111", "1"):
        assert D.b58encode(D.b58decode(s)) == s
    assert D.b58decode(D.NATIVE_SOL_QUOTE) == b"\x00" * 32


def _events_by_kind(ch_events):
    out = {}
    for e in ch_events["events"]:
        kind, ev = D.decode_event(e["data"])
        out.setdefault(kind, []).append((e, ev))
    return out


def test_fixture_has_every_event_kind(ch_events):
    kinds = _events_by_kind(ch_events)
    for k in ("curve_trade", "curve_create", "curve_complete", "amm_buy", "amm_sell", "amm_create_pool"):
        assert k in kinds, k


def test_trade_decoders_match_server_side_sql(ch_events):
    """Every SQL-decoded trade (raw.sql) is reproduced byte-exactly by the Python decoders."""
    exp = {(t["tx"], t["user"], bool(t["is_buy"])): t for t in ch_events["expected_trades"]}
    matched = 0
    for e in ch_events["events"]:
        kind, ev = D.decode_event(e["data"])
        if kind == "curve_trade":
            t = exp.get((e["tx_signature"], ev.user, ev.is_buy))
            if not t:
                continue
            matched += 1
            assert t["venue"] == 0
            assert ev.user_sol == t["usol"]
            assert ev.tok == t["tok"]
            assert ev.vsol == t["x1"] and ev.vtok == t["y1"]
            assert ev.fee == t["pfee"] and ev.creator_fee == t["cfee"]
            assert ev.ix_name == t["ix_name"]
        elif kind in ("amm_buy", "amm_sell"):
            t = exp.get((e["tx_signature"], ev.user, ev.is_buy))
            if not t:
                continue
            matched += 1
            assert t["venue"] == 1
            assert ev.user_sol == t["usol"]
            assert ev.base_amount == t["tok"]
            assert ev.pool_quote_before == t["x0"] and ev.pool_base_before == t["y0"]
            assert ev.pool_quote_after == t["x1"] and ev.pool_base_after == t["y1"]
            assert ev.lp_fee == t["lp_fee"] and ev.protocol_fee == t["pfee"] and ev.coin_creator_fee == t["cfee"]
    assert matched == len(ch_events["expected_trades"])


def test_create_complete_pool_match_curve_sql(ch_events):
    coin = ch_events["expected_coin"]
    kinds = _events_by_kind(ch_events)
    creates = [ev for _, ev in kinds["curve_create"] if ev.mint == coin["mint"]]
    assert creates, "CreateEvent of the fixture coin"
    c = creates[0]
    assert (c.name, c.symbol, c.uri) == (coin["name"], coin["symbol"], coin["uri"])
    assert c.creator == coin["creator"] and c.user == coin["create_user"]
    assert c.ts == coin["c_ts"]
    assert c.is_mayhem == bool(coin["is_mayhem"])
    assert c.quote_mint == coin["curve_quote_mint"] == D.NATIVE_SOL_QUOTE
    assert (c.vsol, c.vtok, c.rtok, c.supply) == (30_000_000_000, 1_073_000_000_000_000, 793_100_000_000_000, 10 ** 15)
    comp = [ev for _, ev in kinds["curve_complete"] if ev.mint == coin["mint"]][0]
    assert comp.ts == coin["g_ts"] and comp.user == coin["completer"]
    pool = [ev for _, ev in kinds["amm_create_pool"] if ev.base_mint == coin["mint"]][0]
    assert pool.pool == coin["pool"] and pool.quote_mint == D.WSOL
    assert pool.pool_quote / 1e9 == pytest.approx(coin["pool_quote0"])
    assert pool.pool_base == 206_900_000_000_000   # migration pools hold 206.9M tokens


def test_reserve_chain_pre_trade_semantics(ch_events):
    """V5 as a unit test: event reserves are pre-trade; derived post-state equals the next event's pre-state."""
    kinds = _events_by_kind(ch_events)
    coin = ch_events["expected_coin"]
    amm = [(e, ev) for k in ("amm_buy", "amm_sell") for e, ev in kinds.get(k, []) if ev.pool == coin["pool"]]
    amm.sort(key=lambda p: (p[0]["block_slot"], p[0]["index"]))
    pairs = [(a, b) for (_, a), (_, b) in zip(amm, amm[1:])]
    assert pairs
    ok = sum(1 for a, b in pairs if a.pool_quote_after == b.pool_quote_before and a.pool_base_after == b.pool_base_before)
    assert ok >= len(pairs) - 1


def test_virtual_quote_reserve_on_buy_events(ch_events):
    """Buy events carry the pool's virtual quote reserve after ix_name; pricing reserve = x + virt."""
    kinds = _events_by_kind(ch_events)
    coin = ch_events["expected_coin"]
    for e, ev in kinds["amm_buy"]:
        if ev.pool != coin["pool"]:
            continue
        raw = D.b58decode(e["data"])
        n = int.from_bytes(raw[409:413], "little")
        virt = int.from_bytes(raw[445 + n:453 + n], "little")
        assert 17.5 < virt / 1e9 < 17.7
        # the first trade after migration prices off x + virt == the 84.99 SOL the pool was created with
        if ev.pool_base_before == 206_900_000_000_000:
            assert (ev.pool_quote_before + virt) / 1e9 == pytest.approx(coin["pool_quote0"], abs=1e-6)


@pytest.mark.parametrize("name", ["curve", "b2", "raw", "b3", "slot_map"])
def test_templates_render_without_leftover_placeholders(name):
    params = dict(s_lo=1, s0=2, s1=3, s1_pool=4, t_lo="2026-10-08 00:00:00", t_hi="2026-10-08 01:00:00",
                  t0="2026-10-08 00:00:00", t1="2026-10-08 01:00:00", launch_s=120, horizon_s=10800,
                  act=D.sql_tuples([(D.WSOL, D.WSOL, 1)]), mints=D.sql_in([D.WSOL]),
                  win=D.sql_tuples([(D.WSOL, D.WSOL, 1, 2)]), min_usol=0, max_trades=10, min_wallet_usol=0)
    sql = D.render_sql(name, **params)
    assert not re.search(r"\$[A-Za-z_]", sql)
    assert "solana." in sql


def test_sql_lists_reject_injection():
    with pytest.raises(ValueError):
        D.sql_in(["abc'); DROP TABLE x; --"])
    with pytest.raises(ValueError):
        D.sql_tuples([("0OIl", 1)])          # 0, O, I, l are not base58
    assert D.sql_in([]) == "('')"
    assert D.sql_tuples([(D.WSOL, 5, True)]) == f"[('{D.WSOL}',5,1)]"
