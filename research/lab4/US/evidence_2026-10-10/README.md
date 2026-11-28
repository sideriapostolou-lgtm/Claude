# Inputs behind the 2026-10-10 desk audit, forensics and venue map

Copied from the session scratchpad with the same layout, so `CLAUDE_SCRATCHPAD=research/lab4/US/evidence_2026-10-10`
points `../venue_map_build.py` at them. Everything here came from PUBLIC endpoints (the Polymarket US gateway, no
key) or from the desk's own history snapshot; no key, token or account secret is in any file.

- `forensics/`: the real-money forensics (91 settled real bets joined with the venue's market records): `real_bets.json`,
  `gw_parsed.json` (one public gateway record per market), `master.json` (the join), `bets_table.md`, `sport_tables.md`.
- `lab4/p6_meta.parquet`: game facts for lab 4 P6 (polymarket.com history, TRAIN window only was read).
- `venue_dl/ev_20261010/*.json.gz`: the gateway's sports event pages at 2026-10-10 18:18 UTC (`desk_*`: the desk's own
  query; `window_*`: widened to 24 h). Stored gzipped (181 MB raw); `gunzip -k` them before re-running the build.
- `venue_dl/books*.jsonl`: per-market book statistics (shares and dollars traded, first trade, settlement).
- `venue_scripts/`: the fetch and load scripts that produced them (gentle, public, no key).
