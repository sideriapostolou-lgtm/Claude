"""The page preserves metric boundaries and cannot turn missing evidence into success."""

from nightcrawler.pagestate import _speed_latency, _speed_scorecard


def test_missing_or_invalid_latency_is_unknown_and_provider_text_is_not_exposed():
    raw = {'decision_to_ack': {'samples': 0, 'median_ms': float('nan'), 'p95_ms': -1,
                               'applicable': False, 'limitation': 'untrusted secret', 'headers': {'key': 'secret'}}}
    result = _speed_latency(raw)
    assert result['decision_to_ack']['samples'] == 0
    assert result['decision_to_ack']['median_ms'] is None and result['decision_to_ack']['p95_ms'] is None
    assert result['decision_to_ack']['applicable'] is False
    assert 'btc_exchange_to_decision' not in result
    assert 'secret' not in str(result)


def test_scorecard_cannot_enable_money_or_replace_unknown_metrics_with_zero():
    raw = {'day': '2026-10-12', 'scope': 'real', 'venue': 'kalshi', 'complete_windows': 0,
           'taker_fill_share': 2, 'median_imbalance': -.1, 'cap_change_allowed': True,
           'automatic_promotion': True, 'cash_usd': 25, 'private_key': 'secret'}
    result = _speed_scorecard(raw)
    assert result is not None
    assert result['complete_windows'] == 0 and result['pnl_usd'] is None
    assert result['taker_fill_share'] is None and result['median_imbalance'] is None
    assert not result['cap_change_allowed'] and not result['automatic_promotion']
    assert not result['day_complete'] and 'cash_usd' not in result and 'secret' not in str(result)
    assert _speed_scorecard(None) is None
    assert _speed_scorecard({**raw, 'venue': 'international'}) is None
