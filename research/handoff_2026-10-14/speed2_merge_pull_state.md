# speed2_merge_pull_state (workflow wf_62b45ee6-ffb)



---
## result 0 

The removed lines are exactly the ones the pull replaces (the four direct `fair_up` calls now routed through `_fair`, the direct twin calls now behind `_practice`, the base's stale-bid/cancel bookkeeping superseded by the pull's, the rest-only send-guard check that gained the pull block, and the `pending`/`units` lines that gained the owed-twin handling). No speed-branch logic was dropped unintentionally.

Only the full-suite result remains; the commit follows it (fill the two WORKLOG count placeholders, stage, commit). Waiting on the monitor's single event.
