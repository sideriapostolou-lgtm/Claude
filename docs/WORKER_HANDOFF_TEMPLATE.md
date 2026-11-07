# Worker handoff template

Use this inside the task's existing research/change record or coordination entry; do not create a
second competing queue. Fill only what is known and label missing fields. Never include credentials.
For a small task, concise sentences covering these fields are enough.

```text
Task ID / objective:
Recorded at (Pacific, plus source UTC where relevant):
Requested model / reasoning effort / role; launch or fallback evidence:
Integration owner; worker-owned paths; other active writers:
Repository / branch / worktree / immutable base SHA:
Current HEAD; dirty/untracked work to preserve:
Owner authorization source and scope; explicitly excluded actions:
Instructions read: AGENTS, COORDINATION, newest relevant WORKLOG, task spec:
Source-of-truth inputs and exact versions/hashes/paths:
Data partition and coverage; holdout access status; missing inputs:
Decisions made, rationale and alternatives still open:
Acceptance criteria:
Patch commit, or base plus complete patch hash including new files:
Tests/checks actually run and results; skipped checks and reasons:
Independent review scope, exact revision, findings and disposition:
Production/account evidence timestamp and scope, if authorized and obtained:
Release state: local / pushed / merged / deployed / verified (separate):
Remaining work and blockers; concrete next step and owner:
Available usage/cost/time receipts, or not exposed:
```

The receiving worker must inspect the linked originals and relevant changed code. A summary of a Page
does not replace its code blocks; synthetic checks do not replace market results. Verify every price,
fee, inventory or P&L claim against the appropriate evidence before using it in a decision.

For money-sensitive changes, preserve real/practice/owner separation, reservations and uncertain-order
state, recorded fees/losses, stops and whether the current resume authorization was already consumed.
Never put the resume token itself in the packet. Do not infer permission from the prior worker's role.

For a new session, re-read current remote instructions and check for concurrent edits. If a referenced
file, Page, dataset or tool is inaccessible, report the exact missing input; do not claim to have read
it. Leave unfinished queue items unfinished. The integration owner records durable final results and
updates the existing WORKLOG/queue before ending the task.
