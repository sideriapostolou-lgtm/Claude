# Kalshi recovered-feed correction — deployment and bounded verification

Evidence completed October 15, 2026, at 2:23 PM Pacific. The narrow correction,
exact deployment, restart retention and declared full-window/tail extraction are
verified. The obsolete-failure branch was not observed in production. Broader
execution gaps and profitable strategy evidence remain open.

The original feed could clear both already-recovered WebSocket books when an
older REST call failed. The correction refuses that obsolete invalidation only
when actual current-ticker books are fresh; tape also needs a fresh real print.
Expired/disconnected/retired or otherwise invalid inputs remain blocked. Cached
aggregate health flags cannot authorize recovery. It does not change buy rules,
fees, amounts or the real controller, and it is not proven to explain past losses.

## Checked and deployed

- PR65: https://github.com/sideriapostolou-lgtm/Claude/pull/65
- Reviewed candidate781b3fd4a54bfc06cf737c4f6dca1d31eb534dc7; merge/source
  b7b7192e5d463e57417d05acb3b168744941b9fc; tree1330db5b8696c595934627583d095c7dbd9685e5.
  Three source/test blobs were remotely read back exactly, candidate and merge.
- Merge request **1:47:19PM PDT**, GitHub merged_at **1:47:21PM** and response
  clock **1:47:22PM**, safe minutes, standing owner approval. Earlier1:47:19
  shorthand was the request clock, not the exact completion timestamp. Railway
  1c01ffe7-e231-40c6-a026-ac63fec01227 SUCCESS **1:49:04.606PM**.
  Normal Polymarket LIVE startup **1:49:01.558PM**, ten contracts/order.
- Full5,939passed/14existing skips, captured exit0; mypy129sourcefiles/Ruff3
  changedPythonfiles pass. Exact correctedpatchd956bf9e5b98fec667a47beb24332af9448131e1c54e94ac9337690bd0775b0a.
  Independent169focused+11source scenarios/BTC+WeatherWS clock checks accepted;
  original code fails16selected recovery/retirement regressions. First rejected
  draft's moving-clock flaw and initial default-Python environment failure remain.
  [Preparation and preserved check originals](PREPARATION.md).
- Two existing feed modules and one new fake test only;178othertrackedsrcfiles
  plus buildfiles byte-equal. No live/controller/model/risk/V1/source protocol
  changes, caps, stop/resume/day budgets, variables, manual orders or Polymarket
  source edits. Existing real bots restarted by the approved source merge.
- At **1:59:06PM**, bot and unchanged recorder are online1/1 with no platform
  issues. The old zero-change staged environment patch was left untouched.
  Bounded startup traceback query returned0; this is not continuous-error proof.

## Restart retention and integration finding

Original **1:45:51.062PM before** and **1:54:18.514PM after** agree exactly on67
of68selected fields. The other is ladder.start_pnl_usd:−3.7461000000000038 versus
−3.7461, a floating-point representation difference. Startup resume/integrity/day
reset values are all ignored as already used; no fresh loss allowance was made.
The bounded intervening service query contains16status/nested-copy matches and
zero anchored original orders/fills/cancels/settlements. Neither that query nor
selected panel fields certify a complete native cash/control ledger export.

Both originals report **$30.5696cash**, **−$19.2018cumulative settled tradingP&L**,
zero risk/reservation/orders/positions, caps **$10/window,$20open,$6day,$10total,
clip5/rung0**. Historical open_cost$0.97 remains displayed despite zero reported
positions; do not relabel it certified exposure or silently drop it. The initial
startup stale-account status is excluded from readiness. as_of is panel time;
actual last-account-read age is unpublished. Real and practice remain separate.

The dependency change also changed V2 fingerprint e7989706... to19387e3a... .
Original **1:50:10.317PM** correctly reports source_or_protocol_mismatch and
**enabled=false**. Old5forecasts/5scores/1unknown remain intact, baselineBrier
0.18726215950008984/shadow0.1796062816651917. That is not ongoing collection,
profitability or a meaningful five-sample accuracy claim. V1 remains enabled with
its earlier gap history. A separately scoped/tested versioned continuation is
pending; do not alias old hashes or claim this integration problem is fixed yet.

## Fixed prospective window

[Declaration](CAPTURE_DECLARATION.md) published in docs-only08208179 at
**1:55:40PM PDT**, before opening. Its minute-rounded1:56entry headings are not
original evidence timestamps. Root verified ready using original1:54:18PM status;
actual verification clock is in the declaration. Exact initialized market metadata
was read publicly before start; settlement uses CF Benchmarks60secondBRTI averages,
YES on equality. No Coinbase settlement-source substitution.

Target **KXBTC15M-26OCT151715-15**, **2:00–2:15PM**, fixed tail **2:17PM**.
Source is frozen through that tail. Original2:00:22PM already reports existing
bot trading live, $30.0096cash/$0.56risk, one order/one position. Its cumulative
P&L−$19.1718 includes a prior-window change and is not target-window profit.

The fixed capture is closed, with complete parseable same-bound root queries at
**2:18:45–46PM** (real transactions) and **2:21:32–33PM** (siblings). All six
queries are below500rows and error-free. The earlier worker's initial transfer
truncated at the PTY limit and its retry hung; those failed artifacts are preserved
and not used as successful native evidence. Corrected root wrappers, query clocks,
raw hashes and original-event projections are linked in [manifest](TARGET_CAPTURE_MANIFEST.json).
No bounds were extended or winner selected afterward.

Three distinct target fillIDs join two accepted real orders: Up0.1+0.9 at56c,
Down1 at28c, all maker/zero fees. Exact decimal cost **$0.84**, matched payout
**$1**, **+$0.16 locked/zero directional**, official venue settled_time original
**2:15:11.418PM**, independently agrees with the finalized YES public market.
Pairedcredit$1/netpayout0 reflects the venue's paired credit, not another$1 to add.
Prior partial **+$0.03** settles2:00:06 and next-window Down1@48c fills2:16:53;
both are excluded from target P&L. Target practice twin has zero shares/zero P&L,
not a substitute for real. This one target's worst-window figure is trivially16c
and is not a historical drawdown estimate. [Originals](TARGET_REAL_ORIGINALS.json),
[math](TARGET_MATH.json), independent financial/coverage receipts alongside.

There are20durable target intents,17explicit accepted orders and two orders with
fills: **2/17=11.76%** on that explicitly acknowledged-order basis. Three failed
acknowledgement timings remain unknown, not zero latency; two have original400
invalid_order rejections, whose precise cause is not established. A same-bound
supplement retains them. Successful decision-to-ack17samples median102.20ms /
p95nearest-rank1346.56ms;20Bitcoin-receipt-to-decision samples median354.96ms /
p951184.20ms. Finite successful samples do not cover failed acknowledgements or
prove his speed. Fractional0.1/0.9 are two fill records on one order, not two full
contracts or two independent wins.

Feed originals108rows include73timing,34WSwarnings and one unassigned-market
tradegap ValueError/invalidated=True at2:08:35. No invalidated=False or bookfailed
is observed, so the new suppression branch is **unexercised in production**.
Main reader gap timing23rows:3known/20overflow; known in-window residence2629.85ms
at2:12:17; tail2980.82/3423.12ms. Derived reader10gap rows(3known/7overflow), including
10053.56ms, remains separate from real mainreader. Additional status-overflow
receipts preserve unknown timings. The warning without ticker/reader cannot be
assigned to this BTC market. Zero bounded Traceback matches does not erase these
gaps or certify continuous coverage.

Final fixed original **2:16:33.087PM** says LIVE/authenticated/empty waiting,
cash$30.7296/cumulative−$19.0118/day−$4.5647, no positions, one order/reserved45c.
It **precedes** the next-window48c fill, so it is not a final-tail exposure or cash
audit. V2 stays disabled with its five old scores; V1unknown29→30/pregap26→27.
The one16c win cannot be attributed to this correction and does not establish a
profitable strategy or justify larger stakes. These runtime limits keep broad
EXEC OPEN, while the bounded PR65 release/verification task is complete.

## Recorder and remaining work

Original **2:00:08.909PM** recorder report for the prior hour shows592,963,377
retainedbytes/4,831,838,208cap, level0/deletions0; this is not disk-free measurement.
Sixty sampled BTC/tape minutes and reported fresh-bookshare1.0 do not certify
coverage: coverage_certified=false, rawrows/outcomes/per-venue tickverification
false, one spot-reconnected gap. Original1:21:18PM Kraken disconnect and1:21:23PM
reconnect remain visible. Existing **3:45PM Pacific** recorder checkpoint/storage
review is retained. Connected platform access does not currently export raw volume
rows; no claimed row-level replay or strategy backtest followed from these reports.

This bounded capture/release is complete. Separately complete
the source-version observer repair and its own prospective runtime proof. Keep
broader EXEC/profitability and original/inverse comparison open, every existing
business/takeover commitment deferred/unfinished, and TJR/MNQ last. Nothing here
raises limits or proves an account that only goes up.
