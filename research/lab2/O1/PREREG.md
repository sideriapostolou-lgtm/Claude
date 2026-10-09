# O1 pre-registration: operator-backed graduates as an entry universe

- **Version:** `o1-v1`. **Code:** `research/lab2/o1.py` (class rules imported from `g1.py`, unchanged).
- **Written:** 2026-10-09 ~05:40 UTC, by the lead, by hand, BEFORE any O1 run on any split.
- **Freeze.** The first `--stage train` run (provisional or not) writes `O1/prereg.lock` with this file's SHA-256;
  every later stage refuses to run if this file changed. Changes go to `O1/AMENDMENTS.md` as a new version.

## 1. Provenance: what was already seen (read this first)

This hypothesis was written AFTER G1's official TRAIN and VAL reports (`G1/train.md`, `G1/val.md`) showed the R0
random-entry host's mean net return by G1 class:

| Split | OPERATOR n | mean | 95% CI | every other class |
|---|---:|---:|---|---|
| TRAIN (10-01..10-05) | 233 | -3.0% | [-6.5, +0.4] | -28% to -46% (ORGANIC, COMPLETED, FACTORY); UNRESOLVED +3.9% wide |
| VAL (10-05..10-06 12:00) | 79 | +23.3% | [-10.1, +84.7] | -20% to -48% |

So O1's config `r0|r0exit` (R0 timing, R0 exit) on TRAIN and VAL is a RE-READ of a cell already seen, and the
other 5 configs differ from it only in timing and exit. Consequences, fixed here:

1. O1's TRAIN and VAL are **selection only** (<= 2 of 6 configs), never evidence. Their numbers are reported with
   this caveat in every O1 document.
2. The first unseen looks are **TEST** (one shot) and **CONFIRM** (one shot, when its data exists). **FINAL** is
   judged on the census VAL and TEST thirds only.
3. A TEST pass does not put real money in: the Coach's stage-2 forward proof (>= 150 paper trades over >= 14 days,
   anytime-valid lower bound > 0) still applies, per docs/LEARNING.md and craft rule G39.
4. The post-hoc origin is one more trial against the deflated Sharpe ratio: all 6 configs are counted, plus the
   G1 class tables that motivated them are already in the ledger as G1's runs.

## 2. Hypothesis and mechanism

An OPERATOR graduate (G1: >= 500 SOL of non-agent buying from <= 30 buyers in the first 120 s after migration) is
being supported by a market maker, launch team or paid bot operator with inventory and a motive to defend price for
a while. For an outside buyer entering 30-115 minutes after graduation, the market's base drift is about -20% per
trade (G1 R0 host, TRAIN). The hypothesis: while operator support lasts, that drift is absent or positive, so a
late $20 entry into an alive OPERATOR coin beats the same-timed entry into a random alive coin by enough to clear
the 1.4-5.1% round trip. The named loser is the operator's own exit liquidity: if operators dump on late buyers,
O1 reads WORSE_THAN_RANDOM and dies.

Not duplicated: G1 used OPERATOR only as a *gate* (skip); S1/D1 need wallet trades; M1 (killed) rode the mechanical
bid itself; X5/Y5/Z5 pin hosts to all classes. O1 is the only entry universe defined by the OPERATOR class.

## 3. Data, splits, universe

- Data: `graduates`, `b2_coins`, `b2_bars` through `common.load` (SOL-quoted, non-Mayhem, virtual reserve known,
  B2 complete). No B1. No CryptoHouse queries.
- Splits: `common.SPLIT_BOUNDS`, by coin creation, never shuffled. Stop rule 1 (data validation) via
  `common.validation_gates`.
- Universe at the decision: coin alive (R0 rule: >= $1,500 volume in 15 min and market cap >= $6,000) AND G1 class
  OPERATOR from as-of features only (`g1.g1_features(snap, None)` -> `g1.classify`). Class fields are legal from
  g + 120 s; every decision here is at >= g + 30 min. A coin whose class is UNRESOLVED or anything else is skipped.

## 4. Decisions, fills, exits (fixed)

- One decision per coin at the first grid time (minute + 20 s) at or after the target age; fills
  `common.FillConfig(exit_delay_bars=1)`: worst-side entry in the landing bar, every exit (stop, time) at the
  next bar's worst side. $20 tickets. Registered deadline: sell by g + 178 min.
- Stress runs (reported, never selected on): costs x1.5, rent $0.22, same-bar exits, no entry-bar exits.

## 5. Grid: 6 configs = 6 counted trials (cap 12)

| timing | meaning |
|---|---|
| `t30` | first decision at or after g + 30 min |
| `t60` | first decision at or after g + 60 min |
| `r0` | G1's R0 seeded random age in [30, 115] min (seed 0: the same draws G1 used) |

| exit | meaning |
|---|---|
| `r0exit` | catastrophe stop -50%, hold 60 min (PLAN R0 exit) |
| `tight` | stop -35%, hold 30 min |

Primary (PREREG 1 re-read) config: `r0|r0exit`.

## 6. Controls

- **Judged control (matched placebo):** the same timing (+-120 s) on ANY alive coin, 20 draws per signal, class
  unmatched. The test is the class itself, so the control must not match on it.
- **Diagnostic control:** class-matched (alive AND OPERATOR), isolates timing. Reported, never judged.
- **Reading** per config (`direction`): BEATS_RANDOM if the judged diff's 95% CI is above 0, WORSE_THAN_RANDOM if
  below 0, NEITHER otherwise, UNDERPOWERED under 30 trades.

## 7. Stage rules

- **TRAIN:** a config qualifies with n >= 30, mean > 0, mean without the top 2 trades > 0, judged-control diff > 0.
  Rank by the coin 90% CI lower bound, then mean, then timing order t30 < t60 < r0, then r0exit before tight.
  Shortlist = the top 2 (written to the lab's shortlist dir). No qualifying config: NO_CONFIG (dies); no powered
  config: UNDERPOWERED_TRAIN.
- **VAL:** the shortlist only; candidate = higher VAL mean (ties: TRAIN rank); SELECTED needs n >= 15, mean > 0,
  mean without top 2 > 0; n in [5, 15) is SELECTED_UNDERPOWERED (proceeds); n < 5 UNDERPOWERED_VAL; else FAIL_VAL.
- **TEST (one look, `LAB2_ALLOW_TEST=1`):** `common.verdict_entry` on the candidate at min mean +3% with VAL as the
  sign check; PLAN 3.6 auto-rejections apply.
- **CONFIRM (one look):** spent only if TEST is not REJECTED and TEST mean > 0 (or n < 5 = no evidence).
- **FINAL (one look):** judged on `final_val` + `final_test`; the census TRAIN third hosted the debug run.
- The debug run on the census TRAIN third reports counts only; no parameter is chosen from it.

## 8. Kill criteria

O1 dies at: TRAIN NO_CONFIG; VAL FAIL_VAL; TEST FAIL / REJECTED; CONFIRM not PASS; FINAL mean <= 0. A
WORSE_THAN_RANDOM primary reading on TEST is reported as evidence that operators are exit liquidity (useful as a
future veto candidate, pre-registered separately).
