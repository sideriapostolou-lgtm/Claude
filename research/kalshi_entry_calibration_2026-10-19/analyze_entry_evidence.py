"""Offline development diagnostic: exact historical first-order intent joins only.

No network calls, alternate fills, tuning, or recorder/TEST inputs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BASELINE = REPO / 'research/kalshi_recovery_loss_2026-10-18/LOSS_MECHANISM.json'
MONEY = REPO / 'research/daily_status_2026-10-17/DAY_MONEY_LOGS.json'
def D(value):
    return Decimal(str(value))

CHECKS = 0
SOURCES = {}


def check(value, label):
    global CHECKS
    if not value:
        raise AssertionError(label)
    CHECKS += 1


def load(path):
    content = path.read_bytes()
    SOURCES[str(path.relative_to(HERE)) if path.is_relative_to(HERE) else 'repository/' + str(path.relative_to(REPO))] = hashlib.sha256(content).hexdigest()
    return json.loads(content)


def close(a, b, label):
    check(abs(D(a) - D(b)) < D('0.00000001'), label)


def iso_s(timestamp):
    return D(str(datetime.fromisoformat(timestamp).timestamp()))


def parse(row):
    match = re.search(r'nightcrawler\.speeddesk: (\w+) (\{.*\})$', row['message'])
    if not match:
        return None
    try:
        result = json.loads(match[2])
    except json.JSONDecodeError:
        return None
    return {'event': match[1], **result}


def dump(path, data):
    path.write_text(json.dumps(data, indent=2, default=str) + '\n')


def main():
    global REPO, BASELINE, MONEY
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=REPO)
    parser.add_argument('--output-dir', type=Path, default=HERE)
    args = parser.parse_args()
    REPO = args.repo.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    BASELINE = REPO / 'research/kalshi_recovery_loss_2026-10-18/LOSS_MECHANISM.json'
    MONEY = REPO / 'research/daily_status_2026-10-17/DAY_MONEY_LOGS.json'
    baseline = load(BASELINE)
    money_cap = load(MONEY)
    plans = load(HERE / 'requests.json')
    population = baseline['per_window']
    expected = {r['first_client_order_id']: r for r in population}
    check(len(expected) == len(population) == 55, '55 unique prespecified first clients')
    plan_ids = [i for p in plans for i in p['client_order_ids']]
    check(len(plan_ids) == len(set(plan_ids)) == 55 and set(plan_ids) == set(expected),
          'query plan includes every first client once regardless of outcome')
    check(len(baseline['empty_settlement_windows']) == 5, '5 empty settlements retained')
    native_rows = money_cap['response']['deploy']
    check(len(native_rows) < money_cap['request']['limit'], 'original money query unsaturated')
    native = [parse(r) for r in native_rows]
    check(all(x is not None for x in native), 'all original money rows parse')
    fills = [e for e in native if e['event'] == 'speeddesk_live_fill']
    settlements = [e for e in native if e['event'] == 'speeddesk_live_settlement']
    check(len(fills) == len({f['fill_id'] for f in fills}) == 149, '149 unique fill receipts')
    check(len(settlements) == 60, '60 settlements incl 5 empty')
    by_order = defaultdict(list)
    for fill in fills:
        by_order[fill['order_id']].append(fill)
    by_window = {r['window']: r for r in settlements}

    events = defaultdict(list)
    query_proof = []
    exclusions = Counter()
    seen = set()
    duplicate_rows = 0
    for path in sorted((HERE / 'captures').glob('*.json')):
        capture = load(path)
        req = capture['request']
        resp = capture['response']
        check(not resp.get('isError'), f'{path.name}: no connector error')
        structured = resp['structuredContent']
        rows = structured['deploy']
        original_proof = capture['original_evidence']
        original_count = original_proof['original_provider_rows']
        selected_proof = capture['selected_row_provenance']
        check(len(rows) == len(selected_proof) == original_proof['selected_direct_order_rows'], f'{path.name}: selected count')
        check(len(rows) + sum(original_proof['excluded_rows'].values()) == original_count, f'{path.name}: original count partition')
        exclusions.update(original_proof['excluded_rows'])
        check('deploymentId' not in req and structured['scope'] == 'service',
              f'{path.name}: service scope across deployments')
        check(req['limit'] == 500 and len(rows) <= original_count < 500, f'{path.name}: unsaturated')
        allowed = capture.get('client_order_ids') or [
            i for i in expected if '"' + i + '"' in req['filter']]
        check(bool(allowed) and set(allowed) <= set(expected), f'{path.name}: exact target filter')
        top_count = 0
        for index, row in enumerate(rows):
            proof = selected_proof[index]
            check(hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == proof['original_row_canonical_sha256'], f'{path.name}:{index}: original row hash')
            check(hashlib.sha256(row['message'].encode()).hexdigest() == proof['message_sha256'], f'{path.name}:{index}: original message hash')
            clock = iso_s(row['timestamp'])
            check(iso_s(req['startDate']) <= clock <= iso_s(req['endDate']),
                  f'{path.name}:{index}: provider clock inside explicit request')
            # Provider search also matches event/ID strings nested inside status payloads;
            # those snapshots and their line fragments are never substituted for direct events.
            event = parse(row)
            if event is None:
                exclusions['fragment_or_other_unparseable_top_level'] += 1
                continue
            if event['event'] != 'speeddesk_live_order':
                exclusions['non_order_top_level_' + event['event']] += 1
                continue
            check(event.get('client_order_id') in allowed,
                  f'{path.name}:{index}: direct event client exactly in query targets')
            top_count += 1
            canonical = json.dumps(event, sort_keys=True, separators=(',', ':'))
            # Exact event de-duplication tolerates repeat capture/probe, never changes a field.
            if canonical in seen:
                duplicate_rows += 1
                continue
            seen.add(canonical)
            events[event['client_order_id']].append({
                'payload': event,
                'provider_timestamp': row['timestamp'],
                'capture': path.name,
                'row_index': proof['original_row_index'],
                'message_sha256': hashlib.sha256(row['message'].encode()).hexdigest(),
            })
        query_proof.append({'capture': path.name, 'startDate': req['startDate'],
                            'endDate': req['endDate'], 'target_client_count': len(allowed),
                            'returned_provider_rows': original_count, 'selected_original_direct_rows': len(rows),
                            'original_envelope_sha256': original_proof['original_envelope_sha256'],
                            'original_response_canonical_sha256': original_proof['original_response_canonical_sha256'],
                            'selection_boundary': original_proof['selection_boundary'], 'limit': req['limit'],
                            'unsaturated': True, 'scope': structured['scope'],
                            'direct_order_rows_before_dedup': top_count,
                            'metadata_latest_deployment_id': structured['deploymentId'],
                            'warning': 'latest deployment metadata is NOT source deployment of historical rows'})

    table = []
    conflicts = []
    chronology_failures = []
    missing = []
    for original in population:
        client = original['first_client_order_id']
        entries = events[client]
        intents = [e for e in entries if e['payload'].get('state') == 'durable intent']
        accepted = [e for e in entries if e['payload'].get('order_id') == original['first_order_id']
                    and e['payload'].get('state') == 'accepted; waiting for real fills']
        if len(intents) != 1 or len(accepted) != 1:
            (missing if not intents or not accepted else conflicts).append(client)
            continue
        source = intents[0]
        intent = source['payload']
        ack = accepted[0]['payload']
        check(intent['window'] == original['window'] == ack['window'], f'{client}: exact window')
        check(intent['side'] == original['first_side'], f'{client}: exact side')
        check(intent['kind'] == 'rest', f'{client}: model intent, never lock-fair substitution')
        check(0 <= D(intent['fair']) <= 1, f'{client}: valid fair probability')
        check(D(intent['size']) > 0, f'{client}: valid intended quantity')
        if D(intent['at']) > D(original['first_fill_at']):
            chronology_failures.append(client)
            continue
        first_fills = by_order[original['first_order_id']]
        check({f['client_order_id'] for f in first_fills} == {client}, f'{client}: fill client')
        check({f['window'] for f in first_fills} == {original['window']}, f'{client}: fill window')
        check({f['side'] for f in first_fills} == {intent['side']}, f'{client}: fill side')
        check(set(original['first_order_fill_ids']) == {f['fill_id'] for f in first_fills},
              f'{client}: full first-order partial fill population')
        check(all(D(f['price']) <= D(intent['price']) for f in first_fills), f'{client}: limit respected')
        check(all(not f['is_taker'] for f in first_fills), f'{client}: actual maker fills')
        quantity = sum((D(f['size']) for f in first_fills), D(0))
        cost = sum((D(f['size']) * D(f['price']) for f in first_fills), D(0))
        fee = sum((D(f['fee_usd']) for f in first_fills), D(0))
        settlement = by_window[original['window']]
        outcome = int((intent['side'] == 'up') == settlement['up_wins'])
        actual_pnl = quantity * outcome - cost - fee
        fair = D(intent['fair'])
        expected_pnl = quantity * fair - cost - fee
        residual = D(outcome) - fair
        close(quantity, original['first_order_quantity'], f'{client}: quantity reconciles')
        close(fee, original['first_order_fee_usd'], f'{client}: fee reconciles')
        close(actual_pnl, original['first_order_settlement_cashflow_usd'], f'{client}: pnl reconciles')
        close(actual_pnl - expected_pnl, quantity * residual, f'{client}: calibration identity')
        check(quantity <= D(intent['size']), f'{client}: fills within intended quantity')
        if original['predecision_intent'] is not None:
            old = original['predecision_intent']
            check(all(intent[key] == old[key] for key in ('at', 'side', 'kind', 'price', 'size', 'fair')),
                  f'{client}: selected prior join identical')
        timing = intent.get('timing')
        check(isinstance(timing, list), f'{client}: original decision timing list')
        table.append({**original,
            'predecision_intent': intent,
            'intent_evidence': {k: v for k, v in source.items() if k != 'payload'},
            'accepted_order_evidence': accepted[0],
            'accepted_venue_order_id_exact': True,
            'completion': intent.get('completion'),
            'completion_field_observed': 'completion' in intent,
            'historical_model_version': None,
            'historical_deployment_id': None,
            'first_side_official_outcome': outcome,
            'decision_to_first_fill_s': D(original['first_fill_at']) - D(intent['at']),
            'provider_publication_minus_payload_s': iso_s(source['provider_timestamp']) - D(intent['at']),
            'provider_publication_after_first_fill': iso_s(source['provider_timestamp']) > D(original['first_fill_at']),
            'actual_first_order_weighted_price': cost / quantity,
            'all_first_order_fill_prices_equal_intended_limit': all(D(f['price']) == D(intent['price']) for f in first_fills),
            'decision_fair_minus_limit': fair - D(intent['price']),
            'official_outcome_minus_decision_fair': residual,
            'model_implied_cashflow_at_actual_fills_and_fees_usd': expected_pnl,
            'actual_minus_model_implied_cashflow_usd': actual_pnl - expected_pnl,
            'decision_fair_brier': (D(outcome) - fair) ** 2,
            'own_bid_proxy_brier': (D(outcome) - D(intent['price'])) ** 2,
            'input_age_metrics_as_logged': timing,
            'decision_fair_is_fill_time_fair': False,
            'join_status': 'exact client/window/side; accepted venue-order ID; payload clock before first fill',
        })
    check(not missing and not conflicts and not chronology_failures, 'zero missing/conflict/late intent rows')
    check(len(table) == 55, '55/55 exact joins')
    check(all(r['all_first_order_fill_prices_equal_intended_limit'] for r in table), 'all actual first prices equal limit')
    total_q = sum((D(r['first_order_quantity']) for r in table), D(0))
    total_actual = sum((D(r['first_order_settlement_cashflow_usd']) for r in table), D(0))
    total_expected = sum((r['model_implied_cashflow_at_actual_fills_and_fees_usd'] for r in table), D(0))
    total_other = sum((D(r['all_other_fill_settlement_cashflow_usd']) for r in table), D(0))
    total_fees = sum((D(r['first_order_fee_usd']) for r in table), D(0))
    close(total_actual, '-16.3428', 'all first actual cashflow retained')
    close(total_other, '8.1730', 'all other actual cashflow retained')
    close(total_actual + total_other, '-8.1698', 'original net retained')
    close(total_fees, 0, 'observed actual first order fees zero')
    mean = lambda key: sum((D(r[key]) for r in table), D(0)) / len(table)
    weighted = lambda key: sum((D(r[key]) * D(r['first_order_quantity']) for r in table), D(0)) / total_q
    calibration = {
        'primary_endpoint': 'official first-side outcome minus logged decision fair, conditional on actual first filled venue order',
        'n_complete_market_windows': len(table),
        'actual_first_order_contracts': total_q,
        'first_side_official_wins': sum(r['first_side_official_outcome'] for r in table),
        'equal_window_mean_outcome': mean('first_side_official_outcome'),
        'equal_window_mean_decision_fair': sum((D(r['predecision_intent']['fair']) for r in table), D(0)) / len(table),
        'equal_window_mean_intended_limit': sum((D(r['predecision_intent']['price']) for r in table), D(0)) / len(table),
        'equal_window_mean_outcome_minus_decision_fair': mean('official_outcome_minus_decision_fair'),
        'actual_quantity_weighted_outcome_minus_decision_fair': weighted('official_outcome_minus_decision_fair'),
        'equal_window_mean_decision_fair_minus_limit': mean('decision_fair_minus_limit'),
        'equal_window_mean_actual_first_order_cashflow_per_contract': mean('first_order_per_contract_cashflow_usd'),
        'actual_first_order_cashflow_usd': total_actual,
        'model_implied_cashflow_at_actual_fills_and_fees_usd': total_expected,
        'actual_minus_model_implied_cashflow_usd': total_actual - total_expected,
        'all_other_actual_order_cashflow_usd': total_other,
        'actual_net_usd': total_actual + total_other,
        'actual_first_order_fees_usd': total_fees,
        'decision_fair_brier_equal_window': mean('decision_fair_brier'),
        'own_bid_proxy_brier_equal_window': mean('own_bid_proxy_brier'),
        'brier_fair_minus_own_bid_proxy': mean('decision_fair_brier') - mean('own_bid_proxy_brier'),
        'price_reference_warning': 'Own chosen maker limit, also actual first-fill price in this cohort; bid proxy is NOT an independent venue forecast, market midpoint, or executable hedge.',
        'inference': 'Descriptive exposed-history diagnostic; no significance, confidence interval, gate search, backtest, or profit proof.',
    }
    def distribution(values, units):
        return {'n': len(values), 'units': units, 'min': min(values), 'median': median(values), 'max': max(values)}

    timing_diagnostics = {'decision_to_first_fill': distribution([r['decision_to_first_fill_s'] for r in table], 'seconds; local intent payload to venue fill clock; clock uncertainty remains')}
    for metric in ('btc_exchange_to_decision', 'btc_receipt_to_decision'):
        values = []
        for row in table:
            observed = [x for x in row['input_age_metrics_as_logged'] if x['metric'] == metric]
            check(len(observed) == 1 and observed[0]['status'] == 'ok' and observed[0]['scope'] == 'real_kalshi', f'{row["window"]}: {metric} complete ok')
            values.append(D(observed[0]['value_ms']))
        timing_diagnostics[metric] = distribution(values, 'milliseconds as logged')
    source_reads = [HERE / 'analyze_entry_evidence.py', REPO / 'src/nightcrawler/speeddesk_live.py',
                    REPO / 'src/nightcrawler/speeddesk_metrics.py',
                    REPO / 'research/kalshi_recovery_loss_2026-10-18/LOSS_MECHANISM.md',
                    REPO / 'research/kalshi_recovery_loss_2026-10-18/analyze_loss_mechanism.py']
    for path in source_reads:
        SOURCES[str(path.relative_to(HERE)) if path.is_relative_to(HERE) else 'repository/' + str(path.relative_to(REPO))] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {
        'scope': 'Historical development; conditional on all 55 actual first-order fills in October16 UTC traded settlements. Not all opportunities, backtest, or prospective profit proof.',
        'base_commit_at_extraction': '7523e09e37feb8f313e485917fd71ab9114ff768',
        'source_sha256': SOURCES,
        'checks_passed': CHECKS,
        'coverage': {'prespecified_traded_settlement_windows': 55, 'matched_predecision_intents': len(table),
            'matched_accepted_venue_order_ids': len(table), 'coverage_fraction': '55/55',
            'empty_settlements_outside_first_fill_calibration': baseline['empty_settlement_windows'],
            'excluded_next_day_carry': baseline['excluded_settlement_day_carry'],
            'original_day_fill_receipts_including_carry': 149,
            'provider_rows_all_captures': sum(x['returned_provider_rows'] for x in query_proof),
            'unique_direct_order_events': len(seen), 'duplicate_exact_events': duplicate_rows,
            'excluded_top_level_or_fragment_rows': dict(exclusions),
            'missing_clients': missing, 'conflicting_clients': conflicts,
            'chronology_failures': chronology_failures,
            'provider_intent_rows_published_after_first_fill': sum(r['provider_publication_after_first_fill'] for r in table),
            'missing_historical_completion_field': sum(not r['completion_field_observed'] for r in table),
            'observed_completion_false': sum(r['completion'] is False for r in table),
            'historical_model_or_deployment_versions_not_proven': len(table)},
        'selection_provenance': 'Published captures include only standalone order rows. Query counts/excluded counts and original-envelope hashes describe private originals; full-original-to-selection equality requires the private archive and independent review.',
        'query_proof': query_proof,
        'timing_diagnostics': timing_diagnostics,
        'calibration': calibration,
        'per_window': table,
        'limitations': [
            'Intent payload clock is logged local wall time; actual first-fill clock is venue-reported. Cross-clock offset/uncertainty prevents claiming exact dispatch latency.',
            'Provider timestamp is delayed publication after checkpoint and is not decision time. Timing metrics retain their own original at values.',
            'The logged fair is before the actual fill; it is not a reconstructed fill-time fair.',
            'Coinbase exchange/receipt-to-decision age metrics are preserved as logged. Full historical source snapshots, both-side book ages/queue survival, and fill-time fair are absent; no staleness or adverse-selection causal conclusion.',
            'Current source hash corroborates event semantics but is not a proven historical per-row model/deployment identity. Provider latest deployment metadata cannot assign historical regimes.',
            'Missing completion fields remain null/unknown; no lock fair or late/status snapshot is substituted.',
            'Unsaturated bounded provider receipts cover all prespecified clients; not independent durable-volume/journal completeness certification.',
            'Only actual first orders are calibrated; later reprices/nonfills/cancels, empty windows and all eligible opportunities are not a candidate-profit denominator.',
            'No tuning, future/TEST outcomes, simulated fills, network order calls, source edits, or production/configuration changes.',
        ],
    }
    dump(output_dir / 'ENTRY_EVIDENCE.json', result)
    fields = ['window', 'first_client_order_id', 'first_order_id', 'first_side', 'first_fill_at',
              'intent_at', 'provider_timestamp', 'intended_price', 'decision_fair',
              'first_order_quantity', 'first_side_official_outcome', 'completion',
              'completion_field_observed', 'decision_to_first_fill_s',
              'official_outcome_minus_decision_fair', 'first_order_settlement_cashflow_usd',
              'model_implied_cashflow_at_actual_fills_and_fees_usd',
              'all_other_fill_settlement_cashflow_usd', 'pnl_usd', 'capture', 'row_index']
    with (output_dir / 'ENTRY_EVIDENCE.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in table:
            flat = {k: row.get(k) for k in fields}
            flat.update(intent_at=row['predecision_intent']['at'],
                        provider_timestamp=row['intent_evidence']['provider_timestamp'],
                        intended_price=row['predecision_intent']['price'],
                        decision_fair=row['predecision_intent']['fair'],
                        capture=row['intent_evidence']['capture'],
                        row_index=row['intent_evidence']['row_index'])
            writer.writerow(flat)
    print(json.dumps({'checks_passed': CHECKS, 'coverage': result['coverage'],
                      'timing_diagnostics': timing_diagnostics,
                      'calibration': calibration}, indent=2, default=str))


if __name__ == '__main__':
    main()
