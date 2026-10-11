# Z5 amendments

Changes to the Z5 pre-registration that a reader must be able to see apart from the text that was fixed before any
look at data. Each entry says what changed, when, what it rests on, and its approval status. `PREREG.md` carries the
amended text; this file is the audit trail.

## A1: the concentration check (Z5.4 and the TRAIN qualifier) and the class-matched control, added after the debug run

- **Recorded:** 2026-10-09, before any Z5 TRAIN run (no `Z5/prereg.lock`; no Z5 entry in `research/lab2/trials.json`).
  Version `z5-v1`, grid unchanged (8 configs).
- **Before.** The PREREG that the first debug run used (2026-10-09 03:31 UTC, `PREREG.md` sha256 `d2a0ad217c3f…`) had
  no concentration criterion: TRAIN qualified a filtered config on sample, mean, mean without the top 2, judged
  control, censoring and "the filter adds"; TEST / CONFIRM had the extras Z5.1-Z5.3.
- **After** (`PREREG.md` sha256 `032126ee8360…`, debug re-run 03:50 UTC; text in PREREG §8, §9 and §13):
  1. **TRAIN qualifier "Concentration".** R0 host: mean > 0 on the trades whose PLAN 4.2 class at the entry decision is
     not OPERATOR. M1 host: mean > 0 without the largest operator cluster (M1's own check).
  2. **Z5.4**, the same check on TEST and CONFIRM, **blocking** (FAIL).
  3. **`class_matched`**, a diagnostic placebo control for every R0 config (alive draws of the signal's class). Never
     judged.
- **What it rests on.** Counts from the debug run on the census TRAIN third, with returns, exit reasons, fill prices
  and placebo outcomes hidden: all 29 OPERATOR entries kept at c = 3.40 % belong to one operator cluster, and M1's
  cluster linking merges 66 of the 94 R0 entries into one component through shared early-buyer bots (so "without the
  largest cluster" would drop an arbitrary two thirds of R0's trades). These are decision-time structure (class, cluster
  membership), not outcomes.
- **Why it is not a parameter choice.** No grid value, threshold of the filter, guard constant or host changed. The
  change adds one blocking condition, so it can only turn a PASS into a FAIL, never the reverse. The census TRAIN third
  is reported apart at FINAL and is never judged (PREREG §9, FINAL).
- **Why it still needs this record.** The brief allows the census TRAIN third for debugging only. A decision rule
  that appears after that look must be visible as such (review finding Z5-2, 2026-10-09). The review offered two
  remedies: record it here as an explicit amendment before TRAIN locks the PREREG (taken), or keep Z5.4 as a reported
  diagnostic and judge only on the rules fixed before the debug run.
- **Approval status: pending the lead's sign-off.** `z5.py` enforces A1 as written. The lead accepts it by leaving it
  in place when the first TRAIN run (provisional included) locks `PREREG.md`. To take the other remedy instead, it must
  be done before that run: demote the "Concentration" qualifier and Z5.4 to reports (`robust_check` / `robust_mean`
  stay in every report) and note it here.
