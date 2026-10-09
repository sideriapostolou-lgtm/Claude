# K1 pre-registration: the Desk (a Claude panel decides)

- **Version:** `k1-v1`, prompts `desk-v1` (`research/lab2/desk_core.py`). **Code:** `research/lab2/k1.py`.
- **Written:** 2026-10-09 ~05:50 UTC by the lead, by hand, BEFORE any K1 run with a real model on any split.
- **Freeze.** The first `--stage train` run writes `K1/prereg.lock` with this file's SHA-256; any later change is a
  new version in `K1/AMENDMENTS.md`. The prompts are part of the pre-registration: `desk_core.PROMPT_VERSION`
  changes with any prompt edit, and a new prompt version is a new set of trials.

## 1. Hypothesis and mechanism

The owner's thesis: not a fixed rule but a team of capable minds reading each coin and deciding. Mechanism that
could beat the market's ~-20% per-trade drift for a late outside buyer: judgment on the *combination* of facts in a
brief (class, curve makeup, early buyers, current flow, name/metadata) that no single pre-registered rule captured,
plus the choice of stop and holding time per coin. The named loser is the same as for every late buyer: insider
inventory sold into whatever demand the desk thinks it sees. If the desk cannot tell, it reads NEITHER or
WORSE_THAN_RANDOM and dies like any other hypothesis.

## 2. Why the back-test is legitimate (leakage)

- The models' training knowledge ends before any lab coin existed (coins are from 2026-10). They get no tools, no
  web and no memory between coins. Each decision is one fresh conversation.
- The brief (`desk_core.build_brief`) reads only `common.AsOf` fields legal at the decision time (tau = t - 20 s):
  class per `g1.classify`, curve features known at graduation, the first-120-s pool window, the last 15 and 30
  minutes of completed bars, liveness. No outcome field, no data after tau.
- Creator-chosen text (name, symbol) passes the bot's prompt-injection guard (`nightcrawler.judge.sanitize_untrusted_text`)
  and the prompts say to treat it as data.
- Decisions are cached by (prompt version, config, brief hash): a stage run uses the cache only; the deliberation
  pass is the only place API calls happen. temperature 0.
- The model is told the market base rates (random -20%, factory -46%, operator ~0%) from G1/O1's TRAIN reports.
  Those numbers come from TRAIN, which is the search split; they are not outcomes of the coins being judged.

## 3. Universe, decision time, exits

- `common.load` universe (SOL-quoted, non-Mayhem, virtual reserve known, B2 complete).
- One decision per coin at the first grid time at or after g + 30 min, only if the coin is alive (R0 rule: >= $1,500
  volume in 15 min and market cap >= $6,000). Dead coins are never briefed.
- Entry iff the decision is `buy` with size >= $5. v1 applies a flat $20 ticket (the desk's size is recorded, not
  applied). Exits are the desk's: stop in [20%, 50%], hold in [15, 120] min (clamped), deadline g + 178 min. Fills
  `FillConfig(exit_delay_bars=1)`. Stress runs reported, never selected on.

## 4. Controls and reading

- Judged control: matched timing (+-120 s) on ANY alive coin, 20 draws per signal, no class matching.
- Reading per config: BEATS_RANDOM / WORSE_THAN_RANDOM / NEITHER from the judged diff's 95% CI; UNDERPOWERED under 30.
- Diagnostic: the correlation of the desk's stated confidence with the realized net return (dose-response), reported.

## 5. Grid: 3 configs = 3 counted trials (cap 12)

| config | models |
|---|---|
| `solo-haiku` | one call, claude-haiku-5-5 decides |
| `solo-sonnet` | one call, claude-sonnet-5-5 decides |
| `panel` | scout, skeptic, risk officer memos on claude-haiku-5-5, then claude-sonnet-5-5 decides from brief + memos |

Primary config: `panel`. Tie-break order: panel, solo-sonnet, solo-haiku.

## 6. Stage rules

Identical to O1/Z2: TRAIN qualifies a config with n >= 30, mean > 0, mean without top 2 > 0, judged diff > 0;
rank by coin 90% CI lower bound, then mean, then CONFIG_ORDER; shortlist top 2. VAL candidate = higher VAL mean
(SELECTED n >= 15; [5, 15) SELECTED_UNDERPOWERED; < 5 UNDERPOWERED_VAL; else FAIL_VAL). TEST one look via
`common.verdict_entry` at +3%; CONFIRM one look; FINAL judged on the census VAL/TEST thirds. Debug (census TRAIN
third) with the FAKE client only: counts, no returns, no parameter chosen.

## 7. Budgets (API spend per stage, hard caps; `--budget-usd` may only lower them)

debug $2 (fake client: $0) · TRAIN $40 · VAL $15 · TEST $15 · CONFIRM $40 · FINAL $15. A stage that hits its cap
refuses (decisions so far stay cached; a re-run resumes). A stage never runs with missing decisions.

## 8. Kill criteria and what a pass means

K1 dies at TRAIN NO_CONFIG, VAL FAIL_VAL, TEST FAIL/REJECTED, CONFIRM not PASS, FINAL mean <= 0. A TEST pass does
not fund real money: the Coach's stage-2 forward proof applies (>= 150 paper trades over >= 14 days with an
anytime-valid lower bound above 0), and the live desk would run under Jev's existing fail-closed, budget-capped
path. Real money can be switched OFF by learning, never ON.


## Amendment 1 (2026-10-09 12:55 UTC, before any real decision was scored)

The API for the Claude 5 models (SDK 1.12) has no `temperature` parameter; the request no longer sends one. The
registered reproducibility guarantee therefore rests on the decision cache (every decision is stored once per
prompt version, config and brief hash and never re-asked), not on deterministic sampling. Prompt version unchanged
(`desk-v1`). Budget caps unchanged. The owner funded $25 of credits on 2026-10-09 and chose to supply the key in the
chat; TRAIN runs with `--budget-usd 14`, VAL and TEST with `--budget-usd 5.5` so the whole exam fits the credit.

## Amendment 2 (2026-10-09 13:05 UTC, before any real decision was scored)

The live smoke test showed Haiku 5.5 spending its whole 400-token memo budget on hidden thinking (31 characters of
memo survived). The desk now sends `thinking: disabled` on every call and allows 500 output tokens per memo; the
decider keeps 400. This keeps the exam at ~$0.005 per panel decision. Prompts unchanged (`desk-v1`).
