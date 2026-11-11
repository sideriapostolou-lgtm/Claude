# bid_pull_build_review (workflow wf_95208aa2-fc6)



---
## result 0 

WORKTREE: /home/user/Claude/.claude/worktrees/wf_95208aa2-fc6-1
BRANCH: claude/kalshi-pull. It was cut from origin/claude/nightcrawler-memecoin-bot-Gwnb1S and then rebased onto the newer tip 61ca112 after the ladder (PR #40) merged. It has no upstream and is not pushed.
COMMIT: 8a5b4fe39cd950fab71cadcd6eaace09520c4b2a, one local commit with the requested trailer lines.

TESTS: full `python -m pytest -q -p no:cacheprovider`: 4,831 passed, 12 skipped (network). I edited docs and two comment lines after that run started, so I re-ran the tests that read docs plus the Kalshi files: 374 passed. Ruff is clean on the changed Python files and `mypy src/nightcrawler` is clean. The new file tests/test_speeddesk_live_pull.py has 28 tests:
- a 1.06c move within 0.3 s cancels both resting bids with reason `pull`, and no bid rests until 9.8 s after the move; they come back at the new fair
- a 0.8c move does not pull (one test that dips and recovers, one that just rises)
- a 1.5c move cancels under the old reprice rule and the hold still applies
- the twin keeps its bids, cancels them later under the old reprice rule, and in a held window rests the bid the old rule would have sent
- a lock still fires during a hold
- no cancel is re-sent after Kalshi accepted it while the order list lags
- 20 s of 1.2c jumps give exactly 2 cancels and never more than 5 writes in a second
- the send guard refuses a bid whose fair moved on its way, and sends it with the guard off
- with the guard off, behaviour is the same as today
- pulls count only while real money is on
- unit tests for the trigger, restart persistence and the A/B comparison
- the panel numbers and the page whitelist
- validation of all four settings

FILES CHANGED:
- src/nightcrawler/speeddesk_live_pull.py (new): the rule's state only, no orders. It holds the fair history, triggers, holds, daily counts, the saved `since`, and `compare()` for the A/B.
- src/nightcrawler/speeddesk_live.py: the hooks.
  - Trigger check in `on_tick`, in `step` and in `_cancel_unsafe`.
  - `pull` cancel reason, checked after the stale-bid rules.
  - Hold check in `_decide`, and a pull check in `_send_guard`.
  - `_twin_cancel`, `_twin_unpulled` and `_twin_unpulled_bid` for the twin control.
  - `pull` block in the panel and status line, saved state key `pull`, and one `speeddesk_live_pull` log line per pull. These lines are kept out of the panel's latest events.
- src/nightcrawler/speeddesk_model.py: `PracticeDesk.cancel_order` (cancels one twin order).
- src/nightcrawler/config.py: the four settings and their validation.
- src/nightcrawler/pagestate.py: `_kalshi_pull` whitelist, exposed as `kalshi_live.pull`.
- .env.example, docs/SPEEDDESK_SPEC.md (new section 9.3), docs/WORKLOG.md, docs/COORDINATION.md (data-contract note for Codex). No Codex town files were touched.

LEFT OUT / CAVEATS:
1. The twin is a copy of the live bot's decisions, not an independent bot. To make it "no pull", it keeps pulled bids under the old cancel rules and places the old rule's bid in held windows. Known approximations:
   - its window-wide cancels (unchanged from today) also cancel its kept bids;
   - when the send guard refuses a bid because of a pull, the twin's copies in that window are cancelled, and it re-bids on the next decision;
   - the take-available reprice rule is not copied, because takes are off (`SPEEDDESK_TAKE_EDGE=1.0`).
2. The live-vs-twin difference also contains the existing gap between real and simulated fills. That is why the panel shows a `week_before` baseline next to `since_pull`; judge the change in the gap, not the gap itself.
3. With the defaults, a single jump holds a window about 10 s, not 5 s: it keeps triggering while the old fair is inside the 5 s lookback, then the 5 s hold runs.
4. When claude/kalshi-fix-speed merges, `_pull_watch` must compute the fair exactly as `_decide` does (that branch adds `settles_on_average` to `fair_up`).
5. The owner also said these bots seem to run without daily or lifetime stops. Caps and stops are unchanged here; any change needs his explicit numbers.
6. Not deployed, so there is no live verification yet.


---
## result 1 

**Pull guard correctness review (branch claude/kalshi-pull, commit 8a5b4fe)**

Verdict: the real-money side is correct. Pulls only ever cancel, locks still go through, and an accepted cancel is never re-sent. The weak part is the A/B control. In a confirmed case the practice twin pulls harder than the live bot, and the panel numbers can't measure the pull's main effect.

What checks out:
- **Fair:** the trigger uses the same `fair_up` inputs as `_decide`, per window, at the current clock. The snapshot is refreshed before the live `on_tick` callback (speeddesk.py:221-222), so there is no lag and no look-ahead.
- **Window and direction:** each window uses its own strike and expiry. Both directions trigger (`max(up-low, high-up)`).
- **Order of rules:** the stale-bid and reprice rules are checked before the pull.
- **Locks:** `_lock` and `_lock_guard` never look at the pull.
- **Cutoff:** pulls are not counted from `end - lock_s`, and the "Window cutoff" cancel still applies there.
- **Panel windows:** maker fills for live and twin are counted over the same set of windows.
- **Tests:** the 28 new tests pass.

**Findings, most severe first**

1. **HIGH (A/B fairness, confirmed by a probe): the twin is left with no bid after its kept bid is repriced, while the real re-bid stays up.**
   - Where: speeddesk_live.py:853-870 (`_twin_unpulled`), 877 and 1598 (`_twin_unpulled_bid` only runs for held windows), 1581 (`if pending ... continue`), 1330 (the twin refuses the copy of the real re-bid as `order_pending` while its kept bid is resting).
   - Evidence (probe `test_probe_a.py`): after the hold, the real bot rests down .46 / up .47 at fair .5053. The twin keeps its .47 / .47 bids priced at fair .50. Fair then moves to .512 for 6 s. The real bids stay up (0.7c from their fair). The twin cancels both of its bids (1.2c from their fair) and ends up with no bids. The old rule would have repriced and re-bid at .512. The twin stays bidless until the real bid ends, which can be up to its 30 s expiry. So the control gets fewer maker fills, the pull's fill cost looks smaller than it is, and the P&L comparison is skewed.
   - Fix: when `_twin_unpulled` cancels a kept bid for reprice or bid-above-fair, mark that window and side as owed a bid. In `_decide`, before the `pending` skip, call `_twin_unpulled_bid` for owed sides even when the window is not held. Add a test for this exact sequence.

2. **MEDIUM (measurement): "P&L on windows both traded" leaves out the pull's main effect.**
   - Where: speeddesk_live_pull.py:196-200.
   - Evidence: the pull's effect is fewer fills (18% fewer in the replay). A window where the pull stopped live from trading at all is dropped, and the twin's loss or gain in that window is dropped with it. With $10 windows and 5-contract orders, that can be many windows. This follows the requested spec, but it is the number the owner will use to decide whether to scale.
   - Fix: also show live and twin P&L over windows either side traded, counting a side that did not trade as 0. Keep "both traded" as a secondary number.

3. **MEDIUM (confound): lock costs land only on the live side.**
   - Where: speeddesk_live.py:908-910 (live P&L from `book.settled`, which includes lock fills); `_send_lock` (≈1479) never copies to the twin, and `PracticeDesk` has no lock logic.
   - Evidence: the pull also cancels the resting bids that would complete pairs. That leaves more windows half-filled, so live buys more locks at the ask and the twin buys none. The `week_before` baseline cannot absorb a change in lock frequency that the pull itself causes.
   - Fix: add lock count, contracts and cost per window to `since_pull` and `week_before`, or show P&L with lock fills separated out.

4. **MEDIUM (hold length vs the evidence): with the defaults, one jump holds the window about 10 s, not 5 s.**
   - Where: speeddesk_live_pull.py:108-120 and 127.
   - Evidence: every sample keeps triggering while the pre-move fair is still inside the 5 s lookback, then the 5 s hold runs. The test asserts 9.8 s. The replayed variant was "pull all bids for 5 s after the move". If the replay used one trigger per move, the live rule holds twice as long, and the +28.1c / 18%-fewer-fills result does not describe what is live. The replay code is not in the repo, so I could not check this.
   - Fix: check the replay's trigger definition. If it used one trigger per move, reset the history to the current sample after each trigger, so only a new 1c move triggers again.

5. **MEDIUM (merge hazard, verified): after the speed branch merges, the trigger would silently use a different fair.**
   - Where: speeddesk_live.py:839 (`_pull_watch`'s own `fair_up` call).
   - Evidence: `git diff 61ca112...claude/kalshi-fix-speed` adds `settles_on_average=True` to all four existing call sites (`_stale_bid_reason`, `_send`, `_send_guard`, `_decide`). A clean merge leaves `_pull_watch` on the plain fair. `blocks()` would then compare the averaged fair against a history of plain fairs, which can refuse sends for no real reason.
   - Fix: add one `_fair_up(window, snapshot, now)` helper and use it at all five sites now, plus a test that `_pull_watch` samples the same value `_decide` uses.

6. **LOW-MEDIUM (A/B, confirmed by a probe): one send-guard refusal wipes every twin bid in the window, kept bids included.**
   - Where: speeddesk_live.py:1393 (`real_order_rejected` cancels the whole window).
   - Evidence (probe `test_probe_b.py`): forcing one `blocks()` to return True just before the hold ends cancels both kept twin bids. The twin's bids are replaced by copies of the real re-bid at new prices (down .46 instead of .47). Without the pull there would be no refusal, and the twin would keep its .47 / .47 bids. The builder documented this as an approximation.
   - Fix: have `_send_guard` record when a refusal came from the pull. In the rejection path, for those, keep the twin's copy resting (add it to `twin_kept`) instead of cancelling the window.

7. **LOW: the baseline gets contaminated when settings change.**
   - Where: speeddesk_live_pull.py:84-88.
   - Evidence: any change to the four settings restarts `since`. `week_before` then covers days when the pull was already live under the old settings.
   - Fix: save the first time the guard ever went live and compute the baseline from before that, or save the start time of each set of settings.

8. **LOW: twin logic writes to the real risk book.**
   - Where: speeddesk_live.py:889.
   - Evidence: `_twin_unpulled_bid` calls the real `book.can_buy`. At size 1, a stop refusal there calls `_note_stop`, which sets `stop_hit_at` and the ladder's `last_stop_at` (this can delay a promotion). The old flow's real `_send` would have done the same, so the effect is nearly equivalent, but it is still twin-only logic changing real state.
   - Fix: use a check with no side effects (`_buy_verdict`), or the twin's own `can_buy`.

9. **LOW: a restart loses the hold.**
   - Where: speeddesk_live_pull.py:170-171 (only `since` and `days` are saved).
   - Evidence: after a restart in the middle of a hold, the bot can re-bid as soon as the startup reconcile finishes. A bid decided before a trigger just before the restart is no longer pulled.
   - Fix: save `last_trigger` and `active` per window and restore them if they are still within the hold.

10. **LOW (latent): the take-available reprice is not copied for kept twin bids.**
    - Evidence: if takes are turned back on, the twin refuses a copied take as `order_pending` whenever it holds a kept bid on that side, and the kept bid stays up.
    - Fix: model the old take-available cancel in `_twin_unpulled`, or refuse to run the A/B while `SPEEDDESK_TAKE_EDGE` is below 1.

11. **LOW (speed and robustness): the A/B numbers are computed inside every save.**
    - Where: speeddesk_live.py:898-918, reached through `checkpoint()` → `panel()`.
    - Evidence: this includes the save in `_cancel` that runs before the cancel is sent, and the durable save before each order. `compare` is recomputed over all windows and fills every time a fill arrives. If that code ever raised, it would block every cancel.
    - Fix: compute the pull's A/B in the heartbeat or panel only, not in the saved state.

12. **NIT:** `pulls_today` counts triggers even when no bid is resting, or during a daily stop. `observe()` rescans the whole history on every sample, and the 4,096-sample cap can drop samples silently if the lookback is set as high as 30 s.

Files are in /tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/review:
- test_probe_a.py
- test_probe_b.py


---
## result 2 

No change I found lets the guard add exposure, break a cap ($10 window / $20 open / $6 day / $10 lifetime) or block a lock. It never sends duplicate cancels, and nothing is ever sent again after Kalshi accepts a cancel. I found one High problem: a pull cancel that fails is never retried. Worktree 8a5b4fe was left untouched (git status clean).

Simulation results, defaults unless noted:
- **1c oscillations, flip every 0.3, 2 or 5.2 s, 10 minutes:** 2 cancels total, no creates, at most 2 writes/s. The window stays held the whole time, so it never trades.
- **1c oscillations, flip every 10.2 s, 10 minutes:** 114 creates and 116 cancels, at most 4 writes/s, but up to 15 reads/s demanded against the 10/s budget. With the pull off: 0 writes, 5 reads/s.
- **Random walk (0.07c per 100 ms), 10 minutes:** up to 6 writes inside 0.6 s (M2).
- **Lowest allowed settings** (move 0.002, lookback 0.5 s, hold 0), random walk for 5 minutes: 271 creates and 273 cancels, up to 14 writes/s and 40 reads/s demanded.

The client still caps the wire at 5 writes/s and 10 reads/s. When the bot asks for more, the extra calls wait.

H1 — A pull cancel that fails, or cannot be sent, is never retried once a reconcile runs
- **Where:**
  - speeddesk_live.py:796-797 skips the cancel when `cancel_requested and not uncertain`, treating that as "Kalshi acknowledged".
  - speeddesk_live.py:1160-1163: the reconcile sets `uncertain = False` whenever the order list's filled count matches the books, even if no cancel was ever accepted.
  - Ways in:
    - :976-979: with no order id, `cancel_requested` is set and nothing is sent.
    - :999-1008: on a 503, 429, timeout or transport error, `uncertain` is set and the retry is gated until `retry_at`.
    - :1237-1238: the same reconcile then resets `errors` and `retry_at`.
- **Evidence:**
  - Scratch test `test_a_pull_cancel_that_fails_inside_a_reconcile_is_retried`: the fair swings 1.06c during the order-list read, the first pull cancel gets a 503 and the second succeeds. Ten seconds later order-3 is still resting and only `['order-4']` was cancelled. The bot's status reads "Reconciling an uncertain order; no new orders".
  - Variant `test_a_pull_on_a_bid_whose_create_timed_out_still_cancels_it`: the create reply timed out, then a pull fired. No cancel is ever sent, and the intent ends with cancel_requested=True, uncertain=False.
  - The same failure happens on the previous tip 61ca112 with a 1.5c reprice (`test_base_stale.py`), so the root cause predates the pull. The pull adds a frequent new reason that goes through it. Pulls often fire mid-reconcile, because `_read` runs `_cancel_unsafe` after every account read.
- **Impact:**
  - The pulled bid rests until it expires on Kalshi (at most 30 s, never past the lock-period start). That is exactly the exposure the guard exists to remove.
  - The old stale-bid rules are also switched off for that bid.
  - Every new order and lock is blocked for that time.
  - Caps still hold, because the reservation stays booked.
- **Fix:** record acknowledgement explicitly. Keep an in-memory `self.cancel_acked: set[str]`; nothing is saved, so a rollback is safe, and startup cancels everything anyway.
  - In `_cancel`, add the order after a 200 or a definite 404.
  - Remove it on any failure and on the no-order-id path.
  - At line 796, skip only when the id is in `cancel_acked`.

M2 — The bot asks for more than 5 writes/s with default settings, so the client delays a needed pull cancel
- **Where:**
  - speeddesk_kalshi_client.py:141-152 and :178: creates and cancels share one rolling 5/s budget, and the wait sleeps under the client lock.
  - speeddesk_live.py:1597-1606: creates are sent with no room kept for cancels.
  - config.py:540: PULL_HOLD_S may be 0.
- **Evidence:** `test_peak_write_burst_detail` shows six writes within 0.6 s: reprice cancel + create, reprice cancel + create, then two pull cancels. On the wire the second pull cancel waits about 0.4 s. With the pull off the peak is 4. At the lowest allowed settings the bot asks for 14 writes/s.
- **Fix:** before a resting create, skip it if writes in the last second are at least WRITES_PER_S − 2. Add a small `writes_last_second()` to the client for this, or give cancels their own budget (still under Kalshi's 10/s). Also require PULL_HOLD_S ≥ 1, or add a minimum re-bid interval per window after a pull.

M3 — Every pull cancel forces an immediate account re-read
- **Where:** speeddesk_live.py:799 sets `account_at = None` on the first cancel request, including for `pull` (and :1413 after each create).
- **Evidence:** with 1c oscillations flipping every 10.2 s, read demand peaks at 15/s against the 10/s budget; with the pull off it is 5/s. A pull that fires while a read is waiting on the budget only gets its cancel after that read returns (up to about 1 s).
- **Fix:** don't clear `account_at` when the reason is `pull`. The hold already blocks new bids in that window, and `_waiting_reason` already blocks new orders until the order list confirms the cancel. The regular 1 s reconcile confirms it well inside the hold.

M4 — The twin is not a no-pull control in choppy markets, which biases the A/B toward zero
- **Where:**
  - speeddesk_live.py:845-851: `_twin_cancel` for any non-pull reason cancels every twin bid in the window, including kept ones.
  - :1329-1334: `_send` copies every post-pull real bid into the twin.
  - :792-795: the stale-bid rules are checked before the pull.
- **Evidence:**
  - 1c oscillation, flip every 10.2 s, 120 s: with the pull on, the twin had 20 "reprice" cancels and 24 rests, matching the real bot's 24 creates. A genuine pull-off run had 0 twin cancels and 4 rests.
  - In the 10-minute run, 58 pulls were counted but `bids_pulled_today` = 2. The other 114 cancels at trigger moments were logged as "reprice": re-bids land at an extreme fair, so the old 1c rule fires first.
  - Caveat 1 in the build notes admits the mechanism but not this size. In the market the guard targets, live minus twin understates the effect the owner would scale on.
- **Fix:** while a window has kept twin bids, have non-pull cancels cancel only the matching twin order (`twin.cancel_order(intent.twin_order_id)`). Count a cancel as a pull whenever `pulled_since` is true, even if a stale rule also applies (panel only). Longer term, the twin should make its own decisions without the hold.

L5 — Pull cancels go out in creation order, one at a time, not the overpriced side first
- **Where:** speeddesk_live.py:781-803. Each `_cancel` saves, waits a round trip, and saves again before the next.
- **Evidence:** `test_order_of_pull_cancels`: Up fair +1.06c gives cancel order ['up', 'down'], so the overpriced Down bid waits one round trip and two saves.
- **Fix:** cancel the side whose fair fell first, or send both cancels at once (the write budget allows 2).

L6 — If the wall clock steps back, the hold is extended by the size of the step
- **Where:** speeddesk_live_pull.py:98-99 clears the history but keeps last_trigger, active, range and open.
- **Evidence:** trigger at t=1000, clock steps back to 900: `held` is true from 900 to 1005, about 105 s with no bids. This is safe but stalls trading.
- **Fix:** on a clock step back, also clear last_trigger, active, range and open for that window, or sample with the monotonic clock.

L7 — Long lookbacks are silently shortened, and each sample rescans the history
- **Where:** speeddesk_live_pull.py:26 (HISTORY_LIMIT) and :106 (min and max over the whole history).
- **Evidence:** at about 200 samples/s:
  - lookback 5 s: 1,001 samples, 61 µs per observe, 1.2% of the event loop;
  - lookback 30 s (an allowed value): capped at 4,096 samples, which keeps only 20.5 s, at 267 µs per observe (5.3%).
- **Fix:** use running min/max queues, size the cap from the lookback, or limit PULL_LOOKBACK_S to 10.

L8 — Practice code writes real ladder state
- **Where:** speeddesk_live.py:889. `_twin_unpulled_bid` calls `book.can_buy`. A size-1 refusal for the day or lifetime stop calls `_note_stop`, which blocks ladder promotion for 24 h.
- **Effect:** the same as what the real `_send` would have done without the pull.
- **Fix:** call the side-effect-free `_buy_verdict` instead.

L9 — The hold does not survive a restart
- **Where:** speeddesk_live_pull.py:170-171 saves only `since` and the daily counts.
- **Effect:** after a restart right after a jump, the bot can re-bid as soon as the startup reconcile finishes. That is no more risk than today.
- **Fix:** save last_trigger for open windows, or treat every window as held for hold_s after startup.

Info:
- A single jump holds a window about 10 s, not 5 s (caveat 3). The replay's numbers (18% fewer fills, +28c a window) came from a 5 s hold, so don't judge the live A/B against them. Effect on activity: in a 10-minute random walk at 0.1c per 100 ms the pull made 48 creates against 107 without it; at 0.07c it made 66 against 56.
- Writes and reads are both counted per rolling second.

Files are in `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/pullreview/`:
- `test_pull_review.py`, run from the worktree with `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -s -p no:cacheprovider --rootdir=. -c pyproject.toml <path>`. These fail as designed:
  - the two H1 tests;
  - `test_ten_minutes_of_one_cent_oscillations` (15 reads/s against a limit of 10);
  - `test_order_of_pull_cancels`.

  The `choppy_ab`, `twin_control`, `aggressive`, `moderate` and `burst_detail` tests print the numbers above.
- `test_base_stale.py` reproduces H1 on 61ca112. Run it from the extracted copy in `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/base`.


---
## result 3 

Every blocker and major finding is fixed with a regression test. One major finding did not reproduce, and two items are deferred. Committed locally at **703d94208de1078d0719ad2b8a38e2ef6cd9e405** on `claude/kalshi-pull`, on top of 8a5b4fe. Not pushed or deployed.

- **Where:** worktree `/home/user/Claude/.claude/worktrees/wf_95208aa2-fc6-1`
- **Tests:** full suite 4,852 passed, 12 skipped (network). After the last doc edits, the Kalshi, page and doc-reading tests were re-run: 1,873 passed. Ruff is clean on the changed files and `mypy src/nightcrawler` is clean.
- **New tests:** `tests/test_speeddesk_live_pull.py` grew from 28 to 48 tests (20 new), plus 1 in `tests/test_speeddesk_kalshi_client.py`. All 20 new tests fail on 8a5b4fe. The reviewers' own scratch tests and probes failed on 8a5b4fe and pass now.

**Real money: fixed**
- **H1, failed cancel never retried.** The bot now remembers which cancels Kalshi accepted (200 or a definite 404). Only those are skipped. Any other requested cancel goes out again until accepted: after the retry gate, or as soon as a reconcile learns the order id. This also fixes the same bug on 61ca112, where a cancel was dropped once its reason passed.
- **M2, write bursts.** While the pull is on, a new bid waits if the last second already used 3 of the client's 5 writes. A new `KalshiClient.writes_last_second()` gives the count. The reviewers' burst went from 6 writes in 0.8 s to 4. In the reviewers' load runs with the count connected, peak writes were 4 a second or less in every pull-on run; at the lowest allowed settings it had been 14.
- **M3, re-read on every pull cancel.** A pull cancel no longer forces an immediate account re-read.
- **L5, cancel order.** The bid whose fair fell most is now cancelled first.
- A crash in the practice twin can no longer stop the real loop.

**A/B control: fixed**
- **M4, twin copying the pulled bot.** Real cancels and refusals no longer touch the twin's kept bids. In a choppy market the twin now matches a genuine pull-off run: 0 twin cancels, against 20 in 2 minutes before. Any bid that was resting when the fair moved now counts as pulled; in the 10-minute run that is 116 of 116 cancels, against 2 before.
- **R2-1, twin left bidless.** When the old rule reprices a kept twin bid, the twin bids again right away.
- **R2-6, send refusal wiping twin bids.** A send refused only because of the pull keeps the twin's copy. The pull is now the last check in the send guard.
- **R2-10.** Kept twin bids follow the take-available rule.
- **L8 / R2-8.** Twin bids are sized by the twin's own books and never touch the real risk book or the ladder.

**Panel: fixed**
- **R2-2:** P&L is also shown over windows either side traded, with a side that didn't trade counted as 0.
- **R2-3:** the panel counts the real lock buys (count, contracts, cost, per window).
- **R2-7:** the week-before baseline ends at a saved first go-live time, so a setting change no longer contaminates it.
- **R2-11:** if the comparison ever fails, the panel shows `error` and saves and cancels carry on.

**Merge safety and smaller fixes**
- **R2-5:** every fair value now comes from one helper, `KalshiLiveDesk._fair`. A test fails if a direct `fair_up` call comes back. When `claude/kalshi-fix-speed` merges, its four `settles_on_average` edits will conflict on purpose and belong in `_fair`.
- **L6:** a wall clock stepping back can no longer stretch a hold.
- **L7:** the lookback is tracked in O(1) per sample with no 4,096-sample cap.
- **L9:** holds survive a restart.

**Not reproduced:** R2-4, hold length against the replay. The replay code (`simple_trig` / `pull_simple`) also holds about 9 s after one jump, against about 10 s live. One real difference, now documented: the live rule also triggers on a 1c down-and-back inside 5 s, which the replay would miss. So live pulls at least whenever the replay did.

**Deferred**
- The twin still copies the real bot's decisions and never locks; making it an independent bot is a bigger change.
- Account reads still peak at 15 a second against the client's 10 when the fair flips 1c every 10.2 s, the same before and after. The cause is the existing rule that every new bid forces a full account re-read, not the cancels. The client queues the extra reads, so a pull cancel can wait up to about a second. Skipping a re-read when the read budget is short would fix it and belongs in speed part 2.
- `SPEEDDESK_KALSHI_PULL_HOLD_S` keeps the specified 0–60 range; the write-room rule bounds writes at 0.
- `pulls_today` still counts triggers even when no bid was resting (minor).

Docs updated: `docs/SPEEDDESK_SPEC.md` 9.3, `docs/WORKLOG.md` (new entry, newest first), and the new page fields for Codex in `docs/COORDINATION.md`. No Codex town files touched. Caps ($10 window / $20 open / $6 day / $10 lifetime), stops, locks and the 5-contract clip are unchanged.

**For the owner, in plain words:** The bid puller is safer and the comparison is fairer. The serious bug: if Kalshi failed to cancel a bid at the wrong moment, the bot never tried again. That bid could sit there up to 30 seconds and freeze all new trading. Now it keeps trying until Kalshi confirms. The bot also leaves room in its request limit so a cancel never waits in line behind a new order. The practice twin, which never pulls, was quietly copying the pulling bot in choppy markets, which would have made the pull look like it did nothing. It now behaves like the bot without the pull, so "real vs practice" on the panel really measures the pull. The panel also adds profit over every window either bot traded, plus how many lock buys the real bot made. Your limits are unchanged. Nothing is live until you say merge.
