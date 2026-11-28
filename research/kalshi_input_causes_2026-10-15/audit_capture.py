"""Audit the declared diagnostic cohort from saved original log responses only.

No production calls, client imports, financial decisions, state changes or model
fitting. Missing/capped/errored reads remain explicit. Keep original messages.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
LOGGERS = {
    'kalshi_learning_input_diagnostic': 'nightcrawler.kalshi_arena',
    'kalshi_online_learning_unknown': 'nightcrawler.kalshi_online_learning',
    'kalshi_online_learning_forecast': 'nightcrawler.kalshi_online_learning',
    'kalshi_online_learning_scored': 'nightcrawler.kalshi_online_learning',
    'kalshi_online_learning_status': 'nightcrawler.kalshi_online_learning',
    'speeddesk_live_status': 'nightcrawler.speeddesk',
    'speeddesk_live_fill': 'nightcrawler.speeddesk',
    'speeddesk_live_settlement': 'nightcrawler.speeddesk',
}


def parse_message(message: str, event: str) -> dict[str, Any] | None:
    prefix = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z INFO '
    match = re.fullmatch(prefix + re.escape(LOGGERS[event]) + ': ' + re.escape(event) + r' (\{[^\n]*\})', message)
    if match is None:
        return None
    parsed = json.loads(match.group(1))
    if not isinstance(parsed, dict):
        raise TypeError('event payload is not a dictionary')
    return parsed


def originals(path: Path, event: str) -> tuple[list[dict[str, Any]], list[str]]:
    problems: list[str] = []
    try:
        native = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        return [], [f'native read failed: {type(error).__name__}']
    if not isinstance(native, dict):
        return [], ['native result is not a dictionary']
    if native.get('isError'):
        return [], ['tool returned isError']
    structured = native.get('structuredContent')
    if not isinstance(structured, dict) or not isinstance(structured.get('deploy'), list):
        return [], ['no structured deploy log array']
    rows = []
    for row in structured['deploy']:
        try:
            timestamp = row['timestamp']
            if not isinstance(timestamp, str):
                raise TypeError('missing original timestamp')
            payload = parse_message(row['message'], event)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            problems.append(f'invalid original row: {type(error).__name__}')
            continue
        if payload is not None:
            rows.append({'timestamp': timestamp, 'message': row['message'], 'payload': payload})
    return rows, problems


def main() -> None:
    declaration = json.loads((HERE/'CAPTURE_DECLARATION.json').read_text())
    queries = json.loads((HERE/'CAPTURE_REQUESTS.json').read_text())
    result: dict[str, Any] = {'declaration': declaration, 'queries': [], 'diagnostic': [], 'joins': [], 'payload_errors': []}
    events: dict[str, list[dict[str, Any]]] = {}
    seen: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for query in queries['queries']:
        path = HERE/query['file']
        if not path.exists():
            result['queries'].append({**query, 'missing': True})
            continue
        rows, errors = originals(path, query['event'])
        try:
            native = json.loads(path.read_text())
            structured = native.get('structuredContent') if isinstance(native, dict) else None
            raw = structured.get('deploy') if isinstance(structured, dict) else None
            raw_count = len(raw) if isinstance(raw, list) else None
        except (OSError, ValueError):
            raw_count = None
        result['queries'].append({**query, 'raw_rows': raw_count, 'parsed_rows': len(rows),
                                  'at_cap': raw_count >= query['limit'] if raw_count is not None else None, 'errors': errors})
        event = query['event']
        unique = seen.setdefault(event, {})
        for row in rows:
            identity = (row['timestamp'], row['message'])
            if identity not in unique:
                row['query_files'] = [query['file']]
                unique[identity] = row
                events.setdefault(event, []).append(row)
            elif query['file'] not in unique[identity]['query_files']:
                unique[identity]['query_files'].append(query['file'])
    target: list[dict[str, Any]] = []
    for row in events.get('kalshi_learning_input_diagnostic', []):
        payload = row['payload']
        pending = payload.get('pending')
        if not isinstance(pending, dict):
            result['payload_errors'].append({'timestamp':row['timestamp'], 'error':'diagnostic pending metadata is not a dictionary'})
            continue
        if pending.get('start') == declaration['start'] and pending.get('end') == declaration['end']:
            target.append(row)
    result['diagnostic'] = target
    result['unique_original_counts'] = {key: len(value) for key, value in events.items()}
    for row in target:
        payload = row['payload']
        kind = payload.get('disposition')
        if kind not in ('forecast', 'unknown'):
            result['joins'].append({'window': payload.get('window'), 'disposition': kind, 'error': 'unsupported slot disposition'})
            continue
        expected_event = 'kalshi_online_learning_forecast' if kind == 'forecast' else 'kalshi_online_learning_unknown'
        candidates = [candidate for candidate in events.get(expected_event, [])
                   if candidate['payload'].get('window') == payload.get('window')
                   and candidate['payload'].get('at') == payload.get('at')
                   and candidate['payload'].get('reason') == payload.get('reason')]
        matches = [candidate for candidate in candidates
                   if candidate['payload'].get('source_fingerprint') == payload.get('source_fingerprint') == declaration['learner_fingerprint']
                   and candidate['payload'].get('protocol') == payload.get('protocol') == declaration['learner_protocol']]
        mismatches = [candidate for candidate in candidates if candidate not in matches]
        result['joins'].append({'window': payload.get('window'), 'disposition': kind,
                                'candidate_window_time_reason_receipts':len(candidates), 'matched_original_receipts': len(matches),
                                'identity_mismatches': [{'timestamp':c['timestamp'], 'source_fingerprint':c['payload'].get('source_fingerprint'), 'protocol':c['payload'].get('protocol')} for c in mismatches],
                                'arena_source_match': payload.get('arena_source_sha256') == declaration['arena_source_sha256'],
                                'learner_source_match': payload.get('source_fingerprint') == declaration['learner_fingerprint'],
                                'learner_protocol_match':payload.get('protocol') == declaration['learner_protocol'],
                                'observe_only': payload.get('mode') == 'observe_only' and payload.get('live_application') is False})
    result['limits'] = [
        'Exact original logger/event framing; nested status text is never an original event.',
        'Diagnostic counter deltas describe a whole learner call, not additive per-window totals.',
        'No producer occurrence or parent FIFO timing exists on the unchanged gap wire.',
        'Point/sampled log coverage is not whole-stream certification; retain query caps/errors/missing results.',
        'No strategy-profitability or all-delays-fixed verdict follows from a diagnostic join.',
    ]
    (HERE/'CAPTURE_AUDIT.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'diagnostic_rows': len(target), 'joins': result['joins'], 'query_count': len(result['queries'])}))


if __name__ == '__main__':
    main()
