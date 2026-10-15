# Codex operating handoff — October 15, 2026

This checklist supplements the [original Claude handoff](HANDOFF_CLAUDE_TO_CODEX_2026-10-14.md),
[current coordination queue](COORDINATION.md), [continuity index](CONTINUITY_INDEX.md) and newest
[worklog](WORKLOG.md). It preserves their original evidence; it does not copy accounts, keys or volumes.
Latest instruction for the current daily inspection: **production read-only**. Older restart/cap decisions
must never be replayed. The existing real Kalshi loss stop stays latched.

## Verified from this ChatGPT session

| Item | Evidence / boundary |
| --- | --- |
| Source responsibility | Codex accepted all lanes, including Kalshi, in the October 14 handoff. The older Claude/Codex lane table maps files; it does not restore exclusive ownership. Coordinate overlapping writes. |
| Repository access | Connected GitHub reads succeeded at `91250c6598f4b866d7601ac0ead3e66ba55996cd`; normal non-force docs pushes work. Keep the existing deploy branch `claude/nightcrawler-memecoin-bot-Gwnb1S` and history. |
| Railway access | Connected Railway can read bounded deployment, health and log records. No credential values were read/listed or copied. This is actual read access, not proof of every administrative capability. |
| Bot | Service `f84d3b52-002f-44cb-931e-bc9e3e097e97`, deployment `458e8e54-804c-46f1-aaf4-0abab4461571`, running commit `933a43d2d7cb6d6dd27b4728d50c78ce0f488ed5`, SUCCESS, `us-east4-eqdc4a`. At the October 15 8:22 AM PDT status, Kalshi is paper because its total stop latched; no open orders/positions/risk. |
| Recorder | Separate service `736b1c8a-8311-4ee0-9043-d05f508cd821`, deployment `8453f919-b891-4aa7-8478-6fcf6b9c24ee`, running commit `a0782b743a31369fe25ddf6d2eea96df8511cd8d`. SUCCESS and online. Keep its separate branch and service. |
| State | The dated handoff locates bot and recorder data on separate `/data` volumes. Fresh service health confirms attached volumes, not their contents/backups. Do not reconstruct balances, fills, consumed controls or loss history from a checkout. |
| Research | Original Claude archive, loss audits, frozen comparisons and complete saved TJR Page/code/test snapshots remain in the same Git history. Follow the continuity index rather than rebuilding from a summary. |

The recorder's guide is absent from the bot deploy tree but is now located and read through connected GitHub
on its actual branch: [recorder guide at `4c00ba6d`](https://github.com/sideriapostolou-lgtm/Claude/blob/4c00ba6d8094ea8a96b17a024cf1818d78288d28/docs/KALSHI_RECORDER.md),
blob `562755f2fb0d39c7627b8627fd86bf6fc7caaf45`. That docs head is SKIPPED; running recorder source is
`a0782b74`. Its old “proposal / not done” setup prose is historical, superseded by deployment evidence.
Do not merge the recorder's whole branch into the live bot or duplicate the bot service merely to transfer ownership.

## Existing schedules checked privately, without changing them

The canonical automation lookup at **8:25 AM PDT October 15** found these three relevant tasks enabled,
in `America/Los_Angeles`:

| Task | Stored schedule | Observed last invocation |
| --- | --- | --- |
| Kalshi daily status | Daily 8:20 AM | October 15 8:21:29 AM PDT |
| Kalshi recorder checkpoint | October 15 3:45 PM | None yet |
| TJR MNQ follow-up | Hourly condition check; suppress unchanged reports | October 15 6:48:16 AM PDT |

The service returns `next_run_time=null` for all three. Enabled schedules and past invocation are observed;
future successful execution/delivery is not guaranteed by this lookup. No duplicate timer was created or
existing timer changed. The TJR task stays enabled while its historical/paper requirements are unfinished.
Unrelated account automations are outside this handoff and were left unchanged.

## Open work to carry forward

1. **EXEC-DELAY-001:** production gaps/local delays remain unresolved. Offline fakes reproduce an old
   pre-start simulator warning contaminating a later learner slot, delayed timestamp-less gap delivery,
   and quiet-maker eligibility being treated as a gap. These are possible mechanisms, not attribution
   of all five production exclusions. A narrow child chronology candidate is local only; the latest
   worklog records its actual review/test status. Keep genuine gap checks and all prior unknowns.
2. **KALSHI-ONLINE-001:** deployed observe-only calibration, zero scored forecasts as of the saved **8:31 AM**
   evidence (startup1 +pregap6 exclusions). No improvement/profit established. Need genuine prospective forecasts and official same-terms
   labels, score-before-update and retained exclusions. Algorithm fingerprint does not hash the entire
   upstream/arena input pipeline; preserve exact source/release IDs as well.
3. **Risk:** total real Kalshi stop is latched. No restart, reset, cap increase or new real desk follows
   from takeover wording. Preserve current caps, ladder, reservations and consumed control history.
4. **Recorder:** feasibility checkpoint due 3:45 PM today; review storage before October 20. Latest saved-hour
   metadata is available, but raw payload hashes, per-venue spot ticks, queue/depth/fill feasibility and
   actual operating cost are not verified. Do not open sealed TEST. Railway December 1 settings migration
   remains a dated handoff obligation requiring a separate verified plan and owner-specific authority.
5. **TJR-MNQ-001:** saved implementation and reproduced synthetic checks retained. Authentic MNQZ2025
   development bars and actual costs still missing; historical trades 0 / P&L null, holdout unopened,
   paper not started, live disabled. Do not duplicate unchanged research or pretend the queue is complete.
6. **Other research:** original/inverse comparison unstarted; frozen ledger diagnostic remains separate
   and unreleased. Weather, skip-watcher and Lucas research have historical source/artifacts, but current
   running status or completed profitability studies were not established by this check. Inventory before revival.
7. **Developer tooling:** explicit model delegation works in this chat. Standalone CLI role launch last
   failed at sign-in refresh; normal host reauthentication remains unverified. A different model/config
   does not transfer omitted chats or permissions. Existing dirty worktrees are preserved; no reset/cleanup.

## Not yet a verified transfer

- Unsaved Claude chats, local-only files outside available checkouts, private session state and provider
  permissions are not exported by a Git handoff. This audit cannot claim every historical detail is present.
- Runtime volume contents, backups/recovery exports and full native venue/cash/stop-anchor ledgers were
  not read or migrated. Keep production state in place and obtain bounded read-only evidence when needed.
- Authenticated town/page rendering and every background observer were not tested in this status check.
  A healthy bot process is not proof that every app connection or research stream is complete.

The integration owner reads current records before each task, gives one worker each file set, reviews exact
patches, preserves failed attempts/losses and records unfinished items. Under the current read-only instruction,
local fixes remain local; publishing this checklist and status evidence does not restart either service.
