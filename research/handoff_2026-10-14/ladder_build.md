# ladder_build (workflow wf_919eb4b6-46f)



---
## result 0 

The ladder is built and committed locally on `claude/kalshi-ladder`. Nothing was pushed or deployed. One part is not done: the permission check refused my edit raising the ceilings to $50,000, so the ladder currently stops at $20 a window.

**Worktree:** /home/user/Claude/.claude/worktrees/wf_919eb4b6-46f-1
**Branch:** claude/kalshi-ladder (from origin/claude/nightcrawler-memecoin-bot-Gwnb1S at c3ab6f8)
**Commit:** bbb49e51c182b868ef38c405ff50240cbc41f87d

**The ceiling raise: blocked and not done.** The permission check refused my edit to `config.py` that raised the window, open and day-stop ceilings to $50,000 / $100,000 / $30,000. I did not retry it another way. I also undid the matching raise I had already made to the risk book's inner limit (`LiveLimits`), so the limit can't be lifted by another route. Both ceilings stay at $20 a window, $40 open and $12 a day. Starting from $10, the ladder therefore has two rungs: $15/$30/$9 with 7 contracts, then $20/$40/$12 with 10 contracts. That second rung is the step the owner already approved at 16:00 UTC. Lifting the ceilings needs the user's explicit permission. After that it is a small change: the `hi=` values in `config.py` plus the `HARD_*` constants in `speeddesk_live_model.py`. A test already checks that the top rung would then be exactly $50,000 / $100,000 / $30,000 / 25,000 contracts.

**What is built (everything else in the spec):**
- **Rungs:** rung 0 is exactly the configured limits ($10/$20/$6/$10, 5 contracts), so deploying changes nothing at first. No rung goes below a configured value, and the $10 lifetime stop never changes.
- **Promotion:** only when all five conditions hold, one rung at a time.
- **Demotion:** one rung down after giving back 60% of a window from the rung's peak, never below rung 0.
- **Timing:** every change takes effect at the next window boundary, and each window keeps the limits it started with.
- **Addition beyond the spec:** a stop that trips while a promotion is still waiting for its boundary cancels that promotion. You may want to review this.
- **Limits used everywhere:** window, open, day stop and contract cap all come from the window's rung, for buys, the first buy, balancing buys, locks, status, order sizing, and the practice twin.
- **Saved state:** a new top-level `ladder` key that the previous release ignores. Nothing inside the saved books or intents changed. On restart the window count is rebuilt from the books. After a rollback and re-upgrade, the ladder starts again at rung 0.
- **Settings:** `SPEEDDESK_KALSHI_LADDER` (default true) and `SPEEDDESK_KALSHI_LADDER_MAX_WINDOW_USD` (default 50000, at most 50000).
- **Visible:** the panel and status line carry a `ladder` block (rung, limits, progress n/96, gain vs needed, room vs needed, cash vs needed, the demotion line), and `caps` now show the rung in force. The page feed exposes it as `kalshi_live.ladder`. Each change logs one `speeddesk_live_ladder` line with every number.

**Worth knowing:** the unchanged lifetime stop also keeps money at risk at any one moment below $10 (less any loss since launch), at every rung. So above rung 1 it binds before the day stop, and a bigger rung mostly adds fully hedged volume (complete pairs), not more unhedged risk.

**Files changed:**
- New: `src/nightcrawler/speeddesk_live_ladder.py`, `tests/test_speeddesk_live_ladder.py`
- Modified: `src/nightcrawler/speeddesk_live_model.py`, `src/nightcrawler/speeddesk_live.py`, `src/nightcrawler/config.py`, `src/nightcrawler/pagestate.py`, `tests/test_speeddesk_live.py`
- Docs: `.env.example`, `docs/SPEEDDESK_SPEC.md` (new section 9.2), `docs/ACCOUNTS.md`, `docs/WORKLOG.md`, `docs/COORDINATION.md`. The owner's quote is recorded in `config.py`, `ACCOUNTS.md` and the spec. The `COORDINATION.md` entry tells Codex the new data fields, since `pagestate.py` is a shared file.

**Tests:** 46 new tests cover:
- promotion only when all five conditions hold, each condition failing on its own;
- never mid-window, one rung at a time, counters restarting;
- demotion on give-back and the rung-0 floor;
- the configured maximum and the code ceilings;
- scaled limits in every check, and the lifetime stop still switching the desk to practice;
- persistence, restart and rollback, and unreadable saved state;
- the settings, the panel, status line and page, and the twin mirroring;
- a randomized run (20 seeds × 150 windows) checking every accepted order against its window's rung. It produced 52 promotions and 17 demotions.

Full suite: 4,755 passed, 12 skipped (network-only tests). Ruff is clean on every changed Python file and `mypy src/nightcrawler` is clean.

To keep the merge with `claude/kalshi-fix-speed` easy, the edits to `speeddesk_live.py` are a handful of small changes (startup, save, order sizing, step, panel) plus two new helper methods. The total-stop and reconcile code is untouched.


---
## result 1 

I found no path where an accepted order breaks the limits of its window's rung. The book checks every buy and lock against that rung, the $10 lifetime stop and the cash on hand. But the rules that decide when the ladder moves have holes: 10 failing tests across 7 bug findings, plus 2 notes. I made no changes to the worktree (`git status` is clean).

**Failing tests:** `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/test_ladder_adversarial.py` (it reuses the helpers in `tests/test_speeddesk_live_ladder.py`). Run from the worktree with `python -m pytest -q -p no:cacheprovider --rootdir . -c pyproject.toml <file>`. All 10 fail on commit bbb49e5; ruff is clean on the file.

### F1 HIGH: the ladder never sees a daily stop, so a promotion can raise the stop the same day it was hit
- **Where:** `speeddesk_live_ladder.py:257` and `:315-317` read only the flags `halted`, `integrity_error` and `day_stopped`. `speeddesk_live_model.py:301` sets `day_stopped` only when today's loss plus money at risk reaches the cap. But `can_buy` (`:378-379`) refuses any buy that would reach it. A settlement turns money at risk into loss one-for-one, so the sum never reaches the cap and `day_stopped` (and `halted`, `:286`) stays off in normal running. Condition 4 is therefore dead for daily and total stops; the existing tests trip them only by setting `day_pnl -= 60` by hand.
- **Evidence (`test_f1`, `test_f1b`):** after 82 wins, 14 losses on 2026-10-10 lose $5.88 of the $6 daily stop. The next buy is refused with `day_stop`, yet `last_stop_at` stays None. The ladder promotes on that same loss. From the next window the day stop is $9 and a buy on the same UTC day returns `""`.
- **Fix:** treat any refusal for `day_stop`, `total_budget` or `total_loss` as a stop (set a book-level `stop_seen_at` in `can_buy`/`can_lock`, or have `_decide` report it to the ladder). Also block a promotion while today's loss plus money at risk is within one contract cap's cost of the current day stop.

### F2 MEDIUM-HIGH: a promotion is checked once, then takes effect up to a window later without a re-check
- **Where:** `speeddesk_live_ladder.py:234-239` (`rung_for` switches on the clock alone) and `:262-273` (while a promotion is waiting, only a stop or a demotion can cancel it). `:294-296` measures gain and room from settled P&L only, ignoring money at risk and windows that have ended but not settled.
- **Evidence:**
  - `test_f2`: the gain clears the bar by $0.10 when the promotion is decided. The window under way then loses its $2.10 opening buy at rung 0, so gain minus money at risk is below the bar, and rung 1 still takes effect.
  - `test_f2b`: cash falls to $5 (rung 1 needs $30) before the boundary, and rung 1 still takes effect. Per-order cash checks still stop any overdraft; only the promotion rule is broken.
- **Fix:** make a waiting promotion provisional. At the first look at or after the boundary, before any order in the new window, re-check conditions 2, 3 and 5 using settled P&L minus money at risk, and re-check condition 4. Until it is confirmed, `rung_for` should return the previous rung. Use settled P&L minus money at risk when deciding, too.

### F3 MEDIUM: a waiting promotion hides a demotion due at the rung in force
- **Where:** `speeddesk_live_ladder.py:345-346` resets the peak when the promotion is decided. `:277` then measures the give-back against the waiting rung's larger window (60% of $20 = $12 instead of $9).
- **Evidence (`test_f3`):** at rung 1, the promotion to rung 2 is decided with $5.04 already given back. Losing $4.32 more in the window under way crosses rung 1's own line (peak minus $9). The desk still goes to rung 2.
- **Fix:** keep the in-force rung's peak and line until the boundary, and cancel the promotion (or demote) when they are crossed. The F2 re-check covers this if it includes the line.

### F4 MEDIUM: changing the configured floor changes what a saved rung means
- **Where:** `speeddesk_live_ladder.py:119-124` does not save the floor; `:177-185` restores the rung against the new one.
- **Evidence (`test_f4[15-1]`, `test_f4[5-2]`):**
  - Rung 1 was earned at a $10 floor. A restart with the floor raised to $15 trades $20/$40/$12 windows with a 10-contract cap at once.
  - The owner lowering the floor to $5 to cut risk still gets $15 windows with a 7-contract cap.
- **Fix:** save the floor (and the rung's window size) in the ladder state, and restart at rung 0 with a "rebased" note when it differs.

### F5 LOW: saved state can skip a rung
- **Where:** `speeddesk_live_ladder.py:126-141` checks only that each rung is an integer of at least 0.
- **Evidence (`test_f5`):** a saved state with rung 2, previous rung 0 is restored, giving a two-rung jump at one boundary.
- **Fix:** reject the state (start fresh) when the two rungs differ by more than one, or when `rung_from` is more than one boundary ahead of now.

### F6 LOW: a stop just before the boundary does not cancel a waiting promotion
- **Where:**
  - `speeddesk_live.py:1258-1266`: the ladder is looked at once a second at most, and later when the loop stalls.
  - `speeddesk_live.py:295-305`: the resume and day-reset tokens are applied after `ladder.start` and before the first look.
- **Evidence (`test_f6`):** an integrity error set 0.5 s before the boundary and seen 0.5 s after it leaves rung 1 in force. On restart, a stop saved in the books but never looked at is cleared by a token without being recorded.
- **Fix:** the F2 confirmation covers the boundary case. Also have the ladder look at the books once in `__init__` before the tokens are applied.

### F7 LOW: the contract cap has no inner clamp
- **Where:** `speeddesk_live_model.py:68-80` clamps the window, open, day-stop and total-stop limits but not the contract cap (`clip`); `speeddesk_live_ladder.py:72` sets each rung's cap as half its window.
- **Evidence (`test_f7`):** `LiveLimits(clip=25_000).clip == 25000`. The config `hi=25` bounds only the configured floor, not the rungs. Once the ceilings are raised, the top rung's cap is 25,000 contracts with no second check.
- **Fix:** add a hard contract-cap ceiling to `__post_init__`, kept separate from the ladder's own constants. Today the ladder takes its top from the same `HARD_*` values the clamp uses, so the "independent" guard is not independent.

### P1 MEDIUM (needs an owner decision): rung 2 brings back the 10-contract first buy
- **Where:** `config.py:511-516` records the owner's 16:20 UTC rule: "make sure it never happens again", with the first buy held to 5 contracts after two 10-contract first buys were run over. `speeddesk_live_ladder.py:72` makes the first buy 7 contracts at rung 1 and 10 at rung 2; the existing test `test_every_check_uses_the_windows_rung` accepts a first buy of 10 at rung 2.
- **Fix:** the spec asks for this and the owner approved the ladder, but nobody has told the owner about the conflict. Either keep the first buy at the configured cap and scale only balancing and lock orders, or get the owner's explicit OK.

### N1 LOW: what counts toward a rung's numbers
- **Gain and peak start too early.** They are taken when the promotion is decided (`speeddesk_live_ladder.py:345-346`), so the old-rung window under way counts toward the new rung's gain and peak, while the window count does not include it. Fix: take the starting P&L when the boundary is confirmed.
- **The room check skips the stop anchor and money at risk.** Room is `realized_pnl + 10` (`:296`); the true room above the stop is `realized - stop_anchor + 10 - at_risk`. It is cautious after a loss and resume, but too generous when positions are open or the anchor is above zero.
- **Demotion lags.** It uses settled P&L only (`:280`), so a late settlement leaves an extra window at the bigger rung.

**Checked and found sound:**
- Every buy and lock, the first-buy cap, balancing and lock sizing, and the open, window and day checks all use the window's own rung.
- The lifetime stop uses the configured $10 at every rung.
- The practice twin is updated before each placement and each step, and cannot differ from live while windows stay on 15-minute boundaries.
- A demotion and a promotion at the same boundary resolve to the previous rung. One change per boundary holds.
- A restart while a promotion waits restores its effective time.
- After a rollback the saved books are unchanged, and re-upgrading starts again at rung 0.
- The randomized run's "never above the rung" property holds.


---
## result 2 

**Ladder correctness review: commit bbb49e5 on `claude/kalshi-ladder`**

Worktree: `/home/user/Claude/.claude/worktrees/wf_919eb4b6-46f-1`. I made no edits. The repro scripts are in `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/` and run with `PYTHONPATH=src:tests python <script>` from the worktree.

Three rule violations need fixing before this goes live: two high, one medium. Two of them come from the same cause: the ladder resets its counters when it decides a change, not when the change takes effect.

## Findings

**F1 — High — promotion is locked in at decision time, and the rung in force loses its demotion protection until the boundary**
- **Where:** `src/nightcrawler/speeddesk_live_ladder.py:345-347` (`_change` resets `started_at`, `start_pnl` and `peak_pnl` at the decision); `:263-264` (only a stop cancels a waiting promotion); `:270` (`if pending ... return None`); `:266-269` and `:277` (while a promotion waits, the demotion test uses the pending rung's window and the reset peak).
- **Evidence (`peak.py`):** at rung 1, peak 99.76 and total 91.36, so the demotion line is 90.76. The promotion to rung 2 is decided. The rung-1 window under way then loses $2.10, so total 89.26 is below rung 1's line. `evaluate()` at the boundary returns None, and the next window runs at $20/$40/$12. By the spec's rule rung 1 should have dropped to rung 0; instead it went up.
- **Evidence (`boundary.py`):** promotion decided with room 25.22 ≥ 24.75 and G 20.68 ≥ 20.58. The window under way loses $2.10, so room 23.12 and G 18.58 now both fail. The next window still runs at $15/$30.
- **Fix:**
  - Keep the old rung's counters (start P&L, peak, results) running until the boundary.
  - At the boundary, re-check all five promotion conditions and the old rung's demotion line against those counters. Apply the promotion only if it still passes; if it fails, cancel it, or demote when the line is crossed.
  - While a promotion waits, test demotion against the rung in force (`prior_rung`) and its own peak.

**F2 — High — condition 4 ("no stop tripped in 24 h") never sees the daily or total stop binding**
- **Where:** `speeddesk_live_ladder.py:257` and `:315-317` read only the `halted`, `integrity_error` and `day_stopped` flags. `speeddesk_live_model.py:378` and `:381` refuse any order with `day_loss + at_risk + cost >= limit - EPS`, and the flags at `:301` and `:286` use the same threshold. Settling a window never raises `loss + at_risk`.
- **Effect:** in normal trading the flags only trip through manual edits (every stop test sets `day_pnl` or `halted` by hand), a lowered limit, or an integrity error. A day that used up its stop does not count as a stop.
- **Evidence (`daystop.py`):** day loss is 5.88 of 6, buys are refused with `day_stop`, and `day_stopped` is False. The ladder promotes, and after the boundary the same UTC day has a $9 stop and accepts a 5-contract buy.
- **Fix:** have the book record a stop time whenever `can_place` or `reserve_intent` returns `day_stop`, `total_budget` or `total_loss` (for example `book.stop_hit_at = now`), and have `evaluate` take the later of that and `last_stop_at`. Or define "stop tripped" as the day loss reaching the stop minus the smallest order cost.

**F3 — Medium — losing or winning windows from the previous rung that settle after a change are charged to the new rung's G and peak, but not to its n**
- **Where:** `speeddesk_live_ladder.py:217-221` (`_fold` updates the peak on every settlement), `:294` (`gain = realized - start_pnl`), `:204` (`_count` excludes windows that started before `rung_from`).
- **Evidence (`lag.py`):** after a 0→1 promotion, the rung-0 window under way settles after the boundary at -$2.10. Rung 1 then shows n=0, G=-2.10 and a 2.10 give-back.
- **Effect:** after a demotion from rung 2, a rung-2 window can lose up to about $12, which alone crosses rung 1's $9 line and demotes again to rung 0. In the other direction, a winning old-rung window inflates the next rung's G.
- **Fix:** in `_fold`, when a settled window started before `rung_from`, shift `start_pnl` and `peak_pnl` by its P&L. Equivalently, compute G as the sum of this rung's results and the peak from their running total. Fixing F1 covers most of this.

**F4 — Low — a stop-cancel resets the counters of the rung that never changed**
- **Where:** `:264` then `:345-347`.
- **Effect:** the cancel throws away the 96-window count (conservative) and also resets the peak to the current total (not conservative). A rung at peak 50, total 45, line 41 moves its line to 36.
- **Fix:** on cancel, restore the old rung's start P&L, peak and results instead of making a fresh state.

**F5 — Low — log and panel are inaccurate while a promotion waits**
- **Where:** `:336-339`, `:277`.
- **Effect:** a demotion while a promotion waits is logged as `demote` from r+1 to r, with `limits_before` at rung r+1, though r+1 never took effect. The panel's demotion line during that time is the pending rung's line, not the line of the rung in force.
- **Fix:** log it as `cancel`, with `from_rung = prior_rung`, and show the demotion line of the rung in force.

**F6 — Low — a "clamped" restore keeps the old rung's counters**
- **Where:** `:179-181`.
- **Effect:** when a lower `SPEEDDESK_KALSHI_LADDER_MAX_WINDOW_USD` clamps the rung, the start P&L, peak and window count carry over. The spec says counters restart after any change.
- **Fix:** when clamping, call `_fresh(book, now)` but keep `last_stop_at`.

**F7 — Info — the ceilings were not raised, as the build already reported**
- **Where:** `speeddesk_live_model.py:42` (`HARD_*` = 20/40/12/10) and `config.py` `hi=20/40/12`.
- **Effect:** the ladder tops out at rung 2 ($20/$40/$12, 10 contracts), not $50,000. Raising them needs the user's explicit approval, after which only those values change.

## Checked and correct
- **Sigma floor:** `max(sample SD, 0.105 × rung window)` (:293).
- **Window count:** n counts only settled windows with a bot fill that started at or after `rung_from` (:202-205).
- **Promotion conditions:** `2σ√n` with n=0 blocked (:311); house money `realized + total_loss_usd >= 1.65 × next window` (:296-297); the 24 h quiet period (:301); cash from a balance under 60 s old, net of reservations and debits, against the next rung's open budget (:298-319).
- **Promotion mechanics:** one rung at a time with no skipping (:270-273); a demotion is never doubled while another waits (:267-268); never below rung 0 (:280).
- **Rung limits:** match the spec ($15/$30/$9 with 7 contracts, $20/$40/$12 with 10). The total stop stays the configured one, and every buy, first-buy, balancing and lock check uses the window's rung.
- **Restore:** the window count is rebuilt from the books, including archived windows, so a saved list cannot inflate it. Unreadable states, the ladder switched off, or a rollback all restart at rung 0.
- **Old-code tolerance:** I ran the previous release (c3ab6f8, from `git archive`) against a state written by the new code at rung 1 with a 7-contract order. It loaded cleanly, ran at $10/$20/$6/$10, and its next save dropped the `ladder` key.
- **Status line, panel and logs:** they carry every number in the spec (rung, limits, n/96, G vs needed, room vs needed, cash, demotion line). A change logs exactly one `speeddesk_live_ladder` line, and the output stays valid JSON.


---
## result 3 

I fixed and committed every blocker and major review finding, plus the cheap minor ones; one owner decision is still open. Nothing was pushed or deployed, and the ladder still stops at $20 a window, because raising the ceilings needs your permission.

**Final sha:** `e7bd096fb2caff91a58df52ea50a5af745b275e5`, on `claude/kalshi-ladder` in `/home/user/Claude/.claude/worktrees/wf_919eb4b6-46f-1`, on top of bbb49e5.

**Tests:**
- Full `python -m pytest -q`: 4,783 passed, 12 skipped (network-only). That is 28 more than the build round.
- The ladder test file now has 74 tests.
- `ruff` is clean on every changed Python file and `mypy src/nightcrawler` is clean.
- The reviewer's adversarial file passes 9 of its 10 tests without edits. The 10th, `test_f6`, expected the old behaviour of returning nothing; the code now returns the cancel the reviewer asked for.

**Fixed, each with a regression test:**
- **R1-F1 / R2-F2 (high): daily and total stops never counted as stops.** Now any of these counts:
  - the day stop's own flag;
  - today's settled loss within $1 of the day stop;
  - a buy of even one contract refused by the day or lifetime stop. The risk book tells the ladder the moment this happens.

  A refusal that only makes a bigger order smaller does not count. This differs from the reviewer's suggestion, which also counted money at risk plus a full first buy. That version would have blocked almost every promotion, because an open first buy plus $5 is already more than the $6 day stop.
- **R1-F2 / R2-F1 (high): a promotion was locked in when decided.** It is now provisional until its window boundary:
  - Until then, the current rung keeps its limits, its counters and its own demotion line, and any stop cancels the promotion.
  - At the first check on or after the boundary, everything is checked again with money still at risk treated as lost: gain, room above the stop, cash, stops and the demotion line. The desk now does this check immediately, not just once a second.
  - It applies (logged as `confirm`) only if all of these still hold and nothing has traded yet in a window starting at or after the boundary. Otherwise it is cancelled and the limits stay as they were. The cancel leaves the rung's counters untouched.
- **R1-F3 / R2-F5: a waiting promotion hid a demotion that was due.** The demotion line now belongs to the rung in force. Crossing it demotes from that rung and drops the promotion, and the log line says so.
- **R1-F4: changing the configured floor changed what a saved rung meant.** The saved ladder now records the limits it was earned on. Different limits restart it at rung 0, logged as "rebased".
- **R1-F5: saved state could skip a rung.** A saved state with a two-rung jump, a change set beyond the next boundary, or a promotion applied before its boundary is now rejected.
- **R1-F6: a stop could slip through at the boundary or at restart.** The boundary case is covered by the re-check above. At startup the desk now looks at the books before a resume or day-reset token can clear a saved stop.
- **R1-F7: the contract cap had no inner clamp.** `LiveLimits` now clamps it (`HARD_CLIP` = 25, the same as the config limit). The ladder finds its top rung by asking the risk book's clamp instead of copying its numbers.
- **R2-F3 / R1-N1: counters started at the wrong time.** Counters now restart when a change takes effect, not when it is decided. A window from the earlier rung that settles later moves the rung's starting P&L and peak with it, so it never counts as the new rung's gain or loss. Counters and peak are rebuilt from the books on restart.
- **R2-F4: a cancel reset the counters of the rung that never changed.** It no longer does.
- **R2-F6: a restore clamped by a lower maximum kept the old counters.** The counters now restart; the last stop time is kept.
- **R1-N1 (room):** the room above the lifetime stop now subtracts money at risk and any resume anchor above zero.

**Not reproduced:** none. Every finding reproduced on bbb49e5.

**Deferred:**
- **R2-F7 / ceilings to $50,000:** still $20 a window, $40 open, $12 a day stop, 25 contracts, $10 lifetime stop. The permission check refused this edit in the build round and I did not try it again. It needs your explicit go-ahead, and `HARD_CLIP` must be raised along with it.
- **P1, needs an owner decision:** rung 2 brings back a 10-contract first buy, as the ladder rule says, which conflicts with your 16:20 UTC rule capping it at 5. The code follows the approved ladder rule. This is recorded as open in the spec, section 9.2, and in the WORKLOG.
- **N1 (demotion timing):** demotion still waits for settled P&L, as the rule is written. Money at risk only blocks or cancels a promotion; it never triggers a demotion early.

**What changed in the files:** most of the change is in `speeddesk_live_ladder.py`. The other code changes are small:
- `speeddesk_live_model.py`: the contract-cap clamp and stop reporting.
- `speeddesk_live.py`: three lines.
- `pagestate.py`: new whitelisted fields, so the town can show them.
- Docs: `.env.example`, a config comment, the spec (section 9.2), `ACCOUNTS.md`, a field update in `COORDINATION.md` and a new WORKLOG entry.

**For the owner, in plain words:** The ladder can no longer move up on numbers that have already gone bad. A promotion is a provisional "yes" until the next 15-minute window starts. Right before it would apply, the bot checks everything again, counting any money still on the table as lost. If the profit, the cushion above the $10 lifetime stop, the cash or the stops no longer hold, the promotion is cancelled and the limits stay the same. A day that came close to its daily stop now counts as a stopped day, so the bot can't step up on a bad day. Changing the base settings starts the ladder over at the bottom. The bot still starts at $10 a window with a 5-contract first buy, and the most it can reach is $20 a window. Two decisions are yours: whether to allow anything above $20, and whether the $20 rung may use a 10-contract first buy.
