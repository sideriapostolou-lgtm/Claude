"""Independent raw-bar/result reconciliation; imports no simulator or runner."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
DATA = Path('/workspace/ifvg_data_20261019/MNQ_1min_sample.csv')
NY = ZoneInfo('America/New_York')
MINUTE = timedelta(minutes=1)
CHECKS = 0


def check(condition, label):
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(label)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(value):
    return datetime.fromisoformat(value).astimezone(UTC)


def slots(begin, end):
    return [begin + i * MINUTE for i in range(int((end - begin).total_seconds() // 60))]


def usd(value):
    return f'{value:.2f}'


def verify_summary(days, summary):
    closed = [d['trade'] for d in days if d['trade']]
    nets = [Decimal(t['net_usd']) for t in closed]
    daily = [Decimal(d['net_usd']) for d in days]
    balances = [Decimal(0), *itertools.accumulate(daily)]
    drawdown = max(max(balances[:i + 1]) - balance for i, balance in enumerate(balances))
    loss_runs = [len(list(group)) for loss, group in itertools.groupby(n < 0 for n in nets) if loss]
    total = sum(nets, Decimal(0))
    expected = {
        'sessions': len(days), 'decisions': dict(Counter(d['decision'] for d in days)),
        'unresolved_dates': [], 'closed_trades': len(closed),
        'net_wins': sum(n > 0 for n in nets), 'net_losses': sum(n < 0 for n in nets),
        'net_flat': sum(n == 0 for n in nets),
        'win_fraction': f'{sum(n > 0 for n in nets)}/{len(nets)}' if nets else None,
        'known_closed_gross_after_friction_usd': usd(sum((Decimal(t['gross_usd']) for t in closed), Decimal(0))),
        'known_closed_fees_usd': usd(sum((Decimal(t['fees_usd']) for t in closed), Decimal(0))),
        'known_closed_net_usd': usd(total), 'known_entry_fees_on_unresolved_usd': '0.00',
        'period_trading_net_usd': usd(total),
        'mean_per_closed_trade_usd': usd(total / len(nets)) if nets else None,
        'mean_per_scheduled_session_usd': usd(total / len(days)),
        'worst_closed_trade_usd': usd(min(nets)) if nets else None,
        'worst_known_day_usd': usd(min(daily)),
        'longest_known_closed_loss_streak': max(loss_runs, default=0),
        'session_end_max_drawdown_usd': usd(drawdown),
        'net_without_best_day_usd': usd(total - max(daily)),
        'ambiguous_closed_trades': sum(t['ambiguous'] for t in closed),
        'planned_entry_risk_usd': [usd(Decimal(t['risk_ticks']) / 2) for t in closed],
        'operating_net_usd': None,
    }
    for field, value in expected.items():
        check(summary[field] == value, f'summary mismatch {field}: {summary[field]} != {value}')
    check('unverified' in summary['operating_net_reason'], 'operating-cost limitation')


def verify_day(day, fee_cents, friction, raw):
    local_day = datetime.fromisoformat(day['session_date']).replace(tzinfo=NY)

    def at(hour, minute=0):
        return local_day.replace(hour=hour, minute=minute).astimezone(UTC)

    phase = {
        'asian_reference': set(slots(at(20) - timedelta(days=1), at(0))),
        'london_reference': set(slots(at(2), at(5))),
    }
    bounds = {}
    for name, key in [('ASIAN', 'asian_reference'), ('LONDON', 'london_reference')]:
        bars = [raw[t] for t in phase[key]]
        bounds[name + '_HIGH'] = max(b[1] for b in bars)
        bounds[name + '_LOW'] = min(b[2] for b in bars)
    check(bounds == day['reference_levels'], 'raw reference bounds')

    def swept(t):
        _, high, low, close = raw[t]
        high_names = [name for name, level in bounds.items()
                      if name.endswith('HIGH') and high > level and close <= level]
        low_names = [name for name, level in bounds.items()
                     if name.endswith('LOW') and low < level and close >= level]
        return high_names, low_names

    sweep_candidates = [(t, swept(t)) for t in slots(at(9, 30), at(11)) if any(swept(t))]
    evidence = {'date': day['session_date'], 'decision': day['decision'], 'reason': day['reason']}
    if not sweep_candidates:
        check(day['decision'] == 'NO_TRADE' and day['reason'] == 'NO_SWEEP', 'no-sweep verdict')
        check(day['attempt'] is None and day['trade'] is None, 'no-sweep has no attempted trade')
        phase['observation'] = set(slots(at(9, 30), at(11)))
    else:
        first, (highs, lows) = sweep_candidates[0]
        attempt = day['attempt']
        check(stamp(attempt['sweep_timestamp']) == first, 'first sweep, no earlier eligible event')
        check(not (highs and lows), 'actual sample has no simultaneous first sweep')
        long = bool(lows)
        side = 1 if long else -1
        check(attempt['direction'] == ('LONG' if long else 'SHORT'), 'sweep direction')
        check(attempt['swept_levels'] == highs + lows, 'swept named levels')
        phase['observation'] = set(slots(at(9, 30), first + MINUTE))
        phase['pre_gap'] = set(slots(first - 12 * MINUTE, first))
        evidence['sweep_ny'] = first.astimezone(NY).isoformat()
        eligible = []
        for c in slots(first - 10 * MINUTE, first):
            a = c - 2 * MINUTE
            lower, upper = (raw[c][1], raw[a][2]) if long else (raw[a][1], raw[c][2])
            if upper <= lower:
                continue
            inverted = any(raw[t][3] > upper if long else raw[t][3] < lower
                           for t in slots(c + MINUTE, first))
            if not inverted:
                eligible.append((c, lower, upper))
        if not eligible:
            check(day['reason'] == 'NO_ELIGIBLE_GAP', 'no eligible raw pre-sweep gap')
            check(day['trade'] is None and attempt['gap'] is None, 'rejected gap creates no trade')
        else:
            c, lower, upper = max(eligible)
            gap = attempt['gap']
            check(stamp(gap['c_timestamp']) == c, 'latest eligible gap chosen')
            check(stamp(gap['a_timestamp']) == c - 2 * MINUTE, 'gap a time')
            check(stamp(gap['b_timestamp']) == c - MINUTE, 'gap b time')
            check((gap['lower_ticks'], gap['upper_ticks']) == (lower, upper), 'raw gap boundaries')
            check(gap['kind'] == ('BEARISH' if long else 'BULLISH'), 'gap kind')
            events = []
            for t in slots(first, first + 11 * MINUTE):
                high_sweeps, low_sweeps = swept(t)
                opposite = bool(high_sweeps if long else low_sweeps)
                inversion = raw[t][3] > upper if long else raw[t][3] < lower
                if opposite or inversion:
                    events.append((t, opposite))
            check(bool(events), 'sample has confirmation or rejection within window')
            confirm, opposite = events[0]
            phase['confirmation'] = set(slots(first, confirm + MINUTE))
            if opposite:
                check(day['reason'] == 'OPPOSITE_SWEEP' and day['trade'] is None,
                      'opposite sweep rejects before confirmation')
                evidence['opposite_sweep_ny'] = confirm.astimezone(NY).isoformat()
            else:
                check(stamp(attempt['confirmation_timestamp']) == confirm, 'first inversion close')
                entry_time = confirm + MINUTE
                check(entry_time < at(11), 'entry before cutoff')
                adverse = min(raw[t][2] for t in phase['confirmation']) if long else max(
                    raw[t][1] for t in phase['confirmation'])
                stop = adverse - side
                entry = raw[entry_time][0] + side * friction
                risk = abs(entry - stop)
                check(side * (raw[entry_time][0] - stop) > 0, 'raw open stays inside stop')
                target = entry + side * risk * 2
                trade = day['trade']
                check((trade['entry_ticks'], trade['stop_ticks'], trade['target_ticks'], trade['risk_ticks'])
                      == (entry, stop, target, risk), 'raw entry stop target risk')
                check(stamp(trade['entry_timestamp']) == entry_time, 'next-open entry')
                phase['entry'] = {entry_time}
                exit_event = None
                for t in slots(entry_time, at(11, 31)):
                    op, high, low, _ = raw[t]
                    stop_at_open = op <= stop if long else op >= stop
                    target_at_open = op >= target + 1 if long else op <= target - 1
                    stop_in_bar = low <= stop if long else high >= stop
                    target_in_bar = high >= target + 1 if long else low <= target - 1
                    if stop_at_open:
                        exit_event = (t, op - side * friction, 'STOP', False, 'OPEN')
                    elif target_at_open:
                        exit_event = (t, target, 'TARGET', False, 'OPEN')
                    elif t == at(11, 30):
                        exit_event = (t, op - side * friction, 'TIME', False, 'OPEN')
                    elif stop_in_bar:
                        exit_event = (t, stop - side * friction, 'STOP', target_in_bar, 'INTRABAR_INTERVAL')
                    elif target_in_bar:
                        exit_event = (t, target, 'TARGET', False, 'INTRABAR_INTERVAL')
                    if exit_event:
                        break
                check(exit_event is not None, 'raw exit found')
                exit_time, exit_price, reason, ambiguous, basis = exit_event
                check(stamp(trade['exit_timestamp']) == exit_time, 'earliest raw exit bar')
                check((trade['exit_ticks'], trade['exit_reason'], trade['ambiguous'], trade['exit_time_basis'])
                      == (exit_price, reason, ambiguous, basis), 'exit fill and precision')
                if basis == 'INTRABAR_INTERVAL':
                    check(stamp(trade['exit_interval_end']) == exit_time + MINUTE, 'exit interval')
                gross_ticks = side * (exit_price - entry)
                gross_usd = Decimal(gross_ticks) / 2
                fees = Decimal(fee_cents) / 50
                net = gross_usd - fees
                check(trade['gross_ticks'] == gross_ticks, 'gross tick accounting')
                for field, value in [('gross_usd', gross_usd), ('fees_usd', fees), ('net_usd', net)]:
                    check(trade[field] == usd(value) and day[field] == usd(value), field + ' reconciliation')
                phase['outcome'] = set(slots(entry_time, exit_time + MINUTE))
                evidence.update(gap_c_ny=c.astimezone(NY).isoformat(),
                                confirmation_ny=confirm.astimezone(NY).isoformat(),
                                entry_ny=entry_time.astimezone(NY).isoformat(),
                                exit_bar_ny=exit_time.astimezone(NY).isoformat(),
                                planned_risk_usd=usd(Decimal(risk) / 2), net_usd=usd(net))
    union = set().union(*phase.values())
    check(union <= raw.keys(), 'all required raw slots present')
    check(day['coverage']['required_count'] == len(union), 'unique required slot count')
    check(day['coverage']['present_count'] == len(union), 'unique present slot count')
    check(day['coverage']['complete'] and not day['required_missing'], 'complete day coverage flags')
    check(set(day['coverage']['phases']) == set(phase), 'coverage phase names')
    for name, timestamps in phase.items():
        actual = day['coverage']['phases'][name]
        check(actual == {'required_count': len(timestamps), 'present_count': len(timestamps),
                         'required_missing': []}, 'coverage phase counts ' + name)
    return evidence


def main():
    results_path = HERE / 'RESULTS_CORRECTED.json'
    manifest_path = HERE / 'RUN_MANIFEST_CORRECTED.json'
    result = json.loads(results_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    check(digest(DATA) == result['data_sha256'] == manifest['data_sha256'], 'exact data hash')
    check(result['manifest_sha256'] == digest(manifest_path), 'result bound to corrected manifest')
    for name, expected in manifest['source_sha256'].items():
        check(digest(HERE / name) == expected == result['source_sha256'][name], 'frozen source ' + name)
    check(stamp(manifest['frozen_at_utc']) < stamp(result['generated_at_utc']), 'freeze before result')
    raw = {}
    with DATA.open(newline='') as stream:
        reader = csv.reader(stream)
        check(next(reader) == ['timestamp', 'open', 'high', 'low', 'close', 'volume'], 'literal header')
        for row in reader:
            t = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S').replace(tzinfo=NY).astimezone(UTC)
            prices = [Decimal(v) * 4 for v in row[1:5]]
            if t in raw or any(p != p.to_integral_value() for p in prices):
                raise AssertionError('raw duplicate or off-tick value')
            raw[t] = tuple(int(v) for v in prices)
    check(len(raw) == 16200, 'raw data row count')
    check(result['whole_downloaded_span_pnl_usd'] is None, 'incomplete downloaded span stays unknown')
    check(not result['actual_contract_verified'] and not result['actual_costs_verified'], 'proxy limitations')
    check({(s['fee_per_side_cents'], s['friction_ticks']) for s in result['scenarios']}
          == set(itertools.product([50, 100, 150], [1, 2, 4])), 'all nine frozen cases')
    baseline = []
    scenario_totals = []
    for scenario in result['scenarios']:
        boundary = scenario['boundary_diagnostic']
        check(boundary['decision'] == 'UNRESOLVED' and boundary['net_usd'] is None, 'boundary unknown')
        check(len(boundary['required_missing']) == 240, 'missing initial Asian range retained')
        check(all(stamp(t) not in raw for t in boundary['required_missing']), 'boundary holes real')
        days = scenario['early_days'] + scenario['later_days']
        check([d['session_date'] for d in scenario['early_days']] == manifest['early_dates'], 'early order')
        check([d['session_date'] for d in scenario['later_days']] == manifest['later_dates'], 'later order')
        for day in days:
            evidence = verify_day(day, scenario['fee_per_side_cents'], scenario['friction_ticks'], raw)
            if scenario['fee_per_side_cents'] == 100 and scenario['friction_ticks'] == 2:
                baseline.append(evidence)
        for key, segment in [('early', scenario['early_days']), ('later', scenario['later_days']),
                             ('interior', days)]:
            verify_summary(segment, scenario[key + '_summary'])
        scenario_totals.append({'fee_per_side_cents': scenario['fee_per_side_cents'],
                                'friction_ticks': scenario['friction_ticks'],
                                'net_usd': scenario['interior_summary']['period_trading_net_usd']})
    receipt = {
        'verdict': 'RAW_RECONCILIATION_PASS', 'assertions_passed': CHECKS,
        'method': 'Independent CSV parsing, signal timing/coverage and arithmetic; no simulator/runner import or call',
        'review_script_sha256': digest(Path(__file__)), 'data_sha256': digest(DATA),
        'results_sha256': digest(results_path), 'manifest_sha256': digest(manifest_path),
        'reviewed_source_sha256': manifest['source_sha256'],
        'scenarios_verified': 9, 'scenario_day_records_verified': 99, 'summary_blocks_verified': 27,
        'baseline_daily_evidence': baseline, 'scenario_totals': scenario_totals,
        'limitations': ['Exploratory root-series proxy only; actual contract/adjustment/roll unknown',
                        'Only 11 days and 2 modeled trades, with unequal one-contract dollar risk',
                        'Actual costs and operating net unknown; no proven future edge',
                        'Old TEST, network, accounts and production not accessed'],
    }
    with (HERE / 'RESULTS_INDEPENDENT_REVIEW.json').open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'verdict': receipt['verdict'], 'assertions_passed': CHECKS,
                      'scenarios': 9, 'day_records': 99, 'summaries': 27}))


if __name__ == '__main__':
    main()
