"""Strategy families the learner can replay (docs/LEARNING.md §4, §8).

A family module defines ``NAME``, ``PROMOTABLE`` (engine-executable and allowed to become champion),
``CONTROL`` (a control such as the placebo: never promotable, spends no alpha) and
``entry_fn(mint, created_ts)`` -> the ``backtest`` ``entry_fn`` hook for one coin (None = the
strategy's own :func:`nightcrawler.strategy.entry_signal`). Exits, costs and fills always come from
``strategy.py`` and ``backtest.py``. A variant's hash covers the bytes of ``strategy.py`` AND its
family file, so editing either one makes every frozen variant of that family a new variant.
"""
