"""Predictions are issued after durable feature-prefix recording, never reconstructed on replay."""

import threading

from nightcrawler.config import Settings
from nightcrawler.skipwatch import SkipwatchRunner, iter_records


def test_prediction_clock_is_actual_issuance_and_restart_never_backfills_predictions(tmp_path):
    clock = [1000.0]
    settings = Settings(data_dir=tmp_path)
    watch = SkipwatchRunner(settings, threading.Event(), clock=lambda: clock[0])
    feature = {'at': 1000., 'observed_at': 1000., 'window': 'market-a', 'window_start': 900., 'window_end': 1200.,
               'fair': .5, 'bid': .4, 'ask': .45, 'bid_top_size': 30, 'move_5s': 0,
               'prior_up': 0, 'prior_down': 0,
               'coverage': dict.fromkeys(('bitcoin', 'book', 'wallet', 'trades'), True)}
    original = watch.predictions.observe

    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] += .02
        return result

    watch.predictions.observe = delayed
    watch.emit('opportunity', {**feature, 'side': 'up'}, clock[0])
    watch.emit('opportunity', {**feature, 'side': 'down'}, clock[0])
    watch.close()
    rows = list(iter_records(tmp_path / 'skipwatch'))
    batches = [row for row in rows if row['kind'] == 'execution_prediction_batch']
    assert len(batches) == 1
    batch = batches[0]
    assert batch['observed_at'] == clock[0] > 1000.02
    assert batch['payload']['observed_at'] == batch['observed_at']
    assert batch['payload']['feature_prefix_seq'] < batch['seq']
    assert not batch['payload']['causal_execution_timing_verified']
    count = len(rows)
    restored = SkipwatchRunner(settings, threading.Event(), clock=lambda: clock[0])
    try:
        assert restored.started_at == 1000.
        assert restored.predictions.started_at == batch['payload']['shadow_started_at']
        restored.emit('opportunity', {**feature, 'side': 'up'}, clock[0])
        restored.emit('opportunity', {**feature, 'side': 'down'}, clock[0])
    finally:
        restored.close()
    after = list(iter_records(tmp_path / 'skipwatch'))
    assert len(after) > count
    assert sum(row['kind'] == 'execution_prediction_batch' for row in after) == 1
