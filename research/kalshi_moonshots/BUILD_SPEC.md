# Build specification: isolated crypto long-shot research

Proposed modules and tests, not implemented here. Policy: [STRATEGY.md](STRATEGY.md). Research-only
defaults; no order transport or real-money capability in the first build. Source baseline `f7ab4d7`
includes the preceding independent speed-desk timing update `7ce65d8`.
Before saving this report we also pulled `417cf0f` (PR #27, smaller state saves); its code remains untouched.
The source anchors below describe the inspected `f7ab4d7` baseline and are not claims of new latency results.

## Existing pieces and boundaries

| Existing code | Reusable part | What must change in a separate research implementation |
|---|---|---|
| `speeddesk_kalshi.py:40` | Rules/series validation, market strike, public books and canonical trade direction | It intentionally selects a whole-cent grid; preserve native price bands instead. |
| `speeddesk_kalshi_ws.py:78` | Market-data handshake, book sequence checks, source versus receipt timing | Add narrow index subscriptions; a snapshot arrival is not quote-source freshness. |
| `skipwatch_bitcoin.py:25` | Multi-exchange timestamps, causal 1/5/30s features and connection generations | Use verified midpoint feeds and index basis; do not assume current last-trade features satisfy this policy. |
| `speeddesk_model.py:100` | A tested normal-CDF baseline | It is not a final-minute average model or calibrated extreme-tail distribution. |
| `speeddesk_model.py:553` | First post-delay IOC recheck; real prints consuming maker queue | Add symmetric sell simulation, exact decimals and per-order fees. |
| `skipwatch_journal.py:108` | Durable append-only receipts and recovery | New independent directory, quotas and gaps; never mix strategy cash. |
| `speeddesk_metrics.py:39` | Coverage and latency cohorts | Separate source age, decision delay, transport and simulated arrival. |
| `speeddesk_live.py:883` | Durable intent, unique IDs, timeout reconciliation pattern | Do not import its side-effectful live controller into research. |

Current live guards require whole-cent prices and whole-contract submissions; fractional fills are
already possible. Current risk/ledger code is **buys only**, rejects sell fills, and was designed for
paired holdings. Neither its opposite-side buying nor its inventory cap exemptions belong in this new
strategy. A source push restarts the existing money service, so even a recorder needs normal review,
green checks, resource limits and exact-commit deployment verification.

## Module contracts

1. **`moonshot_types.py`** — Decimal price/quantity/cash, explicit monetary units, native grid bands,
   minimum order metadata, BUY/SELL intent, contract rules/version, source timestamps, receipt monotonic
   timestamps and uncertainty. Preserve original decimal strings. Never silently round an off-grid price
   into a more expensive order or raise quantity to a minimum that exceeds the budget.
2. **`moonshot_recorder.py`** — Read-only market/index/spot subscriptions, full book reconstruction,
   public prints, instrument/fee revisions, lifecycle/cutoff events and coverage. Capability interface has
   no account/order methods. Index authentication must reuse an approved read-only adapter, never expose
   keys to fitting/reporting. Confirm actual index availability and raw frames, not just subscription ACK.
3. **`moonshot_model.py`** — Causal path distribution for the exact averaged settlement value, basis and
   tail calibration, versioned artifacts and `q_L` availability. Five-Hz ticks are predictors; the
   settlement sample retains its own count/boundaries. Return an explicit rejection when unsupported.
4. **`moonshot_policy.py`** — Pure deterministic entry/exit decisions implementing the frozen policy.
   Inputs contain model/version, book/version, clock/latency state, exact costs, owned inventory and
   reservations. Return an intent plus machine-readable reason; no network, money movement or refitting.
5. **`moonshot_sim.py`** — Event replay with delayed IOC buys/sells, depth consumption, partials, cancel
   races and native fees. Implement maker queues only for a separately frozen later maker experiment.
   Fill at the first valid arrival state, not a later favorable rebound. Rejected/unknown/no-fill are
   distinct. Replays at multiple sizes/policies are alternatives, not simultaneous claims on one book.
6. **`moonshot_ledger.py`** — Entry cost, available/held/reserved quantity, exit revenue, actual model
   fees, realized loss/profit and unsettled value. One deterministic cost-basis allocation, replayable
   fills and settlement corrections. Paper cash never enters actual balances or town growth.
7. **Research `fit.py` / `report.py`** — Frozen data manifests/splits, candidate version, complete-window
   and day clusters, calibration, executable returns, latency stresses, capacity and fail/inconclusive
   verdicts. Fit cannot write the deployed model or enable a live mode automatically.

No `moonshot_execution.py` or live switch in phase one. A future live proposal must use a single
account-level allocator, reconciled real fill/fee receipts and explicit new owner amounts.

## Data and causal clocks

Store under `/data/moonshot/` with bounded disk/CPU/network use and explicit backpressure gaps. Journal
records: schema version; strategy/session/connection; exchange event ID/sequence; raw-source timestamp;
local receive UTC and monotonic time; clock error; raw payload fingerprint; contract/model hashes;
snapshot/delta validity; decision inputs/reason; hypothetical order/arrival/fill; fees and settlement.

Sequence loss invalidates the book until recovery. A reconnect resets unknown queue priority. Late and
duplicate frames remain evidence but cannot rewrite what the strategy knew earlier. Historical backfill
is labeled as later knowledge. Window and date boundaries use exchange UTC metadata, not ticker text.
The journal preserves all candidate/rejection observations, including periods with no trades.

Calibration data must include unsuccessful tail forecasts and all relevant outcomes, not only orders
that a prior model elected to place. Sell-policy labels describe executable bids after causal decisions;
the future maximum is never an action label available to the policy. Track disappearance before entry
separately from an adverse move after fill.

## Exact accounting

For entry fills `(Q_i,P_i,F_i)`, exit fills `(R_j,B_j,G_j)` and official binary result `Y`:

```text
owned_quantity = sum(Q_i) - sum(R_j)
cash_spent = sum(Q_i * P_i + F_i)
cash_received = sum(R_j * B_j - G_j)
terminal_net_pnl = cash_received + owned_quantity * Y - cash_spent
available_to_sell = owned_quantity - pending_or_unknown_sell_quantity
```

The fee emulator implements the applicable schedule, model-fee precision, signed cash rounding and
order-level rounding accumulator. Preserve expected economics separately from worst-case reservation.
No promised future rebate can be spent before receipt. Actual minimum order/quantity eligibility must
be verified; wire decimal precision alone does not prove acceptance.

On an eventual real account, use actual receipts and exchange netting/settlement behavior, not simulated
fees. Buying the opposite outcome must not be silently substituted for a sale. Current v2 order commands
quote a single YES book; explicitly map economic outcome/action and prevent unintended opposite exposure.
[Official create-order v2](https://docs.kalshi.com/api-reference/orders/create-order-v2) currently restricts
reduce-only to IOC. Confirm fields and current constraints again at implementation.

## State and failure handling

```text
DISABLED -> OBSERVING -> DATA_READY -> ELIGIBLE
  -> ENTRY_INTENT -> ENTRY_PENDING -> OPEN
  -> EXIT_INTENT -> EXIT_PENDING -> CLOSED
                           residual -> AWAITING_SETTLEMENT -> SETTLED
pending/unknown -> RECONCILING
data/rules/integrity failure -> HALTED_FOR_NEW_ENTRIES
```

Track child orders separately from aggregate position: partial fills do not fit a single simple flag.
A cancel request is not final cancellation. A timeout retains the cash/quantity reservation and triggers
ID-based reconciliation; never resubmit a create blindly. Late fills remain real even after an exit
decision, disconnect, mode change or process restart. Exits cannot exceed confirmed available quantity.
At close, do not assume a cancel/sell can still execute; reconcile venue state and residual settlement.

Stopping blocks new exposure and cancels owned entry orders. It may still allow specifically authorized
risk-reducing exits while usable books exist. A failed exit remains exposed. Full entry premium is the
loss budget; a stop-loss price is not a guaranteed limit on realized loss.

## Existing-account collision: mandatory future live gate

The current speed desk already trades BTC windows in the same Kalshi account. Kalshi nets positions.
Two autonomous controllers can consume the same cash, hedge each other unintentionally or sell each
other's holdings. Before a live moonshot path, use **one shared account/order/risk owner** with durable
strategy allocations, or an explicitly supported and authorized isolated account arrangement. Separate
Python files, client-ID prefixes or internal ledgers alone do not isolate venue exposure. Do not weaken
the current foreign-position protections to make this strategy fit.

## Required tests

| Area | Required adversarial cases |
|---|---|
| Monetary units/grid | .001 dollars versus .1 cents; every native band boundary; invalid four-decimal price; fractional quantities; exact complement; fee-inclusive budget after size rounding. |
| Fees | Buy/sell signs, maker/taker/event overrides, split partials and accumulator rebates, separate-order accumulators, worst-case reserve, no unreceived rebate spending. |
| Settlement | Exact strike; YES tie; asset-specific rounding; known prefix and 60th tick; trailing versus final-minute boundary; five-Hz data cannot replace one-Hz samples; missing values and exceptional rules. |
| Causality/model | No future tick or corrected hindsight input; source/receipt clocks differ; old calibration cannot claim new unsupported regime; zero evidence returns unavailable rather than a probability floor. |
| Entry/exit simulation | Ask cancels before arrival; wrong-side print; bid absent at exit; target touched with no available size; partial IOC; queue depletion before maker fill; duplicate depth not reused. |
| Risk/accounting | No shorts or duplicate exit; fills after cancel; unknown create; mode change; restore after crash; cash/quantity conservation; full-loss budget despite planned sale. |
| Isolation | Observer and paper imports cannot construct/call an order client; existing desks untouched; eventual account allocator rejects double cash/inventory use. |
| Evaluation | Held-out data unavailable to fitting; split embargo; incomplete windows/pending settlements; quantity is not independent trials; identical replay is deterministic. |

Required before runtime merge: full pytest, mypy, Ruff on changed Python, secret scan and independent
money/accounting review if any future real-order path is proposed. A source deploy requires matching
Railway's commit and healthy existing-desk logs. This research documentation does not require a restart.

## Build order and review outputs

1. Recorder and instrument/fee arithmetic: prove source access, clocks, grids, average reconstruction,
   quota safety and data completeness. A few days can establish feasibility, not profitability.
2. Two-way replay and exact ledger: demonstrate missing fills, losing exits, residual settlements,
   fee conservation and resource isolation with recorded/fake data before fitting a profitable story.
3. Frozen model/policy and forward study: follow the chronological protocol in STRATEGY; publish all
   rejections, losses, gaps and uncertainty. No automated promotion based on a few lucky outcomes.
4. Only after evidence supports it, prepare a concrete live proposal with account allocation, selected
   series, cash budget, per-window/open caps, daily/lifetime stops and a bounded scale schedule. The owner
   names/approves those amounts. No such request or activation is part of this design session.

Future phone display: OBSERVING / SIMULATED / REAL only when applicable; actual cash separate from marks;
estimated probability with uncertainty; executable entry/exit price and size; signal reason; missed-fill
reason; realized fees/profit; remaining risk and data age. Never show the maximum conditional payout as
cash earned or make simulated activity grow the real-money town.
