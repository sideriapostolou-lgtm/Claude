# Storage recovery preparation, October 19

This package prepares the first **read-only metadata inspection**. It has not
been executed on production and does not recover the bot or prove profitable
trading. Existing losses, entry containment, financial limits and unresolved
release checks remain unchanged.

## Access and dated platform evidence

Railway login and public-key registration succeeded in the existing cloud task.
The owner currently uses a phone. SSH to `ssh.railway.com:22` is unreachable from
this workspace; the configured TCP proxy also refused connection and its TCP
destination grants are empty. No remote command ran. Supported SFTP volume-file
access uses the same destination. [Phone/web setup handoff](../../docs/RECOVERY_ACCESS.md).

[PLATFORM.json](PLATFORM.json) preserves the read-only request/response:

- At October 19, approximately **1:39 PM PDT**, the existing bot deployment
  `43f14443-2d07-4985-b879-3a2515fb8d2c` is online, one of one replicas.
- Exact-deployment native-status query for **12:10–1:39 PM PDT** returns zero
  rows, below its 20-row limit. This does not establish no venue activity,
  break-even performance or current account state.
- The previous successful volume inventory, **12:47–12:48 PM PDT**, reported
  4997.89824 of 5000 MB used. Its underlying metric timestamp is absent. It is
  not a per-file inspection or actual filesystem free-space measurement.

No full daily report, ledger reconciliation or fresh financial snapshot is
claimed from these reads. The last financial snapshot remains dated October 17.

## Metadata helper

`inventory_metadata.py` is standalone standard-library Python for Linux. Its
command-line entrypoint is fixed to `/data`; alternate imported roots exist for
synthetic fixtures. It does not import the application or initialize any trading
or database client. Only directory descriptors and the bounded procfs mount
metadata are opened; regular-file contents are not opened.

Once supported access exists, send this standalone source to the container's
existing Python interpreter over standard input and collect its JSON output
privately. No package installation, code upload to the full volume or service
restart is needed for that inspection. This execution has not occurred yet.

The helper checks directory identity, rejects symlinks, anchors traversal to
directory descriptors and excludes boundaries listed in its mount snapshot and
different-device entries. The command-line path requires `/data` to appear as
the exact matching root mount before traversing entries. Its defaults bound
entries to 4,000, opened directories to 256, depth to 8, elapsed budget to five
seconds, mount metadata to 1 MiB, errors to 20 and result rows to 256. The largest
file sample contains at most 20 observed unique regular files.

Output includes UTC observation times, root and mount identity metadata,
filesystem free/available bytes and inodes, bounded observed file/group sizes,
counts, skipped boundaries, errors and explicit partial/stop reasons. Known
financial paths get **metadata only if encountered**; an absent sample means
not observed, not a missing file. Device/inode deduplication prevents counting
hardlink aliases twice; a file linked across groups belongs to the first group
observed. Metadata and names may still be private: preserve any production output
privately and sanitize it before publication.

Limits remain material:

- The time limit is cooperative; a blocked kernel call can overrun it.
- Mount metadata is a snapshot, not a namespace lock. Concurrent mount changes
  are not prevented, and the helper cannot prove a Railway volume ID.
- Files can change during inspection. Observed sums are not an atomic snapshot,
  a bound on current usage, or a list of files safe to delete.
- No SQLite integrity, WAL coherence, financial state, consumed-control history,
  current account exposure or restart safety is checked by this helper.

## Validation and next step

Final combined checks: **62 passed** (46 implementation cases and 16 independent
cases), reproduced by root in 0.17 seconds; changed-file Ruff passes. All fixtures
are synthetic and temporary. Source SHA-256 is
`e02812647346b2532a9cc0b8eb0287d9f08fdf7d2fbd6c7459bd72e388c4abad`.
[Implementation receipt](INVENTORY_VALIDATION.json),
[independent review](INDEPENDENT_REVIEW.json) and
[root verification](ROOT_VALIDATION.json) preserve the checks and limitations.

Early failures are retained: missing pytest in the default interpreter, an
incorrect bytearray-to-text conversion, lint findings, stale independent fixture
device IDs, and an independently reproduced stacked-mount ambiguity. The final
helper refuses an ambiguous longest containing mount before traversal. Observed
size sums no longer claim to be bounds on a changing filesystem. No application
performance gate is waived and no production result is inferred from these tests.

Next, obtain supported SSH connectivity and run the first metadata inspection
read-only. Preserve coherent DB/WAL/state/history and reconcile paginated venue
records before selecting a measured capacity recovery. Do not delete files,
checkpoint production SQLite, resize storage, restart a desk or clear old losses
as an evidence-gathering shortcut. Source release and recovery remain OPEN.
