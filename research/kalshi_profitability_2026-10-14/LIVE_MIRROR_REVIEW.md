# Exact review: live mirror serialization and reader identity

## Disposition and finding

**ACCEPTED: no unresolved blocking defect found in four-file bundle `0faa0c5d9a1fd07c4824f51b323ec5a4d068837d6d0fdf64fb4ea6cee7eccac2`.** This is acceptance of a focused partial mirror-cost correction plus future diagnostic producer identity. It is conditional on root's full required checks, exact release/restart verification and the frozen production capture finishing through 04:47 UTC before any release. It does not close EXEC-DELAY-001 or establish an all-source freshness pass.

One issue found in the first candidate was corrected: a signer/connect/handshake failure before `_session` started would log the prior connection's session number. Final source snapshots `session_before` at each attempt and logs `reader_session=None` unless that attempt actually advanced the instance's session counter. A new regression starts with prior session 7, forces connection entry failure, and verifies None, the unchanged fixed exception-class reason and absence of remote exception text. The first bundle `7edec11654fe695bb44b7d38e570f9607ce5b94eba6dcfb5527e1418097d9d50` is superseded.

## Exact reviewed source

Isolated checkout `/workspace/nightcrawler-mirror-speed`; base `10f7f9d88a9acd51aba041345d569cd9972c4b6c`. No source edits, commits, production calls, credentials, orders, account changes or deployments by this reviewer. Root owns integration, full checks and release. This report is written only under `/workspace/shared`.

Hash construction: sorted relative path + NUL + exact file bytes + NUL. Independently checked before and after final targeted tests; both checks match:

```text
d76e9dfa6a026f796f11503642a373a5a0f2799da8dabadf078c565591f82112  src/nightcrawler/speeddesk_kalshi_ws.py
5e69c33b05afc9531b42670389e94a5a0d0e0fadda0c9f0858aeec94b3337835  src/nightcrawler/speeddesk_live.py
3ebff61c7af746d91c975d4029f83d5c696cc0828cfdda0f8209802ccdfe04b6  tests/test_speeddesk_live_mirror.py
a0c3bf59a3f8623ae856563eac02478b6c89d157d078a9d7554212baff2acd5e  tests/test_speeddesk_ws_timing_integration.py
bundle: 0faa0c5d9a1fd07c4824f51b323ec5a4d068837d6d0fdf64fb4ea6cee7eccac2
```

## Mirror behavior

The runtime mirror edit is one expression plus a comment: within the same opened temporary UTF-8 file, replace `json.dump(full, stream, allow_nan=False, separators=(",", ":"))` with `stream.write(json.dumps(full, allow_nan=False, separators=(",", ":")))`. It retains the same already-constructed `full` value, JSON options, file-open context, atomic replacement, last_mirror update, checkpoint cadence and ledger-before-mirror order. It changes neither KV serialization nor receipt normalization/hash code. Practice's existing helper uses the same compact write approach.

The seven new actual-checkpoint tests exercise a real `KalshiLiveDesk` with a local test ledger and blocked account client. They verify one mirror write; exact legacy `json.dump` bytes for actual shallow state with active/archived windows, full merged archive parts and panel; Unicode including a lone surrogate, negative zero and extreme finite floats; and a valid receipt chain. The five injected failure cases cover NaN, infinity, unsupported display-only objects, partial write and atomic replacement failure. Each preserves the prior final display and last_mirror timestamp while retaining already-committed ledger/archive state. The restart test corrupts the display and demonstrates recovery from the authoritative ledger, not that display.

The final source does not move financial durability behind mirror success. A mirror encoding or I/O failure may still affect the controller through its preexisting exception handling; this patch does not suppress it. Eager encoding can leave an empty temporary file where old chunked encoding left a partial prefix, but no final target is replaced on failure. That temporary-prefix difference is not a financial recovery contract.

Accepted scope is exact normal-model-state output and retained atomic failure boundaries, **not universal equivalence for every arbitrary Python object/call stack**. The profiling worker's malformed depth-1100 nested-list example fails under old Python `json.dump` but succeeds under C-backed `json.dumps`. This known distinction is preserved in evidence and was explicitly considered. Actual tested model mirror depth is below 32; no broad recursive guard is added merely to reproduce an incidental old encoder depth limit. Financial restore reads ledger STATE_KEY and refuses an existing mirror beside a missing ledger. No deliberate financial safeguard is removed.

## Producer identity and recovery paths

`WeatherWS` inherits the base reader on another execution path. New timing JSON contains a fixed kind (`speeddesk` for the actual base class; `derived_market_reader` for subclasses), module-wide monotonic instance counter and process PID. The existing warning prefix and fixed reason remain first; the same identity and active session are appended. No raw class name, ticker, credential, arbitrary server string or private payload is added. The native framing, source guard, callbacks, invalidation, reconnect/backoff, complete-message yield and observer retention cap remain unchanged.

Constructing the actual WeatherWS subclass in the new integration test proves that two readers reporting local session 1 have distinct instance identities and base/derived categories. The pre-connection error test proves the previous session cannot be falsely reused. Identity is qualified by external deployment and **process incarnation**, not globally unique across restarted/reused PIDs, replicas or arbitrary forked object reuse. Do not use `(process, instance, session)` without that outer scope. The current source path constructs the relevant readers in their running process; no new subprocess lifecycle is introduced.

Historical timing/warning rows without identity remain producer-unknown unless other independent wiring evidence proves their source. Missing local_work does not identify WeatherWS, and a bare old session counter cannot join two historical rows across readers. The new label does not retroactively clear the earlier mixed-logger attribution limit.

## Independent tests

Final exact bundle, Python3.12.14 / websockets15.0.1:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /workspace/shared/nightcrawler-venv/bin/python -m pytest -q tests/test_speeddesk_live_mirror.py tests/test_speeddesk_live_saves.py tests/test_speeddesk_live_crash.py tests/test_speeddesk_ws_timing_integration.py tests/test_speeddesk_kalshi_ws.py tests/test_weatherwatch_markets.py
```

**123 passed in 7.32 seconds, exit 0.** This covers actual mirror integration, existing save/crash behavior, eight timing integration tests, existing Kalshi WS behavior and Weather market tests. The earlier candidate passed 122 targeted tests, but that result is not substituted for the final bundle. Root's earlier full-suite attempt was interrupted/exit137 after an identity fix; it is not a pass. At this review root was starting the final full tests. Full tests/mypy/Ruff/secret scan and production verification are not certified by this targeted review.

## Profile evidence checked and limits

Read the original mirror profile scripts and JSON result files, without rerunning their whole experiment:

```text
a35d33ce91f07a25d5ca161834598335bac0fe5c3a386f2973693db26bb8c3ff  kv-profile-artifacts/SUMMARY.json
0bc3735b7676bb76ebd4a4adae21858b05cb854eda396e716c11a99f34961c96  kv-profile-artifacts/mirror-results.json
184d0258248756835f012a94179347fcab453005984e15059d9272996d4e9083  kv-profile-artifacts/mirror-extra-results.json
```

The 1,771,743-byte synthetic enlarged mirror's exact output bytes match. Write calls decrease from 346744 to one. The main profile records median wall 87.954→17.465 ms; the separate extra run records 86.828→14.609 ms. The benchmark uses `time.process_time()` for CPU, not WorkTrace's thread CPU, and runs old then new in fixed blocks. These are offline mechanism/rough-cost observations, not a controlled production causal speedup or exact savings prediction.

The extra run measures traced peak allocation **87,604→3,549,061 bytes**, reflecting the whole encoded string. This is a real memory tradeoff. The synthetic enlarged state is not actual production archive content or a proven maximum size; no production memory ceiling is established here. Do not present the improvement without its additional allocation or claim the candidate eliminates all mirror costs: full-dictionary construction, `panel()`, OS writes and replacement remain.

The prior identified main-reader incident at 04:13:07 has 2731.530 ms measured post-protocol residence with a fully contained live_mirror span of 280.869 ms (nested in a 377.893 ms checkpoint). That supports the mirror as a concrete partial contributor, while its exact encoder fraction requires profile interpretation and other waiting time remains. This patch does not attribute every old warning, resolve metadata overflow, or prove complete-window source freshness.

Finish the frozen capture unchanged. After any authorized post-tail release, preserve exact deployment and financial restart checks, then collect repeated full windows with explicit producer identity, sample/overflow limits and original work/receipt intervals. All risk limits, stop/reset/resume state, fees/losses, reservations, uncertain orders and owner positions retain their existing authority. Strategy comparison remains unstarted until EXEC-DELAY-001's required evidence is complete.
