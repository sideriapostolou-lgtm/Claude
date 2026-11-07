# Storage persistence repair implementation handoff

Worker: delegated implementer `/root/storage_source_fix`. Repository `/workspace/nightcrawler-daily`.
Task authorization: owner asks to fix why the bot is off and unprofitable; root assigned only bounded source repair for storage persistence failures. No strategy, financial setting, variables, deployment, real orders or raw history deletion authorized to this worker.

Base: `f0ce4f8` on `codex/storage-recovery-20261018`; deployed application source remains PR76 `f370c3c2` pending root verification.

Frozen four-file patch SHA256: `d3cdde2f73aff37f0be3b5c883359d714b1a3481c007e52b3684bde08be8643e`.
Hash recipe: concatenate `git diff -- src/nightcrawler/polydesk.py src/nightcrawler/speeddesk_live.py tests/test_speeddesk_live_mirror.py` bytes with raw `tests/test_storage_persistence_failures.py` bytes, then SHA256.

## Changes

- `src/nightcrawler/speeddesk_live.py`: catch only optional JSON display-copy `OSError` after authoritative financial ledger transaction commits. Preserve prior display bytes/source timestamp, publish native panel fault metadata, log sanitized type/errno once per attempt, retry at most once per 60 wall-clock seconds, including shutdown. Successful candidate display projects healthy/current-success metadata, while native memory clears fault only after atomic replace succeeds. Remove only this attempt's optional temporary after successful truncating open; failed-open pre-existing temporary remains untouched; cleanup errors stay bounded and do not mask the original failure. Ledger, receipt transaction and pre-send journal failures remain outside the optional catch. No financial gate/admission change.
- `src/nightcrawler/polydesk.py`: authoritative JSON save failure closes real-order client, marks process-local fault/status, requests thread stop, and re-raises. The loop does not recursively attempt another fault save; direct subsequent poll/save rejects. Existing loss, halt, pending-order and consumed-control fields are preserved. No runtime automatic resume, state schema, broad receipt policy or fsync policy change. One existing percent-format lint finding changed to equivalent `:g` formatting.
- `tests/test_speeddesk_live_mirror.py`: optional I/O failure expectations, partial temporary cleanup, and ledger-based restart preservation of stop latches/consumed resume fingerprints.
- `tests/test_storage_persistence_failures.py`: bounded retry/recovery and correct recovered telemetry; mandatory ledger failure propagation; initial display failure unknown success; owned vs unowned temporary cleanup; cleanup failure; direct and recovery-save Polydesk failures; actual partial Path.write_text and atomic replace ENOSPC preserving target/history.

## Verification

Final targeted command: `.venv/bin/python -m pytest -q tests/test_storage_persistence_failures.py tests/test_speeddesk_live_mirror.py tests/test_speeddesk_live_runtime.py tests/test_polydesk_live.py tests/test_polydesk_safety.py tests/test_polydesk_owner.py` — **101 passed in 1.73s**. After final partial-temp assertion, the two fault/mirror files reran: **16 passed in 0.34s**.

Final `.venv/bin/python -m mypy src/nightcrawler`: **Success, no issues in 135 source files**. Changed-four-file Ruff: **all checks passed**. `git diff --check`: clean. Root owns full-suite/release checks; worker did not launch full suite.

Baseline reproduction: extracted original `_loop` and `_save` from `git show f0ce4f8:src/nightcrawler/polydesk.py`, bound to an offline synthetic desk and injected a recovery-save ENOSPC. Original `_loop` let errno28 escape with no persistence latch. Final targeted tests show explicit bounded halt instead. No live or network account access.

Independent reviewer `/root/storage_risk_review` confirmed the frozen hash, no blocking bounded source defect, and 135 selected offline tests passed in 1.33s. Root retains reviewer receipt.

## Initial failures and corrections

- System Python initially lacked package import path and requests; authorized shared `.venv` was created, editable dev dependencies and Ruff installed.
- Calling `.venv/bin/pytest` directly produced three existing namespace `tests` import collection errors. Using `.venv/bin/python -m pytest` included checkout root and passed.
- Initial Ruff exposed an existing percent-format finding in the now-touched Polydesk file plus two new style findings; corrected narrowly.
- Additional restart test initially assigned synthetic realized loss without matching settlement records; existing integrity validation correctly rejected that invalid fixture. Fixture corrected to valid accounting with preserved total/day latches and consumed fingerprint. No product relaxation.
- A scratch baseline harness patched the original namespace incorrectly and entered an error loop; interrupted immediately, corrected namespace injection, bounded it to one pass, then reproduced original errno28 escape. Only temporary local synthetic state was involved; no repository/source changes followed.

## Limits and next step

This patch does not free or inventory the production full volume, prove current exposure, reconcile missing Polydesk history, or establish profitability. Polydesk latch is process-local: it cannot persist itself to a failed volume and does not guarantee restart safety. Root must obtain real disk/state integrity/headroom and current authenticated venue reconciliation or independently approved containment before deployment. Existing Kalshi reduction-only policy, financial limits, stops, losses and consumed controls remain unchanged. No data reset, history deletion, cleanup of unknown files, variables, deployment, or trades performed.

All four source/test files frozen at the hash above; no further worker edits planned.
