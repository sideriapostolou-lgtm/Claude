# Independent Kalshi shard API review — 2026-10-16

Scope: public documentation HTTP GETs only, reviewed from repository `nightcrawler-shard-cash` after its AGENTS.md and newest COORDINATION inbox (Claude 13:55 UTC). No credentials, authenticated account calls, orders, transfers, allocation changes, research TEST data, or production operations. Documentation OpenAPI version observed: 3.34.0. This proves API contracts, not the account-specific reason for its rejects.

## Cash contract

Source: https://docs.kalshi.com/api-reference/portfolio/get-balance.md

- `GET /portfolio/balance` defaults to primary subaccount 0. `subaccount` selects another account (numbered accounts 1–63). Without `exchange_index`, top-level balance and portfolio value include all exchange indexes.
- `balance`: integer cents. `balance_dollars`: fixed-point USD string. `portfolio_value`: integer cents; not cash for admission.
- `balance_breakdown`: optional array of `{exchange_index: integer, balance: FixedPointDollars}`. Its `balance` is a **USD string**, not cents or centicents. FixedPointDollars response precision is up to six decimals. E.g. `"25.121900"` means $25.1219.
- Breakdown is described as “User balance breakdown per exchange instance, omitted only when using a subaccount-restricted API key.” The docs do not define an absent shard row as zero or provide a fallback-to-aggregate rule. They also do not explicitly state how breakdown contents follow a numbered `subaccount` filter. Do not infer those semantics.
- `updated_ts` is Unix seconds of the last balance update; it is not a snapshot receipt timestamp. Freshly read unchanged cash can legitimately have an old updated_ts.
- Endpoint has its own no-burst bucket: Basic/Advanced 1 call/sec, higher tiers 5/sec. Docs say balance only changes on fills, settlements and transfers; polling every order is unnecessary.

Source: https://docs.kalshi.com/api-reference/portfolio/get-all-subaccount-balances.md

- `GET /portfolio/subaccounts/balances` returns `subaccount_balances` rows with required `subaccount_number`, `exchange_index`, `balance` (USD string), `updated_ts` (Unix seconds). This is an unambiguous account+shard lookup for unrestricted keys.

### “Available balance” does not prove unencumbered spendable

Get Balance labels the top-level cash “Member's available balance.” Its breakdown schema gives no additional hold/reservation definition. The statement that cash changes only on fills/settlements/transfers, and the sharding guide's explicit subtraction of resting orders when computing rebalance cash, mean this API response must **not** replace the bot's resting/inflight/fee reservations. Public docs do not fully specify pending withdrawals, account holds/restrictions, or a complete collateral admission formula for this account. An HTTP200 cash read is not proof every proposed order will be accepted.

https://docs.kalshi.com/api-reference/portfolio/get-total-resting-order-value.md describes `GET /portfolio/summary/total_resting_order_value`, including per-shard USD breakdown, but explicitly says it is intended only for FCM members. Do not introduce a retail dependency on it.

## Shards and orders

Sources:

- https://docs.kalshi.com/getting_started/exchange_sharding.md
- https://docs.kalshi.com/api-reference/market/get-market.md
- https://docs.kalshi.com/api-reference/orders/create-order-v2.md

The matching engine performs collateral checks per shard. Programmatic traders normally must fund that shard first. App/web orders auto-transfer cash as needed; that does not describe REST bot behavior. FCM FIX auto-transfer is a separate eligible-session feature. New Crypto/Commodities events go to shard 2, but ticker categories are not authoritative: market `exchange_index` is. All children of an event share a shard and no live-market migration is currently planned.

`POST /portfolio/events/orders` is the documented V2 order route. Request uses required `ticker`, side `bid`/`ask`, fixed-point contract `count` string, fixed-point USD `price` string, time_in_force and self_trade_prevention_type. Request-body `exchange_index >= 0` explicitly targets a shard; `-1` requires auto-route using ticker; omitted index with ticker auto-routes. V2 docs call the field `ticker`, unlike the general guide's broader `market_ticker` wording. Current `exchange_index: -1` is therefore valid, not a cause of insufficient balance by itself. Missing market index must not silently become 0 for cash checks. Market schema does not provide that fallback.

## Transfers/allocation (contract only; excluded from implementation)

https://docs.kalshi.com/api-reference/portfolio/intra-account-transfer.md

- `POST /portfolio/intra_exchange_instance_transfer`: source/destination enum `event_contract` or `margined`; required integer `amount` **centicents**, i.e. $1=10,000, $25=250,000. Source/destination shard fields default 0, documented range 0–100.
- HTTP200 means asynchronously accepted, not completed; returns `transfer_id`.
- Optional client_transfer_id UUID duplicate prevention is route-scoped and supported only for primary accounts; numbered-subaccount transfers reject that field. Omitting it creates a new transfer on each request.
- source_subaccount/destination_subaccount default 0 and are supported only event-contract to event-contract. Same-shard transfer is handled as subaccount transfer. Cross-index subaccount transfer takes up to three non-atomic steps; completed steps are not undone if later steps fail.

https://docs.kalshi.com/api-reference/portfolio/get-intra-account-transfer.md

- `GET /portfolio/intra_exchange_instance_transfers/{transfer_id}` returns status enum `pending`/`complete`; read-side `amount` is a fixed-point **USD** string, unlike write-side centicents.

https://docs.kalshi.com/api-reference/portfolio/transfer-between-subaccounts.md

- Separate `POST /portfolio/subaccounts/transfer` uses required integer `amount_cents` (**cents**, not centicents), client_transfer_id, from_subaccount/to_subaccount, optional exchange_index default 0.

https://docs.kalshi.com/api-reference/portfolio/set-target-balance-allocation.md
https://docs.kalshi.com/api-reference/portfolio/get-target-balance-allocation.md

- GET/POST `/portfolio/target_balance_allocation`; POST replaces allocation, integer percentages 0–100 total 100, empty array disables automatic rebalancing. Each exchange_index >=0; up to 101 rows.
- `resting_margin_reservation`: default `sum`, leaves summed resting-order margin behind; `max` leaves largest single market-side commitment; `none` leaves none. Guide says Kalshi checks every 10 seconds and transfers to restore target percentages, considering account balance less resting orders. This is an ongoing financial setting, not a read-only cash check.

https://docs.kalshi.com/api-reference/exchange/get-exchange-status.md

- `intra_exchange_transfers_active` reports transfer permission. Top-level flags describe shard 0; optional `exchange_index_statuses` carries per-shard active/trading/transfer flags. Top-level true does not prove shard 2 transfer availability.

## Subaccount key restrictions

https://docs.kalshi.com/getting_started/subaccounts.md

Restricted keys can read/trade only their locked subaccount; omission of subaccount selects that locked one, naming another is rejected. They cannot transfer funds or manage subaccounts/API keys; unsupported endpoints return 403. Therefore missing breakdown on a restricted key is a legitimate shape, not positive cash evidence. A scoped `GET /portfolio/balance?exchange_index=<market shard>` with the correct account is the natural read-only alternative, or fail closed if unsupported. Never silently fall back to aggregate cash or the primary account on a restricted key. Numbered accounts are API-only, not yet managed by web/mobile.

## Deterministic implementation recommendations

1. Keep aggregate cash/portfolio reporting separate from target-shard admission cash. Resolve exact market index and exact order subaccount; no category/ticker guess or missing-as-zero routing.
2. Parse USD decimal strings exactly, require finite nonnegative amounts and actual nonnegative integer indexes (reject bools/floats/strings). Duplicate target rows, missing target, null/malformed rows, missing breakdown, and fetch errors produce explicit unknown/unavailable status and block new entries. Missing row is not documented as zero. A scoped read may resolve it; aggregate cash may not.
3. Preserve all existing caps/stops/local reservations. Gate quantity*price plus fee reserve against conservative target-shard headroom; include in-flight/unsent pending commitments. Conservatively subtracting all local reservations from target-shard cash is safe though less permissive than exact shard assignment. Unknown foreign orders/holds remain limitations; don't claim venue-guaranteed spendability.
4. Tie freshness to successful receipt time. Invalidate or conservatively debit after submissions/fills until reconciled. Do not count a cancellation as released cash until confirmed; never refresh stale cash merely by serializing it again.
5. Treat exact structured `insufficient_balance` as a definite refusal: release only the refused order's reservation, persist a bounded cooldown and reason, enforce it immediately before every submit (including lock/hedge paths), and do not let ordinary successful reads/error-clearing erase it. Preserve backoff over restart. Ensure periodic read refresh cannot silently remove it. Retain existing risk-reduction cancellation/reconciliation pathways.
6. No transfer endpoint or auto-allocation setting is required for this fix. No secret, money-setting, loss-reset, or live-enable changes. Unit tests should pin dollar units, aggregate-funded/target-empty, missing/invalid/duplicate shapes, old updated_ts with fresh receipt, stale/error invalidation, reservations, and cooldown across callers/restart.

Unresolved: actual account cash distribution and account restrictions; complete venue collateral/holds semantics; runtime acceptance after manual funding. The shard-2 explanation is plausible and contract-supported, but not proven by public docs alone.
