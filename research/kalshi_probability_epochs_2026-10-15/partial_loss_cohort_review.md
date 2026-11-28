# Partial loss and cohort review — provenance repaired

**Provenance repair:** The original v1 artifacts are preserved as `.v1`. This version selects only the latest actual object in `structuredContent.deploy` whose `message` matches `^\S+ INFO nightcrawler\.speeddesk: speeddesk_live_status `; no wrapper display text was parsed. Native row timestamp: `2026-10-15T21:39:48.144889077Z`; deploy array index: `4`; matched originals: 5. Message SHA-256: `a6aec0c75a43b0d450861d2a5daee391ce30f27762ab2f2081bfcd81bdeea601`; payload SHA-256: `cd208ad15584bc5de70266d1fdab969445f15379322854f89029ff3139fd2c8a`. Input SHA-256: `3f7799bc958e9093f846f9623beb2549908ef0c2a4f2932d9df5bd27ddc01a62`. The v1 wrapper-text timestamp ending in `Z info` was display provenance and is superseded here.

**Comparison to v1:** No extracted values changed (0 value mismatches). The repaired extraction restores 16 scorecard fields that v1 omitted, including settled/unsettled traded-window counts, unmatched fees, and full-cohort worst values for today and prior days. Every added field is listed in the JSON `provenance_repair_comparison.differences` field; nulls remain null.

The original reports **mode `paper`**, configured mode `live`, status `PRACTICE`, trading now `False`, with daily stop latched. Cash: $30.2496; reserved/open risk/open cost/at-risk: all $0; open orders: 0. Caps: window $10.00, open $20.00, day stop $6.00, total stop $10.00, clip 5.

## October 15 raw daily aggregate

The top-level `today` aggregate reports 69 windows, 302 fills, 71 settled windows; P&L **$-5.0447**, with locked **$4.5012**, directional **$-9.5459**, fees **$0.8455**. It reports 3582 maker orders / 224 maker fills; 61 locks / 39 lock fills; 0 take attempts / 0 take fills.

## October 15 fully observed scorecard cohort

The separate scorecard covers **27 fully observed of 79 eligible windows**, with **52 gaps**. It has 26 traded windows, 124 fills, 167.83 matched pairs, matched pair cost **$1.0272**, and fees **$0.3744**. Cohort P&L is **$-10.0028**: locked **$-4.5708**, directional **$-5.4320**. It differs in scope from the raw aggregate and must not be combined with it. The UTC day remains open and the scorecard is partial; it says full-day discovery/recording coverage is uncertified and some window coverage or fill history is missing or invalid.

## Where recorded losses sit

In the fully observed cohort, locked loss is **$4.5708** and directional loss is **$5.4320**, with directional larger. In the raw daily aggregate, locked P&L is positive **$4.5012**, while directional P&L is negative **$9.5459** and larger in magnitude. Those figures describe different populations. They locate recorded losses but do not establish a cause.

## Prior completed UTC day reports

Top-level `reports[day].real` values are shown as separate raw and scorecard populations:

| UTC day | Raw windows / fills | Raw P&L (locked; directional; fees) | Scorecard coverage | Scorecard P&L (locked; directional; fees; pair cost) |
|---|---:|---:|---|---|
| 2026-10-12 | 2 / 3 | $1.0653 ($0.0000; $1.0653; $0.0697) | 0/19 complete, 5 gaps; partial | unknown |
| 2026-10-13 | 68 / 299 | $-11.0074 ($-0.2566; $-10.7508; $1.5004) | 6/96 complete, 90 gaps; partial | $-2.9150 ($0.5317; $-3.4467; $0.0350; pair cost $0.7342) |
| 2026-10-14 | 41 / 222 | $-4.5050 ($-0.5646; $-3.9404; $0.7011) | 0/96 complete, 96 gaps; partial | unknown |

Prior scorecards remain partial even though those UTC days ended. October 12 and 14 have no complete windows and their cohort financial fields are null/unknown. October 13 has only 6 of 96 complete windows and 90 gaps; its cohort P&L covers only that observed subset. Raw totals do not fill scorecard gaps. Incomplete coverage prevents a clean full-day or entire-history strategy verdict; this evidence does not establish causation or profitability.

The JSON preserves the extracted fields, nulls, provenance hashes, and v1 comparison. No raw full panels are included.
