# Reproduce RCL-v1 without trading

This directory contains independently written, standard-library-only research code. No external bot code is imported. Never run the external repository or connect a trading account for this experiment. Sources and boundaries are in PROTOCOL.md; amendment1 preserves the original declaration.

Keep the directory layout shown here. Obtain the **public release metadata**, without market-data parsing, for Strobingn/kalshi-odds-app tag scalper-data from GitHub's releases API and save it as RELEASE_METADATA.json in this directory. The exact metadata hash is recorded in CONFIRMATION_FREEZE.json. Raw market files are not redistributed here: license and producer provenance remain unresolved. The collector checks each release asset's published SHA256 and writes bounded public-GET receipts. Official Kalshi and Coinbase responses have their own raw hashes; historical revisions may prevent a later re-fetch from reproducing exact bytes. Preserve those differences rather than silently replacing files.

Commands from this directory, using Python3.11+:

```sh
python root-data/fetch_data.py --partition dev
python sol-replay/run_partition.py --partition dev --data-root root-data --cards RULE_CARDS.json --out results
python root-data/fetch_data.py --partition val
python sol-replay/run_partition.py --partition val --data-root root-data --cards RULE_CARDS.json --out results
```

Before confirmation access, reproduce the fake tests, mypy and Ruff checks in CHECKS.json, independently review the exact sources, and validate **all** entries in CONFIRMATION_FREEZE.json. That dated freeze was published before the original confirmation download. Do not replace a freeze with an empty list and two true booleans: the lightweight script guard is a checksum tripwire, not an independent authorization or security boundary. Code, tests, rules, original protocol, amendment, collector, metadata identity and review receipts must all match the complete published manifest. Confirmation windows are October10–12UTC only; do not fetch October13 or our unrelated sealed research TEST.

```sh
python root-data/fetch_data.py --partition confirmation
python sol-replay/run_partition.py --partition confirmation --data-root root-data --cards RULE_CARDS.json --out results
```

`evaluate.combine` accepts **only** rows explicitly labeled1000ms_current_targets and delay1000, with unique market/window identities and the declared VAL/confirmation calendars. Secondary target/hold/delay cells are reported separately; never select the best one as if it were preregistered primary. Development results are excluded from pooled evaluation. Every results file preserves input hashes, data-quality counts, fees, unknown entry/exit bounds and planned-window denominators.

This is a sampled-taker proxy, not the source's actual GTC queue execution. Historical bar publication is assumed at minute-end+1second; APIs do not establish first visibility or revisions. A quote seen after1/3seconds is sampled availability, not continuous quote survival. One-contract gains are hypothetical and cannot be multiplied into a realistic larger-budget projection. Real live bot performance, its cumulative losses, all existing caps/stops and its unresolved execution/data tasks remain separate and unchanged.
