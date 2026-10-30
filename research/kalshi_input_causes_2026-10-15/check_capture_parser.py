"""Offline evidence-parser regression harness, no venue or network access."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = ROOT/'audit_capture.py'
    spec = importlib.util.spec_from_file_location('input_capture_audit', parser)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    unknown = 'kalshi_online_learning_unknown'
    diagnostic = 'kalshi_learning_input_diagnostic'

    def message(event: str, payload: Any) -> str:
        return '2026-10-15T17:00:00Z INFO '+module.LOGGERS[event]+': '+event+' '+json.dumps(payload)

    receipt = {'window':'KXBTC15M-synthetic', 'at':1300, 'reason':'pregap',
               'source_fingerprint':'f', 'protocol':'p'}
    original = message(unknown, receipt)
    assert module.parse_message(original, unknown)['reason'] == 'pregap'
    parent = '2026-10-15T17:00:00Z INFO nightcrawler.speeddesk: speeddesk_live_status '+json.dumps({'note':original})
    for bad in (parent, 'prefix '+original, original+'\n'+original, original.replace('INFO', 'WARNING')):
        assert module.parse_message(bad, unknown) is None
    assert module.parse_message(original, 'kalshi_online_learning_forecast') is None
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        native = directory/'native.json'
        cases = [({'isError':True}, 'tool returned isError'),
                 ({'content':[{'text':original}]}, 'no structured deploy log array'),
                 ({'structuredContent':None}, 'no structured deploy log array'),
                 ({'structuredContent':{'deploy':None}}, 'no structured deploy log array'),
                 (None, 'native result is not a dictionary'), ([], 'native result is not a dictionary')]
        for raw, expected in cases:
            native.write_text(json.dumps(raw))
            assert module.originals(native, unknown) == ([], [expected])
        native.write_text('{invalid json')
        assert module.originals(native, unknown)[1] == ['native read failed: JSONDecodeError']
        native.write_text(json.dumps({'structuredContent':{'deploy':[{'message':original},
            {'timestamp':'original-time', 'message':original}, {'timestamp':'parent-time', 'message':parent}]}}))
        rows, errors = module.originals(native, unknown)
        assert len(rows) == len(errors) == 1 and rows[0]['timestamp'] == 'original-time'
        declaration = {'start':1000, 'end':1900, 'arena_source_sha256':'s', 'learner_fingerprint':'f', 'learner_protocol':'p'}
        (directory/'CAPTURE_DECLARATION.json').write_text(json.dumps(declaration))
        payload = {'pending':{'start':1000, 'end':1900}, 'at':1300, 'window':'KXBTC15M-synthetic',
                   'disposition':'unknown', 'reason':'pregap', 'arena_source_sha256':'s',
                   'source_fingerprint':'f', 'protocol':'p', 'mode':'observe_only', 'live_application':False}

        def write(name: str, event: str, data: Any) -> None:
            (directory/name).write_text(json.dumps({'structuredContent':{'deploy':[
                {'timestamp':'original-time', 'message':message(event, data)}]}}))

        for name in ('diag1.json', 'diag2.json'):
            write(name, diagnostic, payload)
        for name in ('unknown1.json', 'unknown2.json'):
            write(name, unknown, receipt)
        (directory/'null.json').write_text(json.dumps({'structuredContent':None}))
        requests = [{'file':name, 'event':event, 'limit':10} for name, event in
                    [('diag1.json', diagnostic), ('diag2.json', diagnostic),
                     ('unknown1.json', unknown), ('unknown2.json', unknown), ('null.json', unknown)]]
        (directory/'CAPTURE_REQUESTS.json').write_text(json.dumps({'queries':requests}))
        module.HERE = directory

        def run() -> Any:
            with contextlib.redirect_stdout(io.StringIO()):
                module.main()
            return json.loads((directory/'CAPTURE_AUDIT.json').read_text())

        result = run()
        assert len(result['diagnostic']) == 1 and result['joins'][0]['matched_original_receipts'] == 1
        assert len(result['diagnostic'][0]['query_files']) == 2
        assert result['queries'][-1]['raw_rows'] is None and result['queries'][-1]['at_cap'] is None
        assert result['queries'][-1]['errors']
        for identity in ({'source_fingerprint':'wrong'}, {'protocol':'wrong'}):
            altered = {**receipt, **identity}
            for name in ('unknown1.json', 'unknown2.json'):
                write(name, unknown, altered)
            result = run()
            assert result['joins'][0]['matched_original_receipts'] == 0
            assert len(result['joins'][0]['identity_mismatches']) == 1
        write('unknown1.json', unknown, receipt)
        write('unknown2.json', unknown, receipt)
        for name in ('diag1.json', 'diag2.json'):
            write(name, diagnostic, {**payload, 'pending':['invalid']})
        result = run()
        assert len(result['diagnostic']) == 0 and len(result['payload_errors']) == 1
        for name in ('diag1.json', 'diag2.json'):
            write(name, diagnostic, {**payload, 'disposition':'scored'})
        assert run()['joins'][0]['error'] == 'unsupported slot disposition'
    result = {'parser_sha256':hashlib.sha256(parser.read_bytes()).hexdigest(),
              'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'passed':True,
              'checks':['original event framing', 'nested/prefix/multiline/wronglogger/event/level rejection',
                        'tool error and malformed native/JSON/timestamp shapes', 'overlap dedup with provenance',
                        'unknown query limits retained', 'malformed pending metadata reported',
                        'source and protocol mismatch blocked on receipt side', 'unsupported disposition blocked'],
              'scope':'Synthetic offline evidence-parser checks, not trading/profit results.'}
    (ROOT/'PARSER_CHECK.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
