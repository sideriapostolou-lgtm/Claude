# Prop Engine

AI-native micro-prop pricing. A user speaks or types **any** prop —
*"third inning home run"*, *"Messi to score from exactly 29 yards"* — and the
system parses it into a structured spec, prices it with a real probabilistic
model, applies a risk-aware margin, returns book-ready odds, and grades the
bet after the game from official data.

This is the B2B engine play (the Simplebet path: build the pricing tech, books
write the check). The consumer demo doubles as a future 99¢ Community feature
("Ask the AI to price any prop").

## Architecture

```
utterance ──► PARSER (LLM → PropSpec JSON, rule-based fallback)
                 │  hard gate: ungradeable props are REJECTED with a reason
                 ▼
              DETERMINISTIC VALIDATION (game on slate, player on roster,
                 │                      inning 1-9, distance in bounds)
                 ▼
              ROUTER ──► PRICING MODEL by market_family
                 │         inning_event      Poisson HR intensity, factors fit
                 │                           from 227k PAs of 2024-26 play-by-play
                 │         coordinate_event  StatsBomb shot model (21k shots)
                 │         count_event       Poisson/binomial compositions
                 │         player_event      count_event with count=1
                 ▼
              MARGIN + RISK ENGINE (uncertainty-tiered vig, stake limits,
                 │                  exposure caps, velocity flags, quote log)
                 ▼
              API: {prop_id, fair_prob, book_odds, tier, max_stake, expires_at}
                 ▼
              GRADER (official MLB play-by-play / StatsBomb events)
                 └► settlement {win|loss|void} + play-level evidence JSON
```

## Run it

```bash
pip install -r requirements.txt

# tests (hermetic — no network)
python -m pytest tests/ -q                      # 76 passed

# demo web + API (needs network for MLB Stats API)
uvicorn api.main:app --port 8000                # then open http://localhost:8000

# data pipeline (caches are committed; re-run to refresh)
python -m backtest.corpus 2026-03-20 2026-07-06   # MLB play-by-play corpus
python -m backtest.statsbomb_corpus               # StatsBomb shot corpus
python -m backtest.fit_factors                    # fit factors -> data/fits.json
python -m backtest.fit_factors 2026-01-01         # leakage-free fits for backtest

# walk-forward backtest (67 days, ~8k markets)
python -m backtest.run_backtest 2026-05-01 2026-07-06
```

API endpoints: `POST /parse`, `POST /price`, `POST /quote` (the consumer
endpoint: parse+price in one call), `POST /grade`, `GET /markets/today`.
Quotes expire after 90 seconds.

The LLM parser uses the Anthropic API (`claude-sonnet-4-6`) when
`ANTHROPIC_API_KEY` is set; otherwise a deterministic rule parser covers the
same utterance space, so the whole system runs without a key.

## The Messi answer

> **"Messi to score from exactly 29 yards" → fair +26974, book +22275 (tier C, max stake $25)**

From his entire StatsBomb-recorded La Liga career (43,590 minutes):
**54 open-play shots from 28.5–29.5 yards, 2 goals.** League conversion in
that band is 2.9%; blended with Messi's own record it prices to a 0.37%
chance in a 90-minute match — a fair price of roughly **270/1**.

## Model (inning_event v1)

`λ(team, inning) = teamHR_perPA × expPA(half, inning) × inningFactor × parkFactor × pitcherBlend`,
`P = 1 − e^(−λ)`. Every factor is empirical (2,985 games, 227,335 PAs, 6,821 HRs):

- **Inning factors**: inning 1 runs 1.12× league HR rate (top of the order is
  guaranteed), inning 2 dips to 0.97, late innings fade to 0.94.
- **Expected PA per half-inning** counts unplayed halves as zero — bottom 9
  averages 2.28 PAs vs 4.37 for bottom 8, so "the inning may never happen" is
  priced automatically.
- **Slot occupancy** `P(lineup slot s bats in inning i)` makes player-level
  inning props possible (leadoff bats in inning 1 with p=1.00; the cleanup
  hitter 61% of the time). Lineups hydrate from the schedule ~2-4h pregame;
  slot priors otherwise.
- **Pitcher blending**: the starter faces 100% of inning-1 PAs but only 46%
  by inning 6 and 1% by inning 9 (empirical), so starter HR factors are
  weighted by that share and the bullpen factor takes the rest.
- **Rates are regressed**: hitter HR/PA gets a 200-PA league-average prior,
  pitchers 150 BF — a hot week can't produce insane prices.
- Every price carries `model_variance` from the sample sizes behind it; the
  risk engine consumes it.

## Risk engine

| Tier | Meaning | Margin | Max stake |
|---|---|---|---|
| A | liquid analog exists, low variance | 9% | $500 |
| B | standard exotic, decent data | 13.5% | $100 |
| C | thin data / weird constraint (exact distance, extras) | 21% | $25 |

Hard rules: never above 98.5% implied, per-game exposure cap, repeat-quote
velocity flag (sharp probing), every quote logged to `data/quotes.jsonl` for
CLV analysis.

## Backtest (walk-forward, binding doctrine)

Same pricing code path as live. Structural factors fitted on 2024-25 only;
team/pitcher rates accumulate day by day (a game on day D is priced with data
through D−1). Window 2026-05-01 → 2026-07-06, "HR in inning N" for all nine
innings of every game:

- **7,983 markets settled**, base rate 22.4%
- **Brier 0.17294** vs climatology 0.17388 (v1 raw model: 0.17313; the v1.1
  walk-forward Platt recalibration layer lifted the skill score from +0.43%
  to +0.54% — inning-level HR outcomes are mostly irreducible noise, so
  calibration is the real test)
- Calibration is tight in the 20–35% buckets (e.g. predicted 0.225 vs
  realized 0.238 on n=3,517)
- **Book P&L at $10 flat: +$4,203 on $79,830 handle = 5.27% hold**

v1.1 model additions, all exercised by the backtest:
- **Platt recalibration** (`engine/calibration.py`): 2-parameter logistic
  recalibration in log-odds, refit daily on a trailing 45-day window of
  settled markets — the reliability curve had a slope problem a global
  multiplier couldn't fix
- **Real bullpen split**: reliever-only HR/BF per pitching team (pitcher ≠
  half-inning starter) feeds the starter/bullpen blend instead of a
  full-staff proxy
- **League-drift hook** (`rates.hr_drift`) retained for live use
- **Slot priors + game ranking** (API): players without a posted lineup get
  their modal slot from the season corpus; unanchored utterances price every
  slate game and quote the hottest one

Full report: `backtest/reports/calibration_2026-05-01_2026-07-06.{json,md}`.

## Grading

Deterministic and auditable. MLB settlements filter official play-by-play
(`result.eventType`, `about.inning`, `about.halfInning`, batter/pitcher IDs)
and store the exact plays as evidence. Soccer settlements check StatsBomb shot
location + outcome against the distance band. Voids when the inning was never
played or no feed exists.

## Model weaknesses: found in v1, addressed in v1.1, and what remains

1. **Low-bucket underpricing** *(partially fixed)*. v1's 10–20% buckets
   realized ~2.5pts above prediction. A global drift multiplier didn't help
   (Brier 0.17311 — the overall level was already right; the reliability
   curve had a slope < 1). The Platt layer fixed the shape where the data is
   (Brier 0.17294, mid-buckets tight), but a residual remains at the low end:
   the 2026 late-inning/bullpen HR environment runs hotter than the 2024-25
   inning factors. Next: blend 2026 per-inning HR rates into the structural
   factors walk-forward, and add a game-time temperature term.
2. **Bullpen modelling** *(fixed in backtest + corpus rates)*. Reliever-only
   HR/BF per team now feeds the blend. Live `LiveRates` still uses the
   full-staff proxy (the Stats API has no cheap reliever split) — port the
   corpus split to the live path next.
3. **Game/lineup disambiguation** *(fixed)*. Unanchored utterances now price
   every slate game and quote the hottest; players without posted lineups get
   their modal slot from the season corpus. Remaining: re-price standing
   quotes when lineups post (the `hydrate=lineups` refresh hook exists).

## Not in scope (v2+)

Real money, KYC/licensing, live in-game repricing (needs websocket feeds),
NBA/NFL market families, correlated parlay pricing across user-generated legs.

## Repo layout

```
engine/    pricing models, rates providers, odds math, risk engine, legacy v0
parser/    PropSpec schema, LLM parser + few-shots, rule parser, validation
grading/   MLB play-by-play + StatsBomb settlement with evidence
backtest/  corpus pullers, factor fitting, walk-forward runner, reports
api/       FastAPI service (/parse /price /quote /grade /markets/today)
web/       single-page demo ("Say your bet") with mic input
data/      cached corpora + fitted factors (committed for reproducibility)
tests/     76 tests: parser (30 utterances), pricing, grading, risk
```
