"""The self-learning loop (owner: O7). Spec: docs/LEARNING.md.

Phase 1 - forward logging, shadow book and scoreboard; trading behaviour is unchanged:

* :mod:`~nightcrawler.learn.store`     ``learn.db`` (SQLite WAL): coins, fetch queue, variants, evidence,
  scoreboard, outbox (-> ``learn`` receipts, exactly once), learner lease. Advisory only: the
  champion is a fold over receipts, never a read of this file.
* :mod:`~nightcrawler.learn.tape`      append-only JSONL tape per first-seen UTC day: writer (fsync, torn-line
  repair, hourly segment roots, atomic seal), reader and the leak-free ``TapeView(as_of)``.
* :mod:`~nightcrawler.learn.recorder`  ``RecorderThread``: pump.fun census, candle fetch queue, DexScreener
  snapshots; its own capped ``HttpClient``, a 429/403 circuit breaker, restart with backoff.
* :mod:`~nightcrawler.learn.variants`  ``VariantSpec``, hard bounds, Settings anchors, ``variant_hash``, seeds.
* :mod:`~nightcrawler.learn.replay`    frozen variants replayed through ``backtest.Backtester`` on the tape.
* :mod:`~nightcrawler.learn.evidence`  pure statistics: betting e-processes, LB, proof, ETA, CUSUM.
* :mod:`~nightcrawler.learn.job`       the learner child (``nightcrawler learn run --incremental``): lease,
  seeds, judged days replayed once with per-coin commits, the scoreboard; limits, no secrets.
* :mod:`~nightcrawler.learn.card`      ``learning_card_state(settings, now)`` for the dashboard (never raises).
* :mod:`~nightcrawler.learn.gate`      the statistical constants (docs/LEARNING.md §5.9).

Boundary (``tests/test_learn_boundary.py``): learner modules import none of ``broker``, ``wallet``,
``risk``, ``judge``, ``http`` or ``sources``; the recorder imports only ``http``, ``sources`` and
``learn.{tape,store}``. Learning never writes Settings and never trades.
"""
