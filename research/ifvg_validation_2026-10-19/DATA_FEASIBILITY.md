# Fresh public-data feasibility: October 19, 2026

Metadata-only check at 21:58 UTC. Six public HTTPS requests through the inherited proxy, all HTTP200; each bounded to10MiB and30seconds. No credentials, account, purchase, price inspection or strategy replay. Raw files remain privately in `/workspace/ifvg_data_20261019/`; do not publish them. Exact URLs, retrieval timestamps, byte counts and SHA256 hashes are in DATA_FEASIBILITY.json.

## A usable exploratory candidate

FirstRate's currently offered MNQ ZIP contains16200 one-minute rows from October1 00:00 through October16 16:59,2026, US Eastern. Its readme explicitly says timestamps label interval starts and zero-volume minutes are omitted. There are no duplicate timestamps. Only the timestamp field was parsed; price/volume values were not interpreted or displayed.

For OWNER_SWEEP_IFVG_MNQ_v1's chosen intervals,11 weekdays have every scheduled timestamp: **October2,5,6,7,8,9,12,13,14,15,16**. Each has240 prior-evening Asian minutes [20:00,00:00),180 London minutes [02:00,05:00), and133 minutes09:18 through11:30 inclusive. October1 is retained as incomplete: all240 prior-evening Asian timestamps are absent. The per-day JSON includes every count and missing timestamp.

The official Nasdaq2026 PDF was freshly downloaded, rendered and visually checked against its holiday/early-close legend. These dates are regular cash-open weekdays; October12 is not marked closed. This establishes the cash calendar, not CME maintenance/halts or source fidelity.

**The sample does not establish actual-contract MNQ identity.** The CSV has timestamp/OHLC/volume only. No contract mapping or roll log is included. Vendor documentation offers unadjusted, absolute-adjusted and ratio-adjusted continuous series, but the sample's member name/readme does not establish its adjustment variant. Its individual-contract endpoint remains stale atMNQZ24 despite2026 coverage. Thus it is a root-series/continuous candidate for a separately declared exploratory sensitivity study; it cannot be called verified actual-contract profitability or fill evidence. Freeze this limitation, dates, code hash and chronological split before reading prices. Do not silently promote the proxy to the original actual-contract protocol.

The provider explicitly links this public sample for download. This pass keeps bytes private and reports metadata only. FirstRate's full linked license was not independently fetched within the six-request bound; broad entitlement or redistribution rights are not asserted. A published result must retain this provenance limitation. No raw data is committed.

## Exact-contract public sample

Portara freshly confirms its complimentary sample asMNQ2026M and defaults to Chicago-local timestamps. Its unchanged896 rows cover June15 08:04–23:59 Chicago (09:04 June15–00:59 June16 NewYork). Neither morning has the complete reference-to-entry sequence: June15 lacks priorAsian/London and June16 lacksLondon/morning. Provider format documentation states Start of Bar as standard, but a sample-specific independent flag was not found. Its purchased license permits internal research and derived results while forbidding external raw redistribution; this does not create purchased historical entitlement.

## Actionable next step

For an immediate limited experiment, explicitly freeze the FirstRate root-series proxy and its11 complete dates before any price access; keep October1's incompleteness visible. This can test the new engine and report assumption-only results with adjustment/roll/contract uncertainty and tiny-sample limitations. It cannot settle whether the actual-contract strategy is profitable. The integration owner chooses and records the split; this metadata pass does not inspect or select on returns.

For the intended actual-contract test, obtain a licensed individual MNQ export covering full overnight ranges plus09:18–11:30 on each frozen day, with verified contract/provider mapping, adjustment status, timezone/interval labels, gaps and roll documentation. FirstRate and Portara both advertise individual-contract history; neither supplied an adequate actual-contract overnight public sample in this pass. No purchase or account is implied. Costs/spreads and business expenses remain separate missing inputs.
