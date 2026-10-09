# K1 the Desk: how to run the exam (for the session that has the key)

The owner adds `ANTHROPIC_API_KEY` to the Claude Code cloud environment (environment settings -> variables; never in
chat). A NEW session picks it up. Then, from `/home/user/Claude`, in this order, one stage per command:

```bash
python research/lab2/k1.py --stage train --check          # prerequisites only (data gates, PREREG, ledger)
python research/lab2/k1.py --stage train                  # deliberates first (budget $40), then the backtest
python research/lab2/k1.py --stage val                    # only if TRAIN shortlisted (budget $15)
# judge reads K1/val.md; a SELECTED verdict earns the ONE test look:
LAB2_ALLOW_TEST=1 python research/lab2/k1.py --stage test # budget $15; a TEST pass never funds real money by itself
```

Rules that the code enforces (see `PREREG.md`):

- The desk sees one as-of brief per alive coin at the first grid time >= g + 30 min; the brief holds nothing after
  tau (tested on real census bars: `tests/test_k1.py::test_no_lookahead_real_census_train`).
- Decisions are cached under `K1/decisions/<prompt version>/<config>/<brief hash>.json`. A re-run makes no API call.
  A stage that stops at its budget cap is REFUSED but resumable: run it again and it continues from the cache.
- A stage never scores an incomplete exam: with no key and uncached coins it refuses with "set ANTHROPIC_API_KEY".
- `--fake-client` is for `--debug` and tests only; its decisions go to `K1/decisions_fake/` (ignored by git).
- Commit `K1/decisions/` with the stage results: the exam record is what makes the result reproducible.

Costs. Counted on the real data (no returns looked at): TRAIN has 3,863 coins of which **1,408 are alive at the
desk's decision time** (36 %); VAL 1,278 / **488** (38 %). With real brief sizes (~900 input tokens, cached system
prompt, ~300-token memos) the panel costs about $0.008 per decision, solo Sonnet ~$0.003, solo Haiku ~$0.0003, so
TRAIN is roughly **$10-20** of its $40 cap and VAL **$4-7** of $15. A stage stops at its cap and resumes from the cache.
