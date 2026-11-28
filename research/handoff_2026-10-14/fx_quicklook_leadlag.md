# fx_quicklook_leadlag (workflow wf_e0da78bf-798)



---
## result 0 

# TrueFX vs Kalshi 15-minute FX quick look — 20-minute quiet-hour sample

**Window:** Tue Oct 13, 2026, 4:56:57 PM – 5:17:03 PM PT (23:57–00:17 UTC, NY close / Asia early morning). Research only, public GETs, no keys, nothing written to the repo (`git status` clean).

## Headline

**No measurable lead for TrueFX over Kalshi at the resolution this sample allowed, and the sample cannot resolve anything shorter than ~2.6–5.6 s.** Kalshi's implied fair and TrueFX spot move together *within the same poll interval* (Δfair vs Δspot r = 0.59–0.70 at lag 0 on the two big markets, n = 66–170), and the correlation is ~0 when either feed is shifted by one poll (|r| ≤ 0.12). The task's event statistic produced only 3 events in 20 minutes, 2 of them matched, both "ambiguous within one poll interval." Treat all lead numbers below as illustrations of the measurement floor, not as findings.

## What was captured

| | TrueFX | Kalshi |
|---|---|---|
| Requests | 2,400 (all 200) at 0.5 s | 555 total: 526 orderbook (200) + 9 orderbook 429 + 20 market-list (200) |
| Rows kept | 948 distinct-timestamp quotes (EUR/USD 255, GBP/USD 319, USD/JPY 374) | 526 orderbook snapshots across 6 markets |
| Latency (median/p95) | 57 ms / 99 ms | 56 ms / 88 ms |
| Cadence achieved | 2 req/s | **0.46 req/s** (never above 2/s; min spacing 0.7 s) |

**Rate limit, honestly:** the smoke test got a 429 on the very first orderbook poll at 0.5 s spacing, so the run started at the 0.7 s fallback. It still drew 9 more 429s (4:57:02, 4:57:04, 4:59:55, 5:02:28, 5:03:02, 5:03:40, 5:05:20, 5:16:12 and one more), each adding 0.3 s to the global spacing, ending at **3.4 s**. The egress IP is shared, so these are not evidence of Kalshi's limit for a dedicated IP. Resulting per-market poll gap: median **2.6 s** (4:57–5:00), **5.6 s** (5:00–5:15), **6.5 s** (5:15–5:17). The task's 1 s floor was not achieved.

**Markets (all `greater_or_equal`, strike = Pyth print at window open):**

| Ticker | Pair | floor_strike | Closes (PT) | Snapshots | Fair first → last |
|---|---|---|---|---|---|
| KXEURUSD15M-26OCT132000-30 | EUR/USD | 1.12008 | 5:00:00 PM | 70 | 0.735 → 0.76 |
| KXGBPUSD15M-26OCT132000-30 | GBP/USD | 1.3257 | 5:00:00 PM | 68 | 0.485 → 0.985 |
| KXEURUSD15M-26OCT132015-30 | EUR/USD | 1.12012 (None at listing; filled 2 min later) | 5:15:00 PM | 181 | 0.305 → 0.965 |
| KXGBPUSD15M-26OCT132015-30 | GBP/USD | 1.32573 | 5:15:00 PM | 178 | 0.195 → 0.985 |
| KXEURUSD15M-26OCT132030-30 | EUR/USD | 1.12038 (post-filled) | 5:30:00 PM | 15 | 0.275 → 0.42 |
| KXGBPUSD15M-26OCT132030-30 | GBP/USD | 1.32594 | 5:30:00 PM | 14 | 0.425 → 0.435 |

Kalshi lists the new 15-minute market with `floor_strike: null` for the first seconds after open; the roll took 10–23 s because `status=open` did not show the new market immediately.

## 1. Kalshi implied fair per snapshot

`fair = (best_yes_bid + (1 − best_no_bid)) / 2` when both sides exist. Book states over 526 snapshots: **ok 490, empty_side 35, empty 1, crossed 0, locked 0.** Empty sides cluster in the last ~30 s before expiry (one side gets pulled). Best-level spread median 2–4 c (max 46 c at an expiry).

Churn: best levels (yes bid or no bid) changed on **71–82 % of consecutive polls**; fair moved ≥ 2 c on 19–36 %. So "time until any best-level change" is bounded by the poll interval regardless of spot, which is why I ran a stricter variant alongside.

## 2. Events and leads

**Event definition (as specified):** TrueFX mid moves ≥ 1 pip from its level at the last Kalshi reprice; event time = TrueFX server timestamp; reprice time = Kalshi local receive time. Because the reference resets on every Kalshi reprice and Kalshi repriced on ~75 % of polls, a tick must move ≥ 1 pip within one poll interval to count. In this hour that was rare.

**Mode A — reprice = any best-level change**

| | EUR/USD | GBP/USD | Pooled |
|---|---|---|---|
| Events | 0 | 3 | 3 |
| With reprice within 10 s | – | 2 | 2 |
| Lead (Kalshi detect − TrueFX ts), s: p25 / median / p75 | – | 1.16 / 1.93 / 2.70 (n=2) | same |
| Lead floor (earliest Kalshi could have changed), s | – | −2.84, −2.14 | both negative |
| Share lead ≥ 0.5 s | – | 1/3 of events, 1/2 of matched | 33 % / 50 % |
| Share TrueFX-first *resolved* (floor > 0) | – | 0 % | 0 % |
| Share ambiguous within one poll interval | – | 67 % | 67 % |
| Share Kalshi-first (nearest reprice was before the event) | – | 33 % | 33 % |
| Share no reprice within 10 s | – | 33 % | 33 % |

The three events:
- 5:00:19.814 PM GBP/USD −1.0 pip → no reprice within 10 s. **Artifact:** this fell in the roll gap; the new GBP market was not being polled until 5:00:23.
- 5:02:02.273 PM GBP/USD +1.1 pip → best levels (0.04, 0.93) → (0.09, 0.87), fair 0.055 → 0.11, detected 0.394 s after the TrueFX stamp, but the previous poll was 2.835 s *before* the stamp, so the Kalshi change could have preceded the TrueFX move.
- 5:05:30.548 PM GBP/USD +1.1 pip → (0.19, 0.78) → (0.41, 0.57), fair 0.205 → 0.42, detected 3.473 s after; previous poll 2.136 s before the stamp (ambiguous); also a Kalshi reprice 2.136 s before the event (Kalshi-first by nearest neighbour).

Both matched Kalshi moves were in the direction the spot move implies.

**Mode B — reprice = fair moved ≥ 2 c in the implied direction (stricter, my addition):** 3 events (EUR 1, GBP 2), 1 matched (the 5:05:30 event, lead 3.47 s, ambiguous), 2 with no same-direction reprice within 10 s (one is the roll-gap artifact; the EUR event at 5:01:31.7 PM saw an opposite-direction 2 c move first and a same-direction one only after 19.7 s).

**Reverse: for each Kalshi best-level change, time since the last TrueFX mid change** (195 EUR, 191 GBP changes):

| | EUR/USD | GBP/USD |
|---|---|---|
| p25 / median / p75, s | 1.79 / 3.89 / 8.84 | 1.68 / 3.84 / 7.64 |
| within 1 s / 2 s / 5 s | 17 % / 29 % / 57 % | 19 % / 33 % / 58 % |
| **Baseline** at polls with *no* best-level change: median | 7.06 s | 6.27 s |
| TrueFX mid moved during the poll interval: change polls vs no-change polls | 53 % vs 37 % | 55 % vs 42 % |
| Same, fair ≥ 2 c polls vs < 2 c polls | **71 % vs 40 %** | **66 % vs 47 %** |

So Kalshi repricing is associated with TrueFX having moved *in the same poll interval* — consistent with the lag-0 cross-correlation — but nothing here separates "TrueFX 0.3 s ahead" from "Kalshi 0.3 s ahead."

**Cross-correlation (poll resolution), Δfair vs Δspot:**

| Market | n | same interval (lag 0) | spot moved previous interval (spot leads) | spot moved next interval (Kalshi leads) | level r (fair vs spot−strike) |
|---|---|---|---|---|---|
| EUR 00:00 | 67 | 0.27 | 0.05 | 0.08 | 0.47 |
| EUR 00:15 | 152 | **0.61** | −0.04 | −0.12 | 0.97 |
| GBP 00:00 | 66 | **0.59** | −0.05 | −0.13 | 0.54 |
| GBP 00:15 | 170 | **0.70** | 0.01 | 0.02 | 0.98 |

**Settlement cross-check:** both 5:15 PM markets resolved YES on Pyth prints 1.12038 / 1.32594; TrueFX mid stamped 1.45 s before close was 1.12039 / 1.32594 (0.1 pip / 0.0 pip apart), both above strike.

## 3. Caveats

1. **Sample size:** one 20-minute window, 2 pairs, 3 ≥1-pip events (2 matched). Nothing here is statistically meaningful; this is a plumbing check, not the 2-weekday study.
2. **Quiet hour:** 23:57–00:17 UTC. EUR/USD ranged 5.7 pips, GBP/USD 5.6 pips over the whole 20 minutes; TrueFX median inter-update gap 2.7 s (EUR) / 1.6 s (GBP). Both the event count and the Kalshi books (thin, pulled near expiry) reflect that.
3. **Measurement floor:** the Kalshi poll gap per market was 2.6 s early and 5.6–6.5 s after the 429 back-offs, not 1 s. Any lead shorter than the poll gap is unresolvable; the `lead_floor` column was negative for every matched event. Even at the intended 1 s cadence, a 1 s floor would hide a sub-second TrueFX edge. Also the shared egress IP means the 429 behaviour says little about Kalshi's limit for the owner's own IP.
4. **TrueFX timestamps and cadence:** the unauthenticated CSV endpoint returns a snapshot of the latest quote per pair; polling at 0.5 s captured 255–374 distinct updates per pair, and 14–19 % of inter-update gaps were ≤ 0.5 s, so some intermediate quotes were missed. The ms timestamp is TrueFX's server stamp of the quote, not a trade time. Clock skew: in 19–36 rows per pair the TrueFX stamp was *after* our receive time (5th percentile of recv − ts: −9 to −17 ms, min −32 ms), so our sandbox clock trails TrueFX's by roughly 30–80 ms once one-way latency is added; small versus the poll floor but it biases "TrueFX first" slightly in TrueFX's favour. Median quote age at receipt 0.15–0.19 s, max 0.52 s.
5. **TrueFX ≠ Pyth:** Kalshi's rules settle on Pyth Network's EUR/USD and GBP/USD prints; TrueFX is a bank-quote aggregator. They agreed to 0–0.1 pip at the two closes observed here, but that is two points, and a Pyth-based study would need Pyth itself.
6. **Kalshi roll handling:** `status=open` lagged the new market by 10–23 s and listed `floor_strike: null` initially; strikes were filled from later list calls and one post-run GET.

## Files

All under `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/fx_quicklook/`:

- `capture.py` — capture script (python3 -I, stdlib + requests; two threads; token-spaced Kalshi limiter with escalating 429 back-off; market roll logic)
- `analyze.py` — analysis (fair parsing, both reprice modes, event matching, reverse stats, cross-correlation)
- `fill_strikes.py` — post-run strike fill for markets listed with `floor_strike: null`
- `truefx_ticks.jsonl` (948 rows; 200 KB) — pair, ts_ms, bid, ask, mid, local send/recv, raw CSV line
- `kalshi_orderbooks.jsonl` (535 rows; 1.0 MB) — ticker, strike, close_time, local send/recv, status, full raw JSON
- `kalshi_markets.jsonl` (21 rows) — every market-list and post-fill record
- `run_log.txt`, `run_summary.json`, `capture_stdout.txt` — request counts, status codes (TrueFX 2400×200; Kalshi 546×200, 9×429), 429 timestamps, latency
- `analysis.json`, `analysis_report.txt` — full numbers including every event and every reprice
- `baseline_reverse.json`, `settlement_check.json` — the baseline table and the Pyth-vs-TrueFX close check

Core computation from `analyze.py`:

```python
def parse_book(body):
    ob = (body or {}).get("orderbook_fp") or {}
    yes = [(float(p), float(s)) for p, s in (ob.get("yes_dollars") or [])]
    no  = [(float(p), float(s)) for p, s in (ob.get("no_dollars") or [])]
    yb = max((p for p, _ in yes), default=None)        # best yes bid
    nb = max((p for p, _ in no), default=None)         # best no bid
    ya = None if nb is None else round(1.0 - nb, 4)    # implied best yes ask
    state = ("empty" if yb is None and nb is None else "empty_side" if yb is None or nb is None
             else "crossed" if yb + nb > 1 + 1e-9 else "locked" if abs(yb + nb - 1) < 1e-9 else "ok")
    fair = None if (yb is None or nb is None) else round((yb + ya) / 2, 4)
    ...

# events: reference resets at every Kalshi reprice (detect time); event when |mid - ref| >= 1 pip
for tk in ticks:
    t_ev = tk["ts_ms"] / 1000
    while ri < len(reps) and reps[ri]["t_detect"] <= t_ev:
        ref_mid, pending = mid_at(ticks, reps[ri]["t_detect"]), None; ri += 1
    if pending is None and abs(tk["mid"] - ref_mid) >= pip - 1e-9:
        pending = {...}; events.append(pending)
# per event: lead = next reprice's local_recv - TrueFX ts; floor = that reprice's previous poll time - TrueFX ts
#   floor > 0  -> TrueFX first (resolved);  floor <= 0 < lead -> ambiguous within one poll interval
```


---
## result 1 

I have everything needed. All numbers below were re-derived from `truefx_ticks.jsonl`, `kalshi_orderbooks.jsonl` and `kalshi_markets.jsonl` with my own code (`/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/skeptic/recheck.py`, `timing.py`, `neighborhood.py`; nothing written to the repo).

# Skeptic re-check: TrueFX vs Kalshi 15-min FX, 20-minute quiet-hour sample (Tue Oct 13, 4:56:57–5:17:03 PM PT)

## Headline

The capture agent's event numbers reproduce exactly, but the event statistic as specified cannot measure a sub-second lead, so its lead/"share ≥ 0.5 s" figures are noise. A different test on the same raw data (regressing each Kalshi fair change on *where inside the poll interval* TrueFX moved) does resolve timing to ~0.5 s, and it finds **no lead either way bigger than roughly 0.2–0.3 s**. Spot moves in the last 0.5 s before a Kalshi poll are already in Kalshi's book at that poll; spot moves in the 0.5 s after the poll are not. Point estimate: TrueFX ahead by ~0.05–0.1 s, which is inside the clock-offset uncertainty.

## 1. Data integrity (raw files)

- Epochs are consistent: TrueFX `ts_ms` is Unix ms (first row 23:56:55.056 UTC), local clocks Unix s; no timezone mix-up. Kalshi `close_time` 00:00:00Z = local 1791936000 matches the logged rolls.
- 948 TrueFX rows, 0 duplicate `(pair, ts_ms)`, monotone per pair. Kalshi: 526 × 200, 9 × 429. Book states ok 490 / empty_side 35 / empty 1. All as reported.
- Per-market poll gap: median **2.60 s** (4:57–5:00), **5.59 s** (5:00–5:15), **6.76 s** (5:15–5:17). Best-level churn 71–82% of polls; fair ≥ 2 c on 19–36%. Matches.
- TrueFX mid granularity in this hour: moves of 0.05–0.3 pip per update; **zero** tick-to-tick jumps ≥ 1 pip in either pair. A 1-pip threshold is 5–20 ticks of drift, which is why only 3 events exist.

## 2. Clock offset (recv − TrueFX stamp on freshest rows)

d = local_recv − ts: min −0.032 s, p01 −0.028, p05 −0.011 (pooled, n = 945); RTT/2 = 0.028 s. So **our clock trails TrueFX's by ~0.057–0.061 s**.

**Sign error in the capture report.** It says the skew "biases 'TrueFX first' slightly in TrueFX's favour." It is the opposite: TrueFX stamps are *late* in our clock, so uncorrected leads are **understated** by ~60 ms. Correcting shifts the two matched leads from 0.394 → 0.451 s and 3.473 → 3.529 s. Magnitude is trivial vs the poll gap, but the direction stated was wrong.

No look-ahead found in `analyze.py`: `mid_at` uses stamps ≤ detect time (the offset makes it slightly *conservative*); event time and reprice time are in different clocks but the only consequence is the 60 ms above. One caveat for a trading reading: TrueFX quotes were *received* 0.15–0.19 s (median) after their stamp, so "lead vs our recv" is the actionable number.

## 3. Events re-derived (Mode A, any best-level change)

| Event (PT, offset-corrected) | Move | Next reprice | Lead (detect) | Floor | Class |
|---|---|---|---|---|---|
| 5:00:19.757 PM GBP | −1.0 pip | none ≤ 10 s | – | – | **roll-gap artifact** (new GBP market not polled until 5:00:23) — should be dropped |
| 5:02:02.216 PM GBP | +1.1 pip | 5:02:02.667 (0.055 → 0.11) | +0.451 s | −2.78 s | ambiguous |
| 5:05:30.491 PM GBP | +1.2 pip | 5:05:34.020 (0.205 → 0.42) | +3.529 s | −2.08 s | ambiguous |

EUR/USD: 0 events. Mode B (fair ≥ 2 c, same direction): 3 events, 1 matched (5:05:30, +3.53 s), EUR 5:01:31.7 saw an opposite-direction move at +16.6 s and same-direction at +19.8 s. **All identical to the capture report** up to the 57 ms offset. No double counting (the `pending` flag gives one event per inter-reprice gap).

Corrected event count: **2 usable events, 0 resolved, 2 ambiguous within one poll interval, 0 "Kalshi-first."** The capture report's "33% Kalshi-first" is a construction artifact: the "nearest reprice before the event" is *always* the reprice that set the reference. For 5:05:30 it was a 1-cent yes-bid downtick (0.20 → 0.19, fair 0.21 → 0.205) in the *opposite* direction of the subsequent +1.2 pip rally, not Kalshi anticipating anything. Tick-level view of that event: Kalshi poll 5:05:28.41 fair 0.205; TrueFX 1.32560 → 1.32561 → 1.325645 → 1.325685 → 1.325715 over 5:05:28.65–5:05:30.49; next Kalshi poll 5:05:34.02 fair 0.42. Kalshi changed somewhere in a 5.6 s window that straddles the whole spot move. Unresolvable.

## 4. Is "lead ≥ 0.5 s" measurable under this polling? No — it is biased, not just noisy

Measured lead = true lead + detection delay, and the detection delay is ~Uniform(0, poll gap). With the 520 observed gaps (mean 4.43 s):
- If Kalshi moved **at the same instant** as TrueFX: P(measured lead ≥ 0.5 s) = **87%**.
- If Kalshi moved **0.5 s *before*** TrueFX: still **74%**.
- Expected upward bias of every measured lead: **+2.2 s**. At the intended 1 s cadence it would still be +0.5 s with P(≥ 0.5 s | simultaneous) = 50%.

So the "1/2 of matched events had lead ≥ 0.5 s" line carries no information. The capture agent correctly flagged this as a floor; the correction is that the statistic is *biased toward TrueFX-first*, not merely coarse.

## 5. What the data *can* resolve: within-interval timing (n = 433 intervals, 4 big markets, last 30 s before expiry excluded)

Sliding-window cross-correlation of Δfair with Δspot shifted by τ: pooled peak at **τ = 0.00 s**, r = 0.647; r within 0.05 of peak only for τ ∈ [0, +0.25 s]; block-bootstrap (200×) puts the peak at 0 in 94% and +0.25 in 6%, never ≥ 0.5. But a lag-0 peak over a 2.6–5.6 s window can't separate "Kalshi first inside the interval" from "TrueFX first inside the interval," so:

OLS of Δfair_i (z-scored per market) on TrueFX moves in time bins relative to poll P_i:

| Bin (relative to poll) | coef on Δfair_i (t) | coef on Δfair_{i+1} (t) |
|---|---|---|
| A: start … −2 s | +4.17 (14.4) | −0.05 (−0.2) |
| B: −2 … −1 s | +2.02 (4.0) | +0.04 (0.1) |
| C: −1 … −0.5 s | +4.34 (7.3) | +0.13 (0.2) |
| **D: −0.5 … 0 s (last half-second before poll)** | **+3.32 (5.0)** | +0.67 (0.9) |
| **E: 0 … +0.5 s (first half-second after poll)** | **+0.29 (0.4)** | +4.13 (4.8) |
| F: +0.5 … +1 s | −0.16 (−0.3) | +3.93 (5.4) |
| G: +1 … +2 s | −0.27 (−0.5) | +3.33 (5.9) |

Reading: a spot move in the last 0.5 s before Kalshi was polled is already ~83% reflected in Kalshi's book at that poll (3.32 vs 0.67 spillover) → Kalshi's lag behind TrueFX ≈ 0.5 × 17% ≈ **0.08 s**, upper ~2-SE bound ≈ **0.3 s**. A spot move in the 0.5 s *after* the poll is ~7% reflected (0.29 vs 4.13) → Kalshi's lead over TrueFX ≈ **0.03 s**, upper bound ≈ **0.2 s**. Stable across clock offsets 0 / −0.057 / −0.10 s (bin D stays +3.2 to +3.3, bin E stays t < 1). Same picture in the per-bin sign test (bins A–C: 83–94% same-sign in the same interval; E–G: 78–90% same-sign in the *next* interval; bin D n = 8, too small).

Reverse baseline re-derived: TrueFX mid changed inside the interval on 65% of fair ≥ 2 c polls vs 34–39% of fair < 2 c polls (capture agent: 71/66% vs 40/47%; same message, differences from the offset shift and dropping no-fair rows).

## 6. Corrected numbers in one place

- Events: 2 usable (not 3); matched 2; TrueFX-first resolved 0%; ambiguous 100%; Kalshi-first 0% (the 33% was an artifact).
- Leads (offset-corrected): 0.45 s and 3.53 s, both with negative floor; expected bias of these numbers +1.3 to +2.8 s (half the gap at the time).
- Clock: our clock − TrueFX clock ≈ −0.06 s; uncorrected leads understated by 60 ms (bias *against* TrueFX-first, not for it).
- Lead/lag bound from within-interval regression: |lead| ≲ 0.2–0.3 s either direction; point estimate TrueFX ahead ~0.05–0.1 s, within clock uncertainty.
- Settlement cross-check confirmed: both 5:15 PM markets YES; TrueFX mid 1.5 s before close 1.12039 / 1.32594 vs Pyth 1.12038 / 1.32594.

## Verdict for the owner (plain words)

In this 20-minute look, no: the real FX price does not visibly move before Kalshi reprices. The three "events" the original method found are two usable ones and one artifact, and the method itself was rigged by the 2.6–6.5 s polling gap to call almost anything "TrueFX first" (even a simultaneous move would have scored "lead ≥ 0.5 s" 87% of the time), so its lead numbers should be ignored rather than read as weak evidence. Using the half-second resolution of the TrueFX feed to see where inside each Kalshi poll gap the spot move happened, Kalshi's book already reflects spot moves that occurred within the last half-second before we looked, and does not reflect moves that came after — so whatever lag exists between TrueFX and Kalshi's best levels is a few tenths of a second at most, in either direction, and after adding our ~0.06 s clock skew, ~0.15 s TrueFX quote age and ~0.06 s request latency there is nothing left to act on from a public REST poll. How much to trust this: it is one quiet hour (23:57–00:17 UTC, 5–6 pip range, 0.05–0.3 pip ticks), two pairs, one aggregator (TrueFX, not Pyth, which is what Kalshi settles on), thin books that get pulled near expiry, a shared egress IP that drew nine 429s, and a bound of "≤ 0.3 s" rather than a measurement of zero. It is a plumbing check that says the obvious free-feed edge is not sitting there in calm conditions; it says nothing about busy hours, news spikes, or whether a true Pyth feed at millisecond resolution would show a sub-100 ms gap. The 2-weekday study is still needed, and it should use the within-interval regression (or a WebSocket book feed) rather than the reset-reference event statistic.
