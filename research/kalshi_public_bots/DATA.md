# Public Kalshi fill sample: szg.szg

Captured 2026-10-13 UTC, using unauthenticated public GETs only. These files are compact research evidence, not a trading rule, a backtest or verified account P&L. No orders, account credentials or private holdings were accessed.

- `szg_fills.csv`: 300 unique public Social fills across eight Bitcoin 15-minute windows, normalized from three returned pages. Public trade IDs remain so individual observations can be checked.
- `szg_windows.json`: source/capture metadata, per-window counts and market results. Opaque pagination cursors are excluded. More history remained after page three.

## Sources and reconstruction

1. Read [szg.szg's public Social fills](https://api.elections.kalshi.com/v1/social/trades?nickname=szg.szg), then followed two cursors returned by that response. All pages explicitly reported `visibility_state=visible`. Social endpoints are first-party but not covered by the documented exchange API schema; their observed fields may change.
2. For each sampled ticker/time interval, read one bounded page, at most 1,000 records, from the documented [public trade endpoint](https://docs.kalshi.com/api-reference/market/get-trades), `https://external-api.kalshi.com/trade-api/v2/markets/trades`. Match by exact `trade_id`; verify timestamp, fixed-point quantity and YES price.
3. Read `https://external-api.kalshi.com/trade-api/v2/markets/{ticker}` for each window's explicit `close_time`, status and result. Do not infer UTC close time from the ticker's clock text.
4. Preserve economic direction/price only for exact tape joins. Unmatched fields are blank, not zero and not simulated. All eight markets were finalized when collected; the selected direction agrees with the outcome in the joined subset. This does not establish the trader's net inventory, opening/closing activity or profit.

The three Social pages cover executions from **05:40:30 to 13:13:24 UTC on October 13**. Capture times are in `szg_windows.json`; Social page one uses the recorded start of its profile-request batch. The first and last windows can be partial. Repeating the latest-page request later will return different data; the CSV freezes this observation, and replay of its arithmetic does not need network access.

## CSV units and mapping

| Column | Meaning |
|---|---|
| `trade_id`, `ticker` | Public exchange identifiers. A fill is not necessarily a distinct order. |
| `executed_at` | Source execution timestamp in UTC; exact equality checked for joined tape records. |
| `count_fp` | Decimal contract quantity from the fixed-point string, including fractions. The old integer `count` can truncate it. |
| `profile_role` | `maker` or `taker`, identified by the public Social nickname field matching `szg.szg`. |
| `social_yes_price_dollars` | Original Social `price_dollars`; dollar price on the YES scale in all 220 exact joins. Social's schema is undocumented; unmatched rows have not been independently price-validated. |
| `v2_taker_outcome_side` | Canonical `yes`/`no` exposure from the exact public v2 trade; blank if unmatched. |
| `own_economic_direction` | Canonical taker direction when the profile is taker; opposite direction when maker. This is exposure direction, not proof of opening a position. |
| `own_direction_price_dollars` | Corresponding public v2 `yes_price_dollars` or `no_price_dollars`; blank if unmatched. |
| `market_close_time`, `market_result` | Explicit market metadata, not ticker parsing or a simulated settlement. |

The [official direction reference](https://docs.kalshi.com/getting_started/order_direction) is important. Social `taker_action=sell` and `taker_side=yes` sometimes match v2 `taker_outcome_side=yes`; applying a legacy action/side flip would misclassify exposure. Neither the Social legacy action nor the other participant's action establishes this profile's own buy/sell or opening/closing behavior. Similarly, Social YES price `$0.0020` can describe this maker's NO-direction trade at `$0.9980`, not a cheap `$0.0020` purchase.

## Reconciled totals and selection limits

- **300** rows and unique trade IDs; **220** exact tape joins, **80** unmatched; **8** windows.
- **229 maker / 71 taker fills**: maker share **76.33% of fill count**.
- **340,981.49 contracts** across the sample, including **202,317.56 maker contracts**: maker share **59.33% of contract quantity**. Do not confuse the two denominators.
- The 220 joined fills have directional prices **$0.995–$0.999**, with one direction per sampled window. **This range does not characterize all 300 fills.**
- The 80 unmatched Social YES prices span **$0.0060–$0.0580**. Bounded latest-tape pages create time and price selection, so the joined subset is not representative by construction. Unmatched economic direction and price remain unknown here.
- No private fees, orders, cancellations, inventory, cash, deposits, or historical order books were available. We cannot infer hold-to-settlement behavior, account return, exact triggers, our fillability, or guaranteed automation. This same-day sample has no held-out predictive test.

The export was re-read and checked for unique IDs, role totals, 220 joined/80 blank fields, each window's counts, and canonical direction counts. Every CSV-derived count agrees with the JSON aggregate. No return was computed.

## Integrity fingerprints

SHA-256 of the committed CSV:

```text
61a2057c84cab8bb42d4cb4b0e226f367ee5cac4addb3debaea5b4830dbfd923
```

Raw public response files were retained in the collection workspace, not committed as a cache. Their SHA-256 hashes identify the exact inputs; a hash is not proof of venue authenticity:

```text
profile-szg.szg.json  f5de41bd386b63b3cab5d5f3406bf18e292397da0729ad4b956bc8819b760c98
szg-page-2.json       83087edfe481830757e22fc55784f8fce9716eab2041560878a2d3ee59d737fe
szg-page-3.json       0e2b559ab704ccb92ea2ebcfd422c7d2b7f952ab85fc73d958da46ca9cff9b9e
```
