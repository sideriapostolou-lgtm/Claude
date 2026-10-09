# Q10 (LP1): be the house. Pre-registration, version q10-v1

Written 2026-10-09 ~11:00 UTC, before any outcome of this hypothesis was read. Idea-mill item q10 (merged raw idea
OC-OA19; sources: Galaxy, a Solana node operator's fee analysis, pump.fun/docs/fees). Every other hypothesis in the
lab bets on the token's direction. This one does not: it deposits liquidity into a busy, fresh PumpSwap pool and
collects the LP fee (20 bps of every trade at market cap >= 420 SOL) while carrying half the token's exposure.

## 1. Gate G0 (protocol semantics, read before modelling) - PASSED 2026-10-09 10:55 UTC

Sources: `pump-fun/pump-public-docs` (`docs/PUMP_SWAP_README.md`, `docs/VIRTUAL_QUOTE_RESERVES_FEE_ADJUSTMENT.md`,
`docs/NEGATIVE_VIRTUAL_QUOTE_RESERVES.md`, `docs/SYNTHETIC_MIGRATION.md`), pump.fun/docs/fees (updated 2026-10-08),
and the lab's own bars (3,863 TRAIN pools).

- Quotes: constant product on `effective_quote_reserves = quote_vault + virtual_quote_reserves` and the raw base
  vault. Our bars carry `X` (effective) and `x_real` (vault), so `v = X - x_real`.
- `virtual_quote_reserves = boost_reserves - protocol_fees_waiting - creator_fees_waiting`. On every TRAIN pool
  `v` starts at +17.585 SOL (the migration boost; median 17.585, range 17.14-19.87) and never turns negative inside
  180 min; `x_real` never reaches 0. `v` falls only when v2 trades keep protocol/creator fees in the vault (15 % of
  pools); a sweep pays them out and adds the same amount back to `v`.
- The LP fee "goes back to the pool in the form of liquidity": it stays in the vault AND in the effective reserve
  (price-moving, like Uniswap), so it accrues to LP token holders pro rata. Protocol and creator fees are "not
  liquidity" and never reach an LP.
- Deposit/withdraw: `deposit(lpTokenOut, maxBaseIn, maxQuoteIn)`, `withdraw(lpTokenIn, minBaseOut, minQuoteOut)`,
  no fee, priced on the pool balances (not the effective reserve). Fairness check: a depositor supplying SOL and
  tokens in the vault ratio hands over value `x_d (1 + X / q)` and receives a claim worth `x_d (1 + X / q)` when
  priced against the real vault `q`; priced against the raw vault (real + waiting fees) the depositor is slightly
  WORSE off. **No mispricing in the depositor's favour exists, so nothing here exploits a protocol bug.**
- The boost is depth the LP does not own: LP value = `s (q + y p) = s (2X - v)`, so a price move by factor `r`
  gives `(2X sqrt(r) - v) / (2X - v)` instead of `sqrt(r)`: the LP is levered against the boost (r = 0.5 ->
  -32.7 % instead of -29.3 %; the real SOL is gone at r = (v / X)^2 ~ 0.04).
- Open point (live only, not for the test): whether a third-party deposit into a canonical pool is accepted on
  chain. The instruction is generic over pools; a $1 deposit on mainnet would settle it before any real use.
  Jupiter cannot do this; a direct program call is needed.

## 2. Universe and decision grid

- Splits and bars as in `common.py` (TRAIN 10-01 -> 10-05, VAL, TEST one look, CONFIRM, FINAL census thirds).
- Decisions on the lab grid (minute boundary + 20 s), from age 10 min to the deadline; one position per coin
  (the first decision that qualifies). Only SOL-quoted canonical pools.
- Eligible at a decision when ALL hold (as-of, completed bars only): alive (PLAN R0 rule: 15-min volume >= $1,500
  and market cap >= $6,000); market cap >= 420 SOL (the 20 bps LP tier; below it the LP gets 2 bps);
  |15-min return| <= 20 %; and the selection criterion `V15 >= M * x_real` (15-min buy + sell SOL vs real depth).

## 3. The position (FIXED)

- Ticket $20 (`size_usd`), converted at the as-of SOL/USD. Order lands 30 s after the decision; token leg bought
  at the WORST price of the landing bar (max(open, high)) with the pool's own fee tier, Ultra 10 bps, 20 bps
  slippage/MEV haircut and constant-product impact (`common.simulate_buy`). The SOL leg is sized to the vault
  ratio (`x_real / y`), so the deposit is token-heavy on boosted pools; SOL that cannot be deposited stays as cash.
- Share `s = tokens_deposited / y` (state at the start of the landing bar). LP value in SOL at bar i:
  `s * (q_i + X_i)` with `q_i = x_real_i - max(0, v_ref - v_i)` (waiting protocol/creator fees, which an LP
  cannot claim, are removed; `v_ref` = `v` at entry).
- Exit: triggered on completed bars; fills one bar later (`FillConfig(exit_delay_bars=1)`): withdraw
  `s * q_e` SOL and `s * y_e` tokens, sell the tokens at the worst price of the fill bar (min(open, low)) through
  `common.simulate_sell`. Costs: 4 network fees (buy, deposit, withdraw, sell) and the ATA rent stress.
- Exit triggers (first of): price <= D x entry price (D in the grid; "deadline" configs have no stop);
  30-min volume < 1 x `x_real` (a quiet pool pays no fees); the registered deadline g + 178 min; the data horizon.

## 4. Grid (6 counted trials, PLAN 3.4 limit 8)

`M in {3, 6}` x `D in {0.7, 0.5, none}`. Config key `M<M>|D<D>` or `M<M>|deadline`.
Tie-break order (most conservative first): M6 before M3; D0.7, D0.5, deadline.

## 5. Controls and readings

- Matched placebo: for each entry, 20 LP deposits of the same size at a random coin that is alive with market
  cap >= 420 SOL at a decision age within +-120 s of the signal's (the selection criteria `V15 / x_real` and
  |R15| are the only differences), same exits, same costs. Reading: BEATS_RANDOM / WORSE_THAN_RANDOM / NEITHER
  from the paired difference's 95 % CI (n >= 30).
- Same-entry comparisons, reported per config: the token's mid return over the hold; `ret_5050` = holding half
  SOL / half the token with the same entry and exit costs and no fees (what the LP would earn with zero volume);
  the estimated LP fee income `s * sum(lp_bps_i * volume_i)` (the mechanism's size). The LP minus `ret_5050` gap
  is the fee-minus-leverage effect and must be positive for the mechanism to be real.
- Stress: costs x1.5; rent $0.22; same-bar exits; no entry-bar exits.

## 6. Decisions

- TRAIN: a config qualifies with n >= 30 trades, mean > 0, mean without the top 2 > 0 and placebo diff > 0;
  rank by the coin-bootstrap 90 % CI lower bound, then mean, then the tie-break order; shortlist the top 2 (PLAN
  3.5). No qualifier -> NO_CONFIG (dead). n < 30 everywhere -> UNDERPOWERED_TRAIN.
- VAL: the shortlisted config with the higher VAL mean among those with >= 15 trades; SELECTED needs mean > 0 and
  a sign test; the other is its twin. The judge must read VAL before TEST.
- TEST (one look, `LAB2_ALLOW_TEST=1`): `common.verdict_entry` with min mean +3 %. CONFIRM and FINAL as in PLAN.
- A TEST pass never funds real money by itself: live execution needs a deposit/withdraw path that does not exist
  in the bot, a $1 mainnet deposit check (G0 open point) and the owner's explicit go.

## 7. Power (counts only, TRAIN, read 2026-10-09 10:55 UTC before any outcome)

At the 10-min decision: 2,468 of 3,863 coins alive; 1,856 at market cap >= 420 SOL; 190 with |R15| <= 20 %.
First-hit entries anywhere in the window: M3 433 coins (108 / day), M6 364 (91 / day). Median `V15 / x_real` at
10 min is 4.3 (p90 39): fresh pools turn over several times their real depth every 15 minutes.

## 8. Stop rules

- G0 fails -> never run (it passed).
- TRAIN NO_CONFIG -> dead; no re-spec of the grid on this data.
- A VAL or TEST mean below zero closes the hypothesis.
