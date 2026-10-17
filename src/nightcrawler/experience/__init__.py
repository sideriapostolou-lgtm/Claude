"""The experienced team (owner: O8). Spec: docs/EXPERIENCE.md.

Experience is a GRADER: practice records, report cards, a loss library and a tested playbook. It never trades,
never writes Settings, specs or code, and in phases 1-2 it has no effect on trading at all (X1). Learning and
experience may only ever turn real trading OFF, never ON; risk limits and the kill switch are never learnable.

Phase 1 core (T3) - pure modules, standard library plus ``nightcrawler.learn`` only, no IO except reading the
packaged playbook:

* :mod:`~nightcrawler.experience.constants`   every threshold, the cells, the loss taxonomy, the feature catalogue
  and the known patterns; ``TAXONOMY_VERSION`` is their hash (§5.1, §6.3, §6.5).
* :mod:`~nightcrawler.experience.stats`       α_v and the α ledger fold, outbox idempotency keys, day blocks with the
  operator cap, always-valid bands, the stability veto, rough ranges, e-BH and n_eff (§4.7, §5.1, §6.5).
* :mod:`~nightcrawler.experience.cards`       the report cards: VV, EE, DS_net, coverage and the self-checks, each
  as the ``/api/page.experience`` member dict (§5.2, §9), and the team summary (§8.2).
* :mod:`~nightcrawler.experience.attribution` the seven parts that always add up to the trade (§6.2).
* :mod:`~nightcrawler.experience.losses`      descriptive loss types and their luck base rates (§6.3).
* :mod:`~nightcrawler.experience.features`    cells, verdicts and the feature catalogue as of a time; weekly lesson
  opening (e-BH at 10 %) that can only produce hypothesis drafts (§4.6, §6.5).
* :mod:`~nightcrawler.experience.texts`       every owner-facing string, and the no-gamification lint (§8).
* :mod:`~nightcrawler.experience.playbook`    the tested-rules registry: statuses and counts (§7.1).

Outcome labels live in :mod:`nightcrawler.learn.labels` (shared with the Coach). Boundary
(``tests/test_learn_boundary.py``): nothing here imports broker, wallet, risk, judge, http, sources, ledger, engine,
crawler, cocoon, radar or dashboard, and learn never imports experience.
"""
