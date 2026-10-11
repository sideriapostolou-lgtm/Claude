# Q11: the value of speed. Pre-registration, version q11-v1

Written 2026-10-09 ~13:25 UTC, before any return of this study was read. Owner question (same day): "if we had the
speed could we create what I want?" This is a MEASUREMENT, not a strategy: for every recorded coin, what does a $20
buy at graduation + L seconds, held H seconds, earn after real costs, for a grid of L and H? The result is a
latency x hold surface of mean returns with coin-bootstrap CIs. No parameter is selected, so there is no VAL / TEST
machinery; the 80 cells are still written to the trial ledger (kind "measurement") so the program's trial count
stays honest.

## 1. Data and universe

- Per-trade tape from B1 (`CoinData.trades`): slot, second timestamp, venue (0 curve / 1 PumpSwap pool), side,
  SOL and token amounts, pool reserves BEFORE the trade (`x0`, `y0`), virtual quote reserve (`virt_ksol`, x1000 =
  lamports). Pricing reserve `X = x0 + virt_ksol * 1000`; price = `(X / 1e9) / (y0 / 1e6)` SOL per token.
- Universe = the S1 universe (b1_select v1): usable TRAIN coins, creation scanned, `grad_delay_s > 5`
  (NOT the instant / synthetic migrations: 2,208 of the 3,863 usable coins are excluded). 1,420 TRAIN coins.
  **Bias, stated up front:** instant graduations are the ones snipers target hardest; this curve says nothing
  about them. VAL (458) and TEST (418) tapes exist and are NOT read by this study (TRAIN only: no selection means
  nothing to validate; a follow-up could pre-register a VAL look).
- The tape covers [creation, g + ~2 h] (median 6,400 s after g, minimum 361 s): a cell is counted for a coin only
  when the exit time lies inside the tape (censored cells are counted and reported).

## 2. Fills (FIXED)

- Entry at `t_in = g + L`, L in {1, 2, 5, 10, 20, 30, 60, 120, 300, 900} s. Pool state at `t_in` = reserves before
  the first pool trade with `ts > t_in` (= the state after the last trade at or before `t_in`); before any pool
  trade: the pool's initial state. Buy $20 (SOL at the as-of SOL/USD) through `common.simulate_buy`: PumpSwap fee
  tier at the market cap + Ultra 10 bps + 20 bps slippage/MEV haircut + constant-product impact on the pool's `k`.
  Our own trade's effect on later prices is ignored ($20 vs ~85 SOL of depth).
- Exit at `t_out = t_in + H`, H in {5, 15, 30, 60, 120, 300, 900, 1800} s, at the pool state at `t_out`, through
  `common.simulate_sell` (same fee tier at the exit market cap, impact on `k`).
- Costs: 2 network fees; a priority tip per entry (fast entries pay to land): tip grid {0, 0.001, 0.01} SOL; the
  0.001 SOL case is the primary, 0 and 0.01 are reported next to it.
- Slip stress: fills one second late (`t_in + 1`, `t_out + 1`) - what a bot that is one slot slower would get.

## 3. Readings (pre-registered)

For each (L, H): n coins, mean net return, coin-bootstrap 95 % CI, median, share positive, mean entry market
cap. Then:
- **Edge frontier:** for each H, the largest L whose mean return is positive with CI95 above 0 (none = no edge at
  any speed for that hold).
- **Value of speed:** mean return at L = 1 s minus mean return at L = 60 s, per H (what one minute of latency
  costs), with a paired coin-bootstrap CI.
- **Who pays:** mean return by G1 class (OPERATOR / FACTORY / COMPLETED / ORGANIC), diagnostic only (classes are
  assigned from features at g + 30 min, i.e. post hoc; they explain, they do not select).

## 4. What would follow (not part of this study)

If the frontier sits at L >= 15-30 s for some H with a meaningful mean (> 10 % after costs), a pre-registered
strategy study on VAL / TEST with a realistic feed latency is justified and the infrastructure question becomes
concrete (streaming RPC, faster execution path). If the frontier is at L <= 5 s or absent, speed is not our game.
