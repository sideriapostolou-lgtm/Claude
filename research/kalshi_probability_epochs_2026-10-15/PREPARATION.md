# Separate probability-history continuation — checked source and limitations

Prepared October15,2026, Pacific afternoon, after the frozen PR65 capture closed.
This repair resumes optional forward probability measurement after a source
version change. It never changes which real trades the bot chooses.

## Exact implementation

Root legacy key is the exact validated original dictionary, frozen before strict
restore annotates timestamps/errors. A bounded authoritative epoch envelope plus
separate marker stores immutable archived histories and one current-source state.
Every actual new source starts zero calibration; same-source restarts retain strict
restart exclusions. A→B→A creates three epochs, not resumed A training. Four archives
plus one active, per-state262144bytes/joint2MiB including duplicatedlegacy; no eviction.
Canonical hashes show consistency, not authenticity or original-file byte export.

Fatal original errors/rejected restore flags cannot be masked by mismatch then
reenabled. Loaded missing/null/corrupt histories and exhausted retention disable
this optional observer. Corruption retains validated legacy/contiguous archive
prefix; unvalidated remainder is unrecovered. Missing marker OR envelope fails
closed; both removed cannot be distinguished from genuine legacy import. A binary
downgrade to pre-host code is unsupported and can drop the envelope; not planned.

Runtime callbacks still reach only the current strict learner. Disposable strict
validation uses a silent event-only subclass so it cannot emit invented unknown
receipts. Actual restore/events remain unchanged. One bounded startup lineage log
and separate current/archived page-payload summaries permit verification without
reading secrets or claiming full volume export/browser-render testing.

## Source/version/check record

- Exactv4patch **3f3626033fb618a08d79270c2dd6e4165ecbc49888849bae5d99800c72e7f957**,
  54,430bytes; seven source/test paths in [manifest](epochs-v4.json).
- Four production file bytes are identical to independently acceptedv3; v4 only
  scopes the startup-log test after its fixture startup and asserts timestamp9000.
- Current source fingerprint **23e2ca80d3c04415256bf3fc237ba017d56733a59219d718e86c554eaa1f1d25**,
  including the new host. V1fingerprintb6112b7e... unchanged. Existing disabled
  oldhistorye7989706... and runtime19387e3a... are distinct; no compatibility alias.
  [Dependency preflight](fingerprint-preflight-v3.json).
- Three existing source files plus one new host;177othertrackedsrcfiles/all4build
  files byte-equal. Every strict learner method AST unchanged. No V1, livecontroller,
  model, strategy/fees, financialledger, risk, Polymarket or parentFIFO changes.
  [Root scope](ROOT_SCOPE_CHECK.json).
- Current focused **224passed** (including existing OnlineLearning coverage),
  targeted INFO-level regression **1passed**, Ruff on all7Pythonpaths passes.
  Source unchanged after implementation's mypy **130files clean**; full suite also
  includes the required source typecheck. Verbatim commands/outputs retained.
- Independent exactv4 review **60e2868ade2a7a6365669786b45d6f9dadf17372868eead84be3079193c82c84**;
  independent INFO-level188passed and adversarial strict-restore/history/fault
  isolation plus source-boundary checks accepted. [Review](epoch_v4_frozen_review.json).
- Fresh fullv4 **5,992passed/14existing skips**, captured0, finished **2:26:05PM PDT**;
  304.65s wrapper/303.01s pytest, all7source/test hashes unchanged.
  [Verbatim full output](FULL_PYTEST.stdout.txt), [receipt](FULL_PYTEST_RECEIPT.json).

## Rejected drafts and retained failures

Initial archive loss/orphan observer cases and missing-active/marker prefix-loss
reproductions remain. Frozenv2validation emitted phantom unknown receipts: exact
regression fails oldhost, v3silentprobe passes. Its interrupted/superseded full run
captured−9 with changed hashes is not a pass; precise termination amid workspace
reconnection was not certified. Original partial outputs and reason retained.

Fullv3completed **5,991passed/1failed/14existing skips**, captured1, all7hashesstable.
An INFO-level single-test reproduction confirms the startup assertion accidentally
included separate fixture-at900 and restored-at9000 records. Test-only clear and
explicit target timestamp now pass; the failedfullrun remains verbatim, not hidden
or represented as a production double-log bug. Freshv4fullchecks are required.

## Resource screen and release gate

Pre-fixed local gates passed on exact production bytes: added steadyframe mean
0.01421ms; populated checkpoint+JSONp9525.56ms/max28.40ms; startuprestorep95/max
124.65ms reported separately. Joint optional436,561bytes, individualstates<=78,195,
fullarena panel18,815bytes. Dense structural-count/slug fixtures are not a proof
of every possible float encoding or production scheduler/fsync/latency behavior.
Existing save ordering, durability and cadence unchanged. All samples/outliers and
supersededv2 measurements retained alongside [independent resource output](epoch_resource_v3_resume.json).

PR65release/capture is independently verified: the predeclared2:00–2:15PM window
made16c locked/zero direction/zero fees, while mainreader gaps remain. That profit
was made with V2disabled and is not attributed to learning or this continuation.
No source changed during its fixed2:17PM tail. [PR65evidence](../kalshi_rest_recovery_2026-10-15/RELEASE.md).

Freshfullgreen verified; publish reviewed source, merge during safe minutes under
standing owner approval, and verify exact Railway SUCCESS, normal Polymarket LIVE
startup, original financial/cap/used-control retention plus archived5scores versus
freshcurrent0 in original lineage logs. No variables, limits, stop/resume/day
budgets, trading mode or manual orders. Freeze the earliest full futurewindow
>=60seconds after ready verification, declare beforestart, tail=end+120s. Require
original current forecast/input qualification/official outcome/score, retaining
all unknowns. One score proves plumbing, not accuracy/profit or larger stakes.

Keep source frozen afterward for prospective accumulation. Broader input-delay,
profitable strategy and any missing volume/coverage verification remain on their
existing queues. Other business/takeover deferred; TJR/MNQ last.
