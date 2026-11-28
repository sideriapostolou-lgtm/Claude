"""Offline receipt arithmetic; no network or runtime mutations. Run from any cwd."""
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
CHECKS = 0


def eq(actual, expected):
    global CHECKS
    CHECKS += 1
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        assert abs(actual - expected) < 1e-9, (actual, expected)
    else:
        assert actual == expected, (actual, expected)


def read(name):
    return json.loads((ROOT / name).read_text())


def parse(rows):
    return [dict(json.loads(r['message'][r['message'].index('{'):]),
                 log_timestamp=r['timestamp']) for r in rows]


def query(name):
    doc = read(name)
    eq(len(doc['response']['deploy']) < doc['request']['limit'], True)
    rows = parse(doc['response']['deploy'])
    for row in rows:
        eq(datetime.fromtimestamp(row['at'], UTC).date().isoformat(), '2026-10-16')
        eq(row['log_timestamp'][:10], '2026-10-16')
    return rows


def reconstruct(fills, settlements):
    for s in settlements:
        ff = [f for f in fills if f['window'] == s['window']]
        q = {side: sum(f['size'] for f in ff if f['side'] == side) for side in ('up', 'down')}
        cost = sum(f['size'] * f['price'] for f in ff)
        fees = sum(f['fee_usd'] for f in ff)
        unit = sum(sum(f['size'] * f['price'] + f['fee_usd'] for f in ff if f['side'] == side)
                   / shares if shares else 0 for side, shares in q.items())
        pairs = min(q.values())
        locked = pairs * (1 - unit)
        payout = q['up' if s['up_wins'] else 'down']
        pnl = payout - cost - fees
        values = {'up_shares': q['up'], 'down_shares': q['down'], 'cost_usd': cost,
                  'fee_usd': fees, 'payout_usd': payout, 'locked_usd': locked,
                  'direction_usd': pnl - locked, 'pnl_usd': pnl}
        if 'paired_credit_usd' in s:
            values.update(paired_credit_usd=pairs, net_payout_usd=payout-pairs)
        for key, value in values.items():
            eq(value, s[key])


artifact = read('independent_verification.json')
for path, digest in artifact['source_sha256'].items():
    eq(hashlib.sha256((REPO / path).read_bytes()).hexdigest(), digest)
eq(all(c['pass'] for c in artifact['checks']), True)
eq(len(artifact['checks']), artifact['checks_passed'])
native = read('PRIOR_UTC_DAY_NATIVE.json')['report']
last = read('LAST_NATIVE.json')['state']
money = query('DAY_MONEY_LOGS.json')
real_fills = [r for r in money if 'fill_id' in r]
real_settlements = [r for r in money if 'settlement_id' in r]
eq(len({f['fill_id'] for f in real_fills}), len(real_fills))
eq(len({s['settlement_id'] for s in real_settlements}), len(real_settlements))
practice_fills = query('TWIN_FILL_LOGS.json')
practice_settlements = query('TWIN_SETTLEMENT_LOGS.json')
eq(len({(f['window'], f['order_id']) for f in practice_fills}), len(practice_fills))
eq(len({s['window'] for s in practice_settlements}), len(practice_settlements))
for scope, fills, settlements in [('real', real_fills, real_settlements),
                                  ('practice_twin', practice_fills, practice_settlements)]:
    n = native[scope]
    reconstruct(fills, settlements)
    eq(len(fills), n['fills'])
    eq(len({f['window'] for f in fills}), n['windows'])
    eq(len(settlements) if scope == 'real' else sum(s['up_shares']+s['down_shares'] > 0 for s in settlements),
       n['settled_windows'])
    for field, native_field in [('pnl_usd', 'pnl_usd'), ('locked_usd', 'locked_usd'),
                                 ('direction_usd', 'directional_usd')]:
        eq(sum(s[field] for s in settlements), n[native_field])
    eq(min(s['pnl_usd'] for s in settlements), n['worst_usd'])
eq(len(real_fills), 149)
eq(len(real_settlements), 60)
eq(artifact['summary']['filled_windows'], len({f['window'] for f in real_fills}))
eq(sum(f['fee_usd'] for f in real_fills), native['real']['fees_usd'])
eq(sum(s['fee_usd'] for s in real_settlements), 0.482)
eq(len(practice_settlements), 96)
eq(sum(s['up_shares']+s['down_shares'] == 0 for s in practice_settlements), 79)
eq(sum(f['fee_usd'] for f in practice_fills), 0.0508)
eq(sum(s['fee_usd'] for s in practice_settlements), 0.0508)
carry = artifact['cross_day_carry']['actual_next_day_settlement']
original = json.loads((REPO / 'research/kalshi_post75_loss_2026-10-16/NEXT_WINDOW.json').read_text())
eq(carry, parse(original['money_query']['response']['deploy'])[0])
reconstruct(real_fills, [carry])
eq(sum(f['fee_usd'] for f in real_fills)-sum(s['fee_usd'] for s in real_settlements), carry['fee_usd'])
eq(carry['pnl_usd'], last['today']['pnl_usd'])
eq(carry['log_timestamp'][:10], '2026-10-17')
practice_carry = [f for f in practice_fills if f['window'] not in {s['window'] for s in practice_settlements}]
eq(len(practice_carry), 1)
eq(practice_carry[0]['window'], carry['window'])
eq(practice_carry[0]['side'], 'down')
eq(carry['up_wins'], False)
eq(1-practice_carry[0]['price']-practice_carry[0]['fee_usd'], last['practice_twin']['pnl_usd'])
eq(native['real']['scorecard']['complete_windows'], 26)
eq(native['real']['scorecard']['gap_windows'], 70)
eq(native['real']['scorecard']['eligible_windows'], 96)
print(json.dumps({'status': 'PASS', 'offline_checks_passed': CHECKS,
                  'artifact_checks_passed': artifact['checks_passed'],
                  'real_pnl_usd': native['real']['pnl_usd'],
                  'practice_simulated_fees_usd': sum(f['fee_usd'] for f in practice_fills)}, indent=2))
